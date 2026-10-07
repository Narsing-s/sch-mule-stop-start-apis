# Scheduler Email Alerts

The scheduler sends a completion email after every real START/STOP execution. The email contains the actual execution analytics produced by `scripts/mule_control.py`.

## Configure in GitHub

Add these to the same GitHub Environment used by the scheduler (currently `sandbox`).

### Environment variables

- `ALERT_EMAIL_TO` — recipient email address.
- `ALERT_EMAIL_FROM` — sender address. Optional; defaults to `SMTP_USERNAME`.
- `SMTP_HOST` — SMTP server hostname.
- `SMTP_PORT` — SMTP port. Defaults to `587`.
- `SMTP_SECURITY` — `starttls` (default) or `ssl`.

### Environment secrets

- `SMTP_USERNAME` — SMTP account/user.
- `SMTP_PASSWORD` — SMTP password or provider app password.

Do not put SMTP passwords or API credentials in repository files.

## Behavior

- Sends after START or STOP execution finishes.
- Sends for both complete success and partial/failed execution.
- Includes Business Group, Anypoint environment, group, region, total/success/failed counts, execution duration, poll interval, every API result, final state/message, per-API duration, and the GitHub Actions run link.
- The email step uses `continue-on-error: true`, so a mail-server problem does not incorrectly change a successful MuleSoft execution into a failed scheduler execution.
- Scheduler handoff runs do not send an email because no API execution occurred in that run.
