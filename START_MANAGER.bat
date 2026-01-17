@echo off
REM F-22 Data System Manager Launcher
REM Double-click to start the manager

cd /d "%~dp0"
echo Starting F-22 Data System Manager...
echo.

if exist ".venv\Scripts\python.exe" (
    start "F-22 Manager" ".venv\Scripts\python.exe" "tools\f22_data_manager.py" "%~dp0" --host 127.0.0.1 --port 8022
    powershell -NoProfile -Command "$url = 'http://127.0.0.1:8022/'; $max = 80; $delay = 250; for ($i = 0; $i -lt $max; $i++) { try { $client = New-Object System.Net.Sockets.TcpClient; $async = $client.BeginConnect('127.0.0.1', 8022, $null, $null); if ($async.AsyncWaitHandle.WaitOne(200)) { $client.EndConnect($async); $client.Close(); Start-Process $url; exit } $client.Close() } catch { } Start-Sleep -Milliseconds $delay } Start-Process $url"
) else (
    echo ERROR: Virtual environment not found!
    echo Please create it first: python -m venv .venv
    echo Then install requirements: .venv\Scripts\pip install -r requirements.txt
    pause
)
