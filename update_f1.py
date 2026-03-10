#!/usr/bin/env python3
"""
APEX F1 2026 — Auto-updater
Fetches the latest standings, results and calendar from Wikipedia
and rebuilds the standalone HTML file.
"""

import re
import json
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

WIKI_URL = "https://en.wikipedia.org/w/api.php?action=parse&page=2026_Formula_One_World_Championship&prop=wikitext&format=json"
HTML_FILE = Path("index.html")

# ── Helpers ────────────────────────────────────────────────────────────────────

def fetch_wikitext() -> str:
    req = urllib.request.Request(
        WIKI_URL,
        headers={"User-Agent": "APEX-F1-Updater/1.0 (github-actions)"}
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read().decode())
    return data["parse"]["wikitext"]["*"]


def clean(s: str) -> str:
    """Strip wiki markup from a string."""
    s = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]+)\]\]", r"\1", s)  # [[link|text]] → text
    s = re.sub(r"\{\{[^}]*\}\}", "", s)                        # {{templates}}
    s = re.sub(r"<ref[^/]*/?>.*?</ref>", "", s, flags=re.S)   # <ref>…</ref>
    s = re.sub(r"<[^>]+>", "", s)                              # HTML tags
    s = re.sub(r"'{2,}", "", s)                                 # bold/italic ''
    s = re.sub(r"\s+", " ", s).strip()
    return s


# ── Parsers ────────────────────────────────────────────────────────────────────

TEAM_KEY_MAP = {
    "McLaren":       "mclaren",
    "Mercedes":      "mercedes",
    "Red Bull":      "redbull",
    "Ferrari":       "ferrari",
    "Williams":      "williams",
    "Racing Bulls":  "racingbulls",
    "Aston Martin":  "astonmartin",
    "Haas":          "haas",
    "Audi":          "audi",
    "Alpine":        "alpine",
    "Cadillac":      "cadillac",
}

DRIVER_KEY_MAP = {
    "Russell":    "russell",
    "Antonelli":  "antonelli",
    "Leclerc":    "leclerc",
    "Hamilton":   "hamilton",
    "Norris":     "norris",
    "Piastri":    "piastri",
    "Verstappen": "verstappen",
    "Hadjar":     "hadjar",
    "Albon":      "albon",
    "Sainz":      "sainz",
    "Lawson":     "lawson",
    "Lindblad":   "lindblad",
    "Alonso":     "alonso",
    "Stroll":     "stroll",
    "Bearman":    "bearman",
    "Ocon":       "ocon",
    "Hülkenberg": "hulkenberg",
    "Bortoleto":  "bortoleto",
    "Gasly":      "gasly",
    "Colapinto":  "colapinto",
    "Pérez":      "perez",
    "Bottas":     "bottas",
}


def parse_driver_standings(wikitext: str) -> list[dict]:
    """
    Extract the Drivers' Championship standings table from wikitext.
    Returns a list of dicts: {position, driverId, teamId, points, wins}
    """
    # Find the Drivers' Championship section
    section = re.search(
        r"Drivers' Championship.*?(?=\n==|\Z)", wikitext, re.S | re.I
    )
    if not section:
        print("  [warn] Drivers' Championship section not found")
        return []

    standings = []
    pos = 1

    # Look for table rows with points data: | Driver || Team || pts || wins
    rows = re.findall(
        r"\|\s*(\d+)\s*\|\|\s*(.*?)\s*\|\|\s*(.*?)\s*\|\|\s*(\d+)\s*\|\|\s*(\d+)",
        section.group(0)
    )

    for row in rows:
        raw_pos, raw_driver, raw_team, raw_pts, raw_wins = row
        driver_name = clean(raw_driver).split()[-1]  # use surname
        team_name   = clean(raw_team)

        driver_id = next(
            (v for k, v in DRIVER_KEY_MAP.items() if k.lower() in driver_name.lower()),
            driver_name.lower().replace(" ", "")
        )
        team_id = next(
            (v for k, v in TEAM_KEY_MAP.items() if k.lower() in team_name.lower()),
            team_name.lower().replace(" ", "")
        )

        standings.append({
            "position": int(raw_pos),
            "driverId": driver_id,
            "teamId":   team_id,
            "points":   int(raw_pts),
            "wins":     int(raw_wins),
        })

    if not standings:
        print("  [warn] Could not parse driver standings rows — Wikipedia table format may have changed")

    return standings


