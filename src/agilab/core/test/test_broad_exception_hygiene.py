from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
CORE_SOURCE_ROOTS = (
    ROOT / "src/agilab/core/agi-env/src",
    ROOT / "src/agilab/core/agi-node/src",
    ROOT / "src/agilab/core/agi-cluster/src",
)
BROAD_EXCEPT_MARKER = "except Exception"
CLASSIFICATION_TOKENS = (
    "boundary",
    "defensive",
    "intentional",
    "worker code",
    "third-party",
    "best-effort",
    "log and re-raise",
    "persist the failure",
    "keep the queue alive",
)


def _nearby_classification(lines: list[str], line_index: int) -> str:
    start = max(0, line_index - 3)
    end = min(len(lines), line_index + 2)
    return " ".join(lines[start:end]).lower()


def test_core_broad_exception_handlers_are_classified() -> None:
    unclassified: list[str] = []
    for source_root in CORE_SOURCE_ROOTS:
        for path in sorted(source_root.rglob("*.py")):
            rel = path.relative_to(ROOT).as_posix()
            lines = path.read_text(encoding="utf-8").splitlines()
            for index, line in enumerate(lines):
                if BROAD_EXCEPT_MARKER not in line:
                    continue
                nearby = _nearby_classification(lines, index)
                if not any(token in nearby for token in CLASSIFICATION_TOKENS):
                    unclassified.append(f"{rel}:{index + 1}: {line.strip()}")

    assert unclassified == []
