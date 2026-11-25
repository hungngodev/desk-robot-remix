import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
from unittest.mock import Mock

import pytest

HEAD = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("overlay_release", HEAD / "install_overlay.py")
overlay = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(overlay)
UPSTREAM = Path(os.environ.get("DESK_ROBOT_UPSTREAM", HEAD.parents[1] / "upstream/xiaozhi-esp32"))


@pytest.mark.parametrize("fault", [None, "missing", "null", "empty", "wrong", "duplicate"])
def test_release_publish_requires_exact_remote_digest(tmp_path, fault):
    path = UPSTREAM / "scripts/release.py"
    if not path.is_file():
        pytest.skip("pinned upstream checkout is required")
    source = overlay.harden_release_tooling(path.read_text())
    # Execute the actual patched publish function; isolate only the external API.
    tree = ast.parse(source)
    publish = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                   and node.name == "publish")
    assets = tmp_path / "assets"
    assets.mkdir()
    archive = assets / "v2.5.2_test.zip"
    archive.write_bytes(b"firmware")
    metadata = tmp_path / "metadata"
    manifest = {"tag": "v2.5.2", "source_sha": "a" * 40, "firmware_count": 1,
                "board_count": 1, "idf_version": "6.1.0"}
    draft = {"id": 42, "draft": True, "target_commitish": manifest["source_sha"]}

    def remote(_repo, endpoint, **kwargs):
        if endpoint == "releases/latest":
            return None
        assert endpoint == "releases/42"
        files = [archive, metadata / "release-manifest.json", metadata / "SHA256SUMS"]
        entries = [{"name": p.name, "size": p.stat().st_size,
                    "digest": "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest()}
                   for p in files]
        if fault == "missing":
            del entries[0]["digest"]
        elif fault == "null":
            entries[0]["digest"] = None
        elif fault == "empty":
            entries[0]["digest"] = ""
        elif fault == "wrong":
            entries[0]["digest"] = "sha256:" + "0" * 64
        elif fault == "duplicate":
            entries.append(entries[0])
        return {"assets": entries, "html_url": "https://example.com/release"}

    commands = Mock()
    commands.check_output.return_value = '{"body":"changes"}'
    namespace = {"hashlib": hashlib, "json": json, "subprocess": commands,
                 "preflight": Mock(return_value=None), "find_release": Mock(return_value=draft),
                 "verify_assets": Mock(return_value="checksums"), "gh_json": remote}
    exec(compile(ast.Module(body=[publish], type_ignores=[]), str(path), "exec"), namespace)
    args = ("example/repo", manifest, assets, metadata, "https://example.com/run", True)
    if fault is None:
        namespace["publish"](*args)
        assert "--draft=false" in commands.run.call_args.args[0]
    else:
        with pytest.raises(ValueError, match="asset (digest mismatch|set is incomplete)"):
            namespace["publish"](*args)
        assert all("--draft=false" not in c.args[0] for c in commands.run.call_args_list)
