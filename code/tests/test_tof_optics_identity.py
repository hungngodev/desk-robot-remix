import pytest
from desk_robot.tof_optics import validate_optics


def sample():
    return {
        'robot_id': 'robot-01',
        'optics': {
            'ambient_97': [0] * 8, 'signal_97': [32] + [0] * 7, 'age_ms': [0] * 8,
            'present_mask': 1, 'valid_mask': 1,
            'physical_qualified': False, 'motor_authorized': False,
        },
    }


@pytest.mark.parametrize(
    ('reported', 'expected'),
    [(None, None), (True, 1), (1, True), ([], []), ('', ''), (' ', ' ')],
)
def test_noncanonical_robot_identity_rejected(reported, expected):
    data = sample()
    data['robot_id'] = reported
    with pytest.raises(ValueError, match='robot identity mismatch'):
        validate_optics(data, expected)


def test_missing_robot_identity_rejected():
    data = sample()
    del data['robot_id']
    with pytest.raises(ValueError, match='robot identity mismatch'):
        validate_optics(data, None)


def test_optics_receipt_detaches_from_input_and_other_receipts():
    data = sample()
    first = validate_optics(data, 'robot-01')
    data['optics']['signal_97'][0] = 33
    second = validate_optics(data, 'robot-01')
    assert first['optics']['signal_97'][0] == 32
    assert second['optics']['signal_97'][0] == 33
    first['optics']['valid_mask'] = 0
    assert second['optics']['valid_mask'] == 1
