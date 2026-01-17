# ==================================================================
# Panel ID Map Baker - For GLB Model's UV Layout
# ==================================================================
# This script bakes a panel ID map that matches the UV layout of
# the F22Raptor.glb model (or any exported GLB).
#
# CRITICAL: Run this in Blender AFTER importing your GLB model!
#
# Workflow:
#   1) Open Blender
#   2) File > Import > glTF 2.0 (.glb/.gltf) -> Select F22Raptor.glb
#   3) Run this script in Blender's Text Editor
#   4) Outputs: panel_id_map.png + panel_id_map_colors.json
#
# ==================================================================

import bpy
import os
import json

# =========================
# USER SETTINGS
# =========================
OUT_DIR = r"C:\Users\Chance\Desktop\F22 Mapper\assets"
OUT_PNG = "panel_id_map.png"
OUT_JSON = "panel_id_map_colors.json"

IMAGE_SIZE = 2048
BAKE_MARGIN_PX = 4

# Panel objects to include (names as they appear in the GLB)
# Leave empty [] to auto-detect based on naming patterns
PANEL_NAMES = [
    "LH AVI DOOR",
    "LH LWR SWBD",
    "LH UPR SWBD",
    "RH ACFC",
    "RH ALPHA",
    "RH AVI DOOR",
    "RH IFR DOOR",
    "RH LWR BETA",
    "RH SHOULDER BAY",
    "RH UPPER BETA",
]

# Objects to EXCLUDE (substrings - case insensitive)
EXCLUDE_CONTAINS = [
    "airframe",
    "cockpit",
    "canopy",
    "hud",
    "glass",
    "landing",
    "gear",
    "wheel",
    "pilot",
    "seat",
    "light",
    "Sketchfab",
]

# Background color (hex) - reserved for non-panel areas
AIRFRAME_HEX = "#000000"

# =========================
# HELPERS
# =========================
def ensure_dir(path):
    os.makedirs(path, exist_ok=True)

def index_to_rgb(index: int):
    """Convert panel index (1-16777215) to RGB tuple and hex string."""
    if index <= 0 or index > 0xFFFFFF:
        raise ValueError("index must be in range 1..16777215")
    r = (index >> 16) & 0xFF
    g = (index >> 8) & 0xFF
    b = index & 0xFF
    rgb = (r / 255.0, g / 255.0, b / 255.0)
    hexv = f"#{r:02X}{g:02X}{b:02X}"
    return rgb, hexv

def ensure_cycles():
    """Configure Blender for Cycles baking."""
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.render.bake.use_selected_to_active = False
    scene.render.bake.use_clear = True
    scene.render.bake.margin = BAKE_MARGIN_PX
    scene.render.bake.target = "IMAGE_TEXTURES"
    scene.cycles.bake_type = "EMIT"

def create_bake_image(name, size):
    """Create a new image for baking."""
    img = bpy.data.images.new(
        name=name, 
        width=size, 
        height=size, 
        alpha=False, 
        float_buffer=False
    )
    img.colorspace_settings.name = "sRGB"
    # Fill with black background
    pixels = [0.0, 0.0, 0.0, 1.0] * (size * size)
    img.pixels = pixels
    return img

