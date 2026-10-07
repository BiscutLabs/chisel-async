import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { parse } from "parse5";

export function inspectHtml(html) {
  const ids = new Set();
  const links = [];
  function walk(node) {
    for (const { name, value } of node.attrs || []) {
      if (name === "id" || name === "name") ids.add(value);
      if (name === "href" || name === "src") links.push(value);
    }
    for (const child of node.childNodes || []) walk(child);
  }
  walk(parse(html));
  return { ids, links };
}
export async function checkLink(href, page, directory, base) {
  if (/^(?:[a-z][a-z0-9+.-]*:|\/\/)/i.test(href)) return;
  const url = new URL(href, `https://local.invalid${base}${page}`);
  if (!url.pathname.startsWith(base))
    throw new Error(`Link escapes Pages base: ${href} on ${page}`);
  const relative = decodeURIComponent(url.pathname.slice(base.length));
  const file = path.join(
    directory,
    !relative || relative.endsWith("/") ? `${relative}index.html` : relative,
  );
  const stat = await fs.stat(file).catch(() => {
    throw new Error(`Missing target: ${href} on ${page}`);
  });
  if (!stat.isFile())
    throw new Error(`Target is not a file: ${href} on ${page}`);
  if (url.hash && file.endsWith(".html") && !relative.startsWith("api/")) {
    const { ids } = inspectHtml(await fs.readFile(file, "utf8"));
    if (!ids.has(decodeURIComponent(url.hash.slice(1))))
      throw new Error(`Missing anchor: ${href} on ${page}`);
  }
}
async function main() {
  const directory = path.join(
    path.dirname(fileURLToPath(import.meta.url)),
    "dist",
  );
  const manifest = JSON.parse(
    await fs.readFile(path.join(directory, "site-manifest.json"), "utf8"),
  );
  if (manifest.pages.length < 18) throw new Error("Incomplete guide inventory");
  let count = 0;
  for (const page of [
    "index.html",
    "404.html",
    ...manifest.pages.map((route) => `${route}index.html`),
  ]) {
    const html = await fs.readFile(path.join(directory, page), "utf8");
    const { links } = inspectHtml(html);
    for (const href of links) {
      await checkLink(href, page, directory, manifest.base);
      count++;
    }
    if (!html.includes('<main id="main"') || !html.includes('<html lang="en">'))
      throw new Error(`Missing accessible page structure: ${page}`);
  }
  // Check the generated API's entrypoint and its own local resource links, too.
  const apiPage = "api/scala/index.html";
  const apiHtml = await fs.readFile(path.join(directory, apiPage), "utf8");
  for (const href of inspectHtml(apiHtml).links)
    await checkLink(href, apiPage, directory, manifest.base);
  await fs.access(
    path.join(directory, "api/scala/chiselasync/core/AsyncModule.html"),
  );
  const search = JSON.parse(
    await fs.readFile(path.join(directory, "assets/search.json"), "utf8"),
  );
  if (
    search.length !== manifest.pages.length ||
    search.some((page) => !page.text || !page.title)
  )
    throw new Error("Incomplete search index");
  for (const page of search)
    await checkLink(page.url, "index.html", directory, manifest.base);
  console.log(
    `PASS: ${manifest.pages.length} guides, ${count} links/resources, search inventory, and generated Scala API.`,
  );
}
if (
  process.argv[1] &&
  path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)
)
  await main();
