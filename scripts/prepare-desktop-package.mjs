import { cp, mkdir, rm, stat, writeFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import url from "node:url";

const scriptDir = path.dirname(url.fileURLToPath(import.meta.url));
const rootDir = path.resolve(scriptDir, "..");
const releaseDir = path.join(rootDir, ".release");
const backendSourceDir = path.join(rootDir, "services", "backend", "src");
const backendPyprojectPath = path.join(rootDir, "services", "backend", "pyproject.toml");
const backendDistDir = path.join(rootDir, "services", "backend", "dist");

async function pathExists(targetPath) {
  try {
    await stat(targetPath);
    return true;
  } catch {
    return false;
  }
}

async function ensureEmptyDir(targetPath) {
  await rm(targetPath, { recursive: true, force: true });
  await mkdir(targetPath, { recursive: true });
}

async function main() {
  const stagedSourceDir = path.join(releaseDir, "backend-src");
  const stagedPyprojectDir = path.join(releaseDir, "backend-pyproject");
  const stagedDistDir = path.join(releaseDir, "backend-dist");

  await ensureEmptyDir(stagedSourceDir);
  await ensureEmptyDir(stagedPyprojectDir);
  await ensureEmptyDir(stagedDistDir);

  await cp(backendSourceDir, stagedSourceDir, { recursive: true });
  await cp(backendPyprojectPath, path.join(stagedPyprojectDir, "pyproject.toml"));

  if (await pathExists(backendDistDir)) {
    await cp(backendDistDir, stagedDistDir, { recursive: true });
  } else {
    await writeFile(
      path.join(stagedDistDir, "README.txt"),
      "No packaged backend executable is available. The desktop app will fall back to source-mode backend startup.\n",
      "utf8",
    );
  }
}

await main();
