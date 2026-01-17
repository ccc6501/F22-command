import cv2
import numpy as np
import pytesseract
import argparse
import sys
import json
import os
from collections import Counter

# Set tesseract path options (Windows)
possible_tesseract_paths = [
    r'C:\Program Files\Tesseract-OCR\tesseract.exe',
    r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe',
    os.path.join(os.environ.get('LOCALAPPDATA', ''), r'Tesseract-OCR\tesseract.exe'),
    os.path.expanduser(r'~\AppData\Local\Tesseract-OCR\tesseract.exe')
]

for path in possible_tesseract_paths:
    if os.path.exists(path):
        pytesseract.pytesseract.tesseract_cmd = path
        print(f"Using Tesseract at: {path}")
        break
# If not found, it relies on PATH


def get_dominant_color(image, k=1):
    """
    Get dominant color of a small image patch using K-means or simple average.
    Returns (R, G, B) tuple.
    """
    pixels = np.float32(image.reshape(-1, 3))
    if len(pixels) == 0:
        return (0, 0, 0)
    
    n_pixels = len(pixels)
    if n_pixels < 5: # Too small, just average
        return tuple(np.mean(pixels, axis=0).astype(int))

    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 10, 1.0)
    flags = cv2.KMEANS_RANDOM_CENTERS
    compactness, labels, centers = cv2.kmeans(pixels, k, None, criteria, 10, flags)
    
    return tuple(map(int, centers[0]))

def rgb_to_hex(rgb):
    return "#{:02x}{:02x}{:02x}".format(rgb[0], rgb[1], rgb[2])

def extract_regions(image_path, output_format="json", debug=False):
    print(f"Processing {image_path}...")
    
    if not os.path.exists(image_path):
        print(f"Error: File {image_path} not found.")
        return

    # Read image
    img = cv2.imread(image_path)
    if img is None:
        print("Error: Could not read image.")
        return

    # Convert to RGB (OpenCV is BGR)
    img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    
    # Preprocessing for OCR might typically involve grayscale, thresholding
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    
    # Simple thresholding for text boosting
    # Determine if light text on dark bg or vice versa
    mean_val = np.mean(gray)
    if mean_val < 128:
        # Likely dark background, light text
        _, binary = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)
    else:
        # Likely light background, dark text
        _, binary = cv2.threshold(gray, 100, 255, cv2.THRESH_BINARY_INV)

    # Use pytesseract to get data
    # psm 6 = Assume a single uniform block of text. 11 = Sparse text.
    # We'll try default or 11/12 for scattered labels.
    custom_config = r'--oem 3 --psm 11' 
    
    try:
        results = pytesseract.image_to_data(img_rgb, config=custom_config, output_type=pytesseract.Output.DICT)
    except pytesseract.TesseractNotFoundError:
        print("\nERROR: Tesseract OCR is not installed or not in your PATH.")
        print("Please install Tesseract OCR:")
        print("  Windows: https://github.com/UB-Mannheim/tesseract/wiki")
        print("  Linux: sudo apt-get install tesseract-ocr")
        print("After installing, you may need to add it to your PATH or uncomment the line in this script specifying the path.")
        return

    regions = []
    
    n_boxes = len(results['text'])
    for i in range(n_boxes):
        text = results['text'][i].strip()
        confidence = int(results['conf'][i])
        
        # Filter weak detections and empty text
        if confidence > 30 and len(text) > 1:
            x, y, w, h = int(results['left'][i]), int(results['top'][i]), int(results['width'][i]), int(results['height'][i])
            
            # Identify the ID format (roughly matches typically AC IDs like TC1, BC65, etc)
            # This is optional, but helps filter noise
            # if not any(c.isdigit() for c in text): continue 

            # Determining the Color of the Region
            # Strategy: Look at the pixels "surrounding" the text or the centroid context.
            # We can sample a few points just outside the text box or use a larger box.
            
            # Let's verify the center of the text box
            cx, cy = x + w // 2, y + h // 2
            
            # Sampling strategy:
            # Check if the text is inside a colored polygon.
            # We will sample pixel colors around the text box.
            
            # Define sample margin
            margin = 5
            
            # Check bounds
            h_img, w_img, _ = img.shape
            
            # We want the background color, not the text color.
            # Since the text is usually contrasting, we can take the dominant color of a slightly larger crop
            # but mask out the text pixels (which we found in 'binary').
            
            y1 = max(0, y - margin)
            y2 = min(h_img, y + h + margin)
            x1 = max(0, x - margin)
            x2 = min(w_img, x + w + margin)
            
            patch = img_rgb[y1:y2, x1:x2]
            
            # If we simply take dominant color of the patch, the text color might interfere if it's large,
            # but usually background dominates.
            dom_color = get_dominant_color(patch, k=2) # k=2 usually separates bg and text
            
            # We can refine this:
            # Often the text is Black on Color or White on Color.
            # If dominant color is black/white/gray, pick the secondary color?
            # Or assume the text is strictly detected inside a "blob".
            
            # Alternative: Point check just outside the center of the four sides?
            # Let's stick to k-means dominant, and maybe ignore shades of grey if we expect vibrant colors.
            # For now, nearest standard color might be useful too.
            
            hex_color = rgb_to_hex(dom_color)
            
            if debug:
                # Draw box on debug image
                cv2.rectangle(img, (x, y), (x + w, y + h), (0, 255, 0), 2)
                cv2.circle(img, (cx, cy), 2, (0, 0, 255), -1)

            regions.append({
                "id": text,
                "hex": hex_color,
                "rgb": dom_color,
                "confidence": confidence,
                "bbox": [x, y, w, h]
            })

    # Deduplicate IDs (sometimes same ID appears multiple times or split)
    # This logic can be improved based on specific needs
    
    output_filename = os.path.splitext(os.path.basename(image_path))[0] + "_regions." + output_format
    
    if output_format == "json":
        with open(output_filename, 'w') as f:
            json.dump(regions, f, indent=2)
        print(f"Saved report to {output_filename}")
    elif output_format == "csv":
        with open(output_filename, 'w') as f:
            f.write("ID,Hex,RGB,Confidence\n")
            for r in regions:
                f.write(f"{r['id']},{r['hex']},\"{r['rgb']}\",{r['confidence']}\n")
        print(f"Saved report to {output_filename}")

    if debug:
        debug_filename = "debug_" + os.path.basename(image_path)
        cv2.imwrite(debug_filename, img)
        print(f"Debug image saved to {debug_filename}")

def process_directory(directory=".", output_format="json", debug=False):
    valid_extensions = {".jpg", ".jpeg", ".png", ".bmp", ".tiff"}
    
    files = [f for f in os.listdir(directory) if os.path.splitext(f)[1].lower() in valid_extensions and not f.startswith("debug_")]
    
    if not files:
        print(f"No image files found in {directory}")
        return
        
    print(f"Found {len(files)} images in {directory}. Processing...")
    
    for filename in files:
        filepath = os.path.join(directory, filename)
        extract_regions(filepath, output_format, debug)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract Region IDs and Colors from Images")
    parser.add_argument("path", nargs="?", default=".", help="Path to image file or directory (default: current directory)")
    parser.add_argument("--format", choices=["json", "csv"], default="json", help="Output format")
    parser.add_argument("--debug", action="store_true", help="Save debug image with bounding boxes")
    
    args = parser.parse_args()
    
    if os.path.isdir(args.path):
        process_directory(args.path, args.format, args.debug)
    else:
        extract_regions(args.path, args.format, args.debug)
