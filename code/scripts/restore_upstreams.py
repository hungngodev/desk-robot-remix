"""Restore exact public source revisions without overwriting local upstream changes."""

import json
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_GIT_TIMEOUT_S = 30
TRANSFER_GIT_TIMEOUT_S = 300


def git_env():
    # Never let an inherited GIT_DIR, GIT_WORK_TREE or config injection redirect Git.
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def git(args, cwd, *, timeout=None, **kwargs):
    try:
        return subprocess.run(
            ["git", *args], cwd=cwd, env=git_env(),
            timeout=LOCAL_GIT_TIMEOUT_S if timeout is None else timeout, **kwargs,
        )
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError(f"Git {args[0]} timed out in {cwd}") from exc


def run(args, cwd):
    return git(args, cwd, check=True, stdout=subprocess.PIPE, text=True).stdout.strip()


def transfer(args, cwd, source):
    try:
        git(args, cwd, check=True, timeout=TRANSFER_GIT_TIMEOUT_S)
    except (subprocess.CalledProcessError, TimeoutError) as exc:
        raise RuntimeError(
            f"Cannot {args[0]} {source['path']} at {source['commit']}: "
            f"{'Git timed out; ' if isinstance(exc, TimeoutError) else ''}"
            "check network access to the pinned origin or restore a local checkout "
            "containing the exact commit."
        ) from exc


def restore_path(source):
    relative = Path(source["path"])
    if (len(relative.parts) != 2 or relative.parts[0] != "upstream"
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", relative.parts[1])):
        raise RuntimeError("Invalid upstream checkout path")
    if not re.fullmatch(r"[0-9a-f]{40}", source["commit"]):
        raise RuntimeError("Invalid upstream commit pin")
    if not re.fullmatch(r"https://github\.com/[\w.-]+/[\w.-]+\.git", source["url"]):
        raise RuntimeError("Invalid upstream repository URL")
    path = ROOT / relative
    for candidate in (path.parent, path):
        if candidate.is_symlink() or (candidate.exists() and not candidate.is_dir()):
            raise RuntimeError(f"Refuse redirected upstream directory: {candidate}")
    return path


def require_checkout(path):
    metadata = path / ".git"
    if metadata.is_symlink() or not metadata.is_dir():
        raise RuntimeError(f"Expected a standalone upstream checkout in {path}")
    if Path(run(["rev-parse", "--show-toplevel"], path)).resolve() != path.resolve():
        raise RuntimeError(f"Git worktree mismatch in {path}")
    common = run(["rev-parse", "--git-common-dir"], path)
    if (path / common).resolve() != metadata.resolve():
        raise RuntimeError(f"Git metadata mismatch in {path}")
    # A replacement ref can make HEAD name the pin while checking out other content.
    if run(["for-each-ref", "--format=%(refname)", "refs/replace/"], path):
        raise RuntimeError(f"Refuse replacement refs in {path}")


def require_visible_index(path):
    # Git status can ignore edits to assume-unchanged or skip-worktree entries.
    # Reject the flags rather than clearing them or overwriting local work.
    entries = git(["ls-files", "-v", "-z"], path, check=True, stdout=subprocess.PIPE).stdout
    if any(entry[:1].islower() or entry.startswith(b"S ") for entry in entries.split(b"\0")):
        raise RuntimeError(f"Preserve local changes and clear hidden index flags in {path}")


def main():
    sources = json.loads((ROOT / "upstream-lock.json").read_text())["repositories"]
    paths = [restore_path(source) for source in sources]
    if len(set(paths)) != len(paths):
        raise RuntimeError("Duplicate upstream checkout path")
    for source in sources:
        path = restore_path(source)
        if not path.exists():
            path.parent.mkdir(exist_ok=True)
            transfer(["clone", "--no-checkout", "--", source["url"], str(path)], ROOT, source)
            path = restore_path(source)
            require_checkout(path)
        else:
            require_checkout(path)
            require_visible_index(path)
            if run(["status", "--porcelain", "--untracked-files=all"], path):
                raise RuntimeError(f"Preserve local changes in {path} before restoring sources")
        if run(["remote", "get-url", "origin"], path) != source["url"]:
            raise RuntimeError(f"Origin mismatch in {path}")
        if git(
            ["cat-file", "-e", source["commit"] + "^{commit}"],
            path,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode:
            transfer(["fetch", "origin", source["commit"]], path, source)
        git(["checkout", "--detach", "--no-overwrite-ignore", source["commit"]], path, check=True)
        if run(["rev-parse", "HEAD"], path) != source["commit"]:
            raise RuntimeError(f"Upstream commit mismatch in {path}")
        require_visible_index(path)
        print(f"Verified {source['name']} at {source['commit'][:12]}")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, TimeoutError) as exc:
        raise SystemExit(str(exc)) from None
