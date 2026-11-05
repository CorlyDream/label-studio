#!/usr/bin/env node

import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";

/**
 * Bun test runner with an isolated editor integration suite.
 *
 * - Discovers test files under provided roots
 * - Sorts files lexicographically for deterministic order
 * - Runs upstream unit tests together and real-editor integration in a fresh process
 * - Bun treats unprefixed unit paths as filters, so their execution order may differ
 *
 * Usage:
 *   node scripts/bun-test-ordered.mjs [roots...] -- [bun test args...]
 *
 * Examples:
 *   node scripts/bun-test-ordered.mjs libs/editor/src
 *   node scripts/bun-test-ordered.mjs libs/editor/src -- --bail=1 --only-failures
 *   node scripts/bun-test-ordered.mjs libs/editor/src -- --max-concurrency=20
 */

const rawArgs = process.argv.slice(2);

if (rawArgs.includes("-h") || rawArgs.includes("--help")) {
  console.log(`Ordered Bun test runner

Usage:
  node scripts/bun-test-ordered.mjs [roots...] -- [bun args...]

Notes:
  - roots default to "." when omitted
  - file selection is sorted; upstream unit execution order is controlled by Bun
  - drawing-hotkeys runs in a fresh process with a separate coverage report
  - concurrency is controlled by Bun args; not overridden here
`);
  process.exit(0);
}

const separatorIndex = rawArgs.indexOf("--");
const targets = separatorIndex >= 0 ? rawArgs.slice(0, separatorIndex) : rawArgs;
const bunArgs = separatorIndex >= 0 ? rawArgs.slice(separatorIndex + 1) : [];

const roots = targets.length > 0 ? targets : ["."];
const skipDirs = new Set(["node_modules", ".git", "coverage", "dist", "build", ".nx", ".turbo"]);

const isTestFile = (filePath) => {
  const normalized = filePath.split(path.sep).join("/");
  const isInTestsDir = normalized.includes("/__tests__/");
  const hasTestLikeName = /\.(test|spec)\.(js|jsx|ts|tsx)$/.test(normalized);
  const hasSupportedExt = /\.(js|jsx|ts|tsx)$/.test(normalized);
  return hasTestLikeName || (isInTestsDir && hasSupportedExt);
};

const collectFiles = (entryPath, out) => {
  const absPath = path.resolve(entryPath);
  if (!fs.existsSync(absPath)) return;

  const stat = fs.statSync(absPath);
  if (stat.isFile()) {
    if (isTestFile(absPath)) out.push(absPath);
    return;
  }

  if (!stat.isDirectory()) return;

  for (const entry of fs.readdirSync(absPath, { withFileTypes: true })) {
    if (entry.isDirectory() && skipDirs.has(entry.name)) continue;
    collectFiles(path.join(absPath, entry.name), out);
  }
};

const files = [];
for (const root of roots) collectFiles(root, files);

/** Fixed "en-US" + numeric sort — host-default localeCompare() differs across macOS vs Linux. */
const pathOrder = new Intl.Collator("en-US", { numeric: true, sensitivity: "variant" });
const uniqueSortedFiles = [...new Set(files)]
  .map((absPath) => path.relative(process.cwd(), absPath))
  .sort((a, b) => pathOrder.compare(a, b));

if (!uniqueSortedFiles.length) {
  console.error("No test files found for provided paths.");
  process.exit(1);
}

function resolveBunExecutable() {
  const candidates = [
    path.resolve("node_modules/.bin/bun"),
    path.resolve("node_modules/.bin/bun.exe"),
    path.resolve("node_modules/.bin/bun.cmd"),
  ];
  for (const p of candidates) {
    if (fs.existsSync(p)) return p;
  }
  return "bun";
}

const bunBin = resolveBunExecutable();
// This suite starts a real editor. Region unit suites replace shared Registry/model
// modules, so it needs a fresh process rather than relying on mock cleanup/order.
const editorIntegration = "libs/editor/src/stores/Annotation/__tests__/label-drawing-hotkeys.test.js";
const integrationFiles = uniqueSortedFiles.filter((file) => file === editorIntegration);
const unitFiles = uniqueSortedFiles.filter((file) => file !== editorIntegration);
let exitCode = 0;
for (const [name, files] of [
  ["unit", unitFiles],
  ["drawing-hotkeys", integrationFiles],
]) {
  if (!files.length) continue;
  const coverageArgs = name !== "unit" && bunArgs.includes("--coverage") ? ["--coverage-dir", `coverage/${name}`] : [];
  // Use an explicit path for the isolated suite. Keep existing discovery behavior
  // for upstream unit tests until their shared mocks are independently isolated.
  const paths = name === "unit" ? files : files.map((file) => `./${file}`);
  const args = ["test", "--dom", ...bunArgs, ...coverageArgs, ...paths];
  const result = spawnSync(bunBin, args, { stdio: "inherit", env: process.env });
  if (result.error) {
    console.error(`bun-test-ordered: failed to run "${bunBin}": ${result.error.message}`);
  }
  if (result.error || result.status !== 0) exitCode = 1;
}
process.exit(exitCode);
