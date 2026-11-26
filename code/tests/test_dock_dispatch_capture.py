from types import SimpleNamespace

import desk_robot.controller as controller
import pytest
from desk_robot.controller import Coordinator, Job


def test_dock_dispatch_checks_keep_attempt_evidence(monkeypatch):
    checked = []
    expired = set()

    def unpack(observation):
        checked.append(("camera", observation))
        if observation in expired:
            raise ValueError("expired")

    def validate(reading, robot_id, *, expected_dock_id, elapsed_ms):
        checked.append(("ir", reading, robot_id, expected_dock_id, elapsed_ms))

    monkeypatch.setattr(controller, "unpack_dock_frame", unpack)
    monkeypatch.setattr(controller, "validate_motion_ir", validate)
    monkeypatch.setattr(controller, "time", SimpleNamespace(monotonic=lambda: 10.0))
    coordinator = SimpleNamespace(
        _require_camera_motion_grant=lambda grant: checked.append(("grant", grant)),
        dock_inhibited=lambda robot_id: False,
    )
    head = SimpleNamespace(
        dock_receipt_current_now=lambda observation: checked.append(("boot", observation)),
    )
    job = Job("job", "pet", "dock")
    checks = []
    for index in (1, 2):
        checks.append(Coordinator._dock_dispatch_checks(
            coordinator, job, head, camera_grant=index, expected_dock=7,
            observation=index, reading=index, ir_request_at=10.0 - index / 8,
        ))

    checks[0][1]()
    assert checked == [
        ("grant", 1), ("camera", 1), ("ir", 1, "pet", 7, 125.0), ("boot", 1),
    ]
    checked.clear()
    expired.add(1)
    with pytest.raises(controller._DockCameraQueueExpired, match="expired"):
        checks[0][1]()
    assert checked == [("grant", 1), ("camera", 1)]
    checked.clear()
    checks[1][1]()
    assert checked == [
        ("grant", 2), ("camera", 2), ("ir", 2, "pet", 7, 250.0), ("boot", 2),
    ]
