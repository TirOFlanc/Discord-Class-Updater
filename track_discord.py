"""Track Discord class names straight from the source (Stable and Canary).

On each run, for each Discord version:
  1. read the build number on https://discord.com/app (or canary); if it hasn't changed, nothing to do;
  2. download every JS file of the app and extract the CSS class names;
  3. compare with the previous list: when a CSS module changes hash, its classes are
     matched one by one (old name -> new name) and added to data/map.txt;
  4. save the new list (data/stable.txt, data/canary.txt) and data/builds.json.

No dependencies: Python 3 is enough.
  python3 track_discord.py [--data data] [--versions stable,canary]
"""

import argparse
import collections
import concurrent.futures
import datetime
import json
import os
import re
import sys
import time
import urllib.request

SITES = {"stable": "https://discord.com", "canary": "https://canary.discord.com", "ptb": "https://ptb.discord.com"}
UA = "Mozilla/5.0 (compatible; discord-class-updater)"

RE_SCRIPT = re.compile(r'<script defer src="/assets/([\w.-]+\.js)"></script>')
RE_BUILD = re.compile(r'BUILD_NUMBER"\s*:\s*"(\d+)"')
RE_CHUNKS = re.compile(r'\(({(?:\w+:"\w+",)*\w+:"\w+"})\)\[\w+\]\+"\.js"')
RE_TERNARY = re.compile(r'"(\d+)"===\w+\?(?:""\+\w+\+)?"(?:\d+)?\.([a-f0-9]+)\.js"')

# CSS modules in Discord's JS, 3 known shapes:
#   123(e){e.exports={a:"name_hash",...}}   123(e,t,n){n.r(e.exports={...})}   123(e,t,n){var r={...}
RE_MODULE = re.compile(r'(\d+)\(([\w$]+)(?:,[\w$]+)*\)\{(?:(?:[\w$]+\.r\()?\2\.exports=|var [\w$]+=)\{')
RE_REF = re.compile(r'[\w$]+\(\d+\)(?:\.[\w$]+|\["[^"]*"\])')  # classes borrowed from another module
RE_PAIR = re.compile(r'(?:^|,)(?:[\w$]+|"[^"]*"):((?:"[^"]*"|\+)+)(?=,|$)')
RE_CLASS = re.compile(r"^[A-Za-z][\w/-]*_[\w-]{6}$")

MIN_CLASSES = 10000      # below that, extraction is probably broken: nothing is written
MAX_DROP = 0.30          # same if more than 30% of the classes disappear at once


def log(msg):
    print(msg, flush=True)


def get(url, attempts=4):
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read().decode("utf-8", errors="replace")
        except Exception:
            if i == attempts - 1:
                raise
            time.sleep(2 * (i + 1))


# ---------------------------------------------------------------- extraction

def object_end(t, i):
    """Position of the brace closing the object opened just before i."""
    depth = 1
    while i < len(t):
        c = t[i]
        if c == '"':
            i += 1
            while i < len(t) and t[i] != '"':
                i += 2 if t[i] == "\\" else 1
        elif c in "{[(":
            depth += 1
        elif c in "}])":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def extract_classes(js):
    classes = set()
    for m in RE_MODULE.finditer(js):
        end = object_end(js, m.end())
        if end < 0:
            continue
        body = RE_REF.sub("", js[m.end():end])
        pairs = RE_PAIR.findall(body)
        if not pairs:
            continue
        found, nb = [], 0
        for value in pairs:
            tokens = [x for s in re.findall(r'"([^"]*)"', value) for x in s.split()]
            if tokens and all(RE_CLASS.match(x) for x in tokens):
                found += tokens
                nb += 1
        # at least half of the entries must be classes, otherwise it's not a CSS module
        if nb and nb * 2 >= len(pairs):
            classes.update(found)
    return classes


def list_files(site):
    html = get(f"{site}/app")
    build = RE_BUILD.search(html)
    scripts = RE_SCRIPT.findall(html)
    web = next((s for s in scripts if s.startswith("web.")), None)
    if not scripts or not web:
        raise RuntimeError("scripts not found in the app page")
    js = get(f"{site}/assets/{web}")
    files = set(scripts)
    for block in RE_CHUNKS.findall(js):
        for h in json.loads(re.sub(r"(\w+):", r'"\1":', block)).values():
            files.add(f"{h}.js")
    for key, h in RE_TERNARY.findall(js):
        files.add(f"{key}.{h}.js")
    if len(files) < 100:
        raise RuntimeError(f"suspicious list of JS files ({len(files)} files)")
    return (build.group(1) if build else web), sorted(files)


