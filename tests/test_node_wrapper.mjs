import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { test } from "node:test";
import {
  buildPythonArgs,
  packageCacheName,
  packagePythonPath,
  venvPythonPath,
} from "../bin/ews-meeting-agent.js";

test("package cache name is safe for scoped npm packages", () => {
  assert.equal(packageCacheName("@company/ews-meeting-mcp", "0.1.0"), "_company_ews-meeting-mcp_0.1.0");
});

test("venv python path uses platform-specific executable", () => {
  assert.equal(venvPythonPath("/tmp/cache", "win32"), "/tmp/cache/Scripts/python.exe");
  assert.equal(venvPythonPath("/tmp/cache", "darwin"), "/tmp/cache/bin/python");
});

test("package python path points to bundled src directory", () => {
  assert.equal(packagePythonPath("/pkg/root"), "/pkg/root/src");
});

test("default mode launches MCP server", () => {
  assert.deepEqual(buildPythonArgs([]), ["-m", "ews_meeting_mcp.mcp_server"]);
});

test("cli mode launches original Python CLI with passthrough args", () => {
  assert.deepEqual(buildPythonArgs(["--cli", "env"]), ["-m", "ews_meeting_mcp.cli", "env"]);
});

test("bin entrypoint runs when invoked through an npm-style symlink", () => {
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "ews-meeting-mcp-bin-"));
  const symlinkPath = path.join(tempDir, "ews-meeting-mcp");
  const binPath = path.resolve("bin/ews-meeting-agent.js");
  fs.symlinkSync(binPath, symlinkPath);

  const result = spawnSync(process.execPath, [symlinkPath, "--help"], {
    encoding: "utf8",
  });

  assert.equal(result.status, 0);
  assert.match(result.stdout, /Start the MCP stdio server/);
});
