import { access, readFile, stat } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import url from "node:url";

const scriptDir = path.dirname(url.fileURLToPath(import.meta.url));
const rootDir = path.resolve(scriptDir, "..");
const releaseDir = path.join(rootDir, ".release");
const desktopDir = path.join(rootDir, "apps", "desktop");
const electronPackageJsonPath = path.join(desktopDir, "node_modules", "electron", "package.json");
const stagedElectronDistPath = path.join(releaseDir, "electron-dist");
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
  const packagedBinaryPresent = await pathExists(packagedBinary);

  const stagedBinary = process.platform === "darwin"
    ? path.join(stagedElectronDistPath, "Electron.app", "Contents", "MacOS", "Electron")
    : process.platform === "win32"
      ? path.join(stagedElectronDistPath, "electron.exe")
      : path.join(stagedElectronDistPath, "electron");

  if (!(await pathExists(stagedBinary))) {
    throw new Error(
      `Staged Electron runtime is missing at ${path.relative(rootDir, stagedBinary)}. Run \`npm run desktop:release:prepare\` first.`,
    );
  }

  return {
    packageVersion: packageVersion ?? "unknown",
    packagedBinary: packagedBinaryPresent ? packagedBinary : null,
    packagedBinaryPresent,
    stagedBinary,
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
        electronBinary: electron.packagedBinary ? path.relative(rootDir, electron.packagedBinary) : null,
        electronBinaryPresent: electron.packagedBinaryPresent,
        stagedElectronBinary: path.relative(rootDir, electron.stagedBinary),
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
