"""Tests for Discord Class Updater. Run from anywhere:  python3 tests/run_tests.py

They use their own small fixed data (tests/data), so they never break when Discord renames classes.
"""

import datetime
import filecmp
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

TESTS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TESTS)
failures = []


def check(label, ok, detail=""):
    print(("✔ " if ok else "✘ ") + label + ("" if ok or not detail else f"\n    {detail}"))
    if not ok:
        failures.append(label)


def load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, f"{name}.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def prepare_data(folder, last_check_days_ago=0, build="123456"):
    """Copy the test data and add what the tool needs: enough classes and a builds.json."""
    shutil.copytree(os.path.join(TESTS, "data"), folder)
    with open(os.path.join(folder, "stable.txt"), "a", encoding="utf-8") as f:
        f.write("".join(f"filler{i}_ZZZZZZ\n" for i in range(10000)))
    date = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=last_check_days_ago)
    with open(os.path.join(folder, "builds.json"), "w", encoding="utf-8") as f:
        json.dump({"last_check": date.strftime("%Y-%m-%d %H:%M UTC"),
                   "stable": {"build": build, "classes": 10011, "date": "2026-11-08 12:00 UTC"}}, f)


def run_action(work, data, language="en", max_age="3", data_url="", github=None):
    """Run update_classes.py like the GitHub Action does, return (stdout, outputs, report).
    github: GitHub Actions variables to simulate (repository, commit...), none by default."""
    out_file = os.path.join(work, "outputs.txt")
    report = os.path.join(work, "report.md")
    open(out_file, "w").close()
    env = dict(os.environ, INPUT_FILES="*.css", INPUT_IGNORES="ignored.css", INPUT_IGNORE_CLASS_NAMES="vc-",
               INPUT_LANGUAGE=language, INPUT_REPORT=report, INPUT_MAX_DATA_AGE=max_age, INPUT_DATA_URL=data_url,
               GITHUB_OUTPUT=out_file, RUNNER_TEMP=work)
    # The tests themselves run in GitHub Actions: start from a clean state, then add what is asked
    for name in ("GITHUB_STEP_SUMMARY", "GITHUB_REPOSITORY", "GITHUB_SERVER_URL", "GITHUB_WORKSPACE", "GITHUB_SHA",
                 "INPUT_LINK_BRANCH"):
        env.pop(name, None)
    env.update(github or {})
    result = subprocess.run([sys.executable, "-B", os.path.join(ROOT, "update_classes.py"), "--data", data],
                            cwd=os.path.join(work, "css"), env=env, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    outputs = dict(line.split("=", 1) for line in open(out_file, encoding="utf-8").read().splitlines() if "=" in line)
    return result.stdout, outputs, open(report, encoding="utf-8").read()


def test_scripts_and_languages():
    update = load("update_classes")
    load("track_discord")
    check("Both scripts load without errors", True)
    keys = set(update.MESSAGES["en"])
    for code, texts in update.MESSAGES.items():
        missing = keys ^ set(texts)
        placeholders = [k for k, v in texts.items()
                        for p in ("{n}", "{list}", "{build}", "{date}") if (p in v) != (p in update.MESSAGES["en"][k])]
        check(f"Language '{code}' has every text", not missing and not placeholders, f"{missing or placeholders}")
    check("Language blocks are in alphabetical order", list(update.MESSAGES) == sorted(update.MESSAGES))


def test_real_data():
    track = load("track_discord")
    data = os.path.join(ROOT, "data")
    bad = [l for l in open(os.path.join(data, "map.txt"), encoding="utf-8")
           if len(l.split()) != 2 or not all(track.RE_CLASS.match(x) for x in l.split())]
    check("data/map.txt: every line is 'old new'", not bad, f"{bad[:3]}")
    bad = [l for l in open(os.path.join(data, "manual.txt"), encoding="utf-8")
           if l.strip() and not l.startswith("#")
           and (len(l.split()) != 2 or not track.RE_CLASS.match(l.split()[0])
                or not (l.split()[1] == "-" or track.RE_CLASS.match(l.split()[1])))]
    check("data/manual.txt: every line is 'old new' or 'old -'", not bad, f"{bad[:3]}")
    for name in ("stable.txt", "canary.txt"):
        count = sum(1 for l in open(os.path.join(data, name), encoding="utf-8") if l.strip())
        check(f"data/{name}: more than 10,000 classes", count > 10000, f"{count} classes")
    builds = json.load(open(os.path.join(data, "builds.json"), encoding="utf-8"))
    check("data/builds.json: has the stable and canary builds",
          all(isinstance(builds.get(v), dict) and builds[v].get("build") for v in ("stable", "canary")))


def test_extraction():
    track = load("track_discord")
    js = open(os.path.join(TESTS, "samples", "discord-modules.js"), encoding="utf-8").read()
    found = track.extract_classes(js)
    expected = {"alpha_MOD001", "beta_MOD001", "gamma_MOD001", "delta_MOD002", "eps_MOD002", "zeta_MOD003"}
    check("Extraction reads the 3 shapes of Discord CSS modules and skips other objects",
          found == expected, f"found {sorted(found)}")
    web = open(os.path.join(TESTS, "samples", "web.js"), encoding="utf-8").read()
    files = track.chunk_files(web)
    check("Chunk list includes the main map and the specially named chunks",
          files == {"aaa111.js", "bbb222.js", "715528.4b47d81567290fff.js"}, f"found {sorted(files)}")


def test_matching():
    track = load("track_discord")
    before = {"container__1a2b3", "header__1a2b3", "title__1a2b3", "solo__ffff1", "one__bbbb1", "two__bbbb1"}
    after = {"container_AAAAAA", "header_AAAAAA", "title_AAAAAA", "solo_SOLO01",
             "one_TIE001", "two_TIE001", "one_TIE002", "two_TIE002"}
    pairs = set(track.match(before, after))
    expected = {("container__1a2b3", "container_AAAAAA"), ("header__1a2b3", "header_AAAAAA"),
                ("title__1a2b3", "title_AAAAAA"), ("solo__ffff1", "solo_SOLO01")}
    check("Matching follows a module that changed hash and a class moved alone, and never guesses a tie",
          pairs == expected, f"found {sorted(pairs)}")


def test_update():
    with tempfile.TemporaryDirectory() as work:
        data = os.path.join(work, "data")
        prepare_data(data)
        css = os.path.join(work, "css")
        shutil.copytree(os.path.join(TESTS, "input"), css)
        stdout, outputs, report = run_action(work, data)

        for name in sorted(os.listdir(os.path.join(TESTS, "expected"))):
            same = filecmp.cmp(os.path.join(css, name), os.path.join(TESTS, "expected", name), shallow=False)
            check(f"CSS result as expected: {name}", same,
                  open(os.path.join(css, name), encoding="utf-8").read() if not same else "")
        check("Outputs: 8 replaced, 2 not found, data not stale",
              (outputs.get("changed"), outputs.get("replaced"), outputs.get("missing"), outputs.get("stale"))
              == ("true", "8", "2", "false"), f"{outputs}")
        for label, text in [
            ("Report counts the classes to check", "**8** (including 3 to check)"),
            ("Report marks the inferred class", "`title__1a2b3` → `title_AAAAAA` *(inferred, please check)*"),
            ("Report gives the other possibility of an ambiguous class", "other possibility: `icon_SPLITa`"),
            ("Report shows the class removed by Discord", "`gone__00002` (line 7) — removed by Discord"),
            ("Report shows the missing class without a fake lead", "`lost__00001` (line 8) — no lead"),
        ]:
            check(label, text in report, f"not found in the report:\n{report}")
        check("One warning per file, linked to the right line", "file=main.css,line=7," in stdout, stdout)
        check("Ignored terms are neither replaced nor reported", "vc-toolbar" not in report)
        check("Outside GitHub Actions, file names and lines are plain text", "](" not in report, report)
        check("Report starts with the review reminder as a title",
              report.startswith("# Review before merging!\n"), report)
        check("Classes not found come first, then the folded replacements",
              re.search(r"\n### Classes not found\n.*\n<details><summary><b>Replacements</b></summary>\n", report, re.S)
              is not None, report)
        check("The folded block closes right after the last replacement (no gap in Discord)",
              re.search(r"\n- `[^\n]+\n</details>\n", report) is not None, report)

        stdout, outputs, report = run_action(work, data)
        check("A second run changes nothing", outputs.get("replaced") == "0", f"{outputs}")

        shutil.rmtree(css)
        shutil.copytree(os.path.join(TESTS, "input"), css)
        stdout, outputs, report = run_action(work, data, language="fr")
        check("Language 'fr' gives a French title and report",
              outputs.get("title") == "🔄 Mise à jour des classes Discord" and "Classes remplacées" in report)

    with tempfile.TemporaryDirectory() as work:
        data = os.path.join(work, "data")
        prepare_data(data, last_check_days_ago=10)
        shutil.copytree(os.path.join(TESTS, "input"), os.path.join(work, "css"))
        stdout, outputs, report = run_action(work, data)
        check("Old data (10 days) triggers the stale warning",
              outputs.get("stale") == "true" and "Data not updated for 10 days" in report, f"{outputs}")
        stdout, outputs, report = run_action(work, data, max_age="15")
        check("max-data-age raises the limit", outputs.get("stale") == "false", f"{outputs}")


def test_links():
    update = load("update_classes")
    with tempfile.TemporaryDirectory() as work:
        os.environ.update(GITHUB_REPOSITORY="owner/repo", GITHUB_SERVER_URL="https://github.com", GITHUB_WORKSPACE=work)
        try:
            url = update.file_url(os.path.join(work, "themes", "my theme (2).css"), "updates")
            outside = update.file_url(os.path.join(os.path.dirname(work), "elsewhere.css"), "updates")
        finally:
            for name in ("GITHUB_REPOSITORY", "GITHUB_SERVER_URL", "GITHUB_WORKSPACE"):
                os.environ.pop(name, None)
        check("File addresses keep the folders and encode spaces and brackets",
              url == "https://github.com/owner/repo/blob/updates/themes/my%20theme%20%282%29.css", url)
        check("No address for a file outside the repository", outside is None, f"{outside}")

    with tempfile.TemporaryDirectory() as work:
        data = os.path.join(work, "data")
        prepare_data(data)
        css = os.path.join(work, "css")
        shutil.copytree(os.path.join(TESTS, "input"), css)
        github = {"GITHUB_REPOSITORY": "owner/repo", "GITHUB_SERVER_URL": "https://github.com",
                  "GITHUB_WORKSPACE": css, "GITHUB_SHA": "abc123", "INPUT_LINK_BRANCH": "discord-class-updater"}
        base = "https://github.com/owner/repo/blob/"
        stdout, outputs, report = run_action(work, data, github=github)
        check("In the pull request, file names link to the files on its branch",
              f"**[main.css]({base}discord-class-updater/main.css)**" in report, report)
        check("In the pull request, line numbers link to the lines",
              f"`gone__00002` ([line 7]({base}discord-class-updater/main.css#L7))" in report, report)
        stdout, outputs, report = run_action(work, data, github=github)
        check("Without replacements (no pull request), links point to the checked commit",
              f"([line 7]({base}abc123/main.css#L7))" in report and "discord-class-updater" not in report, report)


def test_data_download():
    with tempfile.TemporaryDirectory() as work:
        bundled, remote = os.path.join(work, "data"), os.path.join(work, "remote")
        prepare_data(bundled, build="111111")
        prepare_data(remote, build="222222")
        shutil.copytree(os.path.join(TESTS, "input"), os.path.join(work, "css"))
        url = "file://" + remote.replace(os.sep, "/")
        stdout, outputs, report = run_action(work, bundled, data_url=url)
        check("Fresh data is downloaded from data-url and used", "build 222222" in report and "Data downloaded" in stdout,
              stdout)
        shutil.rmtree(os.path.join(work, "css"))
        shutil.copytree(os.path.join(TESTS, "input"), os.path.join(work, "css"))
        stdout, outputs, report = run_action(work, bundled, data_url="file:///nowhere/at/all")
        check("If the download fails, the bundled data is used with a warning",
              "build 111111" in report and "couldn't be downloaded" in stdout and outputs.get("replaced") == "8", stdout)


if __name__ == "__main__":
    for test in (test_scripts_and_languages, test_real_data, test_extraction, test_matching, test_update,
                 test_links, test_data_download):
        try:
            test()
        except Exception as e:  # a crash is a failure too
            check(f"{test.__name__} ran without crashing", False, repr(e))
    print()
    if failures:
        print(f"{len(failures)} test(s) failed")
        sys.exit(1)
    print("All tests passed")
