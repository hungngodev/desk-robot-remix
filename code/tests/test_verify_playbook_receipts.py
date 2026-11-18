"""Online playbook receipts must be checked against actual GitHub metadata."""
import importlib.util
from pathlib import Path
from urllib.error import URLError

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "playbook_online_receipts",
    ROOT / "code/scripts/verify_playbook_receipts.py",
)
verify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)
SHA = "a" * 40
RUN = "https://github.com/hungngodev/desk-robot-remix/actions/runs/42"
RAW = ("https://github.com/hungngodev/desk-robot-remix/blob/"
       + SHA + "/docs/records/bench.csv")


def lookup(url):
    if url.endswith("/actions/runs/42"):
        return {"head_sha": SHA, "status": "completed", "conclusion": "success"}
    if "/contents/docs/records/bench.csv?ref=" in url:
        return {"type": "file", "size": 52}
    raise AssertionError("Unexpected URL " + url)


def promoted(gate="TESTED"):
    return {"procedures": [{
        "id": 89, "gate": gate, "last_verified_sha": SHA,
        "executed_test_receipt": {
            "sha": SHA, "exit_code": 0, "url": RUN,
        },
        "physical_measurement_receipt": {
            "result": "pass", "raw_data_url": RAW,
        },
    }]}


def test_open_playbook_requires_no_network():
    assert verify.audit({"procedures": [{"id": 89, "gate": "OPEN"}]},
                        lambda url: 1 / 0) == []


def test_verified_run_and_pinned_physical_record_paths():
    assert verify.audit(promoted("MEASURED"), lookup) == []
    assert verify.verified_actions_run(RUN, SHA, lookup)
    assert verify.verified_raw_record(RAW, SHA, lookup)


def test_ci_fails_if_github_reports_failure_or_wrong_sha():
    def failed(_):
        return {"head_sha": "b" * 40, "status": "completed",
                "conclusion": "failure"}
    assert "CI run not verified" in verify.audit(promoted(), failed)[0]


def test_physical_record_must_exist_at_same_commit():
    bad = promoted("MEASURED")
    bad["procedures"][0]["physical_measurement_receipt"]["raw_data_url"] = (
        RAW.replace(SHA, "b" * 40))
    assert any("raw physical record not found" in item
               for item in verify.audit(bad, lookup))

    def empty_record(url):
        if "/contents/" in url:
            return {"type": "file", "size": 0}
        return lookup(url)
    assert any("raw physical record not found" in item
               for item in verify.audit(promoted("MEASURED"), empty_record))


def test_unavailable_api_cannot_approve_evidence():
    def offline(_):
        raise URLError("offline")
    assert any("CI lookup failed" in item
               for item in verify.audit(promoted(), offline))


def test_wrong_run_host_is_rejected_without_network():
    fake = promoted()
    fake["procedures"][0]["executed_test_receipt"]["url"] = (
        "https://example.com/hungngodev/desk-robot-remix/actions/runs/42")
    assert "CI run not verified" in verify.audit(fake, lookup)[0]
