# F-22 Raptor Data System

Comprehensive data management, mapping tools, and validation system for F-22 component tracking.

## Quick Start

### Launch the Manager (Recommended)

```powershell
# Windows PowerShell (uses .venv automatically)
.\run_manager.ps1

# Or use Python directly
python run_manager.py
```

Once running, access:
- **Control Center**: `http://127.0.0.1:8022/` (status dashboard, checks, inbox routing)
- **Blueprint Mapper**: `http://127.0.0.1:8022/apps/blueprint_mapper.html`
- **3D Viewer**: `http://127.0.0.1:8022/apps/f22_raptor_3d.html`
- **REST API**: `http://127.0.0.1:8022/api/status`

### Standalone Mode (No Server)

```powershell
# Just open HTML files directly in browser
start web\blueprint_mapper.html
```

## Repository Structure

```
📁 F22 Mapper/
├── 📁 web/                    # Browser-based apps
│   ├── f22_control_center.html    # Main manager UI
│   ├── blueprint_mapper.html       # Interactive region mapper
│   └── f22_raptor_3d.html          # 3D model viewer
│
├── 📁 tools/                  # Python scripts & utilities
│   ├── f22_data_manager.py         # Central orchestrator (server + API)
│   ├── extract_regions.py          # Region extraction from images
│   ├── mapping_compiler.py         # Compile mapping outputs
│   ├── panel_id_map_baker.py       # Generate panel-to-ID mappings
│   └── f22_calibration_blender.py  # Blender automation scripts
│
├── 📁 data/                   # Canonical data storage
│   ├── 📁 sources/                 # Raw/source data (master_parts.*)
│   ├── 📁 exports/                 # Generated/derived data
│   ├── 📁 slides/                  # Slide manifest + images
│   ├── 📁 models/                  # 3D models (.glb, .obj)
│   ├── 📁 touch_masks/             # Touch zone masks
│   ├── 📁 measurements/            # 3D measurement data
│   └── 📁 inbox/                   # Drop zone for new files (auto-routed)
│
├── 📁 outputs/                # Tool-generated artifacts
│   ├── 📁 mapping/                 # Blueprint mapping outputs
│   └── 📁 region_extraction/       # Extracted regions + debug
│
├── 📁 manager/                # Manager internals
│   ├── f22_registry.db             # SQLite tracking database
│   └── 📁 logs/                    # System logs
│
├── 📁 schemas/                # JSON schemas for validation
├── 📁 docs/                   # Documentation
├── 📁 archive/                # Old/legacy files
├── 📁 project_root/           # Legacy structure (preserved for compatibility)
│
├── README.md                  # This file
├── requirements.txt           # Python dependencies
├── run_manager.ps1            # PowerShell launcher
├── run_manager.py             # Python launcher
└── f22_data_manager.py        # Convenience wrapper (imports from tools/)
```

## Data Flow

### Inbox → Routing → Canonical Storage

1. **Drop files** into `data/inbox/`
2. **Route via API** or Control Center UI: `POST /api/inbox/route`
3. **Auto-moves** to canonical locations:
   - `panel_id_map_colors.json` → `data/exports/`
   - `master_parts*.json/.csv/.sqlite` → `data/sources/`
   - `blueprint_map*.json` → `data/exports/`
   - `master_inventory*.json` → `data/exports/`

### Scanning & Validation

The manager automatically:
- **Scans** every 10 seconds for file changes
- **Hashes** files (SHA256) and tracks versions
- **Validates** JSON structure (lightweight shape checks)
- **Marks INVALID** if validation fails

### Integrity Checks

Run via Control Center or `POST /api/checks/run`:
- `inbox_pending` – Warns if files waiting in inbox
- `panel_id_map_colors_location` – Ensures canonical placement
- `invalid_records` – Lists any failed validations
- `duplicate_master_part_uids` – Detects duplicate UIDs

## REST API

### System
- `GET /api/status` – Uptime, version, scan stats
- `GET /api/health` – Component health, disk space, error counts
- `GET /api/stats` – Record counts by category/status
- `GET /api/logs` – Recent log entries
- `POST /api/scan` – Trigger immediate scan
- `POST /api/backup` – Create backup archive

### Data Records
- `GET /api/records?category=&status=&prefix=&limit=`
- `GET /api/records/{uid}`
- `POST /api/records` – Register new record
- `POST /api/records/{uid}/stale` – Mark outdated

### Inbox & Checks
- `GET /api/inbox` – List pending files
- `POST /api/inbox/route` – Route files: `{"mode":"copy|move","files":[...]}`
- `GET /api/checks` – Last check results
- `POST /api/checks/run` – Execute checks: `{"checks":[...]}`

### 3D Data
- `GET /api/measurements` – 3D measurement points
- `GET /api/touch_zones` – Interactive touch zones
- `POST /api/measurements` – Add measurement
- `POST /api/touch_zones` – Add touch zone

### Search & Audit
- `GET /api/search?q=` – Search all tracked files
- `GET /api/audit?limit=&target=` – Audit log

## Outputs

### Mapping Mode (Blueprint Mapper)
Exports saved to `outputs/mapping/`:
- `mapping_output_Top_20260116_123456.png`
- `mapping_output_Top_20260116_123456.json`
- `combined_mapping_*.png` (composite of all views)

### Region Extraction
Outputs saved to `outputs/region_extraction/`:
- Extracted regions JSON
- Debug images with highlighted regions

## Development

### Requirements
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Scan-Only Mode (No Server)
```powershell
python tools/f22_data_manager.py . --scan-only
```

### Custom Port/Host
```powershell
python tools/f22_data_manager.py . --port 9000 --host 0.0.0.0
```

## Legacy Compatibility

`project_root/` is preserved for backward compatibility with older scripts. **Do not add new files there.** All new development should use the canonical structure above.

## Troubleshooting

### Server won't start
- Check port 8022 isn't already in use: `Get-NetTCPConnection -LocalPort 8022`
- Try a different port: `.\run_manager.ps1 -Port 8023`
- Check logs: `manager/logs/`

### Files not routing from inbox
- Ensure file names match known patterns (see "Inbox → Routing" above)
- Check `GET /api/inbox` to see pending files
- Manually route: `POST /api/inbox/route` with `{"mode":"move"}`

### Invalid records showing up
- Check `GET /api/checks` to see validation errors
- View details: `GET /api/records?status=INVALID`
- Fix source files and re-scan: `POST /api/scan`
