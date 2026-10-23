import { build } from "esbuild";
import { mkdir, cp, readFile, rm, writeFile } from "node:fs/promises";

await rm("dist", { recursive: true, force: true }); // без хвостов прошлых сборок
await mkdir("dist/assets", { recursive: true });
await cp("public", "dist", { recursive: true });

// Сценарий показа (docs/DEMO.md) и авторство фото (public/cars/credits.json) — статические страницы
const esc = (t) => String(t).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
const inline = (t) =>
  esc(t)
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/`(.+?)`/g, "<code>$1</code>");

function markdown(md) {
  const out = [];
  let list = null;
  const close = () => {
    if (list) out.push(`</${list}>`);
    list = null;
  };
  for (const line of md.split(/\r?\n/)) {
    if (/^#{1,3} /.test(line)) {
      close();
      out.push(`<h2>${inline(line.replace(/^#+ /, ""))}</h2>`);
    } else if (/^\d+\. /.test(line)) {
      if (list !== "ol") close(), out.push("<ol>"), (list = "ol");
      out.push(`<li>${inline(line.replace(/^\d+\. /, ""))}</li>`);
    } else if (/^[*-] /.test(line)) {
      if (list !== "ul") close(), out.push("<ul>"), (list = "ul");
      out.push(`<li>${inline(line.slice(2))}</li>`);
    } else if (line.trim()) {
      close();
      out.push(`<p>${inline(line)}</p>`);
    }
  }
  close();
  return out.join("\n");
}

const page = (title, body) =>
  `<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">` +
  `<title>${title}</title><link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600&family=Manrope:wght@800&display=swap" rel="stylesheet">` +
  `<style>body{font:15px/1.7 Inter,system-ui,sans-serif;background:#0a0c0f;color:#d6dbe1;max-width:820px;margin:0 auto;padding:40px 22px 60px}` +
  `a{color:#ffd23f}h1{font:800 34px/1.15 Manrope,sans-serif;color:#fff;letter-spacing:-.03em;margin:22px 0 8px}` +
  `h2{font:800 21px Manrope,sans-serif;color:#fff;margin:34px 0 10px}li{margin:6px 0}strong{color:#fff}` +
  `code{background:#181d23;padding:1px 6px;border-radius:6px;font-size:13px}.note{color:#6c7682;font-size:13px}` +
  `table{border-collapse:collapse;width:100%;font-size:13px}td{padding:8px 6px;border-bottom:1px solid #20262e;vertical-align:top}</style>` +
  `<a href="/">← К прототипу</a>${body}</html>`;

await writeFile(
  "dist/guide.html",
  page(
    "Сценарий показа · концепт таксопарка",
    `<h1>Сценарий показа</h1><p class="note">Концепт и прототип · автор Игорь Шварёв · учебные данные</p>` +
      markdown(await readFile("docs/DEMO.md", "utf8")),
  ),
);
const credits = JSON.parse(await readFile("public/cars/credits.json", "utf8"));
await writeFile(
  "dist/credits.html",
  page(
    "Фото автомобилей · авторы",
    `<h1>Фото автомобилей</h1><p class="note">Все фотографии — Wikimedia Commons, свободные лицензии; уменьшены и пережаты в WebP.</p><table>` +
      credits
        .map(
          (c) =>
            `<tr><td><strong>${esc(c.model)}</strong></td><td>${esc(c.author || "—")}</td><td>${esc(c.license)}</td>` +
            `<td><a href="${esc(c.source)}" target="_blank" rel="noreferrer">источник</a></td></tr>`,
        )
        .join("") +
      `</table>`,
  ),
);

const result = await build({
  entryPoints: ["web/main.tsx"],
  bundle: true,
  outdir: "dist/assets",
  entryNames: "app-[hash]",
  chunkNames: "chunk-[hash]",
  splitting: true, // кабинет, графики, карта и консоль — отдельные чанки, лендинг их не ждёт
  format: "esm",
  platform: "browser",
  target: "es2022",
  minify: true,
  jsx: "automatic",
  metafile: true,
  define: { "process.env.NODE_ENV": '"production"' },
  loader: { ".png": "file", ".svg": "file" },
  assetNames: "asset-[name]-[hash]",
  logLevel: "info",
});
const template = await readFile("index.html", "utf8");
const js = Object.entries(result.metafile.outputs).find(([path, info]) => path.endsWith(".js") && info.entryPoint?.replaceAll("\\", "/") === "web/main.tsx");
if (!js) throw new Error("No application bundle");
await writeFile(
  "dist/index.html",
  template
    .replace("/web/main.tsx", "/" + js[0].replace("dist/", ""))
    .replace(
      "</head>",
      `<link rel="stylesheet" href="/${js[1].cssBundle.replace("dist/", "")}">` +
        // общие чанки точки входа — сразу, параллельно с ней
        js[1].imports
          .filter((i) => i.kind === "import-statement")
          .map((i) => `<link rel="modulepreload" href="/${i.path.replace("dist/", "")}">`)
          .join("") +
        "</head>",
    ),
);
const assets = [
  "/",
  "/manifest.webmanifest",
  "/icon.svg",
  "/" + js[0].replace("dist/", ""),
  "/" + js[1].cssBundle.replace("dist/", ""),
];
await writeFile(
  "dist/sw.js",
  `const CACHE='fleet-${js[0].split("/").pop()}';self.addEventListener('install',e=>{e.waitUntil(caches.open(CACHE).then(c=>c.addAll(${JSON.stringify(assets)})).then(()=>self.skipWaiting()))});self.addEventListener('activate',e=>{e.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k!==CACHE).map(k=>caches.delete(k)))).then(()=>self.clients.claim()))});self.addEventListener('fetch',e=>{const u=new URL(e.request.url);if(e.request.method!=='GET'||u.origin!==location.origin||u.pathname.startsWith('/api/'))return;e.respondWith(fetch(e.request).catch(()=>caches.match(e.request).then(r=>r||caches.match('/'))))});`,
);
