# Discord Class Updater

Standalone GitHub Action that keeps the Discord class names in your CSS files up to date.

Discord regularly renames its CSS classes (`sidebar__5e434` → `sidebar_pog62O`), which breaks themes and snippets.
This project tracks those changes itself, straight from Discord, and uses them to fix your CSS files through a pull request.

## Quick start

Add this file to your repository, for example `.github/workflows/discord-classes.yml`:

```yml
name: Discord classes

on:
  schedule:
    - cron: '12 3 * * *'    # Every day at 3:12 (UTC)
  workflow_dispatch:

jobs:
  update:
    runs-on: ubuntu-latest
    permissions:
      contents: write
      pull-requests: write
    steps:
      - uses: actions/checkout@v6
      - uses: TirOFlanc/Discord-Class-Updater@main
        with:
          files: '*.css'
          language: en
```

Then, in your repository settings, enable **Settings → Actions → General → Allow GitHub Actions to create and approve pull requests**, otherwise the pull request can't be created.

That's it. When a class in your CSS has changed, you get a pull request with a report. When nothing changed, nothing happens.

## Inputs

| Name | Default | Description |
|---|---|---|
| `files` | `**/*.css` | Files to process (glob patterns, comma-separated or one per line) |
| `ignores` | *(empty)* | Files, folders or patterns to leave untouched (file name, path, folder or glob pattern) |
| `ignore-class-names` | *(empty)* | Terms to ignore: a class that contains one of them, partly or fully, is never replaced nor reported (`bd-` ignores `bd-addon-card`, `headerContainer` ignores `headerContainer__095fe`). Case-insensitive |
| `language` | `en` | Language of the pull request and of the warnings (see [Languages](#languages)) |
| `pull-request` | `true` | Opens (or updates) a pull request when classes were replaced. `false` to only edit the files |
| `branch` | `discord-class-updater` | Branch of the pull request |
| `title` | *(in the chosen language)* | Title of the pull request |
| `commit-message` | *(same as the title)* | Commit message |
| `report` | runner temp folder | Path of the Markdown report |
| `max-data-age` | `3` | Warn when Discord tracking hasn't worked for more than this many days |
| `fail-if-stale` | `false` | `true` to also make the run fail when the data is too old, so GitHub sends you its failure email |

## Outputs

| Name | Content |
|---|---|
| `changed` | `true` if at least one class was replaced |
| `replaced` | Number of classes replaced |
| `missing` | Number of classes not found |
| `report` | Path of the Markdown report |
| `stale` | `true` if the data is older than `max-data-age` |

## How it works

### 1. Tracking (`track_discord.py`, every 6 hours)

The `.github/workflows/track-discord.yml` workflow runs `track_discord.py`, which, for Discord **Stable** and **Canary**:

1. reads the build number on `discord.com/app` (or `canary.discord.com/app`); if it hasn't changed, it stops there;
2. downloads every JS file of the app (about 6,800, including the chunks Discord names outside its main list) and extracts the CSS class names (about 24,000);
3. compares them with the previous build of the same version:
   - all classes of a CSS module share the same hash: when a module changes hash, it's matched with the new module that has the same class names, then its classes one by one;
   - a single class moving to another module is also tracked if its name is unique in Discord;
4. saves the result in `data/` and commits it.

Each successful run also updates `last_check` in `builds.json`: on every new build, otherwise once a day (a small daily commit). It proves tracking works, and keeps the repository active so GitHub never disables the schedule.

Canary gets changes first, so the old → new pair is usually known before Stable switches.

If the extraction finds far fewer classes than usual (Discord changed the way its JS is built), the workflow stops with an error **without touching the data**.

### 2. Updating CSS files (the action, `update_classes.py`)

- It only uses this repository's `data/` folder: no call to any other project.
- Changes confirmed by hand in `data/manual.txt` come first: renamed classes that no algorithm can guess (e.g. `nickname` → `displayName`) and classes removed by Discord.
- A class is only replaced **if the new one exists in Discord Stable today**.
- If a class changed several times (a → b → c), it follows the chain up to the current name, even if your theme missed several updates.
- When Discord split a module in two, an old class can lead to two current classes. The tool then picks the one whose module your file already uses, or else the one whose module looks most like the old one, and marks it *please check* in the report with the other possibility.
- As a last resort, if the other classes of the same module changed hash, it tries the same name with that new hash. These replacements are marked *inferred, please check* in the report.
- Classes that can't be found are left untouched: they are listed in the report with their line and, when there is one, the current module that looks most like their old one (or *removed by Discord* when confirmed). They are also shown as one warning per file in the run.
- A single pass per file, whole class names only: no double replacement.
- If tracking hasn't worked for more than `max-data-age` days (`last_check` too old), it warns in the run and at the top of the report, because classes renamed since then can't be detected. With `fail-if-stale: true`, the run also fails, after the pull request is created.

## Data (`data/`)

| File | Content |
|---|---|
| `stable.txt` | Every class of Discord Stable (one per line) |
| `canary.txt` | Every class of Discord Canary |
| `map.txt` | Old name → new name table (one pair per line), filled automatically |
| `manual.txt` | Changes confirmed by hand: `old new`, or `old -` for a class removed by Discord |
| `builds.json` | Number and date of the last recorded build for each version, and `last_check`: the last time tracking worked |

The starting table comes from a one-time import done on November 8, 2026:
- the history of 2,724 Discord builds (February 2025 → November 2026), analyzed with `track_discord.py`;
- the table of [fedeericodl/discord-update-classnames](https://github.com/fedeericodl/discord-update-classnames), under the MIT license (see `data/LICENSE-fedeericodl.txt`);
- about 4,500 pairs for classes that both histories had missed since November 4, 2026, recovered by comparing the last build before that date with the complete extraction of November 8.

Since then, everything is updated by this repository alone.

## Running locally

Only Python 3 is needed:

```
python3 track_discord.py
python3 update_classes.py --files "*.css" --ignores "RefreshTitleBar.css" --ignore-class-names "bd-,vc-" --language en
```

## Tests

The `.github/workflows/test.yml` workflow runs `tests/run_tests.py` on every change pushed to `main` and on every pull request, so a broken change shows a red ❌ before it reaches anyone. It checks:

- both scripts load, the 14 languages have every text and stay in alphabetical order;
- the format of `data/` (`map.txt`, `manual.txt`, `builds.json`, class lists);
- the extraction on a sample of Discord's JS (the 3 shapes of CSS modules, the specially named chunks);
- the matching of old and new classes;
- the CSS results on fixed examples (`tests/input` → `tests/expected`): renames, chains, inferred and ambiguous classes, manual fixes, removed and missing classes, ignored files and terms, languages and the stale data warning.

The tests use their own small data (`tests/data`), so they never break when Discord renames classes. Run them locally with `python3 tests/run_tests.py`.

## Languages

The pull request, its report and the run warnings are available in:

| Code | Language | Code | Language |
|---|---|---|---|
| `ar` | Arabic | `ko` | Korean |
| `de` | German | `pl` | Polish |
| `en` | English (default) | `pt` | Portuguese |
| `es` | Spanish | `ru` | Russian |
| `fr` | French | `tr` | Turkish |
| `it` | Italian | `uk` | Ukrainian (not "United Kingdom": use `en`) |
| `ja` | Japanese | `zh` | Chinese (simplified) |

Codes are case-insensitive and regional variants work too (`FR`, `fr-FR`, `pt-BR`, `zh-TW`...). An unknown code falls back to English with a warning.

### Adding or improving a language

All texts are in the `MESSAGES` dictionary at the top of `update_classes.py`. To add a language, copy the `en` block, give it the two-letter code of your language, put it in alphabetical order and translate the values (keep the `{...}` parts as they are). Native speakers are welcome to improve the existing translations. Pull requests are welcome.

## Contributing a fix

If you found by hand the new name of a class the tool couldn't find (with DevTools), add it to `data/manual.txt` (`old new`, or `old -` if Discord removed it) and open a pull request: everyone using the action will benefit from it.

## Limits

- If Discord rebuilds a component (instead of just renaming its classes), no tracking can guess the new name: it has to be found with DevTools.
- If Discord changes the way its JS is built, the extraction may break. Tracking then stops with an error without damaging the data, and `track_discord.py` needs to be adapted.
