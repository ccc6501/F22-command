// main.js
const { app, BrowserWindow, ipcMain, dialog, shell, session } = require("electron");
const path = require("path");
const fs = require("fs/promises");

// AUTO-ALLOW the app directory on startup (covers web/assets + other bundled files)
// Users can still select a different folder via the picker, but this prevents
// confusing "No folder selected" / ENOENT errors for the default bundled assets.
let allowedRoot = __dirname;

function assertAllowed(p) {
    if (!allowedRoot) throw new Error("No folder selected yet");
    const rp = path.resolve(p);
    const rr = path.resolve(allowedRoot);
    // Allow reads only within the allowed root
    if (!rp.startsWith(rr)) throw new Error("Path not allowed");
    return rp;
}

function createMainWindow() {
    const win = new BrowserWindow({
        width: 1500,
        height: 950,
        backgroundColor: "#060913",
        webPreferences: {
            // ✅ Secure defaults (fixes your warnings)
            webSecurity: true,
            allowRunningInsecureContent: false,
            sandbox: true,
            contextIsolation: true,
            nodeIntegration: false,
            enableRemoteModule: false,
            preload: path.join(__dirname, "preload.js"),
        },
    });

    // ✅ Lock navigation to local app only
    win.webContents.on("will-navigate", (e, url) => {
        if (!url.startsWith("file://")) e.preventDefault();
    });

    // ✅ Block popups by default; allow https external if you want
    win.webContents.setWindowOpenHandler(({ url }) => {
        if (url.startsWith("https://")) shell.openExternal(url);
        return { action: "deny" };
    });

    win.loadFile(path.join(__dirname, 'web', 'f22_raptor_3d.html'));
    return win;
}

/* ---------------------------
   IPC: folder + read/write
--------------------------- */
ipcMain.handle("pick-folder", async () => {
    const res = await dialog.showOpenDialog({ properties: ["openDirectory"] });
    if (res.canceled || !res.filePaths?.[0]) return null;
    allowedRoot = res.filePaths[0];
    return allowedRoot;
});

// Open a file dialog rooted at web/assets so users can *see* the files (useful when folder dialog hides files)
ipcMain.handle('pick-assets-file', async () => {
    const defaultPath = path.join(__dirname, 'web', 'assets');
    const res = await dialog.showOpenDialog({
        title: 'Select an asset file (you can see files here)',
        defaultPath,
        properties: ['openFile'],
        filters: [
            { name: 'JSON Files', extensions: ['json'] },
            { name: 'Image Files', extensions: ['png', 'jpg', 'jpeg'] },
            { name: 'All Files', extensions: ['*'] }
        ]
    });
    if (res.canceled || !res.filePaths?.length) return null;
    return res.filePaths[0];
});

ipcMain.handle("read-text", async (_e, p) => {
    const rp = assertAllowed(p);
    return fs.readFile(rp, "utf8");
});

ipcMain.handle("write-text", async (_e, p, data) => {
    const rp = assertAllowed(p);
    await fs.writeFile(rp, data, "utf8");
    return true;
});

ipcMain.handle("read-binary", async (_e, p) => {
    const rp = assertAllowed(p);
    const buf = await fs.readFile(rp);
    return buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength);
});

/* Optional: deny all permission prompts */
function lockPermissions() {
    session.defaultSession.setPermissionRequestHandler((_wc, _perm, cb) => cb(false));
}

app.whenReady().then(() => {
    lockPermissions();
    createMainWindow();
});

app.on("window-all-closed", () => {
    if (process.platform !== "darwin") app.quit();
});