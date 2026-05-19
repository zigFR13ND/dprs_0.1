#!/usr/bin/env python3
"""Build read-only derived CSV tables from a raw demo export.

The script reads raw files from meta/events/ticks and writes only to a separate
``derived`` output directory plus an optional small debug pack. Raw files are
never modified.
"""

from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd

DEFAULT_INPUT_DIR = Path("output/recheck_raw_v1")
DERIVED_TABLES = ("players", "rounds", "kills", "damage", "shots", "bomb_events")
EXPLICIT_ID_COLUMNS = {
    "weapon_itemid",
    "weapon_fauxitemid",
    "weapon_originalowner_xuid",
    "weapon_original_owner_xuid",
    "active_weapon_original_owner",
    "active_weapon_original_owner_xuid",
    "entindex",
}


@dataclass(frozen=True)
class TableResult:
    name: str
    path: Path
    rows: int
    columns: list[str]


def read_csv_if_exists(path: Path) -> pd.DataFrame:
    """Read a CSV file if it exists, otherwise return an empty DataFrame."""
    if not path.exists():
        return pd.DataFrame()
    id_dtype_columns = {
        "steamid",
        "user_steamid",
        "attacker_steamid",
        "assister_steamid",
        *EXPLICIT_ID_COLUMNS,
    }
    return pd.read_csv(path, dtype={column: "string" for column in id_dtype_columns})


def normalize_steamid(value: object) -> str | pd.NA:
    """Normalize SteamID-like values that may have been parsed as floats."""
    if pd.isna(value):
        return pd.NA
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none"}:
        return pd.NA
    if text.endswith(".0"):
        text = text[:-2]
    # Pandas may stringify very large IDs read from older CSVs as 7.65612e+16.
    # Keep those values as-is instead of inventing precision that is already lost.
    return text


def normalize_steamid_columns(df: pd.DataFrame) -> pd.DataFrame:
    for column in df.columns:
        if column.endswith("steamid") or column == "steamid":
            df[column] = df[column].map(normalize_steamid).astype("string")
    return df


def is_identifier_column(column: str) -> bool:
    if column in EXPLICIT_ID_COLUMNS:
        return True
    lowered = column.lower()
    return (
        lowered.endswith("_steamid")
        or lowered.endswith("_xuid")
        or lowered.endswith("_id")
        or lowered.endswith("id")
        or lowered == "steamid"
    )


def normalize_identifier_columns(df: pd.DataFrame) -> pd.DataFrame:
    for column in df.columns:
        if is_identifier_column(column):
            df[column] = df[column].map(normalize_steamid).astype("string")
    return df


def select_existing(df: pd.DataFrame, preferred_columns: Iterable[str]) -> pd.DataFrame:
    columns = [column for column in preferred_columns if column in df.columns]
    remaining = [column for column in df.columns if column not in columns]
    return df[columns + remaining].copy()


def build_players(raw_dir: Path) -> pd.DataFrame:
    players = read_csv_if_exists(raw_dir / "meta" / "player_info.csv")
    if players.empty:
        return pd.DataFrame(columns=["player_id", "steamid", "name", "team_number"])
    players = normalize_steamid_columns(players.copy())
    players = select_existing(players, ["steamid", "name", "team_number"])
    players.insert(0, "player_id", range(1, len(players) + 1))
    return players


def unique_sorted_ticks(df: pd.DataFrame) -> list[int]:
    if df.empty or "tick" not in df.columns:
        return []
    ticks = (
        pd.to_numeric(df["tick"], errors="coerce")
        .dropna()
        .astype(int)
        .drop_duplicates()
    )
    return sorted(ticks.tolist())


def first_tick_in_range(
    ticks: list[int],
    start: int,
    stop: int | None,
    *,
    include_start: bool = True,
    include_stop: bool = False,
) -> int | pd.NA:
    for tick in ticks:
        after_start = tick >= start if include_start else tick > start
        before_stop = (
            True if stop is None else (tick <= stop if include_stop else tick < stop)
        )
        if after_start and before_stop:
            return tick
    return pd.NA


