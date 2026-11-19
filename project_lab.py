# project_lab.py
# =============================================================================
# project_lab.py  —  «Лаборатория проекта»
# -----------------------------------------------------------------------------
# Пошаговый конструктор проекта через промпты для внешней LLM + реальные
# действия на диске (структура, .venv, зависимости, git, экспорт отчёта).
#
# ЗАПУСК:      python project_lab.py
# ТРЕБОВАНИЯ:  Python 3.8+, только стандартная библиотека (tkinter входит в
#              стандартную поставку python; на Debian/Ubuntu — python3-tk).
#
# КАРТА ФАЙЛА (секции идут по порядку, сверху вниз):
#   1. Константы: палитры, лимиты, имена папок/файлов, список этапов.
#   2. Утилиты: время, текст, пути, буфер обмена, лог, защита кнопок.
#   3. AppState — модель состояния проекта (то, что уезжает в state.json).
#   4. Пресеты тем и описания полей этапов.
#   5. PromptBuilder — сборка промптов и мастер-промпта.
#   6. CommandRunner + Scaffolder — реальные действия на диске.
#   7. HistoryManager — снапшоты и обратимые откаты.
#   8. Exporter — prompts/, artifacts/, report.html, pipeline.svg.
#   9. Виджеты, лог-консоль, фоновые задачи, вкладка «Старт».
#  10. Вкладки этапов, «Итог», «История», класс App и точка входа.
#
# ПРАВИЛА, ЗАЛОЖЕННЫЕ В КОД:
#   - файлы пользователя никогда не перезаписываются молча (только через диалог);
#   - внешние команды — списком аргументов, без shell, с capture_output;
#   - отсутствие git/pip/прав — понятное сообщение в лог, а не падение;
#   - все цвета — в одном месте (PALETTE_DARK / PALETTE_LIGHT).
#
# ЧТО ИСПРАВЛЕНО В ВЕРСИИ 1.1.0:
#   - выбор папки больше не затирает чужой state.json (три варианта + бэкап);
#   - «Вставить из буфера» не стирает результат при пустом буфере;
#   - откат/undo/redo не уводят рабочую папку в путь из снапшота;
#   - App.update переименован в refresh_ui (не перекрываем tk.Tk.update);
#   - ScrollFrame: одно окно на канвасе + прокрутка колесом мыши;
#   - галочки инструментов не дублируются в поля этапа (flag_*);
#   - статус этапа красится по смыслу, а не всегда красным;
#   - тема восстанавливается из state.json, красятся меню и новые виджеты;
#   - смена темы: «пресеты изменены» определяется по факту правок;
#   - автосохранение сообщает об ошибке, а не глотает её;
#   - «применить ко всем» в диалоге конфликтов сбрасывается на каждый запуск;
#   - черновик в artifacts подписан честно (черновик ≠ утверждённый);
#   - .gitignore проверяется построчно, картинки — только внутри images/.
# =============================================================================
import base64          # картинки внутри report.html (отчёт одним файлом)
import copy            # глубокие копии состояния для снапшотов
import difflib         # текстовое сравнение снапшотов на вкладке «История»
import functools       # декоратор safe_action
import html            # экранирование текста в HTML-отчёте
import json            # state.json и снапшоты
import os
import platform        # имя ОС для отчёта и подсказок по установке инструментов
import queue           # потокобезопасная передача строк лога в интерфейс
import re              # чистка имён файлов
import shlex           # красивая печать команды в логе (POSIX)
import shutil          # копирование картинок, поиск инструментов в PATH
import subprocess      # все внешние команды
import sys
import threading       # долгие команды (venv, pip) вне UI-потока
import traceback       # понятные сообщения об ошибках
from datetime import datetime

# tkinter может отсутствовать в минимальных сборках python. Не падаем с
# трассировкой: печатаем человеческую инструкцию и выходим с кодом 1.
try:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    from tkinter import font as tkfont
except ImportError:
    sys.stderr.write(
        "Не найден tkinter — графическая часть стандартной библиотеки.\n"
        "Windows/macOS: переустановите python с python.org (tkinter входит в комплект).\n"
        "Debian/Ubuntu: sudo apt install python3-tk\n"
        "Fedora:        sudo dnf install python3-tkinter\n"
    )
    raise SystemExit(1)

# =============================================================================
# СЕКЦИЯ 1. КОНСТАНТЫ
# =============================================================================
APP_NAME = "Лаборатория проекта"
APP_VERSION = "1.1.0"
SCHEMA_VERSION = 1          # версия формата state.json (для будущих миграций)

# --- Палитры -----------------------------------------------------------------
# Все цвета приложения живут ТОЛЬКО здесь. Чтобы поменять оформление —
# правьте значения ниже, остальной код берёт цвета из словаря C.
PALETTE_DARK = {
    "bg":         "#1e1e1e",   # фон окна
    "panel":      "#252526",   # фон вкладок и панелей
    "panel2":     "#2d2d30",   # фон шапок/групп, чуть светлее
    "fg":         "#d4d4d4",   # основной текст
    "muted":      "#9a9a9a",   # подсказки, второстепенный текст
    "border":     "#3c3c3c",   # рамки
    "input":      "#1b1b1c",   # фон полей ввода и лога
    "input_fg":   "#e6e6e6",   # текст в полях ввода
    "sel_bg":     "#264f78",   # выделение текста
    "sel_fg":     "#ffffff",
    "accent":     "#0e639c",   # основные кнопки
    "accent_hi":  "#1177bb",   # кнопка под курсором
    "accent_fg":  "#ffffff",
    "ok":         "#4ec9b0",   # успех
    "warn":       "#d7ba7d",   # предупреждение
    "err":        "#f14c4c",   # ошибка
    "approved":   "#2ea043",   # утверждённый этап
    "draft":      "#d7ba7d",   # черновик
    "empty":      "#6a6a6a",   # пустой этап
    "log_cmd":    "#569cd6",   # строка команды в логе
    "log_ok":     "#4ec9b0",
    "log_err":    "#f14c4c",
    "log_warn":   "#d7ba7d",
    "log_info":   "#d4d4d4",
    "log_raw":    "#9a9a9a",   # сырой вывод программы
}

PALETTE_LIGHT = {
    "bg":         "#f3f3f3",
    "panel":      "#ffffff",
    "panel2":     "#eaeaea",
    "fg":         "#1f1f1f",
    "muted":      "#6a6a6a",
    "border":     "#c8c8c8",
    "input":      "#ffffff",
    "input_fg":   "#1f1f1f",
    "sel_bg":     "#add6ff",
    "sel_fg":     "#000000",
    "accent":     "#0e639c",
    "accent_hi":  "#1177bb",
    "accent_fg":  "#ffffff",
    "ok":         "#107c10",
    "warn":       "#9a6700",
    "err":        "#c42b1c",
    "approved":   "#107c10",
    "draft":      "#9a6700",
    "empty":      "#9a9a9a",
    "log_cmd":    "#0451a5",
    "log_ok":     "#107c10",
    "log_err":    "#c42b1c",
    "log_warn":   "#9a6700",
    "log_info":   "#1f1f1f",
    "log_raw":    "#5a5a5a",
}

# C — «текущая палитра». Меняется целиком при переключении темы, поэтому
# виджеты всегда читают C["..."], а не запоминают цвет навсегда.
C = dict(PALETTE_DARK)


def set_palette(mode):
    """Переключает активную палитру (dark/light) прямо в словаре C."""
    C.clear()
    C.update(PALETTE_LIGHT if mode == "light" else PALETTE_DARK)
    return "light" if mode == "light" else "dark"


# --- Лимиты и таймауты -------------------------------------------------------
LIMITS = {
    "snapshot_keep":  100,    # сколько снапшотов храним в history/
    "context_chars":  6000,   # максимум символов на один этап в контексте промпта
    "context_min":    500,    # нижняя граница настройки лимита
    "context_max":    200000, # верхняя граница настройки лимита
    "log_lines":      5000,   # кольцевой буфер лога в памяти
    "autosave_ms":    1500,   # задержка автосохранения после правки
    "timeout_cmd":    60,     # сек, обычные команды (git, --version)
    "timeout_venv":   300,    # сек, создание .venv
    "timeout_pip":    900,    # сек, установка зависимостей
    "image_max_mb":   15,     # большие картинки не встраиваем в HTML (только ссылкой)
}

# Шрифт подбираем в UI-секции по наличию в системе; здесь только кандидаты.
FONT_MONO_CANDIDATES = ("Consolas", "Menlo", "DejaVu Sans Mono", "Courier New")
FONT_MONO_SIZE = 10

# --- Этапы -------------------------------------------------------------------
# (id, номер, заголовок вкладки, короткое пояснение)
STAGES = [
    ("idea",     1, "Идея",        "Что за проект и для кого"),
    ("charter",  2, "Паспорт",     "Цель, границы, критерии готовности"),
    ("arch",     3, "Архитектура", "Модули, потоки данных, контракты"),
    ("skeleton", 4, "Скелет",      "Дерево файлов и заготовки"),
    ("feature",  5, "Фича",        "Первая полезная функция"),
    ("debug",    6, "Отладка",     "Ошибка, причина, фикс, регресс-тест"),
    ("summary",  7, "Итог",        "Мастер-промпт и экспорт"),
]
STAGE_IDS = [s[0] for s in STAGES]
WORK_STAGE_IDS = [s[0] for s in STAGES if s[0] != "summary"]   # 6 рабочих этапов
STAGE_TITLES = {s[0]: s[2] for s in STAGES}
STAGE_NUM = {s[0]: s[1] for s in STAGES}

# Имена файлов промптов и артефактов — фиксированы, чтобы экспорт был предсказуем.
PROMPT_FILENAMES = {
    "summary":  "00_master_prompt.txt",
    "idea":     "01_idea.txt",
    "charter":  "02_charter.txt",
    "arch":     "03_architecture.txt",
    "skeleton": "04_skeleton.txt",
    "feature":  "05_feature.txt",
    "debug":    "06_debug.txt",
}
ARTIFACT_FILENAMES = {
    "idea":     "01_idea_result.md",
    "charter":  "02_charter_result.md",
    "arch":     "03_architecture_result.md",
    "skeleton": "04_skeleton_result.md",
    "feature":  "05_feature_result.md",
    "debug":    "06_debug_result.md",
}

# --- Файловая структура проекта ---------------------------------------------
BASE_DIRS = ["src", "tests", "features", "docs", "data", "out",
             "scripts", "prompts", "artifacts", "images", "history"]

# Файлы пользователя: создаём один раз, перезапись — только через диалог.
USER_FILES = ["README.md", "AGENTS.md", "CLAUDE.md", "PROJECT_CHARTER.md",
              "requirements.txt", ".gitignore", ".env.example", "pytest.ini"]

# Файлы самого приложения: перезаписываются свободно, но с записью в лог.
APP_FILES = {"state.json", "report.html", "pipeline.svg"}

STATE_FILE = "state.json"
REPORT_FILE = "report.html"
SVG_FILE = "pipeline.svg"

# .gitignore по ТЗ (+ два очевидных дополнения, помечены комментарием).
GITIGNORE_TEXT = """# --- окружение и кэш ---
.venv/
__pycache__/
*.pyc
.pytest_cache/

# --- данные и результаты (не храним в git) ---
out/
data/

# --- секреты ---
*.env
.env
"""

# =============================================================================
# СЕКЦИЯ 2. УТИЛИТЫ
# =============================================================================


def now_stamp():
    """Метка времени для имён файлов снапшотов: 20261119_142530."""
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def now_human():
    """Читаемая метка времени для состояния, лога и отчёта."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def platform_name():
    """Человеческое имя ОС — попадает в промпт и в отчёт об окружении."""
    s = platform.system()
    return {"Windows": "Windows", "Darwin": "macOS", "Linux": "Linux"}.get(s, s or "неизвестно")


def is_windows():
    """Единая точка проверки платформы (пути к .venv зависят от неё)."""
    return os.name == "nt"


def ensure_dir(path):
    """Создаёт папку (и родителей), если её нет. Пустой путь игнорирует."""
    if path and not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)
    return path


def atomic_write(path, text):
    """Пишет файл атомарно: сначала .tmp, потом os.replace.
    Зачем: при сбое питания/прав не останется наполовину записанный state.json."""
    ensure_dir(os.path.dirname(os.path.abspath(path)))
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def read_text(path, default=""):
    """Читает текст в UTF-8; при любой ошибке ввода-вывода возвращает default."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return default


def sanitize_name(name, fallback="file"):
    """Делает имя файла безопасным: без путей, пробелов и служебных символов.
    Используется для картинок пользователя; служебные имена не трогаем."""
    name = os.path.basename(str(name).strip())
    name = re.sub(r"[^\w.\-]+", "_", name, flags=re.UNICODE)
    name = re.sub(r"_{2,}", "_", name).strip("._")
    return (name or fallback)[:80]


def is_inside(child, parent):
    """True, если child лежит внутри parent. Защита от записи «мимо проекта»."""
    try:
        child = os.path.normcase(os.path.abspath(child))
        parent = os.path.normcase(os.path.abspath(parent))
        return os.path.commonpath([child, parent]) == parent
    except (ValueError, OSError):
        return False


def shorten(text, limit):
    """Обрезает длинный текст с явной пометкой — чтобы контекст промпта не разъезжался."""
    text = text or ""
    if limit <= 0 or len(text) <= limit:
        return text
    return text[:limit] + "\n…[обрезано %d символов]…\n" % (len(text) - limit)


def fmt_cmd(args):
    """Собирает команду в строку для показа в логе (реально запускаем списком)."""
    args = [str(a) for a in args]
    if is_windows():
        return subprocess.list2cmdline(args)
    return " ".join(shlex.quote(a) for a in args)


def open_folder(path):
    """Открывает папку/файл средствами ОС. Если инструмента нет — подсказка в лог."""
    if not path or not os.path.exists(path):
        log("Путь не существует: %s" % path, "warn")
        return False
    try:
        if is_windows():
            os.startfile(path)                      # стандартный способ Windows
            return True
        cmd = ["open", path] if platform.system() == "Darwin" else ["xdg-open", path]
        log("$ " + fmt_cmd(cmd), "cmd")
        subprocess.run(cmd, capture_output=True, timeout=LIMITS["timeout_cmd"])
        return True
    except FileNotFoundError:
        log("Не найдена программа для открытия папки (xdg-open). "
            "Откройте вручную: %s" % path, "warn")
    except Exception as e:
        log("Не удалось открыть %s: %s" % (path, e), "err")
    return False


def clipboard_put(widget, text):
    """Кладёт текст в системный буфер обмена через указанный виджет."""
    try:
        widget.clipboard_clear()
        widget.clipboard_append(text)
        widget.update_idletasks()
        log("Скопировано в буфер обмена (%d символов)." % len(text or ""), "ok")
        return True
    except Exception as e:
        log("Буфер обмена недоступен: %s. Выделите текст и нажмите Ctrl+C." % e, "warn")
        return False


# --- Лог ---------------------------------------------------------------------
# Лог пишут и UI-поток, и фоновые задачи. Поэтому буфер защищён замком,
# а интерфейс забирает новые строки из очереди по таймеру (tkinter не потокобезопасен).
LOG_LOCK = threading.Lock()
LOG_BUFFER = []                 # история строк: (время, тип, текст)
LOG_QUEUE = queue.Queue()       # то же самое, но для потребления интерфейсом


def log(text, kind="info"):
    """Добавляет строку в лог. kind: info | cmd | ok | warn | err | raw."""
    rec = (now_human(), kind, str(text))
    with LOG_LOCK:
        LOG_BUFFER.append(rec)
        overflow = len(LOG_BUFFER) - LIMITS["log_lines"]
        if overflow > 0:
            del LOG_BUFFER[:overflow]      # кольцевой буфер: память не растёт бесконечно
    LOG_QUEUE.put(rec)


def log_events():
    """Забирает все накопившиеся строки лога (вызывается из UI-потока по таймеру)."""
    out = []
    while True:
        try:
            out.append(LOG_QUEUE.get_nowait())
        except queue.Empty:
            break
    return out


def log_text():
    """Весь лог одной строкой — для кнопки «Копировать» и сохранения в файл."""
    with LOG_LOCK:
        return "\n".join("[%s] %s: %s" % rec for rec in LOG_BUFFER)


def show_error(title, detail):
    """Показывает окно с ошибкой. Если GUI ещё не готов — только лог."""
    try:
        messagebox.showerror(APP_NAME + " — " + title, detail)
    except Exception:
        pass


def safe_action(title):
    """Декоратор для обработчиков кнопок: ни одно исключение не роняет приложение.
    Пишет короткую причину и полную трассировку в лог, показывает окно пользователю."""
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except Exception as e:
                tb = traceback.format_exc()
                log("Сбой в действии «%s»: %s: %s" % (title, type(e).__name__, e), "err")
                log(tb, "raw")
                show_error(title, "%s: %s\n\nПодробности — в лог-консоли внизу окна."
                           % (type(e).__name__, e))
                return None
        return wrapper
    return decorator


# =============================================================================
# СЕКЦИЯ 3. СОСТОЯНИЕ ПРИЛОЖЕНИЯ (AppState)
# =============================================================================


def default_state():
    """Пустое состояние нового проекта. Никаких выдуманных ответов пользователя:
    поля пустые, флаги выключены — их отмечает человек."""
    return {
        "schema_version": SCHEMA_VERSION,
        "app_version": APP_VERSION,
        "created_at": now_human(),
        "updated_at": now_human(),
        "theme": {"key": "", "title": ""},
        "project": {"name": "", "folder": ""},
        # presets — редактируемые черновики выбранной темы (заполняются в секции 4)
        "presets": {"stack": "", "structure": "", "questions": [], "invariants": ""},
        "flags": {"git": False, "venv": False, "tests": False, "html_report": False},
        "settings": {"theme_mode": "dark", "context_limit": LIMITS["context_chars"],
                     "last_tab": 0, "autosave": True},
        "stages": [
            {"id": sid, "num": num, "title": title, "status": "empty",
             "fields": {}, "prompt": "", "llm_result": "", "images": [],
             "approved_at": "", "updated_at": ""}
            for sid, num, title, _sub in STAGES
        ],
        "history": [],   # метаданные снапшотов: файл, время, причина, этап
    }


def normalize_state(raw):
    """Приводит загруженный словарь к текущему формату.
    Зачем: state.json мог быть сохранён старой версией или повреждён —
    недостающие ключи дополняем значениями по умолчанию, мусор отбрасываем."""
    base = default_state()
    if not isinstance(raw, dict):
        return base
    for key in ("created_at", "app_version", "updated_at"):
        if isinstance(raw.get(key), str):
            base[key] = raw[key]
    for key in ("theme", "project", "presets", "flags", "settings"):
        if isinstance(raw.get(key), dict):
            base[key].update({k: v for k, v in raw[key].items() if k in base[key]})
    if isinstance(raw.get("history"), list):
        base["history"] = raw["history"]

    # Этапы сопоставляем по id, а не по порядку — порядок вкладок мог измениться.
    raw_stages = raw.get("stages")
    if not isinstance(raw_stages, list):        # защита от "stages": null
        raw_stages = []
    old = {s.get("id"): s for s in raw_stages if isinstance(s, dict)}
    for stage in base["stages"]:
        src = old.get(stage["id"])
        if not src:
            continue
        if isinstance(src.get("fields"), dict):
            stage["fields"] = src["fields"]
        for key in ("prompt", "llm_result", "approved_at", "updated_at"):
            if isinstance(src.get(key), str):
                stage[key] = src[key]
        if isinstance(src.get("images"), list):
            stage["images"] = [p for p in src["images"] if isinstance(p, str)]
        if src.get("status") in ("empty", "draft", "approved"):
            stage["status"] = src["status"]

    # Настройки: значения могли быть испорчены руками — приводим к рабочим.
    st = base["settings"]
    if st.get("theme_mode") not in ("dark", "light"):
        st["theme_mode"] = "dark"
    try:
        st["context_limit"] = max(LIMITS["context_min"],
                                  min(LIMITS["context_max"], int(st.get("context_limit"))))
    except (TypeError, ValueError):
        st["context_limit"] = LIMITS["context_chars"]
    try:
        st["last_tab"] = max(0, int(st.get("last_tab", 0)))
    except (TypeError, ValueError):
        st["last_tab"] = 0
    st["autosave"] = bool(st.get("autosave", True))
    for key in base["flags"]:
        base["flags"][key] = bool(base["flags"].get(key))
    if not isinstance(base["presets"].get("questions"), list):
        base["presets"]["questions"] = []
    return base


class AppState:
    """Единственный источник правды о проекте.
    Интерфейс читает и меняет состояние только через методы этого класса —
    так снапшоты, автосохранение и экспорт всегда видят согласованные данные."""

    def __init__(self):
        self.data = default_state()
        self.dirty = False          # есть несохранённые изменения
        self.loaded_from = ""       # откуда читали state.json (для статуса)

    # --- доступ к частям состояния ------------------------------------------
    @property
    def folder(self):
        return self.data["project"]["folder"]

    @property
    def name(self):
        return self.data["project"]["name"]

    def stage(self, sid):
        """Запись этапа по id (их всего 7, линейный поиск дешевле словаря-индекса)."""
        for s in self.data["stages"]:
            if s["id"] == sid:
                return s
        return None

    def touch(self):
        """Отмечает изменение: время обновления + флаг «надо сохранить»."""
        self.data["updated_at"] = now_human()
        self.dirty = True

    # --- правки --------------------------------------------------------------
    def set_folder(self, path):
        """Задаёт рабочую папку. Всё остальное приложение работает только с ней."""
        if not path:
            return False
        path = os.path.abspath(os.path.expanduser(path))
        if os.path.isfile(path):
            log("Выбран файл, а не папка: %s" % path, "err")
            return False
        self.data["project"]["folder"] = path
        if not self.data["project"]["name"]:
            self.data["project"]["name"] = os.path.basename(path)
        self.touch()
        log("Рабочая папка проекта: %s" % path, "ok")
        return True

    def set_name(self, name):
        """Имя проекта для шапки, промптов и отчёта."""
        self.data["project"]["name"] = (name or "").strip()
        self.touch()

    def set_theme(self, key, title, presets=None):
        """Запоминает выбранную тему и (опционально) её редактируемые пресеты."""
        self.data["theme"] = {"key": key, "title": title}
        if presets is not None:
            self.data["presets"] = copy.deepcopy(presets)
        self.touch()

    def set_flag(self, key, value):
        """Флаги «нужны git/venv/тесты/HTML» — ответы пользователя, не наши догадки."""
        if key in self.data["flags"]:
            self.data["flags"][key] = bool(value)
            self.touch()

    def set_setting(self, key, value):
        """Настройки интерфейса (тема, лимит контекста, последняя вкладка)."""
        if key in self.data["settings"]:
            self.data["settings"][key] = value
            self.touch()

    def set_field(self, sid, key, value):
        """Ответ пользователя на поле этапа. Пустой этап становится черновиком."""
        st = self.stage(sid)
        if st is None:
            return
        st["fields"][key] = value
        st["updated_at"] = now_human()
        if st["status"] == "empty" and str(value).strip():
            st["status"] = "draft"
        self.touch()

    def set_prompt(self, sid, text):
        """Сохраняет собранный (и, возможно, вручную поправленный) промпт этапа."""
        st = self.stage(sid)
        if st is not None:
            st["prompt"] = text or ""
            st["updated_at"] = now_human()
            if st["status"] == "empty" and st["prompt"].strip():
                st["status"] = "draft"
            self.touch()

    def set_result(self, sid, text):
        """Сохраняет ответ внешней LLM, вставленный пользователем."""
        st = self.stage(sid)
        if st is not None:
            st["llm_result"] = text or ""
            st["updated_at"] = now_human()
            if st["status"] == "empty" and st["llm_result"].strip():
                st["status"] = "draft"
            self.touch()

    def approve(self, sid):
        """Утверждает этап: его результат пойдёт в контекст следующих промптов."""
        st = self.stage(sid)
        if st is None:
            return False
        st["status"] = "approved"
        st["approved_at"] = now_human()
        self.touch()
        log("Этап «%s» утверждён." % st["title"], "ok")
        return True

    def unapprove(self, sid):
        """Снимает утверждение (например, пользователь переписал ответ LLM)."""
        st = self.stage(sid)
        if st is None:
            return False
        st["status"] = "draft" if (st["llm_result"].strip() or st["fields"]) else "empty"
        st["approved_at"] = ""
        self.touch()
        log("Снято утверждение этапа «%s»." % st["title"], "warn")
        return True

    def add_image(self, sid, rel_path):
        """Регистрирует картинку этапа (путь относительный, внутри images/)."""
        st = self.stage(sid)
        if st is not None and rel_path not in st["images"]:
            st["images"].append(rel_path)
            self.touch()

    def remove_image(self, sid, rel_path):
        """Убирает картинку из списка этапа (файл на диске не трогаем)."""
        st = self.stage(sid)
        if st is not None and rel_path in st["images"]:
            st["images"].remove(rel_path)
            self.touch()

    # --- выборки -------------------------------------------------------------
    def approved_before(self, sid):
        """Утверждённые этапы, идущие ДО указанного, — это контекст промпта."""
        if sid not in STAGE_IDS:
            return []
        cut = STAGE_IDS.index(sid)
        return [s for s in self.data["stages"][:cut] if s["status"] == "approved"]

    def approved_ids(self):
        return [s["id"] for s in self.data["stages"] if s["status"] == "approved"]

    def progress(self):
        """(сколько рабочих этапов утверждено, всего рабочих этапов)."""
        done = sum(1 for s in self.data["stages"]
                   if s["id"] in WORK_STAGE_IDS and s["status"] == "approved")
        return done, len(WORK_STAGE_IDS)

    # --- сохранение / загрузка ----------------------------------------------
    def state_path(self):
        """Полный путь к state.json внутри рабочей папки."""
        return os.path.join(self.folder, STATE_FILE) if self.folder else ""

    def to_dict(self):
        """Копия состояния — для снапшотов и сериализации."""
        return copy.deepcopy(self.data)

    def load_dict(self, raw):
        """Заменяет состояние нормализованными данными (используется и при откате)."""
        self.data = normalize_state(raw)
        self.dirty = True

    def save(self, quiet=False):
        """Пишет state.json в рабочую папку. Без папки — честно сообщает и не падает."""
        if not self.folder:
            if not quiet:
                log("Папка проекта не выбрана — сохранять некуда. "
                    "Откройте вкладку «Старт» и выберите папку.", "warn")
            return False
        # Не воскрешаем путь с другой машины: если родителя нет — это не наш диск.
        parent = os.path.dirname(os.path.abspath(self.folder))
        if not os.path.isdir(self.folder) and not os.path.isdir(parent):
            log("Папка проекта недоступна: %s. Выберите папку заново на вкладке «Старт»."
                % self.folder, "err")
            return False
        ensure_dir(self.folder)
        atomic_write(self.state_path(),
                     json.dumps(self.data, ensure_ascii=False, indent=2))
        self.dirty = False
        if not quiet:
            log("Состояние сохранено: %s" % self.state_path(), "ok")
        return True

    def load(self, path):
        """Читает state.json. Битый файл не роняет приложение: сообщаем и живём дальше."""
        text = read_text(path, "")
        if not text:
            log("Файл состояния не найден или пуст: %s" % path, "warn")
            return False
        try:
            raw = json.loads(text)
        except ValueError as e:
            log("state.json повреждён (%s). Загружено пустое состояние, "
                "старый файл оставлен на диске." % e, "err")
            return False
        self.data = normalize_state(raw)
        self.loaded_from = path
        self.dirty = False
        log("Состояние загружено: %s" % path, "ok")
        return True


