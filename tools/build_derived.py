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
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd

DEFAULT_INPUT_DIR = Path("output/recheck_raw_v1")
ROUND_OUTCOME_DIAGNOSTICS: dict[str, int] = {}
PLAYER_ROUND_SIDE_DIAGNOSTICS: dict[str, int] = {
    "tick_data_rows": 0,
    "fallback_rows": 0,
}
PLAYER_ROUND_PARTICIPATION_DIAGNOSTICS: dict[str, object] = {
    "participation_source": "fallback_all_players",
    "tick_participation_rows": 0,
    "fallback_rows": 0,
    "filtered_rows": 0,
    "rounds_with_tick_participants": 0,
    "rounds_with_fallback_all_players": 0,
}
PLAYER_ROUND_SURVIVAL_DIAGNOSTICS: dict[str, int] = {
    "survived_source_ticks": 0,
    "survived_source_death_fallback": 0,
}

DERIVED_TABLES = (
    "players",
    "rounds",
    "round_outcomes",
    "kills",
    "damage",
    "shots",
    "weapon_actions",
    "bomb_events",
    "player_round_stats",
)

FIREARM_WEAPONS = {
    # Pistols
    "cz75a",
    "deagle",
    "elite",
    "fiveseven",
    "glock",
    "hkp2000",
    "p250",
    "revolver",
    "tec9",
    "usp_silencer",
    # Rifles
    "ak47",
    "aug",
    "famas",
    "galilar",
    "m4a1",
    "m4a1_silencer",
    "sg556",
    # SMGs
    "bizon",
    "mac10",
    "mp5sd",
    "mp7",
    "mp9",
    "p90",
    "ump45",
    # Shotguns
    "mag7",
    "nova",
    "sawedoff",
    "xm1014",
    # Snipers
    "awp",
    "g3sg1",
    "scar20",
    "ssg08",
    # Machine guns
    "m249",
    "negev",
}
WEAPON_FIRE_DIAGNOSTICS: dict[str, object] = {}
EXPLICIT_ID_COLUMNS = {
    "weapon_itemid",
    "weapon_fauxitemid",
    "weapon_originalowner_xuid",
    "weapon_original_owner_xuid",
    "active_weapon_original_owner",
    "active_weapon_original_owner_xuid",
    "entindex",
}
IDENTIFIER_DIAGNOSTICS: dict[str, dict[str, int]] = {}


def relative_path_or_posix(path: Path, base: Path) -> str:
    """Return a stable POSIX path relative to base when possible."""
    path = Path(path)
    base = Path(base)
    try:
        return path.relative_to(base).as_posix()
    except ValueError:
        pass
    try:
        return path.resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def debug_pack_source_path(path: Path, raw_dir: Path) -> str:
    """Return a debug-pack path relative to the raw export root where possible."""
    return relative_path_or_posix(path, raw_dir)


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
    """Normalize identifier values and avoid float/scientific notation artifacts."""
    if pd.isna(value):
        return pd.NA
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none"}:
        return pd.NA
    try:
        numeric = Decimal(text)
    except InvalidOperation:
        return text
    if numeric == numeric.to_integral_value():
        text = str(numeric.to_integral_value())
    elif text.endswith(".0"):
        text = text[:-2]
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


def normalize_identifier_columns(df: pd.DataFrame, table_name: str) -> pd.DataFrame:
    table_stats = IDENTIFIER_DIAGNOSTICS.setdefault(table_name, {})
    for column in df.columns:
        if is_identifier_column(column):
            before = df[column].astype("string")
            after = before.map(normalize_steamid).astype("string")
            changed = int((before.fillna("") != after.fillna("")).sum())
            if changed > 0:
                table_stats[column] = changed
            df[column] = after
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
    players = normalize_identifier_columns(players, "players")
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
    poststart_ticks = unique_sorted_ticks(
        read_csv_if_exists(raw_dir / "events" / "round_poststart.csv")
    )
    freeze_end_ticks = unique_sorted_ticks(
        read_csv_if_exists(raw_dir / "events" / "round_freeze_end.csv")
    )
    officially_ended_ticks = unique_sorted_ticks(
        read_csv_if_exists(raw_dir / "events" / "round_officially_ended.csv")
    )
    win_panel_ticks = unique_sorted_ticks(
        read_csv_if_exists(raw_dir / "events" / "cs_win_panel_match.csv")
    )

    start_ticks = prestart_ticks
    start_source = "round_prestart"
    if not start_ticks:
        if poststart_ticks:
            start_ticks = poststart_ticks
            start_source = "round_poststart"
        elif freeze_end_ticks:
            start_ticks = freeze_end_ticks
            start_source = "round_freeze_end"
        elif officially_ended_ticks:
            # Last-resort fallback: treat round end markers as timeline anchors.
            start_ticks = officially_ended_ticks
            start_source = "round_officially_ended"

    rows: list[dict[str, object]] = []
    for index, start_tick in enumerate(start_ticks):
        next_start_tick = (
            start_ticks[index + 1] if index + 1 < len(start_ticks) else None
        )

        prestart_tick = (
            start_tick
            if start_source == "round_prestart"
            else first_tick_in_range(
                prestart_ticks,
                start_tick,
                next_start_tick,
                include_start=True,
                include_stop=False,
            )
        )
        poststart_tick = first_tick_in_range(
            poststart_ticks,
            start_tick,
            next_start_tick,
            include_start=True,
            include_stop=False,
        )
        freeze_end_tick = first_tick_in_range(
            freeze_end_ticks,
            start_tick,
            next_start_tick,
            include_start=True,
            include_stop=False,
        )

        # A round_officially_ended marker that lands exactly on the next prestart
        # is only a boundary echo, not proof of the active phase close.  Only a
        # strictly in-window marker can be used as an official close tick.
        official_close_tick = first_tick_in_range(
            officially_ended_ticks,
            start_tick,
            next_start_tick,
            include_start=False,
            include_stop=False,
        )
        boundary_official_tick = (
            next_start_tick
            if next_start_tick is not None and next_start_tick in officially_ended_ticks
            else pd.NA
        )

        if not pd.isna(official_close_tick):
            round_close_tick = official_close_tick
            end_marker_source = "round_officially_ended"
        elif index == len(start_ticks) - 1:
            round_close_tick = first_tick_in_range(
                win_panel_ticks,
                start_tick,
                None,
                include_start=False,
                include_stop=False,
            )
            end_marker_source = (
                "cs_win_panel_match" if not pd.isna(round_close_tick) else "missing"
            )
        elif next_start_tick is not None:
            round_close_tick = next_start_tick
            end_marker_source = "next_prestart_boundary"
        else:
            round_close_tick = pd.NA
            end_marker_source = "missing"

        missing_markers: list[str] = []
        if pd.isna(prestart_tick):
            missing_markers.append("prestart")
        if pd.isna(poststart_tick):
            missing_markers.append("poststart")
        if pd.isna(freeze_end_tick):
            missing_markers.append("freeze_end")
        if pd.isna(official_close_tick):
            missing_markers.append("valid_officially_ended")
        if not pd.isna(boundary_official_tick):
            missing_markers.append("officially_ended_at_next_prestart")
        if pd.isna(round_close_tick):
            missing_markers.append("round_close")

        core_markers_present = all(
            not pd.isna(tick)
            for tick in (prestart_tick, poststart_tick, freeze_end_tick)
        )
        fallback_start = start_source != "round_prestart"
        if core_markers_present and end_marker_source == "round_officially_ended":
            timeline_confidence = "medium" if fallback_start else "high"
        elif core_markers_present and end_marker_source == "cs_win_panel_match":
            timeline_confidence = "medium"
        elif core_markers_present and end_marker_source == "next_prestart_boundary":
            timeline_confidence = "medium"
        elif not pd.isna(round_close_tick):
            timeline_confidence = "low"
        else:
            timeline_confidence = "low"

        rows.append(
            {
                "round_number": index + 1,
                "prestart_tick": prestart_tick,
                "poststart_tick": poststart_tick,
                "freeze_end_tick": freeze_end_tick,
                "round_close_tick": round_close_tick,
                "next_prestart_tick": (
                    next_start_tick if next_start_tick is not None else pd.NA
                ),
                "end_marker_source": end_marker_source,
                "timeline_confidence": timeline_confidence,
                "missing_markers": ";".join(missing_markers),
            }
        )

    return pd.DataFrame(
        rows,
        columns=[
            "round_number",
            "prestart_tick",
            "poststart_tick",
            "freeze_end_tick",
            "round_close_tick",
            "next_prestart_tick",
            "end_marker_source",
            "timeline_confidence",
            "missing_markers",
        ],
    )


