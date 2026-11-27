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


@pytest.mark.parametrize("threshold", [float("nan"), float("inf"), -float("inf"), 0, -1, 256,
                                      True, 16.0])
def test_invalid_threshold_rejected(threshold):
    baseline = bytes([100]) * (64 * 48)
    with pytest.raises(ValueError, match="threshold"):
        scene_change_mask(baseline, baseline, threshold=threshold)
    with pytest.raises(ValueError, match="threshold"):
        change_fraction(baseline, baseline, threshold=threshold)


@pytest.mark.parametrize("threshold", [1, 255])
def test_threshold_endpoints_preserve_signed_residuals(threshold):
    baseline = bytes(64 * 48)
    changed = bytes([255]) + baseline[1:]
    mask = scene_change_mask(baseline, changed, threshold=threshold)
    assert mask == bytes([1]) + baseline[1:]
    assert change_fraction(baseline, changed, threshold=threshold) == 1 / len(mask)


@pytest.mark.parametrize("invalid", [
    bytearray(64 * 48), memoryview(bytes(64 * 48)), [True] * (64 * 48),
    [float("nan")] * (64 * 48), [float("inf")] * (64 * 48),
    [-1] * (64 * 48), [256] * (64 * 48), None,
])
def test_fingerprints_require_immutable_bytes(invalid):
    baseline = bytes(64 * 48)
    for score in (scene_change_mask, change_fraction):
        with pytest.raises(ValueError, match="immutable bytes"):
            score(invalid, baseline)
        with pytest.raises(ValueError, match="immutable bytes"):
            score(baseline, invalid)


@pytest.mark.parametrize("invalid", [b"", b"\x00", bytes(64 * 48 + 1)])
def test_fingerprint_dimensions_rejected(invalid):
    baseline = bytes(64 * 48)
    with pytest.raises(ValueError, match="dimensions"):
        scene_change_mask(invalid, baseline)
    with pytest.raises(ValueError, match="dimensions"):
        scene_change_mask(invalid, invalid)


@pytest.mark.parametrize("invalid", [b"\x03", b"\xff", bytearray(b"\x01"), [True]])
def test_invalid_mask_cannot_count_as_persistent_motion(invalid):
    with pytest.raises(ValueError, match="signed change mask"):
        consistent_change_mask(invalid, invalid)
    with pytest.raises(ValueError, match="signed change mask"):
        consistent_change_mask(None, invalid)
    with pytest.raises(ValueError, match="signed change mask"):
        consistent_change_mask(invalid, b"\x01")


def test_mask_dimensions_and_empty_overlap():
    with pytest.raises(ValueError, match="dimensions"):
        consistent_change_mask(b"\x01", b"\x01\x02")
    assert not consistent_change_mask(b"", b"")
