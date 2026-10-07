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


def parse_json(text: str):
    """Decode Anypoint CLI JSON, tolerating banners/warnings around the payload."""
    raw = (text or "").lstrip("\ufeff").strip()
    if not raw:
        raise RuntimeError("Anypoint CLI returned empty output while JSON was expected")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # CLI versions can prepend warnings or formatting text even with
        # --output json. Extract the first complete JSON object/array.
        decoder = json.JSONDecoder()
        for index, char in enumerate(raw):
            if char not in "[{":
                continue
            try:
                value, _ = decoder.raw_decode(raw[index:])
                return value
            except json.JSONDecodeError:
                continue
        preview = " ".join(raw.split())[:500]
        raise RuntimeError(f"invalid JSON from Anypoint CLI; output={preview!r}")


def walk(value):
    """Yield every nested dict/list value so CLI response shapes can vary safely."""
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)

def cli(environment: str, *args: str) -> subprocess.CompletedProcess[str]:
    """Run Anypoint CLI with the command first, then authentication/global flags."""
    flags = []
    client_id = os.getenv("ANYPOINT_CLIENT_ID", "").strip()
    client_secret = os.getenv("ANYPOINT_CLIENT_SECRET", "").strip()
    organization = os.getenv("ANYPOINT_ORG", "").strip()
    if client_id:
        flags.extend(["--client_id", client_id])
    if client_secret:
        flags.extend(["--client_secret", client_secret])
    if organization:
        flags.extend(["--organization", organization])
    if environment:
        flags.extend(["--environment", environment])
    # Anypoint CLI v4 syntax is: anypoint-cli-v4 [command] [parameters] [flags].
    # Authentication flags before the command are interpreted as commands.
    return subprocess.run(
        ["anypoint-cli-v4", *args, *flags],
        text=True,
        capture_output=True,
        check=False,
    )

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
    api_filter = os.getenv("MULE_API_FILTER", "").strip().lower()
    if api_filter:
        targets = [t for t in targets if t[0].strip().lower() == api_filter]
        if not targets:
            raise RuntimeError(f"API filter {api_filter!r} was not found in {INVENTORY}.")
    if not targets:
        raise RuntimeError(f"No active applications configured in {INVENTORY} for region={selected_region}.")
    return targets

def list_applications(environment: str) -> list[Application]:
    result = cli(environment, "runtime-mgr:application:list", "--output", "json")
    if result.returncode != 0:
        raise RuntimeError(f"application list failed for environment {environment}: {(result.stderr or result.stdout).strip()}")
    payload = parse_json(result.stdout or result.stderr)
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
    payload = parse_json(result.stdout or result.stderr)
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
                if not matches:
                    skipped = getattr(resolve_targets, "_skipped", [])
                    skipped.append({"api": name, "environment": "auto", "region": region, "reason": "API not found in any accessible Anypoint environment; skipped"})
                    resolve_targets._skipped = skipped
                    print(f"[SKIP] API {name} could not be found in any accessible Anypoint environment.", flush=True)
                    continue
                raise RuntimeError("API %s was found in multiple Anypoint environments: %s; configure its environment explicitly." % (name, ", ".join(unique.values())))
            resolved_requested.append(matches[0])
    by_environment = {}
    for name, environment, region in resolved_requested:
        if region == "auto": region = "all"
        if region != "all" and region not in REGIONS: raise RuntimeError(f"Invalid resolved region {region} for {name}.")
        by_environment.setdefault(environment.lower(), []).append((name, environment, region))
    resolved, missing, skipped = [], [], []
    seen_ids = set()
    for entries in by_environment.values():
        environment = entries[0][1]
        available = list_applications(environment)
        by_name = {app.name.lower(): app for app in available}
        by_id = {app.app_id: app for app in available}
        for name, env, region in entries:
            app = by_name.get(name.lower()) or by_id.get(name)
            if not app:
                missing.append(f"{env}/{region}:{name}")
                skipped.append({"api": name, "environment": env, "region": region, "reason": "API not present in runtime; skipped"})
                print(f"[SKIP] {env}/{region} -> API {name} is not present in the Anypoint runtime; continuing with remaining APIs.", flush=True)
                continue
            key = (env.lower(), app.app_id)
            if key in seen_ids: continue
            seen_ids.add(key); resolved.append(Application(app.name, env, region, app.app_id))
    if missing:
        print(f"[WARN] Skipped {len(missing)} inventory API(s) that are not deployed in their configured Anypoint environment: {', '.join(missing)}", flush=True)
    return resolved, skipped

