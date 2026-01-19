// preload.js
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("api", {
    pickFolder: () => ipcRenderer.invoke("pick-folder"),
    pickAssetsFile: () => ipcRenderer.invoke("pick-assets-file"),

    readText: (path) => ipcRenderer.invoke("read-text", path),
    writeText: (path, data) => ipcRenderer.invoke("write-text", path, data),

    // for images / glb / binary stuff
    readBinary: (path) => ipcRenderer.invoke("read-binary", path),
});