"""Check the complete PlatformIO library inventory after a room station build."""

import argparse
import json
from pathlib import Path

CODE = Path(__file__).resolve().parents[1]


def verify_inventory(directory, lock):
    """Fail on missing, duplicate, unexpected or differently resolved libraries."""
    expected = lock['direct_libraries'] | lock['transitive_libraries']
    seen = set()
    for package in sorted(directory.iterdir()):
        if not package.is_dir():
            continue
        # PlatformIO 6.1.18 stores metadata in .git or the package root.
        metadata = next(
            (path for path in (package / '.git/.piopm', package / '.piopm') if path.is_file()),
            None,
        )
        if metadata is None:
            raise ValueError(f'Missing package metadata: {package}')
        item = json.loads(metadata.read_text())
        name = item['name']
        if name in seen or name not in expected:
            raise ValueError(f'Duplicate or unexpected library: {name}')
        seen.add(name)
        pinned = expected[name]
        if isinstance(pinned, dict):
            uri = f"git+{pinned['url']}#{pinned['commit']}"
            prefix = f"{pinned['version']}+sha."
            version = item['version']
            revision = version.removeprefix(prefix)
            if (item.get('spec') or {}).get('uri') != uri or not (
                version.startswith(prefix)
                and len(revision) >= 7
                and pinned['commit'].startswith(revision)
            ):
                raise ValueError(f'Incorrect Git source or revision for {name}: {item}')
        elif item['version'] != pinned:
            raise ValueError(f"Incorrect version for {name}: {item['version']} != {pinned}")
    if seen != expected.keys():
        raise ValueError(f'Missing libraries: {sorted(expected.keys() - seen)}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('environment', nargs='+')
    args = parser.parse_args()
    lock = json.loads((CODE / 'toolchain-lock.json').read_text())['room_station']
    for environment in args.environment:
        directory = CODE / 'firmware/room_station/.pio/libdeps' / environment
        verify_inventory(directory, lock)
        print(f'Room station library inventory verified: {environment}')


if __name__ == '__main__':
    main()