def assign_round_numbers(df: pd.DataFrame, rounds: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "tick" not in df.columns or rounds.empty:
        df = df.copy()
        if "round_number" not in df.columns:
            df.insert(0, "round_number", pd.NA)
        return df

    marker_columns = [
        column
        for column in ("prestart_tick", "poststart_tick", "freeze_end_tick")
        if column in rounds.columns
    ]
    round_starts = rounds[
        ["round_number", *marker_columns, "next_prestart_tick"]
    ].copy()
    ticks = pd.to_numeric(df["tick"], errors="coerce")
    round_numbers: list[object] = []
    for tick in ticks:
        if pd.isna(tick):
            round_numbers.append(pd.NA)
            continue
        tick_int = int(tick)
        matched = pd.NA
        for row in round_starts.to_dict("records"):
            start = next(
                (row[column] for column in marker_columns if not pd.isna(row[column])),
                pd.NA,
            )
            if pd.isna(start):
                continue
            stop = row["next_prestart_tick"]
            if tick_int >= int(start) and (pd.isna(stop) or tick_int < int(stop)):
                matched = int(row["round_number"])
                break
        round_numbers.append(matched)

    out = df.copy()
    if "round_number" in out.columns:
        out["round_number"] = round_numbers
    else:
        out.insert(0, "round_number", round_numbers)
    return out


OUTCOME_COLUMNS = [
    "round_number",
    "start_tick",
    "live_start_tick",
    "end_tick",
    "bomb_planted",
    "bomb_defused",
    "bomb_exploded",
    "winner_side",
    "winner_team_number",
    "end_reason",
    "outcome_confidence",
]
SIDE_TO_TEAM_NUMBER = {"T": 2, "CT": 3}
TEAM_NUMBER_TO_SIDE = {2: "T", 3: "CT"}
WINNER_SIDE_COLUMNS = (
    "winner_side",
    "winning_side",
    "winner",
    "winning_team",
    "winner_team",
)
WINNER_TEAM_NUMBER_COLUMNS = (
    "winner_team_number",
    "winning_team_number",
    "team_number",
    "winner_team_num",
    "winning_team_num",
    "team",
)
END_REASON_COLUMNS = (
    "end_reason",
    "reason",
    "win_reason",
    "round_end_reason",
    "message",
)
OUTCOME_SOURCE_EVENTS = (
    "round_officially_ended",
    "round_announce_match_point",
    "round_announce_last_round_half",
)
ROUND_STATE_TICK_WINDOW = 512


def round_timeline_value(row: dict[str, object], candidates: Iterable[str]) -> object:
    for column in candidates:
        value = row.get(column, pd.NA)
        if not pd.isna(value):
            return value
    return pd.NA


def normalize_side(value: object) -> str | pd.NA:
    if pd.isna(value):
        return pd.NA
    if isinstance(value, str):
        text = value.strip().lower()
        if not text or text in {"nan", "none", "unknown"}:
            return pd.NA
        if text in {"t", "terrorist", "terrorists", "team_t", "tt"}:
            return "T"
        if text in {
            "ct",
            "counter-terrorist",
            "counter-terrorists",
            "counterterrorist",
            "counterterrorists",
            "team_ct",
        }:
            return "CT"
    number = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if not pd.isna(number):
        return TEAM_NUMBER_TO_SIDE.get(int(number), pd.NA)
    return pd.NA


def normalize_team_number(value: object) -> int | pd.NA:
    if pd.isna(value):
        return pd.NA
    number = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(number):
        side = normalize_side(value)
        return SIDE_TO_TEAM_NUMBER.get(side, pd.NA) if not pd.isna(side) else pd.NA
    number_int = int(number)
    return number_int if number_int in TEAM_NUMBER_TO_SIDE else pd.NA


def first_unique_value(values: Iterable[object]) -> object:
    unique: list[object] = []
    for value in values:
        if pd.isna(value):
            continue
        normalized = str(value).strip() if isinstance(value, str) else value
        if isinstance(normalized, str) and not normalized:
            continue
        if normalized not in unique:
            unique.append(normalized)
    return unique[0] if len(unique) == 1 else pd.NA


def explicit_round_outcomes(raw_dir: Path, rounds: pd.DataFrame) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for event_name in OUTCOME_SOURCE_EVENTS:
        frame = read_csv_if_exists(raw_dir / "events" / f"{event_name}.csv")
        if frame.empty:
            continue
        useful_columns = [
            column
            for column in frame.columns
            if column in WINNER_SIDE_COLUMNS
            or column in WINNER_TEAM_NUMBER_COLUMNS
            or column in END_REASON_COLUMNS
            or column in {"tick", "round_number"}
        ]
        # Tick-only announcement events are timeline markers, not reliable outcome
        # evidence.  Keep only rows that contain explicit winner/reason fields.
        if set(useful_columns) <= {"tick", "round_number"}:
            continue
        frame = frame[useful_columns].copy()
        frame.insert(0, "event_name", event_name)
        frames.append(assign_round_numbers(frame, rounds))
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True, sort=False)


def raw_player_team_map(raw_dir: Path) -> dict[str, int]:
    players = read_csv_if_exists(raw_dir / "meta" / "player_info.csv")
    if (
        players.empty
        or "steamid" not in players.columns
        or "team_number" not in players.columns
    ):
        return {}
    players = normalize_steamid_columns(players.copy())
    players["team_number"] = pd.to_numeric(players["team_number"], errors="coerce")
    usable = players.dropna(subset=["steamid", "team_number"])
    return {
        str(row.steamid): int(row.team_number)
        for row in usable.itertuples(index=False)
        if int(row.team_number) in TEAM_NUMBER_TO_SIDE
    }


def read_player_team_events(raw_dir: Path) -> pd.DataFrame:
    teams = read_csv_if_exists(raw_dir / "events" / "player_team.csv")
    required = {"tick", "user_steamid", "team"}
    if teams.empty or not required <= set(teams.columns):
        return pd.DataFrame()
    teams = normalize_steamid_columns(teams.copy())
    teams["tick"] = pd.to_numeric(teams["tick"], errors="coerce")
    teams["team_number"] = pd.to_numeric(teams["team"], errors="coerce")
    if "oldteam" in teams.columns:
        teams["old_team_number"] = pd.to_numeric(teams["oldteam"], errors="coerce")
    else:
        teams["old_team_number"] = pd.NA
    usable = teams.dropna(subset=["tick", "user_steamid", "team_number"]).copy()
    usable = usable[usable["team_number"].isin(TEAM_NUMBER_TO_SIDE)]
    if usable.empty:
        return pd.DataFrame()
    usable["tick"] = usable["tick"].astype(int)
    usable["team_number"] = usable["team_number"].astype(int)
    return usable[["tick", "user_steamid", "team_number", "old_team_number"]]


def team_map_for_tick(
    player_team_map: dict[str, int],
    player_team_events: pd.DataFrame,
    tick: object,
) -> dict[str, int]:
    if pd.isna(tick):
        return dict(player_team_map)
    target = int(tick)
    players = set(player_team_map)
    if not player_team_events.empty and "user_steamid" in player_team_events.columns:
        players.update(player_team_events["user_steamid"].dropna().astype(str).tolist())
    result: dict[str, int] = {}
    for steamid in sorted(players):
        player_events = (
            player_team_events[player_team_events["user_steamid"].astype(str) == steamid]
            if not player_team_events.empty
            else pd.DataFrame()
        )
        team_number = player_team_map.get(steamid)
        if not player_events.empty:
            prior = player_events[player_events["tick"] <= target].sort_values("tick")
            if not prior.empty:
                team_number = int(prior.iloc[-1]["team_number"])
            else:
                future = player_events[player_events["tick"] > target].sort_values("tick")
                if not future.empty:
                    old_team = future.iloc[0].get("old_team_number", pd.NA)
                    if not pd.isna(old_team) and int(old_team) in TEAM_NUMBER_TO_SIDE:
                        team_number = int(old_team)
        if team_number in TEAM_NUMBER_TO_SIDE:
            result[steamid] = int(team_number)
    return result


