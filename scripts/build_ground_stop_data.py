#!/usr/bin/env python3
"""
build_ground_stop_data.py

Builds the data behind BirdyFoot Security's analysis of the November 13, 2026
nationwide FAA ground stop, from adsb.lol's open ADS-B archive.

For each UTC day given, it streams that day's archive from GitHub (no full
download to disk), reads every aircraft's track, and writes:

  airborne_<day>.csv   aircraft in the air over the lower 48, per UTC minute
                       (all aircraft, and scheduled airlines only)
  takeoffs_<day>.csv   one row per detected airline takeoff at a U.S. airport,
                       with time, airport, and whether it was observed or estimated
  takeoffs15_<day>.csv airline takeoffs per 15 minutes (observed, estimated, total)

Usage:
  python3 build_ground_stop_data.py 2026-11-13 2026-11-06 --out data/

Python 3.8+, standard library only. Each day is roughly 3.5 GB compressed and
takes several minutes to stream.

Data sources and licenses:
  - Flight tracks: adsb.lol globe_history, Open Database License (ODbL 1.0).
    Credit "adsb.lol" and share derived databases under the same license.
  - Airports: OurAirports (public domain), downloaded at runtime.

How it works, and its limits (read before quoting numbers):

  1. "In the air" means an aircraft reported a numeric altitude (not "ground")
     at a position inside a rectangle around the contiguous U.S. The rectangle
     also takes in some Canadian and Mexican border airspace. Gaps of up to
     10 minutes between position reports are filled in, so an aircraft that
     briefly drops out of receiver range is still counted.

  2. "Airline" means the callsign starts with an ICAO code on the AIRLINES list
     below: scheduled passenger airlines, their regional partners, and major
     cargo carriers. Private jet operators (NetJets, Flexjet), flight schools,
     charters, and military are excluded. The list is a judgment call; edit it
     to change the definition.

  3. A takeoff is "observed" when an aircraft's last report was on the ground
     and its next is airborne, or when it first appears climbing within 2,500 ft
     of a nearby airport's elevation. Altitudes are above sea level, so the
     airport's own elevation matters (Denver sits at 5,431 ft).

  4. A takeoff is "estimated" when an airline aircraft first appears climbing
     within 40 km of an airport and within 10,000 ft of that airport's elevation,
     and the nearest scheduled airport is in the U.S. (so departures from Tijuana,
     Vancouver, or Ciudad Juárez aren't credited to U.S. airports). This recovers departures from airports with no receiver nearby,
     mostly in the Mountain West, where aircraft aren't heard until they climb
     over terrain. Estimated takeoffs can be assigned to the wrong airport where
     airports are close together, and their time runs a few minutes late.

  5. Coverage depends on volunteer receivers. Counts are lower than official
     totals and thinner in rural and mountainous areas. Comparisons between two
     days processed the same way are more reliable than absolute numbers.
"""
import argparse, csv, gzip, io, json, math, os, sys, tarfile, time, urllib.error, urllib.request

ARCHIVE = "https://github.com/adsblol/globe_history_{year}/releases/download/{tag}/{tag}.tar.{part}"
AIRPORTS_URL = "https://raw.githubusercontent.com/davidmegginson/ourairports-data/main/airports.csv"

LOWER48 = {"lat": (24.5, 49.5), "lon": (-125.0, -66.5)}   # rough box; see note 1
FILL_GAP_S = 600          # fill airborne gaps up to 10 minutes
GROUND_GAP_S = 600        # ground -> air within 10 minutes counts as leaving the ground
REAPPEAR_GAP_S = 900      # a 15-minute silence makes the next report a fresh appearance
CLIMB_FPM = 200           # "climbing" means vertical rate above 200 ft/min
OBSERVED_KM, OBSERVED_FT = 8, 2500
ESTIMATED_KM, ESTIMATED_FT = 40, 10000
REPEAT_S = 1200           # ignore a second takeoff by the same aircraft within 20 minutes

