const { app, BrowserWindow } = require("electron");
const { spawn } = require("child_process");
const http = require("http");
const path = require("path");
const fs = require("fs");

app.name = "Workmap";
app.setAppUserModelId("com.workmap.app");

const BACKEND_PORT = 8000;
const FRONTEND_PORT = 5174;
const FRONTEND_DIST = app.isPackaged
  ? path.join(process.resourcesPath, "frontend")
  : path.join(__dirname, "..", "frontend", "dist");
const BACKEND_DIR = app.isPackaged
  ? path.join(process.resourcesPath, "backend")
  : path.join(__dirname, "..", "backend");
const PYBIN_PATH = app.isPackaged
  ? path.join(process.resourcesPath, "backend", "server")
  : path.join(__dirname, "..", "backend", "dist", "server");
const APP_ICON = path.join(__dirname, "icon.png");

let backendProcess = null;
let server = null;
let win = null;

function findFreePort(port, maxAttempts = 100) {
  return new Promise((resolve, reject) => {
    function tryPort(p) {
      if (p > port + maxAttempts) return reject(new Error("no free port found"));
      const srv = require("net").createServer();
      srv.on("error", () => tryPort(p + 1));
      srv.listen(p, () => {
        srv.close(() => resolve(p));
      });
    }
    tryPort(port);
  });
}

function startStaticServer(distPath, port) {
  return new Promise((resolve) => {
    server = http.createServer((req, res) => {
      const safePath = path.normalize(req.url).replace(/^(\.\.[/\\])+/, "");
      let filePath = path.join(distPath, safePath === "/" ? "index.html" : safePath);

      if (!fs.existsSync(filePath)) {
        filePath = path.join(distPath, "index.html");
      }

      const extMap = {
        ".html": "text/html",
        ".js": "application/javascript",
        ".css": "text/css",
        ".svg": "image/svg+xml",
        ".png": "image/png",
        ".json": "application/json",
        ".woff2": "font/woff2",
      };
      const ext = path.extname(filePath);
      const contentType = extMap[ext] || "application/octet-stream";

      fs.readFile(filePath, (err, data) => {
        if (err) {
          res.writeHead(404);
          res.end("Not found");
        } else {
          res.writeHead(200, { "Content-Type": contentType });
          res.end(data);
        }
      });
    });

    server.listen(port, () => {
      console.log(`frontend server listening on http://localhost:${port}`);
      resolve();
    });
  });
}

function startBackend(freeBackendPort) {
  return new Promise((resolve, reject) => {
    const binPath = fs.existsSync(PYBIN_PATH) ? PYBIN_PATH : null;
    if (binPath) {
      backendProcess = spawn(binPath, [], {
        cwd: BACKEND_DIR,
        stdio: ["pipe", "pipe", "pipe"],
        env: { ...process.env, PORT: String(freeBackendPort) },
      });
    } else {
      backendProcess = spawn("uvicorn", ["api.server:app", "--port", String(freeBackendPort)], {
        cwd: BACKEND_DIR,
        stdio: ["pipe", "pipe", "pipe"],
        env: { ...process.env, PORT: String(freeBackendPort) },
      });
    }

    function onData(data) {
      const text = data.toString();
      console.log("[backend]", text.trim());
      if (text.includes("Uvicorn running") || text.includes("Application startup complete") || text.includes("Bound to")) {
        resolve();
      }
    }

    backendProcess.stdout.on("data", onData);
    backendProcess.stderr.on("data", onData);
    backendProcess.on("error", reject);
    backendProcess.on("exit", (code) => {
      if (code !== 0) console.error(`backend exited with code ${code}`);
    });

    setTimeout(() => resolve(), 5000);
  });
}

async function createWindow() {
  win = new BrowserWindow({
    width: 1280,
    height: 860,
    icon: APP_ICON,
    title: "Workmap",
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
    },
  });

  win.setMenuBarVisibility(false);

  if (process.platform === "darwin" && fs.existsSync(APP_ICON)) {
    app.dock.setIcon(APP_ICON);
  }

  win.loadURL(`http://localhost:${FRONTEND_PORT}`);

  win.on("closed", () => {
    win = null;
  });
}

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

app.on("activate", () => {
  if (win === null) {
    createWindow();
  }
});

app.on("before-quit", () => {
  if (backendProcess) {
    backendProcess.kill();
    backendProcess = null;
  }
  if (server) {
    server.close();
    server = null;
  }
});

app.whenReady().then(async () => {
  const distPath = FRONTEND_DIST;
  if (!fs.existsSync(path.join(distPath, "index.html"))) {
    console.error(
      "frontend/dist/ not found. Run: cd frontend && npm run build"
    );
    app.quit();
    return;
  }

  const freeBackendPort = await findFreePort(BACKEND_PORT);
  await startBackend(freeBackendPort);
  await startStaticServer(distPath, FRONTEND_PORT);
  await createWindow();
});
