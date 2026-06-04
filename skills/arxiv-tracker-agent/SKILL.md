---
name: arxiv-tracker-agent
description: Set up, configure, run, and schedule the colorfulandcjy0806/Arxiv-tracker arXiv paper digest with Codex. Use when the user asks to track arXiv papers, customize categories or keywords, generate daily paper digests, publish GitHub Pages outputs, send email summaries, configure GitHub Actions schedules, or create a Codex scheduled agent/定时 agent for recurring arXiv monitoring.
---

# Arxiv Tracker Agent

## Overview

Use this skill to operate the Arxiv-tracker repository as a paper-monitoring agent. Prefer the main CLI runner because it includes pagination, freshness, deduplication, LLM summaries, translation, site generation, and email support.

## Decision Flow

1. If the user wants a one-time digest, run the tracker locally and report output files.
2. If the user wants different topics, edit `config.yaml` categories, keywords, exclude keywords, freshness, LLM, site, and email settings.
3. If the user wants always-on scheduled delivery in GitHub, configure `.github/workflows/digest.yml`, repository secrets/variables, and GitHub Pages.
4. If the user asks for a Codex scheduled agent, create or update a Codex automation when an automation tool is available; otherwise prepare the prompt and schedule instructions for the user.

## Locate The Repository

Use an existing Arxiv-tracker checkout when present. Otherwise clone the user's fork if provided, falling back to:

```bash
git clone https://github.com/colorfulandcjy0806/Arxiv-tracker.git
cd Arxiv-tracker
```

Inspect `README.md`, `config.yaml`, `.github/workflows/digest.yml`, and `arxiv_tracker/cli.py` before making nontrivial changes.

## Configure Topics

Edit `config.yaml` conservatively:

- `categories`: arXiv categories such as `cs.CV`, `cs.LG`, `cs.AI`, `cs.CL`.
- `keywords`: topic phrases to include. Keep them specific enough to avoid noisy digests.
- `exclude_keywords`: terms to filter out when the user wants to avoid a broad area.
- `logic`: usually `AND` for "category set plus keyword set"; use `OR` only for broader monitoring.
- `freshness.since_days`: use `1` to `3` for daily monitoring; larger windows are useful for a first catch-up run.
- `freshness.unique_only`: keep `true` for recurring digests.
- `summary.mode`: use `llm` for production summaries, `heuristic` or `none` for local smoke tests without an API key.

Never commit API keys, SMTP passwords, or personal recipient addresses unless the user explicitly wants a private local-only config file.

## Run Once

Set up Python dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

For normal runs, set the configured LLM key environment variable, usually `OPENAI_COMPAT_API_KEY`. For email delivery, also set `EMAIL_TO`, `EMAIL_SENDER`, `SMTP_USER`, and `SMTP_PASS`.

Use `--no-email` for tests unless the user explicitly asks to send mail:

```bash
python -m arxiv_tracker.cli run \
  --config config.yaml \
  --site-dir docs \
  --no-email \
  --verbose
```

Report the generated `outputs/arxiv_*.json`, `outputs/arxiv_*.md`, and `docs/index.html` paths. Do not commit generated `docs/`, `outputs/`, or `.state/` changes from a smoke test unless the user asked to update published results.

## Schedule With GitHub Actions

Use the existing `.github/workflows/digest.yml` as the production scheduler. Confirm:

- `on.schedule` has the desired cron time. GitHub cron is UTC.
- Repository secrets/variables include `OPENAI_COMPAT_API_KEY` or provider-specific keys, `SMTP_PASS`, `EMAIL_TO`, `EMAIL_SENDER`, and `SMTP_USER` as needed.
- Pages is configured to deploy from `main` and `/docs`.
- The auto-commit step includes `docs/**`, `outputs/**`, and `.state/**`.

For manual workflow tests, default to `send_email=false` unless the user wants a live email.

## Schedule With Codex

When the user asks for a Codex scheduled agent, first discover the automation tool if available, for example by searching for `automation_update`. Create a recurring task whose prompt invokes this skill and points at the repository path or fork.

Use a prompt like:

```text
Use $arxiv-tracker-agent in <repo-path> to run my arXiv digest for <topics>. Run the tracker, avoid sending email unless credentials are configured, summarize the new papers, and report the generated docs/index.html and outputs files.
```

Keep secrets out of the automation prompt. Store them in the environment, repository secrets, or the user's preferred secret manager.

## Validation Checklist

Before finishing:

- Run `python -m arxiv_tracker.cli --help` or inspect `arxiv_tracker/cli.py` if command options may have changed.
- Run a no-email smoke test when credentials and network access permit.
- Validate edited YAML syntax for `config.yaml` and workflow files.
- Confirm `git diff` contains only intended config, skill, README, or workflow changes.
- Explain whether email was sent, whether a schedule was created, and where outputs live.

Avoid using `arxiv_tracker/scheduler.py` for production setup unless the user specifically asks for a long-running local process; it does not cover the full digest pipeline.