# =============================================================================
# СЕКЦИЯ 4. ПРЕСЕТЫ ТЕМ И ОПИСАНИЯ ПОЛЕЙ ЭТАПОВ
# -----------------------------------------------------------------------------
# Здесь лежит ВСЁ содержимое-заготовка: темы, наводящие вопросы, поля этапов.
# Принцип: это черновики для редактирования, а не ответы за пользователя.
# =============================================================================

# Общая приписка к любому черновику — чтобы человек не принял его за решение.
PRESET_DISCLAIMER = (
    "# ЧЕРНОВИК-ПРЕДЛОЖЕНИЕ, а не готовый ответ. Правьте под себя.\n"
    "# Внешние библиотеки — только если вы их согласовали; наличие и версии\n"
    "# помечайте как ТРЕБУЕТ ПРОВЕРКИ. Сама «Лаборатория» использует только stdlib.\n"
)


def make_question(qid, question, hint="", options=None):
    """Единый формат наводящего вопроса.
    options — не «варианты ответа», а подсказки-заготовки: клик вставляет текст
    в поле ответа, который человек правит своими словами."""
    return {"id": qid, "kind": "question", "question": question,
            "hint": hint, "options": list(options or [])}


def make_field(key, label, kind="text", hint="", rows=4, options=None):
    """Единый формат поля этапа.
    kind: line — одна строка; text — многострочное; checks — набор галочек."""
    return {"key": key, "label": label, "kind": kind,
            "hint": hint, "rows": int(rows), "options": list(options or [])}


# --- Базовые вопросы этапа «Идея» (ровно те 10, что в ТЗ) --------------------
# Они одинаковы для всех тем; тема только ДОБАВЛЯЕТ свои вопросы поверх них.
IDEA_QUESTIONS = [
    make_question(
        "one_liner", "Что делает проект — одним предложением?",
        "Формула: «Инструмент, который помогает <кому> делать <что> из <чего>».",
        ["Собирает данные из … и складывает в …",
         "Считает … по правилам …",
         "Готовит отчёт о …",
         "Управляет … через …"]),
    make_question(
        "user", "Кто пользователь?",
        "Один человек или отдел? Работает сам или запускает по расписанию?",
        ["Только я", "Коллеги / отдел", "Внешние заказчики",
         "Другая программа (по API)", "Оператор у станка/пульта"]),
    make_question(
        "input", "Что на входе?",
        "Форматы, откуда берётся, кто кладёт. Примеры приветствуются.",
        ["Файлы (csv / xlsx / pdf)", "Сайт / веб-страницы", "Ручной ввод",
         "Другое ПО / API", "Оборудование / порт"]),
    make_question(
        "output", "Что на выходе?",
        "Что именно человек получает и куда это кладётся.",
        ["Файл (csv / xlsx / pdf)", "HTML-отчёт", "Графики",
         "Код / конфиг для другого ПО", "Команды оборудованию", "Запись в БД"]),
    make_question(
        "internet", "Нужен ли доступ в интернет?",
        "Если да — куда именно и что будет, когда связи нет.",
        ["Нет, полностью оффлайн", "Да, только чтение данных",
         "Да, API стороннего сервиса", "Не знаю — уточнить"]),
    make_question(
        "data", "Откуда данные, какой объём, нужно ли хранить историю?",
        "Источник, сколько записей/файлов за раз, как часто, сколько хранить.",
        ["До 1 тыс. записей", "1 тыс. — 1 млн", "Поток / постоянно",
         "Историю хранить обязательно", "История не нужна"]),
    make_question(
        "external", "Есть ли внешнее ПО, лицензии, ключи?",
        "Что должно быть установлено, кто выдаёт доступ, где лежат ключи.",
        ["Нет", "Excel / 1С / CRM", "CAD / CAE / CAM",
         "Лицензионный сервер или ключ", "API-ключи (в .env)"]),
    make_question(
        "limits", "Ограничения: оффлайн, бюджет, время?",
        "Что нельзя нарушить: сроки, деньги, права администратора, политика ИБ.",
        ["Только оффлайн", "Бюджет 0 — только бесплатное", "Срок — дни",
         "Срок — недели", "Работа без прав администратора"]),
    make_question(
        "stack", "Какой стек предпочитаешь?",
        "Варианты ниже — предложения для выбранной темы. Можно оставить пусто.",
        []),   # варианты подставляются из темы (см. idea_questions)
    # Последний вопрос — не текст, а галочки: они пишутся в state["flags"].
    {"id": "tooling", "kind": "flags",
     "question": "Что подключаем сразу?",
     "hint": "Отметьте нужное. Кнопки реальных действий на вкладке «Старт» "
             "работают независимо от этих галочек — это ответ для промпта.",
     "flags": [("git", "Git и первый коммит"),
               ("venv", "Виртуальное окружение .venv"),
               ("tests", "Тесты (pytest / unittest)"),
               ("html_report", "HTML-отчёт")]},
]

# --- Темы --------------------------------------------------------------------
# extra_dirs — папки сверх базового набора; создаются только после подтверждения.
THEMES = {
    "engineering": {
        "title": "Инженерный",
        "desc": "Автоматизация оборудования, интеграция с инженерным ПО, расчёты.",
        "stack": PRESET_DISCLAIMER + (
            "Python 3.10+\n"
            "Обмен с оборудованием: pyserial / pymodbus (внешние, по согласованию)\n"
            "Расчёты: чистый Python; numpy — если нужны массивы\n"
            "Файлы: csv, json (stdlib); xlsx — openpyxl (внешняя)\n"
            "Отчёты: HTML на string.Template (stdlib)\n"
            "Тесты: unittest (stdlib) или pytest (внешний)\n"),
        "stack_options": ["Python + stdlib", "Python + pyserial/pymodbus",
                          "Python + numpy", "Обмен файлами с CAD/CAM",
                          "Симулятор вместо реального железа"],
        "extra_dirs": ["src/drivers", "src/calc", "docs/specs",
                       "data/raw", "data/samples"],
        "questions": [
            make_question("eq_link", "С каким оборудованием или ПО идёт обмен и по какому протоколу?",
                          "Порт, скорость, протокол, кто инициатор обмена.",
                          ["COM / RS-485 (Modbus)", "TCP/IP", "Файловый обмен",
                           "Обмена нет, только расчёт"]),
            make_question("eq_safety", "Что нельзя делать ни при каких условиях?",
                          "Аварийные ограничения и обязательные подтверждения оператора.",
                          ["Команда только после подтверждения",
                           "Запрет записи в рабочее ПО", "Только чтение"]),
            make_question("eq_units", "Какие единицы измерения и допуски?",
                          "Что считаем ошибкой: выход за допуск, потеря связи, рассинхрон.",
                          ["мм / мм в минуту", "градусы", "мбар / литры", "допуск задан в ТЗ"]),
            make_question("eq_sim", "Нужен ли режим без реального оборудования (симулятор)?",
                          "Чтобы разрабатывать и тестировать оффлайн.",
                          ["Да, симулятор обязателен", "Нет", "Позже"]),
            make_question("eq_time", "Есть ли требования по времени отклика?",
                          "Если реальное время — это отдельная архитектура, отметьте как риск.",
                          ["Нет, пакетная обработка", "Секунды",
                           "Миллисекунды — ТРЕБУЕТ ПРОВЕРКИ"]),
        ],
        "invariants": PRESET_DISCLAIMER + (
            "- Исходные данные не изменяются: работаем с копиями.\n"
            "- Единицы измерения указываются явно, перевод — в одном месте.\n"
            "- Каждая команда оборудованию логируется: время, параметры, ответ.\n"
            "- Потеря связи не приводит к молчаливому продолжению работы.\n"
            "- Расчётные функции чистые: вход → выход, без побочных эффектов.\n"),
    },
    "finance": {
        "title": "Экономический",
        "desc": "Финансы, бюджеты, цены, отчёты.",
        "stack": PRESET_DISCLAIMER + (
            "Python 3.10+\n"
            "Деньги: decimal.Decimal (stdlib), никаких float\n"
            "Файлы: csv, json (stdlib); xlsx — openpyxl (внешняя)\n"
            "Хранение: sqlite3 (stdlib)\n"
            "Отчёты: HTML (stdlib) + сводные таблицы\n"
            "Тесты: unittest / pytest, обязательно на округлениях\n"),
        "stack_options": ["Python + Decimal + csv", "Python + sqlite3",
                          "Python + openpyxl (xlsx)", "HTML-отчёт на stdlib",
                          "Выгрузка для 1С / ERP"],
        "extra_dirs": ["src/importers", "src/reports", "data/raw",
                       "data/dicts", "docs/methodology"],
        "questions": [
            make_question("fin_source", "Откуда берутся цифры?",
                          "Выгрузка из учётной системы, прайсы, банк, ручной ввод.",
                          ["1С / ERP", "Банковская выписка", "Прайсы поставщиков", "Ручной ввод"]),
            make_question("fin_period", "Какой период и как он закрывается?",
                          "День / месяц / квартал; можно ли пересчитывать закрытый период.",
                          ["День", "Месяц", "Квартал", "Пересчёт запрещён после закрытия"]),
            make_question("fin_round", "Правила округления и валюты?",
                          "Сколько знаков, на каком шаге округляем, что с курсами.",
                          ["2 знака, ROUND_HALF_UP", "Округление только в конце",
                           "Одна валюта", "Мультивалютность + курсы"]),
            make_question("fin_match", "Как сопоставляются справочники (номенклатура, контрагенты)?",
                          "По коду, по имени, вручную; что делать с несопоставленным.",
                          ["По артикулу / коду", "По названию", "Таблица соответствий", "Вручную"]),
            make_question("fin_check", "Как проверяем, что цифры сошлись?",
                          "Контрольные суммы, сверка с источником, кто подписывает отчёт.",
                          ["Контрольные итоги", "Сверка с выгрузкой", "Двойная проверка человеком"]),
            make_question("fin_privacy", "Насколько данные чувствительные?",
                          "Персональные данные, коммерческая тайна, где можно хранить.",
                          ["Обычные рабочие", "Коммерческая тайна",
                           "Персональные данные", "Только локально"]),
        ],
        "invariants": PRESET_DISCLAIMER + (
            "- Деньги только в Decimal; float запрещён.\n"
            "- Округление по единому правилу и в одном месте кода.\n"
            "- Итоги отчёта сходятся с источником до копейки.\n"
            "- Закрытый период не меняется: только новая версия расчёта.\n"
            "- Ключи и пароли — в .env, не в коде и не в git.\n"),
    },
    "data": {
        "title": "Аналитика данных",
        "desc": "Парсинг, обработка, отчёты, графики.",
        "stack": PRESET_DISCLAIMER + (
            "Python 3.10+\n"
            "Загрузка: urllib.request (stdlib); requests — по согласованию\n"
            "Обработка: csv, json, statistics (stdlib); pandas — если объёмы большие\n"
            "Хранение: sqlite3 (stdlib)\n"
            "Графики: matplotlib (внешняя) или SVG вручную (stdlib)\n"
            "Отчёты: HTML (stdlib)\n"),
        "stack_options": ["Python + stdlib (csv/json)", "Python + pandas",
                          "Python + requests", "sqlite3 как хранилище",
                          "SVG-графики без библиотек"],
        "extra_dirs": ["src/parsers", "src/transforms", "data/raw",
                       "data/processed", "out/reports"],
        "questions": [
            make_question("dat_source", "Источник данных и способ получения?",
                          "API, выгрузка, парсинг страниц; есть ли ограничения по частоте.",
                          ["Открытый API", "Выгрузка файлом", "Парсинг сайта", "Внутренняя БД"]),
            make_question("dat_volume", "Объём и частота обновления?",
                          "Сколько строк за запуск, как часто, нужен ли инкремент.",
                          ["Разово", "Ежедневно", "Каждый час", "Инкрементальная дозагрузка"]),
            make_question("dat_quality", "Что делать с пропусками, дубликатами, выбросами?",
                          "Правила чистки должны быть явными, а не «как получится».",
                          ["Пропуски помечать, не заполнять", "Дубликаты по ключу",
                           "Выбросы выносить в отчёт", "Чистка по правилам из ТЗ"]),
            make_question("dat_key", "Что считается ключом записи (дедупликация)?",
                          "По каким полям понимаем, что это та же самая строка.",
                          ["ID источника", "Дата + название", "Хэш строки"]),
            make_question("dat_metrics", "Какие метрики и графики нужны в отчёте?",
                          "Что именно смотрит человек и какое решение принимает.",
                          ["Динамика во времени", "Топ-N", "Сравнение категорий", "Сводная таблица"]),
            make_question("dat_repro", "Нужна ли воспроизводимость расчёта?",
                          "Храним ли сырьё и версию кода, чтобы повторить отчёт через месяц.",
                          ["Да, сырьё сохраняем", "Да, версии фиксируем", "Не требуется"]),
        ],
        "invariants": PRESET_DISCLAIMER + (
            "- Сырые данные неизменяемы: все шаги работают с копиями.\n"
            "- Каждый шаг обработки воспроизводим и логируется.\n"
            "- Пропуски и дубликаты не «исчезают» молча — попадают в отчёт.\n"
            "- В отчёте всегда есть дата, источник и версия расчёта.\n"
            "- Парсинг уважает ограничения источника (частота, robots).\n"),
    },
    "web": {
        "title": "Веб / сервисы",
        "desc": "Сайты, API, внутренние сервисы.",
        "stack": PRESET_DISCLAIMER + (
            "Python 3.10+\n"
            "Прототип: http.server (stdlib)\n"
            "Сервис: Flask или FastAPI (внешние, по согласованию)\n"
            "Хранение: sqlite3 (stdlib)\n"
            "Шаблоны: string.Template (stdlib) или Jinja2 (внешняя)\n"
            "Клиент: urllib.request (stdlib)\n"),
        "stack_options": ["stdlib http.server (прототип)", "Flask", "FastAPI",
                          "sqlite3", "Только API без интерфейса"],
        "extra_dirs": ["src/api", "src/web", "static", "templates", "docs/api"],
        "questions": [
            make_question("web_client", "Кто ходит в сервис?",
                          "Браузер человека, скрипт, другая система.",
                          ["Браузер", "Скрипт / cron", "Другая система", "Смешанно"]),
            make_question("web_api", "Какие эндпоинты и контракты нужны?",
                          "Метод, путь, вход, выход, коды ошибок.",
                          ["GET /items", "POST /jobs", "GET /report", "Список уточню позже"]),
            make_question("web_auth", "Нужна ли авторизация?",
                          "Кто и как доказывает, что ему можно.",
                          ["Нет, только localhost", "Токен в заголовке",
                           "Логин/пароль", "Внешний SSO"]),
            make_question("web_host", "Где это будет работать?",
                          "Локальная машина, сервер в сети, контейнер; есть ли интернет.",
                          ["Только мой компьютер", "Сервер в локальной сети",
                           "Внешний хостинг", "Контейнер"]),
            make_question("web_load", "Какая ожидается нагрузка?",
                          "Запросов в минуту, размер ответа, нужен ли фон/очередь.",
                          ["Единицы запросов", "Десятки в минуту", "Сотни и больше", "Не знаю"]),
        ],
        "invariants": PRESET_DISCLAIMER + (
            "- Секреты не попадают в код, логи и git.\n"
            "- Любой вход валидируется до использования.\n"
            "- Ошибки возвращаются с понятным кодом и текстом, без стектрейса наружу.\n"
            "- Изменение контракта API — только с новой версией.\n"
            "- Сервис поднимается одной командой из README.\n"),
    },
    "science": {
        "title": "Научный / исследовательский",
        "desc": "Модели, эксперименты, проверка гипотез.",
        "stack": PRESET_DISCLAIMER + (
            "Python 3.10+\n"
            "Расчёты: чистый Python; numpy / scipy — по согласованию\n"
            "Графики: matplotlib (внешняя) или SVG (stdlib)\n"
            "Эксперименты: json/csv + фиксация параметров запуска\n"
            "Тесты: unittest (stdlib) на ключевых формулах\n"),
        "stack_options": ["Python + stdlib", "Python + numpy/scipy",
                          "matplotlib", "Эксперименты в json/csv", "SVG-графики"],
        "extra_dirs": ["src/model", "experiments", "data/raw",
                       "data/results", "docs/paper"],
        "questions": [
            make_question("sci_hypo", "Какую гипотезу проверяем?",
                          "Что должно получиться, чтобы работа считалась успешной.",
                          ["Сравнить два метода", "Оценить влияние параметра",
                           "Построить модель процесса", "Проверить качество данных"]),
            make_question("sci_metric", "Метрики и критерий успеха?",
                          "Чем измеряем и какой порог считаем достаточным.",
                          ["Ошибка (MAE/RMSE)", "Точность/полнота",
                           "Время счёта", "Порог задан в ТЗ"]),
            make_question("sci_data", "Данные свои или открытые? Какая лицензия?",
                          "Можно ли их публиковать вместе с результатами.",
                          ["Свои измерения", "Открытый датасет", "Данные заказчика", "Смешанные"]),
            make_question("sci_repro", "Что фиксируем для воспроизводимости?",
                          "Seed, версии библиотек, параметры запуска, контрольные примеры.",
                          ["Seed", "Версии библиотек", "Параметры в файле", "Контрольный пример"]),
            make_question("sci_result", "Что считаем результатом работы?",
                          "Числа, графики, статья, набор файлов для дальнейшей работы.",
                          ["Таблица результатов", "Графики", "Отчёт/статья", "Модель + параметры"]),
        ],
        "invariants": PRESET_DISCLAIMER + (
            "- Seed и версии фиксируются в каждом эксперименте.\n"
            "- Сырые данные неприкосновенны.\n"
            "- Один эксперимент = папка с параметрами, логами и результатом.\n"
            "- Выводы отделены от данных: сначала цифры, потом трактовка.\n"
            "- Отрицательный результат тоже сохраняется.\n"),
    },
    "office": {
        "title": "Автоматизация офиса / скрипты",
        "desc": "Рутинные операции с файлами, отчёты, рассылки.",
        "stack": PRESET_DISCLAIMER + (
            "Python 3.10+\n"
            "Файлы и папки: os, shutil, pathlib, zipfile (stdlib)\n"
            "Таблицы: csv (stdlib); xlsx — openpyxl, docx — python-docx (внешние)\n"
            "Планировщик: средства ОС (Планировщик Windows / cron)\n"
            "Логи: logging (stdlib)\n"),
        "stack_options": ["Python + stdlib", "openpyxl (xlsx)", "python-docx",
                          "Запуск по расписанию ОС", "Один .bat/.sh для запуска"],
        "extra_dirs": ["src/jobs", "inbox", "out", "docs/runbooks"],
        "questions": [
            make_question("off_routine", "Какая рутина и сколько времени она занимает?",
                          "Опишите шаги как есть сейчас — это основа сценария.",
                          ["Переименование файлов", "Сборка отчёта из файлов",
                           "Рассылка", "Перекладывание по папкам"]),
            make_question("off_files", "Где лежат файлы и как называются?",
                          "Шаблон имени, кодировка, что делать с неожиданными именами.",
                          ["Шаблон имени есть", "Имена произвольные",
                           "Сетевая папка", "Локальная папка"]),
            make_question("off_errors", "Что делать, если файл битый или уже обработан?",
                          "Пропустить, повторить, остановить всё — выберите правило.",
                          ["Пропустить и записать в отчёт", "Остановить всю пачку",
                           "Повторить попытку", "Спросить человека"]),
            make_question("off_undo", "Нужен ли откат операций?",
                          "Удаление, перемещение, перезапись — что и как возвращаем.",
                          ["Да, корзина/бэкап", "Только сухой прогон", "Откат не нужен"]),
            make_question("off_run", "Запуск вручную или по расписанию?",
                          "Кто нажимает кнопку и что видит после запуска.",
                          ["Вручную", "По расписанию", "По появлению файла", "Из другого скрипта"]),
        ],
        "invariants": PRESET_DISCLAIMER + (
            "- Сначала сухой прогон: показываем, что будет сделано.\n"
            "- Ничего не удаляем без бэкапа или корзины.\n"
            "- Повторный запуск не создаёт дубликаты.\n"
            "- Каждый запуск пишет отчёт: что сделано, что пропущено, почему.\n"
            "- Пути и имена — через os.path, без «зашитых» дисков.\n"),
    },
    "blank": {
        "title": "Другое (чистый лист)",
        "desc": "Без пресетов: только базовая структура и общие вопросы.",
        "stack": PRESET_DISCLAIMER + (
            "Python 3.x\n"
            "Стандартная библиотека — по умолчанию\n"
            "Внешние библиотеки — только по вашему явному решению\n"),
        "stack_options": ["Python + stdlib", "Свой вариант (напишу сам)"],
        "extra_dirs": [],
        "questions": [],
        "invariants": PRESET_DISCLAIMER + (
            "- Исходные данные не портим.\n"
            "- Ошибки не глотаем молча.\n"
            "- Секреты — в .env, не в коде.\n"),
    },
}

