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
    recipients = [x.strip() for x in recipient.replace(";", ",").split(",") if x.strip()]
    if not recipients: raise SystemExit("ALERT_EMAIL_TO contains no recipients.")
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
        f"Business Group: {data.get('business_group', '')}",
        f"Environments: {', '.join(data.get('environments', []))}",
        f"Region filter: {data.get('region', 'all')}",
        f"Total APIs: {data.get('total', 0)}",
        f"Successful: {data.get('successful', 0)}",
        f"Failed: {failed}",
        f"Execution time: {data.get('total_duration_seconds', 0)} seconds",
        f"Poll interval: {data.get('poll_interval_seconds', 0)} seconds", "",
        "API-level results:",
    ]
    for row in data.get("results", []):
        lines.append(f"- {row.get('environment','').upper()}/{row.get('region','').upper()} {row.get('api','')}: {row.get('result','')} - {row.get('final_state','')} ({row.get('duration_seconds',0)}s)")
    lines.extend(["", f"GitHub Actions run: {run_url}"])
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, sender, recipient
    msg.set_content("\n".join(lines))
    # Modern responsive HTML email; delivery logic and analytics data remain unchanged.
    results = data.get("results", [])
    skipped = int(data.get("skipped", 0))
    successful = int(data.get("successful", 0))
    total = int(data.get("total", 0))
    failed = int(data.get("failed", 0))
    duration = data.get("total_duration_seconds", 0)
    region_filter = data.get("region", "all")
    environments = ", ".join(data.get("environments", [])) or "N/A"
    status_label = "Completed successfully" if failed == 0 else "Completed with failures"
    status_color = "#16a34a" if failed == 0 else "#dc2626"

    result_rows = []
    for row in results:
        result_value = str(row.get("result", ""))
        result_color = "#16a34a" if result_value.upper() in {"SUCCESS", "STARTED", "STOPPED"} else "#dc2626"
        result_rows.append(
            "<tr>"
            f"<td>{html.escape(str(row.get('environment','')))}</td>"
            f"<td>{html.escape(str(row.get('region','')))}</td>"
            f"<td><strong>{html.escape(str(row.get('api','')))}</strong></td>"
            f"<td><span style='display:inline-block;padding:4px 9px;border-radius:999px;background:{result_color}18;color:{result_color};font-weight:700;font-size:12px'>{html.escape(result_value or 'N/A')}</span></td>"
            f"<td>{html.escape(str(row.get('final_state','')))}</td>"
            f"<td>{html.escape(str(row.get('duration_seconds',0)))}s</td>"
            "</tr>"
        )
    if skipped:
        result_rows.append(
            "<tr><td colspan='6' style='padding:14px;color:#64748b'>"
            f"<strong>{skipped} API(s) skipped</strong> — not present in the configured runtime and safely continued."
            "</td></tr>"
        )
    result_table = "".join(result_rows) or "<tr><td colspan='6'>No API results available.</td></tr>"

    body = f"""<!doctype html>
<html><body style="margin:0;background:#f1f5f9;font-family:Arial,Helvetica,sans-serif;color:#0f172a">
<div style="max-width:900px;margin:0 auto;padding:28px 16px">
  <div style="background:#0f172a;border-radius:18px 18px 0 0;padding:26px 28px;color:#fff">
    <div style="font-size:12px;letter-spacing:1.4px;text-transform:uppercase;color:#cbd5e1;font-weight:700">MuleSoft Automation</div>
    <div style="font-size:26px;font-weight:800;margin-top:8px">API Start / Stop Control</div>
    <div style="font-size:14px;color:#cbd5e1;margin-top:6px">{html.escape(action)} execution report</div>
  </div>
  <div style="background:#fff;border:1px solid #e2e8f0;border-top:0;padding:26px 28px">
    <div style="border-left:5px solid {status_color};padding:10px 14px;background:#f8fafc;border-radius:8px;margin-bottom:22px">
      <div style="font-size:18px;font-weight:800;color:{status_color}">{html.escape(status_label)}</div>
      <div style="font-size:13px;color:#64748b;margin-top:4px">MuleSoft API {html.escape(action)} operation has finished.</div>
    </div>
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0"><tr>
      <td width="50%" valign="top" style="padding:6px"><div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:12px;padding:16px"><div style="font-size:12px;color:#64748b">Business Group</div><div style="font-weight:700;margin-top:5px">{html.escape(str(data.get("business_group","N/A")))}</div></div></td>
      <td width="50%" valign="top" style="padding:6px"><div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:12px;padding:16px"><div style="font-size:12px;color:#64748b">Environment(s)</div><div style="font-weight:700;margin-top:5px">{html.escape(environments)}</div></div></td>
    </tr><tr>
      <td width="50%" valign="top" style="padding:6px"><div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:12px;padding:16px"><div style="font-size:12px;color:#64748b">Region filter</div><div style="font-weight:700;margin-top:5px">{html.escape(str(region_filter))}</div></div></td>
      <td width="50%" valign="top" style="padding:6px"><div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:12px;padding:16px"><div style="font-size:12px;color:#64748b">Execution time</div><div style="font-weight:700;margin-top:5px">{html.escape(str(duration))} seconds</div></div></td>
    </tr></table>

    <div style="margin:22px 0 10px;font-size:17px;font-weight:800">Execution summary</div>
    <table role="presentation" width="100%" cellspacing="8" cellpadding="0"><tr>
      <td align="center" style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:12px;padding:14px"><div style="font-size:24px;font-weight:800">{total}</div><div style="font-size:12px;color:#64748b">Total</div></td>
      <td align="center" style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:12px;padding:14px"><div style="font-size:24px;font-weight:800;color:#16a34a">{successful}</div><div style="font-size:12px;color:#64748b">Successful</div></td>
      <td align="center" style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:12px;padding:14px"><div style="font-size:24px;font-weight:800;color:#dc2626">{failed}</div><div style="font-size:12px;color:#64748b">Failed</div></td>
      <td align="center" style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:12px;padding:14px"><div style="font-size:24px;font-weight:800">{skipped}</div><div style="font-size:12px;color:#64748b">Skipped</div></td>
    </tr></table>

    <div style="margin:24px 0 10px;font-size:17px;font-weight:800">API execution details</div>
    <div style="overflow-x:auto;border:1px solid #e2e8f0;border-radius:12px">
      <table width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;font-size:12px">
        <tr style="background:#f8fafc"><th align="left" style="padding:11px">Environment</th><th align="left" style="padding:11px">Region</th><th align="left" style="padding:11px">API</th><th align="left" style="padding:11px">Result</th><th align="left" style="padding:11px">Final state</th><th align="left" style="padding:11px">Duration</th></tr>
        {result_table}
      </table>
    </div>

    <div style="margin-top:24px;text-align:center">
      <a href="{html.escape(run_url)}" style="display:inline-block;background:#2563eb;color:#fff;text-decoration:none;padding:12px 20px;border-radius:9px;font-weight:700;font-size:13px">Open GitHub Actions Run</a>
    </div>
  </div>
  <div style="text-align:center;padding:18px;color:#64748b;font-size:11px">
    Automated notification • MuleSoft API Start / Stop Control
  </div>
</div></body></html>"""
    msg.add_alternative(body, subtype="html")
    context = ssl.create_default_context()
    try:
        if security == "ssl":
            with smtplib.SMTP_SSL(host, port, context=context, timeout=30) as server:
                server.login(username, password); server.send_message(msg, from_addr=sender, to_addrs=recipients)
        else:
            with smtplib.SMTP(host, port, timeout=30) as server:
                server.ehlo(); server.starttls(context=context); server.ehlo(); server.login(username, password); server.send_message(msg, from_addr=sender, to_addrs=recipients)
    except smtplib.SMTPDataError as exc:
        # Do not turn a completed Mule execution into a failed workflow when
        # the SMTP provider rejects delivery (for example Gmail 550 5.4.5
        # daily sending limit). The analytics file remains the source of truth.
        if getattr(exc, "smtp_code", None) == 550 and "5.4.5" in str(getattr(exc, "smtp_error", b"")):
            print(f"WARNING: SMTP provider rejected the alert because the sending limit was exceeded: {exc}", flush=True)
            return 0
        raise
    print(f"Scheduler email alert sent to {recipient}.", flush=True)
    return 0

if __name__ == "__main__": raise SystemExit(main())
