import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { execFileSync } from "node:child_process";
import { createHighlighter } from "shiki";
import { build } from "esbuild";
import { circuitArtwork } from "./circuit-art.mjs";
import {
  repository,
  navigation,
  pages,
  escape,
  docRoute,
  normalizeBase,
  createMarkdown,
} from "./lib.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.dirname(here);
const output = path.join(here, "dist");
const base = normalizeBase(process.env.SITE_BASE || "/chisel-async/");
const origin = "https://biscutlabs.github.io";
const commit = execFileSync("git", ["rev-parse", "HEAD"], {
  cwd: root,
  encoding: "utf8",
}).trim();
const settings = await fs.readFile(path.join(root, "build.sbt"), "utf8");
const version = settings.match(/ThisBuild \/ version := "([^"]+)"/)[1];
const scala = settings.match(/ThisBuild \/ scalaVersion := "([^"]+)"/)[1];
const chisel = settings.match(/(?:val|lazy val) chiselVersion = "([^"]+)"/)[1];
const api = path.join(root, "target/scala-2.13/api");
await fs.access(path.join(api, "index.html")).catch(() => {
  throw new Error(
    "Scaladoc is required. Run python tools/sbt.py doc before building the website.",
  );
});
// Only ever replace this generator's fixed output directory.
if (path.dirname(output) !== here || path.basename(output) !== "dist")
  throw new Error("Unsafe output directory");
await fs.rm(output, { recursive: true, force: true });
await fs.mkdir(path.join(output, "assets"), { recursive: true });
await fs.cp(api, path.join(output, "api/scala"), {
  recursive: true,
  dereference: true,
});
await fs.copyFile(
  path.join(here, "styles.css"),
  path.join(output, "assets/site.css"),
);
await fs.copyFile(
  path.join(here, "favicon.svg"),
  path.join(output, "favicon.svg"),
);
await fs.copyFile(
  path.join(
    here,
    "node_modules/@fontsource-variable/inter/files/inter-latin-wght-normal.woff2",
  ),
  path.join(output, "assets/inter.woff2"),
);
await fs.copyFile(
  path.join(here, "node_modules/@fontsource-variable/inter/LICENSE"),
  path.join(output, "assets/inter-LICENSE.txt"),
);
await build({
  entryPoints: [path.join(here, "client.mjs")],
  outdir: path.join(output, "assets"),
  bundle: true,
  splitting: true,
  format: "esm",
  minify: true,
  target: ["es2022"],
  logLevel: "warning",
});
const highlighter = await createHighlighter({
  themes: ["github-dark", "github-light"],
  langs: ["scala", "json", "bash", "yaml", "xml", "properties"],
});
const highlight = (code, lang) =>
  highlighter.codeToHtml(code, {
    lang: highlighter.getLoadedLanguages().includes(lang) ? lang : "text",
    themes: { light: "github-light", dark: "github-dark" },
  });
const md = createMarkdown(highlight, base, commit);
const readme = await fs.readFile(path.join(root, "README.md"), "utf8");
const compatibilityTable = readme
  .split("## Compatibility matrix")[1]
  ?.match(/\|[^]*?(?=\n\s*\n)/)?.[0];
if (!compatibilityTable)
  throw new Error("README compatibility matrix is missing");
const icon =
  '<svg viewBox="0 0 32 32" fill="none" aria-hidden="true"><path d="M4 10h8l5 12h11M4 22h8l5-12h11" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/><circle cx="4" cy="10" r="2" fill="currentColor"/><circle cx="28" cy="22" r="2" fill="currentColor"/></svg>';
const arrow = '<span aria-hidden="true">↗</span>';
const docs = (slug, label, cls = "") =>
  `<a class="${cls}" href="${base}${docRoute(slug)}">${label}</a>`;
const searchButton =
  '<button class="search-trigger" type="button" aria-label="Search documentation"><span class="search-symbol" aria-hidden="true">⌕</span><span>Search docs</span><kbd>Ctrl K</kbd></button>';
