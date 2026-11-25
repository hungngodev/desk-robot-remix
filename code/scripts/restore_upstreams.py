"""Restore exact public source revisions without overwriting local upstream changes."""

import json
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def git_env():
    # Never let an inherited GIT_DIR, GIT_WORK_TREE or config injection redirect Git.
    return {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}


def run(args, cwd):
    return subprocess.check_output(args, cwd=cwd, text=True, env=git_env()).strip()


def git(args, cwd, **kwargs):
    return subprocess.run(["git", *args], cwd=cwd, env=git_env(), **kwargs)


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
    if Path(run(["git", "rev-parse", "--show-toplevel"], path)).resolve() != path.resolve():
        raise RuntimeError(f"Git worktree mismatch in {path}")
    common = run(["git", "rev-parse", "--git-common-dir"], path)
    if (path / common).resolve() != metadata.resolve():
        raise RuntimeError(f"Git metadata mismatch in {path}")


def main():
    sources = json.loads((ROOT / "upstream-lock.json").read_text())["repositories"]
    paths = [restore_path(source) for source in sources]
    if len(set(paths)) != len(paths):
        raise RuntimeError("Duplicate upstream checkout path")
    for source in sources:
        path = restore_path(source)
        if not path.exists():
            path.parent.mkdir(exist_ok=True)
            git(["clone", "--no-checkout", "--", source["url"], str(path)], ROOT, check=True)
            path = restore_path(source)
            require_checkout(path)
        else:
            require_checkout(path)
            if run(["git", "status", "--porcelain", "--untracked-files=all"], path):
                raise RuntimeError(f"Preserve local changes in {path} before restoring sources")
        if run(["git", "remote", "get-url", "origin"], path) != source["url"]:
            raise RuntimeError(f"Origin mismatch in {path}")
        if git(
            ["cat-file", "-e", source["commit"] + "^{commit}"],
            path,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode:
            git(["fetch", "origin", source["commit"]], path, check=True)
        git(["checkout", "--detach", "--no-overwrite-ignore", source["commit"]], path, check=True)
        if run(["git", "rev-parse", "HEAD"], path) != source["commit"]:
            raise RuntimeError(f"Upstream commit mismatch in {path}")
        print(f"Verified {source['name']} at {source['commit'][:12]}")


if __name__ == "__main__":
    main()