THEME_ORDER = ["engineering", "finance", "data", "web", "science", "office", "blank"]
THEME_TITLES = [(key, THEMES[key]["title"]) for key in THEME_ORDER]


def get_theme(key):
    """Тема по ключу. Неизвестный ключ → «чистый лист», а не ошибка."""
    return THEMES.get(key, THEMES["blank"])


def theme_title(key):
    """Название темы для шапки и промпта."""
    return get_theme(key)["title"]


def structure_text(key):
    """Черновик структуры: базовые папки + дополнительные для темы.
    Формат важен: строки, оканчивающиеся на '/', позже читает Scaffolder."""
    theme = get_theme(key)
    lines = ["# Базовые папки — создаются кнопкой «Создать структуру»:",
             "# " + "  ".join(d + "/" for d in BASE_DIRS),
             "# Дополнительно для темы «%s» (создаются после подтверждения):" % theme["title"]]
    for d in theme["extra_dirs"]:
        lines.append(d.rstrip("/") + "/")
    if not theme["extra_dirs"]:
        lines.append("# (нет — чистый лист)")
    lines.append("# Правьте свободно: строка вида path/ = папка, строки с # игнорируются.")
    return "\n".join(lines)


def clone_presets(key):
    """Копия пресетов темы в формат state['presets'].
    Копия, а не ссылка: правки пользователя не должны менять справочник THEMES."""
    theme = get_theme(key)
    return {"stack": theme["stack"],
            "structure": structure_text(key),
            "questions": copy.deepcopy(theme["questions"]),
            "invariants": theme["invariants"]}


def questions_to_text(questions):
    """Вопросы темы → редактируемый текст (по одному вопросу на строку)."""
    lines = ["# Формат:  id | вопрос | подсказка | вариант1; вариант2",
             "# Это черновик вопросов темы. Строки с # игнорируются.",
             "# Удалите все строки, если вопросы темы не нужны."]
    for qd in questions or []:
        if not isinstance(qd, dict) or qd.get("kind") == "flags":
            continue
        lines.append(" | ".join([qd.get("id", ""), qd.get("question", ""),
                                 qd.get("hint", ""),
                                 "; ".join(qd.get("options") or [])]))
    return "\n".join(lines)


def questions_from_text(text):
    """Текст пользователя → список вопросов. Терпим к неполным строкам:
    не хватает колонок — подставляем пустые, id генерируем."""
    out = []
    for i, raw in enumerate((text or "").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) >= 4:
            qid, question, hint, opts = parts[0], parts[1], parts[2], parts[3]
        elif len(parts) == 3:
            qid, question, hint, opts = parts[0], parts[1], parts[2], ""
        elif len(parts) == 2:
            qid, question, hint, opts = "q%d" % i, parts[0], parts[1], ""
        else:
            qid, question, hint, opts = "q%d" % i, parts[0], "", ""
        if not question:
            continue
        options = [o.strip() for o in opts.split(";") if o.strip()]
        out.append(make_question(sanitize_name(qid, "q%d" % i), question, hint, options))
    return out


def idea_questions(state):
    """Полный список вопросов этапа «Идея»: базовые + вопросы темы.
    Порядок: базовые → тематические → галочки инструментов (всегда последние).
    Пустой список в пресетах уважаем: человек мог убрать вопросы темы намеренно."""
    theme = get_theme(state.data["theme"]["key"])
    base = copy.deepcopy(IDEA_QUESTIONS)
    for qd in base:
        if qd["id"] == "stack":
            qd["options"] = list(theme.get("stack_options") or [])
    extras = state.data["presets"].get("questions")
    if not isinstance(extras, list):
        extras = theme.get("questions") or []
    head = [qd for qd in base if qd.get("kind") != "flags"]
    tail = [qd for qd in base if qd.get("kind") == "flags"]
    seen = {qd["id"] for qd in head}
    for qd in extras:
        if not isinstance(qd, dict) or not qd.get("question"):
            continue
        qid = qd.get("id") or ("q%d" % (len(head) + 1))
        if qid in seen:
            continue
        head.append(make_question(qid, qd["question"], qd.get("hint", ""),
                                  qd.get("options") or []))
        seen.add(qid)
    return head + tail


def assemble_idea_draft(state, include_empty=True):
    """Склеивает ответы мастера в связный черновик идеи.
    include_empty=True  — для черновика на экране: пустые ответы помечаются
                          «— не заполнено —», чтобы человек видел, что дописать.
    include_empty=False — для промпта: пустые ответы и неотмеченные галочки
                          в текст не попадают, чтобы не засорять контекст модели."""
    fields = state.stage("idea")["fields"]
    lines = ["Тема проекта: %s" % (state.data["theme"]["title"] or "не выбрана"),
             "Имя проекта: %s" % (state.name or "— не задано —"), ""]
    for qd in idea_questions(state):
        if qd.get("kind") == "flags":
            chosen = [label for key, label in qd["flags"] if state.data["flags"].get(key)]
            answer = ", ".join(chosen)
        else:
            answer = str(fields.get(qd["id"], "")).strip()
        if not answer:
            if include_empty:                       # режим «для экрана»
                lines.append("• %s" % qd["question"])
                lines.append("  " + ("— не отмечено —" if qd.get("kind") == "flags"
                                     else "— не заполнено —"))
            continue                                # режим «для промпта» — пропускаем
        lines.append("• %s" % qd["question"])
        lines.append("  " + answer.replace("\n", "\n  "))
    return "\n".join(lines)


# --- Описания этапов ---------------------------------------------------------
# goal — что человек заполняет; task — что просим у LLM;
# answer_sections — жёсткий формат ответа (чтобы его удобно класть в артефакт).
STAGE_SPECS = {
    "idea": {
        "goal": "Собрать ответы на наводящие вопросы и получить черновик идеи.",
        "task": "Помоги превратить сырые ответы в чёткую формулировку проекта. "
                "Не додумывай факты: чего не хватает — задай уточняющие вопросы.",
        "answer_sections": [
            "Краткое резюме идеи (3–5 строк)",
            "Уточняющие вопросы, если данных не хватает",
            "Предложение стека с обоснованием и пометками ТРЕБУЕТ ПРОВЕРКИ",
            "Риски и что проверить в первую очередь",
            "Следующий шаг: что заполняем на этапе «Паспорт»",
        ],
        "fields": [
            make_field("draft", "Черновик идеи (собирается из ответов, можно править)",
                       "text", "Нажмите «Собрать черновик» под вопросами или напишите сами.", 10),
            make_field("extra", "Что ещё важно знать о проекте", "text",
                       "Контекст, который не покрыт вопросами.", 4),
        ],
    },
    "charter": {
        "goal": "Зафиксировать цель, границы и критерии готовности проекта.",
        "task": "Собери паспорт проекта (PROJECT_CHARTER.md). Границы важнее хотелок: "
                "явно выпиши, чего в первой версии НЕ будет.",
        "answer_sections": [
            "PROJECT_CHARTER.md целиком (готовый текст файла)",
            "Критерии готовности — проверяемый список",
            "Инварианты списком",
            "Что вынесено за границы первой версии",
            "Открытые вопросы",
        ],
        "fields": [
            make_field("goal", "Цель: какой результат считаем успехом", "text",
                       "Одно-два предложения о результате, а не о процессе.", 4),
            make_field("scope_in", "Что входит в первую версию", "text", "", 4),
            make_field("scope_out", "Что НЕ делаем (границы)", "text",
                       "Самое полезное поле паспорта: защищает от расползания задачи.", 4),
            make_field("done_criteria", "Критерии готовности — как проверим", "text",
                       "Формулируйте так, чтобы можно было ответить «да/нет».", 5),
            make_field("invariants", "Инварианты — что не должно ломаться никогда", "text",
                       "Есть черновик темы — кнопка «Подставить черновик».", 5),
            make_field("constraints", "Ограничения: оффлайн, бюджет, время, права", "text", "", 3),
            make_field("data_policy", "Данные: источник, объём, история, приватность", "text", "", 3),
            make_field("licenses", "Внешнее ПО, лицензии, ключи", "text", "", 2),
            make_field("risks", "Риски и что с ними делаем", "text", "", 4),
            make_field("nfr", "Нефункциональные требования: скорость, надёжность, логи", "text", "", 3),
        ],
    },
    "arch": {
        "goal": "Разложить проект на модули и описать потоки данных и контракты.",
        "task": "Предложи архитектуру под паспорт проекта. Модули должны быть "
                "проверяемыми по отдельности, зависимости — минимальными.",
        "answer_sections": [
            "Модули: имя файла → ответственность",
            "Потоки данных: вход → шаги → выход",
            "Контракты: сигнатуры функций, форматы, коды ошибок",
            "Обработка ошибок и логирование",
            "Зависимости и обоснование каждой",
            "Схема текстом (ASCII), если картинки нет",
        ],
        "fields": [
            make_field("modules", "Модули и их ответственность", "text",
                       "Один модуль — одна задача. Пишите файл → что делает.", 6),
            make_field("data_flow", "Поток данных: вход → шаги → выход", "text", "", 5),
            make_field("contracts", "Интерфейсы и контракты", "text",
                       "Сигнатуры функций, поля форматов, что считаем ошибкой.", 5),
            make_field("formats", "Форматы файлов и структура данных", "text", "", 3),
            make_field("deps", "Зависимости и почему они нужны", "text",
                       "Есть черновик стека темы — кнопка «Подставить черновик».", 3),
            make_field("errors_logging", "Ошибки, логи, диагностика", "text", "", 4),
            make_field("config", "Конфигурация и секреты (.env)", "text", "", 3),
            make_field("diagram_note", "Что изображено на приложенной схеме", "line",
                       "Подпись к картинке — попадёт в отчёт и в промпт.", 1),
        ],
    },
    "skeleton": {
        "goal": "Получить дерево файлов и заготовки, которые можно сразу создать.",
        "task": "Собери скелет проекта: дерево файлов и минимальные заготовки. "
                "Каждый файл — целиком, путь в комментарии первой строкой.",
        "answer_sections": [
            "Дерево файлов проекта",
            "Содержимое заготовок: каждый файл целиком, путь в комментарии",
            "requirements.txt",
            "Как запустить и проверить (команды)",
            "Что оставить пустым и почему",
        ],
        "fields": [
            make_field("tree", "Дерево файлов первой версии", "text",
                       "Есть черновик структуры темы — кнопка «Подставить черновик».", 8),
            make_field("entrypoints", "Точки входа: что и чем запускаем", "text", "", 3),
            make_field("stubs", "Что должно быть в заготовках", "text",
                       "Например: только сигнатуры и docstring, без логики.", 5),
            make_field("requirements", "Зависимости для requirements.txt", "text",
                       "Пустой файл — тоже нормальный старт.", 3),
            make_field("run_how", "Как запускать и проверять", "text", "", 3),
            make_field("config_files", "Служебные файлы: .env.example, pytest.ini, .gitignore",
                       "text", "", 3),
        ],
    },
    "feature": {
        "goal": "Описать первую полезную функцию и критерии её приёмки.",
        "task": "Реализуй одну фичу целиком, с тестами. Не трогай то, что вне её "
                "границ; изменения по файлам давай явно.",
        "answer_sections": [
            "Постановка фичи и критерии приёмки",
            "Изменения по файлам (целиком или патчи с контекстом)",
            "Тест-кейсы: вход → ожидание",
            "Краевые случаи",
            "Как проверить вручную",
        ],
        "fields": [
            make_field("feature_name", "Название фичи", "line", "", 1),
            make_field("user_story", "Что делает фича для пользователя", "text",
                       "«Как <кто>, я хочу <что>, чтобы <зачем>».", 3),
            make_field("acceptance", "Критерии приёмки", "text", "Проверяемые «да/нет».", 4),
            make_field("io_example", "Пример входа и ожидаемого выхода", "text",
                       "Реальные строки/файлы лучше абстрактного описания.", 4),
            make_field("changes", "Какие файлы скелета меняем", "text", "", 4),
            make_field("tests", "Тест-кейсы", "text", "", 4),
            make_field("edge_cases", "Краевые случаи и что делать при ошибке", "text", "", 3),
        ],
    },
    "debug": {
        "goal": "Разобрать ошибку: воспроизведение, причина, фикс, регресс-тест.",
        "task": "Найди причину ошибки, а не симптом. Дай минимальный пример "
                "воспроизведения, исправление и тест, который поймает регресс в будущем.",
        "answer_sections": [
            "Диагноз: причина простыми словами",
            "Минимальный пример воспроизведения",
            "Исправление: файлы целиком",
            "Регресс-тест",
            "Что ещё может сломаться рядом",
        ],
        "fields": [
            make_field("symptom", "Симптом: что видим", "text", "", 3),
            make_field("reproduce", "Шаги воспроизведения", "text", "Нумерованный список.", 4),
            make_field("expected_actual", "Ожидание и факт", "text", "", 3),
            make_field("logs", "Логи и текст ошибки", "text", "Вставляйте как есть.", 5),
            make_field("hypotheses", "Гипотезы и что уже проверено", "text", "", 3),
            make_field("fix", "Что меняем (если уже понятно)", "text", "", 4),
            make_field("regression", "Как поймать это в будущем (регресс-тест)", "text", "", 3),
        ],
    },
    "summary": {
        "goal": "Собрать мастер-промпт и выгрузить всю конструкцию проекта.",
        "task": "Собери итоговую сводку: что построено, как запускать, что дальше.",
        "answer_sections": [
            "Сводка проекта",
            "Порядок работ по шагам",
            "Чек-лист приёмки",
            "Что осталось за границами",
        ],
        "fields": [
            make_field("final_notes", "Что дописать в мастер-промпт от себя", "text",
                       "Тон, ограничения, чего точно не делать.", 4),
            make_field("checklist", "Чек-лист готовности", "text", "", 5),
            make_field("next_steps", "Следующие шаги после первой версии", "text", "", 3),
        ],
    },
}

# Какие поля могут быть предзаполнены черновиком темы (по кнопке, не автоматически).
# На «Идее» стек — это вопрос мастера, отдельной кнопки там нет.
PRESET_HINT_MAP = {
    ("charter", "invariants"): "invariants",
    ("arch", "deps"): "stack",
    ("skeleton", "tree"): "structure",
    ("skeleton", "requirements"): "stack",
}


def fields_of(sid):
    """Список полей этапа (пустой список для неизвестного id — без исключений)."""
    return STAGE_SPECS.get(sid, {}).get("fields", [])


def stage_info(sid, key, default=""):
    """Безопасный доступ к описанию этапа: goal / task / answer_sections."""
    return STAGE_SPECS.get(sid, {}).get(key, default)


def preset_hint_for(state, sid, key):
    """Текст черновика темы для конкретного поля. Пустая строка = кнопки нет."""
    preset_key = PRESET_HINT_MAP.get((sid, key))
    if not preset_key:
        return ""
    return state.data["presets"].get(preset_key, "") or ""


# =============================================================================
# СЕКЦИЯ 5. ГЕНЕРАТОР ПРОМПТОВ (PromptBuilder)
# -----------------------------------------------------------------------------
# Собирает текст для внешней LLM: стандартная обвязка + контекст проекта +
# утверждённые предыдущие этапы + ответы текущего этапа + задача и формат ответа.
# Ничего не пишет на диск и не трогает состояние — только читает.
# =============================================================================
PROMPT_SEP = "=" * 78

FLAG_LABELS = {"git": "Git", "venv": "Виртуальное окружение .venv",
               "tests": "Тесты", "html_report": "HTML-отчёт"}

# Роль одинакова на всех этапах — чтобы модель не «переобувалась» между шагами.
ROLE_TEXT = (
    "Ты — опытный инженер-наставник по Python и автоматизации. "
    "Мы ведём проект пошагово: на каждом этапе ты решаешь ровно одну задачу и "
    "опираешься на то, что уже утверждено на предыдущих этапах. "
    "Пользователь копирует твой ответ обратно в лабораторию, поэтому ответ "
    "должен быть самодостаточным: без ссылок на «то, что мы обсуждали ранее»."
)

# Правила — общий контракт для всех этапов. Порядок важен: сначала запреты,
# потом требования к форме ответа.
RULES = [
    "Отвечай по-русски, по делу, без вводной воды и без пересказа задания.",
    "Не выдумывай факты о данных, окружении и доступных инструментах. "
    "Чего не хватает — задай уточняющие вопросы (не больше пяти, в конце ответа).",
    "Всё непроверенное помечай явно: ТРЕБУЕТ ПРОВЕРКИ. Это касается команд, "
    "флагов, версий, наличия библиотек и лицензий.",
    "Код давай целыми файлами. Первая строка файла — комментарий с его путём "
    "от корня проекта.",
    "Комментарии обязательны: каждая функция и каждый нетривиальный блок — "
    "что делает и зачем. Код должен читаться как инструкция.",
    "Только стандартная библиотека Python, пока иное не согласовано явно. "
    "Нужна внешняя — сначала обоснуй и спроси, не ставь её молча.",
    "Кроссплатформенность: пути через os.path, без shell-магии и без «зашитых» "
    "дисков. Внешние команды — списком аргументов, без shell=True.",
    "Никогда не предлагай молча перезаписать файлы пользователя: предупреждай "
    "и показывай, что именно изменится.",
    "Отсутствие инструмента или прав — не повод падать: дай понятную инструкцию "
    "человеку и безопасный выход.",
    "Не расширяй границы этапа. Делай только то, о чём просят сейчас; "
    "идеи на будущее выноси в раздел «следующий шаг».",
    "Формат ответа — строго по секциям из задания. Не меняй их порядок и названия.",
]

# Что просим в конце каждого ответа — одинаковый «хвост» для всех этапов.
FOOTER_LINES = [
    "Список файлов, которые нужно создать или изменить (пути от корня проекта).",
    "Команды для проверки — только проверенные; сомнительные помечай ТРЕБУЕТ ПРОВЕРКИ.",
    "Риски: что может сломаться и как это заметить.",
    "Один следующий шаг: что делаем дальше.",
    "Уточняющие вопросы, если данных не хватает (не больше пяти).",
]


def numbered(items):
    """Список строк → нумерованный текст (для правил и секций формата)."""
    return "\n".join(str(i) + ". " + str(text) for i, text in enumerate(items, start=1))


def bullets(items):
    """Список строк → маркированный текст."""
    return "\n".join("- " + str(text) for text in items)


def render_fields(sid, fields, skip=(), include_unknown=True, skip_empty=False):
    """Поля этапа → читаемый текст «подпись → ответ».
    Пустые помечаются явно: модель должна спросить, а не додумать.
    include_unknown=False — сырые неизвестные ключи в вывод не берём.
    skip_empty=True — пустые поля вообще не попадают в вывод."""
    fields = fields or {}
    specs = fields_of(sid)
    lines = []
    for f in specs:
        if f["key"] in skip:
            continue
        value = fields.get(f["key"], "")
        if isinstance(value, list):
            value = ", ".join(str(v) for v in value)
        value = str(value).strip()
        if not value and skip_empty:
            continue                       # пустое поле в промпт не берём
        shown = value.replace("\n", "\n  ") if value else "— не заполнено —"
        lines.append("• " + f["label"] + "\n  " + shown)
    if include_unknown:
        known = {f["key"] for f in specs}
        for key, value in fields.items():
            if key in known or key in skip:
                continue
            text = str(value).strip()
            if text:
                lines.append("• " + key + "\n  " + text.replace("\n", "\n  "))
    return "\n".join(lines)


def strip_idea_placeholders(text):
    """Убирает из черновика строки-заполнители («— не заполнено —», «— не отмечено —»)
    и заголовки вопросов, под которыми нет реального ответа."""
    lines = (text or "").split("\n")
    placeholders = ("— не заполнено —", "— не отмечено —")
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.strip().startswith("• "):
            # Собираем строки ответа до следующего заголовка «• ».
            j = i + 1
            answer = []
            while j < len(lines) and not lines[j].strip().startswith("• "):
                answer.append(lines[j])
                j += 1
            real = [a for a in answer if a.strip() and a.strip() not in placeholders]
            if real:                       # есть реальный ответ — оставляем блок
                out.append(line)
                out.extend(real)
            i = j                          # пустой блок — пропускаем целиком
        else:
            if line.strip() not in placeholders:
                out.append(line)
            i += 1
    return "\n".join(out)


def prompt_stats(text):
    """Размер промпта — чтобы человек понимал, влезет ли он в окно модели."""
    text = text or ""
    return {"chars": len(text),
            "lines": (text.count("\n") + 1) if text else 0,
            "words": len(text.split())}


def stats_line(text):
    """Короткая строка для интерфейса под полем промпта."""
    s = prompt_stats(text)
    return "символов: %d | строк: %d | слов: %d" % (s["chars"], s["lines"], s["words"])


