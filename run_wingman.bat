@echo off
REM ═══════════════════════════════════════════════════════════════════════════
REM  F-22 RAPTOR WINGMAN - Launch Script
REM  Double-click to start the complete system
REM ═══════════════════════════════════════════════════════════════════════════

title F-22 Raptor Wingman

cd /d "%~dp0"

echo.
echo  ╔═══════════════════════════════════════════════════════════════════════╗
echo  ║                                                                       ║
echo  ║           F-22 RAPTOR WINGMAN LIBRARY SCREEN                          ║
echo  ║                       Version 2.0.0                                   ║
echo  ║                                                                       ║
echo  ╚═══════════════════════════════════════════════════════════════════════╝
echo.

REM Check for virtual environment
if not exist ".venv\Scripts\python.exe" (
    echo  [ERROR] Virtual environment not found!
    echo.
    echo  Please run these commands first:
    echo     python -m venv .venv
    echo     .venv\Scripts\pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

echo  [*] Starting F-22 Data System Manager...
echo  [*] Server will listen on http://localhost:8022/
echo.

REM Start the server in a new window
start "F-22 Manager Server" /min ".venv\Scripts\python.exe" "tools\f22_data_manager.py" "%~dp0" --host 127.0.0.1 --port 8022

REM Wait for server to start and open browser
echo  [*] Waiting for server to start...
powershell -NoProfile -Command ^
    "$max = 40; $delay = 250; for ($i = 0; $i -lt $max; $i++) { ^
        try { ^
            $client = New-Object System.Net.Sockets.TcpClient; ^
            $async = $client.BeginConnect('127.0.0.1', 8022, $null, $null); ^
            if ($async.AsyncWaitHandle.WaitOne(200)) { ^
                $client.EndConnect($async); ^
                $client.Close(); ^
                Write-Host '  [OK] Server started successfully!'; ^
                Start-Process 'http://localhost:8022/'; ^
                exit 0 ^
            } ^
            $client.Close() ^
        } catch { } ^
        Start-Sleep -Milliseconds $delay ^
    } ^
    Write-Host '  [WARN] Timeout waiting for server - opening browser anyway'; ^
    Start-Process 'http://localhost:8022/'"

echo.
echo  ═══════════════════════════════════════════════════════════════════════════
echo   Wingman is running! Browser should open automatically.
echo.
echo   To stop: Close this window or press Ctrl+C in the server window.
echo  ═══════════════════════════════════════════════════════════════════════════
echo.

REM Keep window open with instructions
pause