def parse_constructor_standings(wikitext: str) -> list[dict]:
    """Extract Constructors' Championship standings."""
    section = re.search(
        r"Constructors' Championship.*?(?=\n==|\Z)", wikitext, re.S | re.I
    )
    if not section:
        print("  [warn] Constructors' Championship section not found")
        return []

    standings = []
    rows = re.findall(
        r"\|\s*(\d+)\s*\|\|\s*(.*?)\s*\|\|\s*(\d+)\s*\|\|\s*(\d+)",
        section.group(0)
    )

    for row in rows:
        raw_pos, raw_team, raw_pts, raw_wins = row
        team_name = clean(raw_team)
        team_id   = next(
            (v for k, v in TEAM_KEY_MAP.items() if k.lower() in team_name.lower()),
            team_name.lower().replace(" ", "")
        )
        standings.append({
            "position": int(raw_pos),
            "teamId":   team_id,
            "points":   int(raw_pts),
            "wins":     int(raw_wins),
        })

    if not standings:
        print("  [warn] Could not parse constructor standings rows")

    return standings


def parse_race_results(wikitext: str) -> list[dict]:
    """
    Extract individual race results. Returns a list of completed race summaries.
    Each entry: {round, raceName, circuit, winner_id, winner_team, fastest_lap_id}
    """
    results = []

    # Match race result blocks: Round N – Race Name
    # Wikipedia uses {{F1 race result}} or similar inline templates, OR
    # a flat results section with "| [[Driver]] || [[Team]] || …" rows.
    # We target the season results summary table which lists:
    # | Rnd | Grand Prix | Pole | Fastest Lap | Winning Driver | Winning Constructor | Report
    header = re.search(r"\|\s*Rnd\b.*?\n(.*?)(?=\n\{\{|\n==|\Z)", wikitext, re.S)
    if not header:
        print("  [warn] Season results table not found")
        return results

    for row in re.finditer(
        r"^\|\s*(\d+)\s*\|\|.*?\[\[([^\]|]+)(?:\|[^\]]+)?\]\]"  # round + GP name
        r".*?\[\[([^\]|]+)(?:\|[^\]]+)?\]\]"                      # pole sitter
        r".*?\[\[([^\]|]+)(?:\|[^\]]+)?\]\]"                      # fastest lap
        r".*?\[\[([^\]|]+)(?:\|[^\]]+)?\]\]"                      # winning driver
        r".*?\[\[([^\]|]+)(?:\|[^\]]+)?\]\]",                     # winning constructor
        header.group(1), re.M
    ):
        rnd, gp, _pole, fl, winner, constructor = row.groups()
        winner_surname = winner.strip().split()[-1]
        winner_id = next(
            (v for k, v in DRIVER_KEY_MAP.items() if k.lower() in winner_surname.lower()),
            winner_surname.lower()
        )
        fl_surname = fl.strip().split()[-1]
        fl_id = next(
            (v for k, v in DRIVER_KEY_MAP.items() if k.lower() in fl_surname.lower()),
            fl_surname.lower()
        )
        team_name = constructor.strip()
        team_id = next(
            (v for k, v in TEAM_KEY_MAP.items() if k.lower() in team_name.lower()),
            team_name.lower().replace(" ", "")
        )
        results.append({
            "round":       int(rnd),
            "raceName":    clean(gp),
            "winnerId":    winner_id,
            "winnerTeam":  team_id,
            "fastestLapId": fl_id,
        })

    if not results:
        print("  [warn] No individual race results parsed yet (season may not have started)")

    return results


def parse_race_statuses(wikitext: str) -> dict[int, str]:
    """
    Return a dict of {round_number → 'completed'|'upcoming'} by checking
    whether each round's Wikipedia section contains result data.
    """
    statuses: dict[int, str] = {}

    # The season summary table uses {{yes}} / {{TBD}} for each round
    # A simpler proxy: look for the results table rows parsed above
    results = parse_race_results(wikitext)
    completed_rounds = {r["round"] for r in results}

    for rnd in range(1, 25):
        statuses[rnd] = "completed" if rnd in completed_rounds else "upcoming"

    return statuses


