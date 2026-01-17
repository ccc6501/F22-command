# Mapping Data Compiler

This Python script compiles all mapping data JSON and PNG files in the **Images** directory into combined master files with timestamps.

## Features

- Combines multiple `mapping_data*.json` files into master JSON files
- Creates combined PNG collage from `mapping_output*.png` files
- Adds timestamps to all output files
- Maintains original JSON files while creating combined versions

## Default Root Directory

The script looks for files in: `C:\Users\Chance\Desktop\F22 Mapper\Images`

You can specify a different directory as a command line argument:

```bash
python mapping_compiler.py "C:\Path\To\Your\Images\Directory"
```

## Output Files

1. `combined_mapping_output_regions_YYYYMMDD_HHMMSS.json` - Combined regions data with global IDs
2. `combined_mapping_data_YYYYMMDD_HHMMSS.json` - Combined mapping data with color assignments
3. `combined_mapping_output_YYYYMMDD_HHMMSS.png` - Combined PNG collage (requires PIL/Pillow)

## Requirements

- Python 3.6+
- PIL/Pillow (for PNG processing): `pip install Pillow`

## Usage

1. Place the script in the same directory as your mapping data files
2. Run: `python mapping_compiler.py`

## File Patterns

The script looks for files matching these patterns:

- JSON files: `mapping_data*.json`
- PNG files: `mapping_output*.png`

## Example Output Structure

### combined_mapping_output_regions.json

```json
{
  "timestamp": "20240116_143022",
  "processing_date": "2024-01-16T14:30:22.123456",
  "total_files_processed": 3,
  "files_processed": ["mapping_data_001.json", "mapping_data_002.json", "mapping_data_003.json"],
  "regions": [
    {
      "id": 1,
      "color": "#ff3366",
      "region_id": "region_001",
      "name": "Region 1",
      "original_file": "mapping_data_001.json",
      "file_index": 0,
      "global_id": 1
    }
  ]
}
```

### combined_mapping_data.json

```json
{
  "timestamp": "20240116_143022",
  "processing_date": "2024-01-16T14:30:22.123456",
  "total_files_processed": 3,
  "files_processed": ["mapping_data_001.json", "mapping_data_002.json", "mapping_data_003.json"],
  "mappings": [
    {
      "id": 1,
      "global_id": 1,
      "color": "#ff3366",
      "region_id": "region_001",
      "name": "Region 1",
      "original_file": "mapping_data_001.json",
      "file_index": 0
    }
  ]
}
```

## Notes

- Original JSON files are preserved
- PNG combination creates a grid layout collage
- All output files include processing timestamps
- Global IDs are assigned sequentially across all files
