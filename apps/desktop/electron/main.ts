import { app, BrowserWindow } from "electron";
import { existsSync } from "node:fs";
import { access } from "node:fs/promises";
import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import path from "node:path";
import process from "node:process";
import { fileURLToPath, pathToFileURL } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const isDev = !app.isPackaged;
const backendOrigin = (process.env.RECRUIT_AGENT_BACKEND_URL ?? "http://127.0.0.1:8741").replace(/\/$/, "");
const backendHealthUrl = `${backendOrigin}/health`;
const backendStartupTimeoutMs = Number(process.env.RECRUIT_AGENT_BACKEND_STARTUP_TIMEOUT_MS ?? 20_000);
const electronRemoteDebugPort = process.env.RECRUIT_AGENT_ELECTRON_REMOTE_DEBUG_PORT ?? "9222";
const rendererOrigin = (process.env.RECRUIT_AGENT_DESKTOP_RENDERER_URL ?? "http://localhost:5174").replace(/\/$/, "");
let backendProcess: ChildProcessWithoutNullStreams | undefined;

if (isDev) {
  app.commandLine.appendSwitch("remote-debugging-port", electronRemoteDebugPort);
}

function createWindow(): BrowserWindow {
  const window = new BrowserWindow({
    width: 1440,
    height: 920,
    minWidth: 1180,
    minHeight: 760,
    title: "Recruit Agent",
    show: false,
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
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
          <div style="font-size:12px;letter-spacing:0.18em;text-transform:uppercase;color:rgba(238,243,255,0.56)">Recruit Agent</div>
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
  const backendCommand = process.env.RECRUIT_AGENT_BACKEND_CMD;
  if (backendCommand) {
    return backendCommand.split(" ");
  }

  if (!isDev) {
    const packagedBinary = resolvePackagedBackendBinary();
    if (packagedBinary) {
      return [packagedBinary];
    }
  }

  const preferredPython = resolveConfiguredPythonExecutable()
    ?? resolvePythonExecutable();
  return [preferredPython, "-m", "recruit_agent.core.app"];
}

function resolvePackagedBackendBinary(): string | null {
  const bundledBackendPath = process.env.RECRUIT_AGENT_BACKEND_BUNDLED_PATH;
  if (bundledBackendPath) {
    return bundledBackendPath;
  }

  const executableName = process.platform === "win32" ? "recruit-agent-backend.exe" : "recruit-agent-backend";
  return path.join(process.resourcesPath, "backend-dist", executableName);
}

function resolveBackendCwd(): string {
  if (isDev) {
    return path.resolve(__dirname, "../../../../services/backend/src");
  }

  const backendCwd = process.env.RECRUIT_AGENT_BACKEND_CWD;
  if (backendCwd) {
    return backendCwd;
  }

  return path.join(process.resourcesPath, "backend-src", "src");
}

function resolvePythonExecutable(): string {
  const candidates = [
    "/usr/local/bin/python3",
    "/Library/Frameworks/Python.framework/Versions/3.14/bin/python3",
    "/opt/homebrew/bin/python3",
    "/usr/bin/python3",
  ];
  const available = candidates.find((candidate) => existsSync(candidate));
  return available ?? "python3";
}

function resolveConfiguredPythonExecutable(): string | undefined {
  const configured = [
    process.env.RECRUIT_AGENT_PYTHON,
    process.env.PYTHON3,
    process.env.PYTHON,
  ].find((candidate): candidate is string => Boolean(candidate?.trim()));
  if (!configured) {
    return undefined;
  }
  return existsSync(configured) ? configured : undefined;
}

async function hasFilesystemPath(targetPath: string): Promise<boolean> {
  try {
    await access(targetPath);
    return true;
  } catch {
    return false;
  }
}

function startBackend(): Promise<void> {
  const [command, ...args] = resolveBackendCommand();
  const cwd = resolveBackendCwd();
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      cwd,
      env: {
        ...process.env,
        RECRUIT_AGENT_DESKTOP_MODE: "1",
      },
    });
    backendProcess = child;

    let settled = false;
    child.once("spawn", () => {
      settled = true;
      resolve();
    });
    child.once("error", (error) => {
      if (!settled) {
        settled = true;
        reject(error);
        return;
      }
      process.stderr.write(`[backend] startup error: ${error instanceof Error ? error.message : String(error)}\n`);
    });
    child.stdout.on("data", (chunk) => {
      process.stdout.write(`[backend] ${chunk}`);
    });
    child.stderr.on("data", (chunk) => {
      process.stderr.write(`[backend] ${chunk}`);
    });
  });
}

async function isBackendHealthy(): Promise<boolean> {
  try {
    const response = await fetch(backendHealthUrl);
    return response.ok;
  } catch {
    return false;
  }
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
    await window.loadURL(rendererOrigin);
    window.webContents.openDevTools({ mode: "detach" });
  } else {
    const rendererPath = path.join(__dirname, "../dist-renderer/index.html");
    await window.loadURL(pathToFileURL(rendererPath).toString());
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
    if (!(await isBackendHealthy())) {
      await startBackend();
    }
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
