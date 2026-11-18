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

import json
import re
from pathlib import Path
from urllib.error import HTTPError, URLError

from procurement_release import PART_GATES, SUPPLEMENTAL_DECISIONS, SYSTEM_GATES
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
    return sha

def required_receipts(evidence: dict):
    """Scope each receipt to its specific purchased part, station or gate."""
    for ident, record in evidence.get("parts", {}).items():
        for gate in PART_GATES:
            yield "part:" + ident, gate, record.get(gate)
    for ident, record in evidence.get("room_pod", {}).items():
        for gate in PART_GATES:
            yield "room:" + ident, gate, record.get(gate)
    for gate in SYSTEM_GATES:
        yield "system", gate, evidence.get("system", {}).get(gate)
    for ident, (parent, count) in SUPPLEMENTAL_DECISIONS.items():
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


def audit_release(evidence: dict, sha: str, lookup=None) -> list[str]:
    """Fail closed if a receipt is missing, mis-scoped or not actually present."""
    if not isinstance(evidence, dict) or not SHA.fullmatch(sha):
        return ["missing exact checkout SHA or release evidence"]
    from verify_playbook_receipts import github_json
    lookup = github_json if lookup is None else lookup
    errors = []
    seen = 0
    for scope, gate, receipt in required_receipts(evidence):
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
                or not receipt["tested_on"].strip()):
            errors.append(f"{scope}.{gate}: unpinned or generic signoff")
            continue
        try:
            if not verified_raw_record(
                receipt.get("evidence_url"), sha, lookup
            ):
                errors.append(f"{scope}.{gate}: immutable source record absent")
        except (HTTPError, URLError, ValueError, TimeoutError, OSError):
            errors.append(f"{scope}.{gate}: record lookup unavailable")
    if seen == 0:
        errors.append("no release receipts recorded")
    return errors
