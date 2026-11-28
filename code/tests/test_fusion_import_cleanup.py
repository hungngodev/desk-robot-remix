"""Exercise Fusion document ownership without a licensed Fusion installation."""
import runpy
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "docs/cad/remixes/fusion_one_robot_scaffold.py"


@pytest.fixture
def fusion(monkeypatch, tmp_path):
    run = runpy.run_path(str(SCRIPT))["run"]
    namespace = run.__globals__
    monkeypatch.setitem(namespace, "find_repo", lambda _: tmp_path)
    monkeypatch.setitem(namespace, "verify_original_source_revisions", lambda _: None)
    monkeypatch.setitem(namespace, "jaw_topology_warning", lambda _: "jaw HOLD")
    monkeypatch.setitem(namespace, "verify_optional_fit_references", lambda _: None)
    monkeypatch.setitem(namespace, "build_manifest", lambda _: [
        ("first", tmp_path / "first.stl"), ("second", tmp_path / "second.stl"),
    ])
    prior = Mock(name="existing_document")
    created = Mock(name="new_document")
    mesh_add = Mock(return_value=SimpleNamespace(count=1))
    occurrences = SimpleNamespace(addNewComponent=lambda _: SimpleNamespace(
        component=SimpleNamespace(meshBodies=SimpleNamespace(add=mesh_add)),
    ))
    design = SimpleNamespace(rootComponent=SimpleNamespace(occurrences=occurrences))
    app = SimpleNamespace(activeDocument=prior, activeProduct=design,
                          userInterface=SimpleNamespace(messageBox=Mock()))

    def add_document(_):
        app.activeDocument = created
        return created

    def close_document(_):
        app.activeDocument = prior
        return True

    created.close.side_effect = close_document
    app.documents = SimpleNamespace(add=Mock(side_effect=add_document))
    adsk = ModuleType("adsk")
    adsk.core = ModuleType("adsk.core")
    adsk.fusion = ModuleType("adsk.fusion")
    adsk.core.Application = SimpleNamespace(get=lambda: app)
    adsk.core.DocumentTypes = SimpleNamespace(FusionDesignDocumentType=object())
    adsk.core.Matrix3D = SimpleNamespace(create=object)
    adsk.fusion.Design = SimpleNamespace(cast=Mock(return_value=design))
    adsk.fusion.DesignTypes = SimpleNamespace(DirectDesignType=object())
    adsk.fusion.MeshUnits = SimpleNamespace(MillimeterMeshUnit=object())
    for module in (adsk, adsk.core, adsk.fusion):
        monkeypatch.setitem(sys.modules, module.__name__, module)
    return SimpleNamespace(run=run, namespace=namespace, prior=prior, created=created,
                           mesh_add=mesh_add, app=app, cast=adsk.fusion.Design.cast)


@pytest.mark.parametrize("failure", ["exception", "empty", "design"])
def test_failed_import_closes_only_created_document(fusion, failure):
    if failure == "design":
        fusion.cast.return_value = None
    else:
        second = RuntimeError("second import failed") if failure == "exception" else None
        fusion.mesh_add.side_effect = [SimpleNamespace(count=1), second]
    fusion.run(None)
    fusion.created.close.assert_called_once_with(False)
    fusion.prior.close.assert_not_called()
    assert fusion.app.activeDocument is fusion.prior
    assert fusion.mesh_add.call_count == (0 if failure == "design" else 2)
    assert "Fusion import failure" in fusion.app.userInterface.messageBox.call_args.args[0]


def test_invalid_packaging_never_creates_document(fusion, monkeypatch):
    monkeypatch.setitem(fusion.namespace, "verify_optional_fit_references", lambda _: {})
    fusion.run(None)
    fusion.app.documents.add.assert_not_called()
    fusion.prior.close.assert_not_called()
    fusion.created.close.assert_not_called()
    assert fusion.app.activeDocument is fusion.prior
    message = fusion.app.userInterface.messageBox.call_args.args[0]
    assert "Unverified Fusion power fit scope" in message


def test_success_keeps_created_document_open(fusion):
    fusion.run(None)
    fusion.created.close.assert_not_called()
    fusion.prior.close.assert_not_called()
    assert fusion.app.activeDocument is fusion.created
    assert fusion.mesh_add.call_count == 2
    assert "Imported 2" in fusion.app.userInterface.messageBox.call_args.args[0]


@pytest.mark.parametrize("close_failure", [False, RuntimeError("close failed")])
def test_cleanup_failure_preserves_original_error(fusion, close_failure):
    fusion.mesh_add.side_effect = RuntimeError("mesh failed")
    if isinstance(close_failure, Exception):
        fusion.created.close.side_effect = close_failure
    else:
        fusion.created.close.side_effect = None
        fusion.created.close.return_value = close_failure
    fusion.run(None)
    fusion.created.close.assert_called_once_with(False)
    fusion.prior.close.assert_not_called()
    message = fusion.app.userInterface.messageBox.call_args.args[0]
    assert "mesh failed" in message
    assert "cleanup" in message
