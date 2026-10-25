// Фото моделей автопарка с Wikimedia Commons (свободные лицензии) + файл авторства.
// node scripts/fetch_car_photos.mjs            — кандидаты в public/cars/_candidates (по 4 на модель)
// node scripts/fetch_car_photos.mjs pick       — забрать выбранные (scripts/car_photos.json) в public/cars/
import fs from "node:fs";
import path from "node:path";

const UA = "FleetConceptDemo/1.0 (portfolio demo)";
const MODELS = {
  "skoda-rapid": "Skoda Rapid liftback",
  "vw-polo": "Volkswagen Polo sedan 2020",
  "kia-rio": "Kia Rio 2021 sedan",
  "moskvich-3": "Moskvich 3",
  "geely-emgrand": "Geely Emgrand 2023",
  "chery-tiggo-4": "Chery Tiggo 4 Pro",
  "belgee-x50": "Belgee X50",
  "haval-f7": "Haval F7",
  "hyundai-sonata": "Hyundai Sonata DN8",
  "exeed-lx": "Exeed LX",
  "kaiyi-x3": "Kaiyi X3",
  "geely-preface": "Geely Preface",
  "hongqi-h5": "Hongqi H5",
  "mercedes-e": "Mercedes-Benz W214 E-Class",
  "bmw-xm": "BMW XM",
  "zeekr-9x": "Zeekr 9X",
  "sollers-atlant": "Sollers Atlant",
  "sollers-argo": "Sollers Argo",
  "lada-largus": "Lada Largus",
  "gazelle-next": "GAZelle Next",
  // повторный поиск: у первых запросов не нашлось подходящих ракурсов/поколений
  "kia-rio-b": "Kia Rio 2020 sedan Russia",
  "kia-rio-c": "Kia Rio IV sedan",
  "geely-emgrand-b": "Geely Emgrand 2024 front",
  "geely-emgrand-c": "Geely Emgrand SS11",
  "lada-largus-b": "Lada Largus 2021",
  "haval-jolion": "Haval Jolion",
};

const api = async (params) => {
  const u =
    "https://commons.wikimedia.org/w/api.php?" + new URLSearchParams({ format: "json", origin: "*", ...params });
  const r = await fetch(u, { headers: { "User-Agent": UA } });
  return r.json();
};
const strip = (s = "") =>
  s
    .replace(/<[^>]+>/g, "")
    .replace(/\s+/g, " ")
    .trim();

async function candidates(query) {
  const j = await api({
    action: "query",
    generator: "search",
    gsrsearch: `${query} filetype:bitmap`,
    gsrnamespace: "6",
    gsrlimit: "12",
    prop: "imageinfo",
    iiprop: "url|size|extmetadata",
    iiurlwidth: "1280",
  });
  return Object.values(j.query?.pages ?? {})
    .map((p) => ({ title: p.title, index: p.index, ...p.imageinfo?.[0] }))
    .filter(
      (x) => x.width >= 1200 && x.width / x.height > 1.25 && x.width / x.height < 2.2 && /\.jpe?g$/i.test(x.title),
    )
    .sort((a, b) => a.index - b.index)
    .slice(0, 4)
    .map((x) => ({
      title: x.title,
      thumb: x.thumburl,
      page: x.descriptionurl,
      license: strip(x.extmetadata?.LicenseShortName?.value),
      author: strip(x.extmetadata?.Artist?.value),
    }));
}

async function download(url, file) {
  await new Promise((res) => setTimeout(res, 700));
  const r = await fetch(url, { headers: { "User-Agent": UA } });
  if (!r.ok) throw new Error(`HTTP ${r.status} ${url}`);
  fs.writeFileSync(file, Buffer.from(await r.arrayBuffer()));
}

const OUT = path.resolve("public/cars");
if (process.argv[2] === "pick") {
  const picks = JSON.parse(fs.readFileSync("scripts/car_photos.json", "utf8"));
  const credits = [];
  for (const [slug, c] of Object.entries(picks)) {
    await download(c.thumb, path.join(OUT, `${slug}.jpg`));
    credits.push({
      slug,
      model: c.model,
      file: c.title.replace(/^File:/, ""),
      author: c.author,
      license: c.license,
      source: c.page,
    });
    console.log("ok", slug);
  }
  fs.writeFileSync(path.join(OUT, "credits.json"), JSON.stringify(credits, null, 1));
} else {
  const dir = path.join(OUT, "_candidates");
  fs.mkdirSync(dir, { recursive: true });
  const cf = path.join(dir, "candidates.json");
  const all = fs.existsSync(cf) ? JSON.parse(fs.readFileSync(cf, "utf8")) : {};
  for (const [slug, q] of Object.entries(MODELS)) {
    if (all[slug]?.length) continue; // уже есть — продолжаем с места остановки
    const list = await candidates(q);
    all[slug] = list;
    for (const [i, c] of list.entries())
      await download(c.thumb, path.join(dir, `${slug}-${i}.jpg`)).catch((e) => console.error(e.message));
    console.log(slug, list.length, list.map((c) => c.license).join(", "));
    fs.writeFileSync(cf, JSON.stringify(all, null, 1));
    await new Promise((r) => setTimeout(r, 2500));
  }
}
