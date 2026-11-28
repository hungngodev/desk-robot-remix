"""Physical MG90S fit coupons must reject misleading printable geometry."""
import importlib.util
import shutil
import subprocess
from collections import Counter
from math import fsum, isfinite, ldexp
from pathlib import Path
from struct import pack, unpack_from

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCAD = ROOT / "docs/cad/remixes/mg90s_pocket_fit_gauges.scad"


def _expected_cup_volume(clearance_mm: float, mark_count: int) -> float:
    return (
        28.0 * 17.2 * 8.0
        - (23.0 + clearance_mm) * (12.2 + clearance_mm) * 6.0
        + mark_count * 1.5 * 0.6 * 2.5
    )


def _split_closed_stl_shells(blob: bytes) -> list[dict]:
    """Split a multi-solid binary STL into closed, manifold shells."""
    assert len(blob) >= 84
    triangles = unpack_from("<I", blob, 80)[0]
    assert triangles > 0 and len(blob) == 84 + triangles * 50
    parents = list(range(triangles))
    first_face_for_edge = {}
    incidence = Counter()
    winding = Counter()
    face_points = []
    face_scaled_volumes = []

    def root(face: int) -> int:
        while parents[face] != face:
            parents[face] = parents[parents[face]]
            face = parents[face]
        return face

    for index in range(triangles):
        offset = 84 + 50 * index + 12
        pts = tuple(
            unpack_from("<fff", blob, offset + 12 * corner) for corner in range(3)
        )
        assert len(set(pts)) == 3
        assert all(isfinite(coord) for pt in pts for coord in pt)
        face_points.append(pts)
        a, b, c = pts
        face_scaled_volumes.append(
            a[0] * (b[1] * c[2] - b[2] * c[1])
            + a[1] * (b[2] * c[0] - b[0] * c[2])
            + a[2] * (b[0] * c[1] - b[1] * c[0])
        )
        sa, sb, sc = (
            tuple(int(ldexp(val, 149)) for val in pt) for pt in pts
        )
        ab = tuple(sb[k] - sa[k] for k in range(3))
        ac = tuple(sc[k] - sa[k] for k in range(3))
        normal = (
            ab[1] * ac[2] - ab[2] * ac[1],
            ab[2] * ac[0] - ab[0] * ac[2],
            ab[0] * ac[1] - ab[1] * ac[0],
        )
        assert any(normal)
        for corner in range(3):
            u, v = pts[corner], pts[(corner + 1) % 3]
            edge = (u, v) if u < v else (v, u)
            other = first_face_for_edge.setdefault(edge, index)
            parents[root(index)] = root(other)
            incidence[edge] += 1
            winding[edge] += 1 if u < v else -1

    assert all(count == 2 for count in incidence.values())
    assert all(delta == 0 for delta in winding.values())

    grouped: dict[int, list[int]] = {}
    for index in range(triangles):
        grouped.setdefault(root(index), []).append(index)

    shells = []
    for face_indices in grouped.values():
        verts = [pt for idx in face_indices for pt in face_points[idx]]
        mins = tuple(round(min(p[axis] for p in verts), 3) for axis in range(3))
        maxs = tuple(round(max(p[axis] for p in verts), 3) for axis in range(3))
        dims = tuple(round(maxs[axis] - mins[axis], 2) for axis in range(3))
        volume = fsum(face_scaled_volumes[idx] for idx in face_indices) / 6.0
        assert volume > 0
        shells.append({
            "vertices": verts,
            "mins": mins,
            "maxs": maxs,
            "dims": dims,
            "volume": volume,
        })
    shells.sort(key=lambda shell: shell["mins"][0])
    return shells


