"""Update Discord class names in CSS files.

Data (data/ folder next to this script, kept up to date by track_discord.py):
  - stable.txt : every class of Discord Stable today;
  - map.txt    : old name -> new name table, one pair per line.

A class is only replaced if the new one really exists in Discord Stable today.
Classes that can't be found are left untouched and listed in the report.

Locally:
  python3 update_classes.py --files "*.css" --ignores "RefreshTitleBar.css" --ignore-class-names "bd-,vc-" --language en
In a GitHub Action, settings come from
INPUT_FILES / INPUT_IGNORES / INPUT_IGNORE_CLASS_NAMES / INPUT_REPORT / INPUT_LANGUAGE.
"""

import argparse
import collections
import fnmatch
import glob
import json
import os
import re
import sys

# .className_hash6  (old format: name__1a2b3 / name_1a2b3c, new format: name_aB3-x_)
RE_CLASS = re.compile(r"\.([A-Za-z][\w-]*_[\w-]{6})(?![\w-])")
RE_DISCORD = re.compile(r"(__[0-9a-f]{5}|_[0-9a-f]{6}|_[\w-]*[A-Z0-9_-][\w-]*)$")

# Texts of the pull request and of the run warnings.
# Blocks are sorted by language code. To add a language, copy the "en" block,
# put it in alphabetical order and translate the values ({...} stay as they are).
MESSAGES = {
    "ar": {
        "title": "🔄 تحديث أسماء فئات Discord",
        "intro": "تحديث تلقائي لأسماء فئات Discord. يُرجى المراجعة قبل الدمج.",
        "replaced": "✅ الفئات المستبدلة: **{n}**",
        "to_check": " (منها {n} بحاجة إلى مراجعة)",
        "missing": "⚠️ الفئات غير الموجودة: **{n}** (غيّر Discord هذا المكوّن، أصلِحه يدويًا باستخدام DevTools)",
        "replacements": "الاستبدالات",
        "inferred": "مُستنتَجة، يُرجى المراجعة",
        "missing_title": "الفئات غير الموجودة",
        "line": "السطر {n}",
        "same_name": "الاسم نفسه حاليًا: {list}",
        "none": "لا شيء",
        "data": "البيانات: Discord Stable، الإصدار {build} ({date})",
        "warning": "الفئات غير الموجودة: {n}",
    },
    "de": {
        "title": "🔄 Aktualisierung der Discord-Klassen",
        "intro": "Automatische Aktualisierung der Discord-Klassennamen. Bitte vor dem Mergen prüfen.",
        "replaced": "✅ Ersetzte Klassen: **{n}**",
        "to_check": " (davon {n} zu prüfen)",
        "missing": "⚠️ Nicht gefundene Klassen: **{n}** (Komponente von Discord geändert, bitte manuell mit den DevTools korrigieren)",
        "replacements": "Ersetzungen",
        "inferred": "abgeleitet, bitte prüfen",
        "missing_title": "Nicht gefundene Klassen",
        "line": "Zeile {n}",
        "same_name": "heute gleicher Name: {list}",
        "none": "keine",
        "data": "Daten: Discord Stable Build {build} ({date})",
        "warning": "Nicht gefundene Klassen: {n}",
    },
    "en": {
        "title": "🔄 Update Discord class names",
        "intro": "Automatic update of Discord class names. Please review before merging.",
        "replaced": "✅ Classes replaced: **{n}**",
        "to_check": " (including {n} to check)",
        "missing": "⚠️ Classes not found: **{n}** (component changed by Discord, fix it manually with DevTools)",
        "replacements": "Replacements",
        "inferred": "inferred, please check",
        "missing_title": "Classes not found",
        "line": "line {n}",
        "same_name": "same name today: {list}",
        "none": "none",
        "data": "Data: Discord Stable build {build} ({date})",
        "warning": "Classes not found: {n}",
    },
    "es": {
        "title": "🔄 Actualización de las clases de Discord",
        "intro": "Actualización automática de los nombres de clases de Discord. Revísala antes de fusionar.",
        "replaced": "✅ Clases reemplazadas: **{n}**",
        "to_check": " (de las cuales {n} por revisar)",
        "missing": "⚠️ Clases no encontradas: **{n}** (componente modificado por Discord, corrígelo a mano con las DevTools)",
        "replacements": "Reemplazos",
        "inferred": "deducida, por revisar",
        "missing_title": "Clases no encontradas",
        "line": "línea {n}",
        "same_name": "mismo nombre hoy: {list}",
        "none": "ninguno",
        "data": "Datos: Discord Stable build {build} ({date})",
        "warning": "Clases no encontradas: {n}",
    },
    "fr": {
        "title": "🔄 Mise à jour des classes Discord",
        "intro": "Mise à jour automatique des classes Discord. À vérifier avant de fusionner.",
        "replaced": "✅ Classes remplacées : **{n}**",
        "to_check": " (dont {n} à vérifier)",
        "missing": "⚠️ Classes introuvables : **{n}** (composant modifié par Discord, à corriger à la main avec les DevTools)",
        "replacements": "Remplacements",
        "inferred": "déduite, à vérifier",
        "missing_title": "Classes introuvables",
        "line": "ligne {n}",
        "same_name": "même nom aujourd'hui : {list}",
        "none": "aucun",
        "data": "Données : Discord Stable build {build} ({date})",
        "warning": "Classes introuvables : {n}",
    },
    "it": {
        "title": "🔄 Aggiornamento delle classi Discord",
        "intro": "Aggiornamento automatico dei nomi delle classi Discord. Da verificare prima del merge.",
        "replaced": "✅ Classi sostituite: **{n}**",
        "to_check": " (di cui {n} da verificare)",
        "missing": "⚠️ Classi non trovate: **{n}** (componente modificato da Discord, da correggere a mano con i DevTools)",
        "replacements": "Sostituzioni",
        "inferred": "dedotta, da verificare",
        "missing_title": "Classi non trovate",
        "line": "riga {n}",
        "same_name": "stesso nome oggi: {list}",
        "none": "nessuno",
        "data": "Dati: Discord Stable build {build} ({date})",
        "warning": "Classi non trovate: {n}",
    },
    "ja": {
        "title": "🔄 Discord クラス名の更新",
        "intro": "Discord のクラス名の自動更新です。マージする前に確認してください。",
        "replaced": "✅ 置き換えたクラス：**{n}**",
        "to_check": "（うち {n} 件は要確認）",
        "missing": "⚠️ 見つからないクラス：**{n}**（Discord によりコンポーネントが変更されました。DevTools で手動で修正してください）",
        "replacements": "置き換え一覧",
        "inferred": "推定、要確認",
        "missing_title": "見つからないクラス",
        "line": "{n} 行目",
        "same_name": "現在同じ名前：{list}",
        "none": "なし",
        "data": "データ：Discord Stable ビルド {build}（{date}）",
        "warning": "見つからないクラス：{n}",
    },
    "ko": {
        "title": "🔄 Discord 클래스 업데이트",
        "intro": "Discord 클래스 이름 자동 업데이트입니다. 병합하기 전에 확인하세요.",
        "replaced": "✅ 교체된 클래스: **{n}**",
        "to_check": " (그중 {n}개는 확인 필요)",
        "missing": "⚠️ 찾을 수 없는 클래스: **{n}** (Discord가 컴포넌트를 변경함, DevTools로 직접 수정하세요)",
        "replacements": "교체 목록",
        "inferred": "추정, 확인 필요",
        "missing_title": "찾을 수 없는 클래스",
        "line": "{n}번째 줄",
        "same_name": "현재 같은 이름: {list}",
        "none": "없음",
        "data": "데이터: Discord Stable 빌드 {build} ({date})",
        "warning": "찾을 수 없는 클래스: {n}",
    },
    "pl": {
        "title": "🔄 Aktualizacja klas Discorda",
        "intro": "Automatyczna aktualizacja nazw klas Discorda. Sprawdź przed scaleniem.",
        "replaced": "✅ Zastąpione klasy: **{n}**",
        "to_check": " (w tym {n} do sprawdzenia)",
        "missing": "⚠️ Nieznalezione klasy: **{n}** (komponent zmieniony przez Discorda, popraw ręcznie w DevTools)",
        "replacements": "Zamiany",
        "inferred": "wywnioskowana, do sprawdzenia",
        "missing_title": "Nieznalezione klasy",
        "line": "wiersz {n}",
        "same_name": "dziś ta sama nazwa: {list}",
        "none": "brak",
        "data": "Dane: Discord Stable, build {build} ({date})",
        "warning": "Nieznalezione klasy: {n}",
    },
    "pt": {
        "title": "🔄 Atualização das classes do Discord",
        "intro": "Atualização automática dos nomes de classes do Discord. Revise antes de fazer o merge.",
        "replaced": "✅ Classes substituídas: **{n}**",
        "to_check": " (das quais {n} a verificar)",
        "missing": "⚠️ Classes não encontradas: **{n}** (componente alterado pelo Discord, corrija manualmente com as DevTools)",
        "replacements": "Substituições",
        "inferred": "deduzida, a verificar",
        "missing_title": "Classes não encontradas",
        "line": "linha {n}",
        "same_name": "mesmo nome hoje: {list}",
        "none": "nenhum",
        "data": "Dados: Discord Stable build {build} ({date})",
        "warning": "Classes não encontradas: {n}",
    },
    "ru": {
        "title": "🔄 Обновление классов Discord",
        "intro": "Автоматическое обновление имён классов Discord. Проверьте перед слиянием.",
        "replaced": "✅ Заменено классов: **{n}**",
        "to_check": " (из них {n} нужно проверить)",
        "missing": "⚠️ Не найдено классов: **{n}** (компонент изменён Discord, исправьте вручную через DevTools)",
        "replacements": "Замены",
        "inferred": "предположение, проверьте",
        "missing_title": "Ненайденные классы",
        "line": "строка {n}",
        "same_name": "сейчас с тем же именем: {list}",
        "none": "нет",
        "data": "Данные: Discord Stable, сборка {build} ({date})",
        "warning": "Не найдено классов: {n}",
    },
    "tr": {
        "title": "🔄 Discord sınıflarının güncellenmesi",
        "intro": "Discord sınıf adlarının otomatik güncellemesi. Birleştirmeden önce kontrol edin.",
        "replaced": "✅ Değiştirilen sınıflar: **{n}**",
        "to_check": " (bunlardan {n} tanesi kontrol edilmeli)",
        "missing": "⚠️ Bulunamayan sınıflar: **{n}** (bileşen Discord tarafından değiştirildi, DevTools ile elle düzeltin)",
        "replacements": "Değişiklikler",
        "inferred": "tahmini, kontrol edin",
        "missing_title": "Bulunamayan sınıflar",
        "line": "satır {n}",
        "same_name": "bugün aynı ada sahip: {list}",
        "none": "yok",
        "data": "Veriler: Discord Stable, sürüm {build} ({date})",
        "warning": "Bulunamayan sınıflar: {n}",
    },
    "uk": {
        "title": "🔄 Оновлення класів Discord",
        "intro": "Автоматичне оновлення імен класів Discord. Перевірте перед злиттям.",
        "replaced": "✅ Замінено класів: **{n}**",
        "to_check": " (з них {n} потрібно перевірити)",
        "missing": "⚠️ Не знайдено класів: **{n}** (компонент змінено Discord, виправте вручну через DevTools)",
        "replacements": "Заміни",
        "inferred": "припущення, перевірте",
        "missing_title": "Не знайдені класи",
        "line": "рядок {n}",
        "same_name": "зараз з тією ж назвою: {list}",
        "none": "немає",
        "data": "Дані: Discord Stable, збірка {build} ({date})",
        "warning": "Не знайдено класів: {n}",
    },
    "zh": {
        "title": "🔄 更新 Discord 类名",
        "intro": "自动更新 Discord 类名。合并前请检查。",
        "replaced": "✅ 已替换的类：**{n}**",
        "to_check": "（其中 {n} 个需要检查）",
        "missing": "⚠️ 未找到的类：**{n}**（Discord 修改了该组件，请用 DevTools 手动修复）",
        "replacements": "替换列表",
        "inferred": "推断结果，请检查",
        "missing_title": "未找到的类",
        "line": "第 {n} 行",
        "same_name": "当前同名：{list}",
        "none": "无",
        "data": "数据：Discord Stable 构建 {build}（{date}）",
        "warning": "未找到的类：{n}",
    },
}


