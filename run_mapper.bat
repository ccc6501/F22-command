@echo off
TITLE F-22 Wingman Precision Mapper
echo Launching Arcana Flow Viz Pro...
echo Environment: Windows PowerShell / Python 3.x / Electron
echo Path: %~dp0

choice /C EB /M "Press E to launch in ELECTRON (No CORS) or B for BROWSER:"
if errorlevel 2 goto browser
if errorlevel 1 goto electron

:electron
echo Starting Electron App...
start npm start
goto end

:browser
echo Starting Python Data Manager...
start http://localhost:8022/web/f22_raptor_3d.html
python tools/f22_data_manager.py
goto end

:end
pause