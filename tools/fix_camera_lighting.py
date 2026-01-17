#!/usr/bin/env python3
"""
Fix camera speed, lighting, and display stage for F22 3D viewer.
- Increase lighting intensity (brighter scene)
- Add more lights for better coverage
- Speed up camera controls
- Brighter background / stage
"""

# Read the file
with open(r'C:\Users\Chance\Desktop\F22 Mapper\f22_raptor_3d.html', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Fix background color - brighter
old_bg = "scene.background = new THREE.Color(0x050508);"
new_bg = "scene.background = new THREE.Color(0x1a1a2e);  // Brighter background"
content = content.replace(old_bg, new_bg)

# 2. Fix controls - faster rotation and zoom
old_controls = """const controls = new OrbitControls(camera, renderer.domElement);
            controls.enableDamping = true;
            controls.dampingFactor = 0.08;
            controls.rotateSpeed = 0.6;"""

new_controls = """const controls = new OrbitControls(camera, renderer.domElement);
            controls.enableDamping = true;
            controls.dampingFactor = 0.12;      // Faster damping response
            controls.rotateSpeed = 1.5;         // FASTER rotation (was 0.6)
            controls.zoomSpeed = 2.0;           // FASTER zoom
            controls.panSpeed = 1.5;            // FASTER pan
            controls.minDistance = 0.5;         // Allow closer zoom
            controls.maxDistance = 50;          // Allow farther zoom"""
content = content.replace(old_controls, new_controls)

# 3. Fix lighting - much brighter with better coverage
old_lights = """const hemi = new THREE.HemisphereLight(0xffffff, 0x202030, 1);
            scene.add(hemi);
            const dir = new THREE.DirectionalLight(0xffffff, 1);
            dir.position.set(2, 3, 2);
            scene.add(dir);
            const dir2 = new THREE.DirectionalLight(0xffffff, 0.5);
            dir2.position.set(-2, 1, -2);
            scene.add(dir2);"""

new_lights = """// === ENHANCED LIGHTING SETUP ===
            // Hemisphere light (sky + ground ambient)
            const hemi = new THREE.HemisphereLight(0xffffff, 0x444466, 2.0);  // BRIGHTER
            scene.add(hemi);
            
            // Main key light (front-top-right)
            const dir = new THREE.DirectionalLight(0xffffff, 2.5);  // MUCH BRIGHTER
            dir.position.set(5, 8, 5);
            scene.add(dir);
            
            // Fill light (front-left)
            const dir2 = new THREE.DirectionalLight(0xaaccff, 1.5);  // Cool fill
            dir2.position.set(-5, 3, 3);
            scene.add(dir2);
            
            // Back rim light
            const dir3 = new THREE.DirectionalLight(0xffffee, 1.0);
            dir3.position.set(0, 2, -8);
            scene.add(dir3);
            
            // Bottom fill (reduce harsh shadows)
            const dir4 = new THREE.DirectionalLight(0x6688aa, 0.8);
            dir4.position.set(0, -5, 0);
            scene.add(dir4);
            
            // Ambient for overall minimum brightness
            const ambient = new THREE.AmbientLight(0xffffff, 0.5);
            scene.add(ambient);
            
            // Ground plane / stage
            const stageGeo = new THREE.CircleGeometry(15, 64);
            const stageMat = new THREE.MeshStandardMaterial({ 
                color: 0x2a2a3a, 
                roughness: 0.8,
                metalness: 0.2
            });
            const stage = new THREE.Mesh(stageGeo, stageMat);
            stage.rotation.x = -Math.PI / 2;
            stage.position.y = -0.01;  // Slightly below origin
            stage.receiveShadow = true;
            scene.add(stage);"""

content = content.replace(old_lights, new_lights)

# Write the updated file
with open(r'C:\Users\Chance\Desktop\F22 Mapper\f22_raptor_3d.html', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ FIXED!")
print("")
print("Changes made:")
print("  📷 Camera Controls:")
print("      - rotateSpeed: 0.6 → 1.5 (2.5x FASTER)")
print("      - Added zoomSpeed: 2.0")
print("      - Added panSpeed: 1.5")
print("      - dampingFactor: 0.08 → 0.12 (snappier)")
print("")
print("  💡 Lighting:")
print("      - HemisphereLight: 1.0 → 2.0 intensity")
print("      - Main DirectionalLight: 1.0 → 2.5 intensity")
print("      - Added 4 additional lights (fill, rim, bottom)")
print("      - Added AmbientLight for base brightness")
print("")
print("  🎭 Stage:")
print("      - Background: 0x050508 → 0x1a1a2e (brighter)")
print("      - Added circular ground plane")
print("")
print("Refresh your browser to see the changes!")