function shell(title, body, route, description, isDocs = false) {
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="color-scheme" content="light dark"><title>${escape(title)} · chisel-async</title><meta name="description" content="${escape(description)}"><meta property="og:title" content="${escape(title)} · chisel-async"><meta property="og:description" content="${escape(description)}"><meta property="og:type" content="website"><meta property="og:url" content="${origin}${base}${route}"><link rel="canonical" href="${origin}${base}${route}"><link rel="icon" type="image/svg+xml" href="${base}favicon.svg"><link rel="preload" href="${base}assets/inter.woff2" as="font" type="font/woff2" crossorigin><script>try{document.documentElement.dataset.theme=localStorage.getItem('ca-theme')||(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light')}catch{}</script><link rel="stylesheet" href="${base}assets/site.css"><script type="module" src="${base}assets/client.js"></script></head><body data-base="${base}"><a class="skip-link" href="#main">Skip to content</a>
<header class="site-header"><a class="brand" href="${base}" aria-label="chisel-async home">${icon}<span>chisel<span class="brand-divider">-</span>async</span></a><a class="version" href="${base}docs/compatibility/">${escape(version)}</a><div class="header-spacer"></div>${searchButton}<nav class="header-links" aria-label="Main">${docs("getting-started", "Docs", isDocs ? "current" : "")}<a href="${base}api/scala/">Scala API ${arrow}</a><a href="${repository}">GitHub ${arrow}</a></nav><button class="theme-toggle" type="button" aria-label="Toggle color theme" title="Toggle color theme">◐</button><button class="menu-toggle" type="button" aria-label="Toggle navigation" aria-expanded="false" aria-controls="mobile-nav">☰</button></header>
<nav id="mobile-nav" class="mobile-nav" aria-label="Mobile navigation" hidden>${docs("getting-started", "Documentation")}<a href="${base}api/scala/">Scala API</a><a href="${repository}">GitHub</a>${isDocs ? navigation.map(([group, links]) => `<p>${group}</p>${links.map(([slug, label]) => docs(slug, label)).join("")}`).join("") : ""}</nav>
${body}
<footer class="site-footer"><a class="brand" href="${base}">${icon}<span>chisel-async</span></a><p>Asynchronous hardware components for Chisel.</p><div>${docs("provenance", "References")}<a href="${repository}/blob/${commit}/LICENSE">Apache 2.0</a><a href="${repository}/commit/${commit}" title="Documentation source commit">${commit.slice(0, 7)}</a></div></footer>
<dialog id="search-dialog" aria-labelledby="search-title"><div class="search-heading"><label id="search-title" for="search-input">Search documentation</label><button id="close-search" type="button" aria-label="Close search">Esc</button></div><input id="search-input" type="search" placeholder="Try ‘reset’, ‘dual-rail’, or ‘timing’" autocomplete="off"><p id="search-status" role="status">Type to search the guides. Use Tab to browse results.</p><div id="search-results"></div><a class="search-api" href="${base}api/scala/">Looking for a class? Open the Scala API ${arrow}</a></dialog>
</body></html>`;
}
async function write(route, html) {
  const destination = path.join(output, route, "index.html");
  await fs.mkdir(path.dirname(destination), { recursive: true });
  await fs.writeFile(destination, html);
}
const search = [];
for (const [index, page] of pages.entries()) {
  const source = `docs/${page.slug}.md`;
  const raw = (await fs.readFile(path.join(root, source), "utf8")).replace(
    "<!-- compatibility-matrix -->",
    compatibilityTable,
  );
  const env = { source };
  const content = md.render(raw.replace(/<!--[^]*?-->/g, ""), env);
  const title = env.headings.find((h) => h.level === 1)?.title || page.label;
  const bodyText = raw
    .replace(/<!--[^]*?-->/g, "")
    .replace(/```[^]*?```/g, " ")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/[#*`|>\n]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  search.push({
    title: page.label,
    url: base + docRoute(page.slug),
    text: bodyText,
  });
  const sidebar = navigation
    .map(
      ([group, links]) =>
        `<section><h2>${group}</h2>${links.map(([slug, label]) => `<a href="${base}${docRoute(slug)}" ${slug === page.slug ? 'aria-current="page"' : ""}>${label}</a>`).join("")}</section>`,
    )
    .join("");
  const toc = env.headings
    .filter((h) => h.level === 2)
    .map((h) => `<a href="#${escape(h.id)}">${escape(h.title)}</a>`)
    .join("");
  const neighbors = [pages[index - 1], pages[index + 1]];
  const html = `<div class="docs-layout"><aside class="sidebar"><nav aria-label="Documentation">${sidebar}<a class="api-sidebar" href="${base}api/scala/">Scala API reference ${arrow}</a></nav></aside><main id="main" class="docs-main"><div class="doc-eyebrow">${page.group}</div><article class="prose">${content}</article><div class="doc-end"><a href="${repository}/edit/main/${source}">Edit this page ${arrow}</a><span>Development documentation · ${escape(version)}</span></div><nav class="page-neighbors" aria-label="Adjacent guides">${neighbors.map((neighbor, i) => (neighbor ? docs(neighbor.slug, `<small>${i ? "Next" : "Previous"}</small><span>${neighbor.label} ${i ? "→" : ""}</span>`) : "<span></span>")).join("")}</nav></main><aside class="toc"><nav aria-label="On this page"><h2>On this page</h2>${toc}</nav><div class="api-callout"><span>Constructor and method details</span><a href="${base}api/scala/">Browse the Scala API ${arrow}</a></div></aside></div>`;
  await write(
    docRoute(page.slug),
    shell(
      title,
      html,
      docRoute(page.slug),
      bodyText.slice(title.length, title.length + 180).trim(),
      true,
    ),
  );
}
const quickstart = await fs.readFile(
  path.join(root, "examples/quickstart/src/main/scala/Quickstart.scala"),
  "utf8",
);
const example = quickstart
  .slice(
    quickstart.indexOf("class AddPipeline"),
    quickstart.indexOf("\nobject EmitQuickstart"),
  )
  .trim();
const home = `<main id="main" class="home"><section class="hero">${circuitArtwork()}<div class="hero-copy"><div class="eyebrow"><span class="status-dot"></span> OPEN SOURCE · BUILT WITH CHISEL</div><h1>Asynchronous hardware.<br><span>Built with Chisel.</span></h1><p class="hero-description">Chisel-async gives you typed pipelines, routing and protocol converters.<br class="desktop-break"> Connect bundled-data, dual-rail and clocked logic in Scala.</p><div class="hero-actions">${docs("getting-started", 'Start building <span aria-hidden="true">→</span>', "button primary")}<a class="button secondary" href="${base}api/scala/">Explore the Scala API ${arrow}</a></div><p class="hero-note">Version <strong>${escape(version)}</strong><span>·</span> Scala ${scala}<span>·</span> Chisel ${chisel}</p></div></section>
<section class="showcase" aria-label="Typed pipeline example"><div class="showcase-code"><div class="editor-bar"><span><i></i><i></i><i></i></span><a href="${repository}/blob/${commit}/examples/quickstart/src/main/scala/Quickstart.scala">Quickstart.scala ${arrow}</a></div>${highlight(example, "scala")}<div class="editor-caption">This pipeline adds two operands and stores the result, with both stages sharing a reset domain.</div></div><div class="handshake"><div class="eyebrow">FOUR-PHASE HANDSHAKE</div><h2>Follow a token<br>through a handshake.</h2><p>The producer offers data with a request. The consumer acknowledges it, then both signals return to idle before the next token.</p><div class="pipeline-art" aria-hidden="true"><div class="node"><span>A + B</span><small>Operands</small></div><div class="wire"><span>req →</span><b></b><span>← ack</span></div><div class="node accent"><span>Σ</span><small>UInt(9.W)</small></div></div><div class="signal-display"><div><span>req</span><b id="request-bit">0</b></div><div><span>ack</span><b id="ack-bit">0</b></div><div class="phase-label" id="phase-label" aria-live="polite">0 · Ready for a token</div></div><button type="button" id="step-handshake">Step handshake <span aria-hidden="true">→</span></button><small class="demo-caption">This illustration shows the protocol steps. Circuit delays are not simulated.</small></div></section>
<div class="principles"><span><b>Typed channels</b> Keep your Chisel payload types</span><span><b>Explicit reset</b> Coordinate reset across components</span><span><b>Timing contracts</b> Declare delay bounds and guards</span></div>
<section class="styles-section"><div class="section-heading"><div><span class="eyebrow">CHANNELS AND CONVERTERS</span><h2>Choose how your<br>hardware communicates.</h2></div><p>Choose a protocol for your design, then use converters to connect components with different encodings or clocks.</p></div><div class="style-cards">${[
  [
    "01",
    "Bundled data",
    "req / data / ack",
    "Build pipelines, route tokens and arbitrate between producers, with explicit bounds on modeled delays.",
    "bundled-data",
    "cyan",
  ],
  [
    "02",
    "Dual-rail logic",
    "rail₀ / rail₁ / ack",
    "Represent each bit with two rails, detect complete words and compose strongly indicating logic.",
    "dual-rail",
    "violet",
  ],
  [
    "03",
    "Clocked boundaries",
    "ready / valid / bits",
    "Connect async channels to Chisel Decoupled interfaces, clocked memory backends and pending-event capture.",
    "clocked-integration",
    "amber",
  ],
]
  .map(
    ([number, title, signal, description, slug, color]) =>
      `<a class="style-card ${color}" href="${base}${docRoute(slug)}"><div class="card-top"><span>${number}</span>${arrow}</div><div class="signal-glyph"><span></span><span></span><span></span></div><code>${signal}</code><h3>${title}</h3><p>${description}</p><span class="card-link">Read the guide →</span></a>`,
  )
  .join("")}</div></section>
<section class="verification-section"><div><span class="eyebrow">TESTING YOUR DESIGN</span><h2>Test the function<br>and the handshake.</h2><p>Compare results with a software model, stall consumers and vary cell delays to look for races. Saved traces help you investigate failures. Hardware implementation also requires physical timing and metastability checks.</p>${docs("testing", "Read the testing guide →", "text-link")}</div><div class="verification-list">${[
  [
    "01",
    "Test from ScalaTest",
    "Use AsyncTest for four-phase designs and ChiselSim for clocked harnesses.",
    "testing",
  ],
  [
    "02",
    "Vary delays and stalls",
    "Exercise delayed cells, backpressure and reset with event simulation.",
    "bundled-data",
  ],
  [
    "03",
    "Inspect the exported design",
    "Validate timing metadata and endpoints against the emitted netlist.",
    "timing-and-export",
  ],
]
  .map(
    ([n, title, description, slug]) =>
      `<a href="${base}${docRoute(slug)}"><span>${n}</span><div><h3>${title}</h3><p>${description}</p></div><b aria-hidden="true">↗</b></a>`,
  )
  .join("")}</div></section>
<section class="start-section"><span class="eyebrow">GET STARTED</span><h2>Build and test your first pipeline.</h2><p>Run the adder pipeline and GCD loop in a standalone sbt project, with ScalaTest tests for both.</p>${docs("getting-started", "Open the quickstart →", "button primary")} ${docs("components", "Browse all components", "button secondary")}</section></main>`;
await write(
  "",
  shell(
    "Asynchronous hardware. Built with Chisel.",
    home,
    "",
    "Typed asynchronous hardware for Chisel. Explore bundled-data, dual-rail, and clocked interfaces with explicit protocols and timing contracts.",
  ),
);
await fs.writeFile(
  path.join(output, "404.html"),
  shell(
    "Page not found",
    `<main id="main" class="not-found"><span class="eyebrow">404 · NO HANDSHAKE</span><h1>This endpoint isn’t connected.</h1><p>The page may have moved. Search the guides or start at the documentation index.</p>${docs("index", "Open documentation →", "button primary")}</main>`,
    "404.html",
    "Find your way back to the chisel-async documentation.",
  ),
);
await fs.writeFile(
  path.join(output, "assets/search.json"),
  JSON.stringify(search),
);
await fs.writeFile(
  path.join(output, "site-manifest.json"),
  JSON.stringify(
    {
      base,
      commit,
      version,
      scala,
      chisel,
      pages: pages.map((p) => docRoute(p.slug)),
      api: "api/scala/",
    },
    null,
    2,
  ),
);
await fs.writeFile(path.join(output, ".nojekyll"), "");
await fs.writeFile(
  path.join(output, "sitemap.xml"),
  `<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">${["", ...pages.map((p) => docRoute(p.slug)), "api/scala/"].map((route) => `<url><loc>${origin}${base}${route}</loc></url>`).join("")}</urlset>`,
);
console.log(
  `Built ${pages.length} guides, homepage, search, and Scala API at ${output} (base ${base}).`,
);
highlighter.dispose();