class PromptBuilder:
    """Собирает промпты этапов и мастер-промпт из состояния проекта."""

    def __init__(self, state):
        self.state = state

    # --- служебное -----------------------------------------------------------
    def context_limit(self):
        """Лимит символов на один этап в контексте. Значение из настроек,
        с защитой от мусора (пользователь может ввести что угодно)."""
        raw = self.state.data["settings"].get("context_limit", LIMITS["context_chars"])
        try:
            value = int(raw)
        except (TypeError, ValueError):
            value = LIMITS["context_chars"]
        return max(LIMITS["context_min"], value)

    def flags_line(self):
        """Отмеченные пользователем инструменты. «не отмечено» ≠ «не нужно»:
        мы честно передаём, что человек просто не поставил галочку."""
        flags = self.state.data["flags"]
        return "; ".join(label + " — " + ("да" if flags.get(key) else "не отмечено")
                         for key, label in FLAG_LABELS.items())

    def missing_previous(self, sid):
        """Названия предыдущих рабочих этапов, которые ещё не утверждены."""
        if sid not in STAGE_IDS:
            return []
        cut = STAGE_IDS.index(sid)
        return [s["title"] for s in self.state.data["stages"][:cut]
                if s["id"] in WORK_STAGE_IDS and s["status"] != "approved"]

    def context_summary(self, sid):
        """Строка для шапки вкладки: что попадёт в контекст."""
        approved = self.state.approved_before(sid)
        if not approved:
            return "пока пусто — это первый содержательный этап."
        return ", ".join(s["title"] for s in approved)

    # --- блоки промпта -------------------------------------------------------
    def project_block(self):
        """Постоянный контекст проекта: кто, где, на чём, с какими черновиками."""
        st = self.state
        presets = st.data["presets"]
        lim = self.context_limit()
        done, total = st.progress()
        lines = [
            "- Имя проекта: " + (st.name or "— не задано —"),
            "- Тема: " + (st.data["theme"]["title"] or "— не выбрана —"),
            "- Папка проекта: " + (st.folder or "— не выбрана —"),
            "- ОС пользователя: " + platform_name(),
            "- Python лаборатории: " + sys.version.split()[0],
            "- Инструменты: " + self.flags_line(),
            "- Прогресс: утверждено " + str(done) + " из " + str(total) + " рабочих этапов",
        ]
        # Черновики темы передаём именно как черновики — с шапкой-дисклеймером.
        for key, title in (("stack", "Черновик стека (предложение, не решение)"),
                           ("invariants", "Черновик инвариантов"),
                           ("structure", "Черновик структуры папок")):
            text = (presets.get(key) or "").strip()
            if text:
                lines += ["", title + ":", shorten(text, lim)]
        return "\n".join(lines)

    def previous_block(self, sid):
        """Утверждённые предыдущие этапы. Неутверждённые не подмешиваем,
        но честно перечисляем — чтобы модель знала о дырах и не заполняла их сама."""
        approved = self.state.approved_before(sid)
        lim = self.context_limit()
        if not approved:
            text = ("Пока ничего не утверждено. Опирайся только на ответы текущего этапа "
                    "и контекст проекта.")
        else:
            chunks = []
            for s in approved:
                body = (s["llm_result"] or "").strip()
                if not body:
                    # Результата LLM нет, но этап утверждён по полям — берём поля.
                    body = render_fields(s["id"], s["fields"]) or "— содержимое пустое —"
                chunks.append("### Этап " + str(s["num"]) + " «" + s["title"] + "» "
                              + "(утверждён " + (s["approved_at"] or "время не указано") + ")\n"
                              + shorten(body, lim))
            text = "\n\n".join(chunks)
        missing = self.missing_previous(sid)
        if missing:
            text += ("\n\nВНИМАНИЕ: предыдущие этапы не утверждены: " + ", ".join(missing)
                     + ". Их содержимого в контексте нет — не додумывай его. "
                       "Если данных не хватает, задай вопросы.")
        return text

    def answers_block(self, sid):
        """Ответы текущего этапа. Для «Идеи» в промпт попадают ТОЛЬКО заполненные
        ответы: пустые вопросы, неотмеченные галочки и пустые поля не включаются."""
        st = self.state.stage(sid)
        if st is None:
            return "— этап неизвестен —"
        lim = self.context_limit()
        parts = []
        if sid == "idea":
            # Заполненные ответы наводящих вопросов (пустые пропускаем).
            filled = assemble_idea_draft(self.state, include_empty=False)
            parts += ["Ответы наводящих вопросов (только заполненные):",
                      shorten(filled, lim * 2)]
            # Свободный черновик: добавляем, только если он не равен авто-сборке
            # (иначе дублирует ответы) и не состоит из одних заполнителей.
            draft_raw = (st["fields"].get("draft") or "").strip()
            auto = assemble_idea_draft(self.state, include_empty=True).strip()
            if draft_raw and draft_raw != auto:
                cleaned = strip_idea_placeholders(draft_raw).strip()
                if cleaned:
                    parts += ["Черновик идеи (текст пользователя):", shorten(cleaned, lim)]
            # Поле «Что ещё важно знать» — только если заполнено.
            extra = str(st["fields"].get("extra", "")).strip()
            if extra:
                parts += ["Что ещё важно знать о проекте:", extra]
            rendered = ""          # поля «Идеи» уже разобраны выше
        else:
            rendered = render_fields(sid, st["fields"])
        if rendered:
            parts += ["Поля этапа:", rendered]
        if not parts:
            parts = ["— поля не заполнены. Задай уточняющие вопросы и не выдумывай ответы. —"]
        return "\n\n".join(parts)

    def images_block(self, sid):
        """Список приложенных картинок. Сам промпт — текст, файлы человек
        прикладывает к сообщению вручную; модель должна об этом знать."""
        st = self.state.stage(sid)
        images = st["images"] if st else []
        if not images:
            return "Картинок к этапу не приложено."
        lines = ["К этапу приложены файлы (пользователь прикладывает их к сообщению вручную):"]
        lines += ["- " + rel for rel in images]
        lines.append("Если файлы не приложены — скажи об этом и работай по текстовому описанию, "
                     "не описывай картинку, которой не видишь.")
        return "\n".join(lines)

    def task_block(self, sid):
        """Задача этапа + жёсткий список секций ответа."""
        info = STAGE_SPECS.get(sid, {})
        task = info.get("task") or ("Помоги с этапом «" + STAGE_TITLES.get(sid, sid) + "».")
        lines = [task]
        sections = info.get("answer_sections") or []
        if sections:
            lines += ["", "Ответ дай строго по секциям, с этими же заголовками:",
                      numbered(sections)]
        return "\n".join(lines)

    # --- сборка --------------------------------------------------------------
    def build_stage_prompt(self, sid):
        """Главная функция блока: полный промпт одного этапа.
        Для «Итога» возвращает мастер-промпт — там другая задача."""
        if sid == "summary":
            return self.build_master_prompt()
        title = STAGE_TITLES.get(sid, sid)
        num = STAGE_NUM.get(sid, 0)
        head = [
            PROMPT_SEP,
            "ЛАБОРАТОРИЯ ПРОЕКТА — ПРОМПТ ЭТАПА " + str(num) + "/7: " + title.upper(),
            "Проект: " + (self.state.name or "без имени")
            + " | Тема: " + (self.state.data["theme"]["title"] or "не выбрана"),
            "Собран: " + now_human() + " | Лаборатория версии " + APP_VERSION,
            PROMPT_SEP,
            "",
        ]
        blocks = [
            ("1. РОЛЬ", ROLE_TEXT),
            ("2. ПРАВИЛА РАБОТЫ", numbered(RULES)),
            ("3. КОНТЕКСТ ПРОЕКТА", self.project_block()),
            ("4. ЧТО УЖЕ УТВЕРЖДЕНО (контекст предыдущих этапов)", self.previous_block(sid)),
            ("5. ОТВЕТЫ ТЕКУЩЕГО ЭТАПА", self.answers_block(sid)),
            ("6. КАРТИНКИ ЭТАПА", self.images_block(sid)),
            ("7. ЗАДАЧА И ФОРМАТ ОТВЕТА", self.task_block(sid)),
            ("8. ЧТО ВЕРНУТЬ В КОНЦЕ", bullets(FOOTER_LINES)),
        ]
        body = []
        for name, text in blocks:
            body += ["## " + name, (text or "").strip(), ""]
        return "\n".join(head + body).rstrip() + "\n"

    def build_master_prompt(self):
        """Сводный промпт по всему проекту: обвязка + оглавление + все
        утверждённые этапы + честный список пробелов + пожелания к итогу."""
        st = self.state
        lim = self.context_limit()
        done, total = st.progress()
        head = [
            PROMPT_SEP,
            "ЛАБОРАТОРИЯ ПРОЕКТА — МАСТЕР-ПРОМПТ ПРОЕКТА",
            "Проект: " + (st.name or "без имени")
            + " | Тема: " + (st.data["theme"]["title"] or "не выбрана"),
            "Собран: " + now_human() + " | Утверждено этапов: " + str(done) + "/" + str(total),
            PROMPT_SEP,
            "",
        ]
        # Оглавление: видно, что утверждено, а что осталось черновиком.
        status_ru = {"approved": "утверждён", "draft": "черновик", "empty": "пусто"}
        toc = ["Состав проекта по этапам:"]
        for s in st.data["stages"]:
            if s["id"] == "summary":
                continue
            toc.append("- Этап " + str(s["num"]) + " «" + s["title"] + "» — "
                       + status_ru.get(s["status"], s["status"]))

        # Тело: утверждённые этапы целиком (в пределах лимита), с полями и ответом.
        approved_chunks = []
        truncated = False
        for s in st.data["stages"]:
            if s["id"] not in WORK_STAGE_IDS or s["status"] != "approved":
                continue
            fields_text = render_fields(s["id"], s["fields"])
            result_text = (s["llm_result"] or "").strip()
            chunk = ["### Этап " + str(s["num"]) + " «" + s["title"] + "» "
                     + "(утверждён " + (s["approved_at"] or "время не указано") + ")"]
            if fields_text:
                chunk += ["Исходные ответы пользователя:", shorten(fields_text, lim)]
                truncated = truncated or len(fields_text) > lim
            if result_text:
                chunk += ["Утверждённый результат:", shorten(result_text, lim)]
                truncated = truncated or len(result_text) > lim
            if s["images"]:
                chunk += ["Приложенные файлы: " + ", ".join(s["images"])]
            approved_chunks.append("\n\n".join(chunk))
        if not approved_chunks:
            approved_chunks = ["Ни один этап пока не утверждён. "
                               "Начни с уточняющих вопросов и плана работ, "
                               "не проектируй проект на пустом месте."]

        # Пробелы: неутверждённые этапы перечисляем, содержимое не подставляем.
        gaps = [s["title"] for s in st.data["stages"]
                if s["id"] in WORK_STAGE_IDS and s["status"] != "approved"]
        gaps_text = ("Не утверждены: " + ", ".join(gaps)
                     + ". Содержимого этих этапов нет — не выдумывай его, "
                       "вынеси в открытые вопросы.") if gaps else "Все рабочие этапы утверждены."
        summary_fields = render_fields("summary", st.stage("summary")["fields"])
        all_images = []
        for s in st.data["stages"]:
            all_images += list(s["images"])
        images_text = bullets(all_images) if all_images else "Картинок нет."
        task = (STAGE_SPECS.get("summary", {}).get("task", "")
                + " Собери проект воедино по утверждённым этапам: не противоречь им, "
                  "не переделывай утверждённые решения без явной причины. "
                  "Если между этапами есть противоречие — назови его и предложи, "
                  "какое решение считать главным.")
        sections = STAGE_SPECS.get("summary", {}).get("answer_sections") or []
        blocks = [
            ("1. РОЛЬ", ROLE_TEXT),
            ("2. ПРАВИЛА РАБОТЫ", numbered(RULES)),
            ("3. КОНТЕКСТ ПРОЕКТА", self.project_block()),
            ("4. СОСТАВ И СОСТОЯНИЕ ЭТАПОВ", "\n".join(toc)),
            ("5. УТВЕРЖДЁННЫЕ ЭТАПЫ (главный источник истины)", "\n\n".join(approved_chunks)),
            ("6. ПРОБЕЛЫ", gaps_text),
            ("7. ПОЖЕЛАНИЯ К ИТОГУ", summary_fields or "— не заполнены —"),
            ("8. ЗАДАЧА И ФОРМАТ ОТВЕТА",
             task + "\n\nОтвет дай строго по секциям:\n" + numbered(sections)),
            ("9. ПРИЛОЖЕННЫЕ ФАЙЛЫ", images_text),
            ("10. ЧТО ВЕРНУТЬ В КОНЦЕ", bullets(FOOTER_LINES)),
        ]
        body = []
        for name, text in blocks:
            body += ["## " + name, (text or "").strip(), ""]
        if truncated:
            body += ["Примечание: длинные результаты обрезаны по " + str(lim)
                     + " символов на этап. Полные версии лежат в artifacts/ проекта.", ""]
        return "\n".join(head + body).rstrip() + "\n"

    def build_all(self):
        """Свежие промпты всех этапов. Состояние не меняем."""
        return {sid: self.build_stage_prompt(sid) for sid in STAGE_IDS}


# =============================================================================
# СЕКЦИЯ 6. ДЕЙСТВИЯ НА ДИСКЕ (CommandRunner + Scaffolder)
# -----------------------------------------------------------------------------
# CommandRunner — единая точка запуска внешних программ: логирует команду,
# вывод и статус, ловит отсутствие инструмента/прав/таймаут.
# Scaffolder — прикладные действия: структура, .venv, зависимости, git, проверка.
#
# ВАЖНО ПРО ПОТОКИ:
#   create_structure / ensure_gitignore / write_user_file — задают вопросы,
#       поэтому вызываются ТОЛЬКО из UI-потока;
#   create_venv / install_deps / git_init_commit / check_env — без диалогов,
#       их можно запускать в фоновом потоке (см. TaskRunner в секции 9).
# =============================================================================
LOG_OUTPUT_LIMIT = 20000        # столько символов вывода команды пишем в лог за раз
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".svg", ".webp")


def tool_hint(name):
    """Человеческая инструкция, когда инструмента нет. Ничего не запускаем сами."""
    low = (name or "").lower()
    osname = platform_name()
    if "git" in low:
        return "\n".join([
            "Как поставить Git:",
            "  Windows: установщик с git-scm.com (при установке оставьте «Git from PATH»).",
            "  macOS:   xcode-select --install   либо   brew install git",
            "  Debian/Ubuntu: sudo apt install git",
            "  Fedora: sudo dnf install git",
            "После установки перезапустите лабораторию, чтобы обновился PATH."])
    if "pip" in low:
        return "\n".join(["Похоже, в окружении нет pip. Проверенные способы:",
                          "  " + sys.executable + " -m ensurepip --upgrade",
                          "  затем пересоздайте окружение кнопкой «Создать окружение».",
                          "Если сеть закрыта — ставьте пакеты из локального кэша/зеркала."])
    if "venv" in low:
        return "\n".join(["Модуль venv недоступен или отключён в сборке python.",
                          "  Debian/Ubuntu: sudo apt install python3-venv",
                          "  Fedora: sudo dnf install python3-virtualenv  (ТРЕБУЕТ ПРОВЕРКИ)",
                          "  Windows/macOS: используйте python с python.org."])
    if "python" in low:
        return ("Python не найден по указанному пути. Проверьте, что окружение .venv "
                "создано и не удалено вручную.")
    if "xdg-open" in low:
        return "Откройте папку вручную средствами файлового менеджера (" + osname + ")."
    return ""


def venv_python_in(folder):
    """Путь к python внутри .venv с учётом платформы (Windows: Scripts, POSIX: bin)."""
    if not folder:
        return ""
    if is_windows():
        return os.path.join(folder, ".venv", "Scripts", "python.exe")
    return os.path.join(folder, ".venv", "bin", "python")


class CommandResult:
    """Результат одной команды: то, что показываем в логе и в отчёте об окружении."""

    def __init__(self, args, cwd=""):
        self.args = list(args)
        self.cwd = cwd
        self.code = None        # None = команда вообще не запустилась
        self.stdout = ""
        self.stderr = ""
        self.seconds = 0.0
        self.error = ""         # текст нашей ошибки (нет файла, нет прав, таймаут)

    @property
    def ok(self):
        """Успех = процесс запустился и вернул нулевой код."""
        return self.code == 0 and not self.error

    def status_text(self):
        if self.error:
            return "НЕ ЗАПУЩЕНО: " + self.error
        if self.code == 0:
            return "OK (код 0, " + ("%.1f" % self.seconds) + " с)"
        return "ОШИБКА (код " + str(self.code) + ")"

    def combined(self):
        """Вывод и ошибки одной строкой — для отчёта."""
        return ((self.stdout or "") + ("\n" + self.stderr if self.stderr else "")).strip()


class CommandRunner:
    """Единая точка запуска внешних команд. Всегда списком, всегда без shell."""

    def __init__(self, cwd=""):
        self.cwd = cwd

    def run(self, args, cwd=None, timeout=None, show_output=True):
        """Запускает команду, пишет в лог команду/вывод/статус, возвращает CommandResult.
        Любая проблема окружения превращается в текст, а не в исключение наверх."""
        args = [str(a) for a in args]
        cwd = cwd or self.cwd or os.getcwd()
        timeout = timeout or LIMITS["timeout_cmd"]
        res = CommandResult(args, cwd)
        log("$ " + fmt_cmd(args) + "   [папка: " + cwd + "]", "cmd")
        if not os.path.isdir(cwd):
            res.error = "Рабочая папка не существует: " + cwd
            log(res.error, "err")
            return res
        kwargs = {"cwd": cwd, "capture_output": True, "text": True,
                  "encoding": "utf-8", "errors": "replace", "timeout": timeout}
        # На Windows прячем мелькающее окно консоли. Константа есть только там.
        if is_windows() and hasattr(subprocess, "CREATE_NO_WINDOW"):
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        started = datetime.now()
        try:
            proc = subprocess.run(args, **kwargs)
            res.code = proc.returncode
            res.stdout = proc.stdout or ""
            res.stderr = proc.stderr or ""
        except FileNotFoundError:
            res.error = "Программа не найдена: " + args[0]
        except PermissionError as e:
            res.error = "Нет прав на запуск: " + str(e)
        except subprocess.TimeoutExpired:
            res.error = "Не успела за " + str(timeout) + " с — остановлена."
        except OSError as e:
            res.error = "Ошибка запуска: " + str(e)
        res.seconds = (datetime.now() - started).total_seconds()
        if show_output:
            out = (res.stdout or "").strip()
            err = (res.stderr or "").strip()
            if out:
                log(shorten(out, LOG_OUTPUT_LIMIT), "raw")
            if err:
                log(shorten(err, LOG_OUTPUT_LIMIT), "raw")
        if res.error:
            log(res.error, "err")
            hint = tool_hint(os.path.basename(args[0]))
            if hint:
                log(hint, "info")
        elif res.ok:
            log("Готово: " + res.status_text(), "ok")
        else:
            log("Команда завершилась с ошибкой: " + res.status_text(), "err")
        return res


