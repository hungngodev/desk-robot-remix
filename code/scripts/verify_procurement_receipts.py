"""Live evidence check for the irreversible five-robot purchasing release.

The ordinary procurement projection is intentionally pure and accepts
synthetic receipts in its regression tests. The *actual* --require-release
command must additionally resolve every recorded gate receipt to an existing
immutable project record at the clean current source revision.

File existence is not evidence that a physical trial was honest. A human
reviewer must inspect raw measurements and the exact received PCB/pack before
ordering. No physical or charging authorization is inferred by this script.
"""
from __future__ import annotations

import base64
import binascii
import json
import re
import subprocess
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit

from procurement_release import (
    FIRST_ROBOT_ROOM_GATE,
    FLEET_ONLY_SYSTEM_GATES,
    PART_GATES,
    SUPPLEMENTAL_DECISIONS,
    SYSTEM_GATES,
)
from verify_playbook_receipts import verified_raw_record
from verify_system import source_snapshot

ROOT = Path(__file__).resolve().parents[2]
SHA = re.compile(r"^[0-9a-f]{40}$")


def checkout_sha() -> str:
    """Require a clean complete tree, not a sparse/truncated Git index.

    Share the canonical host verification's real worktree presence checks.
    A clean SHA and 400 index entries alone previously missed directories
    removed by sparse checkout or an accidental partial repository tree.
    """
    snapshot = source_snapshot()
    sha = snapshot.get("sha")
    if (not isinstance(sha, str) or not SHA.fullmatch(sha)
            or snapshot.get("tracked_clean") is not True
            or snapshot.get("root_tree_intact") is not True):
        raise ValueError("A clean exact commit and full repository tree are required for ordering")
    # Source authority is the existing PR branch. A clean main checkout,
    # stale fork or detached synthetic merge is not the purchase baseline.
    try:
        current_branch = subprocess.check_output(
            ["git", "symbolic-ref", "--quiet", "--short", "HEAD"],
            cwd=ROOT, text=True, timeout=10,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        current_branch = ""
    if current_branch != "impl/mac-hardware-safety-preflight-2026-11-10":
        raise ValueError("Purchasing requires the canonical PR #17 branch")
    return sha


def required_receipts(evidence: dict, *, first_robot: bool = False):
    """Scope each receipt to its specific purchased part, station or gate."""
    for ident, record in evidence.get("parts", {}).items():
        for gate in PART_GATES:
            yield "part:" + ident, gate, record.get(gate)
    for ident, record in evidence.get("room_pod", {}).items():
        for gate in PART_GATES:
            yield "room:" + ident, gate, record.get(gate)
    for gate in SYSTEM_GATES:
        if first_robot and gate in FLEET_ONLY_SYSTEM_GATES:
            continue
        yield "system", gate, evidence.get("system", {}).get(gate)
    if first_robot:
        yield ("system", FIRST_ROBOT_ROOM_GATE,
               evidence.get("system", {}).get(FIRST_ROBOT_ROOM_GATE))
    for ident in SUPPLEMENTAL_DECISIONS:
        selection = evidence.get("supplemental_decisions", {}).get(ident, {})
        scope = "supplemental:" + ident
        yield scope, "decision_receipt", selection.get("decision_receipt")
        if selection.get("disposition") in {"selected", "reuse_existing"}:
            for gate in PART_GATES:
                yield scope, gate, selection.get(gate)
        else:
            yield scope, "alternative_or_parent_receipt", (
                selection.get("alternative_or_parent_receipt")
            )


def verified_scoped_record(receipt: dict, sha: str, lookup) -> bool:
    """Require one matching record in a versioned docs/records/*.json file.

    The file must contain {"receipts": [record, ...]}, with an explicit
    result, reviewer, tested date, exact revision and measurement payload.
    Mere existence of an unrelated nonempty file never releases purchasing.
    """
    url = receipt.get("evidence_url")
    if not isinstance(url, str) or not urlsplit(url).path.endswith(".json"):
        return False
    response = {}

    def capture(target):
        data = lookup(target)
        response["file"] = data
        return data

    if not verified_raw_record(url, sha, capture):
        return False
    file = response.get("file")
    if (not isinstance(file, dict)
            or file.get("encoding") != "base64"
            or not isinstance(file.get("content"), str)
            or not 0 < file["size"] <= 1_000_000):
        return False
    try:
        raw = base64.b64decode("".join(file["content"].split()), validate=True)
        if len(raw) != file["size"]:
            return False
        document = json.loads(raw.decode("utf-8"))
    except (ValueError, TypeError, UnicodeError, binascii.Error):
        return False
    rows = document.get("receipts") if type(document) is dict else None
    if not isinstance(rows, list) or not 0 < len(rows) <= 2000:
        return False
    identifiers = [row.get("record_id") for row in rows if type(row) is dict]
    if (len(identifiers) != len(rows)
            or any(not isinstance(i, str) or not i.strip() for i in identifiers)
            or len(set(identifiers)) != len(identifiers)):
        return False
    matched = [
        row for row in rows
        if row.get("scope") == receipt.get("scope")
        and row.get("gate") == receipt.get("gate")
    ]
    if len(matched) != 1:
        return False
    record = matched[0]
    fields = (
        "record_id", "source_sha", "scope", "gate", "result",
        "reviewer", "tested_on", "device_revision",
    )
    measurement = record.get("measurement")
    return (record.get("result") == "pass"
            and all(record.get(key) == receipt.get(key) for key in fields)
            and isinstance(measurement, dict) and bool(measurement)
            and measurement == receipt.get("measurement"))


def audit_release(evidence: dict, sha: str, lookup=None, *,
                  first_robot: bool = False) -> list[str]:
    """Fail closed if a receipt is missing, mis-scoped or not actually present."""
    if not isinstance(evidence, dict) or not SHA.fullmatch(sha):
        return ["missing exact checkout SHA or release evidence"]
    from verify_playbook_receipts import github_json
    lookup = github_json if lookup is None else lookup
    errors = []
    seen = 0
    fetched = {}

    def cached_lookup(url):
        if url not in fetched:
            fetched[url] = lookup(url)
        return fetched[url]

    for scope, gate, receipt in required_receipts(
        evidence, first_robot=first_robot
    ):
        seen += 1
        if not isinstance(receipt, dict):
            errors.append(f"{scope}.{gate}: missing receipt")
            continue
        if (receipt.get("result") != "pass"
                or receipt.get("source_sha") != sha
                or receipt.get("scope") != scope
                or receipt.get("gate") != gate
                or not isinstance(receipt.get("reviewer"), str)
                or receipt["reviewer"].strip().casefold() in {
                    "", "unknown", "tbd", "operator", "tester", "fixture",
                }
                or not isinstance(receipt.get("tested_on"), str)
                or not receipt["tested_on"].strip()
                or not isinstance(receipt.get("record_id"), str)
                or not receipt["record_id"].strip()
                or not isinstance(receipt.get("device_revision"), str)
                or receipt["device_revision"].strip().casefold() in {
                    "", "unknown", "tbd", "generic",
                }
                or not isinstance(receipt.get("measurement"), dict)
                or not receipt["measurement"]):
            errors.append(f"{scope}.{gate}: unpinned or generic signoff")
            continue
        try:
            if not verified_scoped_record(receipt, sha, cached_lookup):
                errors.append(f"{scope}.{gate}: immutable scoped record absent or mismatched")
        except (HTTPError, URLError, ValueError, TimeoutError, OSError):
            errors.append(f"{scope}.{gate}: record lookup unavailable")
    if seen == 0:
        errors.append("no release receipts recorded")
    return errors
