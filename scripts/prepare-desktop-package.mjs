import { cp, mkdir, readFile, rm, stat, writeFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import url from "node:url";

const scriptDir = path.dirname(url.fileURLToPath(import.meta.url));
const rootDir = path.resolve(scriptDir, "..");
const releaseDir = path.join(rootDir, ".release");
const backendSourceDir = path.join(rootDir, "services", "backend", "src");
const backendPyprojectPath = path.join(rootDir, "services", "backend", "pyproject.toml");
const backendDistDir = path.join(rootDir, "services", "backend", "dist");
const desktopPackageJsonPath = path.join(rootDir, "apps", "desktop", "package.json");
const desktopElectronDistDir = path.join(rootDir, "apps", "desktop", "node_modules", "electron", "dist");
const rootElectronPackageJsonPath = path.join(rootDir, "node_modules", "electron", "package.json");
const rootElectronDistDir = path.join(rootDir, "node_modules", "electron", "dist");

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

function getElectronBinaryPath(distDir) {
  return process.platform === "darwin"
    ? path.join(distDir, "Electron.app", "Contents", "MacOS", "Electron")
    : process.platform === "win32"
      ? path.join(distDir, "electron.exe")
      : path.join(distDir, "electron");
}

async function hasElectronRuntimeDist(distDir) {
  return pathExists(getElectronBinaryPath(distDir));
}

async function readJsonIfPresent(targetPath) {
  if (!(await pathExists(targetPath))) {
    return null;
  }

  return JSON.parse(await readFile(targetPath, "utf8"));
}

async function resolveElectronDistSource() {
  if (await hasElectronRuntimeDist(desktopElectronDistDir)) {
    return desktopElectronDistDir;
  }

  const desktopPackage = await readJsonIfPresent(desktopPackageJsonPath);
  const desktopElectronVersion = desktopPackage?.devDependencies?.electron ?? null;
  const rootElectronPackage = await readJsonIfPresent(rootElectronPackageJsonPath);
  const rootElectronVersion = rootElectronPackage?.version ?? null;

  if (
    desktopElectronVersion &&
    rootElectronVersion &&
    desktopElectronVersion === rootElectronVersion &&
    await hasElectronRuntimeDist(rootElectronDistDir)
  ) {
    return rootElectronDistDir;
  }

  return null;
}

async function main() {
  const stagedSourceDir = path.join(releaseDir, "backend-src");
  const stagedPyprojectDir = path.join(releaseDir, "backend-pyproject");
  const stagedDistDir = path.join(releaseDir, "backend-dist");
  const stagedElectronDistDir = path.join(releaseDir, "electron-dist");
  const existingStagedElectronRuntime = await hasElectronRuntimeDist(stagedElectronDistDir);
  const electronDistSourceDir = await resolveElectronDistSource();

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

  if (electronDistSourceDir) {
    await ensureEmptyDir(stagedElectronDistDir);
    await cp(electronDistSourceDir, stagedElectronDistDir, { recursive: true });
  } else {
    const stagedReadmePath = path.join(stagedElectronDistDir, "README.txt");
    const shouldWriteMissingRuntimeReadme =
      !existingStagedElectronRuntime || await pathExists(stagedReadmePath);

    if (shouldWriteMissingRuntimeReadme) {
      await ensureEmptyDir(stagedElectronDistDir);
      await writeFile(
        stagedReadmePath,
        "Electron runtime dist is missing from apps/desktop/node_modules/electron/dist and no staged runtime was preserved.\n",
        "utf8",
      );
    }
  }
}

await main();
