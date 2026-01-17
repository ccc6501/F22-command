#!/usr/bin/env python3
"""
Mapping Data Compiler
Compiles all mapping data JSON and PNG files in the current directory
into combined master files with timestamps.
"""

import os
import json
import glob
from datetime import datetime
import sys
try:
    from PIL import Image
    import math
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    print("Warning: PIL/Pillow not available. PNG processing will be skipped.")
    print("Install with: pip install Pillow")

def get_timestamp():
    """Get current timestamp in YYYYMMDD_HHMMSS format"""
    return datetime.now().strftime("%Y%m%d_%H%M%S")

def find_mapping_files(root_dir):
    """Find all mapping data files in the specified root directory"""
    json_pattern = os.path.join(root_dir, "mapping_data*.json")
    png_pattern = os.path.join(root_dir, "mapping_output*.png")

    json_files = glob.glob(json_pattern)
    png_files = glob.glob(png_pattern)

    return sorted(json_files), sorted(png_files)

def load_json_file(filepath):
    """Load and return JSON data from file"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading {filepath}: {e}")
        return None

def combine_mapping_data(json_files):
    """Combine all mapping data JSON files into master structures"""
    timestamp = get_timestamp()

    # Master data structures
    master_regions = {
        "timestamp": timestamp,
        "processing_date": datetime.now().isoformat(),
        "total_files_processed": len(json_files),
        "files_processed": json_files,
        "regions": []
    }

    master_data = {
        "timestamp": timestamp,
        "processing_date": datetime.now().isoformat(),
        "total_files_processed": len(json_files),
        "files_processed": json_files,
        "mappings": []
    }

    region_id_counter = 1

    for file_idx, json_file in enumerate(json_files):
        print(f"Processing {json_file}...")
        data = load_json_file(json_file)

        if not data:
            continue

        # Process regions data
        if "regions" in data:
            for region in data["regions"]:
                # Create a new region entry with global ID
                new_region = region.copy()
                new_region["original_file"] = json_file
                new_region["file_index"] = file_idx
                new_region["global_id"] = region_id_counter
                master_regions["regions"].append(new_region)
                region_id_counter += 1

        # Process mapping data
        if "regions" in data:
            for region in data["regions"]:
                mapping_entry = {
                    "id": region.get("id"),
                    "global_id": region_id_counter - 1,  # Use the counter from above
                    "color": region.get("color"),
                    "region_id": region.get("regionId"),
                    "name": region.get("name"),
                    "original_file": json_file,
                    "file_index": file_idx
                }
                master_data["mappings"].append(mapping_entry)

    return master_regions, master_data

def create_combined_png(png_files, output_filename):
    """Create a combined PNG file from multiple PNG files"""
    if not PIL_AVAILABLE:
        print("PIL not available - skipping PNG combination")
        return

    if not png_files:
        print("No PNG files to combine")
        return

    timestamp = get_timestamp()

    # Load all images
    images = []
    for png_file in png_files:
        try:
            img = Image.open(png_file)
            images.append((png_file, img))
        except Exception as e:
            print(f"Error loading {png_file}: {e}")

    if not images:
        print("No valid PNG files found")
        return

    # Calculate grid layout
    num_images = len(images)
    grid_cols = math.ceil(math.sqrt(num_images))
    grid_rows = math.ceil(num_images / grid_cols)

    # Assume all images are the same size (first image)
    img_width, img_height = images[0][1].size

    # Create combined image
    combined_width = grid_cols * img_width
    combined_height = grid_rows * img_height

    combined_image = Image.new('RGB', (combined_width, combined_height), (255, 255, 255))

    # Paste images into grid
    for idx, (filename, img) in enumerate(images):
        row = idx // grid_cols
        col = idx % grid_cols
        x = col * img_width
        y = row * img_height
        combined_image.paste(img, (x, y))

    # Save combined image
    output_path = f"{output_filename}_{timestamp}.png"
    combined_image.save(output_path)
    print(f"Combined PNG saved as: {output_path}")

def save_master_json(data, filename_prefix):
    """Save master JSON data with timestamp"""
    timestamp = get_timestamp()
    output_filename = f"{filename_prefix}_{timestamp}.json"

    with open(output_filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"Master JSON saved as: {output_filename}")
    return output_filename

def main():
    """Main function to compile mapping data"""
    # Default root directory
    default_root = r"C:\Users\Chance\Desktop\F22 Mapper\Images"

    # Allow command line argument for root directory
    if len(sys.argv) > 1:
        root_dir = sys.argv[1]
    else:
        root_dir = default_root

    print("Mapping Data Compiler")
    print("=" * 50)
    print(f"Root directory: {root_dir}")

    # Check if root directory exists
    if not os.path.exists(root_dir):
        print(f"Error: Root directory '{root_dir}' does not exist!")
        print("Usage: python mapping_compiler.py [root_directory]")
        return

    # Find all mapping files
    json_files, png_files = find_mapping_files(root_dir)

    print(f"Found {len(json_files)} JSON files: {[os.path.basename(f) for f in json_files]}")
    print(f"Found {len(png_files)} PNG files: {[os.path.basename(f) for f in png_files]}")

    if not json_files:
        print("No mapping data JSON files found!")
        return

    # Combine mapping data
    print("\nProcessing JSON files...")
    master_regions, master_data = combine_mapping_data(json_files)

    # Save master JSON files
    regions_file = save_master_json(master_regions, "combined_mapping_output_regions")
    data_file = save_master_json(master_data, "combined_mapping_data")

    # Create combined PNG
    print("\nProcessing PNG files...")
    create_combined_png(png_files, "combined_mapping_output")

    print("\n" + "=" * 50)
    print("Processing complete!")
    print(f"Master regions JSON: {regions_file}")
    print(f"Master data JSON: {data_file}")
    print(f"Total regions processed: {len(master_regions['regions'])}")
    print(f"Total mappings processed: {len(master_data['mappings'])}")

if __name__ == "__main__":
    main()