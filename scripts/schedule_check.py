#!/usr/bin/env python3
"""Resolve the lifecycle action for a registered GitHub schedule event.

Business schedules are configured only as normal 24-hour times in
config/schedules.yml. The registration workflow converts those times into
GitHub schedule entries. This checker does not poll or use a catch-up window.
If the configuration changed after a schedule was registered, the old event
is treated as stale and skipped.
"""
from pathlib import Path
import sys

TIMEZONE = "Asia/Kolkata"

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
        print(f"Invalid {action}.time: {value}", file=sys.stderr)
        raise SystemExit(2)
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        print(f"Invalid {action}.time: {value}", file=sys.stderr)
        raise SystemExit(2)
    return hour, minute

def configured_cron(cfg, action):
    hour, minute = parse_time(cfg, action)
    return f"{minute} {hour} * * *"

def main():
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "config/schedules.yml")
    event_schedule = sys.argv[2].strip() if len(sys.argv) > 2 else ""
    data = read_config(path)
    timezone = str(data.get("timezone", TIMEZONE)).strip()
    if timezone != TIMEZONE:
        print(f"Unsupported scheduler timezone {timezone!r}; expected {TIMEZONE}.", file=sys.stderr)
        raise SystemExit(2)

    matches = []
    for action in ("stop", "start"):
        cfg = data.get(action, {})
        enabled = str(cfg.get("enabled", "true")).lower() in {"true", "yes", "1"}
        if enabled and event_schedule == configured_cron(cfg, action):
            matches.append(action)

    if len(matches) > 1:
        print("Stop and start cannot use the same configured minute.", file=sys.stderr)
        raise SystemExit(2)

    action = matches[0] if matches else "none"
    Path("/tmp/mule-scheduler-action").write_text(action + "\n", encoding="utf-8")
    if action == "none":
        print(f"Stale/unmatched schedule event: {event_schedule or '<empty>'}")
    else:
        hour, minute = parse_time(data[action], action)
        print(f"Registered schedule matched action={action}; configured IST time={hour:02d}:{minute:02d}")

if __name__ == "__main__":
    raise SystemExit(main())