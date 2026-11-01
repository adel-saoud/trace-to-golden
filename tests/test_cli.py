from __future__ import annotations

import json
import runpy
from pathlib import Path

import pytest
from typer.testing import CliRunner

from trace_to_golden.cli import app
from trace_to_golden.models import ReviewStatus
from trace_to_golden.store import Store

runner = CliRunner()


def _ingest_and_triage_samples(tmp_path: Path, samples: Path) -> Path:
    db = tmp_path / "cli.db"
    result = runner.invoke(
        app,
        ["ingest", str(samples / "otel_traces.jsonl"), "--redactor", "regex", "--db", str(db)],
    )
    assert result.exit_code == 0, result.output
    assert "Read 87 records, stored 87 new" in result.output
    result = runner.invoke(
        app,
        [
            "ingest",
            str(samples / "mlflow_traces.jsonl"),
            "--source",
            "mlflow",
            "--redactor",
            "regex",
            "--db",
            str(db),
        ],
    )
    assert result.exit_code == 0, result.output
    result = runner.invoke(app, ["triage", "--db", str(db)])
    assert result.exit_code == 0, result.output
    assert "candidates queued" in result.output
    return db


def test_ingest_triage_review_export(tmp_path: Path, samples: Path):
    db = _ingest_and_triage_samples(tmp_path, samples)
    store = Store(db)
    first, second, *_ = store.candidates()
    assert runner.invoke(app, ["queue", "--db", str(db), "--status", "pending"]).exit_code == 0

    result = runner.invoke(
        app,
        [
            "approve",
            first.record_id,
            "--category",
            "returns",
            "--rubric",
            "Says 30 days.",
            "--rubric",
            "Links the Orders page.",
            "--db",
            str(db),
        ],
    )
    assert result.exit_code == 0, result.output
    result = runner.invoke(app, ["reject", second.record_id, "--reason", "noise", "--db", str(db)])
    assert result.exit_code == 0, result.output
    for command in (["approve", "missing"], ["reject", "missing", "--reason", "x"]):
        assert runner.invoke(app, [*command, "--db", str(db)]).exit_code == 1

    out = tmp_path / "golden.json"
    existing = samples / "existing_golden.json"
    result = runner.invoke(
        app, ["export", "--out", str(out), "--existing", str(existing), "--db", str(db)]
    )
    assert result.exit_code == 0, result.output
    [case] = json.loads(out.read_text(encoding="utf-8"))["cases"]
    assert case["rubric"] == ["Says 30 days.", "Links the Orders page."]

    v1_out = tmp_path / "golden_v1.json"
    result = runner.invoke(app, ["export", "--out", str(v1_out), "--schema", "v1", "--db", str(db)])
    assert result.exit_code == 0, result.output
    assert len(json.loads(v1_out.read_text(encoding="utf-8"))) == 1


def test_review_loop(tmp_path: Path, samples: Path):
    db = _ingest_and_triage_samples(tmp_path, samples)
    store = Store(db)
    pending = store.candidates(ReviewStatus.PENDING)
    keys = (
        "a\nreturns\n"
        + "e\nrefund\nEdited answer.\nMust say 5 business days.\nOffers a label.\n\n"
        + "r\noff topic\n"
        + "s\n"
        + "q\n"
    )
    result = runner.invoke(app, ["review", "--db", str(db)], input=keys)
    assert result.exit_code == 0, result.output
    statuses = [store.candidate(c.record_id) for c in pending[:4]]
    assert [s.status if s else None for s in statuses] == [
        ReviewStatus.APPROVED,
        ReviewStatus.APPROVED,
        ReviewStatus.REJECTED,
        ReviewStatus.PENDING,
    ]
    edited = statuses[1]
    assert edited is not None
    assert (edited.reference_answer, edited.rubric) == (
        "Edited answer.",
        ("Must say 5 business days.", "Offers a label."),
    )


def test_demo_runs_offline(tmp_path: Path):
    workdir = tmp_path / "demo"
    workdir.mkdir()
    (workdir / "stale.txt").write_text("old", encoding="utf-8")
    result = runner.invoke(app, ["demo", "--workdir", str(workdir), "--redactor", "regex"])
    assert result.exit_code == 0, result.output
    assert not (workdir / "stale.txt").exists()
    cases = json.loads((workdir / "golden.json").read_text(encoding="utf-8"))["cases"]
    assert len(cases) > 10
    assert sum("reference_answer" in c for c in cases) > 10
    assert "skipped" in result.output


def test_settings_from_environment(tmp_path: Path, samples: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TTG_DB_PATH", str(tmp_path / "env.db"))
    monkeypatch.setenv("TTG_REDACTOR", "regex")
    result = runner.invoke(
        app, ["ingest", str(samples / "mlflow_traces.jsonl"), "--source", "mlflow"]
    )
    assert result.exit_code == 0, result.output
    assert (tmp_path / "env.db").exists()


def test_misspelled_environment_variable_exits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TTG_DB_PTH", str(tmp_path / "typo.db"))
    result = runner.invoke(app, ["triage", "--db", str(tmp_path / "t.db")])
    assert result.exit_code == 2
    assert "TTG_DB_PTH (did you mean TTG_DB_PATH?)" in result.output


def test_committed_samples_match_generator(tmp_path: Path, samples: Path):
    script = Path(__file__).resolve().parent.parent / "scripts" / "generate_samples.py"
    generate = runpy.run_path(str(script))["generate"]
    generate(tmp_path)
    for name in (
        "otel_traces.jsonl",
        "mlflow_traces.jsonl",
        "existing_golden.json",
        "pii_ground_truth.json",
    ):
        assert (tmp_path / name).read_text(encoding="utf-8") == (samples / name).read_text(
            encoding="utf-8"
        )


def test_export_with_nothing_approved_writes_no_file(tmp_path: Path):
    out = tmp_path / "golden.json"
    result = runner.invoke(app, ["export", "--out", str(out), "--db", str(tmp_path / "e.db")])
    assert result.exit_code == 0, result.output
    assert "No case to export" in result.output
    assert not out.exists()
