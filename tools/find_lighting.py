#!/usr/bin/env python3
"""
Fix camera speed, lighting, and display stage for F22 3D viewer.
"""

import re

# Read the file
with open(r'C:\Users\Chance\Desktop\F22 Mapper\f22_raptor_3d.html', 'r', encoding='utf-8') as f:
    content = f.read()

# Find the initThree function and related setup
# Search for existing lighting setup
light_search = re.search(r'(scene\.add\([^)]*[Ll]ight[^)]*\))', content)
controls_search = re.search(r'(new OrbitControls\([^)]+\))', content)
background_search = re.search(r"scene\.background\s*=\s*new THREE\.Color\([^)]+\)", content)

print("Found lighting:", bool(light_search))
print("Found controls:", bool(controls_search))
print("Found background:", bool(background_search))

# Find where scene is created
scene_match = re.search(r'const scene = new THREE\.Scene\(\);', content)
if scene_match:
    print(f"Scene created at position: {scene_match.start()}")

# Find line numbers for key elements
lines = content.split('\n')
for i, line in enumerate(lines):
    if 'OrbitControls' in line:
        print(f"Line {i+1}: {line.strip()[:80]}")
    if 'Light' in line and 'THREE' in line:
        print(f"Line {i+1}: {line.strip()[:80]}")
    if 'scene.background' in line:
        print(f"Line {i+1}: {line.strip()[:80]}")
    if 'controls.' in line and ('speed' in line.lower() or 'damp' in line.lower() or 'zoom' in line.lower()):
        print(f"Line {i+1}: {line.strip()[:80]}")
