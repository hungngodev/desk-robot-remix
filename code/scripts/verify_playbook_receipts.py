"""Verify promoted playbook receipts against live GitHub facts.

The pure unit-test ledger validator checks structure. This separate online
verification checks that an Actions run really passed for the claimed SHA and
that a physical data record really exists at that exact source revision.
Even successful online checks are not proof that measurements are truthful:
physical reviewer signoff remains mandatory.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

REPO = "hungngodev/desk-robot-remix"
ROOT = Path(__file__).resolve().parents[2]
LEDGER = ROOT / "docs/reviews/100_page_procedure_trace.json"
RUN_PATH = re.compile(r"^/hungngodev/desk-robot-remix/actions/runs/([0-9]+)$")
SHA = re.compile(r"^[0-9a-f]{40}$")


def github_json(url: str, token: str | None = None) -> dict:
    """Read metadata; do not mutate the repository or download arbitrary URLs."""
    token = token or os.environ.get("GITHUB_TOKEN")
    if not url.startswith("https://api.github.com/repos/" + REPO + "/"):
        raise ValueError("Unexpected GitHub API target")
    headers = {"Accept": "application/vnd.github+json",
               "User-Agent": "desk-robot-playbook-verification"}
    if token:
        headers["Authorization"] = "Bearer " + token
    with urlopen(Request(url, headers=headers), timeout=20) as response:
        data = json.load(response)
    if not isinstance(data, dict):
        raise ValueError("Expected a JSON object from GitHub")
    return data


def verified_actions_run(url: str, sha: str, lookup=github_json) -> bool:
    if not isinstance(url, str):
        return False
    parsed = urlsplit(url)
    match = RUN_PATH.fullmatch(parsed.path)
    if (parsed.scheme != "https" or parsed.netloc != "github.com"
            or parsed.query or parsed.fragment or match is None):
        return False
    run = lookup(f"https://api.github.com/repos/{REPO}/actions/runs/{match[1]}")
    return (run.get("head_sha") == sha
            and run.get("name") == "Host verification"
            and run.get("status") == "completed"
            and run.get("conclusion") == "success")


def verified_raw_record(url: str, sha: str, lookup=github_json) -> bool:
    if not isinstance(url, str):
        return False
    parsed = urlsplit(url)
    base = f"/{REPO}/blob/{sha}/docs/records/"
    if (parsed.scheme != "https" or parsed.netloc != "github.com"
            or parsed.query or parsed.fragment
            or not parsed.path.startswith(base)):
        return False
    filename = parsed.path[len(base):]
    if (not filename or any(segment in {"", ".", ".."}
                            for segment in filename.split("/"))):
        return False
    encoded_path = quote("docs/records/" + filename, safe="/")
    data = lookup(
        f"https://api.github.com/repos/{REPO}/contents/"
        f"{encoded_path}?ref={sha}"
    )
    return data.get("type") == "file" and type(data.get("size")) is int \
        and data["size"] > 0


def audit(ledger: dict, lookup=github_json) -> list[str]:
    """Return failures, never turn network errors into a success receipt."""
    errors: list[str] = []
    for row in ledger.get("procedures", []):
        if row.get("gate") == "OPEN":
            continue
        identifier = row.get("id", "unknown")
        evidence_class = row.get("evidence_class")
        if evidence_class not in {"source", "mixed", "physical"}:
            errors.append(f"procedure {identifier}: missing evidence class")
            continue
        if evidence_class == "physical" and row.get("gate") == "TESTED":
            errors.append(f"procedure {identifier}: physical task cannot be source-only TESTED")
            continue
        sha = row.get("last_verified_sha")
        receipt = row.get("executed_test_receipt")
        if (not isinstance(sha, str) or not SHA.fullmatch(sha)
                or not isinstance(receipt, dict)
                or receipt.get("sha") != sha
                or receipt.get("exit_code") != 0):
            errors.append(f"procedure {identifier}: invalid source receipt")
            continue
        try:
            if not verified_actions_run(receipt.get("url", ""), sha, lookup):
                errors.append(f"procedure {identifier}: CI run not verified")
        except (HTTPError, URLError, ValueError, TimeoutError, OSError) as exc:
            errors.append(f"procedure {identifier}: CI lookup failed: {type(exc).__name__}")
        if row.get("gate") in {"MEASURED", "QUALIFIED"}:
            measurement = row.get("physical_measurement_receipt")
            if not isinstance(measurement, dict):
                errors.append(f"procedure {identifier}: no physical receipt")
                continue
            try:
                if not verified_raw_record(
                    measurement.get("raw_data_url", ""), sha, lookup
                ):
                    errors.append(f"procedure {identifier}: raw physical record not found")
            except (HTTPError, URLError, ValueError, TimeoutError, OSError) as exc:
                errors.append(
                    f"procedure {identifier}: physical lookup failed: {type(exc).__name__}"
                )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, default=LEDGER)
    args = parser.parse_args()
    try:
        ledger = json.loads(args.ledger.read_text(encoding="utf-8"))
        errors = audit(ledger)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(f"INCOMPLETE: invalid playbook ledger: {exc}", file=sys.stderr)
        return 1
    for error in errors:
        print("REJECTED: " + error, file=sys.stderr)
    if errors:
        return 1
    promoted = sum(row.get("gate") != "OPEN"
                   for row in ledger.get("procedures", []))
    if promoted == 0:
        print("No procedures promoted. No live evidence receipts checked; "
              "all acceptance gates remain unclaimed.")
    else:
        print(f"Verified GitHub metadata for {promoted} promoted procedure(s). "
              "Physical authenticity and acceptance still require bench review.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