# ── Driver Ratings Engine ─────────────────────────────────────────────────────
#
# Uses Jolpica-F1 (api.jolpi.ca) — the official open-source replacement for the
# deprecated Ergast API. Identical endpoints, no API key, free.
#
# 6 radar dimensions computed from real career stats:
#   qualifying     → pole rate + top-10 qualifying rate
#   racePace       → win rate + podium rate + points per race
#   tyreManagement → net positions gained per race (strategy/tyre proxy)
#   wetWeather     → manually researched base (no public API source exists)
#   consistency    → finish rate + top-10 finish rate
#   aggression     → total position movement per race + dnf rate
#
# All metrics normalised to 70–99 relative to the current grid.

JOLPICA_BASE = "https://api.jolpi.ca/ergast/f1"

JOLPICA_DRIVER_IDS = {
    "russell":    "russell",    "antonelli":  "antonelli",
    "leclerc":    "leclerc",    "hamilton":   "hamilton",
    "norris":     "norris",     "piastri":    "piastri",
    "verstappen": "max_verstappen", "hadjar": "hadjar",
    "alonso":     "alonso",     "stroll":     "stroll",
    "albon":      "albon",      "sainz":      "sainz",
    "lawson":     "lawson",     "lindblad":   "lindblad",
    "ocon":       "ocon",       "bearman":    "bearman",
    "hulkenberg": "hulkenberg", "bortoleto":  "bortoleto",
    "gasly":      "gasly",      "colapinto":  "colapinto",
    "perez":      "perez",      "bottas":     "bottas",
}

# Wet-weather scores - manually researched, updated rarely
WET_BASE = {
    "hamilton": 97, "verstappen": 94, "alonso": 93,
    "russell":  88, "leclerc":    85, "norris": 84,
    "sainz":    82, "gasly":      80, "piastri": 78,
    "hulkenberg": 78, "ocon":     79, "bottas":  77,
    "perez":    75, "albon":      76, "colapinto": 74,
    "lawson":   73, "stroll":     72, "antonelli": 72,
    "hadjar":   71, "bearman":    72, "bortoleto": 71,
    "lindblad": 70,
}


