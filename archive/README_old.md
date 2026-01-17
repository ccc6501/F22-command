# F22 Mapper

This folder contains the F-22 blueprint mapping tools (HTML apps) plus helper scripts.

## Quick start

- Open the main mapper:
  - `web/blueprint_mapper.html`

- Start the F-22 Data System Manager (serves apps + API):
  - PowerShell (recommended): `run_manager.ps1`
  - Python (uses your current interpreter): `run_manager.py`

Once running:

- Manager UI: `http://127.0.0.1:8022/`
- Apps (alias): `http://127.0.0.1:8022/apps/blueprint_mapper.html`
- Apps (direct): `http://127.0.0.1:8022/web/blueprint_mapper.html`

## Folder layout

- `web/` – browser-based tools (HTML)
- `tools/` – Python/utility scripts
- `data/` – structured project data (sources/exports/slides/etc.)
- `outputs/` – generated artifacts (PNGs/JSONs) from tools
- `docs/` – documentation
- `archive/` – old/one-off files you don’t want deleted
- `project_root/` – legacy/previous structure kept for backward compatibility

## Outputs

Mapping Mode exports (PNG/JSON) are stored in `outputs/mapping/`.

Other tools should write outputs under `outputs/`:

- `outputs/mapping/` – `mapping_output_*.png/json`, `combined_mapping_*` artifacts
- `outputs/region_extraction/` – extraction JSONs / debug images from `tools/extract_regions.py`

## Notes

If you’ve been using older paths, the files were moved but kept intact. If you spot a broken link or a script that expects an old location, tell me which one and I’ll wire in a compatibility alias.

### Canonical data locations

- Master parts data (source-of-truth copies): `data/sources/`
  - `master_parts.csv`
  - `master_parts.json`
  - `master_parts_v2.json`
  - `master_parts.sqlite`

- Slide exports (manifest + PNGs): `data/slides/`
  - `data/slides/manifest_slides.json`
  - `data/slides/images/slide_*.png`

### Legacy folder (`project_root/`)

`project_root/` is kept as a legacy snapshot for backward compatibility.

- Don’t add new files there.
- If you need to share the project with older scripts that still reference `project_root/`, keep it.
- The canonical locations are the paths listed above.

### Python Tools (scripts)

| Script | Description |
| -------- | ----------- |
| `slidestrip.py` | Command-line slide processing with PowerPoint COM automation |
| `aircraft_map_audit.py` | Audit, trace, and backup utility for data validation |
| `blueprint_clickable_mapper.py` | PyQt6-based desktop blueprint mapper |

## Data Flow

```text
┌─────────────────────────────────────────────────────────────────────────┐
│                            F22 Command Pipeline                         │
└─────────────────────────────────────────────────────────────────────────┘

  PPTX/PDF Files
       │
       ▼
┌──────────────────┐     ┌──────────────────┐
│ slide_stripper   │────▶│  Slide Images    │
│     .html        │     │ slide_0001.png   │
└──────────────────┘     └──────────────────┘
       │
       ▼
┌──────────────────┐     ┌──────────────────┐
│ table_extractor  │────▶│ master_parts_v2  │
│     .html        │     │    .json         │
└──────────────────┘     └──────────────────┘
                               │
                               ▼
                    ┌──────────────────┐     ┌──────────────────────┐
                    │   bootbro.html   │────▶│ master_inventory_v2  │
                    │ (Inventory Mgmt) │     │      .json           │
                    └──────────────────┘     └──────────────────────┘
                               │
                               ▼
                    ┌──────────────────┐     ┌──────────────────────┐
                    │blueprint_mapper  │────▶│  blueprint_map_v2    │
                    │     .html        │     │      .json           │
                    └──────────────────┘     └──────────────────────┘
                               │
                               ▼
                    ┌──────────────────────────────────────────────┐
                    │            aircraft_viewer.html              │
                    │         (Read-Only Operations View)          │
                    └──────────────────────────────────────────────┘
```

## Data Schemas

### master_parts_v2.json

```json
{
  "schema": "master_parts_v2",
  "parts": [
    {
      "uid": "NAS1234-3|CRES",
      "dash": "NAS1234-3",
      "material": "CRES",
      "description": "Screw, Machine",
      "zone": 4,
      "zone_sequence": 2,
      "slide_number": 5
    }
  ]
}
```

### master_inventory_v2.json

```json
{
  "schema": "master_inventory_v2",
  "items": [
    {
      "item_id": 1,
      "uid": "NAS1234-3|CRES",
      "on_hand": 50,
      "min_stock": 10,
      "locations": ["BIN-A1-03"]
    }
  ]
}
```

### blueprint_map_v2.json

```json
{
  "version": "2.0",
  "zones": {
    "zone_1": {
      "zone_id": "zone_1",
      "zone_name": "Zone 1",
      "color": "#ff3366",
      "linked_uids": ["NAS1234-3|CRES"]
    }
  }
}
```

## Quick Start

1. **Extract Tables**: Open `table_extractor.html` and load your PPTX
2. **Process Slides**: Use `slide_stripper.html` to export slide images
3. **Manage Inventory**: Import parts into `bootbro.html` and add storage info
4. **Map Blueprints**: Use `blueprint_mapper.html` to link UIDs to regions
5. **View Operations**: Load everything in `aircraft_viewer.html`

## Requirements

### HTML Tools

- Modern browser (Chrome/Edge recommended for File System Access API)

### Python Scripts

- Python 3.9+
- python-pptx
- PyQt6 (for blueprint_clickable_mapper.py)
- pymupdf (optional, for PDF processing)
- xlsxwriter (optional, for Excel export)

## Project Structure

```text
F22-command/
├── aircraft_viewer.html      # Operations viewer
├── blueprint_mapper.html     # Interactive mapper with UID linking
├── bootbro.html              # Inventory management
├── slide_stripper.html       # PDF/PPTX processing
├── table_extractor.html      # Table extraction
├── slidestrip.py             # CLI slide processor
├── aircraft_map_audit.py     # Audit/backup utility
├── blueprint_clickable_mapper.py  # Desktop mapper
└── project_root/
    ├── data/
    │   ├── master_parts.json
    │   └── master_parts.csv
    └── slides/
        ├── manifest_slides.json
        └── images/
```

## License

MIT