def error(message):
    print(f"::error::{message}")
    sys.exit(1)


def split_list(text):
    """'a.css, b.css' or one entry per line -> ['a.css', 'b.css']"""
    return [s.strip() for s in re.split(r"[,\n]", text or "") if s.strip()]


def split_class(name):
    """'header_S_xUx6' -> ('header', 'S_xUx6')"""
    return name[:-7], name[-6:]


def pick_language(value):
    """'fr', 'FR', 'fr-FR', 'pt_BR'... -> 'fr' / 'pt'. Unknown -> 'en' with a warning."""
    code = (value or "en").strip().lower()[:2]
    if code not in MESSAGES:
        print(f"::warning::Language '{value}' is not supported, using English. Available: {', '.join(MESSAGES)}")
        return "en"
    return code


def load_data(folder):
    live_path = os.path.join(folder, "stable.txt")
    map_path = os.path.join(folder, "map.txt")
    if not os.path.exists(live_path) or not os.path.exists(map_path):
        error(f"Data not found in {folder} (stable.txt and map.txt)")
    with open(live_path, encoding="utf-8") as f:
        live = {l.strip() for l in f if l.strip()}
    if len(live) < 10000:
        error(f"Suspicious list of current classes ({len(live)} classes), stopping to be safe")
    table = collections.defaultdict(list)
    with open(map_path, encoding="utf-8") as f:
        for line in f:
            parts = line.split()
            if len(parts) == 2:
                table[parts[0]].append(parts[1])
    build = {}
    builds_path = os.path.join(folder, "builds.json")
    if os.path.exists(builds_path):
        with open(builds_path, encoding="utf-8") as f:
            build = json.load(f).get("stable", {})
    return live, table, build


