# GitHub Web Uploader

Upload local folders to GitHub through an already logged-in Chrome session on macOS.

This skill is useful when:

- `gh` is not installed
- `git push` is not configured yet
- you want to publish a Codex/OpenClaw skill quickly
- you want to upload a config list, manifest folder, or small source tree

## What It Supports

- Create a new GitHub repository through the web UI
- Upload a local text-based folder into that repository
- Update an existing repository
- Skip unchanged files when the remote content already matches local content
- Reuse the signed-in GitHub session from normal Chrome

## Best For

- Codex or OpenClaw skills
- config folders
- prompt packs
- scripts and source code
- small software projects with mostly text files

## Avoid Or Preprocess First

- large binary-heavy software bundles
- app packages with many compiled artifacts
- directories with huge dependency trees that should not be versioned

For those cases, zip or clean the folder first.

## Examples

Create a new private repository and upload a local skill:

```bash
python3 scripts/github_upload.py \
  --source /absolute/path/my-skill \
  --repo-owner liuyuqingsuser-prog \
  --repo-name my-skill \
  --create-repo \
  --visibility private
```

Preview the upload plan without creating commits:

```bash
python3 scripts/github_upload.py \
  --source /absolute/path/config-list \
  --repo-owner liuyuqingsuser-prog \
  --repo-name config-list \
  --dry-run
```

Update an existing repository and skip unchanged files:

```bash
python3 scripts/github_upload.py \
  --source /absolute/path/github-web-uploader \
  --repo-owner liuyuqingsuser-prog \
  --repo-name github-web-uploader-skill
```

## Default Excludes

These path components are skipped automatically:

- `.git`
- `node_modules`
- `__pycache__`
- `.DS_Store`
- `.pydeps`

You can add more with repeated `--exclude name`.

## Output

The script prints JSON with:

- repository URL
- uploaded file count
- skipped unchanged file count
- binary files skipped from the local scan

## Files

- `SKILL.md`: skill instructions
- `agents/openai.yaml`: UI metadata
- `scripts/github_upload.py`: Python wrapper
- `scripts/github_upload.js`: Playwright web uploader
