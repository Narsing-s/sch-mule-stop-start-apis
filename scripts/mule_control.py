#!/usr/bin/env python3
"""Start/stop selected CloudHub 2.0 applications grouped as EAPI/PAPI/SAPI."""

from __future__ import annotations

import concurrent.futures
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

GROUPS = ("eapi", "papi", "sapi")
POLL_SECONDS = int(os.getenv("MULE_POLL_SECONDS", "10"))
TIMEOUT_SECONDS = int(os.getenv("MULE_TIMEOUT_SECONDS", "1200"))

@dataclass(frozen=True)
class Application:
    group: str
    name: str
    app_id: str

def cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["anypoint-cli-v4", *args], text=True, capture_output=True, check=False)

def parse_json(output: str) -> object:
    try:
        return json.loads(output)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Anypoint CLI returned invalid JSON: {exc}") from exc

def walk(value: object):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)

def values_for_key(value: object, wanted_key: str) -> list[str]:
    found = []
    for obj in walk(value):
        if isinstance(obj, dict):
            for key, child in obj.items():
                if key.lower() == wanted_key.lower() and child is not None:
                    found.append(str(child).strip().upper())
    return found

def load_targets(selected_group: str) -> list[tuple[str, str]]:
    groups = GROUPS if selected_group == "all" else (selected_group,)
    targets = []
    for group in groups:
        config = Path("config") / group / "apis.txt"
        if not config.exists():
            raise RuntimeError(f"Missing group configuration: {config}")
        for raw in config.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            for item in line.split(","):
                name = item.strip()
                if name and not name.startswith("#"):
                    pair = (group, name)
                    if pair not in targets:
                        targets.append(pair)
    if not targets:
        raise RuntimeError(f"No active applications configured for group '{selected_group}'.")
    return targets

def list_applications() -> list[Application]:
    result = cli("runtime-mgr:application:list", "--output", "json")
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"application list failed: {detail}")
    payload = parse_json(result.stdout)
    apps = {}
    for obj in walk(payload):
        if not isinstance(obj, dict):
            continue
        name = obj.get("name") or obj.get("applicationName")
        app_id = obj.get("id") or obj.get("applicationId")
        if name is None or app_id is None:
            continue
        name, app_id = str(name).strip(), str(app_id).strip()
        if name and app_id:
            apps[name.lower()] = Application("", name, app_id)
    return list(apps.values())

def resolve_targets(requested: list[tuple[str, str]]) -> list[Application]:
    available = list_applications()
    by_name = {app.name.lower(): app for app in available}
    by_id = {app.app_id: app for app in available}
    resolved, missing = [], []
    for group, name in requested:
        app = by_name.get(name.lower()) or by_id.get(name)
        if not app:
            missing.append(f"{group}:{name}")
            continue
        resolved.append(Application(group, app.name, app.app_id))
    if missing:
        print("Available applications visible in the selected environment:", file=sys.stderr)
        for app in sorted(available, key=lambda x: x.name.lower()):
            print(f"  - {app.name} [{app.app_id}]", file=sys.stderr)
        raise RuntimeError("Application(s) not found: " + ", ".join(missing))
    return resolved

def describe_state(app_id: str) -> tuple[str, str]:
    result = cli("runtime-mgr:application:describe", app_id, "--output", "json")
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"describe failed for {app_id}: {detail}")
    payload = parse_json(result.stdout)
    desired = values_for_key(payload, "desiredState")
    desired_state = desired[0] if desired else "UNKNOWN"
    deployment_state = "UNKNOWN"
    for key in ("status", "deploymentStatus", "state"):
        for candidate in values_for_key(payload, key):
            if candidate in {"APPLIED", "APPLYING", "FAILED", "DELETED"}:
                deployment_state = candidate
                break
        if deployment_state != "UNKNOWN":
            break
    return desired_state, deployment_state

def control(app: Application, action: str) -> tuple[Application, bool, str]:
    target = "STARTED" if action == "start" else "STOPPED"
    command = "runtime-mgr:application:start" if action == "start" else "runtime-mgr:application:stop"
    deadline = time.monotonic() + TIMEOUT_SECONDS
    try:
        while True:
            desired, deployment = describe_state(app.app_id)
            print(f"[{app.group.upper()}] {app.name} => deployment={deployment}, desired={desired}", flush=True)
            if desired == target and deployment == "APPLIED":
                return app, True, f"{desired}/{deployment}"
            if deployment == "FAILED":
                return app, False, f"deployment failed while targeting {target}"
            if desired != target:
                result = cli(command, app.app_id)
                if result.returncode != 0:
                    detail = (result.stderr or result.stdout).strip()
                    print(f"[WARN] {app.name}: {detail}", flush=True)
                else:
                    print(f"[ACTION] [{app.group.upper()}] {action} submitted for {app.name}", flush=True)
            if time.monotonic() >= deadline:
                desired, deployment = describe_state(app.app_id)
                return app, False, f"timeout: {desired}/{deployment}; target={target}"
            time.sleep(POLL_SECONDS)
    except Exception as exc:
        return app, False, str(exc)

def main() -> int:
    action = os.getenv("MULE_ACTION", "").strip().lower()
    group = os.getenv("MULE_GROUP", "all").strip().lower()
    if action not in {"start", "stop"}:
        print("MULE_ACTION must be 'start' or 'stop'.", file=sys.stderr)
        return 2
    if group not in (*GROUPS, "all"):
        print("MULE_GROUP must be eapi, papi, sapi, or all.", file=sys.stderr)
        return 2
    requested = load_targets(group)
    applications = resolve_targets(requested)
    print(f"Controlling {len(applications)} application(s): group={group}, action={action}", flush=True)
    failures = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(12, max(1, len(applications)))) as executor:
        futures = [executor.submit(control, app, action) for app in applications]
        for future in concurrent.futures.as_completed(futures):
            app, ok, message = future.result()
            print(f"[{'OK' if ok else 'FAILED'}] [{app.group.upper()}] {app.name}: {message}", flush=True)
            if not ok:
                failures += 1
    print(f"Completed: total={len(applications)}, success={len(applications)-failures}, failures={failures}", flush=True)
    return 1 if failures else 0

if __name__ == "__main__":
    raise SystemExit(main())
