# autowebprompt

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Playwright](https://img.shields.io/badge/Playwright-1.40+-green.svg)](https://playwright.dev/python/)

**Drive ChatGPT and Claude like a real user — from the command line.**

Some of the best AI features only exist in the browser: ChatGPT Agent Mode, Claude Extended Thinking, file uploads, artifact downloads. `autowebprompt` gives you programmatic access to all of it by automating a real Chrome session via Playwright and CDP.

Send prompts, upload spreadsheets, download results, run hundreds of tasks in batch — then optionally pipe everything to S3 and PostgreSQL. One `pip install`, one command.

```
You                    autowebprompt               Chrome (CDP)
 |                          |                          |
 |  autowebprompt run ...   |                          |
 |------------------------->|                          |
 |                          |   navigate, upload,      |
 |                          |   send prompts, wait,    |
 |                          |   download artifacts     |
 |                          |------------------------->|
 |                          |                          |  chatgpt.com
 |                          |                          |  or claude.ai
 |                          |<-------------------------|
 |  results + artifacts     |                          |
 |<-------------------------|                          |
```

---

## Prerequisites

Before you start, you'll need:

| Requirement | Details |
|-------------|---------|
| **Python** | 3.10 or newer |
| **Google Chrome** | Chrome or Chrome Canary (for CDP remote debugging) |
| **Playwright** | Installed automatically; run `playwright install chromium` after install |
| **ChatGPT subscription** | **Plus** ($20/mo) or **Pro** ($200/mo) — required for Agent Mode and extended thinking |
| **Claude subscription** | **Pro** ($20/mo) or **Max** ($100–200/mo) — required for extended thinking and higher rate limits |

> **Usage policy.** This tool automates your own logged-in browser session on your own machine. You are responsible for using it in compliance with [OpenAI's Terms of Use](https://openai.com/policies/terms-of-use) and [Anthropic's Acceptable Use Policy](https://www.anthropic.com/legal/aup). Automated access may be subject to rate limits or additional restrictions under those agreements. Use responsibly.

---

## Quick Start

### 1. Install

```bash
pip install autowebprompt
playwright install chromium
```

Or from source:

```bash
git clone https://github.com/NewYorkAILabs/autowebprompt.git
cd autowebprompt
pip install -e ".[dev]"
playwright install chromium
```

### 2. Start Chrome with CDP

```bash
# macOS
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --remote-debugging-port=9222 \
  --user-data-dir=~/.autowebprompt-chrome-profile

# Linux
google-chrome --remote-debugging-port=9222 \
  --user-data-dir=~/.autowebprompt-chrome-profile
```

Log into **ChatGPT** or **Claude** in that browser window.

### 3. Run the Setup Wizard

```bash
autowebprompt setup
```

This copies a starter template and example task file into your project.

### 4. Configure

Edit the template to set your project ID and prompts:

```yaml
# template_chatgpt.yaml
template:
  agent_type: "chatgpt_web"
  download_artifacts: true

  prompts:
    - "Analyze the uploaded files and build a financial model."

  chatgpt_web:
    project_id: "YOUR_PROJECT_ID"
    agent_mode: true
    extended_thinking: true
    max_sec_per_task: 5400
```

### 5. Run

```bash
# ChatGPT
autowebprompt run --provider chatgpt \
  --tasks tasks.yaml --template template_chatgpt.yaml

# Claude
autowebprompt run --provider claude \
  --tasks tasks.yaml --template template_claude.yaml

# With database task fetching
autowebprompt run --provider chatgpt \
  --tasks tasks.yaml --fetch-from-db
```

---

## Features

| Feature | Claude | ChatGPT |
|---------|--------|---------|
| Send prompts | Yes | Yes |
| Upload files | Yes | Yes |
| Download artifacts | Yes | Yes (CDP) |
| Extended thinking | Yes | Yes |
| Agent mode | — | Yes |
| Web search | Yes | Yes |
| Batch execution | Yes | Yes |
| Retry on failure | Yes | Yes |
| S3 upload (optional) | Yes | Yes |
| DB logging (optional) | Yes | Yes |

---

## CLI Commands

```
autowebprompt setup       # Interactive setup wizard
autowebprompt run         # Run batch tasks
autowebprompt check       # Verify Chrome CDP is running
autowebprompt templates   # Show template examples
autowebprompt db init     # Provision a free Neon PostgreSQL database
autowebprompt db migrate  # Run schema migration
autowebprompt db status   # Show connection and table status
```

### `run` Options

| Option | Description |
|--------|-------------|
| `--provider` | `claude` or `chatgpt` (required) |
| `--tasks` | Path to YAML task file |
| `--template` | Path to template config |
| `--fetch-from-db` | Fetch task files from database |
| `--dry-run` | Preview without executing |
| `--start` / `--end` | Task index range |
| `--timeout` | Per-task timeout in seconds |

---

## Configuration

### Template Structure

Templates control agent behavior, timing, and retry policy:

```yaml
template:
  agent_type: "chatgpt_web"    # or "claude_web"
  download_artifacts: true
  upload_to_cloud: false

  prompts:
    - "Your prompt text here"

  chatgpt_web:                  # or claude_web:
    project_id: "YOUR_ID"
    agent_mode: true
    max_sec_per_task: 5400
    max_wait_per_prompt_seconds: 5400
    check_interval_seconds: 3

    browser:
      type: "chrome"
      cdp_port: 9222

    retry:
      max_agent_attempts: 3
      max_total_attempts: 10
      sleep_between_retries: 5
```

### Task File

```yaml
task_source: "my_project"
tasks:
  - "task-1-analysis"
  - "task-2-modeling"
```

---

## Optional: Database

Track task results across runs with a free PostgreSQL database. The quickest setup is one command:

```bash
pip install "autowebprompt[storage]"
autowebprompt db init
```

This will:
1. Ask for your [Neon API key](https://console.neon.tech/app/settings/api-keys) (free tier works)
2. Create a database and run the schema migration
3. Save the connection string to `.env.local`

Already have a Neon key? Pass it directly:

```bash
autowebprompt db init --api-key <your-key>
```

Already have any PostgreSQL database? Skip Neon entirely:

```bash
autowebprompt db migrate --database-url <your-connection-string>
autowebprompt db status  --database-url <your-connection-string>
```

Preview the migration SQL without touching a database:

```bash
autowebprompt db migrate --dry-run
```

## Optional: Cloud Storage

Install with storage extras for S3 and database support:

```bash
pip install "autowebprompt[storage]"
```

Set environment variables:

```bash
export AWS_ACCESS_KEY_ID=...
export AWS_SECRET_ACCESS_KEY=...
export AWS_S3_BUCKET=my-bucket
export DATABASE_URL=postgresql://...
```

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  autowebprompt                                      │
│                                                     │
│  CLI / BatchRunner                                  │
│       │                                             │
│       ▼                                             │
│  EngineRunner (per-task lifecycle)                   │
│       │                                             │
│       ├── ClaudeWebAgent    (claude.ai)             │
│       └── ChatGPTWebAgent   (chatgpt.com)           │
│              │                                      │
│              ▼                                      │
│  BrowserManager ──► Chrome CDP (port 9222)          │
│                      Your logged-in browser         │
│                                                     │
│  Optional: S3 upload, PostgreSQL logging            │
└─────────────────────────────────────────────────────┘
```

- **`WebAgent` (ABC)** — abstract base with 9 lifecycle methods
- **`ClaudeWebAgent`** — drives claude.ai (extended thinking, web search)
- **`ChatGPTWebAgent`** — drives chatgpt.com (agent mode, web search, Code Interpreter)
- **`EngineRunner`** — two-tier retry loop (pipeline + agent phases)
- **`BatchRunner`** — sequential task execution from YAML configs
- **`BrowserManager`** — Chrome CDP connection management

### Retry Strategy

The engine uses a two-tier retry loop:

1. **Pipeline phase** — browser launch, navigation, authentication, file upload
2. **Agent phase** — prompt submission, generation wait, artifact download

Pipeline failures restart the entire browser session. Agent failures retry from the prompt step within the same session.

---

## License

MIT