def _verify_four_cup_stl_geometry(blob: bytes) -> None:
    """Validate all 4 separated cups' bounds, pocket corners, ticks, and volumes."""
    shells = _split_closed_stl_shells(blob)
    assert len(shells) == 4
    clearances = (0.15, 0.30, 0.45, 0.60)
    for idx, (shell, clearance_mm) in enumerate(zip(shells, clearances, strict=True)):
        mark_count = idx + 1
        x_offset = idx * 36.0
        assert shell["mins"] == pytest.approx((x_offset, -0.6, 0.0), abs=0.01)
        assert shell["dims"] == (28.0, 17.8, 8.0)
        if idx > 0:
            gap = shell["mins"][0] - shells[idx - 1]["maxs"][0]
            assert gap == pytest.approx(8.0, abs=0.01)
        pocket_offset = 2.5 - clearance_mm / 2
        verts = shell["vertices"]
        for x_local in (pocket_offset, 28.0 - pocket_offset):
            for y_local in (pocket_offset, 17.2 - pocket_offset):
                assert any(
                    abs(x - (x_offset + x_local)) < 0.002
                    and abs(y - y_local) < 0.002
                    and abs(z - 2.0) < 0.002
                    for x, y, z in verts
                )
        marked_edges = sorted({
            round(x - x_offset, 2) for x, y, _ in verts if abs(y + 0.6) < 0.002
        })
        expected_ticks = sorted(
            round(4 + 2.45 * tick + edge, 2)
            for tick in range(mark_count) for edge in (0, 1.5)
        )
        assert marked_edges == expected_ticks
        assert shell["volume"] == pytest.approx(
            _expected_cup_volume(clearance_mm, mark_count), abs=0.02,
        )