# Scheduled passenger and cargo airlines, by ICAO callsign prefix. Edit as needed.
AIRLINES = set("""
AAL ASA DAL UAL SWA JBU NKS FFT HAL AAY SCX MXY VXP
SKW RPA ENY PDT JIA EDV QXE ASH GJS AWI UCA VTE SIL CPZ
FDX UPS GTI ABX ATN CKS AJT WGN PAC
ACA ROU JZA WJA WEN POE TSC AMX SLI VOI VIV
BAW VIR DLH AFR KLM IBE EIN SWR AUA SAS FIN ICE TAP THY
UAE QTR ETD SVA ANA JAL KAL AAR CPA EVA CAL CES CSN CCA
QFA ANZ AVA LAN TAM CMP ELY SIA PAL ETH
""".split())


def airline(callsign):
    # ICAO code followed by a flight number: "UAL871", "BAW15K". Requiring the digit
    # keeps out non-airline callsigns that happen to start with a listed code ("EVANS31").
    cs = (callsign or "").strip()
    return len(cs) >= 4 and cs[:3] in AIRLINES and cs[3].isdigit()


def in_lower48(lat, lon):
    return (lat is not None and lon is not None
            and LOWER48["lat"][0] <= lat <= LOWER48["lat"][1]
            and LOWER48["lon"][0] <= lon <= LOWER48["lon"][1])


# ---------- airports ----------

def load_airports():
    """Airports with scheduled service worldwide, indexed on a quarter-degree grid.
    Non-U.S. airports are kept so a takeoff near the border is credited to the
    right country (Tijuana is 20 km from San Diego); only U.S. ones are recorded."""
    with urllib.request.urlopen(AIRPORTS_URL) as r:
        rows = csv.DictReader(io.TextIOWrapper(r, encoding="utf-8"))
        airports = [(a["ident"], a["iata_code"], float(a["latitude_deg"]), float(a["longitude_deg"]),
                     float(a["elevation_ft"]), a["iso_region"], a["iso_country"])
                    for a in rows
                    if a["scheduled_service"] == "yes" and a["elevation_ft"]]
    grid = {}
    for a in airports:
        grid.setdefault((math.floor(a[2] * 4), math.floor(a[3] * 4)), []).append(a)
    print(f"{len(airports)} airports with scheduled service", file=sys.stderr)
    return grid


def nearest_airport(grid, lat, lon, max_km):
    reach = math.ceil(max_km / 25) + 1          # grid cells are ~25 km tall
    gi, gj = math.floor(lat * 4), math.floor(lon * 4)
    best, best_km = None, max_km
    for di in range(-reach, reach + 1):
        for dj in range(-reach, reach + 1):
            for a in grid.get((gi + di, gj + dj), ()):
                km = math.hypot((a[2] - lat) * 111.0, (a[3] - lon) * 111.0 * math.cos(math.radians(lat)))
                if km < best_km:
                    best, best_km = a, km
    return best, best_km


# ---------- streaming the archive ----------

class Parts(io.RawIOBase):
    """Reads a split archive (.tar.aa, .tar.ab, ...) as one continuous stream."""
    def __init__(self, year, tag):
        self.year, self.tag, self.suffixes, self.cur = year, tag, iter(self._suffixes()), None
    @staticmethod
    def _suffixes():
        for a in "abcdefghij":
            for b in "abcdefghijklmnopqrstuvwxyz":
                yield a + b
    def readable(self):
        return True
    def readinto(self, buf):
        while True:
            if self.cur is None:
                url = ARCHIVE.format(year=self.year, tag=self.tag, part=next(self.suffixes))
                try:
                    self.cur = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "birdyfoot-research"}))
                except urllib.error.HTTPError as e:
                    if e.code == 404:
                        return 0                 # no more parts
                    raise
            n = self.cur.readinto(buf)
            if n:
                return n
            self.cur = None


def traces(day):
    year = day[:4]
    tag = f"v{day.replace('-', '.')}-planes-readsb-prod-0"
    tar = tarfile.open(fileobj=io.BufferedReader(Parts(year, tag), 1 << 20), mode="r|")
    for m in tar:
        if m.isfile() and "/traces/" in m.name:
            raw = tar.extractfile(m).read()
            try:
                yield json.loads(gzip.decompress(raw))
            except OSError:
                yield json.loads(raw)


# ---------- per-day processing ----------

