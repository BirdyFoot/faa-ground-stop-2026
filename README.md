# FAA ground stop, November 13, 2026

Airline traffic over the U.S. during the November 13, 2026 nationwide FAA ground stop, compared with a normal Friday (November 6), built from open ADS-B flight tracking data.

Chart and write-up on [birdyfoot.com](https://birdyfoot.com/research/faa-ground-stop-2026)

## Rebuild

Requires Python 3.8+ and Node 18+.

```
# 1. Data (optional; data/ is already included). Streams ~3.5 GB per day from adsb.lol, several minutes each.
python3 scripts/build_ground_stop_data.py 2026-11-13 2026-11-06 --out data

# 2. Line chart
python3 scripts/build_chart.py

# 3. Map
npm install
node scripts/build_map.mjs
```

If you fork this repo, change `REPO_URL` at the top of `build_chart.py` and `build_map.mjs` to your fork. The pages link to it so readers can get the data, as the ODbL requires.

Output goes to `site/`. Both pages are single self-contained HTML files.

## Files

- `scripts/build_ground_stop_data.py`: builds `data/` from adsb.lol. Method and limits are documented at the top of the file.
- `scripts/build_chart.py`, `scripts/build_map.mjs`: build the pages from `data/` and `templates/`.
- `data/airborne_<day>.csv`: aircraft in the air over the lower 48, per UTC minute.
- `data/takeoffs_<day>.csv`: every detected airline takeoff from a U.S. airport.
- `data/takeoffs15_<day>.csv`: airline takeoffs per 15 minutes.

## Notes

- Counts are tracked flights, not official totals. Receiver coverage is volunteer-run and thinner in rural and mountain areas.
- "Airline" means a callsign from a list of scheduled passenger and cargo carriers in the script. Private jets, flight schools, and military are excluded.
- About 2% of takeoffs are estimated, where an aircraft first appears climbing near an airport with no receiver nearby.
- The airborne count uses a rectangle around the lower 48, which includes some border airspace.
- The baseline is a single day. The pages cover 7 a.m. to 7 p.m. Eastern.

## Licenses

- Code: MIT (see `LICENSE`).
- `data/`: Contains information from [adsb.lol](https://www.adsb.lol/docs/open-data/historical), which is made available here under the [Open Database License (ODbL) 1.0](https://opendatacommons.org/licenses/odbl/1-0/). The derived data in `data/` is shared under the same license. If you publish something built from it, keep this notice and keep the data open.
- Airports: [OurAirports](https://ourairports.com) (public domain). State shapes: U.S. Census Bureau via [us-atlas](https://github.com/topojson/us-atlas).

Analysis: BirdyFoot Security.
