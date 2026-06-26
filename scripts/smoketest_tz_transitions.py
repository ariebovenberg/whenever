"""Compare Whenever's timezone transitions against ``zdump -i``.

Requires tzcode 2026b. On macOS, install it with ``brew install tzdb``.
"""

from __future__ import annotations

import argparse
import ast
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import whenever
from whenever import (
    Instant,
    available_timezones,
    clear_tzcache,
    reset_tzpath,
)

ZDUMP_VERSION = "zdump (tzcode) 2026b"


def parse_offset(value: str) -> int:
    sign = -1 if value[0] == "-" else 1
    digits = value[1:]
    if len(digits) not in (2, 4, 6) or not digits.isdigit():
        raise ValueError(f"unexpected zdump offset: {value!r}")
    hours = int(digits[:2])
    minutes = int(digits[2:4] or 0)
    seconds = int(digits[4:6] or 0)
    return sign * (hours * 3_600 + minutes * 60 + seconds)


def parse_local_timestamp(date: str, time: str) -> int:
    components = [int(part) for part in time.split(":")]
    components.extend([0] * (3 - len(components)))
    year, month, day = map(int, date.split("-"))
    value = datetime(
        year,
        month,
        day,
        *components,
        tzinfo=timezone.utc,
    )
    return int(value.timestamp())


def parse_zdump_rows(
    path: Path, rows: list[list[str]]
) -> tuple[int, list[tuple[int, int]]]:
    if not rows or rows[0][:2] != ["-", "-"]:
        raise ValueError(f"unexpected zdump output for {path}")

    initial_offset = parse_offset(rows[0][2])
    transitions = []
    previous_offset = initial_offset
    for row in rows[1:]:
        offset = parse_offset(row[2])
        local_timestamp = parse_local_timestamp(row[0], row[1])
        if offset != previous_offset:
            transitions.append((local_timestamp - offset, offset))
        previous_offset = offset
    return initial_offset, transitions


def zdump_transitions(
    paths: list[Path], start_year: int, end_year: int
) -> dict[Path, tuple[int, list[tuple[int, int]]]]:
    result = subprocess.run(
        [
            "zdump",
            "-i",
            "-c",
            f"{start_year},{end_year}",
            *map(str, paths),
        ],
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    )
    rows_by_path: dict[Path, list[list[str]]] = {}
    current_path = None
    for line in result.stdout.splitlines():
        if line.startswith("TZ="):
            current_path = Path(ast.literal_eval(line[3:]))
            rows_by_path[current_path] = []
        elif line:
            if current_path is None:
                raise ValueError("unexpected zdump output")
            rows_by_path[current_path].append(line.split())

    if rows_by_path.keys() != set(paths):
        raise ValueError("zdump did not return all requested timezones")
    return {
        path: parse_zdump_rows(path, rows)
        for path, rows in rows_by_path.items()
    }


def all_zdump_transitions(
    paths: list[Path], start_year: int, end_year: int, workers: int
) -> dict[Path, tuple[int, list[tuple[int, int]]]]:
    chunks = [paths[i::workers] for i in range(workers)]
    with ThreadPoolExecutor(max_workers=workers) as executor:
        results = executor.map(
            lambda chunk: zdump_transitions(chunk, start_year, end_year),
            filter(None, chunks),
        )
    return {
        path: transitions
        for result in results
        for path, transitions in result.items()
    }


def tzdata_path() -> Path | None:
    try:
        import tzdata.zoneinfo
    except ImportError:
        return None
    return Path(tzdata.zoneinfo.__path__[0]).resolve()


def find_tzif(key: str, paths: tuple[Path, ...]) -> Path | None:
    return next(
        (candidate for base in paths if (candidate := base / key).is_file()),
        None,
    )


def next_offset_transition(cursor):
    while (transition := cursor.next_transition()) is not None:
        if transition.offset != cursor.offset:
            return transition
        # zdump -i omits transitions that only change metadata.
        cursor = transition
    return None


def check_database(
    label: str,
    paths: tuple[Path, ...],
    start_year: int,
    end_year: int,
    workers: int,
) -> tuple[int, int]:
    start = Instant.from_utc(start_year, 1, 1)
    end_timestamp = Instant.from_utc(end_year, 1, 1).timestamp()
    transition_count = 0
    zones = sorted(available_timezones())
    tzif_paths = []
    for key in zones:
        tzif_path = find_tzif(key, paths)
        if tzif_path is None:
            raise AssertionError((label, key, paths))
        tzif_paths.append(tzif_path)
    expected_by_path = all_zdump_transitions(
        tzif_paths, start_year, end_year, workers
    )

    for key, tzif_path in zip(zones, tzif_paths):
        initial_offset, expected = expected_by_path[tzif_path]
        cursor = start.to_tz(key)
        actual_initial = cursor.offset.total("seconds")
        assert actual_initial == initial_offset, (
            label,
            key,
            start,
            actual_initial,
            initial_offset,
        )

        previous_offset = initial_offset
        for expected_timestamp, expected_offset in expected:
            transition = next_offset_transition(cursor)
            assert transition is not None, (
                label,
                key,
                expected_timestamp,
            )
            actual_timestamp = transition.timestamp()
            assert actual_timestamp == expected_timestamp, (
                label,
                key,
                actual_timestamp,
                expected_timestamp,
            )
            before = Instant.from_timestamp(actual_timestamp - 1).to_tz(key)
            assert before.offset.total("seconds") == previous_offset, (
                label,
                key,
                before,
                previous_offset,
            )
            assert transition.offset.total("seconds") == expected_offset, (
                label,
                key,
                transition,
                expected_offset,
            )
            previous_offset = expected_offset
            cursor = transition
            transition_count += 1

        extra = next_offset_transition(cursor)
        assert extra is None or extra.timestamp() >= end_timestamp, (
            label,
            key,
            extra,
            end_year,
        )

    return len(zones), transition_count


def check_system_database(
    start_year: int, end_year: int, workers: int
) -> tuple[int, int]:
    reset_tzpath()
    clear_tzcache()
    paths = tuple(Path(path).resolve() for path in whenever.TZPATH)
    if tzdata := tzdata_path():
        paths += (tzdata,)
    return check_database(
        "system database", paths, start_year, end_year, workers
    )


def check_tzdata_database(
    start_year: int, end_year: int, workers: int
) -> tuple[int, int] | None:
    if (path := tzdata_path()) is None:
        return None
    reset_tzpath([])
    clear_tzcache()
    return check_database(
        "tzdata package", (path,), start_year, end_year, workers
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-year", type=int, default=1900)
    parser.add_argument("--end-year", type=int, default=2051)
    parser.add_argument(
        "--workers", type=int, default=min(os.cpu_count() or 1, 8)
    )
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers must be positive")

    version = subprocess.run(
        ["zdump", "--version"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    ).stdout.strip()
    assert version == ZDUMP_VERSION, (version, ZDUMP_VERSION)

    system_zones, system_transitions = check_system_database(
        args.start_year, args.end_year, args.workers
    )
    print(
        "System database: checked "
        f"{system_transitions:,} transitions in {system_zones} zones"
    )

    tzdata_result = check_tzdata_database(
        args.start_year, args.end_year, args.workers
    )
    if tzdata_result is None:
        print("tzdata package not installed; skipping")
    else:
        tzdata_zones, tzdata_transitions = tzdata_result
        print(
            "tzdata package: checked "
            f"{tzdata_transitions:,} transitions in {tzdata_zones} zones"
        )


if __name__ == "__main__":
    main()
