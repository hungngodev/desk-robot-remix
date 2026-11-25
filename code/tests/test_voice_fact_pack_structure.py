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
