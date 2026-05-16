import argparse
import json
from importlib import metadata
from pathlib import Path

pd = None
DemoParser = None


METADATA_EXPORTS = {
    "parse_header": ("header", "json"),
    "parse_convars": ("convars", "json"),
    "parse_player_info": ("player_info", "csv"),
    "parse_grenades": ("grenades", "csv"),
    "parse_item_drops": ("item_drops", "csv"),
    "parse_skins": ("skins", "csv"),
    "parse_chat_messages": ("chat_messages", "csv"),
}

TICK_GROUPS = {
    "ticks_player_core": [
        "steamid",
        "name",
        "team_name",
        "team_num",
        "health",
        "armor",
        "has_helmet",
        "has_defuser",
        "is_alive",
        "life_state",
        "is_connected",
        "ping",
        "score",
    ],
    "ticks_view_and_movement": [
        "X",
        "Y",
        "Z",
        "velocity_X",
        "velocity_Y",
        "velocity_Z",
        "pitch",
        "yaw",
        "eye_angle_x",
        "eye_angle_y",
        "eye_angle_z",
        "agent_skin",
    ],
    "ticks_buttons": [
        "buttons",
        "is_walking",
        "is_scoped",
        "is_ducking",
        "is_defusing",
        "is_planting",
        "is_grabbing_hostage",
        "is_rescuing_hostage",
    ],
    "ticks_weapon": [
        "active_weapon_name",
        "active_weapon_original_owner",
        "inventory",
        "weapon_skin",
        "weapon_name",
        "weapon_paint_id",
        "weapon_original_owner_xuid",
        "weapon_zoom_level",
        "ammo_clip",
        "ammo_clip_max",
    ],
    "ticks_damage_and_status": [
        "health",
        "armor",
        "flash_duration",
        "flash_max_alpha",
        "is_blinded",
        "is_airborne",
        "move_type",
        "duck_amount",
        "duck_speed",
    ],
    "ticks_game_state": [
        "game_time",
        "round_start_time",
        "round_num",
        "tick",
        "seconds",
        "is_freeze_period",
        "is_warmup_period",
        "is_terrorist_timeout",
        "is_ct_timeout",
        "is_technical_timeout",
        "is_waiting_for_resume",
    ],
    "ticks_aggregate": [
        "total_rounds_played",
        "score",
        "kills_total",
        "deaths_total",
        "assists_total",
        "mvps",
        "cash_spent_this_round",
        "cash_spent_total",
        "money",
        "current_equip_value",
        "round_start_equip_value",
        "freezetime_end_equip_value",
    ],
    "ticks_usercommands": [
        "usercmd_viewangle_x",
        "usercmd_viewangle_y",
        "usercmd_forwardmove",
        "usercmd_leftmove",
        "usercmd_upmove",
        "usercmd_buttons",
        "usercmd_impulse",
        "usercmd_weaponselect",
        "usercmd_weaponsubtype",
        "usercmd_random_seed",
        "usercmd_mousedx",
        "usercmd_mousedy",
    ],
}

ERROR_FILE_COLUMNS = {
    "failed_events.csv": ["event_name", "error"],
    "failed_tick_groups.csv": ["group", "error", "fields"],
    "failed_meta_methods.csv": ["method", "status", "severity", "error"],
}


def require_runtime_dependencies():
    global pd, DemoParser
    if pd is None:
        import pandas as pandas_module

        pd = pandas_module
    if DemoParser is None:
        from demoparser2 import DemoParser as demo_parser_class

        DemoParser = demo_parser_class