def build_rounds(raw_dir: Path) -> pd.DataFrame:
    prestart_ticks = unique_sorted_ticks(
        read_csv_if_exists(raw_dir / "events" / "round_prestart.csv")
    )
    freeze_end_ticks = unique_sorted_ticks(
        read_csv_if_exists(raw_dir / "events" / "round_freeze_end.csv")
    )
    officially_ended_ticks = unique_sorted_ticks(
        read_csv_if_exists(raw_dir / "events" / "round_officially_ended.csv")
    )

    rows: list[dict[str, object]] = []
    for index, prestart_tick in enumerate(prestart_ticks):
        next_prestart_tick = (
            prestart_ticks[index + 1] if index + 1 < len(prestart_ticks) else None
        )
        rows.append(
            {
                "round_number": index + 1,
                "prestart_tick": prestart_tick,
                "freeze_end_tick": first_tick_in_range(
                    freeze_end_ticks, prestart_tick, next_prestart_tick
                ),
                "officially_ended_tick": first_tick_in_range(
                    officially_ended_ticks,
                    prestart_tick,
                    next_prestart_tick,
                    include_start=False,
                    include_stop=True,
                ),
                "next_prestart_tick": (
                    next_prestart_tick if next_prestart_tick is not None else pd.NA
                ),
            }
        )
    return pd.DataFrame(
        rows,
        columns=[
            "round_number",
            "prestart_tick",
            "freeze_end_tick",
            "officially_ended_tick",
            "next_prestart_tick",
        ],
    )


