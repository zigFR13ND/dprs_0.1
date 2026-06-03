from pathlib import Path
import sys

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.build_derived import build_damage, build_player_round_stats


def _rounds() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "round_number": 1,
                "prestart_tick": 80,
                "freeze_end_tick": 100,
                "round_close_tick": 200,
                "assignment_end_tick": 220,
            }
        ]
    )


def _player_round_sides() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"round_number": 1, "steamid": "A", "team_number": 2},
            {"round_number": 1, "steamid": "B", "team_number": 3},
            {"round_number": 1, "steamid": "C", "team_number": 2},
        ]
    )


def _write_player_hurt(raw_dir: Path) -> None:
    events_dir = raw_dir / "events"
    events_dir.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "tick": 120,
                "user_steamid": "B",
                "attacker_steamid": "A",
                "weapon": "hegrenade",
                "dmg_health": 30,
                "raw_marker": "preserved_enemy_utility_live",
            },
            {
                "tick": 130,
                "user_steamid": "C",
                "attacker_steamid": "A",
                "weapon": "ak47",
                "dmg_health": 10,
                "raw_marker": "preserved_team_live",
            },
            {
                "tick": 140,
                "user_steamid": "A",
                "attacker_steamid": "A",
                "weapon": "inferno",
                "dmg_health": 5,
                "raw_marker": "preserved_self_live",
            },
            {
                "tick": 90,
                "user_steamid": "B",
                "attacker_steamid": "A",
                "weapon": "ak47",
                "dmg_health": 7,
                "raw_marker": "preserved_enemy_freeze",
            },
            {
                "tick": 150,
                "user_steamid": "A",
                "attacker_steamid": "B",
                "weapon": "weapon_molotov",
                "dmg_health": 20,
                "raw_marker": "preserved_enemy_fire_live",
            },
        ]
    ).to_csv(events_dir / "player_hurt.csv", index=False)


def test_build_damage_adds_classification_flags_and_preserves_raw_columns(tmp_path):
    _write_player_hurt(tmp_path)

    damage = build_damage(tmp_path, _rounds(), _player_round_sides())

    assert "raw_marker" in damage.columns
    assert {
        "is_self_damage",
        "is_team_damage",
        "is_enemy_damage",
        "is_grenade_or_fire_damage",
        "is_live_phase_damage",
    } <= set(damage.columns)

    rows = damage.set_index("raw_marker")
    assert bool(rows.loc["preserved_enemy_utility_live", "is_enemy_damage"])
    assert bool(rows.loc["preserved_enemy_utility_live", "is_grenade_or_fire_damage"])
    assert bool(rows.loc["preserved_enemy_utility_live", "is_live_phase_damage"])

    assert bool(rows.loc["preserved_team_live", "is_team_damage"])
    assert not bool(rows.loc["preserved_team_live", "is_enemy_damage"])

    assert bool(rows.loc["preserved_self_live", "is_self_damage"])
    assert not bool(rows.loc["preserved_self_live", "is_team_damage"])
    assert not bool(rows.loc["preserved_self_live", "is_enemy_damage"])

    assert bool(rows.loc["preserved_enemy_freeze", "is_enemy_damage"])
    assert not bool(rows.loc["preserved_enemy_freeze", "is_live_phase_damage"])


def test_player_round_stats_splits_enemy_live_team_self_and_utility_damage(tmp_path):
    _write_player_hurt(tmp_path)
    damage = build_damage(tmp_path, _rounds(), _player_round_sides())
    players = pd.DataFrame(
        [
            {"steamid": "A", "name": "Alpha", "team_number": 2},
            {"steamid": "B", "name": "Bravo", "team_number": 3},
            {"steamid": "C", "name": "Charlie", "team_number": 2},
        ]
    )

    stats = build_player_round_stats(
        tmp_path,
        players,
        _rounds(),
        _player_round_sides(),
        kills=pd.DataFrame(),
        damage=damage,
        shots=pd.DataFrame(),
        bomb_events=pd.DataFrame(),
    ).set_index("steamid")

    assert stats.loc["A", "damage_dealt"] == 30
    assert stats.loc["A", "team_damage_dealt"] == 10
    assert stats.loc["A", "self_damage"] == 5
    assert stats.loc["A", "utility_damage_dealt"] == 30
    assert stats.loc["B", "damage_dealt"] == 20
    assert stats.loc["B", "utility_damage_dealt"] == 20
