# F-22 Raptor Wingman – Release Engineering Report

**Date:** 2026-01-17  
**Version:** 2.0.0  
**Status:** ✅ **GREEN** – Release Ready (MVP Deployable)

---

## A) Executive Summary

The **Raptor Wingman Library Screen** is verified as a **real, deployable system** – not a demo with placeholders. All core features are functional end-to-end:

| Component | Status | Notes |
|-----------|--------|-------|
| Data Manager Server | ✅ OPERATIONAL | HTTP server on port 8022, auto-scans registry |
| Control Center UI | ✅ FUNCTIONAL | Live API metrics, flow visualization |
| Blueprint Mapper | ✅ FUNCTIONAL | Interactive panel mapping with NGA styling |
| 3D Raptor Viewer | ✅ FUNCTIONAL | Touch zones, GLB model rendering |
| Registry Database | ✅ OPERATIONAL | 5,200+ records, SQLite with audit trail |
| Inbox Routing | ✅ FUNCTIONAL | Auto-routes recognized file patterns |
| File Search | ✅ FUNCTIONAL | Full-text search across codebase |

**Minimum Viable Product Confirmed.**

---

## B) Repository Inventory Map

```
F22 Mapper/
├── 📁 web/                          # Primary HTML apps (served by manager)
│   ├── f22_control_center.html      # Command Center dashboard
│   ├── blueprint_mapper.html        # NGA-style panel mapping tool
│   ├── f22_raptor_3d.html           # 3D touch zone viewer
│   └── assets/
│       ├── F22Raptor.glb            # 3D model (28MB)
│       ├── panel_id_map.png         # Panel ID reference image
│       └── panel_id_map_colors.json # Color-to-panel mapping
│
├── 📁 tools/                        # Python utilities
│   ├── f22_data_manager.py          # Main server (2313 lines)
│   ├── mapping_compiler.py          # Region extraction pipeline
│   └── *.py                         # Blender scripts, extractors
│
├── 📁 data/                         # Canonical data folders
│   ├── sources/                     # master_parts.*, raw data
│   ├── exports/                     # Generated reports, artifacts
│   ├── inbox/                       # Ingest drop zone
│   │   └── processed/               # Timestamped archive of routed files
│   ├── slides/images/               # Extracted slide images
│   ├── models/                      # 3D model storage
│   ├── measurements/                # Calibration data
│   └── touch_masks/                 # Touch zone definitions
│
├── 📁 manager/                      # Server state
│   ├── f22_registry.db              # SQLite registry
│   ├── logs/                        # Daily log files
│   ├── backups/                     # Snapshot backups
│   └── reports/                     # Generated reports
│
├── 📁 outputs/                      # Tool output artifacts
│   ├── mapping/                     # Compiled mapping data
│   └── region_extraction/           # Extracted regions
│
├── 📁 archive/                      # Legacy/deprecated files
├── 📁 Blendr/                       # Blender scripts and POC
├── 📁 docs/                         # Documentation
├── 📁 schemas/                      # (Empty – future schema defs)
│
├── START_MANAGER.bat                # Windows double-click launcher
├── run_manager.ps1                  # PowerShell launcher
├── requirements.txt                 # Python dependencies
├── README.md                        # Project README
└── .gitignore                       # Git exclusions
```

---

## C) Component-by-Component Verification

### 1. F-22 Data Manager (`tools/f22_data_manager.py`)

- **Lines:** 2,313
- **Server:** HTTP on port 8022 (configurable)
- **Database:** SQLite (`manager/f22_registry.db`)
- **API Endpoints Verified:**
  - `GET /api/status` ✅ Returns version, uptime, port
  - `GET /api/stats` ✅ Returns record counts by category
  - `GET /api/records` ✅ Lists registry entries
  - `GET /api/search?q=` ✅ Full-text search
  - `POST /api/inbox/route` ✅ Routes files from inbox
  - `POST /api/scan` ✅ Triggers filesystem scan

### 2. Control Center (`web/f22_control_center.html`)

- **Status:** Arcana Flow Viz styling
- **Features:**
  - Canvas-based particle flow visualization
  - Live connection to API (not hardcoded stats)
  - File drop zone for inbox routing
  - Event log with real-time updates
- **API Base:** `http://localhost:8022` (correct)

### 3. Blueprint Mapper (`web/blueprint_mapper.html`)

- **Lines:** 5,389
- **Features:**
  - Interactive region mapping on panel images
  - Master parts V2 loading
  - Zone UID linking
  - Export to JSON

### 4. 3D Raptor Viewer (`web/f22_raptor_3d.html`)

- **Lines:** 1,245
- **Features:**
  - Three.js GLB model rendering
  - Touch zone detection
  - Panel info panel
- **Assets Required:** `F22Raptor.glb` (verified present)

### 5. Registry Database

- **Total Records:** 5,202
  - App: 5
  - Export: 2
  - Source: 5,195
- **Status:** All records marked valid (JSON validation active)
- **Audit Trail:** Logs written to `manager/logs/f22_manager_YYYYMMDD.log`

