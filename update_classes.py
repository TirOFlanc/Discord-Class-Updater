"""Update Discord class names in CSS files.

Data (data/ folder, kept up to date by track_discord.py on the main branch). In the GitHub Action,
the latest data is downloaded from the main branch at each run (data-url), so a pinned version of
the code (@v1) still gets fresh data; the data bundled with the code is only a fallback.
  - stable.txt : every class of Discord Stable today;
  - map.txt    : old name -> new name table, one pair per line.

A class is only replaced if the new one really exists in Discord Stable today.
Classes that can't be found are left untouched and listed in the report.

Locally:
  python3 update_classes.py --files "*.css" --ignores "RefreshTitleBar.css" --ignore-class-names "bd-,vc-" --language en
In a GitHub Action, settings come from
INPUT_FILES / INPUT_IGNORES / INPUT_IGNORE_CLASS_NAMES / INPUT_REPORT / INPUT_LANGUAGE.
There, file names and line numbers in the report are also links to the files on GitHub.
"""

import argparse
import collections
import datetime
import fnmatch
import glob
import html
import json
import os
import re
import sys
import tempfile
import time
import urllib.parse
import urllib.request

DATA_FILES = ("stable.txt", "map.txt", "manual.txt", "builds.json")

# Stands for the branch or commit in the report links until the end, when we know which one to use
LINK_REF = "\0ref\0"

# .className_hash6  (old format: name__1a2b3 / name_1a2b3c, new format: name_aB3-x_)
RE_CLASS = re.compile(r"\.([A-Za-z][\w-]*_[\w-]{6})(?![\w-])")
RE_DISCORD = re.compile(r"(__[0-9a-f]{5}|_[0-9a-f]{6}|_[\w-]*[A-Z0-9_-][\w-]*)$")