def build_round_roster_team_maps(
    raw_dir: Path, rounds: pd.DataFrame, player_team_map: dict[str, int]
) -> dict[object, dict[str, int]]:
    player_team_events = read_player_team_events(raw_dir)
    roster_maps: dict[object, dict[str, int]] = {}
    for round_row in rounds.to_dict("records"):
        round_number = round_row.get("round_number", pd.NA)
        tick = round_timeline_value(
            round_row, ("freeze_end_tick", "poststart_tick", "prestart_tick")
        )
        roster_maps[round_number] = team_map_for_tick(
            player_team_map, player_team_events, tick
        )
    return roster_maps


def normalize_alive_series(frame: pd.DataFrame) -> pd.Series:
    if "is_alive" in frame.columns:
        values = frame["is_alive"]
        if pd.api.types.is_bool_dtype(values):
            return values.fillna(False)
        text = values.astype("string").str.strip().str.lower()
        numeric = pd.to_numeric(values, errors="coerce")
        return text.isin({"true", "t", "yes", "y"}) | (numeric == 1)
    if "life_state" in frame.columns:
        return pd.to_numeric(frame["life_state"], errors="coerce") == 0
    if "health" in frame.columns:
        return pd.to_numeric(frame["health"], errors="coerce") > 0
    return pd.Series([pd.NA] * len(frame), index=frame.index, dtype="boolean")


def read_player_core_states(raw_dir: Path) -> pd.DataFrame:
    core = read_csv_if_exists(raw_dir / "ticks" / "ticks_player_core.csv")
    if core.empty or "tick" not in core.columns or "steamid" not in core.columns:
        return pd.DataFrame()
    team_column = next(
        (
            column
            for column in ("team_num", "team_number", "team")
            if column in core.columns
        ),
        None,
    )
    if team_column is None:
        return pd.DataFrame()
    core = normalize_steamid_columns(core.copy())
    core["tick"] = pd.to_numeric(core["tick"], errors="coerce")
    core["team_number"] = pd.to_numeric(core[team_column], errors="coerce")
    core["is_alive_normalized"] = normalize_alive_series(core)
    usable = core.dropna(subset=["tick", "steamid", "team_number"])
    usable = usable[usable["team_number"].isin(TEAM_NUMBER_TO_SIDE)].copy()
    if usable.empty:
        return pd.DataFrame()
    usable["tick"] = usable["tick"].astype(int)
    usable["team_number"] = usable["team_number"].astype(int)
    return usable[["tick", "steamid", "team_number", "is_alive_normalized"]]


def read_player_aggregate_states(raw_dir: Path) -> pd.DataFrame:
    aggregate = read_csv_if_exists(raw_dir / "ticks" / "ticks_aggregate.csv")
    if (
        aggregate.empty
        or "tick" not in aggregate.columns
        or "steamid" not in aggregate.columns
        or "deaths_total" not in aggregate.columns
    ):
        return pd.DataFrame()
    aggregate = normalize_steamid_columns(aggregate.copy())
    aggregate["tick"] = pd.to_numeric(aggregate["tick"], errors="coerce")
    aggregate["deaths_total"] = pd.to_numeric(
        aggregate["deaths_total"], errors="coerce"
    )
    aggregate = aggregate.dropna(subset=["tick", "steamid", "deaths_total"])
    if aggregate.empty:
        return pd.DataFrame()
    aggregate["tick"] = aggregate["tick"].astype(int)
    return aggregate[["tick", "steamid", "deaths_total"]]


def round_player_snapshot(
    player_core: pd.DataFrame,
    start_tick: object,
    end_tick: object,
) -> pd.DataFrame:
    if player_core.empty or pd.isna(end_tick):
        return pd.DataFrame()
    end = int(end_tick)
    start = int(start_tick) if not pd.isna(start_tick) else None
    window_start = max(
        end - ROUND_STATE_TICK_WINDOW, start or end - ROUND_STATE_TICK_WINDOW
    )
    candidates = player_core[
        (player_core["tick"] <= end) & (player_core["tick"] >= window_start)
    ]
    if candidates.empty and start is not None:
        candidates = player_core[
            (player_core["tick"] >= start) & (player_core["tick"] <= end)
        ]
    if candidates.empty:
        candidates = player_core[
            (player_core["tick"] >= end)
            & (player_core["tick"] <= end + ROUND_STATE_TICK_WINDOW)
        ]
    if candidates.empty:
        return pd.DataFrame()
    snapshot_tick = int(candidates["tick"].max())
    snapshot = candidates[candidates["tick"] == snapshot_tick].copy()
    snapshot = snapshot.drop_duplicates(subset=["steamid"], keep="last")
    return snapshot


def alive_counts_from_snapshot(snapshot: pd.DataFrame) -> dict[int, int]:
    counts = {2: 0, 3: 0}
    if snapshot.empty or "is_alive_normalized" not in snapshot.columns:
        return counts
    alive = snapshot[snapshot["is_alive_normalized"].fillna(False).astype(bool)]
    for team_number, count in alive.groupby("team_number").size().items():
        team_int = int(team_number)
        if team_int in counts:
            counts[team_int] = int(count)
    return counts


def alive_counts_from_deaths(
    deaths: pd.DataFrame,
    roster_team_map: dict[str, int],
    start_tick: object,
    end_tick: object,
) -> dict[int, int] | None:
    team_to_players: dict[int, set[str]] = {2: set(), 3: set()}
    for steamid, team_number in roster_team_map.items():
        if team_number in team_to_players:
            team_to_players[team_number].add(str(steamid))
    if not all(team_to_players.values()):
        return None

    dead_by_team: dict[int, set[str]] = {2: set(), 3: set()}
    if not deaths.empty and {"tick", "user_steamid"} <= set(deaths.columns):
        round_deaths = deaths.copy()
        round_deaths["tick"] = pd.to_numeric(round_deaths["tick"], errors="coerce")
        round_deaths = round_deaths.dropna(subset=["tick", "user_steamid"])
        if not pd.isna(start_tick):
            round_deaths = round_deaths[round_deaths["tick"] >= int(start_tick)]
        if not pd.isna(end_tick):
            round_deaths = round_deaths[round_deaths["tick"] <= int(end_tick)]
        for row in round_deaths.sort_values("tick").itertuples(index=False):
            victim = str(getattr(row, "user_steamid"))
            victim_team = roster_team_map.get(victim)
            if victim_team in dead_by_team:
                dead_by_team[victim_team].add(victim)

    return {
        team: max(len(players) - len(dead_by_team[team]), 0)
        for team, players in team_to_players.items()
    }


def infer_elimination_from_deaths(
    deaths: pd.DataFrame,
    player_core: pd.DataFrame,
    roster_team_map: dict[str, int],
    start_tick: object,
    end_tick: object,
) -> tuple[object, object, object, str] | None:
    snapshot = round_player_snapshot(player_core, start_tick, end_tick)
    if not snapshot.empty:
        alive_counts = alive_counts_from_snapshot(snapshot)
        if alive_counts[2] == 0 and alive_counts[3] > 0:
            return "CT", SIDE_TO_TEAM_NUMBER["CT"], "elimination", "high"
        if alive_counts[3] == 0 and alive_counts[2] > 0:
            return "T", SIDE_TO_TEAM_NUMBER["T"], "elimination", "high"

    if (
        deaths.empty
        or "user_steamid" not in deaths.columns
        or "tick" not in deaths.columns
    ):
        return None

    alive_counts = alive_counts_from_deaths(
        deaths, roster_team_map, start_tick, end_tick
    )
    if alive_counts is None:
        return None
    if alive_counts[2] == 0 and alive_counts[3] > 0:
        return "CT", SIDE_TO_TEAM_NUMBER["CT"], "elimination", "high"
    if alive_counts[3] == 0 and alive_counts[2] > 0:
        return "T", SIDE_TO_TEAM_NUMBER["T"], "elimination", "high"
    return None