def make_emit_material(mat_name, rgb, bake_image):
    """
    Create emission material with bake target.
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

    img_node = nt.nodes.new("ShaderNodeTexImage")
    img_node.location = (0, -220)
    img_node.image = bake_image
    img_node.interpolation = "Closest"  # Sharp edges
    nt.nodes.active = img_node
    img_node.select = True

    nt.links.new(emit.outputs["Emission"], out.inputs["Surface"])
    return mat

def set_single_material(obj, mat):
    """Replace all materials on object with single material."""
    if obj.type != "MESH":
        return
    obj.data.materials.clear()
    obj.data.materials.append(mat)

def has_uvs(obj):
    """Check if mesh has UV coordinates."""
    return (obj.type == "MESH" and 
            obj.data and 
            hasattr(obj.data, "uv_layers") and 
            len(obj.data.uv_layers) > 0)

def should_include(obj):
    """Determine if object should be included as a panel."""
    if obj.type != "MESH":
        return False
    
    name = obj.name
    name_lower = name.lower()
    
    # Check exclusions
    for exclude in EXCLUDE_CONTAINS:
        if exclude.lower() in name_lower:
            return False
    
    # If specific panel names provided, check against list
    if PANEL_NAMES:
        return name in PANEL_NAMES
    
    # Otherwise include all meshes not excluded
    return has_uvs(obj)

def get_panel_objects():
    """Get all panel objects from scene."""
    panels = []
    for obj in bpy.context.scene.objects:
        if should_include(obj):
            if has_uvs(obj):
                panels.append(obj)
            else:
                print(f"WARNING: Skipping '{obj.name}' - no UVs")
    return panels

def store_original_materials(panels):
    """Store original materials for restoration."""
    original_mats = {}
    for obj in panels:
        original_mats[obj.name] = list(obj.data.materials)
    return original_mats

def restore_materials(panels, original_mats):
    """Restore original materials after baking."""
    for obj in panels:
        if obj.name in original_mats:
            obj.data.materials.clear()
            for mat in original_mats[obj.name]:
                obj.data.materials.append(mat)

def bake_emit(target_objs):
    """Bake emission from selected objects."""
    if bpy.context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    
    bpy.ops.object.select_all(action="DESELECT")
    for obj in target_objs:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = target_objs[0]
    
    bpy.ops.object.bake(type="EMIT")

def save_image(img, filepath):
    """Save image to file."""
    img.filepath_raw = filepath
    img.file_format = "PNG"
    img.save()

# =========================
# MAIN
# =========================
def main():
    ensure_dir(OUT_DIR)
    ensure_cycles()

    panels = get_panel_objects()
    if not panels:
        raise RuntimeError(
            "No panel objects found!\n"
            "Make sure you've imported the GLB model and panel names match PANEL_NAMES list."
        )

    print(f"Found {len(panels)} panel objects:")
    for p in panels:
        print(f"  - {p.name}")

    # Create bake target image
    bake_img = create_bake_image("PANEL_ID_MAP_BAKE", IMAGE_SIZE)

    # Store original materials
    original_mats = store_original_materials(panels)

    # Assign unique emission material per panel
    mapping = {}
    
    for idx, obj in enumerate(panels, start=1):
        rgb, hex_color = index_to_rgb(idx)
        
        mapping[hex_color] = {
            "panel_id": obj.name,
            "object_name": obj.name,
            "panel_index": idx
        }
        
        mat = make_emit_material(f"PID_{idx}_{obj.name}", rgb, bake_img)
        set_single_material(obj, mat)
        print(f"  Panel {idx}: {obj.name} -> {hex_color}")

    # Bake!
    print("\nBaking panel ID map...")
    bake_emit(panels)

    # Save outputs
    out_png = os.path.join(OUT_DIR, OUT_PNG)
    out_json = os.path.join(OUT_DIR, OUT_JSON)

    save_image(bake_img, out_png)
    print(f"Saved PNG: {out_png}")

    with open(out_json, "w", encoding="utf-8") as f:
        json.dump({
            "version": "1.0",
            "image_size": IMAGE_SIZE,
            "panel_count": len(mapping),
            "airframe_hex_reserved": AIRFRAME_HEX,
            "mapping": mapping
        }, f, indent=2)
    print(f"Saved JSON: {out_json}")

    # Restore original materials
    restore_materials(panels, original_mats)
    print("\nOriginal materials restored.")

    # Cleanup bake materials
    for mat in list(bpy.data.materials):
        if mat.name.startswith("PID_"):
            bpy.data.materials.remove(mat)

    print(f"\n=== SUCCESS: Panel ID Map generated ===")
    print(f"Panels: {len(mapping)}")
    print(f"PNG:  {out_png}")
    print(f"JSON: {out_json}")

if __name__ == "__main__":
    main()
