"""Verify promoted playbook receipts against live GitHub facts.

The pure unit-test ledger validator checks structure. This separate online
verification checks that an Actions run really passed for the claimed SHA and
that a physical data record really exists at that exact source revision.
Even successful online checks are not proof that measurements are truthful:
physical reviewer signoff remains mandatory.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import csv
import hashlib
import io
import json
import math
import os
import re
import sys
from datetime import date
from decimal import Decimal
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
    head_repo = run.get("head_repository")
    return (run.get("head_sha") == sha
            and run.get("name") == "Host verification"
            and run.get("event") == "pull_request"
            and run.get("head_branch") == "impl/mac-hardware-safety-preflight-2026-11-10"
            and isinstance(head_repo, dict)
            and head_repo.get("full_name") == REPO
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
    return isinstance(data, dict) and data.get("type") == "file" \
        and type(data.get("size")) is int and data["size"] > 0



EVIDENCE_DIGEST = re.compile(r"^[0-9a-f]{64}$")


def source_unchanged_since_test(
    source_sha: object, evidence_sha: object, lookup=github_json,
) -> bool:
    """Allow a later immutable evidence commit without relabeling test inputs.

    This keeps tested source/build identity separate from the record's commit.
    All intervening changes must be physical evidence under docs/records or
    the procedure ledger. New code, tests, firmware, wiring or config need
    another actual successful test run, not a fresh signoff on older source.
    """
    if (type(source_sha) is not str or type(evidence_sha) is not str
            or not SHA.fullmatch(source_sha) or not SHA.fullmatch(evidence_sha)):
        return False
    if source_sha == evidence_sha:
        return True
    try:
        result = lookup(
            f"https://api.github.com/repos/{REPO}/compare/"
            f"{source_sha}...{evidence_sha}"
        )
        files = result.get("files")
        commits = result.get("commits")
        merge_base = result.get("merge_base_commit")
        return bool(
            result.get("status") == "ahead"
            and type(result.get("ahead_by")) is int
            and result["ahead_by"] >= 1
            and type(result.get("total_commits")) is int
            and result["total_commits"] == result["ahead_by"]
            and type(commits) is list
            and len(commits) == result["total_commits"] <= 250
            and isinstance(commits[-1], dict)
            and commits[-1].get("sha") == evidence_sha
            and isinstance(merge_base, dict)
            and merge_base.get("sha") == source_sha
            and type(files) is list
            # GitHub Compare truncates the file list at 300 entries. A
            # 300th visible evidence file may hide an untested source change.
            and 1 <= len(files) < 300
            and all(
                type(item) is dict
                and item.get("status") in {"added", "modified"}
                and type(item.get("filename")) is str
                and (
                    item["filename"].startswith("docs/records/")
                    or item["filename"]
                    == "docs/reviews/100_page_procedure_trace.json"
                )
                for item in files
            )
        )
    except (AttributeError, TypeError, ValueError, IndexError, KeyError,
            HTTPError, URLError, OSError, TimeoutError):
        return False


def evidence_digest_matches(raw: bytes, digest: object) -> bool:
    return (type(digest) is str and EVIDENCE_DIGEST.fullmatch(digest) is not None
            and hashlib.sha256(raw).hexdigest() == digest)


def strict_receipt_object(pairs: list[tuple[str, object]]) -> dict:
    """Reject ambiguous duplicate keys at any JSON receipt nesting depth."""
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("Duplicate physical receipt JSON key")
        result[name] = value
    return result


def reject_nonfinite_receipt_value(value: str) -> None:
    raise ValueError("Nonfinite physical receipt JSON token: " + value)


def finite_receipt_float(value: str) -> float:
    """Fail closed if a physical JSON number loses its decimal value.

    parse_constant rejects NaN/Infinity tokens, but Python's binary float
    parser can silently convert nonzero measurements into zero or infinity.
    Receipt evidence must not silently change numeric identity on import.
    """
    if len(value) > 64:
        raise ValueError("Overlong physical receipt JSON number")
    exact = Decimal(value)
    number = float(exact)
    if not math.isfinite(number) or Decimal(str(number)) != exact:
        raise ValueError("Lossy physical receipt JSON number: " + value)
    return number


def bounded_receipt_int(value: str) -> int:
    """Reject huge JSON integer tokens before a physical receipt is trusted.

    Keep evidence counters and measurements within exact signed 64-bit
    bounds. This is a decoder guard, not a physical pass criterion.
    """
    if len(value) > 20:
        raise ValueError("Overlong physical receipt JSON integer")
    number = int(value)
    if not -(1 << 63) <= number < (1 << 63):
        raise ValueError("Out-of-range physical receipt JSON integer")
    return number


def verified_procedure_record(row: dict, sha: str, lookup=github_json) -> bool:
    """Require the immutable data file to identify the measured procedure.

    Existence of an unrelated nonempty docs/records file is insufficient.
    """
    signoff = row.get("physical_measurement_receipt")
    if not isinstance(signoff, dict):
        return False
    url = signoff.get("raw_data_url")
    if not isinstance(url, str):
        return False
    captured = {}

    def capture(target):
        result = lookup(target)
        captured["file"] = result
        return result

    if not verified_raw_record(url, sha, capture):
        return False
    file = captured.get("file")
    if (not isinstance(file, dict) or file.get("encoding") != "base64"
            or not isinstance(file.get("content"), str)
            or not 0 < file.get("size", 0) <= 1_000_000):
        return False
    try:
        raw = base64.b64decode("".join(file["content"].split()), validate=True)
        if len(raw) != file["size"]:
            return False
        source_revision = signoff.get("source_sha", sha)
        digest = signoff.get("artifact_sha256")
        if digest is not None and not evidence_digest_matches(raw, digest):
            return False
        if source_revision != sha and (
            not evidence_digest_matches(raw, digest)
            or not source_unchanged_since_test(source_revision, sha, lookup)
        ):
            return False
        content = raw.decode("utf-8-sig")
        if urlsplit(url).path.lower().endswith(".csv"):
            reader = csv.DictReader(io.StringIO(content), strict=True)
            if (not reader.fieldnames
                    or any(not field or field != field.strip()
                           for field in reader.fieldnames)
                    or len(reader.fieldnames) != len(set(reader.fieldnames))):
                return False
            records = list(reader)
            # DictReader permits overflow under key None and fills absent
            # cells with None. A malformed physical row cannot be evidence.
            if any(None in record or any(value is None for value in record.values())
                   for record in records):
                return False
        elif urlsplit(url).path.lower().endswith(".json"):
            document = json.loads(
                content, object_pairs_hook=strict_receipt_object,
                parse_constant=reject_nonfinite_receipt_value,
                parse_float=finite_receipt_float,
                parse_int=bounded_receipt_int,
            )
            records = document.get("receipts") if isinstance(document, dict) else None
        else:
            return False
    except (ValueError, TypeError, UnicodeError, binascii.Error, csv.Error):
        return False
    if not isinstance(records, list) or not 0 < len(records) <= 2000:
        return False
    identifier = row.get("id")
    # Python treats true == 1 and 9.0 == 9. A malformed JSON identity
    # must never qualify an immutable physical procedure record.
    def exact_procedure_id(value: object) -> bool:
        return (type(value) is int and value == identifier) or (
            type(value) is str and value == str(identifier)
        )

    matches = [record for record in records if isinstance(record, dict)
               and exact_procedure_id(record.get("procedure_id"))]
    if len(matches) != 1:
        return False
    record = matches[0]
    measured = record.get("measurement")
    has_measurement = (
        (isinstance(measured, dict) and bool(measured))
        or (isinstance(measured, str) and measured.strip().casefold()
            not in {"", "unknown", "tbd", "n/a", "pass", "none"})
    )
    tested_on = record.get("tested_on")
    try:
        valid_date = (isinstance(tested_on, str)
                      and date.fromisoformat(tested_on).isoformat() == tested_on
                      and date.fromisoformat(tested_on) <= date.today())
    except ValueError:
        valid_date = False
    return bool(
        record.get("source_sha") == source_revision
        and record.get("gate") == row.get("gate")
        and record.get("result") == "pass"
        and record.get("operator") == signoff.get("operator")
        and record.get("device_revision") == signoff.get("device_revision")
        and valid_date and tested_on == signoff.get("tested_on")
        and has_measurement
    )

def verified_manual_review(row: dict, sha: str, lookup=github_json) -> bool:
    """Resolve exact PR review evidence, not a self-declared URL string."""
    receipt = row.get("manual_review_receipt")
    if not isinstance(receipt, dict) or receipt.get("sha") != sha:
        return False
    reviewer, url = receipt.get("reviewer"), receipt.get("review_url")
    if not isinstance(reviewer, str) or not isinstance(url, str):
        return False
    match = re.fullmatch(
        r"https://github\.com/hungngodev/desk-robot-remix/pull/17"
        r"#issuecomment-([0-9]+)", url,
    )
    if match is None:
        return False
    comment = lookup(f"https://api.github.com/repos/{REPO}/issues/comments/{match[1]}")
    actor = comment.get("user")
    body = comment.get("body")
    identifier = row.get("id")
    return (
        comment.get("html_url") == url
        and isinstance(actor, dict)
        and actor.get("type") == "User"
        and actor.get("login") == reviewer
        and comment.get("author_association") in {"OWNER", "MEMBER", "COLLABORATOR"}
        and isinstance(body, str)
        and isinstance(identifier, int)
        # A mere mention can be a rejection ("NOT ACCEPTED"), a quote or
        # historical discussion. Accept only a deliberate, standalone
        # affirmative reviewer statement bound to the exact tested SHA.
        and bool(re.fullmatch(
            rf"ACCEPTED procedure #?{identifier} at {re.escape(sha)}",
            body.strip(), re.IGNORECASE,
        ))
    )


def valid_physical_signoff(receipt: object) -> bool:
    """Operator identity and actual carrier revision are mandatory metadata.

    Live record existence is checked separately; these string checks alone
    cannot attest to an instrument, measured force, stopping distance or cell.
    """
    if not isinstance(receipt, dict) or receipt.get("result") != "pass":
        return False
    fields = (
        ("operator", {"", "unknown", "tbd", "bench engineer", "operator", "tester"}),
        ("device_revision", {"", "unknown", "tbd", "generic", "received carrier revision"}),
    )
    for name, placeholders in fields:
        value = receipt.get(name)
        if not isinstance(value, str) or value.strip().casefold() in placeholders:
            return False
    return True


def audit(ledger: dict, lookup=github_json) -> list[str]:
    """Return failures, never turn network errors into a success receipt."""
    if type(ledger) is not dict:
        return ["incomplete procedure ledger: expected JSON object"]
    rows = ledger.get("procedures")
    if type(rows) is not list:
        return ["incomplete procedure ledger: missing procedures array"]
    errors: list[str] = []
    states = {"OPEN", "TESTED", "MEASURED", "QUALIFIED"}
    for row in rows:
        if type(row) is not dict:
            errors.append("procedure unknown: expected object")
            continue
        identifier = row.get("id", "unknown")
        if type(identifier) is not int or not 1 <= identifier <= 96:
            errors.append(f"procedure {identifier}: invalid procedure id")
            continue
        gate = row.get("gate")
        if type(gate) is not str or gate not in states:
            errors.append(f"procedure {identifier}: unknown gate {gate!r}")
            continue
        if gate == "OPEN":
            continue
        evidence_class = row.get("evidence_class")
        if evidence_class not in {"source", "mixed", "physical"}:
            errors.append(f"procedure {identifier}: missing evidence class")
            continue
        if evidence_class == "physical" and row.get("gate") == "TESTED":
            errors.append(f"procedure {identifier}: physical task cannot be source-only TESTED")
            continue
        command = row.get("verification_command")
        receipt = row.get("executed_test_receipt")
        if (not isinstance(command, str)
                or not command.startswith("cd code && ")
                or re.search(r"--(?:help|version|collect-only)\b|&& true\b", command)
                or not isinstance(receipt, dict)
                or receipt.get("command") != command):
            errors.append(f"procedure {identifier}: executable command receipt mismatch")
            continue
        sha = row.get("last_verified_sha")
        if (not isinstance(sha, str) or not SHA.fullmatch(sha)
                or not isinstance(receipt, dict)
                or receipt.get("sha") != sha
                or type(receipt.get("exit_code")) is not int
                or receipt["exit_code"] != 0):
            errors.append(f"procedure {identifier}: invalid source receipt")
            continue
        method = row.get("verification_method")
        if method not in (None, "manual_review"):
            errors.append(f"procedure {identifier}: unsupported verification method")
            continue
        if type(identifier) is int and 1 <= identifier <= 8 and method != "manual_review":
            errors.append(f"procedure {identifier}: manual review evidence is compulsory")
            continue
        # A physical pass must be accepted by an authorized GitHub reviewer,
        # even when its verification method is an executable test command.
        # Operator and device strings alone are not acceptance authority.
        if method == "manual_review" or gate in {"MEASURED", "QUALIFIED"}:
            try:
                if not verified_manual_review(row, sha, lookup):
                    errors.append(f"procedure {identifier}: manual review not verified")
            except (HTTPError, URLError, ValueError, TimeoutError, OSError) as exc:
                errors.append(
                    f"procedure {identifier}: manual review lookup failed: "
                    f"{type(exc).__name__}"
                )
        try:
            if not verified_actions_run(receipt.get("url", ""), sha, lookup):
                errors.append(f"procedure {identifier}: CI run not verified")
        except (HTTPError, URLError, ValueError, TimeoutError, OSError) as exc:
            errors.append(f"procedure {identifier}: CI lookup failed: {type(exc).__name__}")
        if row.get("gate") in {"MEASURED", "QUALIFIED"}:
            measurement = row.get("physical_measurement_receipt")
            if not valid_physical_signoff(measurement):
                errors.append(f"procedure {identifier}: incomplete physical signoff")
                continue
            try:
                if not verified_procedure_record(row, sha, lookup):
                    errors.append(f"procedure {identifier}: immutable physical record not matched")
            except (HTTPError, URLError, ValueError, TimeoutError, OSError) as exc:
                errors.append(
                    f"procedure {identifier}: physical lookup failed: {type(exc).__name__}"
                )
    # A stand-alone online audit is a release-facing command. It must not
    # succeed on a shortened or replaced ledger simply because every remaining
    # OPEN row has no online receipt to check. Preserve detailed row failures
    # above and validate the full canonical procedure universe here.
    if (type(ledger.get("schema_version")) is not int
            or ledger["schema_version"] != 2
            or ledger.get("canonical_repository") != REPO
            or type(ledger.get("canonical_pr")) is not int
            or ledger["canonical_pr"] != 17
            or type(ledger.get("procedure_count")) is not int
            or ledger["procedure_count"] != 96):
        errors.append("incomplete procedure ledger: canonical metadata mismatch")
    ids = [row.get("id") if type(row) is dict else None for row in rows]
    if len(rows) != 96 or ids != list(range(1, 97)):
        errors.append("incomplete procedure ledger: expected exactly 96 unique ordered IDs 1..96")
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
