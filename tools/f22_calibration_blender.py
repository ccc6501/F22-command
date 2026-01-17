# ============================================================
# GLB MEASURE + CALIBRATION DATUM (Blender Drop-in)
# Outputs:
#  1) JSON report with world bounds, polycounts, anchors, and a calibration basis
#  2) TXT summary for quick reading
#
# Usage:
#  1) Import your GLB
#  2) Add empties named: CAL_NOSE, CAL_TAIL, CAL_WING_L, CAL_WING_R (and optional CAL_TOP/CAL_BOT)
#  3) Paste this into Blender Text Editor and Run Script
# ============================================================

import bpy
import json
import os
from mathutils import Vector, Matrix
from datetime import datetime

# =========================
# USER SETTINGS
# =========================
REPORT_JSON_PATH = r"C:\Users\Chance\Desktop\f22_glb_report.json"
REPORT_TXT_PATH  = r"C:\Users\Chance\Desktop\f22_glb_report.txt"

USE_EVALUATED_MESH = True  # True = includes modifiers

# Anchor names (must match exactly)
ANCHORS_REQUIRED = {
    "nose": "CAL_NOSE",
    "tail": "CAL_TAIL",
    "wing_l": "CAL_WING_L",
    "wing_r": "CAL_WING_R",
}
ANCHORS_OPTIONAL = {
    "top": "CAL_TOP",
    "bot": "CAL_BOT",
}

# =========================
# HELPERS
# =========================
def iso_now():
    return datetime.now().isoformat(timespec="seconds")

def vec3(v: Vector):
    return [float(v.x), float(v.y), float(v.z)]

def unit_info():
    u = bpy.context.scene.unit_settings
    return {
        "system": u.system,
        "length_unit": u.length_unit,
        "scale_length": float(u.scale_length),
    }

def bbox_world(obj):
    corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    min_v = Vector((1e9, 1e9, 1e9))
    max_v = Vector((-1e9, -1e9, -1e9))
    for c in corners:
        min_v.x = min(min_v.x, c.x)
        min_v.y = min(min_v.y, c.y)
        min_v.z = min(min_v.z, c.z)
        max_v.x = max(max_v.x, c.x)
        max_v.y = max(max_v.y, c.y)
        max_v.z = max(max_v.z, c.z)
    return min_v, max_v

def mesh_stats(obj):
    deps = bpy.context.evaluated_depsgraph_get()
    eval_obj = obj.evaluated_get(deps) if USE_EVALUATED_MESH else obj
    mesh = eval_obj.to_mesh()
    mesh.calc_loop_triangles()

    stats = {
        "triangles": int(len(mesh.loop_triangles)),
        "vertices": int(len(mesh.vertices)),
        "edges": int(len(mesh.edges)),
        "faces": int(len(mesh.polygons)),
    }

    if USE_EVALUATED_MESH:
        eval_obj.to_mesh_clear()

    return stats

def gather_images(mat):
    images = set()
    if not mat or not mat.use_nodes or not mat.node_tree:
        return images
    for n in mat.node_tree.nodes:
        if n.type == "TEX_IMAGE" and getattr(n, "image", None):
            images.add(n.image.name)
    return images

def safe_normalize(v: Vector, fallback: Vector):
    if v.length < 1e-9:
        return fallback.copy()
    return v.normalized()

def find_anchor(name: str):
    obj = bpy.data.objects.get(name)
    if obj and obj.type == "EMPTY":
        return obj
    return None

def anchor_loc(name: str):
    obj = find_anchor(name)
    if not obj:
        return None
    return obj.matrix_world.translation.copy()

