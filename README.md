# MuleSoft API Auto Start / Stop Scheduler

Automates CloudHub 2.0 Mule application lifecycle management from GitHub Actions.

## Schedule

| IST time | Action |
|---|---|
| **06:00 AM** | Stop configured MuleSoft APIs |
| **06:00 PM** | Start configured MuleSoft APIs |

The workflow uses the Asia/Kolkata timezone.

## Configure targets

Edit `config/apis.txt` and add the exact CloudHub 2.0 application names, one per line.

Example:

```text
integration-with-ai-api
monthly-bank-satement-generate-api
dream-bank-sapi
```

Only add applications that are safe to stop at 06:00 IST and start at 18:00 IST.

## GitHub Environment

Create a GitHub Environment named `prod`. Add these environment secrets:

- `ANYPOINT_CLIENT_ID`
- `ANYPOINT_CLIENT_SECRET`
- `ANYPOINT_ORG_ID`

Add this environment variable:

- `ANYPOINT_ENVIRONMENT` — exact Anypoint Platform environment name

Optional:

- `ANYPOINT_HOST` — defaults to `anypoint.mulesoft.com`; use `eu1.anypoint.mulesoft.com` for EU.

## Connected App

Use an Anypoint Platform Connected App with the `client_credentials` grant and the minimum Runtime Manager / organization / environment permissions required to list and control the target applications.

## Manual test

Go to **GitHub → Actions → MuleSoft API Auto Start Stop → Run workflow**.

Choose `stop` or `start` and the GitHub Environment.

## Safety

- Only applications listed in `config/apis.txt` are controlled.
- Missing application names fail the workflow instead of guessing.
- Secrets are kept in GitHub Environment secrets.
- The controller polls after each start/stop request.
- Any failed application makes the workflow fail.

## Important scheduling note

GitHub Actions scheduled workflows can be delayed during periods of high platform load. The 06:00/18:00 IST values are the scheduled trigger times, not a hard real-time SLA.

For strict real-time enterprise scheduling, an external scheduler/control plane should trigger the same lifecycle logic.
