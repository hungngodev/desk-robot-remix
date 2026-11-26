"""Ensure room station source pins and resolved dependencies cannot drift silently."""

import configparser
import json
import re
import sys
from pathlib import Path

import pytest

CODE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE / 'scripts'))
from verify_room_station_dependencies import verify_inventory  # noqa: E402

LOCK = json.loads((CODE / 'toolchain-lock.json').read_text())['room_station']


def test_room_station_source_pins():
    ini = configparser.ConfigParser(interpolation=None)
    ini.read(CODE / 'firmware/room_station/platformio.ini')
    assert ini['env']['platform'] == f"nordicnrf52@{LOCK['nordicnrf52']}"
    assert ini['env']['board'] == 'adafruit_feather_nrf52840'
    assert ini['env']['framework'] == 'arduino'
    direct = LOCK['direct_libraries']
    assert all(re.fullmatch(r'[0-9a-f]{40}', item['commit']) for item in direct.values())
    assert set(ini['env']['lib_deps'].split()) == {
        f"{item['url']}#{item['commit']}" for item in direct.values()
    }
    assert len(ini['env']['lib_deps'].split()) == len(direct)
    assert not (direct.keys() & LOCK['transitive_libraries'].keys())
    for section in ini.sections():
        if section.startswith('env:'):
            assert not {'lib_deps', 'platform', 'board', 'framework'} & ini[section].keys()


@pytest.mark.parametrize('fault', ['none', 'missing', 'extra', 'duplicate', 'version', 'uri', 'sha'])
def test_room_station_resolved_inventory(tmp_path, fault):
    packages = []
    for name, item in LOCK['direct_libraries'].items():
        packages.append({
            'name': name,
            'version': f"{item['version']}+sha.{item['commit'][:7]}",
            'spec': {'uri': f"git+{item['url']}#{item['commit']}"},
        })
    packages.extend({'name': name, 'version': version}
                    for name, version in LOCK['transitive_libraries'].items())
    if fault == 'missing':
        packages.pop()
    elif fault == 'extra':
        packages.append({'name': 'Unexpected', 'version': '1.0.0'})
    elif fault == 'duplicate':
        packages.append(packages[0])
    elif fault == 'version':
        packages[-1]['version'] = '99.0.0'
    elif fault == 'uri':
        packages[0]['spec']['uri'] = 'git+https://example.com/wrong.git#main'
    elif fault == 'sha':
        packages[0]['version'] = '1.1.0+sha.0000000'
    for index, item in enumerate(packages):
        package = tmp_path / str(index)
        package.mkdir()
        (package / '.piopm').write_text(json.dumps(item))
    if fault == 'none':
        verify_inventory(tmp_path, LOCK)
    else:
        with pytest.raises(ValueError):
            verify_inventory(tmp_path, LOCK)


def test_room_station_notice_inventory():
    direct = LOCK['direct_libraries']
    for item in direct.values():
        base = f"{item['url'].removesuffix('.git')}/blob/{item['commit']}/"
        assert all(url.startswith(base) for url in [item['notice'], *item.get('additional_notices', [])])
    notices = LOCK['transitive_notice_sources']
    assert notices.keys() == LOCK['transitive_libraries'].keys()
    assert all(re.fullmatch(r'https://github\.com/[^/]+/[^/]+/blob/[0-9a-f]{40}/.+', url)
               for url in notices.values())