class Scaffolder:
    """Прикладные действия в папке проекта.
    confirm(title, text) -> bool         — вопрос «да/нет» (подставляет интерфейс);
    ask_conflict(rel, old, new) -> str   — ответ 'skip' | 'overwrite' | 'copy'.
    Без этих функций действуют безопасные значения по умолчанию."""

    def __init__(self, state, confirm=None, ask_conflict=None):
        self.state = state
        self.confirm = confirm or (lambda title, text: False)
        self.ask_conflict = ask_conflict or (lambda rel, old, new: "skip")
        self.runner = CommandRunner()

    # --- базовое -------------------------------------------------------------
    def folder_ready(self):
        """Все действия разрешены только внутри выбранной папки."""
        if not self.state.folder:
            log("Сначала выберите папку проекта на вкладке «Старт».", "warn")
            return False
        return True

    def project_path(self, rel):
        """Абсолютный путь внутри проекта. Выход наружу («..», абсолютный путь) запрещён."""
        folder = self.state.folder
        if not folder:
            raise ValueError("Папка проекта не выбрана")
        path = os.path.abspath(os.path.join(folder, rel))
        if not is_inside(path, folder):
            raise ValueError("Путь вне проекта запрещён: " + str(rel))
        return path

    def venv_python(self):
        """Путь к python окружения текущего проекта."""
        return venv_python_in(self.state.folder)

    def extra_dirs_from_presets(self):
        """Читает черновик структуры: строки вида path/ = дополнительные папки.
        Комментарии и базовые папки игнорируем, опасные пути отбрасываем."""
        text = self.state.data["presets"].get("structure") or ""
        out = []
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or not line.endswith("/"):
                continue
            rel = line.rstrip("/").replace("\\", "/")
            parts = [p for p in rel.split("/") if p]
            if rel.startswith("/") or ":" in rel or ".." in parts:
                continue
            rel = "/".join(sanitize_name(p) for p in parts)
            if rel and rel not in BASE_DIRS and rel not in out:
                out.append(rel)
        return out

    def write_user_file(self, rel, text):
        """Пишет файл пользователя, НИКОГДА не перезаписывая молча.
        Возвращает: created | overwritten | same | skipped | copy."""
        path = self.project_path(rel)
        if not os.path.exists(path):
            atomic_write(path, text)
            log("Создан файл: " + rel, "ok")
            return "created"
        old = read_text(path, "")
        if old == text:
            log("Файл уже актуален, не трогаем: " + rel, "info")
            return "same"
        choice = self.ask_conflict(rel, old, text)
        if choice == "overwrite":
            atomic_write(path, text)
            log("Перезаписан по вашему выбору: " + rel, "warn")
            return "overwritten"
        if choice == "copy":
            newpath = path + ".new"
            i = 1
            while os.path.exists(newpath):          # не затираем и прошлые .new
                newpath = path + ".new" + str(i)
                i += 1
            atomic_write(newpath, text)
            log("Ваш файл оставлен, заготовка сохранена рядом: "
                + os.path.basename(newpath), "ok")
            return "copy"
        log("Пропущен, оставлен ваш файл: " + rel, "warn")
        return "skipped"

    # --- шаблоны файлов ------------------------------------------------------
    def file_templates(self):
        """Содержимое стартовых файлов. Это КАРКАС с заголовками и подсказками,
        а не выдуманный проект: содержательные разделы оставлены пустыми."""
        name = self.state.name or "Новый проект"
        theme = self.state.data["theme"]["title"] or "не выбрана"
        stamp = now_human()
        head = "<!-- Каркас создан «Лабораторией проекта» " + APP_VERSION + " (" + stamp + "). -->"
        readme = "\n".join([
            "# " + name, "", head, "",
            "Тема: " + theme, "",
            "## Что это",
            "<!-- Одно предложение: что делает проект. Заполните после этапа «Идея». -->", "",
            "## Как запустить",
            "<!-- Замените на реальные команды после этапа «Скелет». Каркас: -->", "",
            "```",
            "python -m venv .venv",
            "# Windows: .venv\\Scripts\\python.exe -m pip install -r requirements.txt",
            "# Linux/macOS: .venv/bin/python -m pip install -r requirements.txt",
            "```", "",
            "## Структура",
            "- src/ — код, tests/ — тесты, features/ — описания фич",
            "- docs/ — документы, data/ — данные (не в git), out/ — результаты (не в git)",
            "- prompts/ — промпты этапов, artifacts/ — утверждённые ответы LLM",
            "- images/ — схемы и скриншоты, history/ — снапшоты состояния", "",
            "## Отчёт по проекту",
            "report.html — вся конструкция этапов; pipeline.svg — схема прогресса.", "",
        ])
        agents = "\n".join([
            "# AGENTS.md — правила для ИИ-агентов в этом репозитории", "", head, "",
            "1. Только стандартная библиотека Python, пока иное не согласовано явно.",
            "2. Комментарии обязательны: каждая функция и нетривиальный блок — что делает и зачем.",
            "3. Код — целыми файлами, первая строка — комментарий с путём файла.",
            "4. Непроверенное помечать ТРЕБУЕТ ПРОВЕРКИ (команды, флаги, версии, лицензии).",
            "5. Не перезаписывать файлы пользователя молча: предупреждать и показывать изменения.",
            "6. Кроссплатформенность: os.path, без shell=True, без «зашитых» дисков.",
            "7. Не выходить за границы текущей задачи; идеи на будущее — в конец ответа.",
            "8. Секреты — только в .env (файл в git не попадает), в коде — ссылки на переменные.", "",
            "## Где что лежит",
            "- prompts/ — промпты этапов, artifacts/ — утверждённые результаты",
            "- PROJECT_CHARTER.md — цель и границы проекта",
            "- history/ — снапшоты состояния лаборатории", "",
        ])
        claude = "\n".join([
            "# CLAUDE.md — то же соглашение, отдельным файлом", "", head, "",
            "См. AGENTS.md — правила одинаковые для всех ассистентов.", "",
            "Порядок работы: Идея → Паспорт → Архитектура → Скелет → Фича → Отладка → Итог.",
            "Контекст берём из prompts/ и artifacts/, а не додумываем.", "",
            "Проверка перед сдачей:",
            "- [ ] код запускается на чистой машине по README",
            "- [ ] есть комментарии и понятные имена",
            "- [ ] ошибки окружения не роняют программу",
            "- [ ] файлы пользователя не перезаписаны молча", "",
        ])
        charter = "\n".join([
            "# Паспорт проекта: " + name, "", head, "",
            "Тема: " + theme, "",
            "## Цель",
            "<!-- Заполняется на этапе «Паспорт». -->", "",
            "## Границы: что входит", "", "## Границы: что НЕ делаем", "",
            "## Критерии готовности", "", "## Инварианты", "",
            "## Ограничения (оффлайн, бюджет, время, права)", "",
            "## Данные: источник, объём, история, приватность", "",
            "## Внешнее ПО, лицензии, ключи", "", "## Риски", "",
        ])
        requirements = "\n".join([
            "# Зависимости проекта. Пусто — нормальный старт на стандартной библиотеке.",
            "# Добавляйте по одной строке с обоснованием в комментарии, например:",
            "# openpyxl  # чтение xlsx (внешняя библиотека, согласована на этапе «Скелет»)",
            "",
        ])
        env_example = "\n".join([
            "# Пример переменных окружения. Скопируйте в .env и заполните.",
            "# Настоящий .env в git не попадает (см. .gitignore).",
            "API_URL=",
            "API_KEY=",
            "LOG_LEVEL=INFO",
            "",
        ])
        pytest_ini = "\n".join([
            "[pytest]",
            "testpaths = tests",
            "python_files = test_*.py",
            "addopts = -q",
            "",
        ])
        return {"README.md": readme, "AGENTS.md": agents, "CLAUDE.md": claude,
                "PROJECT_CHARTER.md": charter, "requirements.txt": requirements,
                ".gitignore": GITIGNORE_TEXT, ".env.example": env_example,
                "pytest.ini": pytest_ini}

    # --- действие 1: структура (UI-поток) ------------------------------------
    def create_structure(self, with_extra=True):
        """Создаёт папки и стартовые файлы. В непустой папке — сначала подтверждение."""
        if not self.folder_ready():
            return None
        folder = self.state.folder
        ensure_dir(folder)
        entries = sorted(os.listdir(folder))
        if entries:
            preview = "\n".join("  • " + e for e in entries[:15])
            more = ("\n  … и ещё " + str(len(entries) - 15)) if len(entries) > 15 else ""
            if not self.confirm("Папка не пустая",
                                "В папке уже есть объекты (" + str(len(entries)) + "):\n"
                                + preview + more
                                + "\n\nСуществующие файлы не будут перезаписаны молча — "
                                  "по каждому будет отдельный вопрос.\nПродолжить?"):
                log("Создание структуры отменено: папка не пустая.", "warn")
                return None
        stats = {"dirs": 0, "created": [], "overwritten": [], "same": [],
                 "skipped": [], "copies": []}
        for d in BASE_DIRS:
            path = self.project_path(d)
            if not os.path.isdir(path):
                os.makedirs(path, exist_ok=True)
                stats["dirs"] += 1
        extra = self.extra_dirs_from_presets() if with_extra else []
        if extra and self.confirm("Дополнительные папки темы",
                                  "Создать также папки из черновика структуры?\n\n"
                                  + "\n".join("  " + d + "/" for d in extra)):
            for d in extra:
                path = self.project_path(d)
                if not os.path.isdir(path):
                    os.makedirs(path, exist_ok=True)
                    stats["dirs"] += 1
        for rel, text in self.file_templates().items():
            result = self.write_user_file(rel, text)
            key = {"created": "created", "overwritten": "overwritten", "same": "same",
                   "skipped": "skipped", "copy": "copies"}[result]
            stats[key].append(rel)
        log("Структура готова: новых папок " + str(stats["dirs"])
            + ", создано файлов " + str(len(stats["created"]))
            + ", перезаписано " + str(len(stats["overwritten"]))
            + ", пропущено " + str(len(stats["skipped"]))
            + ", копий рядом " + str(len(stats["copies"])), "ok")
        return stats

    # --- действие 2: окружение (можно в фоне) --------------------------------
    def create_venv(self, force=False):
        """python -m venv .venv тем же интерпретатором, которым запущена лаборатория.
        force=True добавляет --clear: это именно пересоздание, а не обновление."""
        if not self.folder_ready():
            return False
        ensure_dir(self.state.folder)
        py = self.venv_python()
        exists = os.path.exists(py)
        if exists and not force:
            log("Окружение .venv уже есть. Пересоздание — только после подтверждения.", "warn")
            return False
        args = [sys.executable, "-m", "venv"]
        if exists and force:
            args.append("--clear")
            log("Пересоздание окружения: старые пакеты в .venv будут удалены.", "warn")
        args.append(".venv")
        res = self.runner.run(args, cwd=self.state.folder, timeout=LIMITS["timeout_venv"])
        if not res.ok:
            log("Не удалось создать окружение.", "err")
            log(tool_hint("venv"), "info")
            return False
        if not os.path.exists(py):
            log("Команда прошла, но python окружения не найден: " + py, "warn")
            return False
        log("Окружение готово: " + py, "ok")
        return True

    # --- действие 3: зависимости (можно в фоне) ------------------------------
    def install_deps(self):
        """.venv/python -m pip install -r requirements.txt (путь зависит от ОС)."""
        if not self.folder_ready():
            return False
        py = self.venv_python()
        if not os.path.exists(py):
            log("Нет окружения .venv — сначала нажмите «Создать окружение».", "err")
            return False
        req = self.project_path("requirements.txt")
        if not os.path.isfile(req):
            log("Нет requirements.txt — сначала «Создать структуру».", "err")
            return False
        meaningful = [ln.strip() for ln in read_text(req, "").splitlines()
                      if ln.strip() and not ln.strip().startswith("#")]
        if not meaningful:
            log("requirements.txt пуст (только комментарии) — ставить нечего. "
                "Это нормальный старт на стандартной библиотеке.", "ok")
            return True
        res = self.runner.run([py, "-m", "pip", "install", "-r", "requirements.txt"],
                              cwd=self.state.folder, timeout=LIMITS["timeout_pip"])
        if not res.ok:
            log("Установка не удалась. Проверьте сеть, имена пакетов и права.", "err")
            log(tool_hint("pip"), "info")
        return res.ok

    # --- действие 4: git ------------------------------------------------------
    def ensure_gitignore(self):
        """UI-поток: создаёт .gitignore или предлагает дописать недостающие строки.
        Сравниваем построчно: подстрока 'out/' нашлась бы внутри 'layout/'."""
        if not self.folder_ready():
            return False
        path = self.project_path(".gitignore")
        if not os.path.exists(path):
            atomic_write(path, GITIGNORE_TEXT)
            log("Создан .gitignore", "ok")
            return True
        current = read_text(path, "")
        have = {ln.strip() for ln in current.splitlines()}
        required = [".venv/", "__pycache__/", "out/", "data/", "*.env"]
        missing = [p for p in required if p not in have]
        if not missing:
            log(".gitignore уже содержит нужные исключения.", "info")
            return True
        if self.confirm(".gitignore неполный",
                        "В вашем .gitignore нет строк:\n  " + "\n  ".join(missing)
                        + "\n\nДописать их в конец файла? Существующие строки не меняются."):
            new = (current.rstrip("\n") + "\n\n# --- добавлено Лабораторией проекта ---\n"
                   + "\n".join(missing) + "\n")
            atomic_write(path, new)
            log(".gitignore дополнен.", "ok")
            return True
        log(".gitignore оставлен без изменений по вашему выбору.", "warn")
        return False

    def git_init_commit(self):
        """Фоновый поток: git init → add -A → commit. Диалогов здесь нет."""
        if not self.folder_ready():
            return False
        if not shutil.which("git"):
            log("Git не найден в PATH.", "err")
            log(tool_hint("git"), "info")
            return False
        folder = self.state.folder
        if os.path.isdir(os.path.join(folder, ".git")):
            log("Репозиторий уже существует — git init пропускаем.", "info")
        else:
            if not self.runner.run(["git", "init"], cwd=folder).ok:
                return False
        if not self.runner.run(["git", "add", "-A"], cwd=folder).ok:
            return False
        status = self.runner.run(["git", "status", "--porcelain"], cwd=folder)
        if status.ok and not status.stdout.strip():
            log("Изменений нет — коммитить нечего, репозиторий чистый.", "info")
            return True
        res = self.runner.run(["git", "commit", "-m", "стартовый коммит"], cwd=folder)
        if not res.ok:
            text = ((res.stderr or "") + (res.stdout or "")).lower()
            if ("user.email" in text or "user.name" in text
                    or "author identity" in text or "tell me who you are" in text):
                log("Git не знает автора коммита. Задайте имя и почту ДЛЯ ЭТОГО репозитория "
                    "(без --global), затем повторите кнопку:", "err")
                log('  git config user.name "Ваше имя"\n'
                    '  git config user.email "you@example.com"', "info")
            return False
        self.runner.run(["git", "log", "-1", "--oneline"], cwd=folder)
        log("Первый коммит создан.", "ok")
        return True

    # --- действие 5: проверка окружения (можно в фоне) -----------------------
    def _write_test(self, folder):
        """Реальная проверка права записи: создаём и удаляем пробный файл."""
        probe = os.path.join(folder, ".lab_write_test.tmp")
        try:
            with open(probe, "w", encoding="utf-8") as f:
                f.write("ok")
        except OSError as e:
            return False, str(e)
        try:
            os.remove(probe)
        except OSError:
            pass                      # мусор не критичен, права на запись есть
        return True, ""

    def check_env(self):
        """Собирает отчёт об окружении, пишет его в artifacts/env_report.txt."""
        lines = ["ОТЧЁТ ОБ ОКРУЖЕНИИ — " + now_human(),
                 "Лаборатория проекта " + APP_VERSION, ""]
        lines += ["## Система",
                  "ОС: " + platform_name() + " (" + platform.platform() + ")",
                  "Python лаборатории: " + sys.version.split()[0],
                  "Исполняемый файл: " + sys.executable, ""]
        lines += ["## Инструменты в PATH"]
        for tool in ("git", "python", "python3", "pip"):
            found = shutil.which(tool)
            lines.append(tool + ": " + (found if found else "не найден"))
        lines.append("")
        folder = self.state.folder
        lines += ["## Папка проекта", "Путь: " + (folder or "не выбрана")]
        if folder:
            exists = os.path.isdir(folder)
            lines.append("Существует: " + ("да" if exists else "нет"))
            if exists:
                ok, err = self._write_test(folder)
                lines.append("Доступна на запись: " + ("да" if ok else "НЕТ — " + err))
                missing_dirs = [d for d in BASE_DIRS
                                if not os.path.isdir(os.path.join(folder, d))]
                missing_files = [f for f in USER_FILES
                                 if not os.path.isfile(os.path.join(folder, f))]
                lines.append("Нет папок: "
                             + (", ".join(missing_dirs) if missing_dirs else "все на месте"))
                lines.append("Нет файлов: "
                             + (", ".join(missing_files) if missing_files else "все на месте"))
        lines.append("")
        lines += ["## Окружение .venv"]
        py = self.venv_python()
        if folder and os.path.exists(py):
            lines.append("Python окружения: " + py)
            r = self.runner.run([py, "--version"], cwd=folder)
            lines.append("Версия: " + (r.combined() or r.status_text()))
            r = self.runner.run([py, "-m", "pip", "--version"], cwd=folder)
            lines.append("pip: " + (r.combined() or r.status_text()))
        else:
            lines.append("Окружение не создано (кнопка «Создать окружение»).")
        lines.append("")
        lines += ["## Git"]
        if shutil.which("git"):
            r = self.runner.run(["git", "--version"], cwd=folder or os.getcwd())
            lines.append("Версия: " + (r.combined() or r.status_text()))
            if folder and os.path.isdir(folder):
                r = self.runner.run(["git", "rev-parse", "--is-inside-work-tree"], cwd=folder)
                is_repo = r.ok and r.stdout.strip() == "true"
                lines.append("Репозиторий: " + ("да" if is_repo else "нет"))
                if is_repo:
                    r = self.runner.run(["git", "status", "--porcelain"], cwd=folder)
                    changes = [ln for ln in r.stdout.splitlines() if ln.strip()]
                    lines.append("Незакоммиченных изменений: " + str(len(changes)))
                    r = self.runner.run(["git", "log", "-1", "--oneline"], cwd=folder)
                    lines.append("Последний коммит: "
                                 + (r.stdout.strip() or "коммитов ещё нет"))
        else:
            lines.append("Git не установлен.")
            lines.append(tool_hint("git"))
        text = "\n".join(lines) + "\n"
        log(text, "raw")
        if folder and os.path.isdir(folder):
            try:
                ensure_dir(os.path.join(folder, "artifacts"))
                atomic_write(os.path.join(folder, "artifacts", "env_report.txt"), text)
                log("Отчёт сохранён: artifacts/env_report.txt", "ok")
            except OSError as e:
                log("Не удалось сохранить отчёт: " + str(e), "warn")
        return text

    # --- картинки ------------------------------------------------------------
    def attach_image(self, sid, src):
        """Копирует картинку в images/ под безопасным именем и регистрирует её в этапе.
        Возвращает относительный путь или пустую строку."""
        if not self.folder_ready():
            return ""
        if not os.path.isfile(src):
            log("Файл не найден: " + str(src), "err")
            return ""
        ext = os.path.splitext(src)[1].lower()
        if ext not in IMAGE_EXTS:
            log("Неподдерживаемый формат картинки: " + ext
                + ". Допустимы: " + ", ".join(IMAGE_EXTS), "err")
            return ""
        ensure_dir(self.project_path("images"))
        base = sanitize_name(os.path.basename(src), "image" + ext)
        stem, ext2 = os.path.splitext(base)
        prefix = str(STAGE_NUM.get(sid, 0)).zfill(2) + "_" + sid + "_"
        rel = os.path.join("images", prefix + stem + ext2)
        i = 1
        while os.path.exists(self.project_path(rel)):    # не затираем прошлые картинки
            rel = os.path.join("images", prefix + stem + "_" + str(i) + ext2)
            i += 1
        shutil.copy2(src, self.project_path(rel))
        rel = rel.replace("\\", "/")                     # в состоянии — единый стиль путей
        self.state.add_image(sid, rel)
        log("Картинка приложена: " + rel, "ok")
        return rel


# =============================================================================
# СЕКЦИЯ 7. ИСТОРИЯ И ОТКАТЫ (HistoryManager)
# -----------------------------------------------------------------------------
# Снапшот = полный слепок состояния в
#   history/snap_<время>__<причина>__<этап>__<прогресс>.json
# Метаданные зашиты в имя файла: список читается быстро, без разбора содержимого.
#
# Откат ОБРАТИМ двумя способами:
#   1) перед откатом автоматически делается снапшот «before_rollback» (на диске);
#   2) текущее состояние кладётся в память — кнопки «Вернуть откат» / «Повторить откат».
# =============================================================================
REASON_LABELS = {
    "manual": "вручную",
    "approve": "утверждение этапа",
    "before_rollback": "перед откатом",
    "theme_change": "смена темы",
    "before_import": "перед загрузкой состояния",
    "auto": "автосохранение",
}

MEMORY_STACK_LIMIT = 20         # сколько состояний держим в памяти для undo/redo
DIFF_LINES_LIMIT = 600          # столько строк различий показываем в интерфейсе


class HistoryManager:
    """Снапшоты, откаты и сравнение состояний. Работает поверх AppState."""

    def __init__(self, state):
        self.state = state
        self._undo = []         # состояния «до отката» (для кнопки «Вернуть откат»)
        self._redo = []         # состояния «после отката» (для «Повторить откат»)

    # --- пути и имена --------------------------------------------------------
    def history_dir(self):
        """Папка снапшотов внутри проекта (пустая строка, если папка не выбрана)."""
        return os.path.join(self.state.folder, "history") if self.state.folder else ""

    def _safe_path(self, filename):
        """Проверяет имя снапшота и не пускает нас наружу папки history/."""
        name = os.path.basename(filename or "")
        if not name.startswith("snap_") or not name.endswith(".json"):
            log("Это не файл снапшота: " + str(filename), "err")
            return ""
        folder = self.history_dir()
        if not folder:
            log("Папка проекта не выбрана — история недоступна.", "warn")
            return ""
        path = os.path.join(folder, name)
        if not is_inside(path, folder):
            log("Путь вне папки истории запрещён: " + str(filename), "err")
            return ""
        return path

    def _sync_history_from_disk(self):
        """Пересобирает state['history'] по файлам на диске.
        Зачем: после отката в состоянии лежит старый список, а файлы новее."""
        entries = self.list_snapshots()
        self.state.data["history"] = [
            {"file": e["file"], "time": e["time"], "reason": e["reason"],
             "stage": e["stage"], "progress": e["progress"]}
            for e in entries[:LIMITS["snapshot_keep"]]
        ]

    # --- создание снапшота ---------------------------------------------------
    def snapshot(self, reason="manual", stage_id="", quiet=False):
        """Пишет полный слепок состояния. Возвращает путь или пустую строку.
        quiet=True — для служебных снапшотов, чтобы не засорять лог."""
        if not self.state.folder:
            if not quiet:
                log("Снапшот не создан: папка проекта не выбрана.", "warn")
            return ""
        try:
            ensure_dir(self.history_dir())
            done, total = self.state.progress()
            reason_key = sanitize_name(reason, "manual")
            stage_key = sanitize_name(stage_id or "-", "none")
            stem = ("snap_" + now_stamp() + "__" + reason_key + "__" + stage_key
                    + "__" + str(done) + "of" + str(total))
            path = os.path.join(self.history_dir(), stem + ".json")
            i = 1
            while os.path.exists(path):        # два снапшота в одну секунду — не проблема
                path = os.path.join(self.history_dir(), stem + "_" + str(i) + ".json")
                i += 1
            payload = {
                "meta": {"created_at": now_human(), "reason": reason_key,
                         "stage": stage_id, "progress": str(done) + "/" + str(total),
                         "project": self.state.name,
                         "theme": self.state.data["theme"]["title"],
                         "app_version": APP_VERSION, "schema_version": SCHEMA_VERSION},
                "state": self.state.to_dict(),
            }
            atomic_write(path, json.dumps(payload, ensure_ascii=False, indent=2))
            self._sync_history_from_disk()
            self.state.touch()
            if not quiet:
                log("Снапшот создан: history/" + os.path.basename(path), "ok")
            self.prune(quiet=True)
            return path
        except OSError as e:
            log("Не удалось создать снапшот: " + str(e), "err")
            return ""

    def snapshot_on_approve(self, sid):
        """Удобная обёртка: снапшот при утверждении этапа (причина и этап в имени)."""
        return self.snapshot("approve", sid)

    # --- чтение списка -------------------------------------------------------
    def list_snapshots(self):
        """Список снапшотов, новые сверху. Читает только имена файлов — быстро."""
        folder = self.history_dir()
        if not folder or not os.path.isdir(folder):
            return []
        out = []
        try:
            names = sorted(os.listdir(folder), reverse=True)
        except OSError as e:
            log("Не удалось прочитать папку истории: " + str(e), "err")
            return []
        for name in names:
            if not (name.startswith("snap_") and name.endswith(".json")):
                continue
            parts = name[:-5].split("__")        # убираем .json и разбираем имя
            stamp = parts[0][5:] if parts else ""
            try:
                human = datetime.strptime(stamp, "%Y%m%d_%H%M%S").strftime("%Y-%m-%d %H:%M:%S")
            except ValueError:
                human = stamp or "время неизвестно"
            reason = parts[1] if len(parts) > 1 else "manual"
            stage = parts[2] if len(parts) > 2 else "-"
            progress = parts[3] if len(parts) > 3 else ""
            try:
                size = os.path.getsize(os.path.join(folder, name))
            except OSError:
                size = 0
            out.append({"file": name, "path": os.path.join(folder, name),
                        "time": human, "reason": reason,
                        "reason_ru": REASON_LABELS.get(reason, reason),
                        "stage": stage, "stage_ru": STAGE_TITLES.get(stage, "—"),
                        "progress": progress, "size": size})
        return out

    def latest(self):
        """Имя самого свежего снапшота (пустая строка, если истории нет)."""
        items = self.list_snapshots()
        return items[0]["file"] if items else ""

    def summary_line(self):
        """Короткая строка для статусбара и вкладки «История»."""
        items = self.list_snapshots()
        if not items:
            return "Снапшотов пока нет."
        return ("Снапшотов: " + str(len(items)) + " | последний: " + items[0]["time"]
                + " (" + items[0]["reason_ru"] + ")")

    def read_snapshot(self, filename):
        """Возвращает состояние из снапшота или None (битый файл не роняет приложение)."""
        path = self._safe_path(filename)
        if not path or not os.path.isfile(path):
            log("Снапшот не найден: " + str(filename), "warn")
            return None
        text = read_text(path, "")
        try:
            payload = json.loads(text)
        except ValueError as e:
            log("Снапшот повреждён (" + str(e) + "): " + str(filename), "err")
            return None
        if isinstance(payload, dict) and isinstance(payload.get("state"), dict):
            return payload["state"]
        if isinstance(payload, dict) and "stages" in payload:
            return payload                      # совместимость: снапшот без конверта
        log("В файле нет состояния проекта: " + str(filename), "err")
        return None

    # --- откаты --------------------------------------------------------------
    def _load_keeping_folder(self, data):
        """Загружает состояние, но рабочую папку оставляет текущую.
        Иначе снапшот из другой папки уведёт туда автосохранение и историю."""
        folder = self.state.folder
        self.state.load_dict(data)
        if folder:
            self.state.data["project"]["folder"] = folder
        self._sync_history_from_disk()
        self.state.touch()

    def restore(self, filename):
        """Откат к снапшоту. Обратим: страхуемся файлом на диске и памятью."""
        data = self.read_snapshot(filename)
        if data is None:
            return False
        self.snapshot("before_rollback", quiet=True)     # 1) страховка на диске
        self._push(self._undo, self.state.to_dict())     # 2) страховка в памяти
        self._redo.clear()
        self._load_keeping_folder(data)
        log("Откат выполнен: " + filename + ". Вернуть — кнопкой «Вернуть откат».", "ok")
        return True

    def _push(self, stack, data):
        """Кладёт состояние в стек с ограничением памяти (снапшоты большие)."""
        stack.append(data)
        if len(stack) > MEMORY_STACK_LIMIT:
            del stack[0]

    def can_undo(self):
        return bool(self._undo)

    def can_redo(self):
        return bool(self._redo)

    def undo(self):
        """«Вернуть откат»: возвращает состояние, которое было до restore()."""
        if not self._undo:
            log("Возвращать нечего: откатов в этой сессии не было.", "warn")
            return False
        self._push(self._redo, self.state.to_dict())
        self._load_keeping_folder(self._undo.pop())
        log("Откат отменён — вернулось состояние до него.", "ok")
        return True

    def redo(self):
        """«Повторить откат»: снова применяет то, что мы только что вернули."""
        if not self._redo:
            log("Повторять нечего.", "warn")
            return False
        self._push(self._undo, self.state.to_dict())
        self._load_keeping_folder(self._redo.pop())
        log("Откат применён повторно.", "ok")
        return True

    # --- сравнение -----------------------------------------------------------
    def changes_summary(self, filename):
        """Человеческая сводка: что изменилось по этапам относительно текущего состояния."""
        data = self.read_snapshot(filename)
        if data is None:
            return ""
        current = self.state.to_dict()
        old = {s.get("id"): s for s in data.get("stages", []) if isinstance(s, dict)}
        new = {s.get("id"): s for s in current.get("stages", []) if isinstance(s, dict)}
        status_ru = {"approved": "утверждён", "draft": "черновик", "empty": "пусто"}
        lines = ["Сравнение снапшота с текущим состоянием:"]
        for sid in STAGE_IDS:
            a, b = old.get(sid, {}), new.get(sid, {})
            changes = []
            if a.get("status") != b.get("status"):
                changes.append("статус: " + status_ru.get(a.get("status"), "—")
                               + " → " + status_ru.get(b.get("status"), "—"))
            la = len(a.get("llm_result") or "")
            lb = len(b.get("llm_result") or "")
            if la != lb:
                changes.append("ответ LLM: " + str(la) + " → " + str(lb) + " символов")
            if (a.get("fields") or {}) != (b.get("fields") or {}):
                changes.append("поля изменены")
            if (a.get("images") or []) != (b.get("images") or []):
                changes.append("картинки изменены")
            if changes:
                lines.append("• " + STAGE_TITLES.get(sid, sid) + ": " + "; ".join(changes))
        if data.get("theme") != current.get("theme"):
            lines.append("• тема проекта изменена")
        if data.get("project") != current.get("project"):
            lines.append("• имя или папка проекта изменены")
        if len(lines) == 1:
            lines.append("Различий нет.")
        return "\n".join(lines)

    def diff_text(self, filename, other=None):
        """Построчные различия двух состояний (по умолчанию — снапшот против текущего).
        Обрезается, чтобы большое сравнение не подвесило интерфейс."""
        a = self.read_snapshot(filename)
        if a is None:
            return ""
        if other:
            b = self.read_snapshot(other)
            if b is None:
                return ""
            label_b = other
        else:
            b = self.state.to_dict()
            label_b = "текущее состояние"
        left = json.dumps(a, ensure_ascii=False, indent=2, sort_keys=True).splitlines()
        right = json.dumps(b, ensure_ascii=False, indent=2, sort_keys=True).splitlines()
        diff = list(difflib.unified_diff(left, right, fromfile=filename,
                                         tofile=label_b, lineterm="", n=2))
        if not diff:
            return "Различий нет."
        if len(diff) > DIFF_LINES_LIMIT:
            diff = diff[:DIFF_LINES_LIMIT] + ["… показаны первые "
                                              + str(DIFF_LINES_LIMIT) + " строк различий …"]
        return "\n".join(diff)

    def preview(self, filename):
        """Короткий предпросмотр снапшота для правой панели вкладки «История»."""
        data = self.read_snapshot(filename)
        if data is None:
            return ""
        status_ru = {"approved": "утверждён", "draft": "черновик", "empty": "пусто"}
        lines = ["Проект: " + ((data.get("project") or {}).get("name") or "без имени"),
                 "Тема: " + ((data.get("theme") or {}).get("title") or "не выбрана"),
                 "Изменено: " + (data.get("updated_at") or "—"),
                 "Этапы:"]
        for s in data.get("stages", []):
            lines.append("  " + str(s.get("num", "?")) + ". " + str(s.get("title", "?"))
                         + " — " + status_ru.get(s.get("status"), "—")
                         + (" (ответ " + str(len(s.get("llm_result") or "")) + " симв.)"
                            if s.get("llm_result") else ""))
        return "\n".join(lines)

    # --- уборка --------------------------------------------------------------
    def prune(self, quiet=False):
        """Удаляет самые старые снапшоты сверх лимита. Каждый факт — в лог."""
        items = self.list_snapshots()
        keep = LIMITS["snapshot_keep"]
        if len(items) <= keep:
            return 0
        removed = 0
        for item in items[keep:]:              # список отсортирован новые→старые
            try:
                os.remove(item["path"])
                removed += 1
                if not quiet:
                    log("Удалён старый снапшот: " + item["file"], "info")
            except OSError as e:
                log("Не удалось удалить снапшот " + item["file"] + ": " + str(e), "warn")
        if removed and not quiet:
            log("История очищена: удалено " + str(removed) + ", оставлено " + str(keep), "info")
        return removed


