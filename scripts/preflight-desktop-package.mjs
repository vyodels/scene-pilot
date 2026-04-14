import { access, readFile, stat } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import url from "node:url";

const scriptDir = path.dirname(url.fileURLToPath(import.meta.url));
const rootDir = path.resolve(scriptDir, "..");
const releaseDir = path.join(rootDir, ".release");
const electronPackageJsonPath = path.join(rootDir, "node_modules", "electron", "package.json");
const rendererEntryPath = path.join(rootDir, "apps", "desktop", "dist-renderer", "index.html");
const electronMainPath = path.join(rootDir, "apps", "desktop", "dist-electron", "electron", "main.js");
const stagedBackendSourcePath = path.join(releaseDir, "backend-src", "recruit_agent");
const stagedBackendPyprojectPath = path.join(releaseDir, "backend-pyproject", "pyproject.toml");
const stagedBackendDistPath = path.join(releaseDir, "backend-dist");

async function pathExists(targetPath) {
  try {
    await access(targetPath);
    return true;
  } catch {
    return false;
  }
}

async function ensurePath(targetPath, description) {
  if (await pathExists(targetPath)) {
    return;
  }
  throw new Error(`${description} is missing at ${path.relative(rootDir, targetPath)}`);
}

async function inspectElectronInstall() {
  if (!(await pathExists(electronPackageJsonPath))) {
    throw new Error(
      "Electron package is not installed. Run `npm install --ignore-scripts=false` on a machine that can download Electron binaries.",
    );
  }

  const electronPackage = JSON.parse(await readFile(electronPackageJsonPath, "utf8"));
  const packageVersion = electronPackage?.version;
  const electronModuleDir = path.dirname(electronPackageJsonPath);
  const packagedBinary = process.platform === "darwin"
    ? path.join(electronModuleDir, "dist", "Electron.app", "Contents", "MacOS", "Electron")
    : process.platform === "win32"
      ? path.join(electronModuleDir, "dist", "electron.exe")
      : path.join(electronModuleDir, "dist", "electron");

  if (!(await pathExists(packagedBinary))) {
    throw new Error(
      `Electron runtime binary is missing for electron@${packageVersion ?? "unknown"}. Reinstall with scripts enabled on a machine with registry access.`,
    );
  }

  return {
    packageVersion: packageVersion ?? "unknown",
    packagedBinary,
  };
}

async function main() {
  const checkBuildOutputs = process.argv.includes("--require-build");
  const electron = await inspectElectronInstall();

  await ensurePath(stagedBackendSourcePath, "Staged backend source bundle");
  await ensurePath(stagedBackendPyprojectPath, "Staged backend pyproject");
  await ensurePath(stagedBackendDistPath, "Staged backend distribution folder");

  if (checkBuildOutputs) {
    await ensurePath(rendererEntryPath, "Renderer build output");
    await ensurePath(electronMainPath, "Electron main build output");
  }

  const stagedBackendDistStats = await stat(stagedBackendDistPath);
  const mode = checkBuildOutputs ? "release" : "prepare";
  console.log(
    JSON.stringify(
      {
        ok: true,
        mode,
        electronVersion: electron.packageVersion,
        electronBinary: path.relative(rootDir, electron.packagedBinary),
        stagedBackendDistDirectory: path.relative(rootDir, stagedBackendDistPath),
        stagedBackendDistPresent: stagedBackendDistStats.isDirectory(),
      },
      null,
      2,
    ),
  );
}

main().catch((error) => {
  const message = error instanceof Error ? error.message : String(error);
  console.error(`[desktop-release-preflight] ${message}`);
  process.exitCode = 1;
});