def _compact(text: str, limit: int = 1200) -> str:
    value = " ".join((text or "").split())
    return value[:limit] + ("..." if len(value) > limit else "")


def _application_states(applications: list[Application]) -> dict[tuple[str, str], str]:
    """Read lifecycle state for all applications with one list call per environment."""
    states: dict[tuple[str, str], str] = {}
    by_environment: dict[str, list[Application]] = {}
    for app in applications:
        by_environment.setdefault(app.environment.lower(), []).append(app)

    for apps in by_environment.values():
        environment = apps[0].environment
        result = cli(environment, "runtime-mgr:application:list", "--output", "json")
        if result.returncode != 0:
            raise RuntimeError(
                f"state list failed for environment {environment}: "
                f"{_compact(result.stderr or result.stdout)}"
            )
        payload = parse_json(result.stdout or result.stderr)
        wanted = {
            (app.app_id.strip().lower(), app.name.strip().lower()): app
            for app in apps
        }

        for obj in walk(payload):
            if not isinstance(obj, dict):
                continue
            oid = str(obj.get("id") or obj.get("applicationId") or "").strip().lower()
            oname = str(obj.get("name") or obj.get("applicationName") or "").strip().lower()
            app = next(
                (a for (aid, aname), a in wanted.items()
                 if (oid and aid == oid) or (oname and aname == oname)),
                None,
            )
            if app is None:
                continue

            values = []
            for key, value in obj.items():
                normalized_key = str(key).replace("_", "").replace("-", "").lower()
                if normalized_key not in {
                    "status", "state", "applicationstatus", "deploymentstatus",
                    "replicastatus", "workerstates", "workerstatus",
                }:
                    continue
                if isinstance(value, (str, int, float, bool)):
                    values.append(str(value).strip().upper())
                elif isinstance(value, list):
                    for item in value:
                        if isinstance(item, dict):
                            for child_key in ("status", "state", "replicaStatus", "workerStatus"):
                                child = item.get(child_key)
                                if child is not None:
                                    values.append(str(child).strip().upper())
                elif isinstance(value, dict):
                    for child_key in ("status", "state"):
                        child = value.get(child_key)
                        if child is not None:
                            values.append(str(child).strip().upper())

            for nested in walk(obj):
                if not isinstance(nested, dict):
                    continue
                for key in ("status", "state", "applicationStatus", "replicaStatus", "workerStatus"):
                    value = nested.get(key)
                    if value is not None and not isinstance(value, (dict, list)):
                        values.append(str(value).strip().upper())

            ignored = {
                "", "UNKNOWN", "APPLIED", "DEPLOYING", "APPLYING", "PENDING",
                "UPDATING", "UPDATED", "DEPLOYMENT", "DEPLOYED",
            }
            values = [v.replace("-", "_").replace(" ", "_") for v in values if v not in ignored]

            if any(v in {"RUNNING", "STARTED"} for v in values):
                state = "STARTED"
            elif "STARTING" in values:
                state = "STARTING"
            elif "STOPPING" in values:
                state = "STOPPING"
            elif any(v in {"STOPPED", "NOT_RUNNING", "NOTRUNNING", "UNDEPLOYED", "DELETED"} for v in values):
                state = "STOPPED"
            elif any(v in {"FAILED", "TERMINATED", "RECOVERING"} for v in values):
                state = next(v for v in values if v in {"FAILED", "TERMINATED", "RECOVERING"})
            else:
                state = "UNKNOWN"
            states[(app.environment.lower(), app.app_id)] = state
    return states


def issue_lifecycle_command(app: Application, action: str):
    started = time.monotonic()
    command_name = f"runtime-mgr:application:{action}"
    print(
        f"[{action.upper()}] {app.environment}/{app.name} -> "
        f"{command_name} ({app.app_id})",
        flush=True,
    )
    result = cli(app.environment, command_name, app.app_id)
    if result.returncode != 0:
        detail = _compact(result.stderr or result.stdout)
        return app, False, f"CLI failed: {detail}", time.monotonic() - started
    return app, True, "COMMAND_ACCEPTED", time.monotonic() - started


