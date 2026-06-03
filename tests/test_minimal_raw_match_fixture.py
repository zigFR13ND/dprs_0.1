from pathlib import Path
import sys

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.build_derived import (
    PLAYER_ROUND_SURVIVAL_DIAGNOSTICS,
    WEAPON_FIRE_DIAGNOSTICS,
    build_bomb_events,
    build_damage,
    build_kills,
    build_player_round_sides,
    build_player_round_stats,
    build_players,
    build_rounds,
    build_shots,
    build_weapon_actions,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "minimal_raw_match"


def _derived_inputs():
    rounds = build_rounds(FIXTURE_DIR)
    player_round_sides = build_player_round_sides(FIXTURE_DIR, rounds)
    kills = build_kills(FIXTURE_DIR, rounds, player_round_sides)
    damage = build_damage(FIXTURE_DIR, rounds, player_round_sides)
    weapon_actions = build_weapon_actions(FIXTURE_DIR, rounds)
    shots = build_shots(FIXTURE_DIR, rounds, weapon_actions)
    bomb_events = build_bomb_events(FIXTURE_DIR, rounds)
    return rounds, player_round_sides, kills, damage, weapon_actions, shots, bomb_events


def test_minimal_raw_match_assigns_round_numbers_from_csv_markers():
    rounds, player_round_sides, kills, damage, weapon_actions, shots, bomb_events = (
        _derived_inputs()
    )

    assert rounds["round_number"].tolist() == [1, 2]
    assert rounds["prestart_tick"].tolist() == [100, 300]
    assert rounds["freeze_end_tick"].tolist() == [120, 320]

    assert kills.set_index("tick").loc[150, "round_number"] == 1
    assert kills.set_index("tick").loc[350, "round_number"] == 2
    assert damage.set_index("tick").loc[130, "round_number"] == 1
    assert weapon_actions.set_index("tick").loc[330, "round_number"] == 2
    assert shots.set_index("tick").loc[330, "round_number"] == 2
    assert bomb_events.set_index("tick").loc[200, "round_number"] == 1
    assert bomb_events.set_index("tick").loc[460, "round_number"] == 2


def test_minimal_raw_match_derives_side_swap_from_ticks():
    rounds = build_rounds(FIXTURE_DIR)
    player_round_sides = build_player_round_sides(FIXTURE_DIR, rounds)

    sides = player_round_sides.set_index(["round_number", "steamid"])
    assert sides.loc[(1, "A"), "side"] == "T"
    assert sides.loc[(1, "B"), "side"] == "CT"
    assert sides.loc[(2, "A"), "side"] == "CT"
    assert sides.loc[(2, "B"), "side"] == "T"


def test_minimal_raw_match_uses_ticks_for_survival():
    rounds, player_round_sides, kills, damage, _, shots, bomb_events = _derived_inputs()
    stats = build_player_round_stats(
        FIXTURE_DIR,
        build_players(FIXTURE_DIR),
        rounds,
        player_round_sides,
        kills=kills,
        damage=damage,
        shots=shots,
        bomb_events=bomb_events,
    )

    round_one = stats[stats["round_number"] == 1].set_index("steamid")
    assert bool(round_one.loc["A", "survived"])
    assert not bool(round_one.loc["D", "survived"])
    assert round_one.loc["D", "deaths"] == 0
    assert PLAYER_ROUND_SURVIVAL_DIAGNOSTICS["survived_source_ticks"] >= 4


def test_minimal_raw_match_normalizes_and_filters_kills_after_side_swap():
    rounds = build_rounds(FIXTURE_DIR)
    player_round_sides = build_player_round_sides(FIXTURE_DIR, rounds)
    kills = build_kills(FIXTURE_DIR, rounds, player_round_sides).set_index("tick")

    assert kills.loc[150, "user_steamid"] == "B"
    assert kills.loc[150, "attacker_steamid"] == "A"
    assert bool(kills.loc[150, "has_attacker"])
    assert not bool(kills.loc[150, "is_suicide"])
    assert not bool(kills.loc[150, "is_teamkill"])
    assert bool(kills.loc[150, "is_opening_kill"])

    assert kills.index.tolist() == [150, 350]
    assert kills.loc[350, "user_steamid"] == "A"
    assert kills.loc[350, "attacker_steamid"] == "B"
    assert bool(kills.loc[350, "has_attacker"])
    assert not bool(kills.loc[350, "is_suicide"])
    assert not bool(kills.loc[350, "is_teamkill"])


def test_minimal_raw_match_classifies_damage_from_ticks_sides_and_live_window():
    rounds = build_rounds(FIXTURE_DIR)
    player_round_sides = build_player_round_sides(FIXTURE_DIR, rounds)
    damage = build_damage(FIXTURE_DIR, rounds, player_round_sides).set_index("tick")

    assert bool(damage.loc[130, "is_enemy_damage"])
    assert bool(damage.loc[130, "is_live_phase_damage"])
    assert bool(damage.loc[140, "is_team_damage"])
    assert bool(damage.loc[145, "is_self_damage"])
    assert bool(damage.loc[145, "is_grenade_or_fire_damage"])
    assert not bool(damage.loc[110, "is_live_phase_damage"])
    assert bool(damage.loc[330, "is_enemy_damage"])
    assert bool(damage.loc[330, "is_grenade_or_fire_damage"])


def test_minimal_raw_match_filters_firearm_shots_only():
    rounds = build_rounds(FIXTURE_DIR)
    weapon_actions = build_weapon_actions(FIXTURE_DIR, rounds)
    shots = build_shots(FIXTURE_DIR, rounds, weapon_actions)

    assert weapon_actions["weapon"].tolist() == [
        "ak47",
        "hegrenade",
        "weapon_m4a1_silencer",
        "flashbang",
    ]
    assert shots["weapon"].tolist() == ["ak47", "weapon_m4a1_silencer"]
    assert WEAPON_FIRE_DIAGNOSTICS["weapon_fire_rows"] == 4
    assert WEAPON_FIRE_DIAGNOSTICS["firearm_shot_rows"] == 2
