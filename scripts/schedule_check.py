#!/usr/bin/env python3
"""Resolve a configured lifecycle action from the current IST clock.

The workflow wakes every five minutes, while users configure only normal
24-hour IST times in config/schedules.yml. A small catch-up window ensures a
configured minute such as 08:28 is still executed by the 08:30 wake-up.
"""
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import sys

TIMEZONE = "Asia/Kolkata"
WAKEUP_WINDOW_MINUTES = 5


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


def minutes_since_midnight(now):
    return now.hour * 60 + now.minute


def is_due(configured_minute, current_minute):
    # A scheduled run may arrive a few minutes after the configured minute.
    # Handle midnight correctly as well.
    elapsed = (current_minute - configured_minute) % (24 * 60)
    return 0 <= elapsed < WAKEUP_WINDOW_MINUTES


def main():
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "config/schedules.yml")
    data = read_config(path)
    now = datetime.now(ZoneInfo(TIMEZONE))
    current_minute = minutes_since_midnight(now)

    due = []
    for action in ("stop", "start"):
        cfg = data.get(action, {})
        if str(cfg.get("enabled", "true")).lower() in {"true", "yes", "1"}:
            configured_minute = parse_time(cfg, action)
            if is_due(configured_minute, current_minute):
                due.append((action, configured_minute))

    if len(due) > 1:
        # If two configured times fall in the same wake-up window, execute the
        # most recently configured action rather than running both.
        due.sort(key=lambda item: (current_minute - item[1]) % (24 * 60))
        due = [due[0]]

    action = due[0][0] if due else "none"
    Path("/tmp/mule-scheduler-action").write_text(action + "\n", encoding="utf-8")

    if action == "none":
        print(
            f"IST now={now:%Y-%m-%d %H:%M:%S %Z}; "
            "no lifecycle action is due in the current 5-minute wake-up window"
        )
    else:
        configured_minute = due[0][1]
        print(
            f"IST now={now:%Y-%m-%d %H:%M:%S %Z}; "
            f"action={action}; configured_time={configured_minute // 60:02d}:{configured_minute % 60:02d}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
