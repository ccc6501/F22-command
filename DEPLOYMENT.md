# F-22 Raptor Wingman – Deployment Guide

**Version:** 2.0.0  
**Platform:** Windows 10/11 (primary), Linux/macOS (supported)

---

## Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| Python | 3.10+ (3.12 recommended) | Must be in PATH |
| Git | Any | For cloning repo |
| Browser | Chrome/Edge/Firefox | Modern browser with WebGL |
| Disk Space | ~500MB | Includes 28MB 3D model |

---

## Installation Steps

### 1. Clone Repository

```bash
git clone https://github.com/ccc6501/F22-command.git
cd F22-command
```

### 2. Create Virtual Environment

**Windows (PowerShell):**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

**Windows (Command Prompt):**

```batch
python -m venv .venv
.venv\Scripts\activate.bat
```

**Linux/macOS:**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

Required packages:

- `opencv-python` – Image processing
- `numpy` – Numerical operations
- `pytesseract` – OCR (requires Tesseract installed)
- `webcolors` – Color name resolution
- `scipy` – Scientific computing

### 4. Verify Installation

```bash
python -c "import cv2, numpy, scipy; print('Dependencies OK')"
```

---

## Starting the Server

### Option A: Double-Click Launcher (Windows)

1. Navigate to repo folder
2. Double-click `START_MANAGER.bat`
3. Browser opens automatically to <http://localhost:8022/>

### Option B: PowerShell Script

```powershell
cd "C:\path\to\F22-command"
.\run_manager.ps1
```

**With options:**

```powershell
.\run_manager.ps1 -Port 9000 -BindHost 0.0.0.0
```

### Option C: Direct Python

```bash
python tools/f22_data_manager.py . --port 8022 --host 127.0.0.1
```

---

## Configuration

The server uses sensible defaults. Override via command-line:

| Flag | Default | Description |
|------|---------|-------------|
| `--port` | 8022 | HTTP port |
| `--host` | 127.0.0.1 | Bind address (0.0.0.0 for network access) |
| `--scan-only` | false | Run scan and exit |
| `--backup` | false | Create backup and exit |

### Folder Structure (Auto-Created)

```
data/
├── inbox/          # Drop zone for new files
├── sources/        # Canonical source data
├── exports/        # Generated exports
├── models/         # 3D models
├── measurements/   # Calibration data
├── slides/         # Slide images
└── touch_masks/    # Touch zone definitions

manager/
├── f22_registry.db # SQLite registry
├── logs/           # Daily logs
├── backups/        # Snapshots
└── reports/        # Generated reports
```

---

## Accessing the Application

| URL | Description |
|-----|-------------|
| <http://localhost:8022/> | Command Center (main dashboard) |
| <http://localhost:8022/apps/blueprint_mapper.html> | Blueprint Mapper |
| <http://localhost:8022/apps/f22_raptor_3d.html> | 3D Touch Zone Viewer |

---

## Network Access

To allow access from other machines:

```powershell
.\run_manager.ps1 -BindHost 0.0.0.0
```

**Firewall:** Allow incoming TCP on port 8022

**Access:** `http://<your-ip>:8022/`

---

## Production Considerations

### 1. Reverse Proxy (HTTPS)

For production, place behind nginx or Caddy:

```nginx
server {
    listen 443 ssl;
    server_name raptor.example.com;
    
    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;
    
    location / {
        proxy_pass http://127.0.0.1:8022;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### 2. Process Manager

Run as a Windows service or use pm2/supervisor on Linux:

**Windows (NSSM):**

```batch
nssm install F22Manager ".venv\Scripts\python.exe" "tools\f22_data_manager.py"
nssm start F22Manager
```

### 3. Backups

Manual backup:

```bash
python tools/f22_data_manager.py . --backup
```

Backups are stored in `manager/backups/`

---

## Troubleshooting

### Server Won't Start

1. **Port in use:**

   ```powershell
   netstat -an | Select-String "8022"
   ```

   If port is busy, use `--port 8023`

2. **Python not found:**
   Ensure virtual environment is activated

3. **Permission denied:**
   Run PowerShell as Administrator

### Browser Shows Offline

1. Check server is running (terminal should show log output)
2. Verify correct port in browser URL
3. Check Windows Firewall isn't blocking

### GLB Model Not Loading

1. Verify `web/assets/F22Raptor.glb` exists (28MB)
2. Check browser console for WebGL errors
3. Try a different browser

---

## Updating

```bash
git pull origin main
pip install -r requirements.txt --upgrade
```

Then restart the server.

---

## Uninstalling

1. Stop the server (Ctrl+C or close terminal)
2. Delete the repo folder
3. (Optional) Remove Python virtual environment

---

**Support:** Open an issue at <https://github.com/ccc6501/F22-command/issues>
