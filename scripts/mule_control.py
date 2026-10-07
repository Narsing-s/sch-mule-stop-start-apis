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

def resolve_targets(requested):
    auto_names = {name.lower(): name for name, env, region in requested if env.lower() == "auto"}
    explicit = [x for x in requested if x[1].lower() != "auto"]
    if auto_names:
        if any(region == "auto" for _, _, region in requested if _ in auto_names.values()):
            pass
        discovered = []
        for environment in list_environments():
            try:
                available = list_applications(environment)
            except RuntimeError:
                continue
            by_name = {app.name.lower(): app for app in available}
            for key, original_name in auto_names.items():
                app = by_name.get(key)
                if app:
                    discovered.append((original_name, environment, "auto"))
        matches = {}
        for name, env, region in discovered:
            matches.setdefault(name.lower(), []).append((name, env, region))
        for name, items in matches.items():
            unique_envs = {env.lower() for _, env, _ in items}
            if len(unique_envs) > 1:
                raise RuntimeError(f"API {name} was found in multiple Anypoint environments; replace auto with an explicit environment.")
            explicit.append(items[0])
        for name in auto_names.values():
            if name not in {x[0] for x in explicit}:
                raise RuntimeError(f"API {name} could not be found in any accessible Anypoint environment.")

    by_environment = {}
    for name, environment, region in explicit:
        if region == "auto":
            region = "all"
        if region != "all" and region not in REGIONS:
            raise RuntimeError(f"Invalid resolved region {region} for {name}.")
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

