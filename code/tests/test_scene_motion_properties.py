"""Exercise scene scoring and signed persistence with only byte fingerprints."""
from itertools import product

import pytest
from desk_robot.scene_motion import change_fraction, consistent_change_mask, scene_change_mask


def test_signed_overlap_exhaustive():
    masks = [bytes(values) for values in product(range(3), repeat=4)]
    for previous, current in product(masks, repeat=2):
        old = {(index, sign) for index, sign in enumerate(previous) if sign}
        new = {(index, sign) for index, sign in enumerate(current) if sign}
        smaller = min(len(old), len(new))
        expected = bool(smaller and len(old & new) >= smaller / 2)
        assert consistent_change_mask(previous, current) == expected
    assert not consistent_change_mask(None, b"\x01")


@pytest.mark.parametrize("threshold", [1, 16, 18, 32])
@pytest.mark.parametrize("offset", [-20, 0, 20])
def test_uniform_exposure_and_localized_signed_delta(threshold, offset):
    baseline = bytes([100]) * (64 * 48)
    exposed = bytes([100 + offset]) * len(baseline)
    assert change_fraction(baseline, exposed, threshold=threshold) == 0
    changed = bytearray(exposed)
    changed[:16] = bytes([100 + offset + threshold]) * 16
    changed[16:32] = bytes([100 + offset - threshold]) * 16
    mask = scene_change_mask(baseline, bytes(changed), threshold=threshold)
    assert mask[:16] == bytes([1]) * 16
    assert mask[16:32] == bytes([2]) * 16
    assert not any(mask[32:])
    assert change_fraction(baseline, bytes(changed), threshold=threshold) == 32 / len(mask)
