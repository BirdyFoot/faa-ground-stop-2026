// build_map.mjs
//
// Builds site/ground-stop-map.html from data/takeoffs_<day>.csv and the template
// in templates/map.html. Projects every takeoff and the state outlines (U.S.
// Census Bureau shapes from us-atlas) with an Albers USA projection.
//
//   npm install
//   node scripts/build_map.mjs
//
// The map covers 7 a.m. to 7 p.m. Eastern (12:00 to 24:00 UTC).
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { createRequire } from "module";
import { geoAlbersUsa, geoPath } from "d3-geo";
import { feature, mesh } from "topojson-client";

const EVENT = "2026-11-13", BASELINE = "2026-11-06";
// Where this repo is published. The page links here so readers can get the derived
// data, which the Open Database License requires. Set it before building.
const REPO_URL = "https://github.com/BirdyFoot/faa-ground-stop-2026";
if (REPO_URL.includes("YOUR-ACCOUNT")) {
  console.error("Set REPO_URL at the top of this script to where the repo is published.");
  process.exit(1);
}
const START_UTC_HOUR = 12, MINUTES = 720;
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const require = createRequire(import.meta.url);

const us = JSON.parse(fs.readFileSync(require.resolve("us-atlas/states-10m.json")));
const NOT_LOWER48 = ["02", "15", "60", "66", "69", "72", "78"];   // AK, HI, territories
const states = feature(us, us.objects.states).features.filter(f => !NOT_LOWER48.includes(f.id));
const proj = geoAlbersUsa().scale(1300).translate([487.5, 305]);
const geo = geoPath(proj).digits(1);
const borders = geo(mesh(us, us.objects.states, (a, b) => a !== b && !NOT_LOWER48.includes(a.id) && !NOT_LOWER48.includes(b.id)));
const outline = geo({ type: "FeatureCollection", features: states });
const [[x0, y0], [x1, y1]] = geo.bounds({ type: "FeatureCollection", features: states });

function takeoffs(day) {
  const file = path.join(ROOT, "data", `takeoffs_${day}.csv`);
  if (!fs.existsSync(file)) {
    console.error(`Missing ${file}. Run scripts/build_ground_stop_data.py ${day} --out data`);
    process.exit(1);
  }
  const t0 = Date.parse(`${day}T${String(START_UTC_HOUR).padStart(2, "0")}:00:00Z`) / 1000;
  const rows = fs.readFileSync(file, "utf8").trim().split(/\r?\n/).slice(1);
  const out = [];
  for (const r of rows) {
    const c = r.split(",");                       // icao24,callsign,takeoff_utc,lat,lon,...
    const minute = Math.floor((Date.parse(c[2]) / 1000 - t0) / 60);
    if (minute < 0 || minute >= MINUTES) continue;
    const xy = proj([+c[4], +c[3]]);
    if (!xy) continue;
    out.push(Math.round((xy[0] - x0) * 2), Math.round((xy[1] - y0) * 2), minute);
  }
  console.log(`  ${day}: ${out.length / 3} airline takeoffs, 7 a.m. to 7 p.m. ET`);
  return out;
}

const data = { w: +(x1 - x0).toFixed(1), h: +(y1 - y0).toFixed(1), x0, y0, borders, outline,
  d13: takeoffs(EVENT), d06: takeoffs(BASELINE) };
const html = fs.readFileSync(path.join(ROOT, "templates", "map.html"), "utf8").replace("__MAP__", JSON.stringify(data))
  .replaceAll("__REPO_URL__", REPO_URL).replaceAll("__REPO_URL_TEXT__", REPO_URL.split("://")[1]);
fs.mkdirSync(path.join(ROOT, "site"), { recursive: true });
fs.writeFileSync(path.join(ROOT, "site", "ground-stop-map.html"), html);
console.log("Wrote site/ground-stop-map.html");
