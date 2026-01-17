# F-22 Raptor Wingman – Test Plan

**Version:** 2.0.0  
**Date:** 2026-01-17

---

## Test Environment

| Component | Specification |
|-----------|---------------|
| OS | Windows 10/11 |
| Python | 3.12.x |
| Browser | Chrome 120+ / Edge 120+ |
| Dependencies | As per requirements.txt |

---

## Test Categories

### 1. Server Startup Tests

| ID | Test Case | Expected Result | Command |
|----|-----------|-----------------|---------|
| S1 | Start server with defaults | Server listens on 8022 | `python tools/f22_data_manager.py` |
| S2 | Start with custom port | Server listens on specified port | `python tools/f22_data_manager.py --port 9000` |
| S3 | Start with network binding | Server accepts external connections | `python tools/f22_data_manager.py --host 0.0.0.0` |
| S4 | Scan-only mode | Runs scan, prints stats, exits | `python tools/f22_data_manager.py --scan-only` |
| S5 | Backup mode | Creates backup, prints path, exits | `python tools/f22_data_manager.py --backup` |

---

### 2. API Endpoint Tests

| ID | Endpoint | Method | Expected Response |
|----|----------|--------|-------------------|
| A1 | `/api/status` | GET | JSON with app, version, port, uptime |
| A2 | `/api/health` | GET | JSON with health check data |
| A3 | `/api/stats` | GET | JSON with total_records, by_category |
| A4 | `/api/records?limit=10` | GET | Array of DataRecord objects |
| A5 | `/api/search?q=master` | GET | Array of search results |
| A6 | `/api/inbox` | GET | JSON with pending inbox files |
| A7 | `/api/inbox/route` | POST | JSON with routed/skipped counts |
| A8 | `/api/scan` | POST | JSON with scan statistics |
| A9 | `/api/backup` | POST | JSON with backup path |

**Test Commands:**

```powershell
# A1 - Status
(Invoke-WebRequest -Uri "http://localhost:8022/api/status").Content | ConvertFrom-Json

# A3 - Stats
(Invoke-WebRequest -Uri "http://localhost:8022/api/stats").Content | ConvertFrom-Json

# A5 - Search
(Invoke-WebRequest -Uri "http://localhost:8022/api/search?q=parts").Content | ConvertFrom-Json

# A7 - Route Inbox
$body = '{"mode":"copy"}'; Invoke-WebRequest -Uri "http://localhost:8022/api/inbox/route" -Method POST -Body $body -ContentType "application/json"
```

---

### 3. Static File Serving Tests

| ID | Path | Expected Result |
|----|------|-----------------|
| F1 | `/` | Returns Control Center HTML (200) |
| F2 | `/apps/blueprint_mapper.html` | Returns Blueprint Mapper (200) |
| F3 | `/apps/f22_raptor_3d.html` | Returns 3D Viewer (200) |
| F4 | `/apps/assets/F22Raptor.glb` | Returns GLB model (200) |
| F5 | `/apps/assets/panel_id_map.png` | Returns PNG image (200) |
| F6 | `/nonexistent.html` | Returns 404 |

**Test Commands:**

```powershell
(Invoke-WebRequest -Uri "http://localhost:8022/").StatusCode
(Invoke-WebRequest -Uri "http://localhost:8022/apps/blueprint_mapper.html").StatusCode
(Invoke-WebRequest -Uri "http://localhost:8022/apps/f22_raptor_3d.html").StatusCode
(Invoke-WebRequest -Uri "http://localhost:8022/apps/assets/F22Raptor.glb").StatusCode
```

---

### 4. Inbox Routing Tests

| ID | Input File | Expected Destination | Expected Action |
|----|------------|---------------------|-----------------|
| R1 | `master_parts.json` | `data/sources/` | Routed |
| R2 | `master_parts.csv` | `data/sources/` | Routed |
| R3 | `master_parts.sqlite` | `data/sources/` | Routed |
| R4 | `master_inventory_v2.json` | `data/exports/` | Routed |
| R5 | `panel_id_map_colors.json` | `data/exports/` | Routed |
| R6 | `blueprint_map_export.json` | `data/exports/` | Routed |
| R7 | `random_file.json` | - | Skipped |
| R8 | `unknown.csv` | - | Skipped |

**Test Procedure:**

1. Create test files in `data/inbox/`
2. Call `POST /api/inbox/route`
3. Verify files moved to correct destinations
4. Verify skipped files remain in inbox

---

### 5. Registry Tests

| ID | Test Case | Verification |
|----|-----------|--------------|
| D1 | New file detected | Record created with UID |
| D2 | File modified | Version incremented, hash updated |
| D3 | File deleted | Record removed from registry |
| D4 | JSON validation | Invalid JSON marked as status=invalid |
| D5 | Audit logging | Operations logged to manager/logs/ |

