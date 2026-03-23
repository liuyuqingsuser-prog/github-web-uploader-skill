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


def normalize_extensions(values: list[str]) -> set[str]:
    normalized = set()
    for value in values:
        item = value.strip().lower()
        if not item:
            continue
        if not item.startswith("."):
            item = f".{item}"
        normalized.add(item)
    return normalized


def normalize_include_dirs(values: list[str]) -> list[str]:
    normalized = []
    for value in values:
        item = value.strip().strip("/")
        if item:
            normalized.append(item)
    return normalized


def matches_include_filters(repo_path: str, path: Path, include_exts: set[str], include_dirs: list[str]) -> bool:
    if include_exts and path.suffix.lower() not in include_exts:
        return False
    if include_dirs:
        return any(
            repo_path == include_dir or repo_path.startswith(f"{include_dir}/")
            for include_dir in include_dirs
        )
    return True


def collect_files(
    source_root: Path,
    skip_binary: bool,
    extra_excludes: set[str],
    include_exts: set[str],
    include_dirs: list[str],
) -> dict[str, Any]:
    entries = []
    skipped_binary = []
    skipped_filtered = []

    for path in sorted(source_root.rglob("*")):
        if not path.is_file():
            continue
        if should_exclude(path, source_root, extra_excludes):
            continue
        repo_path = path.relative_to(source_root).as_posix()
        if not matches_include_filters(repo_path, path, include_exts, include_dirs):
            skipped_filtered.append(repo_path)
            continue
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

    return {
        "files": entries,
        "skipped_binary": skipped_binary,
        "skipped_filtered": skipped_filtered,
        "include_exts": sorted(include_exts),
        "include_dirs": include_dirs,
    }


def build_summary(
    source_root: Path,
    repo_owner: str,
    repo_name: str,
    manifest: dict[str, Any],
    create_repo: bool,
    visibility: str,
) -> dict[str, Any]:
    files = manifest["files"]
    return {
        "ok": 1,
        "summary_only": True,
        "source": str(source_root),
        "repo_owner": repo_owner,
        "repo_name": repo_name,
        "repo_url": f"https://github.com/{repo_owner}/{repo_name}" if repo_owner else "",
        "create_repo": create_repo,
        "visibility": visibility,
        "file_count": len(files),
        "files": [entry["repo_path"] for entry in files],
        "include_exts": manifest.get("include_exts", []),
        "include_dirs": manifest.get("include_dirs", []),
        "skipped_binary": manifest.get("skipped_binary", []),
        "skipped_filtered": manifest.get("skipped_filtered", []),
    }


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
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Print a local upload summary and stop before opening Chrome.",
    )
    parser.add_argument("--skip-binary", action="store_true", help="Skip binary or non-UTF-8 files instead of failing.")
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        help="Additional path component to exclude. Repeatable.",
    )
    parser.add_argument(
        "--include-ext",
        action="append",
        default=[],
        help="Only include files with this extension. Repeatable. Example: --include-ext .py",
    )
    parser.add_argument(
        "--include-dir",
        action="append",
        default=[],
        help="Only include files under this repo-relative subdirectory. Repeatable. Example: --include-dir scripts",
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

    include_exts = normalize_extensions(args.include_ext)
    include_dirs = normalize_include_dirs(args.include_dir)
    manifest = collect_files(
        source_root=source_root,
        skip_binary=args.skip_binary,
        extra_excludes={item.strip() for item in args.exclude if item.strip()},
        include_exts=include_exts,
        include_dirs=include_dirs,
    )
    if not manifest["files"]:
        fail("No eligible text files were found to upload.")

    if args.summary_only:
        print(
            json.dumps(
                build_summary(
                    source_root=source_root,
                    repo_owner=args.repo_owner,
                    repo_name=args.repo_name,
                    manifest=manifest,
                    create_repo=args.create_repo,
                    visibility=args.visibility,
                ),
                ensure_ascii=False,
                indent=2,
            )
        )
        return

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
