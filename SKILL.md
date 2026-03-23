---
name: github-web-uploader
description: Upload local folders, skills, config lists, or source-code projects to GitHub through the user's logged-in Chrome session on macOS. Use when Codex should create a GitHub repository, sync a local text-based project tree into it, or publish OpenClaw/Codex skills without relying on gh or preconfigured git credentials.
---

# GitHub Web Uploader

## Overview

Use this skill when local `gh` or `git push` setup is missing, but the user is already logged into GitHub in Google Chrome.
The workflow exports GitHub cookies from Chrome, launches a separate automated Chrome window, optionally creates a repository, then writes the local project tree into GitHub through the web UI.
When the target repository already has the same file content, the uploader skips that file instead of creating a redundant commit.

## Best Fit

This skill is optimized for text-based project trees:

- OpenClaw or Codex skills
- config folders and manifest lists
- scripts, source code, and small app repositories

For binary-heavy software bundles, prefer zipping first or using normal git later.

## Quick Start

```bash
python3 scripts/github_upload.py \
  --source /absolute/path/project \
  --repo-name my-project \
  --create-repo \
  --visibility private

python3 scripts/github_upload.py \
  --source /absolute/path/skill \
  --repo-owner my-user \
  --repo-name my-skill \
  --create-repo \
  --visibility private \
  --description "Reusable Codex skill"

python3 scripts/github_upload.py \
  --source /absolute/path/config-list \
  --repo-name config-list \
  --dry-run
```

## Workflow

1. Confirm the user is already logged into `https://github.com` in Google Chrome.
2. Point `--source` at the local folder to publish.
3. Use `--create-repo` when the target repo does not exist yet.
4. Default to `private` unless the user explicitly wants a public repo.
5. Run `--dry-run` first when you want to verify login and the upload plan without creating commits.
6. Read the returned JSON and share the final repository URL.

## Behavior

- Exports live GitHub cookies from Chrome.
- Recursively scans the source folder.
- Skips common junk by default:
  - `.git/`
  - `node_modules/`
  - `__pycache__/`
  - `.DS_Store`
  - `.pydeps/`
- Treats the source as a text-first tree.
- Creates missing files in GitHub or edits existing ones in place.
- Skips unchanged files when the remote and local contents already match.
- Creates one commit per changed file for reliability in the web UI.

## Guardrails

- macOS only.
- Requires Google Chrome with an active GitHub login.
- Optimized for UTF-8 text files.
- If binary files are detected, either use `--skip-binary` or remove them before upload.
- If the repo owner is omitted, the script tries to infer the default signed-in owner from GitHub's new-repo page.

## Resources

### `scripts/github_upload.py`

Python wrapper for dependency bootstrapping, cookie export, source-tree scanning, manifest generation, and invoking the browser uploader.

### `scripts/github_upload.js`

Playwright-based GitHub uploader that creates repositories and writes files through the GitHub web interface.