def follow(table, name, live):
    """Follow chains a -> b -> c (a class may have several successors)
    and return the closest class that exists today."""
    seen, level = {name}, [name]
    while level:
        following = []
        for c in level:
            for n in table.get(c, ()):
                if n in live:
                    return n
                if n not in seen:
                    seen.add(n)
                    following.append(n)
        level = following
    return None


def sibling_votes(table, live):
    """For each old module hash, which new hashes took its classes."""
    votes = collections.defaultdict(collections.Counter)
    for old in table:
        new = follow(table, old, live)
        if new and split_class(old)[0] == split_class(new)[0]:
            votes[split_class(old)[1]][split_class(new)[1]] += 1
    return votes


def find(name, table, votes, live):
    """Return (new class, inferred?) or (None, False)."""
    new = follow(table, name, live)
    if new:
        return new, False
    # Last resort: the other classes of the same module changed hash,
    # so try the same name with that new hash (it must exist).
    base, h = split_class(name)
    for new_h, _ in votes[h].most_common() if h in votes else []:
        if f"{base}_{new_h}" in live:
            return f"{base}_{new_h}", True
    return None, False


def is_ignored_file(path, ignores):
    path = os.path.normpath(path).replace(os.sep, "/")
    for pattern in ignores:
        pattern = pattern.strip("/").replace("\\", "/")
        if (
            path == pattern
            or os.path.basename(path) == pattern
            or path.startswith(pattern + "/")
            or fnmatch.fnmatch(path, pattern)
        ):
            return True
    return False


