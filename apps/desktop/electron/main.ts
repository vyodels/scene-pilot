import { app, BrowserWindow } from "electron";
import { access } from "node:fs/promises";
import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import path from "node:path";
import process from "node:process";
import url from "node:url";

const isDev = !app.isPackaged;
const backendOrigin = (process.env.SCENE_PILOT_BACKEND_URL ?? "http://127.0.0.1:8741").replace(/\/$/, "");
const backendHealthUrl = `${backendOrigin}/health`;
const backendStartupTimeoutMs = Number(process.env.SCENE_PILOT_BACKEND_STARTUP_TIMEOUT_MS ?? 20_000);
let backendProcess: ChildProcessWithoutNullStreams | undefined;

function createWindow(): BrowserWindow {
  const window = new BrowserWindow({
    width: 1440,
    height: 920,
    minWidth: 1180,
    minHeight: 760,
    title: "ScenePilot",
    show: false,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
    },
  });

  return window;
}

function buildBootHtml(title: string, detail: string): string {
  const escapedTitle = title.replace(/[<>&]/g, "");
  const escapedDetail = detail.replace(/[<>&]/g, "");
  return `
    <html>
      <body style="margin:0;display:grid;place-items:center;background:#070b16;color:#eef3ff;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif">
        <main style="max-width:560px;padding:32px 36px;border:1px solid rgba(255,255,255,0.12);border-radius:24px;background:rgba(255,255,255,0.04)">
          <div style="font-size:12px;letter-spacing:0.18em;text-transform:uppercase;color:rgba(238,243,255,0.56)">ScenePilot</div>
          <h1 style="margin:12px 0 10px;font-size:28px;line-height:1.1">${escapedTitle}</h1>
          <p style="margin:0;color:rgba(238,243,255,0.74);line-height:1.6">${escapedDetail}</p>
        </main>
      </body>
    </html>
  `;
}

async function showBootState(window: BrowserWindow, title: string, detail: string): Promise<void> {
  await window.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(buildBootHtml(title, detail))}`);
  if (!window.isVisible()) {
    window.show();
  }
}

function resolveBackendCommand(): string[] {
  if (process.env.SCENE_PILOT_BACKEND_CMD) {
    return process.env.SCENE_PILOT_BACKEND_CMD.split(" ");
  }

  if (!isDev) {
    const packagedBinary = resolvePackagedBackendBinary();
    if (packagedBinary) {
      return [packagedBinary];
    }
  }

  return ["python3", "-m", "scene_pilot.server"];
}

function resolvePackagedBackendBinary(): string | null {
  if (process.env.SCENE_PILOT_BACKEND_BUNDLED_PATH) {
    return process.env.SCENE_PILOT_BACKEND_BUNDLED_PATH;
  }

  const executableName = process.platform === "win32" ? "scene-pilot-backend.exe" : "scene-pilot-backend";
  return path.join(process.resourcesPath, "backend-dist", executableName);
}

function resolveBackendCwd(): string {
  if (isDev) {
    return path.resolve(__dirname, "../../services/backend/src");
  }

  if (process.env.SCENE_PILOT_BACKEND_CWD) {
    return process.env.SCENE_PILOT_BACKEND_CWD;
  }

  return path.join(process.resourcesPath, "backend-src", "src");
}

async function hasFilesystemPath(targetPath: string): Promise<boolean> {
  try {
    await access(targetPath);
    return true;
  } catch {
    return false;
  }
}

function startBackend(): void {
  const [command, ...args] = resolveBackendCommand();
  const cwd = resolveBackendCwd();
  backendProcess = spawn(command, args, {
    cwd,
    env: {
      ...process.env,
      SCENE_PILOT_DESKTOP_MODE: "1",
    },
  });

  backendProcess.stdout.on("data", (chunk) => {
    process.stdout.write(`[backend] ${chunk}`);
  });

  backendProcess.stderr.on("data", (chunk) => {
    process.stderr.write(`[backend] ${chunk}`);
  });
}

async function waitForBackendHealthy(): Promise<void> {
  const deadline = Date.now() + backendStartupTimeoutMs;
  let lastError: unknown;

  while (Date.now() < deadline) {
    try {
      const response = await fetch(backendHealthUrl);
      if (response.ok) {
        return;
      }
      lastError = new Error(`Health responded with ${response.status}`);
    } catch (error) {
      lastError = error;
    }
    await new Promise((resolve) => setTimeout(resolve, 400));
  }

  throw lastError instanceof Error ? lastError : new Error("Backend health check timed out");
}

async function loadApplication(window: BrowserWindow): Promise<void> {
  if (isDev) {
    await window.loadURL("http://localhost:5174");
    window.webContents.openDevTools({ mode: "detach" });
  } else {
    const rendererPath = path.join(__dirname, "../dist-renderer/index.html");
    await window.loadURL(url.pathToFileURL(rendererPath).toString());
  }
  window.show();
}

app.whenReady().then(async () => {
  const window = createWindow();
  await showBootState(window, "Starting desktop runtime", "Bootstrapping the local backend and waiting for health checks.");

  const packagedBinary = !isDev ? resolvePackagedBackendBinary() : null;
  const hasPackagedBinary = packagedBinary ? await hasFilesystemPath(packagedBinary) : false;
  if (!isDev && !hasPackagedBinary) {
    await showBootState(
      window,
      "Packaged backend not found",
      "Falling back to source-mode backend startup. This requires a system Python plus installed backend dependencies.",
    );
  }

  try {
    startBackend();
    await waitForBackendHealthy();
    await loadApplication(window);
  } catch (error) {
    const detail = error instanceof Error ? error.message : "Unknown startup failure";
    await showBootState(window, "Backend startup failed", detail);
  }

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      void loadApplication(createWindow());
    }
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});

app.on("before-quit", () => {
  backendProcess?.kill();
});