def compute_aircraft_basis(nose: Vector, tail: Vector, wing_l: Vector, wing_r: Vector,
                          top: Vector = None, bot: Vector = None):
    """
    Returns an orthonormal basis for the aircraft in WORLD coordinates:
      +X = right (from left wing to right wing)
      +Y = forward (tail -> nose)
      +Z = up (derived; optional top/bot improves accuracy)
    And a suggested datum origin.

    Origin strategy:
      - Default origin = nose (datum at nose tip)
      - Also provides centerline origin = midpoint(nose, tail)
    """
    # Forward: tail -> nose
    fwd = safe_normalize(nose - tail, Vector((0, 1, 0)))

    # Right: left wing -> right wing
    right = safe_normalize(wing_r - wing_l, Vector((1, 0, 0)))

    # Up:
    # If top/bot provided: use that vector
    if top is not None and bot is not None:
        up_hint = top - bot
    elif top is not None:
        # Use top relative to centerline
        up_hint = top - ((nose + tail) * 0.5)
    elif bot is not None:
        up_hint = ((nose + tail) * 0.5) - bot
    else:
        # Derive using cross products
        # Make up orthogonal to fwd and right
        up_hint = fwd.cross(right)

    up = safe_normalize(up_hint, Vector((0, 0, 1)))

    # Orthonormalize to remove any skew:
    # Make right orthogonal to fwd/up, then recompute up
    right = safe_normalize(right - fwd * right.dot(fwd), Vector((1, 0, 0)))
    up = safe_normalize(fwd.cross(right), Vector((0, 0, 1)))

    # Build rotation matrix columns (right, fwd, up) for world space
    # This means:
    #   world_vec = R * aircraft_local_vec
    R = Matrix((
        (right.x, fwd.x, up.x),
        (right.y, fwd.y, up.y),
        (right.z, fwd.z, up.z),
    ))

    # Origins
    origin_nose = nose.copy()
    origin_centerline = (nose + tail) * 0.5

    return {
        "origin_nose_world": origin_nose,
        "origin_centerline_world": origin_centerline,
        "axis_right_world": right,
        "axis_forward_world": fwd,
        "axis_up_world": up,
        "rotation_aircraft_to_world_3x3": R,
        # inverse is world->aircraft
        "rotation_world_to_aircraft_3x3": R.inverted(),
    }

def matrix3_to_list(m: Matrix):
    # m is 3x3
    return [
        [float(m[0][0]), float(m[0][1]), float(m[0][2])],
        [float(m[1][0]), float(m[1][1]), float(m[1][2])],
        [float(m[2][0]), float(m[2][1]), float(m[2][2])],
    ]

def world_to_aircraft_point(p_world: Vector, origin_world: Vector, R_world_to_aircraft: Matrix):
    # translate then rotate
    return R_world_to_aircraft @ (p_world - origin_world)

def pairwise_distances(anchor_points):
    items = list(anchor_points.items())
    pairs = []
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            a_name, a_pt = items[i]
            b_name, b_pt = items[j]
            pairs.append({
                "a": a_name,
                "b": b_name,
                "distance_world": float((b_pt - a_pt).length),
            })
    return pairs