def is_ignored_class(name, terms):
    """Ignored if one of the terms appears in the class name, partly or fully,
    case-insensitive ('vencord' ignores 'VencordCard', 'bd-' ignores 'bd-addon-card')."""
    name = name.lower()
    return any(term.lower() in name for term in terms)


def escape_data(text):
    """Escape a GitHub workflow command message."""
    return str(text).replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def escape_property(text):
    """Escape a GitHub workflow command property (file, title...)."""
    return escape_data(text).replace(":", "%3A").replace(",", "%2C")


def output(key, value):
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
            f.write(f"{key}={value}\n")


def main():
    p = argparse.ArgumentParser(description="Update Discord class names in CSS files")
    p.add_argument("--files", default=os.environ.get("INPUT_FILES") or "**/*.css")
    p.add_argument("--ignores", default=os.environ.get("INPUT_IGNORES") or "")
    p.add_argument("--ignore-class-names", default=os.environ.get("INPUT_IGNORE_CLASS_NAMES") or "")
    p.add_argument("--report", default=os.environ.get("INPUT_REPORT") or "")
    p.add_argument("--language", default=os.environ.get("INPUT_LANGUAGE") or "en")
    p.add_argument("--data", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))
    args = p.parse_args()

    t = MESSAGES[pick_language(args.language)]
    report_path = args.report or os.path.join(os.environ.get("RUNNER_TEMP", "."), "discord-classes-report.md")
    ignores = split_list(args.ignores)
    ignored_terms = split_list(args.ignore_class_names)
    files = sorted({f for pattern in split_list(args.files) for f in glob.glob(pattern, recursive=True) if os.path.isfile(f)})
    files = [f for f in files if not is_ignored_file(f, ignores)]

    live, table, build = load_data(args.data)
    votes = sibling_votes(table, live)
    print(f"{len(live)} current Discord classes, {len(files)} files to check")

    report_ok, report_missing = [], []
    nb_ok = nb_missing = nb_inferred = 0
    for path in files:
        with open(path, encoding="utf-8") as f:
            text = f.read()
        replacements, inferred, missing = {}, set(), []
        for name in sorted(set(RE_CLASS.findall(text))):
            if name in live or not RE_DISCORD.search(name) or is_ignored_class(name, ignored_terms):
                continue
            new, guessed = find(name, table, votes, live)
            if new:
                replacements[name] = new
                if guessed:
                    inferred.add(name)
            else:
                missing.append(name)

        if replacements:
            # A single pass, whole class names only: no double replacement
            pattern = re.compile(
                r"(?<![\w-])("
                + "|".join(re.escape(c) for c in sorted(replacements, key=len, reverse=True))
                + r")(?![\w-])"
            )
            text = pattern.sub(lambda m: replacements[m.group(1)], text)
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(text)
            nb_ok += len(replacements)
            nb_inferred += len(inferred)
            report_ok.append(f"\n**{path}**\n")
            report_ok += [
                f"- `{a}` → `{n}`" + (f" *({t['inferred']})*" if a in inferred else "")
                for a, n in replacements.items()
            ]

        if missing:
            # Line of the first occurrence of each class, for the report and the warning link
            lines = {}
            for name in missing:
                m = re.search(r"(?<![\w-])" + re.escape(name) + r"(?![\w-])", text)
                lines[name] = text.count("\n", 0, m.start()) + 1 if m else 1
            missing.sort(key=lambda c: lines[c])

            report_missing.append(f"\n**{path}**\n")
            for name in missing:
                base = split_class(name)[0]
                hints = sorted(c for c in live if split_class(c)[0] == base)
                hint = ", ".join(f"`{c}`" for c in hints[:5]) + (" …" if len(hints) > 5 else "")
                line = t["line"].format(n=lines[name])
                report_missing.append(f"- `{name}` ({line}) — {t['same_name'].format(list=hint or t['none'])}")
                nb_missing += 1

            # One warning per file (GitHub only shows 10 per step), linking to the first missing class
            detail = ", ".join(f"{c} ({t['line'].format(n=lines[c])})" for c in missing)
            title = t["warning"].format(n=len(missing))
            print(
                f"::warning file={escape_property(path)},line={lines[missing[0]]},"
                f"title={escape_property(title)}::{escape_data(detail)}"
            )

    report = [
        t["intro"],
        "",
        "- " + t["replaced"].format(n=nb_ok) + (t["to_check"].format(n=nb_inferred) if nb_inferred else ""),
        "- " + t["missing"].format(n=nb_missing),
    ]
    if report_ok:
        report += ["", f"<details><summary>{t['replacements']}</summary>", *report_ok, "", "</details>"]
    if report_missing:
        report += ["", f"### {t['missing_title']}", *report_missing]
    if build:
        report += ["", "---", t["data"].format(build=build.get("build", "?"), date=build.get("date", "?"))]
    report_text = "\n".join(report) + "\n"

    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_text)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(report_text)

    output("changed", "true" if nb_ok else "false")
    output("replaced", nb_ok)
    output("missing", nb_missing)
    output("report", os.path.abspath(report_path))
    output("title", t["title"])
    print(f"{nb_ok} replaced, {nb_missing} not found, report: {report_path}")


if __name__ == "__main__":
    main()
