import { access, readFile, stat } from "node:fs/promises";
import { execFile } from "node:child_process";
import path from "node:path";
import process from "node:process";
import url from "node:url";
import { promisify } from "node:util";

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
const execFileAsync = promisify(execFile);

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

function detectNotarizationConfiguration() {
  const env = process.env;
  const hasApiKey = Boolean(env.APPLE_API_KEY || env.APPLE_API_KEY_ID || env.APPLE_API_ISSUER);
  const hasAppleId = Boolean(env.APPLE_ID || env.APPLE_APP_SPECIFIC_PASSWORD || env.APPLE_TEAM_ID);
  const hasKeychain = Boolean(env.APPLE_KEYCHAIN || env.APPLE_KEYCHAIN_PROFILE);

  if (hasApiKey) {
    const missing = ["APPLE_API_KEY", "APPLE_API_KEY_ID", "APPLE_API_ISSUER"].filter((key) => !env[key]);
    return {
      mode: "api-key",
      ready: missing.length === 0,
      missing,
    };
  }

  if (hasAppleId) {
    const missing = ["APPLE_ID", "APPLE_APP_SPECIFIC_PASSWORD", "APPLE_TEAM_ID"].filter((key) => !env[key]);
    return {
      mode: "apple-id",
      ready: missing.length === 0,
      missing,
    };
  }

  if (hasKeychain) {
    const missing = ["APPLE_KEYCHAIN_PROFILE"].filter((key) => !env[key]);
    return {
      mode: "keychain-profile",
      ready: missing.length === 0,
      missing,
    };
  }

  return {
    mode: "none",
    ready: false,
    missing: [],
  };
}

async function listCodeSigningIdentities() {
  if (process.platform !== "darwin") {
    return [];
  }

  try {
    const { stdout } = await execFileAsync("/usr/bin/security", ["find-identity", "-v", "-p", "codesigning"]);
    return Array.from(stdout.matchAll(/"([^"]+)"/g), (match) => match[1]).filter(Boolean);
  } catch {
    return [];
  }
}

async function inspectDistributionReadiness() {
  const identities = await listCodeSigningIdentities();
  const developerIdIdentities = identities.filter((identity) => identity.includes("Developer ID Application:"));
  const notarization = detectNotarizationConfiguration();
  const cscLinkPresent = Boolean(process.env.CSC_LINK);
  const cscKeyPasswordPresent = Boolean(process.env.CSC_KEY_PASSWORD);
  const cscName = process.env.CSC_NAME?.trim() || null;

  let signingMode = "none";
  let signingReady = false;
  let selectedIdentity = null;
  let signingIssues = [];

  if (cscLinkPresent || cscKeyPasswordPresent) {
    signingMode = "csc-link";
    signingReady = cscLinkPresent && cscKeyPasswordPresent;
    if (!cscLinkPresent) {
      signingIssues.push("CSC_LINK");
    }
    if (!cscKeyPasswordPresent) {
      signingIssues.push("CSC_KEY_PASSWORD");
    }
  } else if (developerIdIdentities.length > 0) {
    signingMode = "local-developer-id";
    if (cscName) {
      selectedIdentity = developerIdIdentities.find((identity) => identity.includes(cscName)) ?? null;
      signingReady = selectedIdentity !== null;
      if (!signingReady) {
        signingIssues.push("CSC_NAME does not match an installed Developer ID Application identity");
      }
    } else {
      selectedIdentity = developerIdIdentities[0];
      signingReady = true;
    }
  } else if (cscName) {
    signingMode = "local-developer-id";
    signingIssues.push("CSC_NAME is set but no installed Developer ID Application identity was found");
  } else {
    signingMode = "none";
    signingIssues.push("missing Developer ID Application identity or CSC_LINK/CSC_KEY_PASSWORD");
  }

  return {
    detectedCodeSigningIdentities: identities.length,
    developerIdApplicationIdentities: developerIdIdentities,
    signingMode,
    signingReady,
    selectedIdentity,
    signingIssues,
    notarizationMode: notarization.mode,
    notarizationReady: notarization.ready,
    notarizationMissing: notarization.missing,
    distributionReady: signingReady && notarization.ready,
  };
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
  const requireDistribution = process.argv.includes("--require-distribution");
  const electron = await inspectElectronInstall();
  const distribution = await inspectDistributionReadiness();

  await ensurePath(stagedBackendSourcePath, "Staged backend source bundle");
  await ensurePath(stagedBackendPyprojectPath, "Staged backend pyproject");
  await ensurePath(stagedBackendDistPath, "Staged backend distribution folder");

  if (checkBuildOutputs) {
    await ensurePath(rendererEntryPath, "Renderer build output");
    await ensurePath(electronMainPath, "Electron main build output");
  }

  const stagedBackendDistStats = await stat(stagedBackendDistPath);
  const mode = checkBuildOutputs ? "release" : "prepare";

  if (requireDistribution && !distribution.distributionReady) {
    const problems = [
      ...(distribution.signingReady ? [] : [`signing not ready (${distribution.signingIssues.join(", ")})`]),
      ...(distribution.notarizationReady ? [] : [`notarization not ready (${distribution.notarizationMissing.join(", ") || "missing Apple notarization credentials"})`]),
    ];
    throw new Error(`Distribution release requirements are not met: ${problems.join("; ")}`);
  }

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
        signingMode: distribution.signingMode,
        signingReady: distribution.signingReady,
        selectedSigningIdentity: distribution.selectedIdentity,
        detectedCodeSigningIdentities: distribution.detectedCodeSigningIdentities,
        developerIdApplicationIdentities: distribution.developerIdApplicationIdentities,
        notarizationMode: distribution.notarizationMode,
        notarizationReady: distribution.notarizationReady,
        notarizationMissing: distribution.notarizationMissing,
        distributionReady: distribution.distributionReady,
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
