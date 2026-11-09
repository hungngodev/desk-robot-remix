"""Consolidated day-zero blueprint integrity and traceability contract.

These host tests protect design records only. They do not qualify real robots.
"""

from pathlib import Path
import re

import pytest


REPO = Path(__file__).resolve().parents[2]
BLUEPRINT = REPO / "docs" / "blueprint"
DOCUMENTS = (
    "README.md",
    "system-contract.md",
    "linear-build.md",
    "feature-register.md",
    "reuse-register.md",
    "original-html-link-index.md",
    "acceptance.md",
    "decisions-before-hardware.md",
    "html-quantitative-proposals.md",
    "implementation-file-plan.md",
)


@pytest.fixture(scope="module")
def pages() -> dict[str, str]:
    return {
        name: (BLUEPRINT / name).read_text(encoding="utf-8")
        for name in DOCUMENTS
    }


def test_original_feature_ids_are_all_preserved(pages):
    """The original consolidated register covers 200 named entries across 5 families."""
    found = re.findall(
        r"^\| `([FBSGH]\d{3})` \|",
        pages["feature-register.md"],
        flags=re.MULTILINE,
    )
    expected = {
        *(f"F{n:03d}" for n in range(1, 40)),
        *(f"B{n:03d}" for n in range(1, 31)),
        *(f"S{n:03d}" for n in range(1, 76)),
        *(f"G{n:03d}" for n in range(1, 47)),
        *(f"H{n:03d}" for n in range(1, 11)),
    }
    assert len(found) == len(set(found)), "Duplicate feature IDs cause ambiguity"
    assert expected <= set(found), sorted(expected - set(found))
    assert len(found) >= 200


def test_all_html_external_resources_have_a_stable_index(pages):
    content = pages["original-html-link-index.md"]
    items = re.findall(
        r"^\| `(L\d{3})` \| <(https?://[^>\s]+)> \|$",
        content,
        flags=re.MULTILINE,
    )
    ids = [item[0] for item in items]
    urls = [item[1] for item in items]
    assert len(items) >= 131, "Original 131 unique links have been lost"
    assert len(ids) == len(set(ids))
    assert len(urls) == len(set(urls))
    assert {f"L{n:03d}" for n in range(1, 132)} <= set(ids)


@pytest.mark.parametrize("name", DOCUMENTS)
def test_relative_blueprint_document_links_resolve(name, pages):
    """Check local document files, not remote pages or browser anchors."""
    markdown_links = re.findall(r"\]\(([^)]+)\)", pages[name])
    for link in markdown_links:
        if link.startswith(("http://", "https://", "mailto:", "#")):
            continue
        relative = link.split("#", 1)[0]
        if relative:
            target = BLUEPRINT / relative
            assert target.exists(), f"{name} has a broken local link: {link}"


def test_accepted_experience_and_fail_closed_constraints_are_explicit(pages):
    contract = pages["system-contract.md"].lower()
    acceptance = pages["acceptance.md"].lower()
    design = pages["decisions-before-hardware.md"].lower()
    for claim in (
        "proactive",
        "quiet",
        "memory",
        "cliff",
        "speaker",
        "five",
        "camera",
        "max30102",
        "sense",
        "blind reverse",
    ):
        assert claim in contract
    for test in range(1, 13):
        assert re.search(rf"\bA{test}\b", acceptance), f"A{test} missing"
    assert "19/20" in acceptance and "18/20" in acceptance
    assert "8/10" in acceptance and "120s" in acceptance
    assert "$50" in design and "$52.87" in design
    assert "41/42" in design
    assert "l4cd" in design.lower()


def test_entrypoints_make_blueprint_discoverable():
    for name in ("README.md", "docs/README.md", "docs/PLAN.md", "AGENTS.md"):
        text = (REPO / name).read_text(encoding="utf-8")
        assert "blueprint/" in text or "docs/blueprint/" in text
