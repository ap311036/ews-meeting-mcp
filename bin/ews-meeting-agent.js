#!/usr/bin/env node

import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

export function packageCacheName(packageName, version) {
  return `${packageName.replace(/[^a-zA-Z0-9._-]/g, "_")}_${version}`;
}

export function packagePythonPath(packageRoot) {
  return path.join(packageRoot, "src");
}

export function venvPythonPath(venvDir, platform = process.platform) {
  if (platform === "win32") {
    return path.join(venvDir, "Scripts", "python.exe");
  }
  return path.join(venvDir, "bin", "python");
}

export function buildPythonArgs(argv) {
  if (argv[0] === "--cli") {
    return ["-m", "ews_meeting_agent.cli", ...argv.slice(1)];
  }
  return ["-m", "ews_meeting_agent.mcp_server", ...argv];
}

function main() {
  if (process.argv[2] === "--help" || process.argv[2] === "-h") {
    printUsage();
    return;
  }

  const packageRoot = path.resolve(__dirname, "..");
  const packageJson = JSON.parse(
    fs.readFileSync(path.join(packageRoot, "package.json"), "utf8"),
  );
  const cacheDir = path.join(
    cacheBaseDir(),
    packageCacheName(packageJson.name, packageJson.version),
  );
  const python = ensurePythonRuntime(packageRoot, cacheDir);
  const pythonArgs = buildPythonArgs(process.argv.slice(2));
  const env = {
    ...process.env,
    PYTHONPATH: [packagePythonPath(packageRoot), process.env.PYTHONPATH]
      .filter(Boolean)
      .join(path.delimiter),
  };

  const child = spawnSync(python, pythonArgs, {
    cwd: process.cwd(),
    env,
    stdio: "inherit",
  });

  if (child.error) {
    console.error(child.error.message);
    process.exit(1);
  }
  process.exit(child.status ?? 1);
}

function cacheBaseDir() {
  if (process.env.EWS_MEETING_AGENT_CACHE_DIR) {
    return process.env.EWS_MEETING_AGENT_CACHE_DIR;
  }
  if (process.env.XDG_CACHE_HOME) {
    return path.join(process.env.XDG_CACHE_HOME, "ews-meeting-mcp");
  }
  if (process.platform === "darwin") {
    return path.join(os.homedir(), "Library", "Caches", "ews-meeting-mcp");
  }
  if (process.platform === "win32") {
    return path.join(process.env.LOCALAPPDATA || os.tmpdir(), "ews-meeting-mcp");
  }
  return path.join(os.homedir(), ".cache", "ews-meeting-mcp");
}

function ensurePythonRuntime(packageRoot, cacheDir) {
  if (process.env.EWS_MEETING_AGENT_PYTHON) {
    return process.env.EWS_MEETING_AGENT_PYTHON;
  }

  fs.mkdirSync(cacheDir, { recursive: true });
  const venvDir = path.join(cacheDir, "venv");
  const python = venvPythonPath(venvDir);
  const marker = path.join(cacheDir, "installed");
  const requirements = path.join(packageRoot, "requirements.txt");

  if (fs.existsSync(python) && fs.existsSync(marker)) {
    return python;
  }

  const basePython = findPython();
  runSetupCommand(basePython, ["-m", "venv", venvDir], "create Python virtualenv");
  runSetupCommand(
    python,
    ["-m", "pip", "install", "--upgrade", "-r", requirements],
    "install Python dependencies",
  );
  fs.writeFileSync(marker, new Date().toISOString());
  return python;
}

function findPython() {
  for (const candidate of ["python3", "python"]) {
    const result = spawnSync(candidate, ["--version"], {
      encoding: "utf8",
      stdio: ["ignore", "pipe", "pipe"],
    });
    if (result.status === 0) {
      return candidate;
    }
  }
  console.error("Python 3 is required to run ews-meeting-mcp.");
  process.exit(1);
}

function runSetupCommand(command, args, label) {
  const result = spawnSync(command, args, {
    encoding: "utf8",
    stdio: ["ignore", "ignore", "pipe"],
  });
  if (result.status !== 0) {
    console.error(`Failed to ${label}.`);
    if (result.stderr) {
      console.error(result.stderr.trim());
    }
    process.exit(result.status ?? 1);
  }
}

function printUsage() {
  console.log(`ews-meeting-mcp

Usage:
  ews-meeting-mcp                 Start the MCP stdio server
  ews-meeting-mcp --cli <args>    Run the Python CLI

Examples:
  ews-meeting-mcp
  ews-meeting-mcp --cli env
  ews-meeting-mcp --cli suggest --attendee alice@example.com --start 2026-06-15T09:00:00+08:00 --end 2026-06-19T18:00:00+08:00
`);
}

function isDirectEntrypoint() {
  if (!process.argv[1]) {
    return false;
  }
  return fs.realpathSync(process.argv[1]) === __filename;
}

if (isDirectEntrypoint()) {
  main();
}
