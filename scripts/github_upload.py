#!/usr/bin/env python3

from __future__ import annotations

import argparse
import importlib
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
PY_DEPS_DIR = SCRIPT_DIR / ".pydeps"
COOKIE_EXPORT_PATH = Path("/tmp/github-web-uploader-cookies.json")
MANIFEST_PATH = Path("/tmp/github-web-uploader-manifest.json")
DEFAULT_EXCLUDES = {
    ".git",
    "node_modules",
    "__pycache__",
    ".DS_Store",
    ".pydeps",
}


def fail(message: str, code: int = 1) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(code)


def run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, check=True, text=True, **kwargs)


def ensure_python_dependencies() -> None:
    PY_DEPS_DIR.mkdir(parents=True, exist_ok=True)
    if str(PY_DEPS_DIR) not in sys.path:
        sys.path.insert(0, str(PY_DEPS_DIR))

    missing = []
    try:
        importlib.import_module("browser_cookie3")
    except ModuleNotFoundError:
        missing.append("browser-cookie3")

    if missing:
        run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--quiet",
                "--target",
                str(PY_DEPS_DIR),
                *missing,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    importlib.invalidate_caches()
    if str(PY_DEPS_DIR) not in sys.path:
        sys.path.insert(0, str(PY_DEPS_DIR))


def ensure_node_dependencies() -> None:
    playwright_dir = SCRIPT_DIR / "node_modules" / "playwright"
    if playwright_dir.exists():
        return
    run(
        ["npm", "install", "--silent", "--prefix", str(SCRIPT_DIR)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def export_github_cookies(output_path: Path) -> Path:
    import browser_cookie3

    cookies = []
    now = time.time()
    for cookie in browser_cookie3.chrome(domain_name="github.com"):
        if "github.com" not in cookie.domain:
            continue
        item = {
            "name": cookie.name,
            "value": cookie.value,
            "domain": cookie.domain,
            "path": cookie.path,
            "secure": bool(cookie.secure),
            "httpOnly": False,
            "sameSite": "Lax",
        }
        if cookie.expires and cookie.expires > now:
            item["expires"] = cookie.expires
        cookies.append(item)

    if not cookies:
        fail("No GitHub cookies were found in Chrome. Please log in to github.com in Google Chrome first.")

    output_path.write_text(json.dumps(cookies, ensure_ascii=False, indent=2))
    return output_path


def is_text_file(path: Path) -> bool:
    try:
        path.read_text(encoding="utf-8")
        return True
    except UnicodeDecodeError:
        return False


def should_exclude(path: Path, source_root: Path, extra_excludes: set[str]) -> bool:
    rel_parts = path.relative_to(source_root).parts
    all_excludes = DEFAULT_EXCLUDES | extra_excludes
    return any(part in all_excludes for part in rel_parts)


def collect_files(source_root: Path, skip_binary: bool, extra_excludes: set[str]) -> dict[str, Any]:
    entries = []
    skipped_binary = []

    for path in sorted(source_root.rglob("*")):
        if not path.is_file():
            continue
        if should_exclude(path, source_root, extra_excludes):
            continue
        repo_path = path.relative_to(source_root).as_posix()
        if is_text_file(path):
            entries.append(
                {
                    "repo_path": repo_path,
                    "local_path": str(path.resolve()),
                    "content": path.read_text(encoding="utf-8"),
                }
            )
        else:
            skipped_binary.append(repo_path)

    if skipped_binary and not skip_binary:
        fail(
            "Binary or non-UTF-8 files detected. Re-run with --skip-binary or remove them first:\n"
            + "\n".join(skipped_binary[:30])
        )

    return {"files": entries, "skipped_binary": skipped_binary}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Upload a local text-based folder to GitHub through the logged-in Chrome web session.",
    )
    parser.add_argument("--source", type=Path, required=True, help="Local folder to upload.")
    parser.add_argument("--repo-name", required=True, help="Target GitHub repository name.")
    parser.add_argument("--repo-owner", default="", help="Target GitHub owner. Defaults to the signed-in default owner.")
    parser.add_argument("--description", default="", help="Repository description when creating a repo.")
    parser.add_argument(
        "--visibility",
        choices=["private", "public"],
        default="private",
        help="Visibility when creating a repo.",
    )
    parser.add_argument("--create-repo", action="store_true", help="Create the repository if it does not exist.")
    parser.add_argument("--dry-run", action="store_true", help="Validate login and upload plan without creating commits.")
    parser.add_argument("--skip-binary", action="store_true", help="Skip binary or non-UTF-8 files instead of failing.")
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        help="Additional path component to exclude. Repeatable.",
    )
    parser.add_argument(
        "--chrome-path",
        default="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        help="Chrome executable path for Playwright.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    source_root = args.source.expanduser().resolve()
    if not source_root.exists():
        fail(f"Source path not found: {source_root}")
    if not source_root.is_dir():
        fail(f"Source path is not a directory: {source_root}")

    ensure_python_dependencies()
    ensure_node_dependencies()

    manifest = collect_files(
        source_root=source_root,
        skip_binary=args.skip_binary,
        extra_excludes={item.strip() for item in args.exclude if item.strip()},
    )
    if not manifest["files"]:
        fail("No eligible text files were found to upload.")

    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    cookie_path = export_github_cookies(COOKIE_EXPORT_PATH)

    cmd = [
        "node",
        str(SCRIPT_DIR / "github_upload.js"),
        "--cookies",
        str(cookie_path),
        "--manifest",
        str(MANIFEST_PATH),
        "--repo-name",
        args.repo_name,
        "--visibility",
        args.visibility,
        "--description",
        args.description,
        "--chrome-path",
        args.chrome_path,
    ]
    if args.repo_owner:
        cmd.extend(["--repo-owner", args.repo_owner])
    if args.create_repo:
        cmd.append("--create-repo")
    if args.dry_run:
        cmd.append("--dry-run")

    try:
        result = run(cmd, capture_output=True)
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip() if exc.stderr else ""
        stdout = exc.stdout.strip() if exc.stdout else ""
        detail = stderr or stdout or str(exc)
        fail(f"GitHub upload failed:\n{detail}")
    payload = json.loads(result.stdout)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
