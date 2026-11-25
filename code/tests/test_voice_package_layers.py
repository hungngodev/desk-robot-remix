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
