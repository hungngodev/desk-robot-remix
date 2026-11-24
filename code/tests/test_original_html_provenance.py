"""Guard against accidentally losing user-supplied HTML ideas and source links.

These tests guard the archived Markdown index of the original ESP32 Deskpet
Ideas.html dated 2026-11-09 (1,074,994 bytes, SHA256
12a0068f3bcec7daa6065cc180478294ccc1d0cc5e439250774684f3b2008b5d).
The original HTML is not in the checkout. Set DESK_ROBOT_ORIGINAL_HTML to
its path to rehash and inventory the raw file. Neither mode validates every
idea's prose, external URL access, publisher rights, or reuse.
"""
import hashlib
import os
import re
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path

import pytest

SOURCE_MAP = Path(__file__).resolve().parents[2] / "docs/source-map.md"
EXPECTED_URL_SHA = "83d6250c7c3e632e32624ef90b4656b61e2fe7f30f41b01b19761c3a7b24efc8"
EXPECTED_COUNTS = {"F": 39, "B": 30, "S": 75, "G": 46, "H": 10}


# Original DOM IDs, archived in the 2026-11-09 crosswalk. Keep evolving
# engineering interpretations editable while preserving section identity/order.
EXPECTED_SECTION_IDS = """
project-overview project-architecture project-build-order project-status
project-parts max30102-add project-rules project-roadmap topic6-power
topic4-drive-gripper topic1-cliff topic2-touch topic3-audio topic5-head-face
topic7-mac-brain topic8-proactive project-research-map research-library
start-here paths build-plan modpack1 modpack2 schedule top-picks
brainstorm-sensors specs spec-pack sensor-menu finds reddit-youtube steal
popular tweaks sensors ideas new-finds-2026-11-07 new-finds-2026-11-09
reference diy-shopping-list repos
""".split()


# SHA256 of the exact declared attribute value, not a download from its URL.
# Embedded JPEGs have no original publisher URL or license in the HTML.
EXPECTED_ASSET_REFERENCES = [
    ("link:icon", "4ff286857945d8713fd2e6744ee452fb51aadd3bca707c9850cb95ef18bba878"),
    # Google Fonts preconnect endpoints and stylesheet, not downloaded font files.
    ("link:preconnect", "8e2e7efb6cf0362d10625ef770e91c616d0d443c87612a7a790e7727bc370737"),
    ("link:preconnect", "fc9e1824b0e63191b9c26237bc1e3f710168b33e78dc4dd967e1f7f41dc94a3f"),
    ("link:stylesheet", "7378f86fba0386c16e73148e660e37f98af056b862fdb94383ec721b793a5efa"),
    # Embedded Cozmo, Eilik and StackChan JPEG data URIs in document order.
    ("img:src", "6fe42f22d04208365ebbe8a62941226bfbf4ae3263c4faba86459b10a4aff6a5"),
    ("img:src", "46feecb8f0f51d1634876eac15cd0f9ca8941ae9bc137cf995def0363ae95c22"),
    ("img:src", "dadbe7d9d057ada4a2b46896ea3f0903909ca8fcf5261d1830bbabf2bce46083"),
]


class OriginalHTMLInventory(HTMLParser):
    def __init__(self):
        super().__init__()
        self.sections = []
        self.anchors = []
        self.assets = []
        self.tags = Counter()

    def handle_starttag(self, tag, attrs):
        self.tags[tag] += 1
        attributes = dict(attrs)
        if tag == "section":
            self.sections.append(attributes.get("id"))
        if tag == "a" and "href" in attributes:
            self.anchors.append(attributes["href"])
        for name, value in attrs:
            if value is None:
                continue
            if name in {"src", "srcset", "poster", "data"}:
                self.assets.append((f"{tag}:{name}", hashlib.sha256(value.encode()).hexdigest()))
            elif tag == "link" and name == "href":
                self.assets.append((
                    f"link:{attributes.get('rel')}",
                    hashlib.sha256(value.encode()).hexdigest(),
                ))


