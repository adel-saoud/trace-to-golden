"""Keep the pinned copies of cross-repo contracts identical to their producer's file.

trace-to-golden validates its exports against llm-regression-detector's golden
dataset JSON Schema. The producer owns that file; this repo keeps a byte-for-byte
copy pinned to a released tag, so a schema change reaches this repo only through
an explicit pin bump and a CHANGELOG entry.

    uv run python scripts/sync_schemas.py           # rewrite the local copies
    uv run python scripts/sync_schemas.py --check   # exit 1 if a copy has drifted

Locally the canonical file is read from the sibling checkout (`../<repo>`), the
release the maintainer is about to tag. In CI (`CI` is set, as GitHub Actions does)
or without a sibling it is read from the raw GitHub URL at the pinned tag, so CI
proves the copy matches what was actually released. That URL returns 404 until the
tag is pushed, and the check fails rather than skipping.
"""

from __future__ import annotations

import argparse
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Contract:
    """One file owned by another repo and copied here at a pinned release tag."""

    repository: str
    tag: str
    source_path: str
    local_path: Path

    @property
    def sibling(self) -> Path:
        """Producer checkout next to this repo, as in the maintainer's workspace."""
        return ROOT.parent / self.repository.split("/")[1]

    @property
    def url(self) -> str:
        """Raw file at the pinned tag; a tag never moves, so the content is fixed."""
        return (
            f"https://raw.githubusercontent.com/{self.repository}/refs/tags/{self.tag}/"
            f"{self.source_path}"
        )


CONTRACTS = (
    Contract(
        repository="adel-saoud/llm-regression-detector",
        tag="v0.2.0",
        source_path="schemas/golden-dataset.v2.schema.json",
        local_path=ROOT / "tests" / "fixtures" / "golden-dataset.v2.schema.json",
    ),
)


class SourceUnavailableError(Exception):
    """The canonical file could not be read, so the copy cannot be checked."""


def canonical_bytes(contract: Contract) -> tuple[bytes, str]:
    """The producer's file and where it came from."""
    path = contract.sibling / contract.source_path
    if not os.environ.get("CI") and path.is_file():
        return path.read_bytes(), str(path)
    try:
        # S310 guards against file:// URLs; `Contract.url` is always https.
        with urllib.request.urlopen(contract.url, timeout=30) as response:  # noqa: S310
            return response.read(), contract.url
    except urllib.error.URLError as error:
        raise SourceUnavailableError(
            f"cannot read {contract.url} ({error}). Is tag {contract.tag} pushed to "
            f"{contract.repository}?"
        ) from error


def main() -> int:
    """Sync or check every contract; return the process exit code."""
    parser = argparse.ArgumentParser(description="Sync pinned contract copies.")
    parser.add_argument("--check", action="store_true", help="fail on drift instead of rewriting")
    args = parser.parse_args()
    drifted = 0
    for contract in CONTRACTS:
        try:
            expected, origin = canonical_bytes(contract)
        except SourceUnavailableError as error:
            print(f"ERROR   {error}", file=sys.stderr)
            return 2
        local = contract.local_path
        relative = local.relative_to(ROOT)
        if local.is_file() and local.read_bytes() == expected:
            print(f"ok      {relative} == {contract.repository}@{contract.tag}")
            continue
        if args.check:
            drifted += 1
            print(
                f"DRIFT   {relative} differs from {origin}. "
                "Run `uv run python scripts/sync_schemas.py`, then note it in CHANGELOG.md.",
                file=sys.stderr,
            )
            continue
        local.write_bytes(expected)
        print(f"synced  {relative} <- {origin}")
    return 1 if drifted else 0


if __name__ == "__main__":
    sys.exit(main())
