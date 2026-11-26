"""Seeded SE(2) properties, not physical localization qualification."""

import cmath
import math
import random

import pytest
from desk_robot.spatial_frames import FrameError, PlanarTransform, map_odom_transform


@pytest.mark.parametrize("seed", [740, 741, 742, 743])
def test_rigid_transform_properties(seed):
    rng = random.Random(seed)
    for index in range(256):
        yaw = rng.uniform(-math.pi, math.pi)
        if index < 5:
            yaw = (-math.pi, -math.pi / 2, 0, math.pi / 2, math.pi)[index]
        other_yaw = rng.uniform(-math.pi, math.pi)
        a = complex(rng.uniform(-200_000, 200_000), rng.uniform(-200_000, 200_000))
        b = complex(rng.uniform(-200_000, 200_000), rng.uniform(-200_000, 200_000))
        p = complex(rng.uniform(-100_000, 100_000), rng.uniform(-100_000, 100_000))
        ab = PlanarTransform("map", "odom", a.real, a.imag, yaw)
        bc = PlanarTransform("odom", "base_link", b.real, b.imag, other_yaw)
        ba = ab.inverse()
        assert (ba.parent, ba.child) == ("odom", "map")
        assert ab.compose(ba) == PlanarTransform("map", "map", 0, 0, 0)
        assert ba.compose(ab) == PlanarTransform("odom", "odom", 0, 0, 0)
        expected = a + cmath.exp(1j * yaw) * p
        assert complex(*ab.point(p.real, p.imag)) == pytest.approx(expected, abs=1e-8, rel=0)
        assert complex(*ba.point(expected.real, expected.imag)) == pytest.approx(
            p, abs=1e-8, rel=0,
        )
        ac = ab.compose(bc)
        expected_chain = a + cmath.exp(1j * yaw) * (b + cmath.exp(1j * other_yaw) * p)
        assert complex(*ac.point(p.real, p.imag)) == pytest.approx(
            expected_chain, abs=1e-8, rel=0,
        )
        assert (ac.parent, ac.child) == ("map", "base_link")
        recovered = map_odom_transform(ac, bc)
        assert complex(recovered.x_mm, recovered.y_mm) == pytest.approx(a, abs=1e-8, rel=0)
        assert math.remainder(recovered.yaw_rad - yaw, math.tau) == pytest.approx(0, abs=1e-12)


def test_inverse_and_composition_do_not_expand_coordinate_domain():
    # The inverse of an admissible pose can fall outside the bounded square.
    edge = PlanarTransform("map", "odom", 1_000_000, 1_000_000, math.pi / 4)
    with pytest.raises(FrameError):
        edge.inverse()
    step = PlanarTransform("odom", "base_link", 1, 0, 0)
    boundary = PlanarTransform("map", "odom", 1_000_000, 0, 0)
    with pytest.raises(FrameError):
        boundary.compose(step)
    assert boundary.compose(boundary.inverse()) == PlanarTransform("map", "map", 0, 0, 0)
