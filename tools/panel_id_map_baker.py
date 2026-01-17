# ============================================================
# FINAL: Proxy-Object Panel ID Map Baker (UV-space PNG + JSON)
# ------------------------------------------------------------
# What this does:
#  - Finds panel proxy mesh objects (by suffix/prefix/collection)
#  - Assigns EACH a unique flat Emission color (unlit)
#  - Temporarily duplicates + joins them into one bake mesh
#  - Bakes EMIT to a single UV-space PNG (Panel ID Map)
#  - Writes JSON mapping: hex -> {panel_id: object_name}
#
# Requirements:
#  - Your proxy meshes must have UVs (at least one UV map)
#  - Cycles enabled (script sets it automatically)
#
# How to use:
#  1) Open Blender file with your proxy objects present
#  2) Paste into Text Editor and Run Script
#  3) Outputs in OUT_DIR: panel_id_map.png + panel_id_map_colors.json
#
# Notes:
#  - This does NOT require Edit Mode, materials per panel, or vertex groups.
#  - It uses object names as panel IDs by default.
# ============================================================

import bpy
import os
import json
import hashlib

# =========================
# USER SETTINGS (EDIT ME)
# =========================
OUT_DIR = r"C:\Users\Chance\Desktop\panel_id_map"
OUT_PNG = "panel_id_map.png"
OUT_JSON = "panel_id_map_colors.json"

IMAGE_SIZE = 2048          # 1024 / 2048 / 4096
BAKE_MARGIN_PX = 8         # padding around islands
AIRFRAME_HEX = "#000000"   # reserved background (won't be used for panels)

# --- How to pick panel proxy objects ---
# Option A (recommended): Use name suffix/prefix filters
NAME_SUFFIX = ""     # your screenshot shows names like "LH AVI DOOR_PROXY"
NAME_PREFIX = ""           # optional, leave "" if not needed

# Option B: Restrict to a collection name (leave blank to disable)
USE_COLLECTION = ""  # set to your proxy collection name or "" to disable

# --- Exclusions (leave as-is unless you want to bake more/less) ---
# If an object name contains any of these substrings, it will be skipped.
EXCLUDE_CONTAINS = [
    "cockpit",
    "canopy",
    "hud",
    "instrGlass",
    "glass",
    "Light",
    "landing",
    "gear",
    "wheel",
    "pilot",
    "seat",
    "Sketchfab_model",  # common root container
    "JOINED",           # avoid baking a pre-joined mesh if present
]

# If True, require at least one UV map on each object
REQUIRE_UVS = True

# Join duplicates into one bake object (recommended)
JOIN_FOR_BAKE = True

# =========================
# HELPERS
# =========================
def ensure_dir(path):
    os.makedirs(path, exist_ok=True)

def srgb_to_hex(rgb):
    r = max(0, min(255, int(round(rgb[0] * 255))))
    g = max(0, min(255, int(round(rgb[1] * 255))))
    b = max(0, min(255, int(round(rgb[2] * 255))))
    return f"#{r:02X}{g:02X}{b:02X}"

def index_to_rgb_hex(index: int):
    if index <= 0 or index > 0xFFFFFF:
        raise ValueError("index must be in range 1..16777215")
    r = (index >> 16) & 0xFF
    g = (index >> 8) & 0xFF
    b = index & 0xFF
    rgb = (r / 255.0, g / 255.0, b / 255.0)
    hexv = f"#{r:02X}{g:02X}{b:02X}"
    return rgb, hexv

def stable_color_from_name(name: str):
    """
    Deterministic "unique enough" color from object name.
    Nudges away from very dark colors and the reserved AIRFRAME_HEX.
    """
    h = hashlib.sha1(name.encode("utf-8")).hexdigest()
    r = 0.2 + 0.8 * (int(h[0:2], 16) / 255.0)
    g = 0.2 + 0.8 * (int(h[2:4], 16) / 255.0)
    b = 0.2 + 0.8 * (int(h[4:6], 16) / 255.0)
    hx = srgb_to_hex((r, g, b))
    if hx.upper() == AIRFRAME_HEX.upper():
        r = min(1.0, r + 0.05)
        hx = srgb_to_hex((r, g, b))
    return (r, g, b), hx

def ensure_cycles():
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"  # safest for baking
    scene.render.bake.use_selected_to_active = False
    scene.render.bake.use_clear = True
    scene.render.bake.margin = BAKE_MARGIN_PX
    scene.render.bake.target = "IMAGE_TEXTURES"
    scene.cycles.bake_type = "EMIT"

def create_bake_image(name, size):
    img = bpy.data.images.new(name=name, width=size, height=size, alpha=False, float_buffer=False)
    # Keep sRGB; we care about exact bytes when saved, but this is fine for baking.
    img.colorspace_settings.name = "sRGB"
    return img