def assign_round_numbers(df: pd.DataFrame, rounds: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "tick" not in df.columns or rounds.empty:
        df = df.copy()
        df.insert(0, "round_number", pd.NA)
        return df

    round_starts = rounds[
        ["round_number", "prestart_tick", "next_prestart_tick"]
    ].copy()
    ticks = pd.to_numeric(df["tick"], errors="coerce")
    round_numbers: list[object] = []
    for tick in ticks:
        if pd.isna(tick):
            round_numbers.append(pd.NA)
            continue
        tick_int = int(tick)
        matched = pd.NA
        for row in round_starts.itertuples(index=False):
            stop = row.next_prestart_tick
            if tick_int >= int(row.prestart_tick) and (
                pd.isna(stop) or tick_int < int(stop)
            ):
                matched = int(row.round_number)
                break
        round_numbers.append(matched)

    out = df.copy()
    out.insert(0, "round_number", round_numbers)
    return out


def build_kills(raw_dir: Path, rounds: pd.DataFrame) -> pd.DataFrame:
    kills = read_csv_if_exists(raw_dir / "events" / "player_death.csv")
    if kills.empty:
        return pd.DataFrame()
    kills = normalize_steamid_columns(kills.copy())
    kills = normalize_identifier_columns(kills)
    kills = assign_round_numbers(kills, rounds)
    preferred = [
        "round_number",
        "tick",
        "user_steamid",
        "user_name",
        "attacker_steamid",
        "attacker_name",
        "assister_steamid",
        "assister_name",
        "weapon",
        "headshot",
        "hitgroup",
        "distance",
        "dmg_health",
        "dmg_armor",
        "noscope",
        "thrusmoke",
        "penetrated",
        "attackerblind",
        "attackerinair",
    ]
    return select_existing(kills, preferred)


def build_damage(raw_dir: Path, rounds: pd.DataFrame) -> pd.DataFrame:
    damage = read_csv_if_exists(raw_dir / "events" / "player_hurt.csv")
    if damage.empty:
        return pd.DataFrame()
    damage = normalize_steamid_columns(damage.copy())
    damage = assign_round_numbers(damage, rounds)
    preferred = [
        "round_number",
        "tick",
        "user_steamid",
        "user_name",
        "attacker_steamid",
        "attacker_name",
        "weapon",
        "hitgroup",
        "dmg_health",
        "dmg_armor",
        "health",
        "armor",
    ]
    return select_existing(damage, preferred)


def build_shots(raw_dir: Path, rounds: pd.DataFrame) -> pd.DataFrame:
    shots = read_csv_if_exists(raw_dir / "events" / "weapon_fire.csv")
    if shots.empty:
        return pd.DataFrame()
    shots = normalize_steamid_columns(shots.copy())
    shots = assign_round_numbers(shots, rounds)
    preferred = [
        "round_number",
        "tick",
        "user_steamid",
        "user_name",
        "weapon",
        "silenced",
    ]
    return select_existing(shots, preferred)


def build_bomb_events(raw_dir: Path, rounds: pd.DataFrame) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for path in sorted((raw_dir / "events").glob("bomb_*.csv")):
        frame = read_csv_if_exists(path)
        if frame.empty and not path.exists():
            continue
        frame = normalize_steamid_columns(frame.copy())
        frame = normalize_identifier_columns(frame)
        frame.insert(0, "event_name", path.stem)
        frames.append(frame)
    if not frames:
        return pd.DataFrame()
    bomb_events = pd.concat(frames, ignore_index=True, sort=False)
    bomb_events = assign_round_numbers(bomb_events, rounds)
    preferred = [
        "round_number",
        "event_name",
        "tick",
        "user_steamid",
        "user_name",
        "site",
        "haskit",
        "entindex",
    ]
    return (
        select_existing(bomb_events, preferred)
        .sort_values(["tick", "event_name"], na_position="last")
        .reset_index(drop=True)
    )


def write_table(df: pd.DataFrame, name: str, output_dir: Path) -> TableResult:
    path = output_dir / f"{name}.csv"
    df.to_csv(path, index=False)
    return TableResult(name=name, path=path, rows=len(df), columns=list(df.columns))


def write_summary(results: list[TableResult], raw_dir: Path, output_dir: Path) -> None:
    summary = {
        "built_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "raw_input_directory": raw_dir.as_posix(),
        "derived_output_directory": output_dir.as_posix(),
        "tables": [
            {
                "name": result.name,
                "relative_path": result.path.relative_to(output_dir).as_posix(),
                "rows": result.rows,
                "columns": result.columns,
            }
            for result in results
        ],
        "raw_directories_left_read_only": ["meta", "events", "ticks", "errors"],
    }
    (output_dir / "derived_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def write_debug_pack(
    results: list[TableResult], output_dir: Path, debug_dir: Path, sample_rows: int
) -> None:
    if debug_dir.exists():
        shutil.rmtree(debug_dir)
    samples_dir = debug_dir / "samples"
    samples_dir.mkdir(parents=True, exist_ok=True)

    sample_entries: list[dict[str, object]] = []
    for result in results:
        table = pd.read_csv(output_dir / f"{result.name}.csv", dtype="string")
        sample_path = samples_dir / f"{result.name}_head_{sample_rows}.csv"
        table.head(sample_rows).to_csv(sample_path, index=False)
        sample_entries.append(
            {
                "table": result.name,
                "rows": result.rows,
                "columns": result.columns,
                "sample": sample_path.relative_to(debug_dir).as_posix(),
            }
        )

    summary = {
        "built_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source_derived_directory": output_dir.as_posix(),
        "sample_rows_per_table": sample_rows,
        "tables": sample_entries,
    }
    (debug_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def build_derived(
    raw_dir: Path, output_dir: Path, debug_dir: Path | None, sample_rows: int
) -> list[TableResult]:
    if not raw_dir.exists():
        raise FileNotFoundError(f"Raw input directory does not exist: {raw_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)

    players = build_players(raw_dir)
    rounds = build_rounds(raw_dir)
    tables = {
        "players": players,
        "rounds": rounds,
        "kills": build_kills(raw_dir, rounds),
        "damage": build_damage(raw_dir, rounds),
        "shots": build_shots(raw_dir, rounds),
        "bomb_events": build_bomb_events(raw_dir, rounds),
    }

    results = [write_table(tables[name], name, output_dir) for name in DERIVED_TABLES]
    write_summary(results, raw_dir, output_dir)
    if debug_dir is not None:
        write_debug_pack(results, output_dir, debug_dir, sample_rows)
    return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build derived demo tables without changing raw export files."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT_DIR,
        help="Raw export directory with meta/events/ticks/errors subdirectories.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Derived output directory. Defaults to <input>/derived.",
    )
    parser.add_argument(
        "--debug-pack",
        type=Path,
        default=Path("debug_pack/derived"),
        help="Small debug-pack directory with samples and summary. Use an empty value to disable.",
    )
    parser.add_argument(
        "--sample-rows",
        type=int,
        default=25,
        help="Number of rows per sample CSV in the debug pack.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = args.output or args.input / "derived"
    debug_dir = args.debug_pack if str(args.debug_pack) else None
    results = build_derived(args.input, output_dir, debug_dir, args.sample_rows)
    print(f"Built {len(results)} derived tables in {output_dir}")
    for result in results:
        print(f"- {result.name}: {result.rows} rows, {len(result.columns)} columns")


if __name__ == "__main__":
    main()
