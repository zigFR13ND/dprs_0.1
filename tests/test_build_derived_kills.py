from pathlib import Path
import sys

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.build_derived import (
    build_clutch_attempts,
    build_kills,
    build_player_round_stats,
)


def _rounds() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "round_number": 1,
                "prestart_tick": 100,
                "freeze_end_tick": 110,
                "round_close_tick": 250,
                "assignment_end_tick": 300,
            }
        ]
    )


def _player_round_sides() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"round_number": 1, "steamid": "A", "team_number": 2},
            {"round_number": 1, "steamid": "C", "team_number": 2},
            {"round_number": 1, "steamid": "B", "team_number": 3},
            {"round_number": 1, "steamid": "D", "team_number": 3},
        ]
    )


def _players() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"steamid": "A", "name": "Alpha", "team_number": 2},
            {"steamid": "C", "name": "Charlie", "team_number": 2},
            {"steamid": "B", "name": "Bravo", "team_number": 3},
            {"steamid": "D", "name": "Delta", "team_number": 3},
        ]
    )


def _write_player_death(raw_dir: Path, rows: list[dict[str, object]]) -> None:
    events_dir = raw_dir / "events"
    events_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(events_dir / "player_death.csv", index=False)


def test_build_kills_sorts_and_marks_trade_kills_within_tick_window(tmp_path):
    _write_player_death(
        tmp_path,
        [
            {
                "tick": 180,
                "user_steamid": "B",
                "attacker_steamid": "A",
                "raw_marker": "trade_kill",
            },
            {
                "tick": 150,
                "user_steamid": "C",
                "attacker_steamid": "B",
                "raw_marker": "traded_death",
            },
            {
                "tick": 225,
                "user_steamid": "D",
                "attacker_steamid": "A",
                "raw_marker": "late_non_trade",
            },
        ],
    )

    kills = build_kills(
        tmp_path, _rounds(), _player_round_sides(), trade_tick_window=40
    )

    assert kills["raw_marker"].tolist() == [
        "traded_death",
        "trade_kill",
        "late_non_trade",
    ]
    rows = kills.set_index("raw_marker")
    assert not bool(rows.loc["traded_death", "is_trade_kill"])
    assert bool(rows.loc["trade_kill", "is_trade_kill"])
    assert rows.loc["trade_kill", "traded_victim_steamid"] == "C"
    assert rows.loc["trade_kill", "trade_delay_ticks"] == 30
    assert not bool(rows.loc["late_non_trade", "is_trade_kill"])


def test_player_round_stats_counts_trade_kills_and_traded_deaths_from_built_kills(
    tmp_path,
):
    _write_player_death(
        tmp_path,
        [
            {
                "tick": 150,
                "user_steamid": "C",
                "attacker_steamid": "B",
            },
            {
                "tick": 180,
                "user_steamid": "B",
                "attacker_steamid": "A",
            },
        ],
    )
    kills = build_kills(
        tmp_path, _rounds(), _player_round_sides(), trade_tick_window=40
    )

    stats = build_player_round_stats(
        tmp_path,
        _players(),
        _rounds(),
        _player_round_sides(),
        kills=kills,
        damage=pd.DataFrame(),
        shots=pd.DataFrame(),
        bomb_events=pd.DataFrame(),
    ).set_index("steamid")

    assert stats.loc["A", "trade_kills"] == 1
    assert stats.loc["C", "traded_deaths"] == 1
    assert stats.loc["B", "trade_kills"] == 0
    assert stats.loc["D", "traded_deaths"] == 0


def test_build_kills_filters_invalid_kills_and_marks_opening_kill(tmp_path):
    _write_player_death(
        tmp_path,
        [
            {
                "tick": 105,
                "user_steamid": "B",
                "attacker_steamid": "A",
                "raw_marker": "before_live",
            },
            {
                "tick": 120,
                "user_steamid": "A",
                "attacker_steamid": "A",
                "raw_marker": "suicide",
            },
            {
                "tick": 130,
                "user_steamid": "C",
                "attacker_steamid": "A",
                "raw_marker": "teamkill",
            },
            {
                "tick": 140,
                "user_steamid": "D",
                "attacker_steamid": "A",
                "raw_marker": "valid_opening",
            },
            {
                "tick": 150,
                "user_steamid": "B",
                "attacker_steamid": "A",
                "raw_marker": "valid_later",
            },
        ],
    )

    kills = build_kills(tmp_path, _rounds(), _player_round_sides())

    assert kills["raw_marker"].tolist() == [
        "before_live",
        "valid_opening",
        "valid_later",
    ]
    assert kills["is_opening_kill"].tolist() == [False, True, False]
    assert not kills[["is_suicide", "is_teamkill", "is_world"]].any().any()


def test_player_round_stats_counts_opening_kills_and_deaths(tmp_path):
    _write_player_death(
        tmp_path,
        [
            {
                "tick": 140,
                "user_steamid": "C",
                "attacker_steamid": "B",
            },
            {
                "tick": 150,
                "user_steamid": "B",
                "attacker_steamid": "A",
            },
        ],
    )
    kills = build_kills(tmp_path, _rounds(), _player_round_sides())

    stats = build_player_round_stats(
        tmp_path,
        _players(),
        _rounds(),
        _player_round_sides(),
        kills=kills,
        damage=pd.DataFrame(),
        shots=pd.DataFrame(),
        bomb_events=pd.DataFrame(),
    ).set_index("steamid")

    assert stats.loc["B", "opening_kills"] == 1
    assert stats.loc["C", "opening_deaths"] == 1
    assert stats.loc["A", "opening_kills"] == 0
    assert stats.loc["B", "opening_deaths"] == 0


def test_build_clutch_attempts_records_last_alive_state_and_round_result():
    kills = pd.DataFrame(
        [
            {
                "round_number": 1,
                "tick": 120,
                "user_steamid": "C",
                "attacker_steamid": "B",
            },
            {
                "round_number": 1,
                "tick": 140,
                "user_steamid": "D",
                "attacker_steamid": "A",
            },
            {
                "round_number": 1,
                "tick": 160,
                "user_steamid": "B",
                "attacker_steamid": "A",
            },
        ]
    )
    round_outcomes = pd.DataFrame(
        [{"round_number": 1, "winner_side": "T", "winner_team_number": 2}]
    )

    attempts = build_clutch_attempts(
        kills, _rounds(), round_outcomes, _player_round_sides()
    )

    assert attempts.to_dict("records") == [
        {
            "round_number": 1,
            "steamid": "A",
            "side": "T",
            "opponents_alive": 2,
            "start_tick": 120,
            "won": True,
        },
        {
            "round_number": 1,
            "steamid": "B",
            "side": "CT",
            "opponents_alive": 1,
            "start_tick": 140,
            "won": False,
        },
    ]
