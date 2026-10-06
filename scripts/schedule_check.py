#!/usr/bin/env python3
"""Check whether a configured lifecycle action is due now (IST)."""
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

def main():
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "config/schedules.yml")
    data = read_config(path)
    now = datetime.now(ZoneInfo("Asia/Kolkata"))
    minute = now.hour * 60 + now.minute
    due = []
    for action in ("stop", "start"):
        cfg = data.get(action, {})
        if str(cfg.get("enabled", "true")).lower() not in {"true", "yes", "1"}:
            continue
        value = str(cfg.get("time", ""))
        try:
            hour, mins = map(int, value.split(":"))
        except ValueError:
            print(f"Invalid {action}.time: {value}", file=sys.stderr); return 2
        if not (0 <= hour <= 23 and 0 <= mins <= 59):
            print(f"Invalid {action}.time: {value}", file=sys.stderr); return 2
        target = hour * 60 + mins
        # Five-minute polling: tolerate scheduler delay without running twice.
        if 0 <= minute - target <= 4:
            due.append(action)
    if len(due) > 1:
        print("STOP and START overlap; refusing to act.", file=sys.stderr); return 2
    action = due[0] if due else "none"
    Path("/tmp/mule-scheduler-action").write_text(action + "\n", encoding="utf-8")
    print(f"IST now={now:%Y-%m-%d %H:%M:%S %Z}; action={action}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
