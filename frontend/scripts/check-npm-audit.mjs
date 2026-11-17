#!/usr/bin/env node
/**
 * Enforce the production npm audit and narrowly allow the currently unpatched
 * development-only picomatch CVE-2026-112366 dependency chain.
 *
 * This is an explicit temporary VEX-style exception, not a claim that the
 * development dependency is fixed. The exception is valid only while every
 * affected package remains development-only and no unrelated audit finding
 * appears. Remove this file and return to a blocking full npm audit when the
 * upstream picomatch release contains the fix.
 */
import { spawnSync } from "node:child_process";

const ADVISORY = "https://github.com/advisories/GHSA-fc5q-39xc-vjpf";
const ALLOWED_DEV_CHAIN = new Set([
  "picomatch",
  "fdir",
  "tinyglobby",
  "vite",
  "@vitejs/plugin-react",
  "vitest",
]);

function run(command, args) {
  const result = spawnSync(command, args, {
    encoding: "utf8",
    maxBuffer: 16 * 1024 * 1024,
  });
  if (result.error) throw result.error;
  return result;
}

function parseJson(output, label) {
  try {
    return JSON.parse(output);
  } catch {
    throw new Error(`${label} did not return valid JSON`);
  }
}

function hasDependency(tree, name) {
  for (const [dependency, metadata] of Object.entries(tree?.dependencies ?? {})) {
    if (dependency === name || hasDependency(metadata, name)) return true;
  }
  return false;
}

const production = run("npm", ["ls", "--omit=dev", "--json"]);
if (production.status !== 0) {
  process.stderr.write(production.stderr || production.stdout);
  throw new Error("Could not verify the production dependency tree");
}
const productionTree = parseJson(production.stdout, "npm ls --omit=dev");
const audit = run("npm", ["audit", "--json"]);
const report = parseJson(audit.stdout, "npm audit");
const findings = Object.entries(report.vulnerabilities ?? {});

if (findings.length === 0) {
  if (audit.status !== 0) {
    process.stderr.write(audit.stderr || audit.stdout);
    throw new Error("npm audit failed without a parseable vulnerability report");
  }
  process.stdout.write("Full npm audit passed with no reported vulnerabilities.\n");
  process.exit(0);
}

const unexpected = [];
for (const [name, vulnerability] of findings) {
  if (!ALLOWED_DEV_CHAIN.has(name)) {
    unexpected.push(`${name}: package is outside the temporary allowlist`);
    continue;
  }
  if (hasDependency(productionTree, name)) {
    unexpected.push(`${name}: vulnerable package is present in production dependencies`);
    continue;
  }
  const via = vulnerability.via ?? [];
  if (
    via.length === 0 ||
    via.some((item) => {
      if (typeof item === "string") return !ALLOWED_DEV_CHAIN.has(item);
      return item.url !== ADVISORY && !ALLOWED_DEV_CHAIN.has(item.name);
    })
  ) {
    unexpected.push(`${name}: finding is not exclusively explained by ${ADVISORY}`);
  }
}

if (unexpected.length > 0) {
  process.stderr.write(unexpected.join("\n") + "\n");
  process.stderr.write(audit.stdout);
  throw new Error("npm audit found an unapproved or production-reachable vulnerability");
}

process.stdout.write(
  [
    "TEMPORARY SECURITY EXCEPTION: npm audit reports the known picomatch CVE-2026-112366",
    "through the Vite/Vitest development-tool dependency chain.",
    "All affected packages are verified absent from the production dependency tree.",
    "Production dependencies remain blocking-audited separately in CI.",
    "This is not a package fix; remove this exception when upstream releases a patched picomatch.",
    "",
  ].join("\n"),
);
