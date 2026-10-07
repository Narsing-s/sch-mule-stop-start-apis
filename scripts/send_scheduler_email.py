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
    subject = f"MuleSoft API Scheduler - {action} #${{run_number}} — ${{environment}}"
    run_url = os.getenv("GITHUB_SERVER_URL", "https://github.com").rstrip("/") + "/" + os.getenv("GITHUB_REPOSITORY", "") + "/actions/runs/" + os.getenv("GITHUB_RUN_ID", "")
    run_number = os.getenv("GITHUB_RUN_NUMBER", os.getenv("GITHUB_RUN_ID", ""))
    environment = os.getenv("GITHUB_ENVIRONMENT", "sandbox").strip() or "sandbox"
    subject = f"MuleSoft API Scheduler - {action} #{run_number} — {environment}"
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
    # Spacious responsive HTML email. Keep API names readable and prevent
    # table cells from becoming cramped or overlapping on narrow clients.
    results = data.get("results", [])
    skipped = int(data.get("skipped", 0))
    successful = int(data.get("successful", 0))
    total = int(data.get("total", 0))
    failed = int(data.get("failed", 0))
    duration = data.get("total_duration_seconds", 0)
    region_filter = data.get("region", "all")
    environments = ", ".join(data.get("environments", [])) or "N/A"
    status_label = "Completed successfully" if failed == 0 else "Completed with failures"
    status_color = "#15803d" if failed == 0 else "#b91c1c"

    result_rows = []
    for row in results:
        result_value = str(row.get("result", ""))
        result_color = "#15803d" if result_value.upper() in {"SUCCESS", "STARTED", "STOPPED"} else "#b91c1c"
        result_rows.append(
            "<tr>"
            f"<td style='padding:15px 14px;border-top:1px solid #e5e7eb;vertical-align:top;white-space:nowrap'>{html.escape(str(row.get('environment','')))}</td>"
            f"<td style='padding:15px 14px;border-top:1px solid #e5e7eb;vertical-align:top;white-space:nowrap'>{html.escape(str(row.get('region','')))}</td>"
            f"<td style='padding:15px 14px;border-top:1px solid #e5e7eb;vertical-align:top;min-width:240px;word-break:break-word;overflow-wrap:anywhere;line-height:1.45'><strong>{html.escape(str(row.get('api','')))}</strong></td>"
            f"<td style='padding:15px 14px;border-top:1px solid #e5e7eb;vertical-align:top;white-space:nowrap'><span style='display:inline-block;padding:6px 11px;border-radius:999px;background:{result_color}18;color:{result_color};font-weight:800;font-size:12px'>{html.escape(result_value or 'N/A')}</span></td>"
            f"<td style='padding:15px 14px;border-top:1px solid #e5e7eb;vertical-align:top;min-width:220px;word-break:break-word;overflow-wrap:anywhere;line-height:1.45'>{html.escape(str(row.get('final_state','')))}</td>"
            f"<td style='padding:15px 14px;border-top:1px solid #e5e7eb;vertical-align:top;white-space:nowrap'>{html.escape(str(row.get('duration_seconds',0)))}s</td>"
            "</tr>"
        )
    if skipped:
        result_rows.append("<tr><td colspan='6' style='padding:16px;border-top:1px solid #e5e7eb;color:#64748b'><strong>"+str(skipped)+" API(s) skipped</strong> — not present in the configured runtime and safely continued.</td></tr>")
    result_table = "".join(result_rows) or "<tr><td colspan='6' style='padding:18px'>No API results available.</td></tr>"

    body = f"""<!doctype html>
<html>
<body style="margin:0;padding:0;background:#eef2f7;font-family:Arial,Helvetica,sans-serif;color:#111827">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background:#eef2f7">
<tr><td align="center" style="padding:40px 18px">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="max-width:1180px;background:#ffffff;border:1px solid #dbe2ea;border-radius:18px;overflow:hidden">
<tr><td style="background:#111827;padding:34px 38px;color:#ffffff">
  <div style="font-size:12px;letter-spacing:1.8px;text-transform:uppercase;color:#cbd5e1;font-weight:800">MuleSoft Automation</div>
  <div style="font-size:30px;line-height:1.2;font-weight:800;margin-top:9px">API Start / Stop Control</div>
  <div style="font-size:15px;color:#cbd5e1;margin-top:8px">{html.escape(action)} execution report</div>
</td></tr>
<tr><td style="padding:34px 38px">
  <div style="border-left:5px solid {status_color};padding:16px 20px;background:#f8fafc;border-radius:10px;margin-bottom:28px">
    <div style="font-size:20px;font-weight:800;color:{status_color}">{html.escape(status_label)}</div>
    <div style="font-size:14px;color:#64748b;margin-top:6px">The MuleSoft API {html.escape(action)} operation has finished.</div>
  </div>

  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0"><tr>
    <td width="50%" valign="top" style="padding:0 7px 14px 0"><div style="min-height:72px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:12px;padding:17px"><div style="font-size:12px;color:#64748b">Business Group</div><div style="font-size:15px;font-weight:700;margin-top:7px;word-break:break-word">{html.escape(str(data.get("business_group","N/A")))}</div></div></td>
    <td width="50%" valign="top" style="padding:0 0 14px 7px"><div style="min-height:72px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:12px;padding:17px"><div style="font-size:12px;color:#64748b">Environment(s)</div><div style="font-size:15px;font-weight:700;margin-top:7px;word-break:break-word">{html.escape(environments)}</div></div></td>
  </tr><tr>
    <td width="50%" valign="top" style="padding:0 7px 14px 0"><div style="min-height:72px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:12px;padding:17px"><div style="font-size:12px;color:#64748b">Region filter</div><div style="font-size:15px;font-weight:700;margin-top:7px">{html.escape(str(region_filter))}</div></div></td>
    <td width="50%" valign="top" style="padding:0 0 14px 7px"><div style="min-height:72px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:12px;padding:17px"><div style="font-size:12px;color:#64748b">Execution time</div><div style="font-size:15px;font-weight:700;margin-top:7px">{html.escape(str(duration))} seconds</div></div></td>
  </tr></table>

  <div style="margin:24px 0 12px;font-size:19px;font-weight:800">Execution summary</div>
  <table role="presentation" width="100%" cellspacing="8" cellpadding="0" border="0"><tr>
    <td align="center" style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:12px;padding:18px"><div style="font-size:28px;font-weight:800">{total}</div><div style="font-size:12px;color:#64748b;margin-top:4px">Total APIs</div></td>
    <td align="center" style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:12px;padding:18px"><div style="font-size:28px;font-weight:800;color:#15803d">{successful}</div><div style="font-size:12px;color:#64748b;margin-top:4px">Successful</div></td>
    <td align="center" style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:12px;padding:18px"><div style="font-size:28px;font-weight:800;color:#b91c1c">{failed}</div><div style="font-size:12px;color:#64748b;margin-top:4px">Failed</div></td>
    <td align="center" style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:12px;padding:18px"><div style="font-size:28px;font-weight:800">{skipped}</div><div style="font-size:12px;color:#64748b;margin-top:4px">Skipped</div></td>
  </tr></table>

  <div style="margin:30px 0 12px;font-size:19px;font-weight:800">API execution details</div>
  <div style="border:1px solid #dbe2ea;border-radius:12px;overflow-x:auto;background:#fff">
    <table width="100%" cellspacing="0" cellpadding="0" border="0" style="border-collapse:collapse;table-layout:auto;min-width:900px;font-size:13px">
      <tr style="background:#f8fafc">
        <th align="left" style="padding:14px;font-size:12px;color:#475569;white-space:nowrap">Environment</th>
        <th align="left" style="padding:14px;font-size:12px;color:#475569;white-space:nowrap">Region</th>
        <th align="left" style="padding:14px;font-size:12px;color:#475569;min-width:240px">API / Application</th>
        <th align="left" style="padding:14px;font-size:12px;color:#475569;white-space:nowrap">Result</th>
        <th align="left" style="padding:14px;font-size:12px;color:#475569;min-width:220px">Final state</th>
        <th align="left" style="padding:14px;font-size:12px;color:#475569;white-space:nowrap">Duration</th>
      </tr>
      {result_table}
    </table>
  </div>

  <div style="margin-top:30px;text-align:center">
    <a href="{html.escape(run_url)}" style="display:inline-block;background:#2563eb;color:#ffffff;text-decoration:none;padding:14px 24px;border-radius:9px;font-weight:800;font-size:14px">Open GitHub Actions Run</a>
  </div>
</td></tr>
<tr><td style="padding:22px 38px;background:#f8fafc;border-top:1px solid #e2e8f0;text-align:center;color:#64748b;font-size:11px">
Automated notification • MuleSoft API Start / Stop Control
</td></tr>
</table>
</td></tr>
</table>
</body></html>"""
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
