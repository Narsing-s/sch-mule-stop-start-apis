#!/usr/bin/env python3
"""Resolve the next enabled daily IST action.

The scheduler deliberately does not use cron. If the next action is more than
4h45m away, this run hands off to a fresh workflow_dispatch run before the
GitHub-hosted runner reaches its six-hour maximum.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import json
import os
import re
import time
import urllib.request

CONFIG = Path("config/schedules.yml")
TZ_NAME = "Asia/Kolkata"
HANDOFF_AFTER_SECONDS = 4 * 60 * 60 + 45 * 60

text = CONFIG.read_text(encoding="utf-8")
tz_match = re.search(r'^\s*timezone:\s*["\']?([^\r\n"\']+)["\']?\s*$', text, re.MULTILINE)
timezone = (tz_match.group(1).strip() if tz_match else TZ_NAME)
bg_match = re.search(r'^\\s*business_group:\\s*[\"\']?([^\\r\\n\"\']+)[\"\']?\\s*if timezone != TZ_NAME:
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
print(f"Business Group: {business_group}")
print(f"Next action: {action} at {configured_time} IST ({target:%Y-%m-%d %H:%M:%S})")
print(f"Seconds until action: {seconds}")

def dispatch_next_cycle() -> None:
    token = os.getenv("GITHUB_TOKEN", "").strip()
    repository = os.getenv("GITHUB_REPOSITORY", "").strip()
    server = os.getenv("GITHUB_SERVER_URL", "https://github.com").rstrip("/")
    if not token or not repository:
        raise SystemExit(
            "Next action is more than the safe runner window away, but "
            "GITHUB_TOKEN/GITHUB_REPOSITORY is unavailable for workflow handoff."
        )

    if server == "https://github.com":
        url = f"https://api.github.com/repos/{repository}/actions/workflows/mule-api-scheduler.yml/dispatches"
    else:
        url = f"{server}/api/v3/repos/{repository}/actions/workflows/mule-api-scheduler.yml/dispatches"

    payload = json.dumps({
        "ref": "main",
        "inputs": {"action": "schedule", "group": "all", "region": "all", "business_group": business_group},
    }).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
            "User-Agent": "sch-mule-stop-start-apis-scheduler",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            if response.status not in (200, 201, 204):
                raise RuntimeError(f"workflow_dispatch returned HTTP {response.status}")
    except Exception as exc:
        raise SystemExit(f"Failed to queue next scheduler cycle: {exc}") from exc

    print("Queued next scheduler cycle with workflow_dispatch.", flush=True)
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as out:
        out.write("handoff=true\n")
        out.write(f"business_group={business_group}\n")
        out.write("action=\n")
        out.write("configured_time=\n")

if seconds > HANDOFF_AFTER_SECONDS:
    handoff_wait = HANDOFF_AFTER_SECONDS
    print(
        f"Next action is {seconds / 3600:.2f}h away. "
        f"Waiting {handoff_wait / 3600:.2f}h, then handing off to a fresh workflow run."
    )
    time.sleep(handoff_wait)
    dispatch_next_cycle()
    raise SystemExit(0)

with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as out:
    out.write("handoff=false\n")
    out.write(f"business_group={business_group}\n")
    out.write(f"action={action}\n")
    out.write(f"configured_time={configured_time}\n")

if seconds:
    print(f"Waiting {seconds} seconds...")
    time.sleep(seconds)

print("Configured time reached.", flush=True)
, text, re.MULTILINE)
business_group = (bg_match.group(1).strip() if bg_match else "Learning")
if not business_group:
    business_group = "Learning"
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
print(f"Seconds until action: {seconds}")

def dispatch_next_cycle() -> None:
    token = os.getenv("GITHUB_TOKEN", "").strip()
    repository = os.getenv("GITHUB_REPOSITORY", "").strip()
    server = os.getenv("GITHUB_SERVER_URL", "https://github.com").rstrip("/")
    if not token or not repository:
        raise SystemExit(
            "Next action is more than the safe runner window away, but "
            "GITHUB_TOKEN/GITHUB_REPOSITORY is unavailable for workflow handoff."
        )

    if server == "https://github.com":
        url = f"https://api.github.com/repos/{repository}/actions/workflows/mule-api-scheduler.yml/dispatches"
    else:
        url = f"{server}/api/v3/repos/{repository}/actions/workflows/mule-api-scheduler.yml/dispatches"

    payload = json.dumps({
        "ref": "main",
        "inputs": {"action": "schedule", "group": "all", "region": "all"},
    }).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
            "User-Agent": "sch-mule-stop-start-apis-scheduler",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            if response.status not in (200, 201, 204):
                raise RuntimeError(f"workflow_dispatch returned HTTP {response.status}")
    except Exception as exc:
        raise SystemExit(f"Failed to queue next scheduler cycle: {exc}") from exc

    print("Queued next scheduler cycle with workflow_dispatch.", flush=True)
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as out:
        out.write("handoff=true\n")
        out.write("action=\n")
        out.write("configured_time=\n")

if seconds > HANDOFF_AFTER_SECONDS:
    handoff_wait = HANDOFF_AFTER_SECONDS
    print(
        f"Next action is {seconds / 3600:.2f}h away. "
        f"Waiting {handoff_wait / 3600:.2f}h, then handing off to a fresh workflow run."
    )
    time.sleep(handoff_wait)
    dispatch_next_cycle()
    raise SystemExit(0)

with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as out:
    out.write("handoff=false\n")
    out.write(f"action={action}\n")
    out.write(f"configured_time={configured_time}\n")

if seconds:
    print(f"Waiting {seconds} seconds...")
    time.sleep(seconds)

print("Configured time reached.", flush=True)
