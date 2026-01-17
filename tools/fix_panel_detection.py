#!/usr/bin/env python3
"""
Fix panel detection to use mesh name as primary method
instead of unreliable UV-based color sampling.
"""

import re

# Read the file
with open(r'C:\Users\Chance\Desktop\F22 Mapper\f22_raptor_3d.html', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Add findPanelByMeshName function after findNearestPanel
find_nearest_end = '''return best && bestDist <= tolerance ? { panel: best.panel, dist: bestDist } : null;
        }'''

new_function = '''return best && bestDist <= tolerance ? { panel: best.panel, dist: bestDist } : null;
        }

        // Find panel by mesh/object name (primary detection method)
        function findPanelByMeshName(meshName) {
            if (!meshName || !state.panels.length) return null;
            // Direct match on object_name or panel id
            for (const p of state.panels) {
                const objName = p.data?.object_name || '';
                if (objName === meshName || p.id === meshName || p.name === meshName) {
                    return p;
                }
            }
            // Fuzzy match - normalize names (remove spaces, underscores, case)
            const normalize = s => s.toLowerCase().replace(/[\\s_-]/g, '');
            const normMesh = normalize(meshName);
            for (const p of state.panels) {
                const objName = p.data?.object_name || '';
                if (normalize(objName) === normMesh || normalize(p.id) === normMesh || normalize(p.name) === normMesh) {
                    return p;
                }
            }
            return null;
        }'''

content = content.replace(find_nearest_end, new_function)

# 2. Update tryPick to use mesh name detection first
old_panel_detection = '''const rgb = samplePanelIdMapAtUv(state.lastUv);
            state.lastRgb = rgb;
            const tolerance = Number(els.tolerance.value);
            const nearest = rgb ? findNearestPanel(rgb.r, rgb.g, rgb.b, tolerance) : null;
            state.lastPanel = nearest?.panel ?? null;'''

new_panel_detection = '''const rgb = samplePanelIdMapAtUv(state.lastUv);
            state.lastRgb = rgb;
            
            // PRIMARY: Try to find panel by mesh name first (most reliable)
            const meshPanel = findPanelByMeshName(hit.object?.name);
            
            // FALLBACK: Use UV-based color detection if mesh name didn't match
            const tolerance = Number(els.tolerance.value);
            const nearest = !meshPanel && rgb ? findNearestPanel(rgb.r, rgb.g, rgb.b, tolerance) : null;
            
            // Use mesh-based detection if found, otherwise UV-based
            state.lastPanel = meshPanel ?? nearest?.panel ?? null;
            
            // Log detection method for debugging
            if (meshPanel) {
                console.log('Panel detected by MESH NAME:', meshPanel.id);
            } else if (nearest) {
                console.log('Panel detected by UV COLOR:', nearest.panel.id, 'dist:', nearest.dist);
            }'''

content = content.replace(old_panel_detection, new_panel_detection)

# Write the updated file
with open(r'C:\Users\Chance\Desktop\F22 Mapper\f22_raptor_3d.html', 'w', encoding='utf-8') as f:
    f.write(content)

print("✓ Added findPanelByMeshName function")
print("✓ Updated tryPick to use mesh name as primary detection")
print("✓ File saved successfully!")
print("")
print("Now when you click on 'RH_ACFC' mesh, it will directly match to 'RH ACFC' panel")
print("instead of relying on UV color sampling.")