def tick_state_snapshot(
    frame: pd.DataFrame,
    target_tick: object,
    *,
    before: bool,
) -> pd.DataFrame:
    if frame.empty or pd.isna(target_tick):
        return pd.DataFrame()
    target = int(target_tick)
    if before:
        candidates = frame[frame["tick"] <= target]
        if candidates.empty:
            return pd.DataFrame()
        snapshot_tick = int(candidates["tick"].max())
    else:
        candidates = frame[frame["tick"] >= target]
        if candidates.empty:
            return pd.DataFrame()
        snapshot_tick = int(candidates["tick"].min())
    return candidates[candidates["tick"] == snapshot_tick].drop_duplicates(
        subset=["steamid"], keep="last"
    )


def infer_from_aggregate_deaths(
    aggregate: pd.DataFrame,
    roster_team_map: dict[str, int],
    start_tick: object,
    end_tick: object,
    bomb_planted: bool,
) -> tuple[object, object, object, str] | None:
    if aggregate.empty or not roster_team_map:
        return None
    start = tick_state_snapshot(aggregate, start_tick, before=False)
    end = tick_state_snapshot(aggregate, end_tick, before=True)
    if start.empty or end.empty:
        return None
    deltas = start[["steamid", "deaths_total"]].merge(
        end[["steamid", "deaths_total"]],
        on="steamid",
        suffixes=("_start", "_end"),
        how="inner",
    )
    if deltas.empty:
        return None
    deltas["team_number"] = deltas["steamid"].map(roster_team_map)
    deltas["died_this_round"] = (
        deltas["deaths_total_end"] > deltas["deaths_total_start"]
    )
    team_sizes = deltas.dropna(subset=["team_number"]).groupby("team_number").size()
    deaths = (
        deltas[deltas["died_this_round"]]
        .dropna(subset=["team_number"])
        .groupby("team_number")
        .size()
    )
    for victim_team in (2, 3):
        team_size = int(team_sizes.get(victim_team, 0))
        team_deaths = int(deaths.get(victim_team, 0))
        if team_size > 0 and team_deaths >= team_size:
            winner_team = 3 if victim_team == 2 else 2
            return (
                TEAM_NUMBER_TO_SIDE[winner_team],
                winner_team,
                "elimination",
                "medium",
            )
    teams_alive = all(
        int(team_sizes.get(team, 0)) > int(deaths.get(team, 0)) for team in (2, 3)
    )
    if not bomb_planted and teams_alive:
        return "CT", SIDE_TO_TEAM_NUMBER["CT"], "time_expired", "low"
    return None


def infer_time_expired_from_state(
    player_core: pd.DataFrame,
    start_tick: object,
    end_tick: object,
    bomb_planted: bool,
) -> tuple[object, object, object, str] | None:
    if bomb_planted:
        return None
    snapshot = round_player_snapshot(player_core, start_tick, end_tick)
    if snapshot.empty:
        return None
    alive_counts = alive_counts_from_snapshot(snapshot)
    if alive_counts[2] > 0 and alive_counts[3] > 0:
        return "CT", SIDE_TO_TEAM_NUMBER["CT"], "time_expired", "medium"
    return None


def infer_time_expired_from_deaths(
    deaths: pd.DataFrame,
    roster_team_map: dict[str, int],
    start_tick: object,
    end_tick: object,
    bomb_planted: bool,
) -> tuple[object, object, object, str] | None:
    if bomb_planted:
        return None
    alive_counts = alive_counts_from_deaths(
        deaths, roster_team_map, start_tick, end_tick
    )
    if alive_counts is None:
        return None
    if alive_counts[2] > 0 and alive_counts[3] > 0:
        return "CT", SIDE_TO_TEAM_NUMBER["CT"], "time_expired", "medium"
    return None


def column_values(df: pd.DataFrame, columns: Iterable[str]) -> list[object]:
    values: list[object] = []
    for column in columns:
        if column in df.columns:
            values.extend(df[column].tolist())
    return values


