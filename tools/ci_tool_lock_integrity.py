"""Verify direct CI tool pins stay synchronized with compiled hash locks."""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

DIRECT_PIN_RE = re.compile(
    r"^(?P<name>[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)"
    r"==(?P<version>[^\s;\\]+)$"
)
INPUT_REFERENCE_RE = re.compile(r"#\s+(?:via\s+)?-r\s+(?P<path>\S+)")


class LockIntegrityError(ValueError):
    """Raised when a lock source and compiled lock do not match."""


@dataclass(frozen=True)
class LockedPin:
    name: str
    version: str
    line_number: int
    block: tuple[str, ...]

    @property
    def has_sha256_hash(self) -> bool:
        return any("--hash=sha256:" in line for line in self.block)

    @property
    def input_references(self) -> tuple[str, ...]:
        return tuple(
            match.group("path")
            for line in self.block
            if (match := INPUT_REFERENCE_RE.search(line)) is not None
        )


def _normalize_project_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _parse_pin(text: str, *, path: Path, line_number: int) -> tuple[str, str]:
    pin_text = text.split(";", 1)[0].removesuffix("\\").strip()
    match = DIRECT_PIN_RE.fullmatch(pin_text)
    if match is None:
        raise LockIntegrityError(
            f"{path}:{line_number}: expected an exact NAME==VERSION pin, got {text!r}"
        )
    return match.group("name"), match.group("version")


def read_direct_input_pins(path: Path) -> dict[str, tuple[str, str]]:
    pins: dict[str, tuple[str, str]] = {}
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        name, version = _parse_pin(line, path=path, line_number=line_number)
        normalized = _normalize_project_name(name)
        if normalized in pins:
            raise LockIntegrityError(
                f"{path}:{line_number}: duplicate direct pin for {normalized}"
            )
        pins[normalized] = (name, version)
    if not pins:
        raise LockIntegrityError(f"{path}: no direct pins found")
    return pins


def read_compiled_lock_pins(path: Path) -> list[LockedPin]:
    entries: list[LockedPin] = []
    current_name: str | None = None
    current_version: str | None = None
    current_line = 0
    current_block: list[str] = []

    def append_current() -> None:
        if current_name is None or current_version is None:
            return
        entries.append(
            LockedPin(
                name=current_name,
                version=current_version,
                line_number=current_line,
                block=tuple(current_block),
            )
        )

    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if raw_line and not raw_line[0].isspace() and not raw_line.startswith("#"):
            append_current()
            current_name, current_version = _parse_pin(
                raw_line, path=path, line_number=line_number
            )
            current_line = line_number
            current_block = [raw_line]
        elif current_name is not None:
            current_block.append(raw_line)
    append_current()

    if not entries:
        raise LockIntegrityError(f"{path}: no compiled pins found")
    return entries


def _reference_matches_input(reference: str, input_path: Path) -> bool:
    return Path(reference).resolve() == input_path.resolve()


def validate_lock_pair(input_path: Path, lock_path: Path) -> None:
    input_pins = read_direct_input_pins(input_path)
    lock_entries = read_compiled_lock_pins(lock_path)
    direct_lock_pins: dict[str, LockedPin] = {}

    for entry in lock_entries:
        if not any(
            _reference_matches_input(reference, input_path)
            for reference in entry.input_references
        ):
            continue
        normalized = _normalize_project_name(entry.name)
        if normalized in direct_lock_pins:
            raise LockIntegrityError(
                f"{lock_path}:{entry.line_number}: duplicate compiled direct pin for "
                f"{normalized}"
            )
        direct_lock_pins[normalized] = entry

    missing = sorted(input_pins.keys() - direct_lock_pins.keys())
    extra = sorted(direct_lock_pins.keys() - input_pins.keys())
    problems: list[str] = []
    if missing:
        problems.append(f"missing compiled direct pins: {', '.join(missing)}")
    if extra:
        problems.append(f"stale compiled direct pins: {', '.join(extra)}")

    for normalized in sorted(input_pins.keys() & direct_lock_pins.keys()):
        input_name, input_version = input_pins[normalized]
        lock_entry = direct_lock_pins[normalized]
        if lock_entry.version != input_version:
            problems.append(
                f"{input_name} input version {input_version} != compiled version "
                f"{lock_entry.version}"
            )
        if not lock_entry.has_sha256_hash:
            problems.append(
                f"compiled direct pin {input_name}=={input_version} has no SHA256 hash"
            )

    if problems:
        raise LockIntegrityError(f"{input_path} -> {lock_path}: " + "; ".join(problems))


def validate_requirement_directory(requirements_dir: Path) -> list[tuple[Path, Path]]:
    input_paths = sorted(requirements_dir.glob("ci-*.in"))
    lock_paths = sorted(requirements_dir.glob("ci-*.txt"))
    inputs_by_stem = {path.stem: path for path in input_paths}
    locks_by_stem = {path.stem: path for path in lock_paths}

    missing_locks = sorted(inputs_by_stem.keys() - locks_by_stem.keys())
    orphan_locks = sorted(locks_by_stem.keys() - inputs_by_stem.keys())
    if missing_locks or orphan_locks:
        details: list[str] = []
        if missing_locks:
            details.append(f"missing .txt locks: {', '.join(missing_locks)}")
        if orphan_locks:
            details.append(f"orphan .txt locks: {', '.join(orphan_locks)}")
        raise LockIntegrityError(f"{requirements_dir}: " + "; ".join(details))
    if not inputs_by_stem:
        raise LockIntegrityError(f"{requirements_dir}: no ci-*.in lock sources found")

    pairs = [
        (inputs_by_stem[stem], locks_by_stem[stem]) for stem in sorted(inputs_by_stem)
    ]
    for input_path, lock_path in pairs:
        validate_lock_pair(input_path, lock_path)
    return pairs


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--requirements-dir",
        type=Path,
        default=Path(".github/requirements"),
        help="Directory containing paired ci-*.in and ci-*.txt files",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        pairs = validate_requirement_directory(args.requirements_dir)
    except (LockIntegrityError, OSError) as exc:
        print(f"CI tool lock integrity failed: {exc}", file=sys.stderr)
        return 2
    print(f"CI tool lock integrity passed: {len(pairs)} lock pair(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
