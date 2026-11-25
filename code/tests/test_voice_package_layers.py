"""Voice orchestration must not depend on HTTP route registration."""
import subprocess
import sys
from pathlib import Path


def test_pet_import_keeps_http_routes_out_of_domain_layer():
    # Run in a fresh interpreter: pytest may already have imported the API.
    source = Path(__file__).resolve().parents[1] / "laptop" / "src"
    program = """
import sys
sys.path.insert(0, sys.argv[1])
import desk_robot.pet
routes = sorted(
    name for name in sys.modules
    if name == "desk_robot.api" or name.startswith("desk_robot.api_")
)
assert not routes, routes
"""
    result = subprocess.run(
        [sys.executable, "-c", program, str(source)],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_pet_and_http_routes_share_sensor_provenance_validation():
    from desk_robot import api_robot_status, aux, pet

    assert pet._aux_boot_epoch is api_robot_status._aux_boot_epoch is aux._aux_boot_epoch
    assert (
        pet._fresh_aux_acquisition
        is api_robot_status._fresh_aux_acquisition
        is aux._fresh_aux_acquisition
    )


def test_dock_and_grasp_operations_do_not_load_motion_coordinator():
    # Exercise the deferred call sites, not merely the module import.
    source = Path(__file__).resolve().parents[1] / "laptop" / "src"
    program = """
import asyncio
import sys
import time
from types import SimpleNamespace

sys.path.insert(0, sys.argv[1])
from desk_robot import dock_runtime, grasp_feedback

async def verify(receipt):
    return None

async def health():
    return {"servo": {"attached": True, "position_source": "commanded",
                      "grip_target": 60, "grip": 60}}

async def main():
    head = SimpleNamespace(dock_receipt_current=verify)
    receipt = (b"jpeg", time.monotonic(), (1, 1, 1), 1)
    await dock_runtime.verify_selected_dock_frame(head, receipt)
    await grasp_feedback.await_commanded_jaw_target(health, 60)

asyncio.run(main())
assert "desk_robot.controller" not in sys.modules
"""
    result = subprocess.run(
        [sys.executable, "-c", program, str(source)],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_shared_operation_contract_retains_controller_compatibility():
    from desk_robot import controller, dock_runtime, grasp_feedback, multimodal, operations, pet

    for module in (controller, dock_runtime, grasp_feedback, multimodal, pet):
        assert module._bounded_head_reply is operations._bounded_head_reply
    assert controller.OperationError is grasp_feedback.OperationError is operations.OperationError