def process(day, grid, out):
    air_all, air_airline = [0] * 1440, [0] * 1440
    takeoffs = []
    start, n = time.time(), 0

    for d in traces(day):
        n += 1
        if n % 10000 == 0:
            print(f"  {day}: {n} aircraft, {time.time() - start:.0f}s", file=sys.stderr)
        base, callsign = d["timestamp"], ""
        prev = None            # (seconds, on_ground) of the previous report
        last_air = None        # seconds of the previous airborne report inside the box
        last_takeoff = -1e9
        minutes_all, minutes_airline = set(), set()

        for p in d["trace"]:
            sec, lat, lon, alt = p[0], p[1], p[2], p[3]
            if isinstance(p[8], dict) and p[8].get("flight"):
                callsign = p[8]["flight"].strip()
            on_ground = alt == "ground"
            rate = p[7] if p[7] is not None else (p[11] if len(p) > 11 else None)

            if not on_ground and isinstance(alt, (int, float)) and in_lower48(lat, lon):
                is_airline = airline(callsign)

                # 1. minutes in the air
                minute = int(sec // 60)
                if last_air is not None and 0 < sec - last_air <= FILL_GAP_S:
                    span = range(int(last_air // 60) + 1, minute + 1)
                else:
                    span = (minute,)
                for k in span:
                    if 0 <= k < 1440:
                        minutes_all.add(k)
                        if is_airline:
                            minutes_airline.add(k)
                last_air = sec

                # 2. takeoffs (airlines only)
                if is_airline and sec - last_takeoff > REPEAT_S:
                    left_ground = prev is not None and prev[1] and sec - prev[0] <= GROUND_GAP_S
                    fresh = (prev is None or sec - prev[0] > REAPPEAR_GAP_S) and (rate or 0) > CLIMB_FPM
                    method, ap = None, None
                    if left_ground or fresh:
                        ap, km = nearest_airport(grid, lat, lon, OBSERVED_KM)
                        if ap and (left_ground or alt <= ap[4] + OBSERVED_FT):
                            method = "observed"
                        elif fresh:
                            ap, km = nearest_airport(grid, lat, lon, ESTIMATED_KM)
                            if ap and alt <= ap[4] + ESTIMATED_FT:
                                method = "estimated"
                    if method and ap[6] != "US":
                        method = None                # nearest airport is outside the U.S.
                    if method:
                        takeoffs.append([d["icao"], callsign, int(base + sec), round(lat, 4), round(lon, 4),
                                         ap[0], ap[1], ap[5], method])
                        last_takeoff = sec

            prev = (sec, on_ground)

        for k in minutes_all:
            air_all[k] += 1
        for k in minutes_airline:
            air_airline[k] += 1

    write(day, base, air_all, air_airline, takeoffs, out)
    print(f"{day}: {n} aircraft, {len(takeoffs)} airline takeoffs, {time.time() - start:.0f}s", file=sys.stderr)


def write(day, base, air_all, air_airline, takeoffs, out):
    os.makedirs(out, exist_ok=True)
    stamp = lambda s: time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime(s))
    with open(f"{out}/airborne_{day}.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["minute_utc", "airborne_all", "airborne_airline"])
        for k in range(1440):
            w.writerow([stamp(base + k * 60), air_all[k], air_airline[k]])
    takeoffs.sort(key=lambda r: r[2])
    with open(f"{out}/takeoffs_{day}.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["icao24", "callsign", "takeoff_utc", "lat", "lon", "airport_icao", "airport_iata", "region", "method"])
        for r in takeoffs:
            w.writerow(r[:2] + [stamp(r[2])] + r[3:])
    bins = [[0, 0] for _ in range(96)]
    for r in takeoffs:
        k = int((r[2] - base) // 900)
        if 0 <= k < 96:
            bins[k][0 if r[8] == "observed" else 1] += 1
    with open(f"{out}/takeoffs15_{day}.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["start_utc", "observed", "estimated", "total"])
        for k, (o, e) in enumerate(bins):
            w.writerow([stamp(base + k * 900), o, e, o + e])


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Build airborne counts and airline takeoffs from adsb.lol for the given UTC days.")
    ap.add_argument("days", nargs="+", help="UTC dates, e.g. 2026-11-13")
    ap.add_argument("--out", default="data")
    args = ap.parse_args()
    grid = load_airports()
    for day in args.days:
        process(day, grid, args.out)
