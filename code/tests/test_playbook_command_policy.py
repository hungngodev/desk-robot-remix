"""Canonical command admission must agree with the actual procedure ledger."""
import importlib.util
import json
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
