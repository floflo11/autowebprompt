# X Post Drafts — autowebprompt Launch

## Option A: Research Angle

We built autowebprompt — an open-source tool to automate ChatGPT and Claude web UIs with Playwright.

Why? ChatGPT Agent Mode and Claude Extended Thinking are web-only. No API access. We needed to benchmark hundreds of financial modeling tasks across both providers.

autowebprompt drives your logged-in browser via Chrome DevTools Protocol:
- Send prompts, upload files, download artifacts
- Batch execution with two-tier retry
- Works with ChatGPT Agent Mode + Claude Extended Thinking

We used it to run 50+ Wall Street Prep tasks through both GPT-5.2 and Opus 4.5 — fully automated.

MIT licensed: github.com/[org]/autowebprompt

## Option B: Developer Angle

Tired of copy-pasting prompts into ChatGPT one by one?

autowebprompt automates ChatGPT and Claude web UIs through your real browser. No API keys needed — just your existing login.

```
pip install autowebprompt
autowebprompt setup
autowebprompt run --provider chatgpt --tasks tasks.yaml
```

Features:
- ChatGPT Agent Mode (Code Interpreter)
- Claude Extended Thinking
- File upload + artifact download
- Batch execution with retry
- Optional S3/DB storage

Open source, MIT licensed.

github.com/[org]/autowebprompt

## Option C: Short + Punchy

We open-sourced autowebprompt — automate ChatGPT and Claude web UIs with Playwright.

Send prompts, upload files, download results. Batch hundreds of tasks. Two-tier retry. Works with Agent Mode and Extended Thinking.

`pip install autowebprompt`

github.com/[org]/autowebprompt