# =========================
# MAIN
# =========================
def main():
    print("=== START: GLB MEASURE + CALIBRATION DATUM ===")

    scene = bpy.context.scene
    objs = list(scene.objects)
    mesh_objs = [o for o in objs if o.type == "MESH"]
    empty_objs = [o for o in objs if o.type == "EMPTY"]

    # ---------- Model bounds + stats ----------
    all_bounds = []
    object_reports = []
    totals = {"triangles": 0, "vertices": 0, "edges": 0, "faces": 0}
    material_usage = {}
    image_usage = set()

    for o in mesh_objs:
        mn, mx = bbox_world(o)
        size = mx - mn
        center = (mn + mx) * 0.5

        stats = mesh_stats(o)
        for k in totals:
            totals[k] += stats[k]

        mats = []
        if o.data and hasattr(o.data, "materials") and o.data.materials:
            for m in o.data.materials:
                if m:
                    mats.append(m.name)
                    material_usage[m.name] = material_usage.get(m.name, 0) + 1
                    image_usage |= gather_images(m)

        object_reports.append({
            "name": o.name,
            "location_world": vec3(o.matrix_world.translation),
            "rotation_euler": [float(o.rotation_euler.x), float(o.rotation_euler.y), float(o.rotation_euler.z)],
            "scale": vec3(o.scale),
            "bounds_world": {
                "min": vec3(mn),
                "max": vec3(mx),
                "size": vec3(size),
                "center": vec3(center),
            },
            "mesh_stats": stats,
            "materials": sorted(set(mats)),
        })

        all_bounds.append(mn)
        all_bounds.append(mx)

    global_min = Vector((0, 0, 0))
    global_max = Vector((0, 0, 0))
    if all_bounds:
        global_min = Vector((1e9, 1e9, 1e9))
        global_max = Vector((-1e9, -1e9, -1e9))
        for v in all_bounds:
            global_min.x = min(global_min.x, v.x)
            global_min.y = min(global_min.y, v.y)
            global_min.z = min(global_min.z, v.z)
            global_max.x = max(global_max.x, v.x)
            global_max.y = max(global_max.y, v.y)
            global_max.z = max(global_max.z, v.z)

    global_size = global_max - global_min
    global_center = (global_min + global_max) * 0.5

    # ---------- Anchors ----------
    anchors_found = {}
    missing_required = []

    for key, nm in ANCHORS_REQUIRED.items():
        loc = anchor_loc(nm)
        if loc is None:
            missing_required.append(nm)
        else:
            anchors_found[key] = loc

    anchors_optional = {}
    for key, nm in ANCHORS_OPTIONAL.items():
        loc = anchor_loc(nm)
        if loc is not None:
            anchors_optional[key] = loc

    # Also include any CAL_* empties in a generic list
    cal_any = []
    for e in empty_objs:
        if e.name.startswith("CAL_"):
            cal_any.append({
                "name": e.name,
                "location_world": vec3(e.matrix_world.translation),
            })
    cal_any_sorted = sorted(cal_any, key=lambda x: x["name"])

    calibration = {
        "status": "ok" if not missing_required else "missing_required_anchors",
        "missing_required": missing_required,
        "required_names": ANCHORS_REQUIRED,
        "optional_names": ANCHORS_OPTIONAL,
        "anchors_any_CAL_": cal_any_sorted,
        "pairwise_distances_CAL_": pairwise_distances({a["name"]: Vector(a["location_world"]) for a in cal_any_sorted}),
    }

    # ---------- Aircraft basis / datum ----------
    basis_block = None
    if not missing_required:
        nose = anchors_found["nose"]
        tail = anchors_found["tail"]
        wing_l = anchors_found["wing_l"]
        wing_r = anchors_found["wing_r"]
        top = anchors_optional.get("top")
        bot = anchors_optional.get("bot")

        basis = compute_aircraft_basis(nose, tail, wing_l, wing_r, top=top, bot=bot)

        # Two coordinate frames: origin at nose (datum) and origin at centerline
        origin_nose = basis["origin_nose_world"]
        origin_center = basis["origin_centerline_world"]
        Rw2a = basis["rotation_world_to_aircraft_3x3"]
        Ra2w = basis["rotation_aircraft_to_world_3x3"]

        # Convert anchor points into aircraft-local coordinates (for HTML use)
        anchors_local_nose = {}
        anchors_local_center = {}
        for k, p in anchors_found.items():
            anchors_local_nose[k] = vec3(world_to_aircraft_point(p, origin_nose, Rw2a))
            anchors_local_center[k] = vec3(world_to_aircraft_point(p, origin_center, Rw2a))
        for k, p in anchors_optional.items():
            anchors_local_nose[k] = vec3(world_to_aircraft_point(p, origin_nose, Rw2a))
            anchors_local_center[k] = vec3(world_to_aircraft_point(p, origin_center, Rw2a))

        basis_block = {
            "datum": {
                "origin_nose_world": vec3(origin_nose),
                "origin_centerline_world": vec3(origin_center),
                "note": "Use origin_nose_world as aircraft datum if you want real-aircraft style references."
            },
            "axes_world": {
                "right": vec3(basis["axis_right_world"]),
                "forward": vec3(basis["axis_forward_world"]),
                "up": vec3(basis["axis_up_world"]),
                "note": "These are orthonormal unit vectors in WORLD space."
            },
            "rotation_matrices": {
                "aircraft_to_world_3x3": matrix3_to_list(Ra2w),
                "world_to_aircraft_3x3": matrix3_to_list(Rw2a),
                "note": "Use world_to_aircraft for transforming ray-hit points into aircraft-local coordinates."
            },
            "anchors_world": {
                "required": {k: vec3(v) for k, v in anchors_found.items()},
                "optional": {k: vec3(v) for k, v in anchors_optional.items()},
            },
            "anchors_aircraft_local": {
                "origin_nose": anchors_local_nose,
                "origin_centerline": anchors_local_center,
                "note": "These are the SAME points expressed in aircraft-local coords. Great for HTML calibration."
            }
        }

        calibration["basis_ready"] = True
    else:
        calibration["basis_ready"] = False

    # ---------- Build report ----------
    report = {
        "report_version": "2.0",
        "generated_at": iso_now(),
        "blend_file": bpy.data.filepath or None,
        "scene": {
            "name": scene.name,
            "unit_settings": unit_info(),
        },
        "summary": {
            "mesh_object_count": len(mesh_objs),
            "empty_object_count": len(empty_objs),
            "global_bounds_world": {
                "min": vec3(global_min),
                "max": vec3(global_max),
                "size": vec3(global_size),
                "center": vec3(global_center),
            },
            "totals": totals,
            "materials_unique": len(material_usage),
            "images_unique": len(image_usage),
        },
        "materials": {
            "usage": dict(sorted(material_usage.items(), key=lambda kv: (-kv[1], kv[0]))),
            "images": sorted(image_usage),
        },
        "calibration": calibration,
        "aircraft_basis": basis_block,
        "objects": object_reports,
    }

    # ---------- Write files ----------
    os.makedirs(os.path.dirname(REPORT_JSON_PATH), exist_ok=True)
    os.makedirs(os.path.dirname(REPORT_TXT_PATH), exist_ok=True)

    with open(REPORT_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    # TXT summary
    lines = []
    lines.append("GLB MEASURE + CALIBRATION DATUM REPORT")
    lines.append(f"Generated: {report['generated_at']}")
    lines.append(f"Blend file: {report['blend_file'] or '(unsaved)'}")
    lines.append("")
    lines.append("SCENE UNITS")
    lines.append(json.dumps(report["scene"]["unit_settings"], indent=2))
    lines.append("")
    lines.append("GLOBAL BOUNDS (WORLD)")
    gb = report["summary"]["global_bounds_world"]
    lines.append(f"  min: {gb['min']}")
    lines.append(f"  max: {gb['max']}")
    lines.append(f"  size: {gb['size']}  (X=right, Y=forward?, Z=up? depends on model orientation)")
    lines.append(f"  center: {gb['center']}")
    lines.append("")
    lines.append("TOTAL GEOMETRY")
    lines.append(f"  triangles: {report['summary']['totals']['triangles']}")
    lines.append(f"  vertices : {report['summary']['totals']['vertices']}")
    lines.append(f"  faces    : {report['summary']['totals']['faces']}")
    lines.append("")
    lines.append("CALIBRATION ANCHORS")
    if calibration["status"] != "ok":
        lines.append("  STATUS: MISSING REQUIRED ANCHORS")
        for m in calibration["missing_required"]:
            lines.append(f"   - {m}")
        lines.append("")
        lines.append("  Create empties named:")
        for k, nm in ANCHORS_REQUIRED.items():
            lines.append(f"   - {nm}   ({k})")
        lines.append("  Optional:")
        for k, nm in ANCHORS_OPTIONAL.items():
            lines.append(f"   - {nm}   ({k})")
    else:
        lines.append("  STATUS: OK")
        lines.append("  Required anchors (world):")
        for k, nm in ANCHORS_REQUIRED.items():
            lines.append(f"   - {nm}: {report['aircraft_basis']['anchors_world']['required'][k]}")
        if report["aircraft_basis"]["anchors_world"]["optional"]:
            lines.append("  Optional anchors (world):")
            for k, v in report["aircraft_basis"]["anchors_world"]["optional"].items():
                lines.append(f"   - {k}: {v}")
        lines.append("")
        lines.append("AIRCRAFT AXIS BASIS (WORLD UNIT VECTORS)")
        ax = report["aircraft_basis"]["axes_world"]
        lines.append(f"  right  (+X): {ax['right']}")
        lines.append(f"  forward(+Y): {ax['forward']}")
        lines.append(f"  up     (+Z): {ax['up']}")
        lines.append("")
        lines.append("DATUM ORIGINS (WORLD)")
        dt = report["aircraft_basis"]["datum"]
        lines.append(f"  origin_nose_world      : {dt['origin_nose_world']}")
        lines.append(f"  origin_centerline_world: {dt['origin_centerline_world']}")
        lines.append("")
        lines.append("ANCHORS (AIRCRAFT LOCAL, origin = nose)")
        for k, v in report["aircraft_basis"]["anchors_aircraft_local"]["origin_nose"].items():
            lines.append(f"  {k}: {v}")

    with open(REPORT_TXT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print("=== OK: REPORTS WRITTEN ===")
    print("JSON:", REPORT_JSON_PATH)
    print("TXT :", REPORT_TXT_PATH)
    print("Global size (world):", gb["size"] if isinstance(gb, dict) else vec3(global_size))
    if calibration["status"] != "ok":
        print("Missing required anchors:", missing_required)
    else:
        print("Aircraft basis computed successfully.")

# RUN
main()