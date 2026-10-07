#!/usr/bin/env python3
"""Determine the lifecycle action due now, tolerating delayed GitHub Actions runs."""
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import sys

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
    now = datetime.now(ZoneInfo("Asia/Kolkata"))
    event_schedule = sys.argv[2].strip() if len(sys.argv) > 2 else ""
    minute = now.hour * 60 + now.minute

    configured = {}
    for action in ("stop", "start"):
        cfg = data.get(action, {})
        if str(cfg.get("enabled", "true")).lower() in {"true", "yes", "1"}:
            configured[action] = parse_time(cfg, action)

    # Prefer the GitHub schedule expression that triggered this run.
    # This keeps a delayed STOP run as STOP even if the clock has reached START.
    if event_schedule:
        expected = {
            "30 2 * * *": "stop",
            "40 2 * * *": "start",
        }
        action = expected.get(event_schedule)
        if action in configured:
            Path("/tmp/mule-scheduler-action").write_text(action + "\n", encoding="utf-8")
            print(f"IST now={now:%Y-%m-%d %H:%M:%S %Z}; action={action}; triggered_by={event_schedule}")
            return 0

    if not configured:
        Path("/tmp/mule-scheduler-action").write_text("none\n", encoding="utf-8")
        print(f"IST now={now:%Y-%m-%d %H:%M:%S %Z}; no enabled schedules")
        return 0

    # GitHub scheduled runs can be delayed. Select the most recent configured
    # schedule that has already occurred today. This means a delayed run still
    # performs the missed action instead of silently returning "none".
    #
    # A future schedule is never selected. If both schedules have passed,
    # choose the later one (the current lifecycle state implied by the latest
    # schedule). This also handles schedules crossing midnight.
    candidates = [(t, action) for action, t in configured.items() if t <= minute]

    if candidates:
        target, action = max(candidates)
        age = minute - target
        # If a run starts after midnight, a previous day's schedule may be
        # relevant only for a short safety window. Avoid replaying an old action
        # indefinitely when there has been no run for many hours.
        if age <= 24 * 60:
            print(f"IST now={now:%Y-%m-%d %H:%M:%S %Z}; action={action}; "
                  f"scheduled={target//60:02d}:{target%60:02d}; delay={age} minute(s)")
        else:
            action = "none"
    else:
        action = "none"
        print(f"IST now={now:%Y-%m-%d %H:%M:%S %Z}; no schedule due yet")

    Path("/tmp/mule-scheduler-action").write_text(action + "\n", encoding="utf-8")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
