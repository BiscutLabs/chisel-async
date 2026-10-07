import http from "node:http";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
const root = path.join(path.dirname(fileURLToPath(import.meta.url)), "dist");
const { base } = JSON.parse(
  await fs.readFile(path.join(root, "site-manifest.json"), "utf8"),
);
const mime = {
  ".html": "text/html",
  ".css": "text/css",
  ".js": "text/javascript",
  ".json": "application/json",
  ".svg": "image/svg+xml",
  ".woff2": "font/woff2",
  ".png": "image/png",
  ".gif": "image/gif",
  ".txt": "text/plain",
  ".xml": "application/xml",
};
const port = Number(process.env.PORT || 4173);
http
  .createServer(async (request, response) => {
    try {
      const pathname = decodeURIComponent(
        new URL(request.url, "http://localhost").pathname,
      );
      if (pathname === "/" && base !== "/") {
        response.writeHead(302, { Location: base });
        response.end();
        return;
      }
      if (!pathname.startsWith(base)) throw new Error("Outside site");
      const relative = pathname.slice(base.length);
      const target = path.resolve(root, relative);
      if (target !== root && !target.startsWith(root + path.sep))
        throw new Error("Outside site");
      const stat = await fs.stat(target);
      if (stat.isDirectory() && !pathname.endsWith("/")) {
        response.writeHead(302, { Location: pathname + "/" });
        response.end();
        return;
      }
      const file = stat.isDirectory()
        ? path.join(target, "index.html")
        : target;
      response.writeHead(200, {
        "Content-Type": `${mime[path.extname(file)] || "application/octet-stream"}${/\.(html|css|js|json|svg|txt|xml)$/.test(file) ? "; charset=utf-8" : ""}`,
        "Cache-Control": "no-store",
      });
      response.end(await fs.readFile(file));
    } catch {
      response.writeHead(404, { "Content-Type": "text/html; charset=utf-8" });
      response.end(await fs.readFile(path.join(root, "404.html")));
    }
  })
  .listen(port, "127.0.0.1", () =>
    console.log(`Preview: http://127.0.0.1:${port}${base}`),
  );
