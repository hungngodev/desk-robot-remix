"""Render an explicitly unqualified layout from saved CAD, using Blender only.

Run in a NEW background Blender process, never in the user's live scene.
No source mesh is repaired, rescaled in its own file, or exported as printable CAD.
The chassis STL is provisionally interpreted as mm; the head 3MF declares mm.
Orange parts and all track geometry are illustrative envelopes, not print files.
"""

import argparse
import hashlib
import json
import math
import re
import struct
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser()
parser.add_argument("--head", choices=("eva", "sparky"), default="sparky")
args = parser.parse_args(sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else [])
OUT = ROOT / (
    "docs/cad/concepts/2026-11-03-rounded" if args.head == "sparky" else "docs/cad/concepts/2026-11-03"
)
OUT.mkdir(parents=True, exist_ok=True)
scene = bpy.data.scenes.new("DeskRobot_Concept_Only")
bpy.context.window.scene = scene
bpy.context.preferences.filepaths.save_version = 0  # Owned background preview, no .blend1 copies.
scene.unit_settings.system = "METRIC"
scene.unit_settings.scale_length = 1.0  # All vertex coordinates below are metres.
scene.render.engine = "BLENDER_WORKBENCH"
scene.render.resolution_x = 1440
scene.render.resolution_y = 1050
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
scene.render.film_transparent = False
scene.display.shading.light = "STUDIO"
scene.display.shading.studiolight_rotate_z = math.radians(25)
scene.display.shading.color_type = "MATERIAL"
scene.display.shading.show_shadows = True
scene.display.shading.show_cavity = True
scene.display.shading.cavity_type = "BOTH"
scene.display.shading.curvature_ridge_factor = 1.25
scene.display.shading.curvature_valley_factor = 1.0
scene.display.shading.show_specular_highlight = True
scene.display.shading.background_type = "WORLD"
scene.world = bpy.data.worlds.new("DeskRobot_Preview_World")
scene.world.color = (0.91, 0.93, 0.95)
scene.view_settings.view_transform = "Standard"

collections = {}
for name in ("SOURCE_CAD", "LAYOUT_PLACEHOLDERS", "REVIEW"):
    c = bpy.data.collections.new(name)
    scene.collection.children.link(c)
    collections[name] = c


def material(name, rgb):
    m = bpy.data.materials.new(name)
    m.diffuse_color = (*rgb, 1)
    return m


ivory = material("Source head: ivory", (0.82, 0.84, 0.78))
teal = material("Source chassis: teal", (0.13, 0.47, 0.43))
orange = material("Unqualified mechanism/sensor positions", (0.98, 0.45, 0.16))
rubber = material("Schematic tracks", (0.13, 0.16, 0.20))
wheelmat = material("Schematic wheel hubs", (0.42, 0.47, 0.51))
black = material("Display and camera envelope", (0.025, 0.04, 0.06))
white = material("Monochrome eyes", (0.99, 0.99, 0.99))
ink = material("Annotation", (0.10, 0.17, 0.23))
muted = material("Annotation secondary", (0.34, 0.40, 0.46))
groundmat = material("Ground", (0.85, 0.88, 0.90))


def mesh(name, verts_mm, faces, mat, collection="SOURCE_CAD"):
    data = bpy.data.meshes.new(name + "_mesh")
    data.from_pydata([tuple(v / 1000 for v in p) for p in verts_mm], [], faces)
    data.update()
    obj = bpy.data.objects.new(name, data)
    collections[collection].objects.link(obj)
    obj.data.materials.append(mat)
    return obj


sources = []


