/** Offline integration regression: only pinned Git archives, never a Store working tree. */
import assert from "node:assert/strict";
import { execFileSync, spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { cpSync, existsSync, mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { after, test } from "node:test";

const storefront = process.env.CATALOG_TEST_STOREFRONT;
const dependencies = process.env.CATALOG_TEST_NODE_MODULES;
assert.ok(storefront, "set CATALOG_TEST_STOREFRONT to a read-only local Store Git repository");
assert.ok(dependencies, "set CATALOG_TEST_NODE_MODULES to existing Store dependencies (no install)");
const exporter = readFileSync(join(import.meta.dirname, "export.ts"));
const revisions = {
  main: "3c8cbc29a990347549340b05f80de98f12a26bf3",
  legacy: "88d6d0add414261e5ccf5bd3e2b21285e1a33179",
  paired: "d160a9524feb306e0a20e4a98fe5428174eafcc0",
} as const;
const generatedAt = "2026-10-18T00:00:00Z";
// Historical raw UTF-8 outputs, including trailing newline, at this exact generatedAt/origin.
// Historical exporter revision: 04ad01a2f7690433d170519ea4581ca5983cd71a (provenance only; never loaded).
// Prior exporter SHA-256: 0b7aa611d1757a65b2bd45afc5396c103bec92bd0d0036b36ea4baa8bc0423da.
const legacyOutputSha256 = {
  [revisions.main]: "9765f180b2827a1adad172f54465889ba67b5da9e594835a18805773e9aa25dd",
  [revisions.legacy]: "4bf6b82fa2143cbe29bc85b5db3348c81b2154dc252830b6935a913b602570b8",
};
const temporary = mkdtempSync(join(tmpdir(), "pv-export-layout-"));
after(() => rmSync(temporary, { recursive: true, force: true }));

function archive(name: string, revision: string): string {
  const tree = join(temporary, name);
  execFileSync("mkdir", [tree]);
  const source = execFileSync("git", [
    "-C", storefront!, "archive", revision, "config", "content", "src", "media/manifest.json",
  ], { maxBuffer: 16 * 1024 * 1024 });
  execFileSync("tar", ["-x", "-C", tree], { input: source });
  symlinkSync(resolve(dependencies!), join(tree, "node_modules"), "dir");
  return tree;
}

function run(tree: string, revision: string) {
  const script = join(tree, "__assistant_export.ts");
  writeFileSync(script, exporter);
  return spawnSync(process.execPath, [script, "https://pequeverso.com", revision, generatedAt], {
    cwd: tree,
    env: { PATH: process.env.PATH, NEXT_PUBLIC_SITE_URL: "https://pequeverso.com" },
    encoding: "utf8",
    timeout: 5000,
    maxBuffer: 1024 * 1024,
  });
}

function successful(tree: string, revision: string): string {
  const result = run(tree, revision);
  assert.equal(result.status, 0, result.stderr || String(result.error));
  const catalog = JSON.parse(result.stdout);
  assert.equal(catalog.source.revision, revision);
  assert.equal(catalog.generated_at, generatedAt);
  if (process.env.CATALOG_TEST_OUTPUT) {
    const output = join(process.env.CATALOG_TEST_OUTPUT, `${revision}-current.json`);
    if (existsSync(output)) assert.equal(readFileSync(output, "utf8"), result.stdout);
    else writeFileSync(output, result.stdout, { flag: "wx" });
  }
  return result.stdout;
}

test("legacy raw exports match frozen prior-exporter SHA-256 goldens at main and reviewed header", () => {
  for (const revision of [revisions.main, revisions.legacy]) {
    const tree = archive(revision, revision);
    const actual = createHash("sha256").update(successful(tree, revision)).digest("hex");
    assert.equal(actual, legacyOutputSha256[revision]);
  }
});

test("paired source exports identical facts, retaining exact source provenance and producer detail", () => {
  const legacy = JSON.parse(successful(archive("legacy-equivalence", revisions.legacy), revisions.legacy));
  const paired = JSON.parse(successful(archive("paired-equivalence", revisions.paired), revisions.paired));
  const overview = paired.documents.find((document: { id: string }) => document.id === "affiliate.alimentacion-bebe.overview");
  assert.match(overview.text, /6 módulos en video/);
  assert.match(overview.text, /4 bonos/);
  // Normalize only metadata explicitly owned by the invocation, never business facts.
  delete legacy.source.revision;
  delete paired.source.revision;
  delete legacy.generated_at;
  delete paired.generated_at;
  assert.deepEqual(paired, legacy);
});

test("partial and mixed reviewed layouts fail closed without catalog output", () => {
  const partial = archive("partial", revisions.paired);
  rmSync(join(partial, "src/shared/media/media.ts"));
  const mixed = archive("mixed", revisions.paired);
  const old = archive("mixed-legacy-input", revisions.legacy);
  cpSync(join(old, "src/lib"), join(mixed, "src/lib"), { recursive: true });
  cpSync(join(old, "src/products"), join(mixed, "src/products"), { recursive: true });
  for (const tree of [partial, mixed]) {
    const result = run(tree, revisions.paired);
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, /unsupported storefront source layout/);
    assert.equal(result.stdout, "");
  }
});

test("a selected registry import failure is surfaced without another-layout fallback", () => {
  const tree = archive("broken-paired-registry", revisions.paired);
  rmSync(join(tree, "config/products/schema.ts"));
  const result = run(tree, revisions.paired);
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /ERR_MODULE_NOT_FOUND/);
  assert.equal(result.stdout, "");
});
