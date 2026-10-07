# 🚀 MuleSoft API Auto Start / Stop Scheduler

> **Production-oriented GitHub Actions scheduler for controlling MuleSoft CloudHub 2.0 applications with configurable timing, environment selection, Business Group support, state verification, and execution analytics.**

[![GitHub Actions](https://img.shields.io/badge/GitHub%20Actions-Automated-2088FF?logo=githubactions&logoColor=white)](../../actions)
[![MuleSoft](https://img.shields.io/badge/MuleSoft-CloudHub%202.0-00A1DF)](https://www.mulesoft.com/)
[![Python](https://img.shields.io/badge/Python-3.12+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](#license)

## ✨ What it does

This project automates the **start/stop lifecycle of selected MuleSoft applications** through GitHub Actions.

Instead of using a fixed cron schedule, the workflow is designed around the repository's scheduler configuration:

**Configure → Trigger immediately → Wait for the configured time → Execute → Verify → Report → Queue the next cycle**

### Key capabilities

| Capability | Details |
|---|---|
| ⏱️ Configurable timing | Define start/stop timing in scheduler configuration |
| ⚡ Immediate trigger | Configuration changes can start the scheduler workflow immediately |
| ⏳ Wait-before-run | The workflow waits until the configured execution time |
| 🌎 Timezone | Supports `Asia/Kolkata` / IST |
| 🏢 Business Groups | Business Group is configurable; it is not hardcoded |
| 🌐 Environments | Supports Sandbox, Development, QA, Design and Production |
| 🎯 API groups | EAPI, PAPI, SAPI or all |
| 🔄 Start / Stop | Controls selected MuleSoft applications |
| 🔎 State verification | Waits for the requested deployment/desired state |
| 📊 Analytics | Generates execution-level and API-level results |
| 📧 Email alerts | Sends completion analytics to multiple recipients |
| 🔐 Secrets | Credentials are stored in GitHub Environment secrets |
| 🛡️ Safety | Only explicitly configured applications are controlled |

---

## 🏗️ Architecture

```text
                    ┌──────────────────────────┐
                    │  Repository Configuration │
                    │  Schedule / APIs / Groups │
                    └────────────┬─────────────┘
                                 │
                                 ▼
                    ┌──────────────────────────┐
                    │     GitHub Actions       │
                    │  Immediate Trigger        │
                    └────────────┬─────────────┘
                                 │
                                 ▼
                    ┌──────────────────────────┐
                    │     Schedule Waiter      │
                    │  IST / configured time   │
                    └────────────┬─────────────┘
                                 │
                                 ▼
                    ┌──────────────────────────┐
                    │  Anypoint Authentication │
                    │  Connected App           │
                    └────────────┬─────────────┘
                                 │
                                 ▼
              ┌──────────────────┴──────────────────┐
              │                                     │
              ▼                                     ▼
      ┌─────────────────┐                   ┌─────────────────┐
      │ MuleSoft APIs   │                   │ Business Group  │
      │ EAPI/PAPI/SAPI  │                   │ + Environment   │
      └────────┬────────┘                   └────────┬────────┘
               └────────────────┬────────────────────┘
                                ▼
                    ┌──────────────────────────┐
                    │ Start / Stop Controller  │
                    │ State + Deployment Poll  │
                    └────────────┬─────────────┘
                                 │
                                 ▼
                    ┌──────────────────────────┐
                    │ Execution Analytics       │
                    │ Success / Failed / Time   │
                    └────────────┬─────────────┘
                                 │
                                 ▼
                    ┌──────────────────────────┐
                    │ 📧 Email Notifications   │
                    │ Multiple Recipients       │
                    └──────────────────────────┘
```

---

## 📁 Repository structure

```text
sch-mule-stop-start-apis/
├── .github/
│   └── workflows/
│       └── mule-api-scheduler.yml
│
├── config/
│   ├── eapi/
│   │   └── apis.txt
│   ├── papi/
│   │   └── apis.txt
│   └── sapi/
│       └── apis.txt
│
├── scripts/
│   ├── mule_control.py
│   ├── schedule_wait.py
│   └── send_scheduler_email.py
│
└── README.md
```

---

## ⚙️ API configuration

Applications are controlled only when they are explicitly listed in the API-group files.

### EAPI

```text
config/eapi/apis.txt
```

### PAPI

```text
config/papi/apis.txt
```

### SAPI

```text
config/sapi/apis.txt
```

Both formats are supported:

```text
customer-eapi
order-eapi
payment-eapi
```

or:

```text
customer-eapi,order-eapi,payment-eapi
```

Blank lines and comments are ignored, and duplicate application names are removed.

> **Important:** The scheduler does not guess application names. If an application is missing from configuration, it is not controlled.

---

## 🌍 Environment model

The scheduler supports:

- `sandbox`
- `dev`
- `qa`
- `design`
- `prod`

Create the corresponding GitHub Environments and configure credentials separately where required.

### Required secrets

Configure these as **GitHub Environment secrets**:

```text
ANYPOINT_CLIENT_ID
ANYPOINT_CLIENT_SECRET
ANYPOINT_ORG_ID
```

### Environment selection

Configure the exact Anypoint Platform environment name using:

```text
ANYPOINT_ENVIRONMENT
```

Optional:

```text
ANYPOINT_HOST
```

If `ANYPOINT_HOST` is not supplied, the workflow uses:

```text
anypoint.mulesoft.com
```

> A single Connected App may be reused across multiple environments when it is authorized and has the required permissions in each target environment.

---

## 🏢 Business Group

Business Group selection is **configuration-driven**.

Do not hardcode a Business Group in the workflow or Python scripts.

The selected Business Group is passed through to the Anypoint Platform operations so the same scheduler can be used across different Business Groups.

---

## ⏰ Scheduling model

This project intentionally avoids depending on a traditional fixed cron schedule.

The intended lifecycle is:

```text
Configuration updated
        ↓
Workflow triggered immediately
        ↓
Read scheduler configuration
        ↓
Calculate next configured execution time
        ↓
Wait
        ↓
Execute START / STOP
        ↓
Verify final state
        ↓
Generate analytics
        ↓
Send email notification
        ↓
Queue next scheduler cycle
```

This means changing the configured execution time does not require editing a GitHub cron expression.

> GitHub-hosted runners can still experience platform-level startup delays. The scheduler controls the configured execution time after the workflow has started.

---

## ▶️ Manual execution

Open:

**GitHub → Actions → MuleSoft API Auto Start Stop → Run workflow**

Available controls include:

- **Action:** `start`, `stop`, or scheduler flow where supported
- **Group:** `all`, `eapi`, `papi`, `sapi`
- **Region:** configurable target region where applicable
- **Business Group:** selected rather than hardcoded

Manual execution is useful for testing a configuration on Sandbox before applying the same process to Production.

---

## 📊 Execution analytics

After an execution, the scheduler records analytics such as:

- Action
- Business Group
- Environment
- API group
- Region
- Total APIs
- Successful APIs
- Failed APIs
- Final deployment state
- Per-API execution duration
- Overall execution duration
- Poll interval
- GitHub Actions run

The analytics are written to:

```text
mule-execution-analytics.json
```

---

## 📧 Email notifications

The scheduler can send a completion report after START/STOP execution.

### Multiple recipients

Configure recipients as a comma-separated list:

```text
ALERT_EMAIL_TO=user1@company.com,user2@company.com,user3@company.com
```

Semicolon-separated values are also supported:

```text
ALERT_EMAIL_TO=user1@company.com;user2@company.com
```

Recipients should be configured in the GitHub Environment rather than committed to source control.

### Email configuration

**Environment variables**

```text
SMTP_HOST
SMTP_PORT
SMTP_SECURITY
ALERT_EMAIL_FROM
ALERT_EMAIL_TO
```

**Environment secrets**

```text
SMTP_USERNAME
SMTP_PASSWORD
```

Recommended default for STARTTLS:

```text
SMTP_PORT=587
SMTP_SECURITY=starttls
```

The email contains execution analytics and a link back to the GitHub Actions run.

---

## 🔐 Security

### Never commit

Do **not** place any of these in repository files:

- Anypoint Client Secret
- SMTP password
- SMTP app password
- Personal mailbox password
- Private tokens
- Production credentials

Use GitHub **Environment Secrets** instead.

### Recommended environment isolation

```text
sandbox → development → qa/design → production
```

Validate the scheduler against Sandbox before enabling Production operations.

---

## 🛡️ Operational safeguards

The scheduler is designed to reduce accidental production changes:

- Only configured API names are processed.
- Unknown/missing application names are not guessed.
- Business Group is selected through configuration.
- Environment is explicitly resolved.
- Start/stop operations wait for the requested state.
- Deployment state is checked before completion.
- Execution results are captured for every API.
- Credentials remain outside source control.
- Email delivery is separated from the core MuleSoft control operation.

---

## 🧰 Main components

### `scripts/schedule_wait.py`

Responsible for interpreting scheduler timing and waiting until the configured execution window.

### `scripts/mule_control.py`

Responsible for MuleSoft application control and state verification.

### `scripts/send_scheduler_email.py`

Responsible for generating and sending execution analytics through SMTP, including support for multiple recipients.

### `.github/workflows/mule-api-scheduler.yml`

Orchestrates:

1. Configuration validation
2. Authentication
3. Business Group/environment selection
4. Scheduler wait
5. MuleSoft start/stop operations
6. Analytics generation
7. Email notification
8. Next-cycle queueing

---

## 🧪 Recommended rollout

### 1. Configure Sandbox

Start with:

```text
sandbox
```

### 2. Add a small API list

Use one or two non-critical applications.

### 3. Run manually

Verify:

- Authentication
- Business Group
- Environment
- Application discovery
- Start/stop behavior
- State polling
- Analytics
- Email delivery

### 4. Add recipients

```text
ALERT_EMAIL_TO=user1@company.com,user2@company.com
```

### 5. Expand API groups

Add EAPI/PAPI/SAPI applications only after Sandbox validation.

### 6. Enable Production carefully

Confirm every Production application is safe to stop/start according to the configured schedule.

---

## 🚨 Troubleshooting

### `ANYPOINT_CLIENT_ID` missing

Check the selected GitHub Environment and confirm the required Anypoint secrets exist.

### `ANYPOINT_ENVIRONMENT` missing

Add the exact Anypoint Platform environment name to the selected GitHub Environment.

### SMTP authentication disconnects

Check:

- SMTP hostname
- Port
- STARTTLS/SSL mode
- SMTP username
- SMTP password/app password
- Whether SMTP AUTH is enabled for the mailbox
- Whether your corporate SMTP relay permits authenticated SMTP

### Only one recipient receives email

Verify that `ALERT_EMAIL_TO` uses comma or semicolon separation:

```text
user1@company.com,user2@company.com
```

The scheduler explicitly sends the message to every parsed recipient.

### Application does not change state

Check:

- Business Group
- Anypoint environment
- Application name
- Connected App permissions
- Deployment status
- Runtime/Platform availability

---

## 📌 Production checklist

Before Production use:

- [ ] GitHub Environment created
- [ ] Anypoint Connected App authorized
- [ ] Client ID configured as secret
- [ ] Client Secret configured as secret
- [ ] Organization ID configured
- [ ] Exact Anypoint Environment configured
- [ ] Business Group verified
- [ ] EAPI/PAPI/SAPI application lists reviewed
- [ ] Scheduler time verified in IST
- [ ] SMTP configuration verified
- [ ] Multiple email recipients tested
- [ ] Sandbox execution completed successfully
- [ ] Production applications approved for start/stop
- [ ] First Production execution monitored

---

## 🤝 Operating principle

**Configuration controls behavior. Secrets control access. GitHub Actions controls execution. The scheduler waits for the configured time. Analytics provide traceability. Email provides visibility.**

---

## 📄 License

MIT