def source_record(path):
    sources.append(
        {
            "path": str(path.relative_to(ROOT)),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    )


def stl(path, name, mat):
    source_record(path)
    data = path.read_bytes()
    verts, faces = [], []
    count = struct.unpack_from("<I", data, 80)[0] if len(data) >= 84 else -1
    if len(data) == 84 + count * 50:
        for i in range(count):
            values = struct.unpack_from("<12fH", data, 84 + 50 * i)
            n = len(verts)
            verts.extend([values[3:6], values[6:9], values[9:12]])
            faces.append((n, n + 1, n + 2))
    else:
        verts = [
            tuple(map(float, v))
            for v in re.findall(rb"vertex\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)", data)
        ]
        faces = [(n, n + 1, n + 2) for n in range(0, len(verts), 3)]
    if not verts or len(verts) % 3 != 0:
        raise ValueError(f"STL must contain complete triangles: {path}")
    lo = [min(v[a] for v in verts) for a in range(3)]
    hi = [max(v[a] for v in verts) for a in range(3)]
    verts = [(v[0] - (lo[0] + hi[0]) / 2, v[1] - (lo[1] + hi[1]) / 2, v[2] - lo[2]) for v in verts]
    return mesh(name, verts, faces, mat), [hi[a] - lo[a] for a in range(3)]


chassis, chassis_dims = stl(
    ROOT / "docs/cad/originals/smars-stepper/SMARS_2BJY8-Chassis.stl",
    "SOURCE_Stepper_SMARS_Chassis",
    teal,
)
chassis.location.z = 0.005  # Illustration only, not an axle/ground datum.

if args.head == "sparky":
    shell, head_dims = stl(
        ROOT / "docs/cad/originals/sparky-head/sparky_shell.stl", "SOURCE_Sparky_v010_shell", ivory
    )
    shell.location = (0, -0.007, 0.050)
else:
    # Head front is source x=-9, not its 74-mm dimension. Rotate long axis to rover Y.
    headpath = ROOT / "docs/cad/originals/eva-head/EVA-Robot.3mf"
    source_record(headpath)
    with zipfile.ZipFile(headpath) as z:
        root = ET.fromstring(z.read("3D/3dmodel.model"))
    ns = {"m": root.tag.split("}")[0][1:]}
    if root.attrib.get("unit") != "millimeter":
        raise ValueError(f"3MF must declare millimeter units: {headpath}")
    head_vertices = []
    for item in root.findall("./m:resources/m:object", ns):
        vertices = item.findall("./m:mesh/m:vertices/m:vertex", ns)
        if not vertices:
            continue
        verts = [
            (-float(v.attrib["y"]), float(v.attrib["x"]) - 28 + 2, float(v.attrib["z"]) - 11 + 50)
            for v in vertices
        ]
        # Rigid +90-degree rotation around Z; source dimensions/winding are preserved.
        faces = [
            (int(t.attrib["v1"]), int(t.attrib["v2"]), int(t.attrib["v3"]))
            for t in item.findall("./m:mesh/m:triangles/m:triangle", ns)
        ]
        mesh("SOURCE_EVA_" + item.attrib["id"], verts, faces, ivory)
        head_vertices.extend(verts)
    head_dims = [
        max(v[a] for v in head_vertices) - min(v[a] for v in head_vertices) for a in range(3)
    ]


def box(name, center, dims, mat, bevel=0):
    x, y, z = (v / 2 for v in dims)
    verts = [
        (-x, -y, -z),
        (x, -y, -z),
        (x, y, -z),
        (-x, y, -z),
        (-x, -y, z),
        (x, -y, z),
        (x, y, z),
        (-x, y, z),
    ]
    faces = [(3, 2, 1, 0), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    obj = mesh(name, verts, faces, mat, "LAYOUT_PLACEHOLDERS")
    obj.location = Vector(center) / 1000
    if bevel:
        modifier = obj.modifiers.new("Illustrative rounded edges", "BEVEL")
        modifier.width = bevel / 1000
        modifier.segments = 3
        obj.modifiers.new("Illustrative normals", "WEIGHTED_NORMAL")
    return obj


def cylinder(name, center, radius, depth, mat, axis="Z"):
    verts, faces = [], []
    for z in (-depth / 2, depth / 2):
        for i in range(48):
            a = math.tau * i / 48
            p = [radius * math.cos(a), radius * math.sin(a), z]
            if axis == "X":
                p = [p[2], p[0], p[1]]
            elif axis == "Y":
                p = [p[0], p[2], -p[1]]
            verts.append(p)
    faces.append(tuple(reversed(range(48))))
    faces.append(tuple(range(48, 96)))
    faces.extend((i, (i + 1) % 48, (i + 1) % 48 + 48, i + 48) for i in range(48))
    obj = mesh(name, verts, faces, mat, "LAYOUT_PLACEHOLDERS")
    obj.location = Vector(center) / 1000
    return obj


# Display opening is 35x19.6 mm; actual 0.96" active area is illustrated smaller.
face_y = -33.6 if args.head == "sparky" else -35.4
face_z = 80 if args.head == "sparky" else 81.8
box(
    "PLACEHOLDER_OLED_bezel",
    (0, face_y, face_z),
    (34.5, 1.2, 23.5 if args.head == "sparky" else 19),
    black,
    0.6,
)
for x in (-5.2, 5.2):
    box("PLACEHOLDER_white_eye", (x, face_y - 0.7, face_z), (6, 0.5, 9), white, 1.8)
cylinder(
    "PLACEHOLDER_camera_lens",
    (0, face_y, 54 if args.head == "sparky" else 61),
    1.9,
    1.4,
    black,
    "Y",
)
box("PLACEHOLDER_head_mount", (0, 3, 48), (22, 26, 5), orange, 1)

# Schematic track loops: NOT matching tooth pitch/axles or printable tracks.
for side in (-1, 1):
    x = side * 39
    for y in (-30, 30):
        cylinder("PLACEHOLDER_track_end", (x, y, 17), 17, 18, rubber, "X")
        cylinder("PLACEHOLDER_hub", (x + side * 9.2, y, 17), 10.5, 1.2, wheelmat, "X")
    box("PLACEHOLDER_track_core", (x, 0, 17), (18, 60, 34), rubber)
    for y in range(-27, 28, 6):
        box("PLACEHOLDER_track_tread", (x, y, 34.4), (19, 3, 1.7), rubber, 0.4)
    # Floor sensor bodies and orange ground dots are positions to qualify.
    for y in (-42, 42):
        box("PLACEHOLDER_down_sensor", (side * 27, y, 14), (9, 8, 3), orange, 0.7)
        cylinder("PLACEHOLDER_floor_footprint", (side * 27, y, 1), 3.0, 0.5, orange)

# Lift/claw is a plain envelope representing the existing Bluino/forklift intent.
# No joints/teeth/servo-pocket/mount compatibility is implied by this geometry.
for x in (-12, 12):
    box("PLACEHOLDER_lift_rail", (x, -49, 30), (4, 6, 47), orange, 0.7)
box("PLACEHOLDER_lift_carriage", (0, -54, 18), (30, 8, 9), orange, 1)
box("PLACEHOLDER_claw_servo", (0, -61, 18), (23, 12, 23), orange, 0.8)
for side in (-1, 1):
    jaw = box("PLACEHOLDER_claw_finger", (side * 16, -79, 9), (5, 27, 10), orange, 1)
    jaw.rotation_euler.z = side * math.radians(12)
    box("PLACEHOLDER_claw_tip", (side * 12, -92, 5), (8, 7, 4), orange, 0.6)
box("PLACEHOLDER_front_sensor", (0, -47, 40), (13, 5, 8), orange, 0.6)

# A representative target block, not a claim of key or candy pickup success.
box("ILLUSTRATIVE_light_object", (0, -89, 4), (15, 11, 7), ivory, 1.2)

# Power bank is deliberately not hidden inside an invented miniature enclosure.
# It is absent because its dimensions/weight are unknown; titles say this explicitly.
ground = box("REVIEW_ground", (0, 0, -2), (550, 550, 2), groundmat)
collections["LAYOUT_PLACEHOLDERS"].objects.unlink(ground)
collections["REVIEW"].objects.link(ground)
ground.hide_render = True  # Keep review labels clear of ground/shadow occlusion.

camera_data = bpy.data.cameras.new("REVIEW_camera")
camera = bpy.data.objects.new("REVIEW_camera", camera_data)
collections["REVIEW"].objects.link(camera)
scene.camera = camera
camera_data.type = "ORTHO"
camera_data.lens = 80
camera_data.clip_start = 0.001
camera_data.clip_end = 10


def aim(location, target, scale):
    camera.location = Vector(location) / 1000
    target = Vector(target) / 1000
    camera.rotation_euler = (target - camera.location).to_track_quat("-Z", "Y").to_euler()
    camera_data.ortho_scale = scale / 1000
    bpy.context.view_layer.update()


texts = []


def caption(body, u, v, size, mat=ink):
    data = bpy.data.curves.new("REVIEW_label", "FONT")
    data.body = body
    data.size = size / 1000
    data.align_y = "TOP_BASELINE"
    obj = bpy.data.objects.new("REVIEW_label", data)
    collections["REVIEW"].objects.link(obj)
    obj.data.materials.append(mat)
    q = camera.rotation_euler.to_quaternion()
    width = camera_data.ortho_scale
    height = width * scene.render.resolution_y / scene.render.resolution_x
    obj.location = camera.location + q @ Vector((u * width, v * height, -0.02))
    obj.rotation_euler = camera.rotation_euler
    texts.append(obj)


def clear_text():
    for obj in texts:
        bpy.data.objects.remove(obj, do_unlink=True)
    texts.clear()


views = [
    ("proposed-robot", (215, -280, 185), (0, -13, 42), 250),
    ("side-layout", (270, -8, 90), (0, -13, 43), 250),
    ("front-layout", (0, -300, 90), (0, -13, 43), 235),
    ("top-layout", (0, -13, 400), (0, -13, 0), 285),
]
for name, loc, target, scale in views:
    aim(loc, target, scale)
    caption(
        "ROUNDED HEAD  /  PROPOSED DESK PET"
        if args.head == "sparky"
        else "PROPOSED DESK PET  /  LAYOUT STUDY",
        -0.46,
        0.435,
        5.1,
    )
    caption(
        "Actual head + chassis meshes; mounts, tracks and claw are illustrative.",
        -0.46,
        0.385,
        2.55,
        muted,
    )
    caption(
        "Orange: unqualified positions/mechanism. Power bank not yet fitted.",
        -0.46,
        -0.408,
        2.8,
        ink,
    )
    caption(
        "NOT PRINT-READY  /  no mechanical fit, power or edge-stop validation",
        -0.46,
        -0.455,
        2.45,
        muted,
    )
    scene.render.filepath = str(OUT / (name + ".png"))
    bpy.ops.render.render(write_still=True)
    clear_text()

# Save native layout with clean hero camera and annotations. Originals stay unchanged.
aim(*views[0][1:])
caption("CONCEPT ONLY - source CAD plus illustrative envelopes", -0.46, 0.435, 4.3)
bpy.ops.wm.save_as_mainfile(filepath=str(OUT / "layout-study.blend"))
report = {
    "date": "2026-11-03",
    "blender_version": bpy.app.version_string,
    "render_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    "delivery": "concept_layout_only",
    "engine": "Blender Workbench studio light; material colors; cavity/shadows",
    "unit_system": "metres internally; EVA 3MF declares mm; Sparky source SCAD specifies mm; chassis STL assumed mm, not yet physically checked",
    "source_meshes": sources,
    "chassis_source_size": chassis_dims,
    "head_case": args.head,
    "head_oriented_size_mm": dict(zip(("width", "depth", "height"), head_dims, strict=True)),
    "head_source_note": "Sparky v0.1.0 shell only, original estimated/unprinted design; no whole-case scaling"
    if args.head == "sparky"
    else "EVA front source x=-9; long axis is depth, not face width",
    "illustrative_objects": "all tracks, lift/claw, mounts, lenses, OLED insert, sensors and target",
    "power_bank": "not modeled: dimensions, mass, capacity/current unknown",
    "physical_fit_verified": False,
    "print_exports": [],
    "remaining": [
        "mechanical assembly registration",
        "MG90S fit and flat-key reach",
        "sensor visibility and stopping envelope",
        "bank dimensions/mass/load",
        "slicer/fit coupon",
        "actual assembly and physical tests",
    ],
    "previews": [
        {
            "path": str((OUT / (v[0] + ".png")).relative_to(ROOT)),
            "sha256": hashlib.sha256((OUT / (v[0] + ".png")).read_bytes()).hexdigest(),
        }
        for v in views
    ],
}
(OUT / "evidence.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps({"status": "concept_only", "previews": len(views), "output": str(OUT)}))
