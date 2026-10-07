#!/usr/bin/env python3
"""Send completed MuleSoft scheduler analytics by email."""
from __future__ import annotations
import html, json, os, smtplib, ssl, sys
from email.message import EmailMessage
from pathlib import Path

def required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value: raise SystemExit(f"{name} is required to send scheduler email alerts.")
    return value

def main() -> int:
    path = Path(os.getenv("MULE_ANALYTICS_FILE", "mule-execution-analytics.json"))
    if not path.exists(): raise SystemExit(f"Analytics file not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    recipient = required("ALERT_EMAIL_TO")
    host = required("SMTP_HOST")
    username = required("SMTP_USERNAME")
    password = required("SMTP_PASSWORD")
    sender = os.getenv("ALERT_EMAIL_FROM", username).strip() or username
    port = int(os.getenv("SMTP_PORT", "587"))
    security = os.getenv("SMTP_SECURITY", "starttls").strip().lower()
    action = str(data.get("action", "unknown")).upper()
    failed = int(data.get("failed", 0))
    status = "SUCCESS" if failed == 0 else "FAILED"
    subject = f"MuleSoft API Scheduler - {action} - {status}"
    run_url = os.getenv("GITHUB_SERVER_URL", "https://github.com").rstrip("/") + "/" + os.getenv("GITHUB_REPOSITORY", "") + "/actions/runs/" + os.getenv("GITHUB_RUN_ID", "")
    lines = [
        subject, "",
        f"Business Group: {data.get("business_group", "")}",
        f"Environment: {data.get("environment", "")}",
        f"Group: {data.get("group", "all")}",
        f"Region: {data.get("region", "all")}",
        f"Total APIs: {data.get("total", 0)}",
        f"Successful: {data.get("successful", 0)}",
        f"Failed: {failed}",
        f"Execution time: {data.get("total_duration_seconds", 0)} seconds",
        f"Poll interval: {data.get("poll_interval_seconds", 0)} seconds", "",
        "API-level results:",
    ]
    for row in data.get("results", []):
        lines.append(f"- {row.get("group","").upper()}/{row.get("region","").upper()} {row.get("api","")}: {row.get("result","")} - {row.get("final_state","")} ({row.get("duration_seconds",0)}s)")
    lines.extend(["", f"GitHub Actions run: {run_url}"])
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, sender, recipient
    msg.set_content("\n".join(lines))
    rows = ""
    for row in data.get("results", []):
        rows += "<tr>" + "".join("<td>" + html.escape(str(row.get(k, ""))) + "</td>" for k in ("group","region","api","result","final_state","duration_seconds")) + "</tr>"
    body = "<h2>" + html.escape(subject) + "</h2>"
    body += "<table border=1 cellpadding=6 cellspacing=0><tr><th>Metric</th><th>Value</th></tr>"
    for k,v in (("Business Group",data.get("business_group","")),("Environment",data.get("environment","")),("Group",data.get("group","all")),("Region",data.get("region","all")),("Total APIs",data.get("total",0)),("Successful",data.get("successful",0)),("Failed",failed),("Execution time",str(data.get("total_duration_seconds",0))+" seconds"),("Poll interval",str(data.get("poll_interval_seconds",0))+" seconds")):
        body += "<tr><td>"+html.escape(str(k))+"</td><td>"+html.escape(str(v))+"</td></tr>"
    body += "</table><h3>API-level results</h3><table border=1 cellpadding=6 cellspacing=0><tr><th>Group</th><th>Region</th><th>API</th><th>Result</th><th>Final state</th><th>Duration</th></tr>"+rows+"</table>"
    body += "<p><a href=\"" + html.escape(run_url) + "\">Open GitHub Actions run</a></p>"
    msg.add_alternative(body, subtype="html")
    context = ssl.create_default_context()
    if security == "ssl":
        with smtplib.SMTP_SSL(host, port, context=context, timeout=30) as server:
            server.login(username, password); server.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=30) as server:
            server.ehlo(); server.starttls(context=context); server.ehlo(); server.login(username, password); server.send_message(msg)
    print(f"Scheduler email alert sent to {recipient}.", flush=True)
    return 0

if __name__ == "__main__": raise SystemExit(main())
