import argparse
import json
from importlib import metadata
from pathlib import Path

import pandas as pd
from demoparser2 import DemoParser


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
        "is_alive",
        "life_state",
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
    ],
    "ticks_buttons": [
        "buttons",
        "is_walking",
        "is_scoped",
        "is_ducking",
        "is_defusing",
        "is_planting",
    ],
    "ticks_weapon": [
        "active_weapon_name",
        "active_weapon_original_owner",
        "inventory",
        "weapon_skin",
        "weapon_name",
        "weapon_paint_id",
    ],
    "ticks_damage_and_status": [
        "health",
        "armor",
        "flash_duration",
        "flash_max_alpha",
        "is_blinded",
        "is_airborne",
        "move_type",
    ],
    "ticks_game_state": [
        "game_time",
        "round_start_time",
        "round_num",
        "tick",
        "seconds",
        "is_freeze_period",
        "is_warmup_period",
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
    ],
    "ticks_usercommands": [
        "usercmd_viewangle_x",
        "usercmd_viewangle_y",
        "usercmd_forwardmove",
        "usercmd_leftmove",
        "usercmd_upmove",
        "usercmd_buttons",
        "usercmd_impulse",
    ],
}


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
        except Exception as exc:
            failures.append({"method": method_name, "error": str(exc)})
            meta_results.append(
                {
                    "method": method_name,
                    "status": "error",
                    "path": str(target_path),
                    "error": str(exc),
                }
            )

    if failures:
        save_dataframe(pd.DataFrame(failures), paths["errors"] / "failed_metadata.csv")

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

    if failures:
        save_dataframe(pd.DataFrame(failures), paths["errors"] / "failed_events.csv")

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
        for group_name in TICK_GROUPS:
            failures.append({"group": group_name, "error": "method_not_found"})
            results.append({"group": group_name, "status": "error", "error": "method_not_found"})
        save_dataframe(pd.DataFrame(failures), paths["errors"] / "failed_tick_groups.csv")
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

    if failures:
        save_dataframe(pd.DataFrame(failures), paths["errors"] / "failed_tick_groups.csv")

    return results, failures


def build_light_validation_report(output_dir):
    output_dir = Path(output_dir)
    report = {
        "output_dir": str(output_dir),
        "checks": {},
        "csv_files": [],
        "json_files": [],
    }

    expected_paths = [
        output_dir / "match_summary.json",
        output_dir / "game_events_list.csv",
        output_dir / "meta" / "header.json",
        output_dir / "meta" / "player_info.csv",
        output_dir / "events",
        output_dir / "ticks",
        output_dir / "errors",
    ]

    for path in expected_paths:
        report["checks"][str(path.relative_to(output_dir))] = path.exists()

    for csv_path in sorted(output_dir.rglob("*.csv")):
        item = {"path": str(csv_path.relative_to(output_dir))}
        try:
            item["rows"] = len(pd.read_csv(csv_path))
        except Exception as exc:
            item["read_error"] = str(exc)
        report["csv_files"].append(item)

    for json_path in sorted(output_dir.rglob("*.json")):
        report["json_files"].append({"path": str(json_path.relative_to(output_dir))})

    report["status"] = "ok" if all(report["checks"].values()) else "warning"
    save_json(report, output_dir / "light_validation_report.json")
    return report


def parse_demo(demo_path, output_dir):
    demo_path = Path(demo_path)
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

    if event_names:
        exported_events, failed_events = export_events(parser, event_names, paths)
        summary["game_events"]["exported"] = len([item for item in exported_events if item["status"] == "ok"])
        summary["game_events"]["failed"] = len(failed_events)
        summary["game_events"]["items"] = exported_events
    else:
        summary["game_events"]["items"] = []

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

    parse_demo(Path(args.demo), Path(args.output))


if __name__ == "__main__":
    main()