# =============================================================================
# СЕКЦИЯ 8. ЭКСПОРТ (Exporter)
# -----------------------------------------------------------------------------
# Записывает наружу: промпты (00..06), артефакты (результаты этапов),
# самодостаточный report.html и цветной pipeline.svg.
# Весь пользовательский текст экранируется; картинки — как base64 внутри HTML.
# =============================================================================
MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".gif": "image/gif", ".bmp": "image/bmp", ".svg": "image/svg+xml",
        ".webp": "image/webp"}


class Exporter:
    """Выгружает конструкцию проекта в файлы. Работает только внутри папки проекта."""

    def __init__(self, state, builder):
        self.state = state
        self.builder = builder

    # --- пути ----------------------------------------------------------------
    def _dir(self, name):
        """Путь к подпапке проекта; создаёт её при необходимости."""
        path = os.path.join(self.state.folder, name)
        ensure_dir(path)
        return path

    def ready(self):
        if not self.state.folder:
            log("Экспорт невозможен: папка проекта не выбрана.", "warn")
            return False
        return True

    # --- промпты -------------------------------------------------------------
    def export_prompts(self):
        """prompts/00_master_prompt.txt и 01..06. Берёт сохранённый промпт этапа,
        а если его нет — собирает свежий, чтобы экспорт не был пустым."""
        if not self.ready():
            return []
        out = []
        for sid, fname in PROMPT_FILENAMES.items():
            st = self.state.stage(sid)
            text = (st["prompt"] or "").strip() if st else ""
            if not text:
                text = self.builder.build_stage_prompt(sid)
            path = os.path.join(self._dir("prompts"), fname)
            atomic_write(path, text)
            out.append(path)
            log("Промпт записан: prompts/" + fname, "ok")
        return out

    # --- артефакты -----------------------------------------------------------
    def export_artifacts(self):
        """artifacts/0X_*_result.md + answers.json со всеми полями и флагами.
        Шапка честно пишет статус: черновик не выдаём за утверждённый результат."""
        if not self.ready():
            return []
        out = []
        status_ru = {"approved": "утверждённый результат",
                     "draft": "ЧЕРНОВИК (не утверждён)", "empty": "пусто"}
        for sid, fname in ARTIFACT_FILENAMES.items():
            st = self.state.stage(sid)
            body = (st["llm_result"] or "").strip() if st else ""
            if not body:
                continue                       # пустой результат не выгружаем
            header = ("# Этап " + str(STAGE_NUM.get(sid, "?")) + " «"
                      + STAGE_TITLES.get(sid, sid) + "» — "
                      + status_ru.get(st["status"], st["status"]) + "\n"
                      + "Утверждён: " + (st["approved_at"] or "—") + "\n\n")
            path = os.path.join(self._dir("artifacts"), fname)
            atomic_write(path, header + body + "\n")
            out.append(path)
            log("Артефакт записан: artifacts/" + fname, "ok")
        # Сводный JSON со всеми ответами полей и флагами.
        answers = {"project": self.state.name, "theme": self.state.data["theme"]["title"],
                   "flags": self.state.data["flags"],
                   "stages": {s["id"]: {"status": s["status"], "fields": s["fields"],
                                        "images": s["images"]}
                              for s in self.state.data["stages"]}}
        path = os.path.join(self._dir("artifacts"), "answers.json")
        atomic_write(path, json.dumps(answers, ensure_ascii=False, indent=2))
        out.append(path)
        log("Артефакт записан: artifacts/answers.json", "ok")
        return out

    # --- картинки ------------------------------------------------------------
    def _image_src(self, rel):
        """Возвращает <img> для картинки: либо base64-данные, либо ссылку.
        Путь обязан лежать внутри images/ — состояние мог править человек."""
        images_dir = os.path.join(self.state.folder, "images")
        path = os.path.abspath(os.path.join(self.state.folder, rel.replace("/", os.sep)))
        if not is_inside(path, images_dir):
            return "<p>(путь вне images/ запрещён: " + html.escape(rel) + ")</p>"
        if not os.path.isfile(path):
            return "<p>(файл не найден: " + html.escape(rel) + ")</p>"
        ext = os.path.splitext(path)[1].lower()
        try:
            size = os.path.getsize(path)
        except OSError:
            size = 0
        # Большие картинки не встраиваем, чтобы не раздувать HTML до мегабайтов.
        if size <= LIMITS["image_max_mb"] * 1024 * 1024:
            try:
                with open(path, "rb") as f:
                    data = base64.b64encode(f.read()).decode("ascii")
                return ('<img src="data:' + MIME.get(ext, "application/octet-stream")
                        + ';base64,' + data + '" alt="' + html.escape(rel) + '">')
            except OSError as e:
                return ("<p>(не удалось прочитать " + html.escape(rel) + ": "
                        + html.escape(str(e)) + ")</p>")
        return ('<p>Картинка слишком большая для встраивания, смотрите файл:</p>'
                '<p><code>' + html.escape(rel) + "</code></p>")

    # --- SVG прогресса -------------------------------------------------------
    def build_svg(self):
        """Цветная схема этапов. Цвет зависит от статуса, а не от темы интерфейса,
        чтобы экспорт выглядел одинаково у всех."""
        fixed = {"approved": "#2ea043", "draft": "#d7ba7d", "empty": "#6a6a6a"}
        status_ru = {"approved": "утверждён", "draft": "черновик", "empty": "пусто"}
        stages = self.state.data["stages"]
        bw, bh, gap, margin = 150, 70, 34, 24
        n = len(stages)
        width = margin * 2 + n * bw + (n - 1) * gap
        height = margin * 2 + bh + 46
        parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" '
                 'viewBox="0 0 %d %d" font-family="Segoe UI, Arial, sans-serif">'
                 % (width, height, width, height)]
        parts.append('<rect x="0" y="0" width="%d" height="%d" fill="#1e1e1e"/>'
                     % (width, height))
        x = margin
        y = margin
        for s in stages:
            color = fixed.get(s["status"], "#6a6a6a")
            parts.append('<rect x="%d" y="%d" width="%d" height="%d" rx="8" '
                         'fill="%s" stroke="#3c3c3c"/>' % (x, y, bw, bh, color))
            parts.append('<text x="%d" y="%d" fill="#ffffff" font-size="13" '
                         'text-anchor="middle" font-weight="bold">%d. %s</text>'
                         % (x + bw // 2, y + 28, s["num"], html.escape(s["title"])))
            parts.append('<text x="%d" y="%d" fill="#e8e8e8" font-size="11" '
                         'text-anchor="middle">%s</text>'
                         % (x + bw // 2, y + 50, status_ru.get(s["status"], s["status"])))
            if s["num"] < n:                       # стрелка к следующему этапу
                ax = x + bw
                # Остриё останавливается ДО следующего блока, иначе его срежет прямоугольник.
                parts.append('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="#9a9a9a" '
                             'stroke-width="2"/>'
                             % (ax + 2, y + bh // 2, ax + gap - 9, y + bh // 2))
                parts.append('<polygon points="%d,%d %d,%d %d,%d" fill="#9a9a9a"/>'
                             % (ax + gap - 9, y + bh // 2 - 5,
                                ax + gap - 9, y + bh // 2 + 5,
                                ax + gap - 2, y + bh // 2))
            x += bw + gap
        # Легенда.
        ly = y + bh + 26
        for i, (label, color) in enumerate((("утверждён", fixed["approved"]),
                                            ("черновик", fixed["draft"]),
                                            ("пусто", fixed["empty"]))):
            lx = margin + i * 170
            parts.append('<rect x="%d" y="%d" width="14" height="14" fill="%s"/>'
                         % (lx, ly, color))
            parts.append('<text x="%d" y="%d" fill="#d4d4d4" font-size="12">%s</text>'
                         % (lx + 20, ly + 12, label))
        parts.append('<text x="%d" y="%d" fill="#6a6a6a" font-size="10" '
                     'text-anchor="end">%s</text>'
                     % (width - margin, height - 8, now_human()))
        parts.append("</svg>")
        return "\n".join(parts)

    def export_svg(self):
        """Пишет pipeline.svg в корень проекта."""
        if not self.ready():
            return ""
        path = os.path.join(self.state.folder, SVG_FILE)
        atomic_write(path, self.build_svg())
        log("Схема прогресса записана: " + SVG_FILE, "ok")
        return path

    # --- HTML ----------------------------------------------------------------
    def _stage_html(self, s):
        """Один блок этапа в отчёте: статус, поля, промпт, результат, картинки."""
        status_ru = {"approved": "утверждён", "draft": "черновик", "empty": "пусто"}
        scolor = {"approved": "#2ea043", "draft": "#d7ba7d", "empty": "#6a6a6a"}
        lines = ['<section class="stage">']
        lines.append('<h2>%d. %s <span class="badge" style="background:%s">%s</span></h2>'
                     % (s["num"], html.escape(s["title"]),
                        scolor.get(s["status"], "#6a6a6a"),
                        status_ru.get(s["status"], s["status"])))
        if s["approved_at"]:
            lines.append('<p class="muted">Утверждён: %s</p>' % html.escape(s["approved_at"]))
        fields = fields_of(s["id"])
        if fields:
            lines.append('<table><tr><th>Поле</th><th>Значение</th></tr>')
            for f in fields:
                val = s["fields"].get(f["key"], "")
                if isinstance(val, list):
                    val = ", ".join(str(v) for v in val)
                val = str(val).strip() or "— не заполнено —"
                lines.append('<tr><td>%s</td><td><pre>%s</pre></td></tr>'
                             % (html.escape(f["label"]), html.escape(val)))
            lines.append("</table>")
        if (s["prompt"] or "").strip():
            lines.append("<h3>Промпт</h3><pre>%s</pre>" % html.escape(s["prompt"]))
        if (s["llm_result"] or "").strip():
            lines.append("<h3>Результат от LLM</h3><pre>%s</pre>"
                         % html.escape(s["llm_result"]))
        if s["images"]:
            lines.append("<h3>Картинки</h3>")
            for rel in s["images"]:
                lines.append(self._image_src(rel))
        lines.append("</section>")
        return "\n".join(lines)

    def export_html(self):
        """Самодостаточный тёмный отчёт: шапка, схема, этапы, окружение, история."""
        if not self.ready():
            return ""
        st = self.state
        done, total = st.progress()
        env_text = read_text(os.path.join(st.folder, "artifacts", "env_report.txt"), "")
        parts = ["<!DOCTYPE html>", '<html lang="ru"><head><meta charset="utf-8">',
                 "<title>Отчёт: %s</title>" % html.escape(st.name or "Проект"),
                 "<style>",
                 "body{background:#1e1e1e;color:#d4d4d4;font-family:'Segoe UI',Arial,sans-serif;",
                 "margin:0;padding:24px;line-height:1.5;}",
                 "h1{color:#ffffff}h2{color:#4ec9b0;border-bottom:1px solid #3c3c3c;padding-bottom:4px}",
                 "h3{color:#d7ba7d}",
                 ".muted{color:#9a9a9a}.badge{color:#fff;border-radius:6px;padding:2px 10px;font-size:14px}",
                 "table{border-collapse:collapse;width:100%;margin:8px 0}",
                 "th,td{border:1px solid #3c3c3c;padding:6px 10px;text-align:left;vertical-align:top}",
                 "th{background:#2d2d30;color:#d4d4d4}td pre{white-space:pre-wrap;margin:0}",
                 "pre{background:#1b1b1c;border:1px solid #3c3c3c;border-radius:6px;",
                 "padding:12px;white-space:pre-wrap;word-wrap:break-word;overflow:auto}",
                 "img{max-width:100%;border:1px solid #3c3c3c;border-radius:6px;margin:6px 0}",
                 ".scheme{background:#1e1e1e;border:1px solid #3c3c3c;border-radius:8px;",
                 "padding:12px;overflow:auto;margin:12px 0}",
                 "</style></head><body>"]
        parts.append("<h1>%s</h1>" % html.escape(st.name or "Проект"))
        parts.append('<p class="muted">Тема: %s &nbsp;|&nbsp; Утверждено этапов: %d/%d'
                     " &nbsp;|&nbsp; Собран: %s &nbsp;|&nbsp; ОС: %s</p>"
                     % (html.escape(st.data["theme"]["title"] or "не выбрана"),
                        done, total, now_human(), platform_name()))
        parts.append('<div class="scheme">%s</div>' % self.build_svg())
        for s in st.data["stages"]:
            parts.append(self._stage_html(s))
        if env_text.strip():
            parts.append("<h2>Отчёт об окружении</h2><pre>%s</pre>" % html.escape(env_text))
        hist = self.state.data.get("history") or []
        if hist:
            parts.append("<h2>Снапшоты</h2><table><tr><th>Время</th><th>Причина</th>"
                         "<th>Этап</th><th>Прогресс</th></tr>")
            for h in hist:
                reason = str(h.get("reason", ""))
                parts.append("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>"
                             % (html.escape(str(h.get("time", ""))),
                                html.escape(REASON_LABELS.get(reason, reason)),
                                html.escape(STAGE_TITLES.get(str(h.get("stage", "")),
                                                             str(h.get("stage", "")))),
                                html.escape(str(h.get("progress", "")))))
            parts.append("</table>")
        parts.append('<p class="muted">Создано «Лабораторией проекта» %s</p>' % APP_VERSION)
        parts.append("</body></html>")
        path = os.path.join(st.folder, REPORT_FILE)
        atomic_write(path, "\n".join(parts))
        log("Отчёт записан: " + REPORT_FILE, "ok")
        return path

    # --- всё сразу -----------------------------------------------------------
    def export_all(self):
        """Полный экспорт + свежий state.json. Возвращает список записанных файлов."""
        if not self.ready():
            return []
        files = []
        files += self.export_prompts()
        files += self.export_artifacts()
        files.append(self.export_svg())
        files.append(self.export_html())
        self.state.save(quiet=True)
        files.append(self.state.state_path())
        log("Экспорт завершён: записано файлов — " + str(len(files)), "ok")
        return files


# =============================================================================
# СЕКЦИЯ 9а. ВИДЖЕТЫ, ЛОГ-КОНСОЛЬ, ФОНОВЫЕ ЗАДАЧИ, ВКЛАДКА «СТАРТ»
# =============================================================================


def get_mono_family():
    """Первый доступный моноширинный шрифт — для полей кода и лога."""
    try:
        fams = set(tkfont.families())
    except Exception:
        return "TkFixedFont"
    for name in FONT_MONO_CANDIDATES:
        if name in fams:
            return name
    return "TkFixedFont"


def add_label(parent, text, muted=False, kind=None):
    """Подпись. Атрибут _lbl нужен перекраске, чтобы вернуть правильный цвет."""
    lab = tk.Label(parent, text=text, anchor="w", justify="left", wraplength=760)
    lab._lbl = kind or ("muted" if muted else "normal")
    lab.pack(fill="x", padx=8, pady=(6, 0))
    return lab


def add_text(parent, rows=4, mono=True):
    """Многострочное поле ввода. Все поля моноширинные: код, промпты и ответы."""
    txt = tk.Text(parent, height=rows, wrap="word", undo=True, relief="flat",
                  font=(get_mono_family(), FONT_MONO_SIZE))
    txt.pack(fill="x", padx=8, pady=(2, 6))
    return txt


def add_entry(parent, text=""):
    """Однострочное поле ввода."""
    ent = tk.Entry(parent, relief="flat", font=(get_mono_family(), FONT_MONO_SIZE))
    if text:
        ent.insert(0, text)
    ent.pack(fill="x", padx=8, pady=(2, 6))
    return ent


def add_button(parent, text, command, kind="accent", pady=4):
    """Кнопка. Атрибут _btn сообщает перекраске, какой стиль применить."""
    btn = tk.Button(parent, text=text, command=command, relief="flat", padx=10, pady=pady)
    btn._btn = kind
    btn.pack(side="left", padx=(8, 6), pady=6)
    return btn


def add_hline(parent):
    """Тонкий разделитель между смысловыми группами."""
    sep = tk.Frame(parent, height=1)
    sep._hline = True
    sep.pack(fill="x", padx=8, pady=8)
    return sep


class ScrollFrame(tk.Frame):
    """Прокручиваемая область: длинная форма этапа не обрезается по высоте окна.
    Окно на канвасе ровно одно — его id храним, чтобы менять ширину."""

    def __init__(self, parent):
        tk.Frame.__init__(self, parent)
        self.canvas = tk.Canvas(self, borderwidth=0, highlightthickness=0)
        self.vsb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vsb.set)
        self.vsb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner = tk.Frame(self.canvas)
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>",
                        lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>",
                         lambda e: self.canvas.itemconfigure(self._win, width=e.width))

    def wheel(self, event):
        """Прокрутка колесом: Windows/macOS дают delta, Linux — Button-4/5."""
        num = getattr(event, "num", None)
        if num == 4:
            step = -3
        elif num == 5:
            step = 3
        else:
            step = -3 if getattr(event, "delta", 0) > 0 else 3
        self.canvas.yview_scroll(step, "units")


class LogConsole(tk.Frame):
    """Лог-консоль внизу окна. Забирает строки из очереди по таймеру, красит по типу."""

    def __init__(self, parent, app):
        tk.Frame.__init__(self, parent)
        self.app = app
        bar = tk.Frame(self)
        bar.pack(fill="x")
        self._lbl_title = tk.Label(bar, text="Лог-консоль", anchor="w")
        self._lbl_title._lbl = "muted"
        self._lbl_title.pack(side="left", padx=8)
        for text, cmd, kind in (("Копировать всё",
                                 lambda: clipboard_put(self, log_text()), "warn"),
                                ("Сохранить в файл", self._save, "warn"),
                                ("Очистить", self.clear, "warn")):
            b = tk.Button(bar, text=text, command=cmd)
            b._btn = kind
            b.pack(side="right", padx=4)
        self.text = tk.Text(self, height=8, wrap="word", state="disabled", undo=False,
                            font=(get_mono_family(), FONT_MONO_SIZE))
        self.text.pack(fill="both", expand=True, padx=4, pady=(2, 4))
        self.retag()
        # Стартовые строки, чтобы консоль не была пустой.
        for t, k, m in log_events():
            self.append(t, k, m)

    def retag(self):
        """Перенастраивает цвета строк — вызывается при смене темы."""
        for kind, color in (("cmd", C["log_cmd"]), ("ok", C["log_ok"]),
                            ("err", C["log_err"]), ("warn", C["log_warn"]),
                            ("raw", C["log_raw"]), ("info", C["log_info"])):
            self.text.tag_configure(kind, foreground=color)

    def append(self, when, kind, msg):
        """Добавляет одну строку. Теги красят её по типу (команда/успех/ошибка...)."""
        self.text.configure(state="normal")
        self.text.insert("end", "[" + when + "] " + msg + "\n", kind)
        self.text.configure(state="disabled")
        self.text.see("end")

    def poll(self):
        """Вызывается по таймеру из UI-потока: забирает накопившиеся строки."""
        for t, k, m in log_events():
            self.append(t, k, m)

    def clear(self):
        """Очистка консоли (буфер в памяти не трогаем — он нужен для экспорта)."""
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")

    def _save(self):
        """Сохраняет лог в файл — удобно прикладывать к вопросу."""
        if not self.app.state.folder:
            log("Папка проекта не выбрана — лог некуда сохранить.", "warn")
            return
        path = os.path.join(self.app.state.folder, "artifacts", "log.txt")
        try:
            ensure_dir(os.path.dirname(path))
            atomic_write(path, log_text())
            log("Лог сохранён: artifacts/log.txt", "ok")
        except OSError as e:
            log("Не удалось сохранить лог: " + str(e), "err")


class TaskRunner:
    """Запускает долгие команды в фоновом потоке, результат возвращает в UI-поток
    через app.after — напрямую трогать tkinter из потока нельзя.
    Счётчик active нужен, чтобы предупредить о незавершённой задаче при выходе."""

    def __init__(self, app):
        self.app = app
        self.active = 0
        self._lock = threading.Lock()

    def submit(self, fn, on_done=None, label=""):
        with self._lock:
            self.active += 1

        def worker():
            try:
                result = fn()
            except Exception as e:                # фоновая задача не должна ронять окно
                log("Сбой фоновой задачи «%s»: %s: %s"
                    % (label or "?", type(e).__name__, e), "err")
                log(traceback.format_exc(), "raw")
                result = None
            finally:
                with self._lock:
                    self.active -= 1
            try:
                self.app.after(0, lambda r=result: on_done(r) if on_done else None)
            except (tk.TclError, RuntimeError):
                pass                              # окно закрыто — показывать некому

        threading.Thread(target=worker, daemon=True).start()


class ConflictDialog(tk.Toplevel):
    """Диалог разрешения конфликта файла: пропустить / перезаписать / сохранить рядом.
    Галочка «применить ко всем» запоминает выбор для остальных файлов этого запуска."""

    def __init__(self, parent, rel, old, new):
        tk.Toplevel.__init__(self, parent)
        self.title("Файл уже существует")
        self.result = "skip"
        self.apply_all = False
        self.transient(parent)
        add_label(self, "Файл уже существует и отличается от заготовки:")
        add_label(self, rel, kind="err")
        add_label(self, "Старый размер: %d симв. | Новая заготовка: %d симв."
                  % (len(old or ""), len(new or "")), muted=True)
        self.var_all = tk.BooleanVar(value=False)
        tk.Checkbutton(self, text="Применить ко всем файлам этого запуска",
                       variable=self.var_all).pack(anchor="w", padx=8, pady=4)
        row = tk.Frame(self)
        row.pack(pady=8)
        for text, choice, kind in (("Пропустить (оставить мой)", "skip", "warn"),
                                   ("Перезаписать", "overwrite", "danger"),
                                   ("Сохранить рядом (.new)", "copy", "accent")):
            b = tk.Button(row, text=text, command=lambda c=choice: self._done(c))
            b._btn = kind
            b.pack(side="left", padx=4)
        self.protocol("WM_DELETE_WINDOW", lambda: self._done("skip"))
        # Диалог создан после общей перекраски — красим его сами.
        if hasattr(parent, "_recolor"):
            parent._recolor(self)
        self.grab_set()
        self.focus_set()
        self.wait_window(self)

    def _done(self, choice):
        self.result = choice
        self.apply_all = bool(self.var_all.get())
        self.destroy()


class StartTab:
    """Вкладка «Старт»: выбор темы, пресеты, папка и реальные действия на диске."""

    def __init__(self, parent, app):
        self.app = app
        self.frame = ttk.Frame(parent)
        scroll = ScrollFrame(self.frame)
        scroll.pack(fill="both", expand=True)
        body = scroll.inner
        self.title = "Старт"

        # --- тема ------------------------------------------------------------
        add_label(body, "Тема проекта (пресеты — черновики, ничего не навязывают)")
        self.theme_var = tk.StringVar(value=app.state.data["theme"]["key"] or "blank")
        trow = tk.Frame(body)
        trow.pack(fill="x", padx=8)
        self.theme_buttons = []
        for key in THEME_ORDER:
            rb = tk.Radiobutton(trow, text=THEMES[key]["title"], value=key,
                                variable=self.theme_var, command=self._on_theme)
            rb.pack(side="left", padx=6, pady=2)
            self.theme_buttons.append(rb)
        self.theme_desc = add_label(body, THEMES["blank"]["desc"], kind="muted")

        # --- имя и папка -----------------------------------------------------
        add_label(body, "Имя проекта")
        self.name_ent = add_entry(body, app.state.name)
        self.name_ent.bind("<FocusOut>", lambda e: self._on_name())
        prow = tk.Frame(body)
        prow.pack(fill="x", padx=8, pady=(4, 0))
        add_label(prow, "Папка проекта:")
        self.folder_lbl = tk.Label(prow, text=app.state.folder or "— не выбрана —",
                                   anchor="w")
        self.folder_lbl.pack(side="left", padx=6, fill="x", expand=True)
        add_button(prow, "Выбрать папку", self._choose_folder, kind="accent")
        add_button(prow, "Открыть папку", self._open_folder, kind="warn")

        # --- пресеты ---------------------------------------------------------
        add_hline(body)
        add_label(body, "Пресеты темы (редактируемые черновики)")
        add_label(body, "Стек (предложение)", muted=True)
        self.stack_txt = add_text(body, rows=6)
        add_label(body, "Структура папок (строки вида path/ = доп. папки)", muted=True)
        self.struct_txt = add_text(body, rows=6)
        add_label(body, "Наводящие вопросы темы (формат: id | вопрос | подсказка | варианты)",
                  muted=True)
        self.q_txt = add_text(body, rows=6)
        add_label(body, "Инварианты (черновик)", muted=True)
        self.inv_txt = add_text(body, rows=6)
        add_button(body, "Сохранить правки пресетов", self._save_presets, kind="warn")

        # --- настройки промпта ----------------------------------------------
        add_hline(body)
        add_label(body, "Лимит символов на один этап в контексте промпта "
                        "(от %d до %d)" % (LIMITS["context_min"], LIMITS["context_max"]),
                  muted=True)
        self.ctx_ent = add_entry(body, str(app.state.data["settings"]["context_limit"]))
        self.ctx_ent.bind("<FocusOut>", lambda e: self._on_ctx_limit())

        # --- действия на диске ----------------------------------------------
        add_hline(body)
        add_label(body, "Реальные действия на диске (работают только в выбранной папке)")
        arow = tk.Frame(body)
        arow.pack(fill="x", padx=8)
        self.disk_buttons = []
        self.disk_buttons.append(add_button(arow, "Создать структуру",
                                            self._create_structure, "accent"))
        self.disk_buttons.append(add_button(arow, "Создать окружение .venv",
                                            self._create_venv, "accent"))
        self.disk_buttons.append(add_button(arow, "Установить зависимости",
                                            self._install_deps, "accent"))
        self.disk_buttons.append(add_button(arow, "Инициализировать git",
                                            self._git_init, "accent"))
        self.disk_buttons.append(add_button(arow, "Проверить окружение",
                                            self._check_env, "warn"))

        # --- последний отчёт об окружении -----------------------------------
        add_label(body, "Отчёт об окружении (обновляется кнопкой «Проверить окружение»)",
                  muted=True)
        self.env_txt = add_text(body, rows=10)
        self.env_txt.configure(state="disabled")
        self.refresh()

    # --- сбор данных из виджетов в состояние --------------------------------
    def _on_name(self):
        self.app.state.set_name(self.name_ent.get())
        self.app.schedule_autosave()

    def _on_ctx_limit(self):
        """Лимит контекста: только целое число в разумных пределах."""
        raw = self.ctx_ent.get().strip()
        try:
            value = int(raw)
        except ValueError:
            log("Лимит контекста должен быть целым числом. Оставлено прежнее значение.", "warn")
            value = self.app.state.data["settings"]["context_limit"]
        value = max(LIMITS["context_min"], min(LIMITS["context_max"], value))
        self.app.state.set_setting("context_limit", value)
        self.ctx_ent.delete(0, "end")
        self.ctx_ent.insert(0, str(value))
        self.app.schedule_autosave()

    def _on_theme(self):
        """Смена темы. «Пресеты изменены» = отличаются от штатных пресетов прежней темы,
        а не просто непустые (после любого выбора темы они непустые)."""
        key = self.theme_var.get()
        theme = get_theme(key)
        old_key = self.app.state.data["theme"]["key"]
        current = self.app.state.data["presets"]
        edited = bool(old_key) and current != clone_presets(old_key)
        if edited and not messagebox.askyesno(
                "Смена темы",
                "Пресеты темы «%s» изменены вручную.\nЗаменить их пресетами темы «%s»?"
                % (theme_title(old_key), theme["title"])):
            self.app.state.set_theme(key, theme["title"])     # только тема, пресеты оставляем
        else:
            self.app.state.set_theme(key, theme["title"], clone_presets(key))
        self.app.history.snapshot("theme_change", quiet=True)
        self.app.schedule_autosave()
        self.refresh()
        # Вопросы «Идеи» зависят от темы — перестраиваем их сразу.
        idea = self.app.tabs_by_sid.get("idea")
        if idea is not None:
            idea.refresh()
        self.app.refresh_stage_tabs()
        log("Выбрана тема: " + theme["title"], "ok")

    def _save_presets(self):
        """Правки человека в пресетах — сохраняем в состояние."""
        p = self.app.state.data["presets"]
        p["stack"] = self.stack_txt.get("1.0", "end").strip()
        p["structure"] = self.struct_txt.get("1.0", "end").strip()
        p["invariants"] = self.inv_txt.get("1.0", "end").strip()
        p["questions"] = questions_from_text(self.q_txt.get("1.0", "end"))
        self.app.state.touch()
        self.app.schedule_autosave()
        idea = self.app.tabs_by_sid.get("idea")
        if idea is not None:
            idea.refresh()
        log("Пресеты сохранены.", "ok")

    # --- папка ---------------------------------------------------------------
    def _choose_folder(self):
        """Выбор рабочей папки. Существующий state.json никогда не затирается молча:
        Да — продолжить проект, Нет — начать новый (старый файл копируем в бэкап),
        Отмена — не менять ничего."""
        path = filedialog.askdirectory(title="Выберите папку проекта")
        if not path:
            return
        path = os.path.abspath(os.path.expanduser(path))
        state_file = os.path.join(path, STATE_FILE)

        if os.path.isfile(state_file):
            answer = messagebox.askyesnocancel(
                "Найден state.json",
                "В папке уже есть состояние проекта.\n\n"
                "Да — загрузить его и продолжить этот проект.\n"
                "Нет — начать новый проект (старый state.json будет скопирован "
                "в резервный файл рядом).\n"
                "Отмена — ничего не менять.")
            if answer is None:
                return
            if answer:
                self.app.history.snapshot("before_import", quiet=True)
                self.app.state.set_folder(path)
                self.app.state.load(state_file)
                # Папку берём выбранную, а не из файла: проект могли перенести.
                self.app.state.data["project"]["folder"] = path
            else:
                backup = state_file + ".bak_" + now_stamp()
                try:
                    shutil.copy2(state_file, backup)
                except OSError as e:
                    log("Не удалось сделать копию state.json: %s. Папка не выбрана." % e, "err")
                    return
                log("Прежнее состояние отложено в копию: " + os.path.basename(backup), "warn")
                self.app.state.load_dict(default_state())
                self.app.state.set_folder(path)
        else:
            self.app.state.set_folder(path)
            log("Текущее состояние проекта будет сохранено в эту папку.", "info")

        # Тема интерфейса — из состояния проекта, а не всегда тёмная.
        self.app.apply_theme(self.app.state.data["settings"].get("theme_mode", "dark"))
        self.app.history._sync_history_from_disk()
        self.app.schedule_autosave()
        self.app.reload_all()
        self.app.select_saved_tab()

    def _open_folder(self):
        if self.app.state.folder:
            open_folder(self.app.state.folder)
        else:
            log("Папка ещё не выбрана.", "warn")

    # --- действия на диске ---------------------------------------------------
    def _require_folder(self):
        if not self.app.state.folder:
            messagebox.showwarning(APP_NAME, "Сначала выберите папку проекта.")
            return False
        return True

    def _set_busy(self, busy):
        """Блокируем кнопки диска на время фоновой команды."""
        state = "disabled" if busy else "normal"
        for b in self.disk_buttons:
            b.configure(state=state)

    @safe_action("создание структуры")
    def _create_structure(self):
        if not self._require_folder():
            return
        # «Применить ко всем» действует только на один запуск, не на всю сессию.
        self.app._conflict_all = None
        self.app.scaffolder.create_structure()      # диалоги — в UI-потоке
        self.app.refresh_ui()

    def _create_venv(self):
        if not self._require_folder():
            return
        py = self.app.scaffolder.venv_python()
        force = False
        if os.path.exists(py):
            force = messagebox.askyesno(
                "Окружение уже есть",
                ".venv уже существует.\nПересоздать его? Установленные в него пакеты "
                "будут удалены (venv --clear).")
            if not force:
                return
        self._set_busy(True)
        self.app.tasks.submit(lambda: self.app.scaffolder.create_venv(force),
                              on_done=lambda r: self._set_busy(False), label="venv")

    def _install_deps(self):
        if not self._require_folder():
            return
        self._set_busy(True)
        self.app.tasks.submit(self.app.scaffolder.install_deps,
                              on_done=lambda r: self._set_busy(False), label="pip")

    def _git_init(self):
        if not self._require_folder():
            return
        self.app.scaffolder.ensure_gitignore()      # диалог — в UI-потоке
        self._set_busy(True)
        self.app.tasks.submit(self.app.scaffolder.git_init_commit,
                              on_done=lambda r: self._set_busy(False), label="git")

    def _check_env(self):
        if not self._require_folder():
            return
        self._set_busy(True)

        def show(text):
            self._set_busy(False)
            if text:
                self.env_txt.configure(state="normal")
                self.env_txt.delete("1.0", "end")
                self.env_txt.insert("1.0", text)
                self.env_txt.configure(state="disabled")

        self.app.tasks.submit(self.app.scaffolder.check_env, on_done=show, label="env")

    # --- отображение ---------------------------------------------------------
    def refresh(self):
        """Подтягивает состояние в виджеты (после загрузки/отката/смены темы)."""
        st = self.app.state
        self.name_ent.delete(0, "end")
        self.name_ent.insert(0, st.name)
        self.folder_lbl.configure(text=st.folder or "— не выбрана —")
        self.theme_var.set(st.data["theme"]["key"] or "blank")
        key = st.data["theme"]["key"] or "blank"
        self.theme_desc.configure(text=get_theme(key)["desc"])
        self.ctx_ent.delete(0, "end")
        self.ctx_ent.insert(0, str(st.data["settings"]["context_limit"]))
        p = st.data["presets"]
        for widget, text in ((self.stack_txt, p.get("stack", "")),
                             (self.struct_txt, p.get("structure", "")),
                             (self.inv_txt, p.get("invariants", ""))):
            widget.delete("1.0", "end")
            widget.insert("1.0", text)
        self.q_txt.delete("1.0", "end")
        self.q_txt.insert("1.0", questions_to_text(p.get("questions") or []))


# =============================================================================
# СЕКЦИЯ 9б. ВКЛАДКИ ЭТАПОВ: ИДЕЯ, УНИВЕРСАЛЬНЫЙ ЭТАП, ИТОГ, ИСТОРИЯ
# =============================================================================


class StagePanel:
    """Нижняя половина любого этапа: промпт → копирование → результат → картинки
    → утверждение. sid задаёт этап; collect_fn собирает поля владельца."""

    def __init__(self, parent, app, sid, collect_fn):
        self.app = app
        self.sid = sid
        self.collect_fn = collect_fn
        self.ctx_lbl = add_label(parent, "Контекст: " + app.builder.context_summary(sid),
                                 kind="muted")

        # --- промпт ----------------------------------------------------------
        add_label(parent, "Промпт для внешней LLM (можно править вручную)")
        self.prompt_txt = add_text(parent, rows=8)
        brow = tk.Frame(parent)
        brow.pack(fill="x", padx=4)
        add_button(brow, "Собрать промпт", self.build_prompt, "accent")
        add_button(brow, "Копировать промпт", self.copy_prompt, "warn")
        add_button(brow, "Сохранить промпт в файл", self.save_prompt, "warn")
        self.stats_lbl = add_label(parent, "", muted=True)

        # --- результат от LLM ------------------------------------------------
        add_label(parent, "Результат от внешней LLM (вставьте ответ сюда)")
        self.result_txt = add_text(parent, rows=8)
        rrow = tk.Frame(parent)
        rrow.pack(fill="x", padx=4)
        add_button(rrow, "Вставить из буфера", self.paste_result, "warn")
        add_button(rrow, "Сохранить результат", self.save_result, "warn")

        # --- картинки --------------------------------------------------------
        add_label(parent, "Картинки этапа (схемы, скриншоты)")
        irow = tk.Frame(parent)
        irow.pack(fill="x", padx=4)
        add_button(irow, "Прикрепить картинку", self.attach_image, "warn")
        add_button(irow, "Удалить выбранную", self.remove_image, "warn")
        add_button(irow, "Открыть папку images", self.open_images, "warn")
        self.img_list = tk.Listbox(parent, height=4)
        self.img_list.pack(fill="x", padx=8, pady=(2, 6))

        # --- утверждение -----------------------------------------------------
        arow = tk.Frame(parent)
        arow.pack(fill="x", padx=4)
        self.approve_btn = add_button(arow, "Утвердить этап и перейти дальше",
                                      self.approve, "ok")
        add_button(arow, "Снять утверждение", self.unapprove, "warn")
        add_button(arow, "Снапшот сейчас", self.manual_snapshot, "warn")
        self.status_lbl = add_label(arow, "", kind="muted")

    # --- отображение ---------------------------------------------------------
    def refresh(self):
        st = self.app.state.stage(self.sid)
        self.prompt_txt.delete("1.0", "end")
        self.prompt_txt.insert("1.0", st["prompt"] or "")
        self.result_txt.delete("1.0", "end")
        self.result_txt.insert("1.0", st["llm_result"] or "")
        self.stats_lbl.configure(text=stats_line(st["prompt"] or ""))
        self.img_list.delete(0, "end")
        for rel in st["images"]:
            self.img_list.insert("end", rel)
        self._status()
        self.ctx_lbl.configure(text="Контекст: " + self.app.builder.context_summary(self.sid))

    def _status(self):
        """Цветной ярлык статуса: утверждён — зелёный, черновик — жёлтый, пусто — серый.
        Атрибут _lbl нужен, чтобы перекраска темы сохранила правильный цвет."""
        st = self.app.state.stage(self.sid)
        ru = {"approved": "✓ утверждён", "draft": "черновик", "empty": "пусто"}
        kind = {"approved": "ok", "draft": "warn", "empty": "muted"}.get(st["status"], "muted")
        self.status_lbl._lbl = kind
        self.status_lbl.configure(text=ru.get(st["status"], st["status"]), fg=C[kind])

    # --- действия ------------------------------------------------------------
    @safe_action("сборка промпта")
    def build_prompt(self):
        self.collect_fn()
        text = self.app.builder.build_stage_prompt(self.sid)
        self.app.state.set_prompt(self.sid, text)
        self.app.schedule_autosave()
        self.refresh()
        log("Промпт этапа «" + STAGE_TITLES[self.sid] + "» собран ("
            + str(prompt_stats(text)["chars"]) + " символов).", "ok")

    def copy_prompt(self):
        clipboard_put(self.prompt_txt, self.prompt_txt.get("1.0", "end").strip())

    @safe_action("сохранение промпта")
    def save_prompt(self):
        """Сохраняет промпт этапа в отдельный файл (полезно без полного экспорта)."""
        self.collect_fn()
        if not self.app.state.folder:
            log("Папка не выбрана.", "warn")
            return
        text = (self.prompt_txt.get("1.0", "end").strip()
                or self.app.builder.build_stage_prompt(self.sid))
        self.app.state.set_prompt(self.sid, text)
        path = os.path.join(self.app.state.folder, "prompts", PROMPT_FILENAMES[self.sid])
        ensure_dir(os.path.dirname(path))
        atomic_write(path, text)
        log("Промпт сохранён: prompts/" + PROMPT_FILENAMES[self.sid], "ok")

    def paste_result(self):
        """Вставляет ответ модели из буфера. Пустой/нетекстовый буфер поле НЕ трогает:
        иначе один неудачный клик стирал бы сохранённый результат."""
        try:
            text = self.app.clipboard_get()
        except Exception:
            log("В буфере обмена нет текста — поле результата не изменено.", "warn")
            return
        if not (text or "").strip():
            log("Буфер обмена пуст — поле результата не изменено.", "warn")
            return
        self.result_txt.delete("1.0", "end")
        self.result_txt.insert("1.0", text)
        self.save_result(quiet=True)
        log("Ответ вставлен из буфера обмена (%d символов)." % len(text), "ok")

    def save_result(self, quiet=False):
        self.app.state.set_result(self.sid, self.result_txt.get("1.0", "end"))
        self.app.schedule_autosave()
        if not quiet:
            log("Результат этапа сохранён.", "ok")
        self._status()
        self.app.refresh_stage_tabs()

    @safe_action("прикрепление картинки")
    def attach_image(self):
        path = filedialog.askopenfilename(
            title="Выберите картинку",
            filetypes=[("Картинки", " ".join("*" + e for e in IMAGE_EXTS)),
                       ("Все файлы", "*.*")])
        if not path:
            return
        if self.app.scaffolder.attach_image(self.sid, path):
            self.app.schedule_autosave()
            self.refresh()

    def remove_image(self):
        sel = self.img_list.curselection()
        if not sel:
            log("Выберите картинку в списке.", "warn")
            return
        rel = self.img_list.get(sel[0])
        self.app.state.remove_image(self.sid, rel)
        self.app.schedule_autosave()
        self.refresh()

    def open_images(self):
        if self.app.state.folder:
            open_folder(os.path.join(self.app.state.folder, "images"))

    def manual_snapshot(self):
        self.app.history.snapshot("manual", self.sid)
        self.app.schedule_autosave()

    @safe_action("утверждение этапа")
    def approve(self):
        self.collect_fn()
        st = self.app.state.stage(self.sid)
        if not (st["llm_result"] or "").strip():
            messagebox.showwarning(APP_NAME, "Сначала вставьте результат от внешней LLM — "
                                             "утверждать пустой этап нельзя.")
            return
        self.app.state.approve(self.sid)
        self.app.history.snapshot_on_approve(self.sid)
        self.app.schedule_autosave()
        self.refresh()
        self.app.refresh_stage_tabs()
        self.app.go_next(self.sid)

    def unapprove(self):
        self.app.state.unapprove(self.sid)
        self.app.schedule_autosave()
        self.refresh()
        self.app.refresh_stage_tabs()


class IdeaTab:
    """Этап «Идея»: мастер наводящих вопросов + общая панель этапа."""

    def __init__(self, parent, app):
        self.app = app
        self.sid = "idea"
        self.frame = ttk.Frame(parent)
        scroll = ScrollFrame(self.frame)
        scroll.pack(fill="both", expand=True)
        body = scroll.inner
        self.title = "1. Идея"
        add_label(body, "Этап 1. Идея — ответьте на вопросы своими словами. "
                        "Варианты — подсказки: клик добавляет текст в поле ответа.")
        self.warn_lbl = add_label(body, "", kind="warn")
        self.q_frame = tk.Frame(body)
        self.q_frame.pack(fill="x")
        self.q_entries = {}
        self.flag_vars = {}
        add_hline(body)
        add_label(body, "Поля этапа")
        self.field_widgets = {}
        for f in fields_of("idea"):
            add_label(body, f["label"], muted=True)
            if f["hint"]:
                add_label(body, f["hint"], muted=True)
            self.field_widgets[f["key"]] = add_text(body, rows=f["rows"])
        self.panel = StagePanel(body, app, "idea", self.collect)
        self.refresh()

    def _colorize_draft(self):
        """Раскрашивает строки черновика идеи по смыслу:
        вопросы, заполненные ответы, «не заполнено» и шапка — разными цветами."""
        txt = self.field_widgets["draft"]
        txt.tag_configure("qhead", foreground=C["accent_hi"])   # вопрос
        txt.tag_configure("meta", foreground=C["muted"])        # шапка: тема/имя
        txt.tag_configure("answer", foreground=C["fg"])         # заполненный ответ
        txt.tag_configure("missing", foreground=C["warn"])      # не заполнено/не отмечено
        for tag in ("qhead", "meta", "answer", "missing"):
            txt.tag_remove(tag, "1.0", "end")
        for i, line in enumerate(txt.get("1.0", "end").split("\n"), start=1):
            start = "%d.0" % i
            end = "%d.end" % i
            if line.startswith("• "):
                txt.tag_add("qhead", start, end)
            elif line.startswith("Тема проекта:") or line.startswith("Имя проекта:"):
                txt.tag_add("meta", start, end)
            elif line.strip():
                if ("не заполнено" in line) or ("не отмечено" in line):
                    txt.tag_add("missing", start, end)
                else:
                    txt.tag_add("answer", start, end)

    def _render_questions(self):
        """Перестраивает мастер вопросов под текущую тему и пресеты.
        Новые виджеты создаются уже после общей перекраски — красим их сами."""
        for child in self.q_frame.winfo_children():
            child.destroy()
        self.q_entries = {}
        st = self.app.state.stage("idea")
        for qd in idea_questions(self.app.state):
            if qd.get("kind") == "flags":
                self._render_flags(self.q_frame, qd)
                continue
            add_label(self.q_frame, qd["question"])
            if qd.get("hint"):
                add_label(self.q_frame, qd["hint"], muted=True)
            txt = add_text(self.q_frame, rows=2)
            txt.insert("1.0", str(st["fields"].get(qd["id"], "")))
            self.q_entries[qd["id"]] = txt
            if qd.get("options"):
                orow = tk.Frame(self.q_frame)
                orow.pack(fill="x", padx=8)
                for opt in qd["options"]:
                    # Кнопка-подсказка дописывает вариант в поле ответа.
                    b = tk.Button(orow, text=opt, relief="flat",
                                  command=lambda t=txt, o=opt: self._append_option(t, o))
                    b._btn = "warn"
                    b.pack(side="left", padx=2, pady=1)
        self.app._recolor(self.q_frame)

    def _render_flags(self, parent, qd):
        """Последний вопрос-галочки: пишется в state['flags']."""
        add_label(parent, qd["question"])
        if qd.get("hint"):
            add_label(parent, qd["hint"], muted=True)
        self.flag_vars = {}
        for key, label in qd["flags"]:
            var = tk.BooleanVar(value=bool(self.app.state.data["flags"].get(key)))
            self.flag_vars[key] = var
            tk.Checkbutton(parent, text=label, variable=var,
                           command=self._save_flags).pack(anchor="w", padx=12)

    def _save_flags(self):
        for key, var in self.flag_vars.items():
            self.app.state.set_flag(key, var.get())
        self.app.schedule_autosave()

    def _append_option(self, txt, opt):
        cur = txt.get("1.0", "end").strip()
        txt.delete("1.0", "end")
        txt.insert("1.0", (cur + " " if cur else "") + opt)

    def collect(self):
        """Собирает ответы мастера и поля в состояние.
        Галочки живут в state['flags'] — в поля этапа их не дублируем,
        иначе «flag_git» попадали бы в промпты следующих этапов."""
        for qid, txt in self.q_entries.items():
            self.app.state.set_field("idea", qid, txt.get("1.0", "end").strip())
        for key, txt in self.field_widgets.items():
            self.app.state.set_field("idea", key, txt.get("1.0", "end").strip())
        if self.flag_vars:
            self._save_flags()
        # Чистим следы прежней версии: flag_* в полях этапа не нужны.
        fields = self.app.state.stage("idea")["fields"]
        for key in [k for k in fields if k.startswith("flag_")]:
            del fields[key]
        self.app.schedule_autosave()

    def assemble_draft(self):
        """Кнопка «Собрать черновик» склеивает ответы в единый текст."""
        self.collect()
        draft = assemble_idea_draft(self.app.state)
        self.field_widgets["draft"].delete("1.0", "end")
        self.field_widgets["draft"].insert("1.0", draft)
        self.app.state.set_field("idea", "draft", draft)
        self.app.schedule_autosave()
        self._colorize_draft()
        log("Черновик идеи собран.", "ok")

    def refresh(self):
        self._render_questions()
        st = self.app.state.stage("idea")
        for key, txt in self.field_widgets.items():
            txt.delete("1.0", "end")
            txt.insert("1.0", str(st["fields"].get(key, "")))
        self._colorize_draft()
        missing = self.app.builder.missing_previous("idea")
        self.warn_lbl.configure(text=("Внимание: не утверждены — " + ", ".join(missing))
                                if missing else "")
        self.panel.refresh()


class StageTab:
    """Универсальная вкладка для этапов 2–6: поля из STAGE_SPECS + StagePanel."""

    def __init__(self, parent, app, sid):
        self.app = app
        self.sid = sid
        self.frame = ttk.Frame(parent)
        scroll = ScrollFrame(self.frame)
        scroll.pack(fill="both", expand=True)
        body = scroll.inner
        self.title = str(STAGE_NUM[sid]) + ". " + STAGE_TITLES[sid]
        add_label(body, "Этап %d. %s — %s" % (STAGE_NUM[sid], STAGE_TITLES[sid],
                                              stage_info(sid, "goal")))
        self.warn_lbl = add_label(body, "", kind="warn")
        self.field_widgets = {}
        for f in fields_of(sid):
            add_label(body, f["label"])
            if f["hint"]:
                add_label(body, f["hint"], muted=True)
            if f["kind"] == "line":
                self.field_widgets[f["key"]] = add_entry(body)
            else:
                self.field_widgets[f["key"]] = add_text(body, rows=f["rows"])
            # Кнопка подстановки черновика темы — только там, где он есть.
            if preset_hint_for(app.state, sid, f["key"]):
                add_button(body, "Подставить черновик темы",
                           lambda k=f["key"]: self._apply_hint(k), kind="warn", pady=1)
        self.panel = StagePanel(body, app, sid, self.collect)
        self.refresh()

    def _apply_hint(self, key):
        """Вставляет черновик темы в поле, спрашивая подтверждение при непустом поле."""
        widget = self.field_widgets[key]
        current = (widget.get("1.0", "end").strip() if isinstance(widget, tk.Text)
                   else widget.get())
        if current and not messagebox.askyesno("Подставить черновик",
                                               "Поле не пустое. Заменить его черновиком темы?"):
            return
        text = preset_hint_for(self.app.state, self.sid, key)
        if isinstance(widget, tk.Text):
            widget.delete("1.0", "end")
            widget.insert("1.0", text)
        else:
            widget.delete(0, "end")
            widget.insert(0, text)
        self.collect()

    def collect(self):
        for key, widget in self.field_widgets.items():
            value = (widget.get("1.0", "end").strip() if isinstance(widget, tk.Text)
                     else widget.get().strip())
            self.app.state.set_field(self.sid, key, value)
        self.app.schedule_autosave()

    def refresh(self):
        st = self.app.state.stage(self.sid)
        for key, widget in self.field_widgets.items():
            value = str(st["fields"].get(key, ""))
            if isinstance(widget, tk.Text):
                widget.delete("1.0", "end")
                widget.insert("1.0", value)
            else:
                widget.delete(0, "end")
                widget.insert(0, value)
        missing = self.app.builder.missing_previous(self.sid)
        self.warn_lbl.configure(text=("Внимание: не утверждены предыдущие этапы — "
                                      + ", ".join(missing)) if missing else "")
        self.panel.refresh()


class IdeaTabWithDraft(IdeaTab):
    """Идея с кнопкой «Собрать черновик» сразу под вопросами, до полей этапа."""

    def __init__(self, parent, app):
        IdeaTab.__init__(self, parent, app)
        body = self.q_frame.master
        siblings = body.winfo_children()          # порядок создания = порядок упаковки
        idx = siblings.index(self.q_frame)
        anchor = siblings[idx + 1] if idx + 1 < len(siblings) else None
        btn = tk.Button(body, text="Собрать черновик из ответов", command=self.assemble_draft)
        btn._btn = "accent"
        if anchor is not None:
            btn.pack(fill="x", padx=8, pady=4, before=anchor)
        else:
            btn.pack(fill="x", padx=8, pady=4)
        self.app._recolor(btn)


class SummaryTab(StageTab):
    """Этап «Итог»: поля сводки + мастер-промпт + кнопки экспорта."""

    def __init__(self, parent, app):
        StageTab.__init__(self, parent, app, "summary")
        # Панель экспорта добавляем в конец прокручиваемой области.
        body = self.frame.winfo_children()[0].inner
        add_hline(body)
        add_label(body, "Экспорт всей конструкции")
        erow = tk.Frame(body)
        erow.pack(fill="x", padx=8)
        add_button(erow, "Экспорт всего", self._export_all, "accent")
        add_button(erow, "Только промпты", self._export_prompts, "warn")
        add_button(erow, "Только HTML", self._export_html, "warn")
        add_button(erow, "Открыть report.html", self._open_report, "warn")
        self.master_txt = add_text(body, rows=10)
        self.master_txt.configure(state="disabled")
        add_button(body, "Показать мастер-промпт", self._show_master, "warn")

    @safe_action("сборка мастер-промпта")
    def _show_master(self):
        self.collect()
        text = self.app.builder.build_master_prompt()
        self.master_txt.configure(state="normal")
        self.master_txt.delete("1.0", "end")
        self.master_txt.insert("1.0", text)
        self.master_txt.configure(state="disabled")
        log("Мастер-промпт собран (" + str(prompt_stats(text)["chars"]) + " символов).", "ok")

    @safe_action("экспорт всего")
    def _export_all(self):
        self.collect()
        self.app.exporter.export_all()
        self.app.refresh_ui()

    @safe_action("экспорт промптов")
    def _export_prompts(self):
        self.app.exporter.export_prompts()

    @safe_action("экспорт HTML")
    def _export_html(self):
        self.app.exporter.export_html()

    def _open_report(self):
        if self.app.state.folder:
            open_folder(os.path.join(self.app.state.folder, REPORT_FILE))
        else:
            log("Сначала выберите папку и сделайте экспорт.", "warn")


class HistoryTab:
    """Вкладка «История»: список снапшотов, откат, возврат, сравнение, предпросмотр."""

    def __init__(self, parent, app):
        self.app = app
        self.frame = ttk.Frame(parent)
        self.title = "История"
        self._items = []
        left = tk.Frame(self.frame)
        left.pack(side="left", fill="both", expand=True)
        right = tk.Frame(self.frame)
        right.pack(side="right", fill="both", expand=True)
        trow = tk.Frame(left)
        trow.pack(fill="x")
        add_button(trow, "Обновить", self.refresh, "warn")
        add_button(trow, "Снапшот сейчас", self._manual, "accent")
        add_button(trow, "Откатиться к выбранному", self._restore, "danger")
        add_button(trow, "Вернуть откат", self._undo, "warn")
        add_button(trow, "Повторить откат", self._redo, "warn")
        self.summary_lbl = add_label(left, "", muted=True)
        self.list = tk.Listbox(left, height=18)
        self.list.pack(fill="both", expand=True, padx=8, pady=4)
        self.list.bind("<<ListboxSelect>>", lambda e: self._preview())
        add_label(right, "Предпросмотр / сравнение")
        self.detail = add_text(right, rows=20)
        self.detail.configure(state="disabled")
        drow = tk.Frame(right)
        drow.pack(fill="x")
        add_button(drow, "Изменения (сводка)", self._changes, "warn")
        add_button(drow, "Построчные различия", self._diff, "warn")
        self.refresh()

    def _selected(self):
        sel = self.list.curselection()
        return self._items[sel[0]]["file"] if sel else None

    def refresh(self):
        self._items = self.app.history.list_snapshots()
        self.list.delete(0, "end")
        for item in self._items:
            self.list.insert("end", "%s | %-22s | %-12s | %s"
                             % (item["time"], item["reason_ru"],
                                item["stage_ru"], item["progress"]))
        self.summary_lbl.configure(text=self.app.history.summary_line())

    def _manual(self):
        self.app.history.snapshot("manual")
        self.app.schedule_autosave()
        self.refresh()

    @safe_action("откат к снапшоту")
    def _restore(self):
        f = self._selected()
        if not f:
            log("Выберите снапшот в списке.", "warn")
            return
        if not messagebox.askyesno("Откат", "Откатиться к снапшоту от "
                                   + f.split("__")[0][5:] + "?\n"
                                   "Текущее состояние будет сохранено как «перед откатом»."):
            return
        self.app.history.restore(f)
        self.app.apply_theme(self.app.state.data["settings"].get("theme_mode", "dark"))
        self.app.schedule_autosave()
        self.app.reload_all()
        self.refresh()

    def _undo(self):
        if self.app.history.undo():
            self.app.apply_theme(self.app.state.data["settings"].get("theme_mode", "dark"))
            self.app.schedule_autosave()
            self.app.reload_all()
        self.refresh()

    def _redo(self):
        if self.app.history.redo():
            self.app.apply_theme(self.app.state.data["settings"].get("theme_mode", "dark"))
            self.app.schedule_autosave()
            self.app.reload_all()
        self.refresh()

    def _preview(self):
        f = self._selected()
        if not f:
            return
        self._show(self.app.history.preview(f))

    def _changes(self):
        f = self._selected()
        if not f:
            log("Выберите снапшот в списке.", "warn")
            return
        self._show(self.app.history.changes_summary(f))

    def _diff(self):
        f = self._selected()
        if not f:
            log("Выберите снапшот в списке.", "warn")
            return
        self._show(self.app.history.diff_text(f))

    def _show(self, text):
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        self.detail.insert("1.0", text or "(пусто)")
        self.detail.configure(state="disabled")


# =============================================================================
# СЕКЦИЯ 10. КЛАСС APP И ТОЧКА ВХОДА
# =============================================================================


class App(tk.Tk):
    """Главное окно. Держит состояние и все менеджеры, строит вкладки,
    перекрашивает интерфейс при смене темы и автосохраняет состояние."""

    def __init__(self):
        tk.Tk.__init__(self)
        self.title(APP_NAME + " " + APP_VERSION)
        self.geometry("1180x780")
        self.minsize(940, 620)

        # Ядро приложения: состояние и зависимые менеджеры.
        self.state = AppState()
        self.builder = PromptBuilder(self.state)
        self.history = HistoryManager(self.state)
        self.exporter = Exporter(self.state, self.builder)
        self.tasks = TaskRunner(self)
        self._autosave_failed = False      # чтобы не забивать лог одной и той же ошибкой
        self._conflict_all = None          # «применить ко всем» в диалоге конфликтов

        # Колбэки для Scaffolder: подтверждение и разрешение конфликтов файлов.
        self.scaffolder = Scaffolder(
            self.state,
            confirm=lambda t, m: messagebox.askyesno(t, m),
            ask_conflict=self._ask_conflict)

        set_palette("dark")                # тёмная тема по умолчанию
        self._build_menu()
        self._build_ui()
        self._configure_styles()
        self._recolor(self)
        self._recolor_menus()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Колесо мыши: одно общее правило на всё окно (см. _on_wheel).
        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.bind_all(seq, self._on_wheel)
        self.nb.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        # Таймеры: опрос лога и автосохранение.
        self.after(200, self._poll_log)
        self.after(LIMITS["autosave_ms"], self._autosave_loop)
        self._update_status()

    # --- диалог конфликта файлов --------------------------------------------
    def _ask_conflict(self, rel, old, new):
        """Если уже выбран режим «для всех» — не спрашиваем повторно."""
        if self._conflict_all in ("skip", "overwrite", "copy"):
            return self._conflict_all
        dlg = ConflictDialog(self, rel, old, new)
        if dlg.apply_all:
            self._conflict_all = dlg.result
        return dlg.result

    # --- меню ----------------------------------------------------------------
    def _build_menu(self):
        menubar = tk.Menu(self)
        mfile = tk.Menu(menubar, tearoff=0)
        mfile.add_command(label="Сохранить состояние", command=self.save_now)
        mfile.add_command(label="Экспорт всего",
                          command=lambda: self.exporter.export_all())
        mfile.add_separator()
        mfile.add_command(label="Выход", command=self._on_close)
        menubar.add_cascade(label="Файл", menu=mfile)
        mtheme = tk.Menu(menubar, tearoff=0)
        mtheme.add_command(label="Тёмная тема", command=lambda: self.apply_theme("dark"))
        mtheme.add_command(label="Светлая тема", command=lambda: self.apply_theme("light"))
        menubar.add_cascade(label="Тема", menu=mtheme)
        mhelp = tk.Menu(menubar, tearoff=0)
        mhelp.add_command(label="О программе", command=self._about)
        menubar.add_cascade(label="Справка", menu=mhelp)
        self.config(menu=menubar)
        self.menubar = menubar

    def _recolor_menus(self):
        """Меню не входят в winfo_children — красим их отдельно."""
        bar = getattr(self, "menubar", None)
        if bar is None:
            return
        menus = [bar]
        last = bar.index("end")
        if last is not None:
            for i in range(last + 1):
                if bar.type(i) == "cascade":
                    menus.append(bar.nametowidget(bar.entrycget(i, "menu")))
        for m in menus:
            try:
                m.configure(bg=C["panel2"], fg=C["fg"],
                            activebackground=C["accent"], activeforeground=C["accent_fg"])
            except tk.TclError:
                pass

    # --- интерфейс ------------------------------------------------------------
    def _build_ui(self):
        self.nb = ttk.Notebook(self)
        self.statusbar = tk.Label(self, text="", anchor="w")
        self.logconsole = LogConsole(self, self)
        # Сначала нижние панели, потом растягиваемая область вкладок:
        # так статусбар гарантированно в самом низу, а лог — над ним.
        self.statusbar.pack(side="bottom", fill="x")
        self.logconsole.pack(side="bottom", fill="x")
        self.nb.pack(side="top", fill="both", expand=True)

        self.tabs = []                       # список вкладок по порядку
        self.tabs_by_sid = {}
        self.start_tab = StartTab(self.nb, self)
        self.nb.add(self.start_tab.frame, text="Старт")
        self.tabs.append(self.start_tab)
        for sid in STAGE_IDS:                # idea, charter, arch, skeleton, feature, debug, summary
            if sid == "idea":
                tab = IdeaTabWithDraft(self.nb, self)
            elif sid == "summary":
                tab = SummaryTab(self.nb, self)
            else:
                tab = StageTab(self.nb, self, sid)
            self.nb.add(tab.frame, text=tab.title)
            self.tabs.append(tab)
            self.tabs_by_sid[sid] = tab
        self.history_tab = HistoryTab(self.nb, self)
        self.nb.add(self.history_tab.frame, text="История")
        self.tabs.append(self.history_tab)

    def _on_wheel(self, event):
        """Прокручивает ту прокручиваемую область, над которой указатель.
        Поля Text и Listbox прокручиваются сами (их классовые привязки уже сработали)."""
        try:
            widget = self.winfo_containing(event.x_root, event.y_root)
        except (KeyError, tk.TclError):
            return None
        while widget is not None:
            if isinstance(widget, (tk.Text, tk.Listbox)):
                return None
            if isinstance(widget, ScrollFrame):
                widget.wheel(event)
                return "break"
            widget = getattr(widget, "master", None)
        return None

    def _on_tab_changed(self, event=None):
        """Запоминаем последнюю вкладку — восстановим после загрузки состояния."""
        try:
            idx = self.nb.index(self.nb.select())
        except tk.TclError:
            return
        if self.state.data["settings"].get("last_tab") != idx:
            self.state.set_setting("last_tab", idx)

    def select_saved_tab(self):
        """Открывает вкладку, на которой человек работал в прошлый раз."""
        idx = self.state.data["settings"].get("last_tab", 0)
        if isinstance(idx, int) and 0 <= idx < len(self.tabs):
            self.nb.select(idx)

    # --- темы -----------------------------------------------------------------
    def _configure_styles(self):
        """Настройка ttk (Notebook, скроллбары) под текущую палитру."""
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("TNotebook", background=C["bg"], borderwidth=0)
        style.configure("TNotebook.Tab", background=C["panel"], foreground=C["fg"],
                        padding=(12, 5))
        style.map("TNotebook.Tab",
                  background=[("selected", C["panel2"])],
                  foreground=[("selected", C["fg"])])
        for orient in ("Vertical.TScrollbar", "Horizontal.TScrollbar"):
            style.configure(orient, background=C["panel2"], troughcolor=C["bg"],
                            bordercolor=C["border"], arrowcolor=C["fg"])

    def _recolor(self, widget):
        """Рекурсивно красит обычные tk-виджеты. Вызывается при смене темы
        и после создания новых виджетов (вопросы «Идеи», диалог конфликта).
        Каждый блок обёрнут в try/except: разные виджеты принимают разный набор опций."""
        try:
            cls = widget.winfo_class()
        except Exception:
            return
        try:
            if cls in ("Frame", "Labelframe", "Canvas"):
                widget.configure(bg=C["border"] if getattr(widget, "_hline", False)
                                 else C["panel"])
            elif isinstance(widget, tk.Tk) or cls == "Toplevel":
                widget.configure(bg=C["bg"])
            elif cls == "Label":
                kind = getattr(widget, "_lbl", "normal")
                fg = {"muted": C["muted"], "warn": C["warn"], "err": C["err"],
                      "ok": C["ok"]}.get(kind, C["fg"])
                widget.configure(bg=C["panel"], fg=fg)
            elif isinstance(widget, (tk.Text, tk.Entry)):
                # У Text и Entry есть курсор вставки — красим и его.
                widget.configure(bg=C["input"], fg=C["input_fg"],
                                 insertbackground=C["input_fg"],
                                 selectbackground=C["sel_bg"],
                                 selectforeground=C["sel_fg"],
                                 highlightbackground=C["border"],
                                 highlightcolor=C["accent"], relief="flat")
            elif cls == "Listbox":
                # У Listbox нет курсора вставки: не передаём ему insertbackground.
                widget.configure(bg=C["input"], fg=C["input_fg"],
                                 selectbackground=C["sel_bg"],
                                 selectforeground=C["sel_fg"],
                                 highlightbackground=C["border"],
                                 highlightcolor=C["accent"], relief="flat")
            elif cls == "Button":
                kind = getattr(widget, "_btn", "accent")
                if kind == "accent":
                    bg, fg, hi = C["accent"], C["accent_fg"], C["accent_hi"]
                elif kind == "ok":
                    bg, fg, hi = C["approved"], "#ffffff", C["approved"]
                elif kind == "danger":
                    bg, fg, hi = C["err"], "#ffffff", C["err"]
                else:
                    bg, fg, hi = C["panel2"], C["fg"], C["panel"]
                widget.configure(bg=bg, fg=fg, activebackground=hi, activeforeground=fg,
                                 disabledforeground=C["muted"], relief="flat",
                                 highlightthickness=0)
            elif cls in ("Checkbutton", "Radiobutton"):
                widget.configure(bg=C["panel"], fg=C["fg"], selectcolor=C["input"],
                                 activebackground=C["panel"], activeforeground=C["fg"],
                                 highlightthickness=0)
            elif cls == "Menu":
                widget.configure(bg=C["panel2"], fg=C["fg"],
                                 activebackground=C["accent"], activeforeground=C["accent_fg"])
        except tk.TclError:
            # Виджет не принял какую-то опцию — пропускаем его, не роняя тему.
            pass
        for child in widget.winfo_children():
            self._recolor(child)

    def apply_theme(self, mode):
        """Применяет тёмную/светлую палитру ко всему окну и запоминает выбор."""
        mode = set_palette(mode)
        self.state.set_setting("theme_mode", mode)
        self._configure_styles()
        self._recolor(self)
        self._recolor_menus()
        self.logconsole.retag()
        # Черновик идеи раскрашен тегами — их цвета тоже надо обновить.
        idea = getattr(self, "tabs_by_sid", {}).get("idea")
        if idea is not None:
            idea._colorize_draft()
        for tab in getattr(self, "tabs", []):
            panel = getattr(tab, "panel", None)
            if panel is not None:
                panel._status()
        self._update_status()
        log("Применена тема: " + ("тёмная" if mode == "dark" else "светлая"), "info")

    # --- навигация и статус ---------------------------------------------------
    def refresh_stage_tabs(self):
        """Обновляет заголовки вкладок: добавляет ✓ утверждённым этапам."""
        for i, sid in enumerate(STAGE_IDS, start=1):
            st = self.state.stage(sid)
            mark = " ✓" if st["status"] == "approved" else ""
            self.nb.tab(i, text=self.tabs_by_sid[sid].title + mark)
        self._update_status()

    def go_next(self, sid):
        """После утверждения переходим на следующую вкладку."""
        idx = STAGE_NUM.get(sid, 0) + 1
        if idx >= len(self.tabs):
            idx = len(self.tabs) - 1
        self.nb.select(idx)
        self.refresh_all_tabs()

    def refresh_all_tabs(self):
        """Подтягивает состояние во все вкладки (после загрузки/отката)."""
        for tab in self.tabs:
            try:
                tab.refresh()
            except Exception as e:
                log("Не удалось обновить вкладку: %s: %s" % (type(e).__name__, e), "warn")
        self.refresh_stage_tabs()

    def reload_all(self):
        """Полное перечитывание интерфейса из состояния (используют откаты)."""
        self.start_tab.refresh()
        self.refresh_all_tabs()
        self.history_tab.refresh()

    def refresh_ui(self):
        """Полное обновление интерфейса. НЕ называем update():
        tk.Tk.update — штатный метод обработки событий, перекрывать его нельзя."""
        self.refresh_all_tabs()
        self.history_tab.refresh()
        self._update_status()

    def _update_status(self):
        done, total = self.state.progress()
        folder = self.state.folder or "папка не выбрана"
        dirty = " • есть несохранённые изменения" if self.state.dirty else ""
        busy = " • выполняется фоновая задача" if self.tasks.active else ""
        self.statusbar.configure(
            text="Проект: %s | Утверждено: %d/%d | %s%s%s"
                 % (self.state.name or "без имени", done, total, folder, dirty, busy),
            bg=C["panel2"], fg=C["fg"])

    # --- сохранение -----------------------------------------------------------
    @safe_action("сохранение состояния")
    def save_now(self):
        self.state.save()
        self._update_status()

    def schedule_autosave(self):
        """Просто помечаем состояние изменённым — фактически сохраняет цикл."""
        self.state.touch()

    def _autosave_loop(self):
        """Каждые ~1.5 с: если есть изменения и выбрана папка — тихо сохраняем.
        Ошибку не глотаем: сообщаем один раз, дальше молчим до первого успеха."""
        try:
            if self.state.dirty and self.state.folder:
                self.state.save(quiet=True)
                self._update_status()
            self._autosave_failed = False
        except Exception as e:
            if not self._autosave_failed:
                log("Автосохранение не работает: %s: %s. Проверьте права и место на диске."
                    % (type(e).__name__, e), "err")
                self._autosave_failed = True
        self.after(LIMITS["autosave_ms"], self._autosave_loop)

    # --- лог ------------------------------------------------------------------
    def _poll_log(self):
        self.logconsole.poll()
        self.after(200, self._poll_log)

    # --- служебное -------------------------------------------------------------
    def _about(self):
        messagebox.showinfo(
            APP_NAME,
            APP_NAME + " " + APP_VERSION + "\n\n"
            "Пошаговый конструктор проекта через промпты для внешней LLM,\n"
            "который заодно реально создаёт проект на компьютере.\n\n"
            "Только стандартная библиотека. Тёмная тема по умолчанию.")

    def _on_close(self):
        """Перед выходом предупреждаем о фоновой задаче и предлагаем сохранить."""
        if self.tasks.active:
            if not messagebox.askyesno(
                    "Задача ещё выполняется",
                    "Фоновая команда (venv/pip/git) не завершена.\n"
                    "Если закрыть окно сейчас, она прервётся и окружение может "
                    "остаться недоделанным.\n\nВсё равно выйти?"):
                return
        if self.state.dirty:
            answer = messagebox.askyesnocancel("Выход",
                                               "Есть несохранённые изменения. Сохранить?")
            if answer is None:
                return
            if answer:
                if not self.state.folder:
                    path = filedialog.askdirectory(title="Выберите папку для сохранения")
                    if not path:
                        return
                    self.state.set_folder(path)
                if not self.state.save(quiet=True):
                    if not messagebox.askyesno("Сохранение не удалось",
                                               "Состояние не записано (см. лог).\n"
                                               "Выйти без сохранения?"):
                        return
        self.destroy()


def main():
    """Точка входа: создаёт окно и запускает главный цикл."""
    log("Лаборатория проекта " + APP_VERSION + " запущена. Тема: тёмная.", "info")
    log("Подсказка: сначала выберите тему и папку на вкладке «Старт».", "info")
    try:
        app = App()
    except tk.TclError as e:
        # Нет дисплея (например, запуск по ssh без X11) — понятное сообщение.
        sys.stderr.write("Не удалось открыть окно: %s\n"
                         "Запустите программу в графической сессии рабочего стола.\n" % e)
        raise SystemExit(1)
    app.mainloop()


if __name__ == "__main__":
    main()