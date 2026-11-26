"""Canonical command admission must agree with the actual procedure ledger."""
import importlib.util
import json
import shlex
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "playbook_command_policy", ROOT / "code/scripts/verify_playbook_receipts.py",
)
POLICY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(POLICY)
ROWS = json.loads((ROOT / "docs/reviews/100_page_procedure_trace.json").read_text())["procedures"]


@pytest.mark.parametrize("row", ROWS, ids=lambda row: str(row["id"]))
def test_canonical_command_is_admitted(row):
    assert POLICY.valid_procedure_command(row["id"], row["verification_command"])


@pytest.mark.parametrize("identifier,command", [
    (9, "cd code && git rev-parse HEAD"),
    (1, "cd code && git rev-parse HEAD && true"),
    (2, "cd code && python scripts/verify_system.py --suite body"),
    (26, "cd code && python scripts/verify_system.py --suite sense"),
    (41, "cd code && python scripts/verify_system.py --suite all"),
    (81, "cd code && python scripts/verify_system.py --suite all --help"),
    (9, "cd code && python -m pytest --collect-only tests/test_pet.py"),
    (20, "cd code && cmake --build /tmp/body-build --target cliff_fault_policy"),
])
def test_wrong_procedure_or_nonexecuting_command_is_rejected(identifier, command):
    assert not POLICY.valid_procedure_command(identifier, command)


def test_review_reconciliation_requires_all_surfaces():
    command = POLICY._REVIEW_RECONCILIATION_COMMAND
    assert POLICY.valid_procedure_command(4, command)
    assert not POLICY.valid_procedure_command(5, command)
    tokens = shlex.split(command)
    assert tokens.count("--paginate") == 4
    for endpoint in ("issues/17/comments", "pulls/17/reviews", "pulls/17/comments"):
        assert f"repos/{POLICY.REPO}/{endpoint}" in tokens
    for field in ("isResolved", "isOutdated", "hasNextPage", "endCursor", "databaseId"):
        assert field in tokens[-1]


@pytest.mark.parametrize("command", [
    "cd code && gh api repos/hungngodev/desk-robot-remix/pulls/17/comments --paginate",
    "cd code && python -m pytest -q tests/test_playbook_command_policy.py",
    POLICY._REVIEW_RECONCILIATION_COMMAND.replace("isResolved ", ""),
    POLICY._REVIEW_RECONCILIATION_COMMAND.replace("--paginate", "", 1),
    POLICY._REVIEW_RECONCILIATION_COMMAND + " && true",
])
def test_review_reconciliation_rejects_partial_or_substitute_command(command):
    assert not POLICY.valid_procedure_command(4, command)