def make_emit_material(mat_name, rgb, bake_image):
    """
    Material nodes:
      Emission(color=rgb) -> Output
      Image Texture (bake target) set ACTIVE
    """
    mat = bpy.data.materials.new(mat_name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()

    out = nt.nodes.new("ShaderNodeOutputMaterial")
    out.location = (400, 0)

    emit = nt.nodes.new("ShaderNodeEmission")
    emit.location = (0, 0)
    emit.inputs["Color"].default_value = (rgb[0], rgb[1], rgb[2], 1.0)
    emit.inputs["Strength"].default_value = 1.0

    img = nt.nodes.new("ShaderNodeTexImage")
    img.location = (0, -220)
    img.image = bake_image
    img.interpolation = "Closest"  # CRITICAL: reduces edge blur in bake target
    nt.nodes.active = img
    img.select = True

    nt.links.new(emit.outputs["Emission"], out.inputs["Surface"])
    return mat

def set_single_material(obj, mat):
    if obj.type != "MESH":
        return
    if obj.data.materials:
        obj.data.materials.clear()
    obj.data.materials.append(mat)

def has_uvs(obj):
    return obj.type == "MESH" and obj.data and hasattr(obj.data, "uv_layers") and len(obj.data.uv_layers) > 0

def should_include(obj):
    if obj.type != "MESH":
        return False

    n = obj.name

    if NAME_PREFIX and not n.startswith(NAME_PREFIX):
        return False
    if NAME_SUFFIX and not n.endswith(NAME_SUFFIX):
        return False

    ln = n.lower()
    for bad in EXCLUDE_CONTAINS:
        if bad.lower() in ln:
            return False

    if REQUIRE_UVS and not has_uvs(obj):
        return False

    return True

def get_candidate_objects():
    if USE_COLLECTION:
        col = bpy.data.collections.get(USE_COLLECTION)
        if not col:
            raise RuntimeError(f"Collection '{USE_COLLECTION}' not found. Set USE_COLLECTION = '' to disable.")
        objs = [o for o in col.all_objects if o.type == "MESH"]
    else:
        objs = [o for o in bpy.context.scene.objects if o.type == "MESH"]

    objs = [o for o in objs if should_include(o)]
    return objs

def bake_emit(target_obj):
    # Ensure object mode
    if bpy.context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")

    bpy.ops.object.select_all(action="DESELECT")
    target_obj.select_set(True)
    bpy.context.view_layer.objects.active = target_obj

    bpy.ops.object.bake(type="EMIT")

def save_image(img, filepath):
    img.filepath_raw = filepath
    img.file_format = "PNG"
    img.save()

def duplicate_objects(objs):
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.object.duplicate()
    return [o for o in bpy.context.selected_objects if o.type == "MESH"]

# =========================
# MAIN
# =========================
def main():
    ensure_dir(OUT_DIR)
    ensure_cycles()

    panels = get_candidate_objects()
    if not panels:
        raise RuntimeError(
            "No proxy panel objects matched your filters.\n"
            "Check NAME_SUFFIX/NAME_PREFIX/USE_COLLECTION and EXCLUDE_CONTAINS."
        )

    # Bake target image
    bake_img = create_bake_image("PANEL_ID_MAP_BAKE", IMAGE_SIZE)

    # Assign unique emission material per object (on originals)
    mapping = {}
    used_hex = set()

    for idx, obj in enumerate(panels, start=1):
        rgb, hx = index_to_rgb_hex(idx)

        mapping[hx] = {
            "panel_id": obj.name,
            "object_name": obj.name,
            "panel_index": idx
        }

        mat = make_emit_material(f"PID_{idx}_{obj.name}", rgb, bake_img)
        set_single_material(obj, mat)

    # Duplicate and join for a single, clean bake (so we don't modify originals permanently)
    bake_target = None
    dup_objs = None

    if JOIN_FOR_BAKE and len(panels) > 1:
        dup_objs = duplicate_objects(panels)
        bpy.context.view_layer.objects.active = dup_objs[0]
        bpy.ops.object.join()
        bake_target = bpy.context.view_layer.objects.active
        bake_target.name = "PANEL_ID_MAP_BAKE_JOINED"
    else:
        # Less ideal: bake from first panel only (won't include others). Keep JOIN_FOR_BAKE True.
        bake_target = panels[0]

    # Bake emission to image
    bake_emit(bake_target)

    # Save outputs
    out_png = os.path.join(OUT_DIR, OUT_PNG)
    out_json = os.path.join(OUT_DIR, OUT_JSON)

    save_image(bake_img, out_png)

    with open(out_json, "w", encoding="utf-8") as f:
        json.dump({
            "version": "1.0",
            "image_size": IMAGE_SIZE,
            "name_suffix_filter": NAME_SUFFIX,
            "name_prefix_filter": NAME_PREFIX,
            "collection_filter": USE_COLLECTION,
            "panel_count": len(mapping),
            "airframe_hex_reserved": AIRFRAME_HEX,
            "mapping": mapping
        }, f, indent=2)

    print("=== OK: Panel ID Map generated from proxy objects ===")
    print("Panels:", len(mapping))
    print("PNG :", out_png)
    print("JSON:", out_json)

    # Cleanup: delete duplicate joined bake object (and remaining dupes if any)
    if JOIN_FOR_BAKE and bake_target and bake_target.name == "PANEL_ID_MAP_BAKE_JOINED":
        bpy.ops.object.select_all(action="DESELECT")
        bake_target.select_set(True)
        bpy.ops.object.delete()

    print("Done.")

main()