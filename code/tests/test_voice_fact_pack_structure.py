"""Pure voice fact boundary regressions, without a model or head socket."""
import json
from pathlib import Path

import pytest


@pytest.fixture
def pack(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / 'laptop/server/overlay'))
    from desk_robot_voice_intents import pack_grounded_facts

    return pack_grounded_facts


@pytest.mark.parametrize('bad', [{1: 2150, '1': 4400}, {False: 0}, {'summary': '\ud800'},
                                 {'\udfff': 'value'}])
def test_pack_rejects_lossy_json_structure(pack, bad):
    with pytest.raises(ValueError, match='Tool facts must be JSON values'):
        pack([{'source': 'status', 'nested': [bad]}])


def test_pack_rejects_deep_structure_before_encoding(pack):
    node = {'value': 1}
    for _ in range(10000):
        node = {'nested': node}
    with pytest.raises(ValueError, match='Tool facts must be JSON values'):
        pack([node])


def test_pack_preserves_real_unicode_and_typed_receipts(pack):
    facts = [{'source': 'camera', 'summary': 'cà phê ☕ 🤖'},
             {'source': 'status', 'armed': False, 'cell_mv': 3700}]
    packed = pack(facts)
    assert packed.isascii()
    assert json.loads(packed) == facts


@pytest.mark.parametrize("limit", [256, 257, 4096])
def test_pack_exact_budget_preserves_order_and_typed_values(pack, limit):
    facts = [{"source": "status", "armed": False, "raw": ""},
             {"source": "power", "cell_mv": 3700}]
    base = len(pack(facts, limit=limit))
    facts[0]["raw"] = "x" * (limit - base)
    packed = pack(facts, limit=limit)
    assert len(packed) == limit
    assert json.loads(packed) == facts
    facts[0]["raw"] += "x"
    with pytest.raises(ValueError, match="speech context budget"):
        pack(facts, limit=limit)


@pytest.mark.parametrize("limit", [True, 255, 4097, 256.0, None])
def test_pack_rejects_invalid_budget_type_or_range(pack, limit):
    with pytest.raises(ValueError):
        pack([{"source": "status"}], limit=limit)


def test_pack_exact_depth_boundary(pack):
    # Root list is depth zero, its first dictionary is depth one.
    node = {"value": 1}
    for _ in range(30):
        node = {"nested": node}
    assert json.loads(pack([node])) == [node]
    with pytest.raises(ValueError, match="Tool facts must be JSON values"):
        pack([{"nested": node}])