def test_original_html_bytes_and_assets_when_supplied():
    """Opt-in source audit; private original bytes are not shipped in Git."""
    path = os.environ.get("DESK_ROBOT_ORIGINAL_HTML")
    if not path:
        pytest.skip("Set DESK_ROBOT_ORIGINAL_HTML to the archived original HTML")
    original = Path(path).read_bytes()
    assert len(original) == 1_074_994
    assert hashlib.sha256(original).hexdigest() == (
        "12a0068f3bcec7daa6065cc180478294ccc1d0cc5e439250774684f3b2008b5d"
    )
    inventory = OriginalHTMLInventory()
    inventory.feed(original.decode("utf-8"))
    inventory.close()
    assert inventory.sections == EXPECTED_SECTION_IDS
    assert len(inventory.anchors) == 567
    urls = [url for url in inventory.anchors if url.startswith(("http://", "https://"))]
    assert len(urls) == 256
    assert len(set(urls)) == 131
    assert hashlib.sha256(("\n".join(sorted(set(urls))) + "\n").encode()).hexdigest() == (
        EXPECTED_URL_SHA
    )
    assert inventory.assets == EXPECTED_ASSET_REFERENCES
    assert {tag: inventory.tags[tag] for tag in ("style", "script", "svg")} == {
        "style": 1, "script": 1, "svg": 1,
    }


def test_original_html_section_crosswalk_is_preserved():
    text = SOURCE_MAP.read_text(encoding="utf-8")
    section = text.split("## Original HTML DOM section crosswalk,", 1)[1]
    section = section.split("\n## ", 1)[0]
    rows = re.findall(
        r"(?m)^\| (\d+) \| `([^`]+)` \| .+ \| \[View\]\(([^)]+)\) \|$",
        section,
    )
    assert [int(index) for index, _, _ in rows] == list(range(1, 42))
    assert [section_id for _, section_id, _ in rows] == EXPECTED_SECTION_IDS
    docs = SOURCE_MAP.parent.resolve()
    for _, section_id, target in rows:
        path = (docs / target).resolve()
        assert path.is_relative_to(docs), section_id
        assert path.is_file(), (section_id, target)


def test_full_original_html_links_are_preserved_with_same_url_bytes():
    text = SOURCE_MAP.read_text(encoding="utf-8")
    rows = re.findall(r"(?m)^\| \`L(\d{3})\` \| <(https?://[^>]+)> \|$", text)
    assert len(rows) == 131
    assert [int(index) for index, _ in rows] == list(range(1, 132))
    urls = [url for _, url in rows]
    assert len(set(urls)) == 131
    assert sum(map(len, urls)) == 8786
    digest = hashlib.sha256(("\n".join(sorted(urls)) + "\n").encode()).hexdigest()
    assert digest == EXPECTED_URL_SHA


def test_all_200_original_idea_slots_are_preserved():
    text = SOURCE_MAP.read_text(encoding="utf-8")
    for kind, n in EXPECTED_COUNTS.items():
        matches = re.findall(rf"(?m)^\| \`{kind}(\d{{3}})\` \|", text)
        assert len(matches) == n, kind
        assert [int(x) for x in matches] == list(range(1, n + 1)), kind
    assert sum(EXPECTED_COUNTS.values()) == 200


def test_original_known_hardware_corrections_are_not_lost():
    path = Path(__file__).resolve().parents[2] / "docs/hardware/full-feature-plan.json"
    import json
    plan = json.loads(path.read_text(encoding="utf-8"))
    items = {item["id"]: item for item in plan["parts"]}
    assert items["max30102"]["per_robot"] == 1
    assert items["max30102"]["reported_owned_total"] == 0
    assert items["head_touch"]["reported_owned_total"] >= 1
    assert items["imu"]["reported_owned_total"] >= 1
    assert plan["bus"]["mux_extras"]["channels"][0]["devices"] == [
        # Default 0x29 CAP1188 now shares an address with VL53L0X only
        # ACROSS isolated muxes. Firmware first closes range 0x70, selects
        # 0x71 lane zero, and validates CAP1188 product/manufacturer ID.
        # Strapped 0x28 remains a separately probed alternative.
        {"name": "CAP1188", "address": 0x29},
        {"name": "MAX30102 paw pad", "address": 0x57},
    ]
