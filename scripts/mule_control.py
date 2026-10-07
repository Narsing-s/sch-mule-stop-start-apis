#!/usr/bin/env python3
"""Start/stop explicitly configured CloudHub 2.0 applications."""
from __future__ import annotations
import concurrent.futures
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

GROUPS = ("eapi", "papi", "sapi", "other")
REGIONS = ("west", "westb", "east")
POLL_SECONDS = int(os.getenv("MULE_POLL_SECONDS", "10"))
TIMEOUT_SECONDS = int(os.getenv("MULE_TIMEOUT_SECONDS", "1800"))

@dataclass(frozen=True)
class Application:
    group: str
    region: str
    name: str
    app_id: str

def cli(*args: str) -> subprocess.CompletedProcess[str]:
    command = ["anypoint-cli-v4", *args]
    business_group = os.getenv("ANYPOINT_BG", "").strip()
    environment = os.getenv("ANYPOINT_ENV", "").strip()
    if business_group:
        command.extend(["--organization", business_group])
    if environment:
        command.extend(["--environment", environment])
    return subprocess.run(command, text=True, capture_output=True, check=False)

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

def load_targets(selected_group: str, selected_region: str) -> list[tuple[str, str, str]]:
    groups = GROUPS if selected_group == "all" else (selected_group,)
    requested_regions = REGIONS if selected_region == "all" else (selected_region,)
    targets = []
    for group in groups:
        source_regions = ("all", *REGIONS) if selected_region == "all" else (selected_region,)
        for source_region in source_regions:
            config = Path("config") / group / source_region / "apis.txt"
            if not config.exists():
                raise RuntimeError(f"Missing API configuration: {config}")
            for raw in config.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                for item in line.split(","):
                    name = item.split("#", 1)[0].strip()
                    if not name:
                        continue
                    applicable = REGIONS if source_region == "all" else (source_region,)
                    for region in applicable:
                        if region in requested_regions and (group, region, name) not in targets:
                            targets.append((group, region, name))
    if not targets:
        raise RuntimeError(f"No active applications configured for group={selected_group}, region={selected_region}.")
    return targets

def list_applications() -> list[Application]:
    result = cli("runtime-mgr:application:list", "--output", "json")
    if result.returncode != 0:
        raise RuntimeError(f"application list failed: {(result.stderr or result.stdout).strip()}")
    payload = parse_json(result.stdout)
    apps = {}
    for obj in walk(payload):
        if not isinstance(obj, dict):
            continue
        name = obj.get("name") or obj.get("applicationName")
        app_id = obj.get("id") or obj.get("applicationId")
        if name is not None and app_id is not None:
            name, app_id = str(name).strip(), str(app_id).strip()
            if name and app_id:
                apps[name.lower()] = Application("", "", name, app_id)
    return list(apps.values())

def resolve_targets(requested):
    available = list_applications()
    by_name = {app.name.lower(): app for app in available}
    by_id = {app.app_id: app for app in available}
    resolved, missing, seen_ids = [], [], set()
    for group, region, name in requested:
        app = by_name.get(name.lower()) or by_id.get(name)
        if not app:
            missing.append(f"{group}/{region}:{name}")
            continue
        if app.app_id in seen_ids:
            print(f"[WARN] Duplicate application: {app.name}; controlling once.", flush=True)
            continue
        seen_ids.add(app.app_id)
        resolved.append(Application(group, region, app.name, app.app_id))
    if missing:
        raise RuntimeError("Application(s) not found: " + ", ".join(missing))
    return resolved

def describe_state(app_id: str) -> tuple[str, str]:
    result = cli("runtime-mgr:application:describe", app_id, "--output", "json")
    if result.returncode != 0:
        raise RuntimeError(f"describe failed for {app_id}: {(result.stderr or result.stdout).strip()}")
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

def control(app: Application, action: str):
    target = "STARTED" if action == "start" else "STOPPED"
    command = "runtime-mgr:application:start" if action == "start" else "runtime-mgr:application:stop"
    deadline = time.monotonic() + TIMEOUT_SECONDS
    try:
        while True:
            desired, deployment = describe_state(app.app_id)
            print(f"[{app.group.upper()}/{app.region.upper()}] {app.name} => deployment={deployment}, desired={desired}", flush=True)
            if desired == target and deployment == "APPLIED":
                return app, True, f"{desired}/{deployment}"
            if deployment == "FAILED":
                return app, False, f"deployment failed while targeting {target}"
            if desired != target:
                result = cli(command, app.app_id)
                if result.returncode == 0:
                    print(f"[ACTION] {action} submitted for {app.name}", flush=True)
                else:
                    print(f"[WARN] {app.name}: {(result.stderr or result.stdout).strip()}", flush=True)
            if time.monotonic() >= deadline:
                return app, False, f"timeout: {desired}/{deployment}; target={target}"
            time.sleep(POLL_SECONDS)
    except Exception as exc:
        return app, False, str(exc)

def main() -> int:
    action = os.getenv("MULE_ACTION", "").strip().lower()
    group = os.getenv("MULE_GROUP", "all").strip().lower()
    region = os.getenv("MULE_REGION", "all").strip().lower()
    environment = os.getenv("ANYPOINT_ENV", "").strip()
    if action not in {"start", "stop"}:
        print("MULE_ACTION must be start or stop.", file=sys.stderr)
        return 2
    if group not in (*GROUPS, "all"):
        print("MULE_GROUP must be eapi, papi, sapi, other, or all.", file=sys.stderr)
        return 2
    if region not in (*REGIONS, "all"):
        print("MULE_REGION must be west, westb, east, or all.", file=sys.stderr)
        return 2
    if not environment:
        print("ANYPOINT_ENV is required.", file=sys.stderr)
        return 2
    print(f"Using Anypoint environment: {environment}", flush=True)
    applications = resolve_targets(load_targets(group, region))
    failures = 0
    print(f"Waiting until ALL {len(applications)} configured applications are {'STARTED' if action == 'start' else 'STOPPED'} and APPLIED before completing the workflow.", flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(12, max(1, len(applications)))) as executor:
        for future in concurrent.futures.as_completed([executor.submit(control, app, action) for app in applications]):
            app, ok, message = future.result()
            status = "OK" if ok else "FAILED"
            print(f"[{status}] [{app.group.upper()}/{app.region.upper()}] {app.name}: {message}", flush=True)
            if not ok:
                failures += 1
    success_count = len(applications) - failures
    print(f"Completed: total={len(applications)}, success={success_count}, failures={failures}", flush=True)
    if failures:
        print("Workflow will remain failed; not all applications reached the requested state.", file=sys.stderr, flush=True)
        return 1
    print(f"ALL {len(applications)} applications reached the requested {action.upper()} state. Safe to finish workflow.", flush=True)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
