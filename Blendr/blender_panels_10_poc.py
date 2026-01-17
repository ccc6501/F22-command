import bpy
import bmesh
import os

# --- SETTINGS ---
FILE_PATH = r"C:\Users\Chance\Desktop\F22 Mapper\Blendr\Incoming\f22._raptor.glb"
OUT_FOLDER = r"C:\Users\Chance\Desktop\F22 Mapper\Blendr\Outgoing"
ZONE_COUNT = 10

def unwrap_and_segment():
    # 1. Robust Clean Scene (Data-level, avoids Context errors)
    # Remove all objects
    for obj in bpy.data.objects:
        bpy.data.objects.remove(obj, do_unlink=True)
    # Remove orphaned meshes/materials to keep file clean
    for mesh in bpy.data.meshes:
        bpy.data.meshes.remove(mesh)
    for mat in bpy.data.materials:
        bpy.data.materials.remove(mat)

    # 2. Import GLB
    if not os.path.exists(FILE_PATH):
        print(f"ERROR: File not found at {FILE_PATH}")
        return
    
    print(f"Importing: {FILE_PATH}...")
    bpy.ops.import_scene.gltf(filepath=FILE_PATH)

    # 3. Join all meshes into one "Full Body"
    # (Crucial so we slice a single solid object, not loose parts)
    meshes = [o for o in bpy.context.selected_objects if o.type == 'MESH']
    if not meshes:
        print("ERROR: No meshes found in imported file.")
        return
    
    # Set active object and join
    bpy.context.view_layer.objects.active = meshes[0]
    if len(meshes) > 1:
        bpy.ops.object.join()
    
    obj = bpy.context.active_object
    obj.name = "F22_Full_Body"

    # 4. Smart UV Unwrap (Fixed for Blender 4.0/5.0)
    print("Unwrapping mesh...")
    bpy.ops.object.mode_set(mode='EDIT') 
    bpy.ops.mesh.select_all(action='SELECT')
    
    # Find a 3D Viewport area to satisfy the operator's requirements
    area = next((a for a in bpy.context.screen.areas if a.type == 'VIEW_3D'), None)
    
    if area:
        # MODERN OVERRIDE SYNTAX
        with bpy.context.temp_override(area=area):
            bpy.ops.mesh.smart_project(angle_limit=1.15, island_margin=0.01)
    else:
        print("WARNING: No 3D Viewport found. Smart UV Project skipped.")
    
    bpy.ops.object.mode_set(mode='OBJECT')

    # 5. Segment into 10 Logical Zones (Y-Axis Slicing)
    print(f"Slicing into {ZONE_COUNT} zones...")
    
    # Calculate bounds in World Space
    y_coords = [(obj.matrix_world @ v.co).y for v in obj.data.vertices]
    y_min, y_max = min(y_coords), max(y_coords)
    step = (y_max - y_min) / ZONE_COUNT

    # Perform Bisect Cuts
    bpy.ops.object.mode_set(mode='EDIT')
    for i in range(1, ZONE_COUNT):
        cut_y = y_min + (step * i)
        
        # Bisect is generally robust without overrides in Edit Mode
        bpy.ops.mesh.bisect(
            plane_co=(0, cut_y, 0), 
            plane_no=(0, 1, 0), 
            use_fill=True,
            clear_inner=False,
            clear_outer=False
        )
    
    # 6. Separate Loose Parts
    # The 'fill' from bisect connects the loops, but they are technically loose 
    # relative to each other after the cut if the mesh was manifold.
    bpy.ops.mesh.separate(type='LOOSE')
    bpy.ops.object.mode_set(mode='OBJECT')

    # 7. Rename, Sort, and Color
    # Get all mesh objects and sort them from Tail to Nose (Y-axis)
    segments = [o for o in bpy.context.scene.objects if o.type == 'MESH']
    segments.sort(key=lambda o: o.location.y)

    print(f"Processing {len(segments)} segments...")

    for idx, segment in enumerate(segments):
        # Naming Convention
        segment.name = f"F22_Zone_{idx+1}"
        
        # Create unique material for debugging
        mat = bpy.data.materials.new(name=f"Mat_Zone_{idx+1}")
        mat.use_nodes = True
        
        # Assign color ramp (Dark Blue -> Light Blue)
        principled = mat.node_tree.nodes.get("Principled BSDF")
        if principled:
            blue_val = (idx + 1) / len(segments)
            principled.inputs['Base Color'].default_value = (0.0, 0.2, blue_val, 1.0)
            
        # Clear old slots and assign new material
        segment.data.materials.clear()
        segment.data.materials.append(mat)

    # 8. Export Final Result
    if not os.path.exists(OUT_FOLDER): 
        os.makedirs(OUT_FOLDER)
    
    out_path = os.path.join(OUT_FOLDER, "f22_segmented_ready.glb")
    
    # Select only the segments for export
    bpy.ops.object.select_all(action='DESELECT')
    for s in segments:
        s.select_set(True)
    
    # Export
    bpy.ops.export_scene.gltf(
        filepath=out_path,
        export_format='GLB',
        export_selected=True 
    )
    
    print(f"SUCCESS: Exported to {out_path}")

if __name__ == "__main__":
    unwrap_and_segment()