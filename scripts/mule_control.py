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
    organization = os.getenv("ANYPOINT_ORG", "").strip()
    if organization:
        command.extend(["--organization", organization])
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
            if region not in (*REGIONS, "all", "auto"):
                raise RuntimeError(f"{INVENTORY}:{line_number}: invalid region {region!r}; use west, westb, east, all, or auto.")
            if environment.lower() == "auto":
                environment = "auto"
            if region == "auto":
                if selected_region != "all":
                    continue
                actual_regions = ("auto",)
            else:
                if selected_region != "all" and region not in (selected_region, "all"):
                    continue
                actual_regions = REGIONS if region == "all" else (region,)
            for actual_region in actual_regions:
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

def list_environments() -> list[str]:
    result = cli("", "account:environment:list", "--output", "json")
    if result.returncode != 0:
        raise RuntimeError(f"environment list failed: {(result.stderr or result.stdout).strip()}")
    payload = parse_json(result.stdout)
    names = []
    seen = set()
    for obj in walk(payload):
        if not isinstance(obj, dict):
            continue
        name = obj.get("name") or obj.get("environmentName")
        if name:
            value = str(name).strip()
            if value and value.lower() not in seen:
                seen.add(value.lower())
                names.append(value)
    if not names:
        raise RuntimeError("No accessible Anypoint environments were returned for the Business Group.")
    return names

ENV_ALIASES = {"dev": ("dev","development"), "development": ("dev","development"), "qa": ("qa","quality","test"), "test": ("test","qa"), "prod": ("prod","production"), "production": ("prod","production"), "sandbox": ("sandbox",), "design": ("design",)}

def resolve_environment_name(requested, available):
    exact = next((x for x in available if x.lower() == requested.lower()), None)
    if exact: return exact
    aliases = ENV_ALIASES.get(requested.lower(), (requested.lower(),))
    matches = [x for x in available if x.lower() in aliases or any(a in x.lower() for a in aliases)]
    if len(matches) == 1: return matches[0]
    if len(matches) > 1: raise RuntimeError("Environment %r is ambiguous: %s" % (requested, ", ".join(matches)))
    raise RuntimeError("Anypoint environment %r was not found. Available: %s" % (requested, ", ".join(available)))

def resolve_targets(requested):
    available_envs = list_environments()
    resolved_requested = []
    auto_requested = []
    for name, environment, region in requested:
        if environment.lower() == "auto": auto_requested.append((name, region))
        else: resolved_requested.append((name, resolve_environment_name(environment, available_envs), region))
    if auto_requested:
        discovered = []
        for environment in available_envs:
            try: available = list_applications(environment)
            except RuntimeError as exc:
                print(f"[WARN] Could not list applications in {environment}: {exc}", flush=True); continue
            by_name = {app.name.lower(): app for app in available}
            for name, region in auto_requested:
                if name.lower() in by_name: discovered.append((name, environment, region))
        for name, region in auto_requested:
            matches = [(n,e,r) for n,e,r in discovered if n.lower() == name.lower()]
            unique = {e.lower(): e for _,e,_ in matches}
            if len(unique) != 1:
                if not matches: raise RuntimeError(f"API {name} could not be found in any accessible Anypoint environment.")
                raise RuntimeError("API %s was found in multiple Anypoint environments: %s; configure its environment explicitly." % (name, ", ".join(unique.values())))
            resolved_requested.append(matches[0])
    by_environment = {}
    for name, environment, region in resolved_requested:
        if region == "auto": region = "all"
        if region != "all" and region not in REGIONS: raise RuntimeError(f"Invalid resolved region {region} for {name}.")
        by_environment.setdefault(environment.lower(), []).append((name, environment, region))
    resolved, missing, seen_ids = [], [], set()
    for entries in by_environment.values():
        environment = entries[0][1]
        available = list_applications(environment)
        by_name = {app.name.lower(): app for app in available}
        by_id = {app.app_id: app for app in available}
        for name, env, region in entries:
            app = by_name.get(name.lower()) or by_id.get(name)
            if not app: missing.append(f"{env}/{region}:{name}"); continue
            key = (env.lower(), app.app_id)
            if key in seen_ids: continue
            seen_ids.add(key); resolved.append(Application(app.name, env, region, app.app_id))
    if missing: raise RuntimeError("Application(s) not found: " + ", ".join(missing))
    return resolved

def _compact(text: str, limit: int = 1200) -> str:
    value = " ".join((text or "").split())
    return value[:limit] + ("..." if len(value) > limit else "")


def _application_state(app: Application) -> str:
    result = cli(app.environment, "runtime-mgr:application:describe", app.app_id, "--output", "json")
    if result.returncode != 0:
        # Fall back to the list response when describe is unavailable.
        result = cli(app.environment, "runtime-mgr:application:list", "--output", "json")
    if result.returncode != 0:
        raise RuntimeError("state lookup failed: " + _compact(result.stderr or result.stdout))
    payload = parse_json(result.stdout)

    wanted = app.app_id.strip().lower()
    wanted_name = app.name.strip().lower()
    candidates = []
    for obj in walk(payload):
        if not isinstance(obj, dict):
            continue
        oid = str(obj.get("id") or obj.get("applicationId") or "").strip().lower()
        oname = str(obj.get("name") or obj.get("applicationName") or "").strip().lower()
        if oid == wanted or oname == wanted_name:
            candidates.append(obj)
    if not candidates:
        raise RuntimeError("application was not present in Anypoint response")

    obj = candidates[0]
    for key in ("status", "state", "desiredState", "desired_status", "applicationStatus", "deploymentStatus"):
        value = obj.get(key)
        if value is not None and str(value).strip():
            return str(value).strip().upper()
    # Some CLI versions nest deployment/application state.
    values = []
    for key in ("deployment", "application", "runtime"):
        child = obj.get(key)
        if isinstance(child, dict):
            for state_key in ("status", "state", "desiredState", "desired_status"):
                value = child.get(state_key)
                if value is not None and str(value).strip():
                    values.append(str(value).strip().upper())
    if values:
        return values[0]
    return "UNKNOWN"