def build_classes(site, files, cache):
    """Download and parse the files (files already seen during this run are reused)."""
    todo = [f for f in files if f not in cache]

    def one(f):
        return f, extract_classes(get(f"{site}/assets/{f}"))

    with concurrent.futures.ThreadPoolExecutor(16) as pool:
        for i, (f, cl) in enumerate(pool.map(one, todo), 1):
            cache[f] = cl
            if i % 1000 == 0:
                log(f"  {i}/{len(todo)} files")
    return set().union(*(cache[f] for f in files))


# ---------------------------------------------------------------- matching

def group(classes):
    """{hash: {name: class}}: all classes of a CSS module share the same hash."""
    g = collections.defaultdict(dict)
    for c in classes:
        g[c[-6:]][c[:-7]] = c
    return g


def match(before, after, threshold=0.5):
    """Match each module that disappeared with the new module that looks most like it
    (same class names), then its classes one by one."""
    A, B = group(before), group(after)
    gone = [h for h in A if h not in B]
    new = {h for h in B if h not in A}
    index = collections.defaultdict(set)
    for h in new:
        for name in B[h]:
            index[name].add(h)
    pairs = []
    for h in gone:
        names = set(A[h])
        common = collections.Counter(c for name in names for c in index.get(name, ()))
        scores = sorted(
            ((n / (len(names) + len(B[c]) - n), c) for c, n in common.items()), reverse=True
        )
        if not scores or scores[0][0] < threshold:
            continue
        if len(scores) > 1 and scores[1][0] == scores[0][0]:
            continue  # two modules equally similar: don't guess
        target = B[scores[0][1]]
        pairs += [(A[h][name], target[name]) for name in sorted(names & set(target))]

    # Classes moved alone from one module to another: if a name exists only once
    # in the whole of Discord before and after, and the class changed, it's the same one.
    covered = {a for a, _ in pairs}
    count_before = collections.Counter(c[:-7] for c in before)
    count_after = collections.Counter(c[:-7] for c in after)
    appeared = {c[:-7]: c for c in after - before if count_after[c[:-7]] == 1}
    pairs += [(c, appeared[c[:-7]]) for c in before - after
              if c not in covered and count_before[c[:-7]] == 1 and c[:-7] in appeared]
    return pairs


# ---------------------------------------------------------------- data files

def read_list(path):
    if not os.path.exists(path):
        return set()
    with open(path, encoding="utf-8") as f:
        return {l.strip() for l in f if l.strip()}


def write_list(path, lines):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(sorted(lines)) + "\n")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--data", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))
    p.add_argument("--versions", default="stable,canary")
    args = p.parse_args()
    os.makedirs(args.data, exist_ok=True)

    builds_path = os.path.join(args.data, "builds.json")
    builds = json.load(open(builds_path, encoding="utf-8")) if os.path.exists(builds_path) else {}
    map_path = os.path.join(args.data, "map.txt")
    table = read_list(map_path)
    cache, summary = {}, []

    for version in [v.strip() for v in args.versions.split(",") if v.strip()]:
        site = SITES[version]
        build, files = list_files(site)
        if builds.get(version, {}).get("build") == build:
            log(f"{version}: build {build} already recorded")
            continue
        log(f"{version}: new build {build}, {len(files)} JS files")
        classes = build_classes(site, files, cache)

        list_path = os.path.join(args.data, f"{version}.txt")
        before = read_list(list_path)
        if len(classes) < MIN_CLASSES or (before and len(classes) < len(before) * (1 - MAX_DROP)):
            print(f"::error::{version}: {len(classes)} classes found (before: {len(before)}), "
                  "extraction is probably broken, data left untouched")
            sys.exit(1)

        added = [f"{a} {n}" for a, n in match(before, classes) if f"{a} {n}" not in table] if before else []
        table.update(added)
        write_list(list_path, classes)
        builds[version] = {
            "build": build,
            "date": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "classes": len(classes),
        }
        summary.append(f"- **{version}**: build {build}, {len(classes)} classes, {len(added)} new matches")
        log(summary[-1][2:].replace("**", ""))

    write_list(map_path, table)
    with open(builds_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(builds, f, indent=2, sort_keys=True)
        f.write("\n")
    if summary and os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write("\n".join(summary) + "\n")


if __name__ == "__main__":
    main()
