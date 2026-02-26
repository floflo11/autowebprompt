# autowebprompt

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Playwright](https://img.shields.io/badge/Playwright-1.40+-green.svg)](https://playwright.dev/python/)

**Automate ChatGPT and Claude web UIs with Playwright.** Send prompts, upload files, download artifacts, and run batch tasks — all through the browser you're already logged into.

## Why?

AI providers offer powerful web-only features (ChatGPT Agent Mode, Claude Extended Thinking) that aren't available via API. This tool lets you automate those features programmatically by driving a real browser session.

## How It Works

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

## Quick Start

### 1. Install

```bash
pip install autowebprompt
```

Or from source:

```bash
git clone https://github.com/your-org/autowebprompt.git
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
```

Log into ChatGPT or Claude in that browser window.

### 3. Run the Setup Wizard

```bash
autowebprompt setup
```

This copies a template config and example task file to your project.

### 4. Configure

Edit the template to set your project ID:

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
# Single provider
autowebprompt run --provider chatgpt \
  --tasks tasks.yaml --template template_chatgpt.yaml

# With database task fetching
autowebprompt run --provider claude \
  --tasks tasks.yaml --template template_claude.yaml \
  --fetch-from-db
```

## Features

| Feature | Claude | ChatGPT |
|---------|--------|---------|
| Send prompts | Yes | Yes |
| Upload files | Yes | Yes |
| Download artifacts | Yes | Yes (CDP) |
| Extended thinking | Yes | Yes |
| Agent mode | - | Yes |
| Web search | Yes | - |
| Batch execution | Yes | Yes |
| Retry on failure | Yes | Yes |
| S3 upload (optional) | Yes | Yes |
| DB logging (optional) | Yes | Yes |

## CLI Commands

```
autowebprompt setup       # Interactive setup wizard
autowebprompt run         # Run batch tasks
autowebprompt check       # Verify Chrome CDP is running
autowebprompt templates   # Show template examples
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

## Architecture

The package uses a strategy pattern with a shared engine:

- **`WebAgent` (ABC)** — abstract base with 9 lifecycle methods
- **`ClaudeWebAgent`** — drives claude.ai (extended thinking, web search)
- **`ChatGPTWebAgent`** — drives chatgpt.com (agent mode, Code Interpreter)
- **`EngineRunner`** — two-tier retry loop (pipeline + agent phases)
- **`BatchRunner`** — sequential task execution from YAML configs
- **`BrowserManager`** — Chrome CDP connection management

### Retry Strategy

The engine uses a two-tier retry loop:

1. **Pipeline phase** — browser launch, navigation, authentication, file upload
2. **Agent phase** — prompt submission, generation wait, artifact download

Pipeline failures restart the entire browser session. Agent failures retry from the prompt step within the same session.

## Prerequisites

- Python 3.10+
- Google Chrome or Chrome Canary
- A ChatGPT Plus/Pro or Claude Pro account
- Playwright (`pip install playwright && playwright install chromium`)

## License

MIT
