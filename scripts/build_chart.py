#!/usr/bin/env python3
"""
build_chart.py

Builds site/ground-stop-chart.html from the CSVs in data/ and the template in
templates/chart.html. Python 3.8+, standard library only.

  python3 scripts/build_chart.py

The chart covers 7 a.m. to 7 p.m. Eastern (12:00 to 24:00 UTC) on the event
day and the baseline day, which fits inside a single UTC day of data.
"""
import csv, json, os, sys

EVENT, BASELINE = "2026-11-13", "2026-11-06"
# Where this repo is published. The pages link here so readers can get the derived
# data, which the Open Database License requires. Set it before building.
REPO_URL = "https://github.com/BirdyFoot/faa-ground-stop-2026"
START_MIN, MINUTES = 12 * 60, 720          # 7:00 a.m. EST = 12:00 UTC; 12 hours
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def column(path, name):
    with open(path, newline="") as f:
        return [int(r[name]) for r in csv.DictReader(f)]


def main():
    d = {}
    for day, key in ((EVENT, "13"), (BASELINE, "06")):
        air = os.path.join(ROOT, "data", f"airborne_{day}.csv")
        t15 = os.path.join(ROOT, "data", f"takeoffs15_{day}.csv")
        if not (os.path.exists(air) and os.path.exists(t15)):
            sys.exit(f"Missing data for {day}. Run scripts/build_ground_stop_data.py {day} --out data")
        d["air" + key] = column(air, "airborne_airline")[START_MIN:START_MIN + MINUTES]
        d["all" + key] = column(air, "airborne_all")[START_MIN:START_MIN + MINUTES]
        d["dep" + key] = column(t15, "total")[START_MIN // 15:(START_MIN + MINUTES) // 15]
        d["depall" + key] = d["dep" + key]       # takeoffs are tracked for airlines only

    with open(os.path.join(ROOT, "templates", "chart.html")) as f:
        html = f.read().replace("__DATA__", json.dumps(d, separators=(",", ":")))
    if "YOUR-ACCOUNT" in REPO_URL:
        sys.exit("Set REPO_URL at the top of this script to where the repo is published.")
    html = html.replace("__REPO_URL__", REPO_URL).replace("__REPO_URL_TEXT__", REPO_URL.split("://", 1)[-1])
    os.makedirs(os.path.join(ROOT, "site"), exist_ok=True)
    out = os.path.join(ROOT, "site", "ground-stop-chart.html")
    with open(out, "w") as f:
        f.write(html)

    at_stop = d["air13"][8 * 60 + 54]
    after = sum(d["dep13"][36:]), sum(d["dep06"][36:])
    print(f"Wrote {out}")
    print(f"  airline flights in the air at 3:54 p.m. ET: {at_stop:,}")
    print(f"  in the air at 7 p.m.: {d['air13'][-1]:,} (baseline {d['air06'][-1]:,})")
    print(f"  airline takeoffs 4-7 p.m.: {after[0]:,} (baseline {after[1]:,})")


if __name__ == "__main__":
    main()