def build_round_outcomes(raw_dir: Path, rounds: pd.DataFrame) -> pd.DataFrame:
    if rounds.empty:
        return pd.DataFrame(columns=OUTCOME_COLUMNS)

    bomb_frames: dict[str, pd.DataFrame] = {}
    for event_name in ("bomb_planted", "bomb_defused", "bomb_exploded"):
        frame = read_csv_if_exists(raw_dir / "events" / f"{event_name}.csv")
        bomb_frames[event_name] = (
            assign_round_numbers(frame, rounds) if not frame.empty else pd.DataFrame()
        )

    explicit_outcomes = explicit_round_outcomes(raw_dir, rounds)
    player_deaths = read_csv_if_exists(raw_dir / "events" / "player_death.csv")
    if not player_deaths.empty:
        player_deaths = normalize_steamid_columns(player_deaths.copy())
        player_deaths = assign_round_numbers(player_deaths, rounds)
    player_core = read_player_core_states(raw_dir)
    player_aggregate = read_player_aggregate_states(raw_dir)
    player_team_map = raw_player_team_map(raw_dir)
    round_roster_team_maps = build_round_roster_team_maps(
        raw_dir, rounds, player_team_map
    )

    ROUND_OUTCOME_DIAGNOSTICS.clear()
    ROUND_OUTCOME_DIAGNOSTICS.update(
        {
            "rounds_total": int(len(rounds)),
            "bomb_objective_high_confidence": 0,
            "explicit_high_confidence": 0,
            "elimination_inferred": 0,
            "time_expired_inferred": 0,
            "low_confidence": 0,
            "closed_bomb_objective": 0,
            "closed_elimination": 0,
            "closed_timeout": 0,
            "closed_fallback": 0,
            "closed_unknown": 0,
        }
    )
    rows: list[dict[str, object]] = []
    for round_row in rounds.to_dict("records"):
        round_number = round_row.get("round_number", pd.NA)
        round_bomb_events = {
            event_name: (
                frame[frame["round_number"] == round_number]
                if not frame.empty and "round_number" in frame.columns
                else pd.DataFrame()
            )
            for event_name, frame in bomb_frames.items()
        }
        bomb_planted = not round_bomb_events["bomb_planted"].empty
        bomb_defused = not round_bomb_events["bomb_defused"].empty
        bomb_exploded = not round_bomb_events["bomb_exploded"].empty

        winner_side: object = pd.NA
        winner_team_number: object = pd.NA
        end_reason: object = pd.NA
        outcome_confidence = "low"

        if bomb_defused and not bomb_exploded:
            winner_side = "CT"
            winner_team_number = SIDE_TO_TEAM_NUMBER["CT"]
            end_reason = "bomb_defused"
            outcome_confidence = "high"
            ROUND_OUTCOME_DIAGNOSTICS["bomb_objective_high_confidence"] += 1
        elif bomb_exploded and not bomb_defused:
            winner_side = "T"
            winner_team_number = SIDE_TO_TEAM_NUMBER["T"]
            end_reason = "bomb_exploded"
            outcome_confidence = "high"
            ROUND_OUTCOME_DIAGNOSTICS["bomb_objective_high_confidence"] += 1
        else:
            round_explicit = (
                explicit_outcomes[explicit_outcomes["round_number"] == round_number]
                if not explicit_outcomes.empty
                and "round_number" in explicit_outcomes.columns
                else pd.DataFrame()
            )
            explicit_side = first_unique_value(
                normalize_side(value)
                for value in column_values(round_explicit, WINNER_SIDE_COLUMNS)
            )
            explicit_team_number = first_unique_value(
                normalize_team_number(value)
                for value in column_values(round_explicit, WINNER_TEAM_NUMBER_COLUMNS)
            )
            explicit_reason = first_unique_value(
                column_values(round_explicit, END_REASON_COLUMNS)
            )
            if pd.isna(explicit_side) and not pd.isna(explicit_team_number):
                explicit_side = TEAM_NUMBER_TO_SIDE.get(
                    int(explicit_team_number), pd.NA
                )
            if pd.isna(explicit_team_number) and not pd.isna(explicit_side):
                explicit_team_number = SIDE_TO_TEAM_NUMBER.get(explicit_side, pd.NA)
            if not pd.isna(explicit_side) and not pd.isna(explicit_reason):
                winner_side = explicit_side
                winner_team_number = explicit_team_number
                end_reason = explicit_reason
                outcome_confidence = "high"
                ROUND_OUTCOME_DIAGNOSTICS["explicit_high_confidence"] += 1

            if pd.isna(winner_side):
                start_tick = round_timeline_value(
                    round_row, ("freeze_end_tick", "poststart_tick", "prestart_tick")
                )
                end_tick = round_timeline_value(
                    round_row, ("round_close_tick", "next_prestart_tick")
                )
                round_deaths = (
                    player_deaths[player_deaths["round_number"] == round_number]
                    if not player_deaths.empty
                    and "round_number" in player_deaths.columns
                    else pd.DataFrame()
                )
                roster_team_map = round_roster_team_maps.get(
                    round_number, player_team_map
                )
                inferred = infer_elimination_from_deaths(
                    round_deaths, player_core, roster_team_map, start_tick, end_tick
                )
                if inferred is None:
                    inferred = infer_time_expired_from_state(
                        player_core, start_tick, end_tick, bomb_planted
                    )
                if inferred is None:
                    inferred = infer_time_expired_from_deaths(
                        round_deaths,
                        roster_team_map,
                        start_tick,
                        end_tick,
                        bomb_planted,
                    )
                if inferred is None:
                    inferred = infer_from_aggregate_deaths(
                        player_aggregate,
                        roster_team_map,
                        start_tick,
                        end_tick,
                        bomb_planted,
                    )
                if inferred is not None:
                    (
                        winner_side,
                        winner_team_number,
                        end_reason,
                        outcome_confidence,
                    ) = inferred
                    if end_reason == "elimination":
                        ROUND_OUTCOME_DIAGNOSTICS["elimination_inferred"] += 1
                    elif end_reason == "time_expired":
                        ROUND_OUTCOME_DIAGNOSTICS["time_expired_inferred"] += 1

        if pd.isna(end_reason):
            end_reason = "unknown"
        if outcome_confidence == "low":
            ROUND_OUTCOME_DIAGNOSTICS["low_confidence"] += 1
        if end_reason in {"bomb_defused", "bomb_exploded"}:
            ROUND_OUTCOME_DIAGNOSTICS["closed_bomb_objective"] += 1
        elif end_reason == "elimination":
            ROUND_OUTCOME_DIAGNOSTICS["closed_elimination"] += 1
        elif end_reason == "time_expired":
            ROUND_OUTCOME_DIAGNOSTICS["closed_timeout"] += 1
        elif end_reason == "unknown":
            ROUND_OUTCOME_DIAGNOSTICS["closed_unknown"] += 1
        else:
            ROUND_OUTCOME_DIAGNOSTICS["closed_fallback"] += 1

        rows.append(
            {
                "round_number": round_number,
                "start_tick": round_timeline_value(
                    round_row, ("prestart_tick", "poststart_tick", "freeze_end_tick")
                ),
                "live_start_tick": round_timeline_value(
                    round_row, ("freeze_end_tick", "poststart_tick", "prestart_tick")
                ),
                "end_tick": round_timeline_value(
                    round_row, ("round_close_tick", "next_prestart_tick")
                ),
                "bomb_planted": bomb_planted,
                "bomb_defused": bomb_defused,
                "bomb_exploded": bomb_exploded,
                "winner_side": winner_side,
                "winner_team_number": winner_team_number,
                "end_reason": end_reason,
                "outcome_confidence": outcome_confidence,
            }
        )

    return pd.DataFrame(rows, columns=OUTCOME_COLUMNS)