def _cup_box_triangles(x0, y0, z0, x1, y1, z1):
    """Outward-oriented triangles for an axis-aligned box."""
    corners = [
        (x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
        (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1),
    ]
    quads = [
        (0, 3, 2, 1), (4, 5, 6, 7),
        (0, 1, 5, 4), (2, 3, 7, 6),
        (0, 4, 7, 3), (1, 2, 6, 5),
    ]
    tris = []
    for a, b, c, d in quads:
        tris.append((corners[a], corners[b], corners[c]))
        tris.append((corners[a], corners[c], corners[d]))
    return tris


def _encode_binstl(tris) -> bytes:
    out = bytearray(b"synthetic" + b"\x00" * 71 + pack("<I", len(tris)))
    for a, b, c in tris:
        out.extend(pack("<12fH", 0.0, 0.0, 0.0, *a, *b, *c, 0))
    return bytes(out)


def test_four_cup_validator_rejects_filled_pockets_even_when_outer_bounds_match():
    """Host geometric guard catches filled-pocket coupons without OpenSCAD CLI."""
    tris = []
    for idx in range(4):
        x0 = idx * 36.0
        # Same outer shell dimensions as cups, but pocket completely filled.
        tris.extend(_cup_box_triangles(x0, -0.6, 0.0, x0 + 28.0, 17.2, 8.0))
    with pytest.raises(AssertionError):
        _verify_four_cup_stl_geometry(_encode_binstl(tris))


@pytest.mark.skipif(shutil.which("openscad") is None, reason="Needs OpenSCAD CLI")
def test_nominal_mg90s_four_cups_preserve_printable_bounds(tmp_path):
    output = tmp_path / "mg90s_four_cups.stl"
    result = subprocess.run([
        "openscad", "--export-format", "binstl",
        "-o", str(output), str(SCAD),
    ], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    blob = output.read_bytes()
    _verify_four_cup_stl_geometry(blob)
    count = unpack_from("<I", blob, 80)[0]
    assert count > 0 and len(blob) == 84 + count * 50
    vertices = [
        unpack_from("<fff", blob, 84 + 50 * i + 12 + corner * 12)
        for i in range(count) for corner in range(3)
    ]
    bounds = tuple(
        round(max(p[axis] for p in vertices) -
              min(p[axis] for p in vertices), 2)
        for axis in range(3)
    )
    assert bounds == (136.0, 17.8, 8.0)


@pytest.mark.skipif(shutil.which("openscad") is None, reason="Needs OpenSCAD CLI")
@pytest.mark.parametrize("override,reason", [
    ("clearances_mm=[1.2]", "insufficient printable wall"),
    ("clearances_mm=[0.15,-0.30,0.45,0.6]", "must be measured and positive"),
    ("clearances_mm=[0.15,0.30,0.45,1.6]", "must be measured and positive"),
    ("clearances_mm=[0.15,0.30,0.45,1.2]", "insufficient printable wall"),
    ("clearances_mm=[0.15,0.30,0.30,0.60]", "must be strictly increasing"),
    ("clearances_mm=[0.30,0.15]", "must be strictly increasing"),
    ("clearances_mm=[]", "coupon count must be bounded"),
    ('part="unknown"', "Unknown MG90S fit coupon"),
    ("spacing_mm=0", "printable separation"),
    ("total_height_mm=2.1", "total_height_mm >= (floor_mm + 3)"),
    ("wall_mm=2", "insufficient printable wall"),
])
def test_mg90s_invalid_overrides_cannot_print_misleading_coupons(
    tmp_path, override, reason,
):
    output = tmp_path / "bad.stl"
    result = subprocess.run([
        "openscad", "--export-format", "binstl", "-o", str(output),
        "-D", override, str(SCAD),
    ], capture_output=True, text=True, timeout=120)
    assert result.returncode != 0, result.stderr
    assert not output.exists(), "Invalid override left an STL artifact"
    assert any(
        line.startswith("ERROR: Assertion") and reason in line
        for line in result.stderr.splitlines()
    ), result.stderr


@pytest.mark.skipif(shutil.which("openscad") is None, reason="Needs OpenSCAD CLI")
@pytest.mark.parametrize("part,mark_count,clearance_mm", [
    ("mg90s_fit_015", 1, 0.15),
    ("mg90s_fit_030", 2, 0.30),
    ("mg90s_fit_045", 3, 0.45),
    ("mg90s_fit_060", 4, 0.60),
])
def test_named_mg90s_coupons_have_integral_clearance_ticks(
    tmp_path, part, mark_count, clearance_mm,
):
    """Printed cups remain identifiable after separation from STL filenames."""
    output = tmp_path / (part + ".stl")
    result = subprocess.run([
        "openscad", "--export-format", "binstl", "-o", str(output),
        "-D", f'part="{part}"', str(SCAD),
    ], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    blob = output.read_bytes()
    triangles = unpack_from("<I", blob, 80)[0]
    assert triangles > 0 and len(blob) == 84 + triangles * 50
    vertices = [
        unpack_from("<fff", blob, 84 + 50 * i + 12 + corner * 12)
        for i in range(triangles) for corner in range(3)
    ]
    bounds = tuple(
        round(max(p[axis] for p in vertices) -
              min(p[axis] for p in vertices), 2)
        for axis in range(3)
    )
    # No extra bottom mass or pocket enlargement. Only the external
    # identification ticks protrude 0.6 mm beyond the original Y wall.
    assert bounds == (28.0, 17.8, 8.0)
    marked_edges = sorted({
        round(x, 2) for x, y, _ in vertices if abs(y + 0.6) < 0.002
    })
    expected = sorted(
        round(4 + 2.45 * tick + edge, 2)
        for tick in range(mark_count) for edge in (0, 1.5)
    )
    assert marked_edges == expected
    pocket_offset = 2.5 - clearance_mm / 2
    for x_expected in (pocket_offset, 28.0 - pocket_offset):
        for y_expected in (pocket_offset, 17.2 - pocket_offset):
            assert any(
                abs(x - x_expected) < 0.002
                and abs(y - y_expected) < 0.002
                and abs(z - 2.0) < 0.002
                for x, y, z in vertices
            )
    # Bounding boxes and a pocket corner can miss a fused obstruction.
    # Integrate the oriented surface; the closed shell must enclose only
    # the outer block minus the open pocket plus the exposed tick material.
    six_volume = fsum(
        a[0] * (b[1] * c[2] - b[2] * c[1])
        + a[1] * (b[2] * c[0] - b[0] * c[2])
        + a[2] * (b[0] * c[1] - b[1] * c[0])
        for a, b, c in zip(vertices[::3], vertices[1::3], vertices[2::3], strict=True)
    )
    expected_volume = (
        28.0 * 17.2 * 8.0
        - (23.0 + clearance_mm) * (12.2 + clearance_mm) * 6.0
        + mark_count * 1.5 * 0.6 * 2.5
    )
    assert six_volume / 6 == pytest.approx(expected_volume, abs=0.01)
    # The protrusions must fuse to the cup rather than creating loose
    # separate islands which the printer could silently omit.
    verifier = ROOT / "code/scripts/export_fit_kit.py"
    spec = importlib.util.spec_from_file_location("mg90s_fit_verifier", verifier)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.closed_mesh_edges(output) > 0
