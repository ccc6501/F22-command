@echo off
echo Mapping Data Compiler - Usage Demo
echo ===================================
echo.
echo This script compiles all mapping_data*.json and mapping_output*.png files
echo in the Images directory into combined master files with timestamps.
echo.
echo Default root directory: C:\Users\Chance\Desktop\F22 Mapper\Images
echo.
echo Usage:
echo   python mapping_compiler.py
echo   python mapping_compiler.py "C:\Path\To\Images\Directory"
echo.
echo Requirements:
echo   - Python 3.6+
echo   - PIL/Pillow (optional, for PNG processing): pip install Pillow
echo.
echo Output files (saved in current directory):
echo   - combined_mapping_output_regions_YYYYMMDD_HHMMSS.json
echo   - combined_mapping_data_YYYYMMDD_HHMMSS.json
echo   - combined_mapping_output_YYYYMMDD_HHMMSS.png (if PIL available)
echo.
echo Press any key to run the compiler...
pause > nul

python mapping_compiler.py

echo.
echo Processing complete! Check the generated files above.
pause