#!/usr/bin/env python3
"""Register config/schedules.yml as GitHub Actions schedule entries.

Users edit only normal 24-hour IST values in config/schedules.yml.
This script updates the generated schedule block in the lifecycle workflow.
It intentionally never creates a polling/catch-up schedule.
"""
from pathlib import Path
import re
import sys

TIMEZONE = "Asia/Kolkata"
BEGIN = "    # GENERATED FROM config/schedules.yml. Business times remain normal 24-hour IST."
END = "  workflow_dispatch:"


def read_config(path):
    data, section = {}, None
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.endswith(":") and not line.startswith("-"):
            section = line[:-1].strip()
            data[section] = {}
        elif ":" in line and section:
            key, value = line.split(":", 1)
            data[section][key.strip()] = value.strip().strip('"').strip("'")
    return data


def parse_time(cfg, action):
    value = str(cfg.get("time", ""))
    try:
        hour, minute = map(int, value.split(":"))
    except ValueError:
        raise SystemExit(f"Invalid {action}.time: {value!r}. Use HH:MM.")
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise SystemExit(f"Invalid {action}.time: {value!r}. Use HH:MM.")
    return hour, minute


def main():
    if len(sys.argv) != 3:
        raise SystemExit("Usage: schedule_register.py <workflow> <config>")

    workflow_path = Path(sys.argv[1])
    config_path = Path(sys.argv[2])
    data = read_config(config_path)

    timezone = str(data.get("timezone", TIMEZONE)).strip()
    if timezone != TIMEZONE:
        raise SystemExit(
            f"Unsupported timezone {timezone!r}. This scheduler requires {TIMEZONE}."
        )

    entries = []
    seen = set()
    for action in ("stop", "start"):
        cfg = data.get(action, {})
        enabled = str(cfg.get("enabled", "true")).lower() in {"true", "yes", "1"}
        if not enabled:
            continue
        hour, minute = parse_time(cfg, action)
        cron = f"{minute} {hour} * * *"
        if cron in seen:
            raise SystemExit(
                f"stop and start cannot use the same configured time ({hour:02d}:{minute:02d})."
            )
        seen.add(cron)
        entries.extend([
            f'    - cron: "{cron}"',
            f'      timezone: "{TIMEZONE}"',
        ])

    generated = [
        "  schedule:",
        BEGIN,
        "    # DO NOT EDIT THESE CRON VALUES MANUALLY.",
        "    # They are regenerated from config/schedules.yml by register-mule-schedule.yml.",
    ]
    if entries:
        generated.extend(entries)
    else:
        generated.append("    # No automatic schedules are enabled.")
        generated.append("    # The workflow remains available through workflow_dispatch.")
        generated.insert(1, "  # Automatic schedule registration is disabled.")
        generated = [
            "  schedule: []",
            BEGIN,
            "    # No automatic schedules are enabled.",
            "    # The workflow remains available through workflow_dispatch.",
        ]
    generated_text = "\n".join(generated) + "\n"

    text = workflow_path.read_text(encoding="utf-8")
    start = text.find("  schedule:")
    end = text.find(END, start)
    if start < 0 or end < 0:
        raise SystemExit("Could not locate the workflow schedule block.")

    text = text[:start] + generated_text + "\n" + text[end:]
    workflow_path.write_text(text, encoding="utf-8")

    print("Registered schedule entries:")
    for action in ("stop", "start"):
        cfg = data.get(action, {})
        enabled = str(cfg.get("enabled", "true")).lower() in {"true", "yes", "1"}
        if enabled:
            hour, minute = parse_time(cfg, action)
            print(f"  {action}: {hour:02d}:{minute:02d} {TIMEZONE}")
        else:
            print(f"  {action}: disabled")


if __name__ == "__main__":
    main()
