"""`ttg` command line: ingest, triage, review, export, and an offline demo."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from trace_to_golden import pipeline, review
from trace_to_golden.config import RedactorName, Settings
from trace_to_golden.export.regression_detector import DatasetSchema, ExportResult
from trace_to_golden.models import GoldenCandidate, ReviewStatus, TraceSource
from trace_to_golden.redact import build_redactor
from trace_to_golden.store import Store

app = typer.Typer(
    no_args_is_help=True,
    help="Turn production LLM traces into reviewed, PII-free golden eval cases.",
)
console = Console()

DbOption = Annotated[
    Path | None,
    typer.Option("--db", help="SQLite store. Default: TTG_DB_PATH or ./trace_to_golden.db."),
]


def _load_settings(db: Path | None, redactor: RedactorName | None = None) -> Settings:
    """Settings from `TTG_*` variables, with any flag the user passed taking precedence.

    A bad or unknown variable exits with code 2 and the validation message
    instead of a traceback.
    """
    overrides: dict[str, object] = {}
    if db is not None:
        overrides["db_path"] = db
    if redactor is not None:
        overrides["redactor"] = redactor
    try:
        return Settings.model_validate(overrides)
    except ValidationError as error:
        messages = "; ".join(str(e["msg"]).removeprefix("Value error, ") for e in error.errors())
        console.print(f"[red]Invalid settings:[/red] {messages}", soft_wrap=True)
        raise typer.Exit(code=2) from None


def _queue_table(candidates: list[GoldenCandidate]) -> Table:
    """One row per candidate, with the question cut to fit a terminal line."""
    table = Table("record id", "status", "flags", "topic", "input")
    for c in candidates:
        table.add_row(
            c.record_id, c.status, ", ".join(c.flags) or "-", c.topic or "-", c.input_text[:70]
        )
    return table


@app.command()
def ingest(
    paths: Annotated[list[Path], typer.Argument(exists=True, dir_okay=False)],
    source: Annotated[TraceSource, typer.Option(help="Export format of the files.")] = (
        TraceSource.OTEL
    ),
    redactor: Annotated[
        RedactorName | None, typer.Option(help="presidio (default) or regex (light mode).")
    ] = None,
    db: DbOption = None,
) -> None:
    """Read trace exports, redact PII, and store the result."""
    settings = _load_settings(db, redactor)
    report = pipeline.ingest(
        paths,
        source,
        store=Store(settings.db_path),
        redactor=build_redactor(settings),
        settings=settings,
    )
    entities = ", ".join(f"{k}={v}" for k, v in sorted(report.redacted_entities.items()))
    console.print(
        f"Read {report.records_read} records, stored {report.records_new} new. "
        f"Redacted: {entities or 'nothing'}."
    )


@app.command()
def triage(db: DbOption = None) -> None:
    """Cluster and flag stored traces, then queue candidates for review."""
    settings = _load_settings(db)
    report = pipeline.triage(Store(settings.db_path), settings)
    console.print(
        f"{report.traces} traces, {report.clusters} clusters, {report.flagged} flagged, "
        f"{report.enqueued} new candidates queued."
    )


@app.command()
def queue(
    status: Annotated[ReviewStatus | None, typer.Option(help="Filter by status.")] = None,
    db: DbOption = None,
) -> None:
    """List review candidates."""
    candidates = Store(_load_settings(db).db_path).candidates(status)
    console.print(_queue_table(candidates))


@app.command()
def approve(
    record_id: str,
    category: Annotated[str | None, typer.Option(help="Expected category.")] = None,
    reference_answer: Annotated[str | None, typer.Option(help="Replace the traced answer.")] = None,
    rubric: Annotated[
        list[str] | None,
        typer.Option(help="A criterion a good answer must meet; repeat for several."),
    ] = None,
    input_text: Annotated[str | None, typer.Option(help="Replace the traced question.")] = None,
    db: DbOption = None,
) -> None:
    """Approve one candidate, with optional edits."""
    try:
        review.approve(
            Store(_load_settings(db).db_path),
            record_id,
            input_text=input_text,
            reference_answer=reference_answer,
            category=category,
            rubric=rubric,
        )
    except review.CandidateNotFoundError:
        console.print(f"[red]No candidate {record_id}[/red]")
        raise typer.Exit(code=1) from None
    console.print(f"Approved {record_id}.")


@app.command()
def reject(
    record_id: str,
    reason: Annotated[str, typer.Option(help="Why this trace is not a golden case.")],
    db: DbOption = None,
) -> None:
    """Reject one candidate."""
    try:
        review.reject(Store(_load_settings(db).db_path), record_id, reason=reason)
    except review.CandidateNotFoundError:
        console.print(f"[red]No candidate {record_id}[/red]")
        raise typer.Exit(code=1) from None
    console.print(f"Rejected {record_id}.")


def _prompt_rubric(candidate: GoldenCandidate) -> list[str]:
    """Rubric criteria typed one per line until a blank line; none typed keeps the current ones."""
    if candidate.rubric:
        console.print("Current rubric: " + "; ".join(candidate.rubric))
    criteria: list[str] = []
    while criterion := typer.prompt("Rubric criterion (blank to finish)", default=""):
        criteria.append(criterion)
    return criteria


def _print_export_result(result: ExportResult, out: Path) -> None:
    """Say what was written and why each approved candidate was left out."""
    if result.cases:
        console.print(f"Wrote {len(result.cases)} cases ({result.schema}) to {out}.")
    else:
        console.print(f"[yellow]No case to export; {out} not written.[/yellow]")
    for record_id, reason in result.skipped.items():
        console.print(f"  skipped {record_id}: {reason}")


@app.command("review")
def review_loop(db: DbOption = None) -> None:
    """Walk through pending candidates: approve, edit, reject, skip or quit."""
    store = Store(_load_settings(db).db_path)
    pending = store.candidates(ReviewStatus.PENDING)
    for index, candidate in enumerate(pending, start=1):
        console.print(
            Panel(
                f"[bold]Question[/bold]\n{candidate.input_text}\n\n"
                f"[bold]Traced answer[/bold]\n{candidate.reference_answer}\n\n"
                f"flags: {', '.join(candidate.flags) or '-'}   topic: {candidate.topic or '-'}",
                title=f"{index}/{len(pending)}  {candidate.record_id}",
            )
        )
        choice = typer.prompt("[a]pprove, [e]dit, [r]eject, [s]kip, [q]uit", default="s")
        if choice == "q":
            break
        if choice == "r":
            reason = typer.prompt("Reason")
            review.reject(store, candidate.record_id, reason=reason)
        elif choice in {"a", "e"}:
            category = typer.prompt("Category", default=candidate.category or "")
            answer, rubric = None, None
            if choice == "e":
                answer = typer.prompt("Reference answer", default=candidate.reference_answer)
                rubric = _prompt_rubric(candidate)
            review.approve(
                store,
                candidate.record_id,
                category=category or None,
                reference_answer=answer,
                rubric=rubric,
            )
    console.print("Review session ended.")


@app.command()
def export(
    out: Annotated[Path, typer.Option(help="Dataset file to write.")],
    existing: Annotated[
        Path | None, typer.Option(exists=True, help="Current golden dataset, for dedupe.")
    ] = None,
    schema: Annotated[DatasetSchema, typer.Option(help="Target dataset schema.")] = (
        DatasetSchema.V2
    ),
    db: DbOption = None,
) -> None:
    """Export approved candidates in the llm-regression-detector format."""
    settings = _load_settings(db)
    result = pipeline.export(
        Store(settings.db_path), settings, out_path=out, existing_dataset=existing, schema=schema
    )
    _print_export_result(result, out)


@app.command()
def demo(
    workdir: Annotated[Path, typer.Option(help="Folder for the demo store and output.")] = Path(
        "out/demo"
    ),
    redactor: Annotated[RedactorName | None, typer.Option(help="presidio or regex.")] = None,
) -> None:
    """Run the full pipeline offline on the bundled synthetic traces.

    Candidates are auto-approved with their cluster topic as category, which a
    person does by hand in real use. `scripts/reproduce.py` measures the same run.
    """
    report = pipeline.run_demo(workdir, _load_settings(None, redactor))
    for name, ingested in report.ingest.items():
        console.print(
            f"{name}: {ingested.records_new} records, redacted {dict(ingested.redacted_entities)}"
        )
    console.print(
        f"Triage: {report.triage.clusters} clusters, {report.triage.flagged} flagged, "
        f"{report.triage.enqueued} candidates."
    )
    console.print(_queue_table(report.queued))
    _print_export_result(report.export, report.out_path)