# Texts of the pull request and of the run warnings.
# Blocks are sorted by language code. To add a language, copy the "en" block,
# put it in alphabetical order and translate the values ({...} stay as they are).
MESSAGES = {
    "ar": {
        "title": "🔄 تحديث أسماء فئات Discord",
        "intro": "يُرجى المراجعة قبل الدمج!",
        "replaced": "✅ الفئات المستبدلة: **{n}**",
        "to_check": " (منها {n} بحاجة إلى مراجعة)",
        "missing": "⚠️ الفئات غير الموجودة: **{n}**",
        "replacements": "الاستبدالات",
        "inferred": "مُستنتَجة، يُرجى المراجعة",
        "ambiguous": "يُرجى المراجعة، احتمال آخر: {list}",
        "missing_title": "الفئات غير الموجودة",
        "module": "الوحدة الجديدة المحتملة: {list}",
        "none": "لا توجد أدلة",
        "removed": "حذفها Discord",
        "data": "البيانات: Discord Stable، الإصدار {build} ({date})",
        "warning": "الفئات غير الموجودة: {n}",
        "stale": "⚠️ لم تُحدَّث البيانات منذ مدة (عدد الأيام: {n}): قد يكون تتبّع Discord متوقفًا، ولن تُكتشف الفئات التي أُعيدت تسميتها منذ ذلك الحين.",
        "download_failed": "تعذّر تنزيل البيانات المحدّثة، يتم استخدام البيانات المرفقة بهذا الإصدار.",
    },
    "de": {
        "title": "🔄 Aktualisierung der Discord-Klassen",
        "intro": "Vor dem Mergen prüfen!",
        "replaced": "✅ Ersetzte Klassen: **{n}**",
        "to_check": " (davon {n} zu prüfen)",
        "missing": "⚠️ Nicht gefundene Klassen: **{n}**",
        "replacements": "Ersetzungen",
        "inferred": "abgeleitet, bitte prüfen",
        "ambiguous": "bitte prüfen, andere Möglichkeit: {list}",
        "missing_title": "Nicht gefundene Klassen",
        "module": "wahrscheinliches neues Modul: {list}",
        "none": "kein Hinweis",
        "removed": "von Discord entfernt",
        "data": "Daten: Discord Stable Build {build} ({date})",
        "warning": "Nicht gefundene Klassen: {n}",
        "stale": "⚠️ Daten seit {n} Tagen nicht aktualisiert: Die Discord-Überwachung hängt möglicherweise, seitdem umbenannte Klassen werden nicht erkannt.",
        "download_failed": "Aktuelle Daten konnten nicht heruntergeladen werden, es werden die Daten dieser Version verwendet.",
    },
    "en": {
        "title": "🔄 Update Discord class names",
        "intro": "Review before merging!",
        "replaced": "✅ Classes replaced: **{n}**",
        "to_check": " (including {n} to check)",
        "missing": "⚠️ Classes not found: **{n}**",
        "replacements": "Replacements",
        "inferred": "inferred, please check",
        "ambiguous": "please check, other possibility: {list}",
        "missing_title": "Classes not found",
        "module": "probable new module: {list}",
        "none": "no lead",
        "removed": "removed by Discord",
        "data": "Data: Discord Stable build {build} ({date})",
        "warning": "Classes not found: {n}",
        "stale": "⚠️ Data not updated for {n} days: Discord tracking may be stuck, classes renamed since then won't be detected.",
        "download_failed": "Fresh data couldn't be downloaded, using the data bundled with this version.",
    },
    "es": {
        "title": "🔄 Actualización de las clases de Discord",
        "intro": "¡Revisar antes de fusionar!",
        "replaced": "✅ Clases reemplazadas: **{n}**",
        "to_check": " (de las cuales {n} por revisar)",
        "missing": "⚠️ Clases no encontradas: **{n}**",
        "replacements": "Reemplazos",
        "inferred": "deducida, por revisar",
        "ambiguous": "por revisar, otra posibilidad: {list}",
        "missing_title": "Clases no encontradas",
        "module": "nuevo módulo probable: {list}",
        "none": "sin pistas",
        "removed": "eliminada por Discord",
        "data": "Datos: Discord Stable build {build} ({date})",
        "warning": "Clases no encontradas: {n}",
        "stale": "⚠️ Datos sin actualizar desde hace {n} días: el seguimiento de Discord puede estar bloqueado, las clases renombradas desde entonces no se detectarán.",
        "download_failed": "No se pudieron descargar los datos actualizados, se usan los datos incluidos en esta versión.",
    },
    "fr": {
        "title": "🔄 Mise à jour des classes Discord",
        "intro": "À vérifier avant de fusionner !",
        "replaced": "✅ Classes remplacées : **{n}**",
        "to_check": " (dont {n} à vérifier)",
        "missing": "⚠️ Classes introuvables : **{n}**",
        "replacements": "Remplacements",
        "inferred": "déduite, à vérifier",
        "ambiguous": "à vérifier, autre possibilité : {list}",
        "missing_title": "Classes introuvables",
        "module": "nouveau module probable : {list}",
        "none": "aucune piste",
        "removed": "supprimée par Discord",
        "data": "Données : Discord Stable build {build} ({date})",
        "warning": "Classes introuvables : {n}",
        "stale": "⚠️ Données non mises à jour depuis {n} jours : le suivi de Discord est peut-être bloqué, les classes renommées depuis ne seront pas détectées.",
        "download_failed": "Impossible de télécharger les données à jour, utilisation des données livrées avec cette version.",
    },
    "it": {
        "title": "🔄 Aggiornamento delle classi Discord",
        "intro": "Da verificare prima del merge!",
        "replaced": "✅ Classi sostituite: **{n}**",
        "to_check": " (di cui {n} da verificare)",
        "missing": "⚠️ Classi non trovate: **{n}**",
        "replacements": "Sostituzioni",
        "inferred": "dedotta, da verificare",
        "ambiguous": "da verificare, altra possibilità: {list}",
        "missing_title": "Classi non trovate",
        "module": "probabile nuovo modulo: {list}",
        "none": "nessuna pista",
        "removed": "rimossa da Discord",
        "data": "Dati: Discord Stable build {build} ({date})",
        "warning": "Classi non trovate: {n}",
        "stale": "⚠️ Dati non aggiornati da {n} giorni: il monitoraggio di Discord potrebbe essere bloccato, le classi rinominate da allora non verranno rilevate.",
        "download_failed": "Impossibile scaricare i dati aggiornati, uso dei dati inclusi in questa versione.",
    },
    "ja": {
        "title": "🔄 Discord クラス名の更新",
        "intro": "マージする前に確認してください！",
        "replaced": "✅ 置き換えたクラス：**{n}**",
        "to_check": "（うち {n} 件は要確認）",
        "missing": "⚠️ 見つからないクラス：**{n}**",
        "replacements": "置き換え一覧",
        "inferred": "推定、要確認",
        "ambiguous": "要確認、別の候補：{list}",
        "missing_title": "見つからないクラス",
        "module": "新しいモジュールの候補：{list}",
        "none": "手がかりなし",
        "removed": "Discord により削除",
        "data": "データ：Discord Stable ビルド {build}（{date}）",
        "warning": "見つからないクラス：{n}",
        "stale": "⚠️ データが {n} 日間更新されていません。Discord の追跡が止まっている可能性があり、それ以降に名前が変わったクラスは検出されません。",
        "download_failed": "最新データをダウンロードできなかったため、このバージョンに含まれるデータを使用します。",
    },
    "ko": {
        "title": "🔄 Discord 클래스 업데이트",
        "intro": "병합하기 전에 확인하세요!",
        "replaced": "✅ 교체된 클래스: **{n}**",
        "to_check": " (그중 {n}개는 확인 필요)",
        "missing": "⚠️ 찾을 수 없는 클래스: **{n}**",
        "replacements": "교체 목록",
        "inferred": "추정, 확인 필요",
        "ambiguous": "확인 필요, 다른 후보: {list}",
        "missing_title": "찾을 수 없는 클래스",
        "module": "새 모듈 후보: {list}",
        "none": "단서 없음",
        "removed": "Discord에서 삭제됨",
        "data": "데이터: Discord Stable 빌드 {build} ({date})",
        "warning": "찾을 수 없는 클래스: {n}",
        "stale": "⚠️ 데이터가 {n}일 동안 업데이트되지 않았습니다. Discord 추적이 멈췄을 수 있으며, 그 이후 이름이 바뀐 클래스는 감지되지 않습니다.",
        "download_failed": "최신 데이터를 다운로드할 수 없어 이 버전에 포함된 데이터를 사용합니다.",
    },
    "pl": {
        "title": "🔄 Aktualizacja klas Discorda",
        "intro": "Sprawdź przed scaleniem!",
        "replaced": "✅ Zastąpione klasy: **{n}**",
        "to_check": " (w tym {n} do sprawdzenia)",
        "missing": "⚠️ Nieznalezione klasy: **{n}**",
        "replacements": "Zamiany",
        "inferred": "wywnioskowana, do sprawdzenia",
        "ambiguous": "do sprawdzenia, inna możliwość: {list}",
        "missing_title": "Nieznalezione klasy",
        "module": "prawdopodobny nowy moduł: {list}",
        "none": "brak wskazówek",
        "removed": "usunięta przez Discorda",
        "data": "Dane: Discord Stable, build {build} ({date})",
        "warning": "Nieznalezione klasy: {n}",
        "stale": "⚠️ Dane nieaktualizowane od {n} dni: śledzenie Discorda może być zablokowane, klasy zmienione od tego czasu nie zostaną wykryte.",
        "download_failed": "Nie udało się pobrać aktualnych danych, używane są dane dołączone do tej wersji.",
    },
    "pt": {
        "title": "🔄 Atualização das classes do Discord",
        "intro": "Revise antes de fazer o merge!",
        "replaced": "✅ Classes substituídas: **{n}**",
        "to_check": " (das quais {n} a verificar)",
        "missing": "⚠️ Classes não encontradas: **{n}**",
        "replacements": "Substituições",
        "inferred": "deduzida, a verificar",
        "ambiguous": "a verificar, outra possibilidade: {list}",
        "missing_title": "Classes não encontradas",
        "module": "provável novo módulo: {list}",
        "none": "nenhuma pista",
        "removed": "removida pelo Discord",
        "data": "Dados: Discord Stable build {build} ({date})",
        "warning": "Classes não encontradas: {n}",
        "stale": "⚠️ Dados não atualizados há {n} dias: o monitoramento do Discord pode estar travado, as classes renomeadas desde então não serão detectadas.",
        "download_failed": "Não foi possível baixar os dados atualizados, usando os dados incluídos nesta versão.",
    },
    "ru": {
        "title": "🔄 Обновление классов Discord",
        "intro": "Проверьте перед слиянием!",
        "replaced": "✅ Заменено классов: **{n}**",
        "to_check": " (из них {n} нужно проверить)",
        "missing": "⚠️ Не найдено классов: **{n}**",
        "replacements": "Замены",
        "inferred": "предположение, проверьте",
        "ambiguous": "проверьте, другой вариант: {list}",
        "missing_title": "Ненайденные классы",
        "module": "вероятный новый модуль: {list}",
        "none": "нет подсказок",
        "removed": "удалён Discord",
        "data": "Данные: Discord Stable, сборка {build} ({date})",
        "warning": "Не найдено классов: {n}",
        "stale": "⚠️ Данные не обновлялись {n} дн.: отслеживание Discord, возможно, остановилось, переименованные с тех пор классы не будут обнаружены.",
        "download_failed": "Не удалось загрузить актуальные данные, используются данные, поставляемые с этой версией.",
    },
    "tr": {
        "title": "🔄 Discord sınıflarının güncellenmesi",
        "intro": "Birleştirmeden önce kontrol edin!",
        "replaced": "✅ Değiştirilen sınıflar: **{n}**",
        "to_check": " (bunlardan {n} tanesi kontrol edilmeli)",
        "missing": "⚠️ Bulunamayan sınıflar: **{n}**",
        "replacements": "Değişiklikler",
        "inferred": "tahmini, kontrol edin",
        "ambiguous": "kontrol edin, diğer olasılık: {list}",
        "missing_title": "Bulunamayan sınıflar",
        "module": "olası yeni modül: {list}",
        "none": "ipucu yok",
        "removed": "Discord tarafından kaldırıldı",
        "data": "Veriler: Discord Stable, sürüm {build} ({date})",
        "warning": "Bulunamayan sınıflar: {n}",
        "stale": "⚠️ Veriler {n} gündür güncellenmedi: Discord takibi takılmış olabilir, o zamandan beri yeniden adlandırılan sınıflar algılanmayacak.",
        "download_failed": "Güncel veriler indirilemedi, bu sürümle gelen veriler kullanılıyor.",
    },
    "uk": {
        "title": "🔄 Оновлення класів Discord",
        "intro": "Перевірте перед злиттям!",
        "replaced": "✅ Замінено класів: **{n}**",
        "to_check": " (з них {n} потрібно перевірити)",
        "missing": "⚠️ Не знайдено класів: **{n}**",
        "replacements": "Заміни",
        "inferred": "припущення, перевірте",
        "ambiguous": "перевірте, інший варіант: {list}",
        "missing_title": "Не знайдені класи",
        "module": "ймовірний новий модуль: {list}",
        "none": "немає підказок",
        "removed": "видалено Discord",
        "data": "Дані: Discord Stable, збірка {build} ({date})",
        "warning": "Не знайдено класів: {n}",
        "stale": "⚠️ Дані не оновлювалися {n} дн.: відстеження Discord, можливо, зупинилося, перейменовані відтоді класи не буде виявлено.",
        "download_failed": "Не вдалося завантажити актуальні дані, використовуються дані, що постачаються з цією версією.",
    },
    "zh": {
        "title": "🔄 更新 Discord 类名",
        "intro": "合并前请检查！",
        "replaced": "✅ 已替换的类：**{n}**",
        "to_check": "（其中 {n} 个需要检查）",
        "missing": "⚠️ 未找到的类：**{n}**",
        "replacements": "替换列表",
        "inferred": "推断结果，请检查",
        "ambiguous": "请检查，其他可能：{list}",
        "missing_title": "未找到的类",
        "module": "可能的新模块：{list}",
        "none": "无线索",
        "removed": "已被 Discord 删除",
        "data": "数据：Discord Stable 构建 {build}（{date}）",
        "warning": "未找到的类：{n}",
        "stale": "⚠️ 数据已 {n} 天未更新：Discord 跟踪可能已停止，此后重命名的类将不会被检测到。",
        "download_failed": "无法下载最新数据，改用此版本自带的数据。",
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
    # Changes confirmed by hand: used before the automatic table
    removed, manual = set(), {}
    manual_path = os.path.join(folder, "manual.txt")
    if os.path.exists(manual_path):
        with open(manual_path, encoding="utf-8") as f:
            for line in f:
                parts = line.split()
                if len(parts) != 2 or parts[0].startswith("#"):
                    continue
                if parts[1] == "-":
                    removed.add(parts[0])
                else:
                    manual[parts[0]] = parts[1]
                    table[parts[0]].insert(0, parts[1])
    builds = {}
    builds_path = os.path.join(folder, "builds.json")
    if os.path.exists(builds_path):
        with open(builds_path, encoding="utf-8") as f:
            builds = json.load(f)
    return live, table, manual, removed, builds


def fetch_data(url):
    """Download the latest data files into a temporary folder. Return the folder, or None on failure."""
    folder = tempfile.mkdtemp(prefix="discord-class-updater-", dir=os.environ.get("RUNNER_TEMP") or None)
    try:
        for name in DATA_FILES:
            for attempt in range(3):
                try:
                    req = urllib.request.Request(f"{url.rstrip('/')}/{name}", headers={"User-Agent": "discord-class-updater"})
                    with urllib.request.urlopen(req, timeout=60) as r:
                        content = r.read()
                    break
                except Exception:
                    if attempt == 2:
                        raise
                    time.sleep(2 * (attempt + 1))
            with open(os.path.join(folder, name), "wb") as f:
                f.write(content)
        with open(os.path.join(folder, "stable.txt"), encoding="utf-8") as f:
            if sum(1 for l in f if l.strip()) < 10000:
                return None
        json.load(open(os.path.join(folder, "builds.json"), encoding="utf-8"))
        return folder
    except Exception:
        return None


def data_age(builds):
    """Days since tracking last worked (last_check, or else the most recent build), or None."""
    dates = [builds.get("last_check")] if builds.get("last_check") else [
        v.get("date") for v in builds.values() if isinstance(v, dict) and v.get("date")
    ]
    parsed = []
    for d in dates:
        try:
            parsed.append(datetime.datetime.strptime(d, "%Y-%m-%d %H:%M UTC").replace(tzinfo=datetime.timezone.utc))
        except (TypeError, ValueError):
            pass
    if not parsed:
        return None
    return (datetime.datetime.now(datetime.timezone.utc) - max(parsed)).days


def follow_all(table, name, live):
    """Follow chains a -> b -> c (a class may have several successors) and return
    every class that exists today at the closest step (usually just one)."""
    seen, level = {name}, [name]
    while level:
        found, following = [], []
        for c in level:
            for n in table.get(c, ()):
                if n in live and n not in found:
                    found.append(n)
                if n not in seen:
                    seen.add(n)
                    following.append(n)
        if found:
            return found
        level = following
    return []


def follow(table, name, live):
    found = follow_all(table, name, live)
    return found[0] if found else None


def sibling_votes(table, live):
    """For each old module hash, which new hashes took its classes."""
    votes = collections.defaultdict(collections.Counter)
    for old in table:
        new = follow(table, old, live)
        if new and split_class(old)[0] == split_class(new)[0]:
            votes[split_class(old)[1]][split_class(new)[1]] += 1
    return votes


def find(name, table, manual, votes, live):
    """Return (candidates, source): one candidate when sure, several when ambiguous,
    none when not found. source says where it comes from: "manual" (manual.txt),
    "table" (automatic tracking), "inferred" (guessed from its module) or None."""
    if name in manual:  # confirmed by hand: no ambiguity
        target = manual[name]
        found = [target] if target in live else follow_all(table, target, live)[:1]
        if found:
            return found, "manual"
    found = follow_all(table, name, live)
    if found:
        return found, "table"
    # Last resort: the other classes of the same module changed hash,
    # so try the same name with that new hash (it must exist).
    base, h = split_class(name)
    for new_h, _ in votes[h].most_common() if h in votes else []:
        if f"{base}_{new_h}" in live:
            return [f"{base}_{new_h}"], "inferred"
    return [], None


class ModuleFinder:
    """Finds the current CSS module that looks most like the old module of a missing class
    (same class names), to point to where the class probably went."""

    def __init__(self, table, live):
        self.old_names = collections.defaultdict(set)
        for old, news in table.items():
            for c in [old, *news]:
                if len(c) > 7:
                    self.old_names[split_class(c)[1]].add(split_class(c)[0])
        self.modules = collections.defaultdict(set)
        for c in live:
            self.modules[split_class(c)[1]].add(split_class(c)[0])
        self.index = collections.defaultdict(set)
        for h, names in self.modules.items():
            for n in names:
                self.index[n].add(h)

    def similarity(self, old, candidate):
        """How much the candidate's current module looks like the old module (0 to 1)."""
        a = self.old_names.get(split_class(old)[1], set())
        b = self.modules.get(split_class(candidate)[1], set())
        return len(a & b) / len(a | b) if a | b else 0.0

    def hint(self, name, threshold=0.25, shown=8):
        names = self.old_names.get(split_class(name)[1], set())
        common = collections.Counter(h for n in names for h in self.index.get(n, ()))
        best = max(
            ((n / (len(names) + len(self.modules[h]) - n), n, h) for h, n in common.items()),
            default=None,
        )
        if not best or best[0] < threshold or best[1] < 2:
            return None
        members = sorted(self.modules[best[2]])
        return f"`_{best[2]}` (" + ", ".join(members[:shown]) + (", …" if len(members) > shown else "") + ")"


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


def file_url(path, ref):
    """Address of a file of the repository on GitHub, or None outside GitHub Actions.
    'themes/my theme.css', 'updates' -> 'https://github.com/owner/repo/blob/updates/themes/my%20theme.css'"""
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not repo:
        return None
    root = os.environ.get("GITHUB_WORKSPACE") or os.getcwd()
    try:
        relative = os.path.relpath(os.path.abspath(path), os.path.abspath(root)).replace(os.sep, "/")
    except ValueError:  # another drive (Windows)
        return None
    if relative.startswith("../"):
        return None
    server = (os.environ.get("GITHUB_SERVER_URL") or "https://github.com").rstrip("/")
    return f"{server}/{repo}/blob/{ref}/{urllib.parse.quote(relative)}"


def linked(text, url):
    """HTML link, or the plain text when there is no address.
    Not a Markdown link: Discord removes HTML tags before cutting a pull request to 500 characters,
    so the addresses don't use up that space and are never cut in the middle (the text stays, without link).
    GitHub shows it as a normal link."""
    text = html.escape(text, quote=False)
    return f'<a href="{url}">{text}</a>' if url else text


def first_line(text, name):
    """Line number of the first occurrence of a whole class name in a file (1 if not found)."""
    m = re.search(r"(?<![\w-])" + re.escape(name) + r"(?![\w-])", text)
    return text.count("\n", 0, m.start()) + 1 if m else 1


def manual_url(data_url):
    """Page of manual.txt on GitHub, found from the address the data is downloaded from, or None.
    'https://raw.githubusercontent.com/owner/repo/main/data' -> 'https://github.com/owner/repo/blob/main/data/manual.txt'"""
    m = re.match(r"https://raw\.githubusercontent\.com/([^/]+)/([^/]+)/(.+?)/*$", data_url or "")
    return f"https://github.com/{m[1]}/{m[2]}/blob/{m[3]}/manual.txt" if m else None


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
    p.add_argument("--max-data-age", type=int, default=int(os.environ.get("INPUT_MAX_DATA_AGE") or 3))
    p.add_argument("--data", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))
    p.add_argument("--data-url", default=os.environ.get("INPUT_DATA_URL") or "")
    # Branch of the pull request: the report links point to it when classes were replaced,
    # otherwise to the current commit (GITHUB_SHA)
    p.add_argument("--link-branch", default=os.environ.get("INPUT_LINK_BRANCH") or "")
    args = p.parse_args()

    t = MESSAGES[pick_language(args.language)]
    report_path = args.report or os.path.join(os.environ.get("RUNNER_TEMP", "."), "discord-classes-report.md")
    ignores = split_list(args.ignores)
    ignored_terms = split_list(args.ignore_class_names)
    files = sorted({f for pattern in split_list(args.files) for f in glob.glob(pattern, recursive=True) if os.path.isfile(f)})
    files = [f for f in files if not is_ignored_file(f, ignores)]

    data = args.data
    if args.data_url:
        fresh = fetch_data(args.data_url)
        if fresh:
            data = fresh
            print(f"Data downloaded from {args.data_url}")
        else:
            print(f"::warning title=Discord Class Updater::{escape_data(t['download_failed'])}")
    live, table, manual, removed, builds = load_data(data)
    build = builds.get("stable", {})
    age = data_age(builds)
    stale = age is not None and age > args.max_data_age
    if stale:
        print(f"::warning title=Discord Class Updater::{escape_data(t['stale'].format(n=age))}")
    votes = sibling_votes(table, live)
    modules = ModuleFinder(table, live)
    # Note of the replacements from manual.txt: a file name, the same in every language, linked to the file
    manual_link = linked("manual.txt", manual_url(args.data_url))
    print(f"{len(live)} current Discord classes, {len(files)} files to check")

    report_ok, report_missing = [], []
    nb_ok = nb_missing = nb_inferred = 0
    for path in files:
        with open(path, encoding="utf-8") as f:
            text = f.read()
        replacements, inferred, by_hand, missing, ambiguous, others = {}, set(), set(), [], {}, {}
        url = file_url(path, LINK_REF)
        names = sorted(set(RE_CLASS.findall(text)))
        for name in names:
            if name in live or not RE_DISCORD.search(name) or is_ignored_class(name, ignored_terms):
                continue
            found, source = ([], None) if name in removed else find(name, table, manual, votes, live)
            if len(found) == 1:
                replacements[name] = found[0]
                if source == "inferred":
                    inferred.add(name)
                elif source == "manual":
                    by_hand.add(name)
            elif found:
                ambiguous[name] = found
            else:
                missing.append(name)

        # Several current classes possible (Discord split a module): pick the one whose module
        # the file already uses the most, then the one whose module looks most like the old one.
        if ambiguous:
            context = collections.Counter(
                split_class(c)[1] for c in [*names, *replacements.values()] if c in live
            )
            for name, found in ambiguous.items():
                best = max(found, key=lambda c: (context[split_class(c)[1]], modules.similarity(name, c)))
                replacements[name] = best
                others[name] = [c for c in found if c != best]

        if replacements:
            # A single pass, whole class names only: no double replacement
            pattern = re.compile(
                r"(?<![\w-])("
                + "|".join(re.escape(c) for c in sorted(replacements, key=len, reverse=True))
                + r")(?![\w-])"
            )
            where = {a: first_line(text, a) for a in replacements}  # before replacing
            text = pattern.sub(lambda m: replacements[m.group(1)], text)
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(text)
            nb_ok += len(replacements)
            nb_inferred += len(inferred) + len(others)
            report_ok.append(f"\n**{linked(path, url)}**\n")
            for a in sorted(replacements, key=lambda c: (where[c], c)):
                # (L52), then where it comes from or what to check: (L52 — manual.txt)
                notes = [linked(f"L{where[a]}", url and f"{url}#L{where[a]}")]
                if a in inferred:
                    notes.append(t["inferred"])
                if a in by_hand:
                    notes.append(manual_link)
                if a in others:
                    notes.append(t["ambiguous"].format(list=", ".join(f"`{c}`" for c in others[a])))
                report_ok.append(f"- `{a}` → `{replacements[a]}` ({' — '.join(notes)})")

        if missing:
            # Line of the first occurrence of each class, for the report and the warning link
            lines = {name: first_line(text, name) for name in missing}
            missing.sort(key=lambda c: lines[c])

            report_missing.append(f"\n**{linked(path, url)}**\n")
            for name in missing:
                # "L99", like GitHub writes it (#L99): the same in every language, and short
                line = linked(f"L{lines[name]}", url and f"{url}#L{lines[name]}")
                if name in removed:
                    note = t["removed"]
                else:
                    hint = modules.hint(name)
                    note = t["module"].format(list=hint) if hint else t["none"]
                report_missing.append(f"- `{name}` ({line}) — {note}")
                nb_missing += 1

            # One warning per file (GitHub only shows 10 per step), linking to the first missing class
            detail = ", ".join(f"{c} (L{lines[c]})" for c in missing)
            title = t["warning"].format(n=len(missing))
            print(
                f"::warning file={escape_property(path)},line={lines[missing[0]]},"
                f"title={escape_property(title)}::{escape_data(detail)}"
            )

    # Kept short, classes to fix by hand first: Discord only shows the first 500 characters
    # of a pull request. The replacements come last, folded.
    report = [
        "# " + t["intro"],
        *(["", "> " + t["stale"].format(n=age)] if stale else []),
        "",
        "- " + t["replaced"].format(n=nb_ok) + (t["to_check"].format(n=nb_inferred) if nb_inferred else ""),
        "- " + t["missing"].format(n=nb_missing),
    ]
    if report_missing:
        report += ["", f"### {t['missing_title']}", *report_missing]
    if report_ok:
        # No empty line before </details>: Discord removes the tag but keeps its line, which makes a gap
        report += ["", f"<details><summary><b>{t['replacements']}</b></summary>", *report_ok, "</details>"]
    if build:
        # HTML line, right after </details>: a single empty line in Discord, and no "---" shown as text
        footer = "<hr>" + html.escape(t["data"].format(build=build.get("build", "?"), date=build.get("date", "?")),
                                      quote=False)
        report += [footer] if report_ok else ["", footer]
    report_text = "\n".join(report) + "\n"

    # Links: to the pull request branch when one is opened, so they show the updated files,
    # otherwise to the commit that was checked (same line numbers, since only class names change)
    commit = os.environ.get("GITHUB_SHA", "")
    ref = args.link_branch if args.link_branch and (nb_ok or not commit) else commit
    if LINK_REF in report_text:
        if ref:
            report_text = report_text.replace(LINK_REF, urllib.parse.quote(ref))
        else:  # nowhere to point to: plain text
            report_text = re.sub(r'<a href="[^"]*' + LINK_REF + r'[^"]*">([^<]*)</a>', r"\1", report_text)

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
    output("stale", "true" if stale else "false")
    print(f"{nb_ok} replaced, {nb_missing} not found, report: {report_path}")


if __name__ == "__main__":
    main()
