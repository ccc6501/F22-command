F-22 Zone Touch POC (repeatable steps)
=====================================

This folder contains a Blender script and a one-file HTML proof-of-concept that verifies the pipeline:

Pipeline
--------

GLB → 10 named zones → export GLB+JSON → click/tap selection in browser

- `blender_panels_10_poc.py`
  - Run inside Blender's **Scripting** workspace / Text Editor.
  - Imports your source GLB.
  - Splits the aircraft mesh into **10 Y-band segments**.
  - Creates 10 separate objects named `F22_Zone_01` … `F22_Zone_10` (bright red).
  - Exports:
    - `f22_zones_10_poc.glb`
    - `f22_zones_10_poc.json`

- `poc_touch.html`
  - Single-file web viewer (three.js via CDN).
  - Loads `f22_zones_10_poc.glb` and lets you click/tap zones.
  - Shows the selected object name (example: `F22_Zone_03`).

Do this again (exact steps)
---------------------------

A) Blender: generate the 10 zones
-------------------------------

1. Put the source GLB in `Incoming/` (this repo already has one example).
2. Open `blender_panels_10_poc.py` in an editor and confirm these paths at the top:
   - `GLB_PATH` → your source GLB (example: `Incoming\f22._raptor.glb`)
   - `OUT_DIR`  → output folder (example: `Outgoing`)
   - `ZONE_COUNT` → number of zones (default 10)
3. In Blender:
   - Go to **Scripting** workspace.
   - In the Text Editor: **Text → Open…**
   - Select the on-disk file: `...\Blendr\blender_panels_10_poc.py`
   - Important: the tab name must be exactly `blender_panels_10_poc.py` (NOT `.001`, `.005`, etc).
4. Click **Run Script**.
5. Confirm the output files exist:
   - `Outgoing\f22_zones_10_poc.glb`
   - `Outgoing\f22_zones_10_poc.json`

B) Web: click/tap zone selection
-------------------------------

1. Copy `Outgoing\f22_zones_10_poc.glb` into the same folder as `poc_touch.html` (workspace root).
   - Alternatively you can change the path inside `poc_touch.html`, but copying is simplest.
2. Start a local server **from this folder** (PowerShell):

Optional shortcut: run `serve.ps1` to start the server and print the correct URL.

```powershell
python -m http.server 8000
```

1. Open the page over HTTP (NOT file://):
   - `http://localhost:8000/poc_touch.html`
2. Click/tap a red zone. You should see a label like:
   - `Selected: F22_Zone_03`

Notes and troubleshooting
-------------------------

- **Do not open `poc_touch.html` via `file://`**. Use `http://localhost:8000/...`.
- If you see Blender text tabs like `.001` / `.005`, you opened an internal copy.

   Always use **Text → Open…** and select the on-disk `blender_panels_10_poc.py`.
- If click selection works but zones look weird, your model may not be aligned with Y.

   (We can switch to X/Z or auto-pick the longest axis.)

Outputs
-------

- `Outgoing\f22_zones_10_poc.glb` — model with separate objects named `F22_Zone_01..10`
- `Outgoing\f22_zones_10_poc.json` — simple manifest (names, face counts, bounds)