def control(app: Application, action: str):
    started = time.monotonic()
    command_name = "runtime-mgr:application:%s" % action
    print("[%s] %s/%s -> %s (%s)" % (action.upper(), app.environment, app.name, command_name, app.app_id), flush=True)

    before = "UNKNOWN"
    try:
        before = _application_state(app)
    except Exception as exc:
        print("[WARN] %s initial state lookup: %s" % (app.name, exc), flush=True)

    result = cli(app.environment, command_name, app.app_id)
    if result.returncode != 0:
        detail = _compact(result.stderr or result.stdout)
        return app, False, "CLI failed: %s" % detail, time.monotonic() - started

    expected = "STARTED" if action == "start" else "STOPPED"
    deadline = time.monotonic() + TIMEOUT_SECONDS if TIMEOUT_SECONDS > 0 else time.monotonic() + 300
    last = before
    while time.monotonic() < deadline:
        try:
            last = _application_state(app)
            print("[%s] %s state=%s (before=%s)" % (app.name, last, before, before), flush=True)
            normalized = last.replace("-", "_").replace(" ", "_").upper()
            if expected == "STARTED" and normalized in {"STARTED", "RUNNING", "DEPLOYED"}:
                return app, True, last, time.monotonic() - started
            if expected == "STOPPED" and normalized in {"STOPPED", "UNDEPLOYED"}:
                # STOPPING is accepted only as a transitional success after the stop command.
                return app, True, last, time.monotonic() - started
        except Exception as exc:
            last = "STATE_LOOKUP_ERROR: %s" % _compact(str(exc))
        time.sleep(POLL_SECONDS)

    return app, False, "Expected %s; final state=%s" % (expected, last), time.monotonic() - started

def write_analytics(action, business_group, applications, results, started, error=""):
    path = Path(os.getenv("MULE_ANALYTICS_FILE", "mule-execution-analytics.json"))
    successful = sum(1 for _, ok, _, _ in results if ok)
    failed = max(0, len(applications) - successful)
    if error and failed == 0:
        failed = 1
    rows = []
    for app, ok, msg, duration in results:
        rows.append({
            "api": app.name,
            "business_group": business_group,
            "environment": app.environment,
            "region": app.region,
            "result": "SUCCESS" if ok else "FAILED",
            "final_state": msg,
            "duration_seconds": round(duration, 1),
        })
    if error and not rows:
        rows.append({
            "api": "*",
            "business_group": business_group,
            "environment": "*",
            "region": os.getenv("MULE_REGION", "all"),
            "result": "FAILED",
            "final_state": error,
            "duration_seconds": round(time.monotonic() - started, 1),
        })
    data = {
        "action": action,
        "business_group": business_group,
        "inventory": str(INVENTORY),
        "total": len(applications),
        "successful": successful,
        "failed": failed,
        "total_duration_seconds": round(time.monotonic() - started, 1),
        "poll_interval_seconds": POLL_SECONDS,
        "environments": sorted({a.environment for a in applications}, key=str.lower),
        "error": error,
        "results": rows,
    }
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print("Analytics written to %s" % path, flush=True)
    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write("\n## Execution Analytics\n")
            f.write("**%s — %s/%s successful; %s failed.**\n\n" %
                    (action.upper(), data["successful"], data["total"], data["failed"]))
            if error:
                f.write("**Error:** %s\n\n" % error)
            f.write("| Environment | Region | API | Result | Final state | Duration |\n")
            f.write("|---|---|---|---|---|---:|\n")
            for row in rows:
                safe_state = str(row["final_state"]).replace("|", "/")
                f.write("| %s | %s | %s | %s | %s | %ss |\n" %
                        (row["environment"], row["region"].upper(), row["api"],
                         row["result"], safe_state, row["duration_seconds"]))
    return data

def main() -> int:
    action=os.getenv("MULE_ACTION","").strip().lower(); region=os.getenv("MULE_REGION","all").strip().lower(); bg=os.getenv("ANYPOINT_BG","").strip(); started=time.monotonic(); applications=[]; results=[]
    if action not in {"start","stop"}: write_analytics(action or "unknown",bg,[],[],started,"MULE_ACTION must be start or stop."); return 2
    if not bg: write_analytics(action,bg,[],[],started,"ANYPOINT_BG is required."); return 2
    try:
        applications=resolve_targets(parse_inventory(region))
        print(f"Business Group={bg}; controlling {len(applications)} APIs.",flush=True)
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(12,max(1,len(applications)))) as executor:
            for future in concurrent.futures.as_completed([executor.submit(control,a,action) for a in applications]):
                results.append(future.result())
        data=write_analytics(action,bg,applications,results,started)
        return 1 if data["failed"] else 0
    except Exception as exc:
        print(f"::error::{exc}",file=sys.stderr); write_analytics(action,bg,applications,results,started,str(exc)); return 1

