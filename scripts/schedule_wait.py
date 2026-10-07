#!/usr/bin/env python3
"""Resolve the next enabled daily schedule in Asia/Kolkata and wait for it."""
from __future__ import annotations
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import os
import re
import time

CONFIG = Path("config/schedules.yml")
TZ_NAME = "Asia/Kolkata"
text = CONFIG.read_text(encoding="utf-8")

tz_match = re.search(r'^\s*timezone:\s*["\']?([^\r\n"\']+)["\']?\s*$', text, re.MULTILINE)
timezone = (tz_match.group(1).strip() if tz_match else TZ_NAME)
if timezone != TZ_NAME:
    raise SystemExit(f"Only {TZ_NAME} is supported; found {timezone!r}.")

now = datetime.now(ZoneInfo(TZ_NAME))
candidates = []

for action in ("stop", "start"):
    section = re.search(
        rf'(?ms)^{action}:\s*\n(.*?)(?=^[A-Za-z0-9_-]+:\s*$|\Z)',
        text,
    )
    body = section.group(1) if section else ""
    enabled = re.search(r'^\s*enabled:\s*(true|false)\s*$', body, re.MULTILINE)
    configured = re.search(r'^\s*time:\s*["\']?(\d{2}:\d{2})["\']?\s*$', body, re.MULTILINE)
    if not enabled or enabled.group(1).lower() != "true":
        continue
    if not configured:
        raise SystemExit(f"Invalid {action}.time in {CONFIG}")

    hour, minute = map(int, configured.group(1).split(":"))
    if hour > 23 or minute > 59:
        raise SystemExit(f"Invalid {action}.time: {configured.group(1)}")

    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    candidates.append((target, action, configured.group(1)))

if not candidates:
    raise SystemExit("No enabled stop/start schedule is configured.")

target, action, configured_time = min(candidates)
seconds = max(0, int((target - now).total_seconds()))

print(f"Current IST time: {now:%Y-%m-%d %H:%M:%S}")
print(f"Next action: {action} at {configured_time} IST ({target:%Y-%m-%d %H:%M:%S})")

if seconds > 6 * 60 * 60:
    raise SystemExit(
        f"Next configured time is {seconds / 3600:.2f} hours away. "
        "GitHub-hosted waiting is limited to six hours; trigger the workflow closer to the configured time."
    )

with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as out:
    out.write(f"action={action}\n")
    out.write(f"configured_time={configured_time}\n")

if seconds:
    print(f"Waiting {seconds} seconds...")
    time.sleep(seconds)

print("Configured time reached.")
