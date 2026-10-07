#!/usr/bin/env python3
"""Resolve a configured lifecycle action from the current IST clock.

The workflow contains no action-specific time expressions. Users only edit
config/schedules.yml using normal 24-hour IST values such as 08:00 or 18:30.
"""
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import sys


TIMEZONE = "Asia/Kolkata"


def read_config(path):
    data, section = {}, None
    for raw in path.read_text(encoding="utf-8").splitlines():
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
        hour, mins = map(int, value.split(":"))
    except ValueError:
        print(f"Invalid {action}.time: {value}", file=sys.stderr)
        raise SystemExit(2)

    if not (0 <= hour <= 23 and 0 <= mins <= 59):
        print(f"Invalid {action}.time: {value}", file=sys.stderr)
        raise SystemExit(2)

    return hour * 60 + mins


def main():
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "config/schedules.yml")
    data = read_config(path)
    now = datetime.now(ZoneInfo(TIMEZONE))
    minute = now.hour * 60 + now.minute

    due = []
    for action in ("stop", "start"):
        cfg = data.get(action, {})
        if str(cfg.get("enabled", "true")).lower() in {"true", "yes", "1"}:
            configured_minute = parse_time(cfg, action)
            if configured_minute == minute:
                due.append(action)

    if len(due) > 1:
        print(
            f"ERROR: STOP and START cannot share the same IST minute: "
            f"{now:%H:%M}",
            file=sys.stderr,
        )
        raise SystemExit(2)

    action = due[0] if due else "none"
    Path("/tmp/mule-scheduler-action").write_text(action + "\n", encoding="utf-8")

    if action == "none":
        print(
            f"IST now={now:%Y-%m-%d %H:%M:%S %Z}; "
            "no lifecycle action configured for this minute"
        )
    else:
        print(
            f"IST now={now:%Y-%m-%d %H:%M:%S %Z}; "
            f"action={action}; configured_time={now:%H:%M}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
