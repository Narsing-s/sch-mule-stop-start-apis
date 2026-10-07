#!/usr/bin/env python3
"""Start/stop CloudHub 2.0 applications from config/all/apis.txt.

Inventory format:
  api-name | anypoint-environment | region

The Business Group is shared and supplied through ANYPOINT_BG.
"""
from __future__ import annotations
import concurrent.futures, json, os, subprocess, sys, time
from dataclasses import dataclass
from pathlib import Path

REGIONS = ("west", "westb", "east")
INVENTORY = Path("config/all/apis.txt")
POLL_SECONDS = int(os.getenv("MULE_POLL_SECONDS", "10"))
TIMEOUT_SECONDS = int(os.getenv("MULE_TIMEOUT_SECONDS", "0"))

@dataclass(frozen=True)
class Application:
    name: str
    environment: str
    region: str
    app_id: str

def cli(environment: str, *args: str) -> subprocess.CompletedProcess[str]:
    command = ["anypoint-cli-v4", *args]
    business_group = os.getenv("ANYPOINT_BG", "").strip()
    if business_group:
        command.extend(["--organization", business_group])
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

def parse_inventory(selected_region: str) -> list[tuple[str, str, str]]:
    if not INVENTORY.exists():
        raise RuntimeError(f"Missing API inventory: {INVENTORY}")
    if selected_region not in (*REGIONS, "all"):
        raise RuntimeError("MULE_REGION must be west, westb, east, or all.")
    targets = []
    seen = set()
    for line_number, raw in enumerate(INVENTORY.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        for item in line.split(","):
            item = item.split("#", 1)[0].strip()
            if not item:
                continue
            parts = [part.strip() for part in item.split("|")]
            if len(parts) != 3 or not all(parts):
                raise RuntimeError(f"{INVENTORY}:{line_number}: expected 'api-name | environment | region', got: {item!r}")
            name, environment, region = parts
            region = region.lower()
            if region not in (*REGIONS, "all"):
                raise RuntimeError(f"{INVENTORY}:{line_number}: invalid region {region!r}; use west, westb, east, or all.")
            if selected_region != "all" and region not in (selected_region, "all"):
                continue
            for actual_region in (REGIONS if region == "all" else (region,)):
                key = (name.lower(), environment.lower(), actual_region)
                if key not in seen:
                    seen.add(key)
                    targets.append((name, environment, actual_region))
    if not targets:
        raise RuntimeError(f"No active applications configured in {INVENTORY} for region={selected_region}.")
    return targets

def list_applications(environment: str) -> list[Application]:
    result = cli(environment, "runtime-mgr:application:list", "--output", "json")
    if result.returncode != 0:
        raise RuntimeError(f"application list failed for environment {environment}: {(result.stderr or result.stdout).strip()}")
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
                apps[name.lower()] = Application(name, environment, "", app_id)
    return list(apps.values())

def resolve_targets(requested):
    by_environment = {}
    for name, environment, region in requested:
        by_environment.setdefault(environment.lower(), []).append((name, environment, region))
    resolved, missing, seen_ids = [], [], set()
    for entries in by_environment.values():
        environment = entries[0][1]
        available = list_applications(environment)
        by_name = {app.name.lower(): app for app in available}
        by_id = {app.app_id: app for app in available}
        for name, env, region in entries:
            app = by_name.get(name.lower()) or by_id.get(name)
            if not app:
                missing.append(f"{env}/{region}:{name}")
                continue
            key = (env.lower(), app.app_id)
            if key in seen_ids:
                print(f"[WARN] Duplicate application: {env}/{app.name}; controlling once.", flush=True)
                continue
            seen_ids.add(key)
            resolved.append(Application(app.name, env, region, app.app_id))
    if missing:
        raise RuntimeError("Application(s) not found: " + ", ".join(missing))
    return resolved

def describe_state(app: Application) -> tuple[str, str]:
    result = cli(app.environment, "runtime-mgr:application:describe", app.app_id, "--output", "json")
    if result.returncode != 0:
        raise RuntimeError(f"describe failed for {app.environment}/{app.name}: {(result.stderr or result.stdout).strip()}")
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
    started = time.monotonic()
    target = "STARTED" if action == "start" else "STOPPED"
    command = "runtime-mgr:application:start" if action == "start" else "runtime-mgr:application:stop"
    deadline = None if TIMEOUT_SECONDS <= 0 else time.monotonic() + TIMEOUT_SECONDS
    try:
        while True:
            desired, deployment = describe_state(app)
            print(f"[{app.environment}/{app.region.upper()}] {app.name} => deployment={deployment}, desired={desired}", flush=True)
            if desired == target and deployment == "APPLIED":
                return app, True, f"{desired}/{deployment}", time.monotonic() - started
            if deployment == "FAILED":
                return app, False, f"deployment failed while targeting {target}", time.monotonic() - started
            if desired != target:
                result = cli(app.environment, command, app.app_id)
                if result.returncode == 0:
                    print(f"[ACTION] {action} submitted for {app.environment}/{app.name}", flush=True)
                else:
                    print(f"[WARN] {app.environment}/{app.name}: {(result.stderr or result.stdout).strip()}", flush=True)
            if deadline is not None and time.monotonic() >= deadline:
                return app, False, f"timeout: {desired}/{deployment}; target={target}", time.monotonic() - started
            time.sleep(POLL_SECONDS)
    except Exception as exc:
        return app, False, str(exc), time.monotonic() - started

def main() -> int:
    action = os.getenv("MULE_ACTION", "").strip().lower()
    region = os.getenv("MULE_REGION", "all").strip().lower()
    business_group = os.getenv("ANYPOINT_BG", "").strip()
    if action not in {"start", "stop"}:
        print("MULE_ACTION must be start or stop.", file=sys.stderr)
        return 2
    if not business_group:
        print("ANYPOINT_BG is required.", file=sys.stderr)
        return 2
    applications = resolve_targets(parse_inventory(region))
    failures, results = 0, []
    execution_started = time.monotonic()
    print(f"Business Group={business_group}; controlling {len(applications)} APIs across {len({a.environment.lower() for a in applications})} Anypoint environment(s).", flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(12, max(1, len(applications)))) as executor:
        for future in concurrent.futures.as_completed([executor.submit(control, app, action) for app in applications]):
            app, ok, message, duration = future.result()
            results.append((app, ok, message, duration))
            print(f"[{'OK' if ok else 'FAILED'}] [{app.environment}/{app.region.upper()}] {app.name}: {message}", flush=True)
            if not ok:
                failures += 1
    success_count = len(applications) - failures
    total_duration = time.monotonic() - execution_started
    analytics_path = os.getenv("MULE_ANALYTICS_FILE", "mule-execution-analytics.json")
    analytics = {
        "action": action, "business_group": business_group, "inventory": str(INVENTORY),
        "total": len(applications), "successful": success_count, "failed": failures,
        "total_duration_seconds": round(total_duration, 1), "poll_interval_seconds": POLL_SECONDS,
        "environments": sorted({app.environment for app in applications}, key=str.lower),
        "results": [{"api": app.name, "business_group": business_group, "environment": app.environment,
                     "region": app.region, "result": "SUCCESS" if ok else "FAILED",
                     "final_state": message, "duration_seconds": round(duration, 1)}
                    for app, ok, message, duration in sorted(results, key=lambda x: (x[0].environment.lower(), x[0].region, x[0].name.lower()))]
    }
    with open(analytics_path, "w", encoding="utf-8") as f:
        json.dump(analytics, f, indent=2)
    summary_file = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_file:
        with open(summary_file, "a", encoding="utf-8") as summary:
            summary.write("\n## Execution Analytics\n")
            summary.write(f"**{action.upper()} {'successful' if failures == 0 else 'completed with failures'} — {success_count}/{len(applications)} APIs successful.**\n\n")
            summary.write("| Environment | Region | API | Result | Final state | Duration |\n|---|---|---|---|---|---:|\n")
            for app, ok, message, duration in sorted(results, key=lambda x: (x[0].environment.lower(), x[0].region, x[0].name.lower())):
                summary.write(f"| {app.environment} | {app.region.upper()} | {app.name} | {'SUCCESS' if ok else 'FAILED'} | {message.replace('|', '\\|')} | {duration:.1f}s |\n")
    if failures:
        print(f"{failures} API(s) did not reach the requested {action.upper()} state.", file=sys.stderr)
        return 1
    print(f"ALL {len(applications)} APIs reached the requested {action.upper()} state.", flush=True)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