def build_kills(
    raw_dir: Path, rounds: pd.DataFrame, player_round_sides: pd.DataFrame | None = None
) -> pd.DataFrame:
    kills = read_csv_if_exists(raw_dir / "events" / "player_death.csv")
    if kills.empty:
        return pd.DataFrame()
    kills = normalize_steamid_columns(kills.copy())
    kills = normalize_identifier_columns(kills, "kills")
    kills = assign_round_numbers(kills, rounds)

    attacker = kills.get("attacker_steamid", pd.Series(pd.NA, index=kills.index))
    victim = kills.get("user_steamid", pd.Series(pd.NA, index=kills.index))
    kills["has_attacker"] = attacker.notna()
    kills["is_world"] = ~kills["has_attacker"]
    kills["is_suicide"] = kills["has_attacker"] & attacker.eq(victim).fillna(False)
    kills["is_teamkill"] = False

    if (
        player_round_sides is not None
        and not player_round_sides.empty
        and {"round_number", "steamid", "team_number"} <= set(player_round_sides.columns)
        and {"round_number", "user_steamid", "attacker_steamid"} <= set(kills.columns)
    ):
        side_lookup = (
            player_round_sides[["round_number", "steamid", "team_number"]]
            .dropna(subset=["round_number", "steamid", "team_number"])
            .drop_duplicates(subset=["round_number", "steamid"], keep="first")
        )
        victim_sides = side_lookup.rename(
            columns={"steamid": "user_steamid", "team_number": "victim_team_number"}
        )
        attacker_sides = side_lookup.rename(
            columns={
                "steamid": "attacker_steamid",
                "team_number": "attacker_team_number",
            }
        )
        kills = kills.merge(
            victim_sides, on=["round_number", "user_steamid"], how="left"
        )
        kills = kills.merge(
            attacker_sides, on=["round_number", "attacker_steamid"], how="left"
        )
        victim_team = pd.to_numeric(kills["victim_team_number"], errors="coerce")
        attacker_team = pd.to_numeric(kills["attacker_team_number"], errors="coerce")
        same_team = (
            victim_team.notna() & attacker_team.notna() & victim_team.eq(attacker_team)
        )
        kills["is_teamkill"] = (
            kills["has_attacker"] & ~kills["is_suicide"] & same_team
        )
        kills = kills.drop(columns=["victim_team_number", "attacker_team_number"])

    preferred = [
        "round_number",
        "tick",
        "user_steamid",
        "user_name",
        "attacker_steamid",
        "attacker_name",
        "assister_steamid",
        "assister_name",
        "is_suicide",
        "has_attacker",
        "is_teamkill",
        "is_world",
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
    damage = normalize_identifier_columns(damage, "damage")
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


def normalize_weapon_name(value: object) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip().lower()
    if text.startswith("weapon_"):
        text = text[len("weapon_") :]
    return text


def firearm_shot_series(weapons: pd.Series) -> pd.Series:
    if weapons.empty:
        return pd.Series(dtype=bool, index=weapons.index)
    normalized = weapons.map(normalize_weapon_name)
    return normalized.isin(FIREARM_WEAPONS)


def build_weapon_actions(raw_dir: Path, rounds: pd.DataFrame) -> pd.DataFrame:
    actions = read_csv_if_exists(raw_dir / "events" / "weapon_fire.csv")
    preferred = [
        "round_number",
        "tick",
        "user_steamid",
        "user_name",
        "weapon",
        "is_firearm_shot",
        "silenced",
    ]
    if actions.empty:
        WEAPON_FIRE_DIAGNOSTICS.clear()
        WEAPON_FIRE_DIAGNOSTICS.update(
            {
                "weapon_fire_rows": 0,
                "firearm_shot_rows": 0,
                "non_firearm_action_rows": 0,
                "non_firearm_weapons": {},
            }
        )
        return pd.DataFrame(columns=preferred)

    actions = normalize_steamid_columns(actions.copy())
    actions = normalize_identifier_columns(actions, "weapon_actions")
    actions = assign_round_numbers(actions, rounds)
    if "weapon" in actions.columns:
        actions["is_firearm_shot"] = firearm_shot_series(actions["weapon"])
        non_firearm = actions[~actions["is_firearm_shot"]]
        non_firearm_weapons = (
            non_firearm["weapon"]
            .fillna("<missing>")
            .astype("string")
            .value_counts()
            .sort_index()
            .astype(int)
            .to_dict()
        )
    else:
        actions["is_firearm_shot"] = False
        non_firearm_weapons = {"<missing>": int(len(actions))}

    firearm_rows = int(actions["is_firearm_shot"].sum())
    WEAPON_FIRE_DIAGNOSTICS.clear()
    WEAPON_FIRE_DIAGNOSTICS.update(
        {
            "weapon_fire_rows": int(len(actions)),
            "firearm_shot_rows": firearm_rows,
            "non_firearm_action_rows": int(len(actions) - firearm_rows),
            "non_firearm_weapons": non_firearm_weapons,
        }
    )
    return select_existing(actions, preferred)


def build_shots(
    raw_dir: Path, rounds: pd.DataFrame, weapon_actions: pd.DataFrame | None = None
) -> pd.DataFrame:
    actions = (
        build_weapon_actions(raw_dir, rounds)
        if weapon_actions is None
        else weapon_actions.copy()
    )
    preferred = [
        "round_number",
        "tick",
        "user_steamid",
        "user_name",
        "weapon",
        "silenced",
    ]
    if actions.empty:
        return pd.DataFrame(columns=preferred)
    if "is_firearm_shot" not in actions.columns:
        return pd.DataFrame(columns=preferred)
    firearm_mask = (
        actions["is_firearm_shot"].fillna(False)
        if pd.api.types.is_bool_dtype(actions["is_firearm_shot"])
        else truthy_series(actions["is_firearm_shot"])
    )
    shots = actions[firearm_mask].copy()
    return select_existing(shots.drop(columns=["is_firearm_shot"]), preferred)


def build_bomb_events(raw_dir: Path, rounds: pd.DataFrame) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for path in sorted((raw_dir / "events").glob("bomb_*.csv")):
        frame = read_csv_if_exists(path)
        if frame.empty and not path.exists():
            continue
        frame = normalize_steamid_columns(frame.copy())
        frame = normalize_identifier_columns(frame, "bomb_events")
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


PLAYER_ROUND_SIDES_COLUMNS = [
    "round_number",
    "steamid",
    "name",
    "team_number",
    "side",
    "source_tick",
]


def build_player_round_sides(raw_dir: Path, rounds: pd.DataFrame) -> pd.DataFrame:
    player_core = read_csv_if_exists(raw_dir / "ticks" / "ticks_player_core.csv")
    if player_core.empty or not {"tick", "steamid"} <= set(player_core.columns):
        return pd.DataFrame(columns=PLAYER_ROUND_SIDES_COLUMNS)

    team_column = next(
        (
            column
            for column in ("team_num", "team_number", "team")
            if column in player_core.columns
        ),
        None,
    )
    if team_column is None:
        return pd.DataFrame(columns=PLAYER_ROUND_SIDES_COLUMNS)

    player_core = normalize_steamid_columns(player_core.copy())
    player_core["tick"] = pd.to_numeric(player_core["tick"], errors="coerce")
    player_core["team_number"] = pd.to_numeric(
        player_core[team_column], errors="coerce"
    )
    if "name" not in player_core.columns:
        player_core["name"] = pd.NA

    player_core = player_core.dropna(subset=["tick", "steamid"]).copy()
    if player_core.empty or rounds.empty or "round_number" not in rounds.columns:
        return pd.DataFrame(columns=PLAYER_ROUND_SIDES_COLUMNS)

    player_core["source_tick"] = player_core["tick"].astype(int)
    player_core = player_core.sort_values(["source_tick", "steamid"])

    rows: list[pd.DataFrame] = []
    for round_row in rounds.to_dict("records"):
        target_tick = round_timeline_value(
            round_row, ("freeze_end_tick", "poststart_tick", "prestart_tick")
        )
        if pd.isna(target_tick):
            continue

        target_tick_number = pd.to_numeric(
            pd.Series([target_tick]), errors="coerce"
        ).iloc[0]
        if pd.isna(target_tick_number):
            continue

        candidates = player_core[
            player_core["source_tick"] >= int(target_tick_number)
        ].copy()
        if candidates.empty:
            continue

        nearest = candidates.drop_duplicates(subset=["steamid"], keep="first")
        nearest.insert(0, "round_number", round_row["round_number"])
        rows.append(nearest)

    if not rows:
        return pd.DataFrame(columns=PLAYER_ROUND_SIDES_COLUMNS)

    sides = pd.concat(rows, ignore_index=True, sort=False)
    sides["team_number"] = pd.to_numeric(sides["team_number"], errors="coerce")
    sides["side"] = sides["team_number"].map(TEAM_NUMBER_TO_SIDE)
    return sides[PLAYER_ROUND_SIDES_COLUMNS].reset_index(drop=True)


PLAYER_ROUND_STATS_COLUMNS = [
    "round_number",
    "steamid",
    "name",
    "team_number",
    "kills",
    "deaths",
    "suicides",
    "team_deaths",
    "assists",
    "damage_dealt",
    "damage_taken",
    "headshot_kills",
    "shots",
    "bomb_plants",
    "bomb_defuses",
    "survived",
]


def player_round_counts(
    frame: pd.DataFrame,
    steamid_column: str,
    *,
    count_column: str,
    round_column: str = "round_number",
) -> pd.DataFrame:
    if (
        frame.empty
        or round_column not in frame.columns
        or steamid_column not in frame.columns
    ):
        return pd.DataFrame(columns=[round_column, "steamid", count_column])

    grouped = (
        frame[[round_column, steamid_column]]
        .dropna(subset=[round_column, steamid_column])
        .groupby([round_column, steamid_column], dropna=False)
        .size()
        .reset_index(name=count_column)
        .rename(columns={steamid_column: "steamid"})
    )
    return grouped


def player_round_sums(
    frame: pd.DataFrame,
    steamid_column: str,
    value_column: str,
    *,
    sum_column: str,
    round_column: str = "round_number",
) -> pd.DataFrame:
    if (
        frame.empty
        or round_column not in frame.columns
        or steamid_column not in frame.columns
        or value_column not in frame.columns
    ):
        return pd.DataFrame(columns=[round_column, "steamid", sum_column])

    usable = frame[[round_column, steamid_column, value_column]].dropna(
        subset=[round_column, steamid_column]
    )
    if usable.empty:
        return pd.DataFrame(columns=[round_column, "steamid", sum_column])
    usable = usable.copy()
    usable[value_column] = pd.to_numeric(usable[value_column], errors="coerce").fillna(
        0
    )
    grouped = (
        usable.groupby([round_column, steamid_column], dropna=False)[value_column]
        .sum()
        .reset_index(name=sum_column)
        .rename(columns={steamid_column: "steamid"})
    )
    return grouped


def truthy_series(values: pd.Series) -> pd.Series:
    if values.empty:
        return values.astype(bool)
    if pd.api.types.is_bool_dtype(values):
        return values.fillna(False)
    text = values.astype("string").str.strip().str.lower()
    return text.isin({"true", "1", "yes", "y", "t"})


def build_player_round_participants(
    raw_dir: Path, rounds: pd.DataFrame, player_round_sides: pd.DataFrame
) -> pd.DataFrame:
    """Return per-round participants observed in tick state, when available."""
    columns = ["round_number", "steamid"]
    if rounds.empty or not {"round_number", "freeze_end_tick", "round_close_tick"} <= set(
        rounds.columns
    ):
        return pd.DataFrame(columns=columns)

    player_core = read_csv_if_exists(raw_dir / "ticks" / "ticks_player_core.csv")
    if not player_core.empty and {"tick", "steamid"} <= set(player_core.columns):
        player_core = normalize_steamid_columns(player_core.copy())
        player_core["tick"] = pd.to_numeric(player_core["tick"], errors="coerce")
        player_core = player_core.dropna(subset=["tick", "steamid"]).copy()
        player_core["tick"] = player_core["tick"].astype(int)
    else:
        player_core = pd.DataFrame()

    rows: list[pd.DataFrame] = []
    if not player_core.empty:
        tick_steamids = player_core[["tick", "steamid"]].drop_duplicates()
        for round_row in rounds.to_dict("records"):
            round_number = round_row.get("round_number", pd.NA)
            start_tick = pd.to_numeric(
                pd.Series([round_row.get("freeze_end_tick", pd.NA)]), errors="coerce"
            ).iloc[0]
            close_tick = pd.to_numeric(
                pd.Series([round_row.get("round_close_tick", pd.NA)]), errors="coerce"
            ).iloc[0]
            if pd.isna(round_number) or pd.isna(start_tick) or pd.isna(close_tick):
                continue
            if int(close_tick) < int(start_tick):
                continue
            participants = tick_steamids[
                (tick_steamids["tick"] >= int(start_tick))
                & (tick_steamids["tick"] <= int(close_tick))
            ][["steamid"]].drop_duplicates()
            if participants.empty:
                continue
            participants.insert(0, "round_number", round_number)
            rows.append(participants)

    if rows:
        return pd.concat(rows, ignore_index=True, sort=False).drop_duplicates()

    if (
        not player_round_sides.empty
        and {"round_number", "steamid"} <= set(player_round_sides.columns)
    ):
        return (
            player_round_sides[["round_number", "steamid"]]
            .dropna(subset=["round_number", "steamid"])
            .drop_duplicates()
            .reset_index(drop=True)
        )

    return pd.DataFrame(columns=columns)


def build_player_round_stats(
    raw_dir: Path,
    players: pd.DataFrame,
    rounds: pd.DataFrame,
    player_round_sides: pd.DataFrame,
    kills: pd.DataFrame,
    damage: pd.DataFrame,
    shots: pd.DataFrame,
    bomb_events: pd.DataFrame,
) -> pd.DataFrame:
    if players.empty or rounds.empty:
        return pd.DataFrame(columns=PLAYER_ROUND_STATS_COLUMNS)

    player_columns = [
        column
        for column in ("steamid", "name", "team_number")
        if column in players.columns
    ]
    round_columns = [column for column in ("round_number",) if column in rounds.columns]
    if "steamid" not in player_columns or "round_number" not in round_columns:
        return pd.DataFrame(columns=PLAYER_ROUND_STATS_COLUMNS)

    player_base = players[player_columns].dropna(subset=["steamid"]).drop_duplicates()
    round_base = rounds[round_columns].dropna(subset=["round_number"]).drop_duplicates()
    if player_base.empty or round_base.empty:
        return pd.DataFrame(columns=PLAYER_ROUND_STATS_COLUMNS)

    stats = round_base.merge(player_base, how="cross")
    cross_join_rows = len(stats)

    round_participants = build_player_round_participants(
        raw_dir, rounds, player_round_sides
    )
    if not round_participants.empty:
        participant_keys = round_participants.drop_duplicates(
            subset=["round_number", "steamid"]
        ).copy()
        participant_keys["is_round_participant"] = True
        stats = stats.merge(
            participant_keys, on=["round_number", "steamid"], how="left"
        )
        rounds_with_participants = set(participant_keys["round_number"].dropna())
        has_participant_filter = stats["round_number"].isin(rounds_with_participants)
        participant_match = stats["is_round_participant"].fillna(False)
        fallback_round = ~has_participant_filter
        keep_rows = fallback_round | participant_match
        tick_rows = int((has_participant_filter & participant_match).sum())
        fallback_rows = int(fallback_round.sum())
        stats = stats[keep_rows].drop(columns=["is_round_participant"]).copy()
        participation_source = "ticks_player_core"
    else:
        rounds_with_participants = set()
        tick_rows = 0
        fallback_rows = len(stats)
        participation_source = "fallback_all_players"

    PLAYER_ROUND_PARTICIPATION_DIAGNOSTICS.clear()
    PLAYER_ROUND_PARTICIPATION_DIAGNOSTICS.update(
        {
            "participation_source": participation_source,
            "tick_participation_rows": tick_rows,
            "fallback_rows": fallback_rows,
            "filtered_rows": int(cross_join_rows - len(stats)),
            "rounds_with_tick_participants": int(len(rounds_with_participants)),
            "rounds_with_fallback_all_players": int(
                round_base["round_number"].nunique() - len(rounds_with_participants)
            ),
        }
    )

    if (
        not player_round_sides.empty
        and {"round_number", "steamid", "team_number"} <= set(player_round_sides.columns)
    ):
        side_lookup = (
            player_round_sides[["round_number", "steamid", "team_number"]]
            .dropna(subset=["round_number", "steamid"])
            .drop_duplicates(subset=["round_number", "steamid"], keep="first")
            .rename(columns={"team_number": "tick_team_number"})
        )
        stats = stats.merge(side_lookup, on=["round_number", "steamid"], how="left")
    else:
        stats["tick_team_number"] = pd.NA

    tick_team_number = pd.to_numeric(stats["tick_team_number"], errors="coerce")
    tick_side_available = tick_team_number.isin(list(TEAM_NUMBER_TO_SIDE))
    PLAYER_ROUND_SIDE_DIAGNOSTICS.clear()
    PLAYER_ROUND_SIDE_DIAGNOSTICS.update(
        {
            "tick_data_rows": int(tick_side_available.sum()),
            "fallback_rows": int((~tick_side_available).sum()),
        }
    )
    stats["team_number"] = (
        tick_team_number.where(
            tick_side_available, pd.to_numeric(stats["team_number"], errors="coerce")
        )
        .round()
        .astype("Int64")
    )

    if not kills.empty:
        normal_kills = kills.copy()
        if "has_attacker" in normal_kills.columns:
            normal_kills = normal_kills[truthy_series(normal_kills["has_attacker"])]
        if "is_suicide" in normal_kills.columns:
            normal_kills = normal_kills[~truthy_series(normal_kills["is_suicide"])]
        if "is_teamkill" in normal_kills.columns:
            normal_kills = normal_kills[~truthy_series(normal_kills["is_teamkill"])]
        suicide_deaths = (
            kills[truthy_series(kills["is_suicide"])].copy()
            if "is_suicide" in kills.columns
            else pd.DataFrame()
        )
        team_deaths = (
            kills[truthy_series(kills["is_teamkill"])].copy()
            if "is_teamkill" in kills.columns
            else pd.DataFrame()
        )
    else:
        normal_kills = pd.DataFrame()
        suicide_deaths = pd.DataFrame()
        team_deaths = pd.DataFrame()

    aggregates = [
        player_round_counts(normal_kills, "attacker_steamid", count_column="kills"),
        player_round_counts(kills, "user_steamid", count_column="deaths"),
        player_round_counts(suicide_deaths, "user_steamid", count_column="suicides"),
        player_round_counts(team_deaths, "user_steamid", count_column="team_deaths"),
        player_round_counts(kills, "assister_steamid", count_column="assists"),
        player_round_sums(
            damage, "attacker_steamid", "dmg_health", sum_column="damage_dealt"
        ),
        player_round_sums(
            damage, "user_steamid", "dmg_health", sum_column="damage_taken"
        ),
        player_round_counts(shots, "user_steamid", count_column="shots"),
    ]

    if not normal_kills.empty and "headshot" in normal_kills.columns:
        headshot_kills = normal_kills[truthy_series(normal_kills["headshot"])].copy()
    else:
        headshot_kills = pd.DataFrame()
    aggregates.append(
        player_round_counts(
            headshot_kills,
            "attacker_steamid",
            count_column="headshot_kills",
        )
    )

    if not bomb_events.empty and "event_name" in bomb_events.columns:
        event_names = bomb_events["event_name"].astype("string")
        plants = bomb_events[event_names == "bomb_planted"].copy()
        defuses = bomb_events[event_names == "bomb_defused"].copy()
    else:
        plants = pd.DataFrame()
        defuses = pd.DataFrame()
    aggregates.extend(
        [
            player_round_counts(plants, "user_steamid", count_column="bomb_plants"),
            player_round_counts(defuses, "user_steamid", count_column="bomb_defuses"),
        ]
    )

    for aggregate in aggregates:
        if aggregate.empty:
            continue
        stats = stats.merge(aggregate, on=["round_number", "steamid"], how="left")

    atomic_columns = [
        "kills",
        "deaths",
        "suicides",
        "team_deaths",
        "assists",
        "damage_dealt",
        "damage_taken",
        "headshot_kills",
        "shots",
        "bomb_plants",
        "bomb_defuses",
    ]
    for column in atomic_columns:
        if column not in stats.columns:
            stats[column] = 0
        stats[column] = (
            pd.to_numeric(stats[column], errors="coerce").fillna(0).astype(int)
        )

    stats = apply_round_end_survival(stats, rounds, read_player_core_states(raw_dir))
    return (
        stats[PLAYER_ROUND_STATS_COLUMNS]
        .sort_values(["round_number", "team_number", "steamid"], na_position="last")
        .reset_index(drop=True)
    )


def apply_round_end_survival(
    stats: pd.DataFrame, rounds: pd.DataFrame, player_core: pd.DataFrame
) -> pd.DataFrame:
    """Set per-round survival from the last core tick at or before round close."""
    stats = stats.copy()
    stats["survived"] = stats["deaths"] == 0

    tick_sources = pd.Series(False, index=stats.index)
    if (
        not stats.empty
        and not rounds.empty
        and not player_core.empty
        and {"round_number", "steamid"} <= set(stats.columns)
        and {"round_number", "round_close_tick"} <= set(rounds.columns)
        and {"tick", "steamid", "is_alive_normalized"} <= set(player_core.columns)
    ):
        close_ticks = rounds[["round_number", "round_close_tick"]].copy()
        close_ticks["round_close_tick"] = pd.to_numeric(
            close_ticks["round_close_tick"], errors="coerce"
        )
        close_ticks = close_ticks.dropna(subset=["round_number", "round_close_tick"])
        if not close_ticks.empty:
            close_ticks["round_close_tick"] = close_ticks["round_close_tick"].astype(
                int
            )
            round_players = (
                stats.reset_index(names="stats_index")[
                    ["stats_index", "round_number", "steamid"]
                ]
                .merge(close_ticks, on="round_number", how="left")
                .dropna(subset=["round_close_tick", "steamid"])
            )
            core = player_core[["tick", "steamid", "is_alive_normalized"]].copy()
            core["tick"] = pd.to_numeric(core["tick"], errors="coerce")
            core = core.dropna(subset=["tick", "steamid", "is_alive_normalized"])
            if not round_players.empty and not core.empty:
                round_players["round_close_tick"] = round_players[
                    "round_close_tick"
                ].astype(int)
                core["tick"] = core["tick"].astype(int)
                round_players = round_players.sort_values(
                    ["round_close_tick", "steamid", "stats_index"]
                )
                core = core.sort_values(["tick", "steamid"])
                end_snapshots = pd.merge_asof(
                    round_players,
                    core,
                    left_on="round_close_tick",
                    right_on="tick",
                    by="steamid",
                    direction="backward",
                    allow_exact_matches=True,
                )
                end_snapshots = end_snapshots.dropna(
                    subset=["tick", "is_alive_normalized"]
                )
                if not end_snapshots.empty:
                    alive = (
                        end_snapshots["is_alive_normalized"].fillna(False).astype(bool)
                    )
                    snapshot_indices = end_snapshots["stats_index"].astype(int)
                    stats.loc[snapshot_indices, "survived"] = alive.to_numpy()
                    tick_sources.loc[snapshot_indices] = True

    PLAYER_ROUND_SURVIVAL_DIAGNOSTICS.clear()
    PLAYER_ROUND_SURVIVAL_DIAGNOSTICS.update(
        {
            "survived_source_ticks": int(tick_sources.sum()),
            "survived_source_death_fallback": int((~tick_sources).sum()),
        }
    )
    return stats


def write_table(df: pd.DataFrame, name: str, output_dir: Path) -> TableResult:
    path = output_dir / f"{name}.csv"
    df.to_csv(path, index=False)
    return TableResult(name=name, path=path, rows=len(df), columns=list(df.columns))


def write_summary(results: list[TableResult], raw_dir: Path, output_dir: Path) -> None:
    summary = {
        "built_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "raw_input_directory": ".",
        "derived_output_directory": debug_pack_source_path(output_dir, raw_dir),
        "tables": [
            {
                "name": result.name,
                "relative_path": debug_pack_source_path(result.path, raw_dir),
                "rows": result.rows,
                "columns": result.columns,
            }
            for result in results
        ],
        "raw_directories_left_read_only": ["meta", "events", "ticks", "errors"],
        "identifier_normalization": IDENTIFIER_DIAGNOSTICS,
        "round_outcome_validation": ROUND_OUTCOME_DIAGNOSTICS,
        "player_round_side_sources": PLAYER_ROUND_SIDE_DIAGNOSTICS,
        "player_round_participation": PLAYER_ROUND_PARTICIPATION_DIAGNOSTICS,
        "survived_source_ticks": PLAYER_ROUND_SURVIVAL_DIAGNOSTICS.get(
            "survived_source_ticks", 0
        ),
        "survived_source_death_fallback": PLAYER_ROUND_SURVIVAL_DIAGNOSTICS.get(
            "survived_source_death_fallback", 0
        ),
        "weapon_fire_filter": WEAPON_FIRE_DIAGNOSTICS,
    }
    (output_dir / "derived_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def write_debug_pack(
    results: list[TableResult], output_dir: Path, debug_dir: Path, sample_rows: int
) -> None:
    same_as_output = debug_dir.resolve() == output_dir.resolve()
    if debug_dir.exists() and not same_as_output:
        shutil.rmtree(debug_dir)
    samples_dir = debug_dir / "samples"
    if samples_dir.exists():
        shutil.rmtree(samples_dir)
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
                "source_path": relative_path_or_posix(result.path, output_dir.parent),
                "sample": sample_path.relative_to(debug_dir).as_posix(),
            }
        )

    summary = {
        "built_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source_derived_directory": relative_path_or_posix(output_dir, output_dir.parent),
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
    PLAYER_ROUND_SIDE_DIAGNOSTICS.clear()
    PLAYER_ROUND_SIDE_DIAGNOSTICS.update({"tick_data_rows": 0, "fallback_rows": 0})
    PLAYER_ROUND_PARTICIPATION_DIAGNOSTICS.clear()
    PLAYER_ROUND_PARTICIPATION_DIAGNOSTICS.update(
        {
            "participation_source": "fallback_all_players",
            "tick_participation_rows": 0,
            "fallback_rows": 0,
            "filtered_rows": 0,
            "rounds_with_tick_participants": 0,
            "rounds_with_fallback_all_players": 0,
        }
    )
    PLAYER_ROUND_SURVIVAL_DIAGNOSTICS.clear()
    PLAYER_ROUND_SURVIVAL_DIAGNOSTICS.update(
        {"survived_source_ticks": 0, "survived_source_death_fallback": 0}
    )
    WEAPON_FIRE_DIAGNOSTICS.clear()
    WEAPON_FIRE_DIAGNOSTICS.update(
        {
            "weapon_fire_rows": 0,
            "firearm_shot_rows": 0,
            "non_firearm_action_rows": 0,
            "non_firearm_weapons": {},
        }
    )

    players = build_players(raw_dir)
    rounds = build_rounds(raw_dir)
    player_round_sides = build_player_round_sides(raw_dir, rounds)
    weapon_actions = build_weapon_actions(raw_dir, rounds)
    tables = {
        "players": players,
        "rounds": rounds,
        "round_outcomes": build_round_outcomes(raw_dir, rounds),
        "kills": build_kills(raw_dir, rounds, player_round_sides),
        "damage": build_damage(raw_dir, rounds),
        "shots": build_shots(raw_dir, rounds, weapon_actions),
        "weapon_actions": weapon_actions,
        "bomb_events": build_bomb_events(raw_dir, rounds),
    }
    tables["player_round_stats"] = build_player_round_stats(
        raw_dir,
        tables["players"],
        tables["rounds"],
        player_round_sides,
        tables["kills"],
        tables["damage"],
        tables["shots"],
        tables["bomb_events"],
    )

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
