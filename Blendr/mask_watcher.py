"""
F22 Mask Watcher for Blender
============================
Auto-reloads mask textures when they change on disk.
Paint -> Save -> Blender auto-refreshes.

Usage:
1. Open this script in Blender's Text Editor
2. Click "Run Script" or press Alt+P
3. Paint in external app, save, and Blender updates automatically!
"""

import bpy
import os
from pathlib import Path

# --- CONFIGURATION ---
MASK_FOLDER = r"C:\Users\Chance\Desktop\F22_Masks"

# Expected mask files
MASK_FILES = {
    "panel_top": "panel_top.png",
    "panel_bottom": "panel_bottom.png",
    "zone_top": "zone_top.png",
    "zone_bottom": "zone_bottom.png",
}

# Track file modification times
_file_mtimes = {}

def get_mask_path(name):
    """Get full path to a mask file."""
    return os.path.join(MASK_FOLDER, MASK_FILES.get(name, ""))

def check_and_reload_masks():
    """Check if mask files changed and reload them."""
    global _file_mtimes
    
    reloaded = []
    
    for name, filename in MASK_FILES.items():
        filepath = os.path.join(MASK_FOLDER, filename)
        
        if not os.path.exists(filepath):
            continue
            
        mtime = os.path.getmtime(filepath)
        
        # Check if file was modified
        if filepath in _file_mtimes and mtime > _file_mtimes[filepath]:
            # Find and reload the image in Blender
            for img in bpy.data.images:
                if img.filepath and Path(img.filepath).name == filename:
                    img.reload()
                    reloaded.append(name)
                    print(f"[MASK WATCHER] Reloaded: {filename}")
                    break
        
        _file_mtimes[filepath] = mtime
    
    if reloaded:
        # Force viewport refresh
        for area in bpy.context.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()
    
    return 0.5  # Check every 0.5 seconds

def setup_masks():
    """Initial setup - load mask images into Blender."""
    print("\n=== F22 MASK WATCHER SETUP ===")
    print(f"Mask folder: {MASK_FOLDER}")
    
    loaded = []
    skipped = []
    
    for name, filename in MASK_FILES.items():
        filepath = os.path.join(MASK_FOLDER, filename)
        
        if not os.path.exists(filepath):
            skipped.append(filename)
            print(f"[SKIP] Missing {filename}")
            continue
        
        # Check if already loaded
        existing = None
        for img in bpy.data.images:
            if img.filepath and Path(img.filepath).name == filename:
                existing = img
                break
        
        if existing:
            existing.reload()
            print(f"[RELOAD] {filename}")
        else:
            # Load new image
            img = bpy.data.images.load(filepath)
            img.name = name
            print(f"[LOAD] {filename} -> {name}")
        
        loaded.append(filename)
        _file_mtimes[filepath] = os.path.getmtime(filepath)
    
    print(f"\nLoaded: {len(loaded)}, Skipped: {len(skipped)}")
    print("=== MASK SETUP COMPLETE ===")
    print("Paint -> Save -> Blender auto-refreshes.")
    
    return loaded, skipped

def start_watcher():
    """Start the file watcher timer."""
    # Remove any existing timer
    if bpy.app.timers.is_registered(check_and_reload_masks):
        bpy.app.timers.unregister(check_and_reload_masks)
    
    # Register new timer
    bpy.app.timers.register(check_and_reload_masks, first_interval=1.0)
    print("[MASK WATCHER] Timer started - watching for changes...")

def stop_watcher():
    """Stop the file watcher timer."""
    if bpy.app.timers.is_registered(check_and_reload_masks):
        bpy.app.timers.unregister(check_and_reload_masks)
        print("[MASK WATCHER] Timer stopped.")

# --- MAIN EXECUTION ---
if __name__ == "__main__":
    setup_masks()
    start_watcher()
