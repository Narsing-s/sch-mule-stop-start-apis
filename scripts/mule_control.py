#!/usr/bin/env python3
"""Start/stop selected CloudHub 2.0 applications through Anypoint CLI."""

from __future__ import annotations

import concurrent.futures
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

CONFIG = Path("config/apis.txt")
POLL_SECONDS = int(os.getenv("MULE_POLL_SECONDS", "10"))
TIMEOUT_SECONDS = int(os.getenv("MULE_TIMEOUT_SECONDS", "1200"))

@dataclass(frozen=True)
class Application:
    name: str
    app_id: str
    current_status: str = "UNKNOWN"

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
    found: list[str] = []
    for obj in walk(value):
        if isinstance(obj, dict):
            for key, child in obj.items():
                if key.lower() == wanted_key.lower() and child is not None:
                    found.append(str(child).strip().upper())
    return found

def load_targets() -> list[str]:
    if not CONFIG.exists():
        raise RuntimeError(f"Missing {CONFIG}")
    names: list[str] = []
    for raw in CONFIG.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line not in names:
            names.append(line)
    if not names:
        raise RuntimeError(
            f"{CONFIG} contains no active application names. "
            "Add the exact CloudHub 2.0 application names before scheduling."
        )
    return names

def list_applications() -> list[Application]:
    result = cli("runtime-mgr:application:list", "--output", "json")
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"application list failed: {detail}")
    payload = parse_json(result.stdout)
    apps: dict[str, Application] = {}
    for obj in walk(payload):
        if not isinstance(obj, dict):
            continue
        name = obj.get("name") or obj.get("applicationName")
        app_id = obj.get("id") or obj.get("applicationId")
        if name is None or app_id is None:
            continue
        name = str(name).strip()
        app_id = str(app_id).strip()
        status = str(obj.get("status") or obj.get("applicationStatus") or "UNKNOWN").upper()
        if name and app_id:
            apps[name.lower()] = Application(name, app_id, status)
    return list(apps.values())

def resolve_targets(requested_names: list[str]) -> list[Application]:
    available = list_applications()
    by_name = {app.name.lower(): app for app in available}
    by_id = {app.app_id: app for app in available}
    resolved: list[Application] = []
    missing: list[str] = []
    for requested in requested_names:
        app = by_name.get(requested.lower()) or by_id.get(requested)
        if not app:
            missing.append(requested)
        elif app not in resolved:
            resolved.append(app)
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
    candidates: list[str] = []
    for key in ("status", "deploymentStatus", "state"):
        candidates.extend(values_for_key(payload, key))
    for candidate in candidates:
        if candidate in {"APPLIED", "APPLYING", "FAILED", "DELETED"}:
            deployment_state = candidate
            break
    return desired_state, deployment_state

def wait_for_target(app: Application, target: str) -> tuple[bool, str, str]:
    deadline = time.monotonic() + TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        try:
            desired, deployment = describe_state(app.app_id)
        except RuntimeError as exc:
            print(f"[WARN] {app.name}: {exc}", flush=True)
            time.sleep(POLL_SECONDS)
            continue
        print(f"{app.name} => deployment={deployment}, desired={desired}", flush=True)
        if desired == target and deployment not in {"APPLYING", "FAILED"}:
            return True, desired, deployment
        if deployment == "FAILED":
            return False, desired, deployment
        time.sleep(POLL_SECONDS)
    desired, deployment = describe_state(app.app_id)
    return False, desired, deployment

def control(app: Application, action: str) -> tuple[str, bool, str]:
    target = "STARTED" if action == "start" else "STOPPED"
    command = "runtime-mgr:application:start" if action == "start" else "runtime-mgr:application:stop"
    try:
        desired, deployment = describe_state(app.app_id)
        if desired == target and deployment != "APPLYING":
            return app.name, True, f"already {desired}/{deployment}"
        result = cli(command, app.app_id)
        output = (result.stdout or "").strip()
        error = (result.stderr or "").strip()
        if result.returncode != 0:
            return app.name, False, error or output or f"{command} failed"
        print(f"[ACTION] {app.name}: {action} submitted", flush=True)
        ok, final_desired, final_deployment = wait_for_target(app, target)
        if ok:
            return app.name, True, f"{final_desired}/{final_deployment}"
        return app.name, False, f"did not reach {target}: {final_desired}/{final_deployment}"
    except Exception as exc:
        return app.name, False, str(exc)

def main() -> int:
    action = os.getenv("MULE_ACTION", "").strip().lower()
    if action not in {"start", "stop"}:
        print("MULE_ACTION must be 'start' or 'stop'.", file=sys.stderr)
        return 2
    applications = resolve_targets(load_targets())
    print(f"Controlling {len(applications)} application(s) with action={action}.", flush=True)
    failures = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, max(1, len(applications)))) as executor:
        futures = [executor.submit(control, app, action) for app in applications]
        for future in concurrent.futures.as_completed(futures):
            name, ok, message = future.result()
            print(f"[{'OK' if ok else 'FAILED'}] {name}: {message}", flush=True)
            if not ok:
                failures += 1
    print(f"Completed: total={len(applications)}, success={len(applications)-failures}, failures={failures}", flush=True)
    return 1 if failures else 0

if __name__ == "__main__":
    raise SystemExit(main())