def jolpica_get(path):
    url = f"{JOLPICA_BASE}/{path}.json?limit=1000"
    req = urllib.request.Request(url, headers={"User-Agent": "APEX-F1-Updater/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        print(f"  [warn] Jolpica request failed ({path}): {e}")
        return {}


def fetch_career_stats(ergast_id):
    """Fetch and aggregate career race + qualifying stats for one driver."""
    stats = {
        "races": 0, "wins": 0, "poles": 0, "podiums": 0,
        "points": 0.0, "dnfs": 0, "finished": 0,
        "pos_gained": 0, "pos_lost": 0, "top10": 0,
    }
    DNF_KEYWORDS = (
        "Retired", "Accident", "Collision", "Spun off", "Engine",
        "Gearbox", "Hydraulics", "Brakes", "Suspension", "Electrical",
        "Mechanical", "Fire", "Tyre", "Wheel", "Oil", "Water", "Fuel",
    )
    data = jolpica_get(f"drivers/{ergast_id}/results")
    for race in data.get("MRData", {}).get("RaceTable", {}).get("Races", []):
        for res in race.get("Results", []):
            stats["races"] += 1
            grid   = int(res.get("grid", 0) or 0)
            pos    = res.get("position", "")
            status = res.get("status", "")
            stats["points"] += float(res.get("points", 0) or 0)
            if any(k in status for k in DNF_KEYWORDS):
                stats["dnfs"] += 1
            elif pos.isdigit():
                finish = int(pos)
                stats["finished"] += 1
                if finish <= 3:  stats["podiums"]    += 1
                if finish <= 10: stats["top10"]      += 1
                if grid > 0:
                    diff = grid - finish
                    if diff > 0: stats["pos_gained"] += diff
                    else:        stats["pos_lost"]   += abs(diff)
            if pos == "1":
                stats["wins"] += 1
    qdata = jolpica_get(f"drivers/{ergast_id}/qualifying")
    for race in qdata.get("MRData", {}).get("RaceTable", {}).get("Races", []):
        for q in race.get("QualifyingResults", []):
            if q.get("position") == "1":
                stats["poles"] += 1
    return stats


def normalise(values, lo=70, hi=99):
    vals = list(values.values())
    vmin, vmax = min(vals), max(vals)
    if vmax == vmin:
        return {k: round((lo + hi) / 2) for k in values}
    return {
        k: round(lo + (v - vmin) / (vmax - vmin) * (hi - lo))
        for k, v in values.items()
    }


def compute_driver_ratings(driver_ids):
    """Return normalised 70-99 ratings for every driver based on Jolpica data."""
    print("\n-> Fetching Jolpica career stats for DNA ratings ...")
    raw = {}
    for did in driver_ids:
        jid = JOLPICA_DRIVER_IDS.get(did, did)
        print(f"  {did} ...", end=" ", flush=True)
        raw[did] = fetch_career_stats(jid)
        r = raw[did]
        print(f"races={r['races']} wins={r['wins']} poles={r['poles']}")

    def rate(num, den):
        return num / den if den > 0 else 0.0

    q  = normalise({d: rate(raw[d]["poles"],  max(raw[d]["races"],1))*60
                     + rate(raw[d]["top10"],  max(raw[d]["races"],1))*40 for d in driver_ids})
    rp = normalise({d: rate(raw[d]["wins"],   max(raw[d]["races"],1))*50
                     + rate(raw[d]["podiums"],max(raw[d]["races"],1))*30
                     + rate(raw[d]["points"], max(raw[d]["races"],1))*20 for d in driver_ids})
    ty = normalise({d: rate(raw[d]["pos_gained"], max(raw[d]["races"],1)) for d in driver_ids})
    cn = normalise({d: rate(raw[d]["finished"],max(raw[d]["races"],1))*60
                     + rate(raw[d]["top10"],  max(raw[d]["races"],1))*40 for d in driver_ids})
    ag = normalise({d: rate(raw[d]["pos_gained"]+raw[d]["pos_lost"],max(raw[d]["races"],1))*70
                     + rate(raw[d]["dnfs"],   max(raw[d]["races"],1))*30 for d in driver_ids})
    wt = normalise({d: WET_BASE.get(d, 73) for d in driver_ids})

    ratings = {}
    for d in driver_ids:
        ratings[d] = {
            "qualifying":     q[d],  "racePace":       rp[d],
            "tyreManagement": ty[d], "wetWeather":     wt[d],
            "consistency":    cn[d], "aggression":     ag[d],
        }
        r = ratings[d]
        print(f"  {d:15} Q={r['qualifying']} RP={r['racePace']} "
              f"TY={r['tyreManagement']} WW={r['wetWeather']} "
              f"CN={r['consistency']} AG={r['aggression']}")
    return ratings


# ── HTML patcher ───────────────────────────────────────────────────────────────

def patch_html(
    html: str,
    driver_standings: list,
    constructor_standings: list,
    race_results: list,
    race_statuses: dict,
    updated_at: str,
    ratings: dict = None,
) -> str:
    """
    Replace the inline JSON data blobs inside the standalone HTML file.
    The init() function holds all five JSON objects as JS literals.
    We locate each one by its surrounding variable assignment and replace it.
    """

    def replace_json_var(src: str, var_name: str, new_data) -> str:
        """
        Replace   const VAR_NAME = { ... };
        with      const VAR_NAME = <new_data_json>;
        The block may span multiple lines and use nested braces.
        """
        pattern = rf"(const\s+{re.escape(var_name)}\s*=\s*)({{[\s\S]*?}})(\s*;)"
        replacement = r"\g<1>" + json.dumps(new_data, ensure_ascii=False) + r"\g<3>"
        result, n = re.subn(pattern, replacement, src, count=1)
        if n == 0:
            print(f"  [warn] Could not find {var_name} in HTML — skipping")
        return result

    # ── 1. Driver standings ───────────────────────────────────────────────────
    if driver_standings:
        # Rebuild driverStandings array inside resData
        # We patch the JSON that's inlined for resData
        # Strategy: find "driverStandings":[...] and replace it
        ds_json = json.dumps(driver_standings, ensure_ascii=False)
        html, n = re.subn(
            r'"driverStandings"\s*:\s*\[[^\]]*\]',
            f'"driverStandings": {ds_json}',
            html, count=1
        )
        if n:
            print(f"  ✓ driverStandings updated ({len(driver_standings)} entries)")
        else:
            print("  [warn] driverStandings key not found in HTML")

    # ── 2. Constructor standings ──────────────────────────────────────────────
    if constructor_standings:
        cs_json = json.dumps(constructor_standings, ensure_ascii=False)
        html, n = re.subn(
            r'"constructorStandings"\s*:\s*\[[^\]]*\]',
            f'"constructorStandings": {cs_json}',
            html, count=1
        )
        if n:
            print(f"  ✓ constructorStandings updated ({len(constructor_standings)} entries)")
        else:
            print("  [warn] constructorStandings key not found in HTML")

    # ── 3. Race statuses in rData (races array) ───────────────────────────────
    if race_statuses:
        def patch_race_status(m):
            race_json = m.group(0)
            # Extract round number
            rnd_match = re.search(r'"round"\s*:\s*(\d+)', race_json)
            if not rnd_match:
                return race_json
            rnd = int(rnd_match.group(1))
            status = race_statuses.get(rnd, "upcoming")
            # Replace status field
            patched = re.sub(
                r'"status"\s*:\s*"[^"]*"',
                f'"status": "{status}"',
                race_json
            )
            return patched

        # Find each race object in the races array and patch its status
        html = re.sub(
            r'\{[^{}]*"round"\s*:\s*\d+[^{}]*\}',
            patch_race_status,
            html
        )
        completed_count = sum(1 for s in race_statuses.values() if s == "completed")
        print(f"  ✓ race statuses updated ({completed_count} completed)")

    # ── 4. Driver ratings ─────────────────────────────────────────────────────
    if ratings:
        def patch_one_driver(m):
            block = m.group(0)
            id_match = re.search(r'"id"\s*:\s*"([^"]+)"', block)
            if not id_match or id_match.group(1) not in ratings:
                return block
            new_r = json.dumps(ratings[id_match.group(1)], ensure_ascii=False)
            patched, n = re.subn(
                r'"ratings"\s*:\s*\{[^}]*\}',
                f'"ratings": {new_r}',
                block
            )
            return patched if n else block

        html, n = re.subn(
            r'\{[^{}]*"id"\s*:\s*"[^"]+"[^{}]*"ratings"\s*:\s*\{[^}]*\}[^{}]*\}',
            patch_one_driver,
            html
        )
        print(f"  ✓ driver ratings updated ({n} drivers)")

    # ── 5. Inject last-updated timestamp into footer ──────────────────────────
    html = re.sub(
        r'(F1 2026 Season Analytics).*?(</div>)',
        rf'\1 · Updated {updated_at}\2',
        html, count=1
    )

    return html


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    print("═" * 56)
    print("  APEX F1 2026 — Auto-updater")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("═" * 56)

    if not HTML_FILE.exists():
        print(f"✗ {HTML_FILE} not found. Run from the repo root.")
        raise SystemExit(1)

    # 1. Fetch Wikipedia
    print("\n→ Fetching Wikipedia wikitext …")
    try:
        wikitext = fetch_wikitext()
        print(f"  ✓ {len(wikitext):,} chars received")
    except urllib.error.URLError as e:
        print(f"  ✗ Network error: {e}")
        raise SystemExit(1)

    # 2. Parse
    print("\n-> Parsing standings ...")
    driver_standings      = parse_driver_standings(wikitext)
    constructor_standings = parse_constructor_standings(wikitext)
    race_results          = parse_race_results(wikitext)
    race_statuses         = parse_race_statuses(wikitext)

    print(f"  drivers:      {len(driver_standings)} entries")
    print(f"  constructors: {len(constructor_standings)} entries")
    print(f"  race results: {len(race_results)} races")

    # 2b. Compute driver ratings from Jolpica career stats
    driver_ratings = compute_driver_ratings(list(JOLPICA_DRIVER_IDS.keys()))

    # 3. Patch HTML
    print("\n-> Patching HTML ...")
    html = HTML_FILE.read_text(encoding="utf-8")
    updated_at = datetime.now(timezone.utc).strftime("%d %b %Y %H:%M UTC")
    html = patch_html(html, driver_standings, constructor_standings,
                      race_results, race_statuses, updated_at,
                      ratings=driver_ratings)

    # 4. Write
    HTML_FILE.write_text(html, encoding="utf-8")
    print(f"\n✓ {HTML_FILE} updated ({HTML_FILE.stat().st_size:,} bytes)")
    print("═" * 56)


if __name__ == "__main__":
    main()