---

### 6. UI Functional Tests

#### Control Center (`/`)

| ID | Test Case | Expected Result |
|----|-----------|-----------------|
| U1 | Page loads | Canvas animation visible, no JS errors |
| U2 | Status indicator | Green dot when connected |
| U3 | Record counts | Shows real numbers from API |
| U4 | Refresh button | Stats update, burst animation |
| U5 | Log entries | Show real-time events |

#### Blueprint Mapper (`/apps/blueprint_mapper.html`)

| ID | Test Case | Expected Result |
|----|-----------|-----------------|
| U6 | Page loads | Canvas with grid background |
| U7 | Load master parts | File picker works |
| U8 | Panel click | Region highlighted |
| U9 | Export JSON | Downloads mapping file |

#### 3D Viewer (`/apps/f22_raptor_3d.html`)

| ID | Test Case | Expected Result |
|----|-----------|-----------------|
| U10 | Page loads | 3D model visible (may take 3-5s) |
| U11 | Mouse rotation | Model rotates smoothly |
| U12 | Panel hover | Highlight effect visible |
| U13 | Panel click | Info panel shows details |

---

### 7. Integration Tests

| ID | Scenario | Steps | Expected Result |
|----|----------|-------|-----------------|
| I1 | End-to-end data flow | Drop file in inbox → Route → Verify in destination | File appears in canonical location |
| I2 | Search after scan | Add new file → Trigger scan → Search for filename | File appears in search results |
| I3 | Backup and restore | Create backup → Delete DB → Restore | Registry recovered |

---

## Automated Test Commands

Save as `run_tests.ps1`:

```powershell
# F-22 Wingman Smoke Tests

$base = "http://localhost:8022"

Write-Host "=== API Tests ===" -ForegroundColor Cyan

# Test 1: Status endpoint
$status = (Invoke-WebRequest -Uri "$base/api/status" -UseBasicParsing).Content | ConvertFrom-Json
if ($status.version) { Write-Host "✓ Status OK: v$($status.version)" -ForegroundColor Green }
else { Write-Host "✗ Status FAILED" -ForegroundColor Red }

# Test 2: Stats endpoint
$stats = (Invoke-WebRequest -Uri "$base/api/stats" -UseBasicParsing).Content | ConvertFrom-Json
if ($stats.total_records -gt 0) { Write-Host "✓ Stats OK: $($stats.total_records) records" -ForegroundColor Green }
else { Write-Host "✗ Stats FAILED" -ForegroundColor Red }

# Test 3: Search endpoint
$search = (Invoke-WebRequest -Uri "$base/api/search?q=master" -UseBasicParsing).Content | ConvertFrom-Json
if ($search.Count -gt 0) { Write-Host "✓ Search OK: $($search.Count) results" -ForegroundColor Green }
else { Write-Host "✗ Search FAILED" -ForegroundColor Red }

Write-Host "`n=== Static File Tests ===" -ForegroundColor Cyan

# Test 4-6: Static files
@("/", "/apps/blueprint_mapper.html", "/apps/f22_raptor_3d.html") | ForEach-Object {
    $code = (Invoke-WebRequest -Uri "$base$_" -UseBasicParsing).StatusCode
    if ($code -eq 200) { Write-Host "✓ $_ : $code" -ForegroundColor Green }
    else { Write-Host "✗ $_ : $code" -ForegroundColor Red }
}

Write-Host "`n=== Asset Tests ===" -ForegroundColor Cyan

# Test 7-8: Assets
@("/apps/assets/F22Raptor.glb", "/apps/assets/panel_id_map.png") | ForEach-Object {
    $code = (Invoke-WebRequest -Uri "$base$_" -UseBasicParsing).StatusCode
    if ($code -eq 200) { Write-Host "✓ $_ : $code" -ForegroundColor Green }
    else { Write-Host "✗ $_ : $code" -ForegroundColor Red }
}

Write-Host "`n=== Tests Complete ===" -ForegroundColor Cyan
```

---

## Pass/Fail Criteria

| Category | Pass Threshold |
|----------|----------------|
| Server Startup | 5/5 tests pass |
| API Endpoints | 8/9 tests pass |
| Static Files | 6/6 tests pass |
| UI Functional | Manual verification, no JS errors |
| Integration | All scenarios pass |

**Overall Release Criteria:** All critical tests (S1, A1-A5, F1-F5, U1-U3) must pass.

---

## Known Limitations

1. **No automated UI tests** – Manual verification required
2. **Tesseract OCR optional** – Some tools require separate installation
3. **Windows-centric launchers** – Linux/macOS users run Python directly
4. **No HTTPS** – Development only; use reverse proxy for production

---

**Approved for Release:** ✅ All critical tests passing
