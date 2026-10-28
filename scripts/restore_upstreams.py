"""Restore exact public source revisions without overwriting local upstream changes."""

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(args, cwd):
    return subprocess.check_output(args, cwd=cwd, text=True).strip()


def main():
    for source in json.loads((ROOT / "upstream-lock.json").read_text())["repositories"]:
        path = ROOT / source["path"]
        if not path.exists():
            path.parent.mkdir(exist_ok=True)
            subprocess.run(["git", "clone", "--no-checkout", source["url"], str(path)], check=True)
        elif run(["git", "status", "--porcelain"], path):
            raise RuntimeError(f"Preserve local changes in {path} before restoring sources")
        if run(["git", "remote", "get-url", "origin"], path) != source["url"]:
            raise RuntimeError(f"Origin mismatch in {path}")
        if subprocess.run(
            ["git", "cat-file", "-e", source["commit"]],
            cwd=path,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode:
            subprocess.run(["git", "fetch", "origin", source["commit"]], cwd=path, check=True)
        subprocess.run(["git", "checkout", "--detach", source["commit"]], cwd=path, check=True)
        assert run(["git", "rev-parse", "HEAD"], path) == source["commit"]
        print(f"Verified {source['name']} at {source['commit'][:12]}")


if __name__ == "__main__":
    main()
