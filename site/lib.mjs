import path from "node:path";
import MarkdownIt from "markdown-it";
import GithubSlugger from "github-slugger";

export const repository = "https://github.com/BiscutLabs/chisel-async";
export const navigation = [
  [
    "Start here",
    [
      ["index", "Overview"],
      ["getting-started", "Getting started"],
      ["concepts", "Core concepts"],
      ["examples", "Examples"],
    ],
  ],
  [
    "Build your design",
    [
      ["components", "Component catalog"],
      ["component-terminology", "Terminology & comparison"],
      ["bundled-data", "Bundled data"],
      ["click", "Native Click pipelines"],
      ["click-example", "Click adder example"],
      ["dual-rail", "Dual-rail logic"],
      ["clocked-integration", "Clocked integration"],
    ],
  ],
  [
    "Verify & integrate",
    [
      ["testing", "Testing"],
      ["contracts", "Protocol contracts"],
      ["timing-and-export", "Timing & export"],
      ["asic-mapping", "ASIC mapping"],
      ["gf180-reference", "GF180 reference"],
      ["trace-format", "Trace formats"],
      ["compatibility", "Compatibility"],
      ["troubleshooting", "Troubleshooting"],
    ],
  ],
  [
    "Project",
    [
      ["contributing", "Contributing"],
      ["releasing", "Releasing"],
      ["provenance", "Scientific references"],
      ["website", "Website development"],
    ],
  ],
];
export const pages = navigation.flatMap(([group, links]) =>
  links.map(([slug, label]) => ({ slug, label, group })),
);
export const escape = (text) =>
  String(text).replace(
    /[&<>"']/g,
    (char) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        char
      ],
  );
export const docRoute = (slug) =>
  slug === "index" ? "docs/" : `docs/${slug}/`;
export function normalizeBase(value) {
  if (!/^\/(?:[a-zA-Z0-9_-]+\/)*$/.test(value))
    throw new Error(
      "SITE_BASE must be / or a slash-delimited project path, e.g. /chisel-async/",
    );
  return value;
}
export function rewriteLink(href, source, base, ref = "main") {
  if (/^(?:[a-z][a-z0-9+.-]*:|#|\/\/)/i.test(href)) return href;
  const match = href.match(/^([^?#]*)(.*)$/);
  const [pathname, suffix] = [decodeURI(match[1]), match[2]];
  const resolved = path.posix.normalize(
    path.posix.join(path.posix.dirname(source), pathname),
  );
  if (resolved.startsWith("../") || resolved.startsWith("/"))
    throw new Error(`Link escapes repository: ${href}`);
  if (resolved === "README.md" && suffix === "#compatibility-matrix")
    return `${base}docs/compatibility/#tested-toolchain`;
  if (
    resolved.startsWith("docs/") &&
    pages.some((page) => resolved === `docs/${page.slug}.md`)
  ) {
    return base + docRoute(path.posix.basename(resolved, ".md")) + suffix;
  }
  // Repository files and the historical archive remain available on GitHub.
  return `${repository}/blob/${ref}/${resolved}${suffix}`;
}

export function createMarkdown(highlight, base, ref) {
  const md = new MarkdownIt({ html: false, linkify: true, typographer: false });
  md.renderer.rules.fence = (tokens, idx) => {
    const token = tokens[idx];
    const lang = token.info.trim().split(/\s/)[0] || "text";
    if (lang === "mermaid")
      return `<figure class="diagram"><pre class="mermaid">${escape(token.content)}</pre><figcaption>Channel connections. Timing requirements are explained in the guide.</figcaption></figure>`;
    return `<div class="code-block"><div class="code-bar"><span>${escape(lang)}</span><button class="copy-code" type="button" aria-label="Copy code">Copy</button></div>${highlight(token.content, lang)}</div>`;
  };
  md.core.ruler.push("website", (state) => {
    const slugger = new GithubSlugger();
    state.env.headings = [];
    for (let i = 0; i < state.tokens.length; i++) {
      const token = state.tokens[i];
      if (token.type === "heading_open") {
        const inline = state.tokens[i + 1];
        const title = inline.children
          .filter((t) => ["text", "code_inline"].includes(t.type))
          .map((t) => t.content)
          .join("");
        const id = slugger.slug(title);
        token.attrSet("id", id);
        state.env.headings.push({
          level: Number(token.tag.slice(1)),
          title,
          id,
        });
      }
      for (const child of token.children || []) {
        if (child.type === "link_open")
          child.attrSet(
            "href",
            rewriteLink(child.attrGet("href"), state.env.source, base, ref),
          );
        if (child.type === "image")
          child.attrSet(
            "src",
            rewriteLink(
              child.attrGet("src"),
              state.env.source,
              base,
              ref,
            ).replace("/blob/", "/raw/"),
          );
      }
    }
  });
  return md;
}
