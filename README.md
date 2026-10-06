# MuleSoft API Auto Start / Stop Scheduler

Automatically starts and stops selected CloudHub 2.0 Mule applications using GitHub Actions.

## Automatic schedule

| India time (IST) | Action | Environments |
|---|---|---|
| **06:00 AM** | Stop | prod, dev, qa, sandbox, design |
| **06:00 PM** | Start | prod, dev, qa, sandbox, design |

The workflow uses the GitHub Actions `Asia/Kolkata` timezone. Scheduled runs can occasionally be delayed by GitHub platform load.

## API groups

Applications are separated into:

- `config/eapi/apis.txt` — EAPI
- `config/papi/apis.txt` — PAPI
- `config/sapi/apis.txt` — SAPI

Paste comma-separated application names and save/commit:

```text
customer-eapi,order-eapi,payment-eapi
```

One name per line is also supported. Comments and blank lines are ignored and duplicates are removed.

## Environments

The scheduler supports **prod, dev, qa, sandbox, and design**.

Scheduled runs process all five environments. Manual runs let you select one environment and one API group (`all`, `eapi`, `papi`, or `sapi`).

Create these GitHub Environments:

```text
prod
dev
qa
sandbox
design
```

Add these secrets to each environment:

- `ANYPOINT_CLIENT_ID`
- `ANYPOINT_CLIENT_SECRET`
- `ANYPOINT_ORG_ID`

Add this variable to each environment:

- `ANYPOINT_ENVIRONMENT` — exact Anypoint Platform environment name

Optional:

- `ANYPOINT_HOST` — defaults to `anypoint.mulesoft.com`

A single Connected App can be reused across environments only when it is authorized and has the required permissions in every target environment.

## Manual execution

GitHub → Actions → **MuleSoft API Auto Start Stop** → **Run workflow**.

Select:

1. `action`: `stop` or `start`
2. `environment`: `prod`, `dev`, `qa`, `sandbox`, or `design`
3. `group`: `all`, `eapi`, `papi`, or `sapi`

## Safety

- Only applications explicitly listed in EAPI/PAPI/SAPI files are controlled.
- Missing application names fail the run instead of guessing.
- The controller waits for the requested desired state and `APPLIED` deployment state.
- Applications are processed concurrently.
- Secrets remain in GitHub Environment secrets.
- Test manually on a non-production environment before enabling production scheduling.

## Files

```text
config/eapi/apis.txt
config/papi/apis.txt
config/sapi/apis.txt
scripts/mule_control.py
.github/workflows/mule-api-scheduler.yml
```

Before using the automatic schedule, confirm every listed application in every scheduled environment is safe to stop at 06:00 IST and start at 18:00 IST.