def ensure_dirs(output_dir):
    output_dir = Path(output_dir)
    paths = {
        "output": output_dir,
        "meta": output_dir / "meta",
        "events": output_dir / "events",
        "errors": output_dir / "errors",
        "ticks": output_dir / "ticks",
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    return paths


def save_json(data, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file_obj:
        json.dump(data, file_obj, ensure_ascii=False, indent=2)


def save_dataframe(df, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")




def save_error_csv(rows, path, columns):
    df = pd.DataFrame(rows, columns=columns)
    save_dataframe(df, path)


def validate_demo_path(demo_path):
    demo_path = Path(demo_path)
    if not demo_path.exists():
        raise FileNotFoundError(f"Demo file does not exist: {demo_path}")
    if not demo_path.is_file():
        raise ValueError(f"Demo path is not a file: {demo_path}")
    if demo_path.suffix.lower() != ".dem":
        raise ValueError(f"Demo file must have .dem extension: {demo_path}")
    return demo_path


def get_package_version(package_name):
    try:
        return metadata.version(package_name)
    except metadata.PackageNotFoundError:
        return "not_installed"


def call_parser_method(parser, method_name):
    if not hasattr(parser, method_name):
        raise AttributeError(f"Parser method not found: {method_name}")
    method = getattr(parser, method_name)
    return method()


def save_parser_result(result, path):
    path = Path(path)
    if isinstance(result, pd.DataFrame):
        save_dataframe(result, path)
        return path

    json_path = path if path.suffix.lower() == ".json" else path.with_suffix(".json")
    save_json(make_json_safe(result), json_path)
    return json_path


def make_json_safe(data):
    if isinstance(data, pd.DataFrame):
        return data.to_dict(orient="records")
    if isinstance(data, pd.Series):
        return data.to_dict()
    if isinstance(data, dict):
        return {str(key): make_json_safe(value) for key, value in data.items()}
    if isinstance(data, (list, tuple, set)):
        return [make_json_safe(value) for value in data]
    if hasattr(data, "item"):
        try:
            return data.item()
        except (TypeError, ValueError):
            pass
    if hasattr(data, "isoformat"):
        return data.isoformat()
    try:
        json.dumps(data)
        return data
    except TypeError:
        return str(data)


def export_metadata(parser, paths):
    meta_results = []
    failures = []

    for method_name, (file_stem, extension) in METADATA_EXPORTS.items():
        target_path = paths["meta"] / f"{file_stem}.{extension}"
        try:
            result = call_parser_method(parser, method_name)
            saved_path = save_parser_result(result, target_path)
            meta_results.append(
                {
                    "method": method_name,
                    "status": "ok",
                    "path": str(saved_path),
                    "rows": len(result) if isinstance(result, pd.DataFrame) else None,
                }
            )
        except AttributeError as exc:
            error = str(exc)
            failures.append(
                {
                    "method": method_name,
                    "status": "method_not_found",
                    "severity": "non_critical",
                    "error": error,
                }
            )
            meta_results.append(
                {
                    "method": method_name,
                    "status": "method_not_found",
                    "severity": "non_critical",
                    "path": str(target_path),
                    "error": error,
                }
            )
        except Exception as exc:
            error = str(exc)
            failures.append(
                {
                    "method": method_name,
                    "status": "error",
                    "severity": "non_critical",
                    "error": error,
                }
            )
            meta_results.append(
                {
                    "method": method_name,
                    "status": "error",
                    "severity": "non_critical",
                    "path": str(target_path),
                    "error": error,
                }
            )

    save_error_csv(
        failures,
        paths["errors"] / "failed_meta_methods.csv",
        ERROR_FILE_COLUMNS["failed_meta_methods.csv"],
    )

    return meta_results


def get_game_events(parser):
    if hasattr(parser, "list_game_events"):
        events = parser.list_game_events()
    elif hasattr(parser, "Sequence_game_events"):
        events = parser.Sequence_game_events()
    else:
        return [], "method_not_found"

    if isinstance(events, pd.DataFrame):
        if "event_name" in events.columns:
            return events["event_name"].dropna().astype(str).tolist(), "ok"
        if len(events.columns) > 0:
            return events.iloc[:, 0].dropna().astype(str).tolist(), "ok"
        return [], "ok"

    return [str(event) for event in events], "ok"


def export_events(parser, event_names, paths):
    failures = []
    exported = []

    for event_name in event_names:
        try:
            if hasattr(parser, "parse_event"):
                result = parser.parse_event(event_name)
            elif hasattr(parser, "parse_events"):
                result = parser.parse_events([event_name])
            else:
                raise AttributeError("Parser event method not found: parse_event/parse_events")

            saved_path = save_parser_result(result, paths["events"] / f"{event_name}.csv")
            exported.append(
                {
                    "event_name": event_name,
                    "status": "ok",
                    "path": str(saved_path),
                    "rows": len(result) if isinstance(result, pd.DataFrame) else None,
                }
            )
        except Exception as exc:
            failures.append({"event_name": event_name, "error": str(exc)})
            exported.append({"event_name": event_name, "status": "error", "error": str(exc)})

    save_error_csv(
        failures,
        paths["errors"] / "failed_events.csv",
        ERROR_FILE_COLUMNS["failed_events.csv"],
    )

    return exported, failures


def export_entity_fields(parser, paths):
    if not hasattr(parser, "list_entity_values"):
        return {"status": "method_not_found"}

    try:
        result = parser.list_entity_values()
        saved_path = save_parser_result(result, paths["output"] / "entity_fields_frequency.csv")
        return {
            "status": "ok",
            "path": str(saved_path),
            "rows": len(result) if isinstance(result, pd.DataFrame) else None,
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


def export_tick_groups(parser, paths):
    failures = []
    results = []

    if not hasattr(parser, "parse_ticks"):
        for group_name, fields in TICK_GROUPS.items():
            failures.append({"group": group_name, "error": "method_not_found", "fields": ",".join(fields)})
            results.append({"group": group_name, "status": "error", "error": "method_not_found", "fields": fields})
        save_error_csv(
            failures,
            paths["errors"] / "failed_tick_groups.csv",
            ERROR_FILE_COLUMNS["failed_tick_groups.csv"],
        )
        return results, failures

    for group_name, fields in TICK_GROUPS.items():
        target_path = paths["ticks"] / f"{group_name}.csv"
        try:
            result = parser.parse_ticks(fields)
            saved_path = save_parser_result(result, target_path)
            results.append(
                {
                    "group": group_name,
                    "status": "ok",
                    "path": str(saved_path),
                    "rows": len(result) if isinstance(result, pd.DataFrame) else None,
                    "fields": fields,
                }
            )
        except Exception as exc:
            failures.append({"group": group_name, "error": str(exc), "fields": ",".join(fields)})
            results.append(
                {
                    "group": group_name,
                    "status": "error",
                    "error": str(exc),
                    "fields": fields,
                }
            )

    save_error_csv(
        failures,
        paths["errors"] / "failed_tick_groups.csv",
        ERROR_FILE_COLUMNS["failed_tick_groups.csv"],
    )

    return results, failures


def count_csv_rows(csv_path):
    with Path(csv_path).open("r", encoding="utf-8-sig", newline="") as file_obj:
        line_count = sum(1 for _ in file_obj)
    return max(line_count - 1, 0)


def read_csv_columns(csv_path):
    return pd.read_csv(csv_path, nrows=0).columns.tolist()


def csv_info(csv_path):
    csv_path = Path(csv_path)
    if not csv_path.exists():
        return {"exists": False, "rows": None, "columns": []}
    try:
        return {
            "exists": True,
            "rows": count_csv_rows(csv_path),
            "columns": read_csv_columns(csv_path),
        }
    except Exception as exc:
        return {"exists": True, "rows": None, "columns": [], "read_error": str(exc)}


def first_existing_csv(output_dir, relative_paths):
    for relative_path in relative_paths:
        csv_path = output_dir / relative_path
        if csv_path.exists():
            info = csv_info(csv_path)
            info["path"] = str(relative_path)
            return info
    return {"exists": False, "path": None, "rows": None, "columns": []}


def build_light_validation_report(output_dir):
    output_dir = Path(output_dir)
    player_info = csv_info(output_dir / "meta" / "player_info.csv")
    player_death = csv_info(output_dir / "events" / "player_death.csv")
    player_hurt = csv_info(output_dir / "events" / "player_hurt.csv")
    weapon_fire = csv_info(output_dir / "events" / "weapon_fire.csv")
    ticks_aggregate = csv_info(output_dir / "ticks" / "ticks_aggregate.csv")
    round_start = first_existing_csv(
        output_dir,
        [
            Path("events") / "round_start.csv",
            Path("events") / "round_prestart.csv",
            Path("events") / "round_poststart.csv",
            Path("events") / "round_freeze_end.csv",
        ],
    )
    round_end = first_existing_csv(
        output_dir,
        [
            Path("events") / "round_end.csv",
            Path("events") / "round_officially_ended.csv",
            Path("events") / "cs_win_panel_match.csv",
        ],
    )

    expected_paths = [
        output_dir / "match_summary.json",
        output_dir / "game_events_list.csv",
        output_dir / "meta" / "header.json",
        output_dir / "meta" / "player_info.csv",
        output_dir / "events",
        output_dir / "ticks",
        output_dir / "errors",
        output_dir / "errors" / "failed_events.csv",
        output_dir / "errors" / "failed_tick_groups.csv",
        output_dir / "errors" / "failed_meta_methods.csv",
    ]
    checks = {str(path.relative_to(output_dir)): path.exists() for path in expected_paths}

    csv_files = []
    for csv_path in sorted(output_dir.rglob("*.csv")):
        item = {"path": str(csv_path.relative_to(output_dir))}
        item.update(csv_info(csv_path))
        csv_files.append(item)

    json_files = [
        {"path": str(json_path.relative_to(output_dir))}
        for json_path in sorted(output_dir.rglob("*.json"))
    ]
    available_files = [
        str(path.relative_to(output_dir))
        for path in sorted(output_dir.rglob("*"))
        if path.is_file()
    ][:100]

    report = {
        "output_dir": str(output_dir),
        "checks": checks,
        "players_count": player_info["rows"],
        "player_info_columns": player_info["columns"],
        "player_death_rows": player_death["rows"],
        "player_death_columns": player_death["columns"],
        "player_hurt_rows": player_hurt["rows"],
        "player_hurt_columns": player_hurt["columns"],
        "weapon_fire_rows": weapon_fire["rows"],
        "weapon_fire_columns": weapon_fire["columns"],
        "round_start_rows": round_start["rows"],
        "round_start_source": round_start["path"],
        "round_end_rows": round_end["rows"],
        "round_end_source": round_end["path"],
        "ticks_aggregate_rows": ticks_aggregate["rows"],
        "ticks_aggregate_columns": ticks_aggregate["columns"],
        "available_files": available_files,
        "csv_files": csv_files,
        "json_files": json_files,
    }
    report["status"] = "ok" if all(checks.values()) else "warning"
    save_json(report, output_dir / "light_validation_report.json")
    return report


def add_metadata_fallback_notes(summary, event_names):
    event_names = set(event_names)
    fallback_by_method = {
        "parse_chat_messages": ("chat_message", "Chat messages may be available in events/chat_message.csv."),
        "parse_convars": ("server_cvar", "Convars may be available in events/server_cvar.csv."),
    }
    for item in summary["metadata"]:
        fallback = fallback_by_method.get(item.get("method"))
        if fallback and item.get("status") == "method_not_found" and fallback[0] in event_names:
            item["fallback_note"] = fallback[1]


def parse_demo(demo_path, output_dir):
    demo_path = validate_demo_path(demo_path)
    require_runtime_dependencies()
    output_dir = Path(output_dir)
    paths = ensure_dirs(output_dir)

    parser = DemoParser(str(demo_path))
    summary = {
        "demo_path": str(demo_path),
        "output_dir": str(output_dir),
        "package_versions": {
            "demoparser2": get_package_version("demoparser2"),
            "pandas": get_package_version("pandas"),
        },
        "metadata": [],
        "voice": {
            "method_exists": hasattr(parser, "parse_voice"),
            "status": "skipped",
        },
        "game_events": {"status": None, "count": 0, "exported": 0, "failed": 0},
        "entity_fields": {},
        "tick_groups": {"status": None, "exported": 0, "failed": 0, "groups": []},
    }

    summary["metadata"] = export_metadata(parser, paths)

    event_names, events_status = get_game_events(parser)
    summary["game_events"]["status"] = events_status
    summary["game_events"]["count"] = len(event_names)
    save_dataframe(pd.DataFrame({"event_name": event_names}), output_dir / "game_events_list.csv")

    exported_events, failed_events = export_events(parser, event_names, paths)
    summary["game_events"]["exported"] = len([item for item in exported_events if item["status"] == "ok"])
    summary["game_events"]["failed"] = len(failed_events)
    summary["game_events"]["items"] = exported_events
    add_metadata_fallback_notes(summary, event_names)

    summary["entity_fields"] = export_entity_fields(parser, paths)

    tick_results, failed_tick_groups = export_tick_groups(parser, paths)
    summary["tick_groups"]["groups"] = tick_results
    summary["tick_groups"]["exported"] = len([item for item in tick_results if item["status"] == "ok"])
    summary["tick_groups"]["failed"] = len(failed_tick_groups)
    summary["tick_groups"]["status"] = "error" if failed_tick_groups else "ok"

    save_json(summary, output_dir / "match_summary.json")
    build_light_validation_report(output_dir)
    return summary


def main():
    argument_parser = argparse.ArgumentParser(description="Export CS demo data with demoparser2.")
    argument_parser.add_argument("--demo", required=True, help="Path to a .dem file.")
    argument_parser.add_argument("--output", default="output", help="Output directory. Default: output")
    args = argument_parser.parse_args()

    try:
        parse_demo(Path(args.demo), Path(args.output))
    except (FileNotFoundError, ValueError) as exc:
        argument_parser.error(str(exc))


if __name__ == "__main__":
    main()
