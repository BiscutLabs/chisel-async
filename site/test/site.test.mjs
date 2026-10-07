import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { normalizeBase, rewriteLink, createMarkdown, escape } from "../lib.mjs";
import { checkLink } from "../check.mjs";

test("guide links keep project prefix, query strings and anchors", () => {
  assert.equal(
    rewriteLink("testing.md#clocked-tests", "docs/index.md", "/chisel-async/"),
    "/chisel-async/docs/testing/#clocked-tests",
  );
  assert.equal(rewriteLink("index.md", "docs/concepts.md", "/"), "/docs/");
  assert.equal(
    rewriteLink("concepts.md?q=reset#reset", "docs/index.md", "/preview/"),
    "/preview/docs/concepts/?q=reset#reset",
  );
  assert.equal(rewriteLink("#local", "docs/index.md", "/"), "#local");
});
test("source and archive links retain repository identity at the built revision", () => {
  assert.equal(
    rewriteLink(
      "../src/main/scala/Foo.scala#L2",
      "docs/index.md",
      "/",
      "abc123",
    ),
    "https://github.com/BiscutLabs/chisel-async/blob/abc123/src/main/scala/Foo.scala#L2",
  );
  assert.match(
    rewriteLink("archive/README.md", "docs/index.md", "/"),
    /github.com\/BiscutLabs\/chisel-async\/blob\/main\/docs\/archive\/README.md$/,
  );
  assert.equal(
    rewriteLink("https://example.com/x.md", "docs/index.md", "/"),
    "https://example.com/x.md",
  );
});
test("invalid base paths and links outside the repository fail", () => {
  for (const value of ["chisel-async", "/chisel-async", "//", "/../", "/a b/"])
    assert.throws(() => normalizeBase(value), /SITE_BASE/);
  assert.throws(
    () => rewriteLink("../../secret", "docs/index.md", "/"),
    /escapes repository/,
  );
});
test("Markdown produces stable unique anchors and preserves literal code", () => {
  const md = createMarkdown(
    (code) => `<pre><code>${escape(code)}</code></pre>`,
    "/chisel-async/",
    "abc123",
  );
  const env = { source: "docs/index.md" };
  const html = md.render(
    "# Typed `Channel[T]`\n\n## Reset\n\n## Reset\n\n[Tests](testing.md)\n\n```scala\na < b && c\n```\n\n<script>alert(1)</script>",
    env,
  );
  assert.deepEqual(
    env.headings.map((h) => h.id),
    ["typed-channelt", "reset", "reset-1"],
  );
  assert.match(html, /href="\/chisel-async\/docs\/testing\/"/);
  assert.match(html, /a &lt; b &amp;&amp; c/);
  assert.ok(!html.includes("<script>"));
});
test("link checker rejects missing pages, missing anchors, and root-relative project leaks", async () => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "ca-site-"));
  try {
    await fs.writeFile(
      path.join(directory, "index.html"),
      '<h1 id="present">Hello</h1>',
    );
    await checkLink("/project/#present", "index.html", directory, "/project/");
    await assert.rejects(
      checkLink("/project/missing/", "index.html", directory, "/project/"),
      /Missing target/,
    );
    await assert.rejects(
      checkLink("#missing", "index.html", directory, "/project/"),
      /Missing anchor/,
    );
    await assert.rejects(
      checkLink("/docs/", "index.html", directory, "/project/"),
      /escapes Pages base/,
    );
  } finally {
    await fs.rm(directory, { recursive: true, force: true });
  }
});
