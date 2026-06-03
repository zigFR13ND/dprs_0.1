from pathlib import Path
import sys

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.build_derived import build_round_outcomes, build_rounds


def _write_csv(raw_dir: Path, relative: str, rows: list[dict[str, object]]) -> None:
    path = raw_dir / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)


def _write_round_markers(raw_dir: Path) -> None:
    rows = [{"tick": 100}, {"tick": 200}]
    _write_csv(raw_dir, "events/round_prestart.csv", rows)
    _write_csv(raw_dir, "events/round_poststart.csv", [{"tick": 105}, {"tick": 205}])
    _write_csv(raw_dir, "events/round_freeze_end.csv", [{"tick": 110}, {"tick": 210}])


def test_rounds_keep_assignment_boundary_separate_from_missing_actual_end(tmp_path):
    _write_round_markers(tmp_path)
    _write_csv(
        tmp_path,
        "meta/player_info.csv",
        [
            {"steamid": "T1", "team_number": 2},
            {"steamid": "CT1", "team_number": 3},
            {"steamid": "CT2", "team_number": 3},
        ],
    )
    _write_csv(tmp_path, "events/player_death.csv", [{"tick": 150, "user_steamid": "CT1"}])

    rounds = build_rounds(tmp_path)
    first_round = rounds.set_index("round_number").loc[1]

    assert first_round["assignment_end_tick"] == 200
    assert first_round["next_prestart_tick"] == 200
    assert pd.isna(first_round["inferred_round_end_tick"])
    assert first_round["round_end_source"] == "missing"

    outcomes = build_round_outcomes(tmp_path, rounds).set_index("round_number")
    assert outcomes.loc[1, "end_tick"] == 200
    assert pd.isna(outcomes.loc[1, "inferred_round_end_tick"])
    assert outcomes.loc[1, "round_end_source"] == "assignment_boundary_fallback"


def test_rounds_use_last_death_marker_only_for_elimination(tmp_path):
    _write_round_markers(tmp_path)
    _write_csv(
        tmp_path,
        "meta/player_info.csv",
        [
            {"steamid": "T1", "team_number": 2},
            {"steamid": "CT1", "team_number": 3},
        ],
    )
    _write_csv(tmp_path, "events/player_death.csv", [{"tick": 150, "user_steamid": "T1"}])

    rounds = build_rounds(tmp_path).set_index("round_number")

    assert rounds.loc[1, "assignment_end_tick"] == 200
    assert rounds.loc[1, "inferred_round_end_tick"] == 150
    assert rounds.loc[1, "round_end_source"] == "last_valid_death"


def test_round_outcomes_prefers_factual_bomb_tick_over_assignment_boundary(tmp_path):
    _write_round_markers(tmp_path)
    _write_csv(tmp_path, "events/bomb_defused.csv", [{"tick": 150}])

    rounds = build_rounds(tmp_path)
    outcomes = build_round_outcomes(tmp_path, rounds).set_index("round_number")

    assert outcomes.loc[1, "end_tick"] == 150
    assert outcomes.loc[1, "inferred_round_end_tick"] == 150
    assert outcomes.loc[1, "round_end_source"] == "bomb_defused"
