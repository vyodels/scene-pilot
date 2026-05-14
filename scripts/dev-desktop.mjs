import { spawn } from "node:child_process";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "..");
const appDir = path.join(repoRoot, "apps", "desktop");
const electronEntry = path.join(appDir, "dist-electron", "electron", "main.js");
const rendererOrigin = process.env.RECRUIT_AGENT_DESKTOP_RENDERER_URL ?? "http://127.0.0.1:5174";
const remoteDebugPort = process.env.RECRUIT_AGENT_ELECTRON_REMOTE_DEBUG_PORT ?? "9222";
const viteCommand = process.platform === "win32" ? "npm.cmd" : "npm";
const electronCommand = path.join(
  repoRoot,
  "node_modules",
  ".bin",
  process.platform === "win32" ? "electron.cmd" : "electron",
);

let shuttingDown = false;
const childProcesses = [];

function spawnChild(command, args, options = {}) {
  const child = spawn(command, args, {
    cwd: repoRoot,
    stdio: "inherit",
    env: process.env,
    ...options,
  });
  childProcesses.push(child);
  child.on("exit", (code, signal) => {
    if (shuttingDown) {
      return;
    }
    if (signal != null) {
      shutdown(signal === "SIGINT" ? 130 : 1);
      return;
    }
    if (code && code !== 0) {
      shutdown(code);
    }
  });
  return child;
}

function runCommand(command, args, options = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      cwd: repoRoot,
      stdio: "inherit",
      env: process.env,
      ...options,
    });
    child.on("exit", (code, signal) => {
      if (signal != null) {
        reject(new Error(`${command} terminated by ${signal}`));
        return;
      }
      if (code && code !== 0) {
        reject(new Error(`${command} exited with ${code}`));
        return;
      }
      resolve();
    });
  });
}

async function waitForRenderer(url, timeoutMs = 20_000) {
  const deadline = Date.now() + timeoutMs;
  let lastError;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url);
      if (response.ok) {
        return;
      }
      lastError = new Error(`Renderer responded with ${response.status}`);
    } catch (error) {
      lastError = error;
    }
    await new Promise((resolve) => setTimeout(resolve, 300));
  }
  throw lastError instanceof Error ? lastError : new Error("Renderer health check timed out");
}

function shutdown(code = 0) {
  if (shuttingDown) {
    return;
  }
  shuttingDown = true;
  for (const child of childProcesses) {
    if (!child.killed) {
      child.kill("SIGTERM");
    }
  }
  process.exit(code);
}

process.on("SIGINT", () => shutdown(130));
process.on("SIGTERM", () => shutdown(143));

const viteProcess = spawnChild(viteCommand, [
  "--workspace",
  "apps/desktop",
  "run",
  "dev:renderer",
  "--",
  "--host",
  "127.0.0.1",
]);

try {
  await waitForRenderer(rendererOrigin);
  await runCommand(viteCommand, ["--workspace", "apps/desktop", "run", "electron:build"]);
  const electronProcess = spawnChild(electronCommand, [electronEntry], {
    cwd: appDir,
    env: {
      ...process.env,
      RECRUIT_AGENT_DESKTOP_RENDERER_URL: rendererOrigin,
      RECRUIT_AGENT_ELECTRON_REMOTE_DEBUG_PORT: remoteDebugPort,
    },
  });
  await new Promise((resolve, reject) => {
    electronProcess.on("exit", (code) => {
      if (shuttingDown) {
        resolve();
        return;
      }
      if (code && code !== 0) {
        reject(new Error(`Electron exited with ${code}`));
        return;
      }
      resolve();
    });
    viteProcess.on("exit", (code) => {
      if (shuttingDown) {
        resolve();
        return;
      }
      if (code && code !== 0) {
        reject(new Error(`Renderer exited with ${code}`));
      }
    });
  });
} catch (error) {
  console.error("[desktop:dev]", error instanceof Error ? error.message : String(error));
  shutdown(1);
}