### 6. Inbox Routing

- **Test Results (5 files):**
  - `master_parts_v3.csv` → `data/sources/` ✅
  - `master_inventory_export.json` → `data/exports/` ✅
  - `panel_id_map_colors.json` → `data/exports/` ✅
  - `test_master_parts.json` → SKIPPED (doesn't match `master_parts*` pattern)
  - `unrecognized_data.json` → SKIPPED (unrecognized)
- **Routing Logic:** Pattern-based (filename prefixes)

---

## D) Smoke Test Plan

### Prerequisites

1. Python 3.12+ installed
2. Virtual environment set up: `.venv\`
3. Dependencies installed: `pip install -r requirements.txt`

### Test Commands

```powershell
# 1. Start the Manager Server
cd "C:\Users\Chance\Desktop\F22 Mapper"
.\START_MANAGER.bat
# OR
.\run_manager.ps1

# 2. Verify Server Running
Invoke-WebRequest -Uri "http://localhost:8022/api/status" -UseBasicParsing

# 3. Check Registry Stats
Invoke-WebRequest -Uri "http://localhost:8022/api/stats" -UseBasicParsing

# 4. Search for Files
Invoke-WebRequest -Uri "http://localhost:8022/api/search?q=master" -UseBasicParsing

# 5. Load Control Center in Browser
Start-Process "http://localhost:8022/"

# 6. Load Blueprint Mapper
Start-Process "http://localhost:8022/apps/blueprint_mapper.html"

# 7. Load 3D Viewer
Start-Process "http://localhost:8022/apps/f22_raptor_3d.html"

# 8. Test Inbox Routing (drop a file in data/inbox/)
'{"test": 1}' | Out-File -Encoding utf8 "data\inbox\master_parts_test.json"
$body = @{mode="copy"} | ConvertTo-Json
Invoke-WebRequest -Uri "http://localhost:8022/api/inbox/route" -Method POST -Body $body -ContentType "application/json"
```

---

## E) Release Checklist

- [x] All HTML entrypoints return HTTP 200
- [x] All required assets exist (GLB, PNG, JSON)
- [x] Server starts without errors
- [x] API endpoints respond correctly
- [x] Registry populated with file records
- [x] Logs written to manager/logs/
- [x] Inbox routing functional
- [x] Search returns results
- [x] No secrets/API keys committed
- [x] .gitignore excludes .venv, **pycache**
- [x] Launchers work (START_MANAGER.bat, run_manager.ps1)
- [x] requirements.txt lists all dependencies

---

## F) Deployment Instructions

See **DEPLOYMENT.md** for full instructions.

### Quick Start (Windows)

```batch
:: 1. Clone repo
git clone https://github.com/ccc6501/F22-command.git
cd F22-command

:: 2. Create virtual environment
python -m venv .venv

:: 3. Install dependencies
.venv\Scripts\pip install -r requirements.txt

:: 4. Start manager
START_MANAGER.bat

:: 5. Browser opens automatically to http://localhost:8022/
```

---

## G) Day-to-Day User Experience

### Persona: F-22 Technical Data Analyst

1. **Morning Startup**
   - Double-click `START_MANAGER.bat`
   - Browser opens to Command Center
   - Verify green status indicator and record count

2. **Ingesting New Data**
   - Drag files to `data/inbox/` folder
   - Click "Route Inbox" in Control Center
   - Files automatically moved to canonical locations

3. **Panel Mapping**
   - Open Blueprint Mapper from Control Center
   - Load master_parts_v2.json
   - Click panels on blueprint image
   - Link regions to part UIDs

4. **3D Visualization**
   - Open 3D Viewer from Control Center
   - Rotate F-22 model with mouse
   - Click panels to see linked data

5. **Search & Export**
   - Use search API or Control Center search
   - Export mapping data as JSON
   - Find outputs in `data/exports/`

---

## H) Risks & Mitigations

| Risk | Severity | Mitigation |
|------|----------|------------|
| Port 8022 conflict | Low | Configurable via `--port` flag |
| Large GLB load time | Low | 28MB model, ~3s on modern hardware |
| BOM encoding issues | Low | Some JSON files have UTF-8 BOM, logged as warnings |
| Hardcoded paths in tools | Low | Developer tools only, main app is portable |
| No HTTPS | Medium | Local development only – add reverse proxy for production |
| Schema folder empty | Low | Future enhancement for JSON schema validation |

---

## Touch Features Status

| Feature | Status | Notes |
|---------|--------|-------|
| Touch Zone Detection | ✅ Implemented | In f22_raptor_3d.html |
| Panel Click Mapping | ✅ Implemented | In blueprint_mapper.html |
| Touch Mask Data | 📁 Folder exists | `data/touch_masks/` – empty, ready for data |
| Calibration Data | 📁 Folder exists | `data/measurements/` – empty, ready for data |

---

**Verified by:** GitHub Copilot (Build Verifier Agent)  
**Signature:** `RAPTOR-WINGMAN-RELEASE-2026-01-17`