def execute(applications: list[Application], action: str):
    """Issue all lifecycle commands concurrently, then batch-verify actual state."""
    expected = "STARTED" if action == "start" else "STOPPED"
    results: dict[tuple[str, str], tuple[Application, bool, str, float]] = {}

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(12, max(1, len(applications)))) as executor:
        futures = [executor.submit(issue_lifecycle_command, app, action) for app in applications]
        for future in concurrent.futures.as_completed(futures):
            app, ok, msg, duration = future.result()
            results[(app.environment.lower(), app.app_id)] = (app, ok, msg, duration)

    pending = [
        app for app in applications
        if results[(app.environment.lower(), app.app_id)][1]
    ]
    deadline = time.monotonic() + (TIMEOUT_SECONDS if TIMEOUT_SECONDS > 0 else 300)
    last_states = {}

    while pending and time.monotonic() < deadline:
        try:
            last_states = _application_states(pending)
            next_pending = []
            for app in pending:
                key = (app.environment.lower(), app.app_id)
                state = last_states.get(key, "UNKNOWN")
                print(f"[{app.name}] {state} (expected={expected})", flush=True)
                if state == expected:
                    old = results[key]
                    results[key] = (app, True, state, old[3])
                else:
                    next_pending.append(app)
            pending = next_pending
            if pending:
                time.sleep(POLL_SECONDS)
        except Exception as exc:
            print(f"[WARN] Batch state lookup: {_compact(str(exc))}", flush=True)
            time.sleep(POLL_SECONDS)

    for app in pending:
        key = (app.environment.lower(), app.app_id)
        old = results[key]
        final_state = last_states.get(key, "UNKNOWN")
        results[key] = (
            app,
            False,
            f"Expected {expected}; final state={final_state}",
            time.monotonic() - (time.monotonic() - old[3]),
        )

    return [results[(app.environment.lower(), app.app_id)] for app in applications]


def control(app: Application, action: str):
    """Compatibility entry point used by main(); execute one API lifecycle command."""
    results = execute([app], action)
    return results[0]


def write_analytics(action, business_group, applications, results, started, error="", skipped=None):
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
    skipped = skipped or []
    for item in skipped:
        rows.append({"api": item["api"], "business_group": business_group, "environment": item["environment"], "region": item["region"], "result": "SKIPPED", "final_state": item["reason"], "duration_seconds": 0.0})
    data = {
        "action": action,
        "business_group": business_group,
        "inventory": str(INVENTORY),
        "total": len(applications),
        "successful": successful,
        "failed": failed,
        "skipped": len(skipped),
        "total_duration_seconds": round(time.monotonic() - started, 1),
        "poll_interval_seconds": POLL_SECONDS,
        "environments": sorted({a.environment for a in applications}, key=str.lower),
        "error": error,
        "results": rows,
    }
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"Analytics written to {path}", flush=True)
    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write("\n## Execution Analytics\n")
            f.write(f"**{action.upper()} — {data['successful']}/{data['total']} successful; {data['failed']} failed.**\n\n")
            if error:
                f.write(f"**Error:** {error}\n\n")
            f.write("| Environment | Region | API | Result | Final state | Duration |\n")
            f.write("|---|---|---|---|---|---:|\n")
            for row in rows:
                safe_state = str(row["final_state"]).replace("|", "/")
                f.write(f"| {row['environment']} | {row['region'].upper()} | {row['api']} | {row['result']} | {safe_state} | {row['duration_seconds']}s |\n")
    return data

def main() -> int:
    action=os.getenv("MULE_ACTION","").strip().lower(); region=os.getenv("MULE_REGION","all").strip().lower(); bg=os.getenv("ANYPOINT_BG","").strip(); started=time.monotonic(); applications=[]; results=[]; skipped=[]
    if action not in {"start","stop"}: write_analytics(action or "unknown",bg,[],[],started,"MULE_ACTION must be start or stop."); return 2
    if not bg: write_analytics(action,bg,[],[],started,"ANYPOINT_BG is required."); return 2
    try:
        requested = parse_inventory(region)
        applications, resolved_skipped = resolve_targets(requested)
        skipped.extend(resolved_skipped)
        if not applications:
            raise RuntimeError("No configured APIs are currently deployed in their accessible Anypoint environments.")
        print(f"Business Group={bg}; controlling {len(applications)} APIs; skipping {len(skipped)} missing APIs.",flush=True)
        results = execute(applications, action)
        data=write_analytics(action,bg,applications,results,started,skipped=skipped)
        return 1 if data["failed"] else 0
    except Exception as exc:
        print(f"::error::{exc}",file=sys.stderr); write_analytics(action,bg,applications,results,started,str(exc),skipped=skipped); return 1

if __name__ == "__main__":
    raise SystemExit(main())
