# F22 Command

A comprehensive aircraft mapping, parts management, and operations viewing pipeline for F-22 maintenance and operations.

## Overview

This project provides a complete pipeline for:

- Extracting parts data from PowerPoint presentations
- Managing aircraft parts inventory
- Creating interactive blueprint maps with clickable regions
- Viewing and querying aircraft data in a unified operations viewer

## Tools Included

### Core HTML Tools

| Tool | Description |
|------|-------------|
| `slide_stripper.html` | PDF/PPTX slide processing and image export |
| `table_extractor.html` | PPTX table extraction with zone/sequence detection |
| `bootbro.html` | Inventory management with storage locations and tracking |
| `blueprint_mapper.html` | Interactive region mapping with UID linking |
| `aircraft_viewer.html` | Read-only operations viewer for technicians |

### Python Scripts

| Script | Description |
|--------|-------------|
| `slidestrip.py` | Command-line slide processing with PowerPoint COM automation |
| `aircraft_map_audit.py` | Audit, trace, and backup utility for data validation |
| `blueprint_clickable_mapper.py` | PyQt6-based desktop blueprint mapper |

## Data Flow

```
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

```
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
