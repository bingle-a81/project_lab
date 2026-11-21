# lab/config.py — ВСЕ константы: палитры, лимиты, имена этапов и файлов, режим окна.
import os

APP_NAME = "Лаборатория проекта"
APP_VERSION = "1.0.0"
SCHEMA_VERSION = 1

# Корень приложения (папка с main.py) — сюда кладём глобальные конфиги как запасные.
APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# --- Режим окна при запуске --------------------------------------------------
START_FULLSCREEN = False            # True — старт в полный экран; F11 переключает, Esc выходит
WINDOW_GEOMETRY = "1180x780"     # размер «обычного» окна (кнопка «Вид → Обычное окно»)
WINDOW_MIN = (940, 620)          # минимальный размер (автоматически ужимается под экран)

# --- Палитры. Все цвета — только здесь. -------------------------------------
PALETTE_DARK = {
    "bg": "#1e1e1e", "panel": "#252526", "panel2": "#2d2d30", "fg": "#d4d4d4",
    "muted": "#9a9a9a", "border": "#3c3c3c", "input": "#1b1b1c", "input_fg": "#e6e6e6",
    "sel_bg": "#264f78", "sel_fg": "#ffffff", "accent": "#0e639c", "accent_hi": "#1177bb",
    "accent_fg": "#ffffff", "ok": "#4ec9b0", "warn": "#d7ba7d", "err": "#f14c4c",
    "approved": "#2ea043", "draft": "#d7ba7d", "empty": "#6a6a6a",
    "log_cmd": "#569cd6", "log_ok": "#4ec9b0", "log_err": "#f14c4c",
    "log_warn": "#d7ba7d", "log_info": "#d4d4d4", "log_raw": "#9a9a9a",
}
PALETTE_LIGHT = {
    "bg": "#f3f3f3", "panel": "#ffffff", "panel2": "#eaeaea", "fg": "#1f1f1f",
    "muted": "#6a6a6a", "border": "#c8c8c8", "input": "#ffffff", "input_fg": "#1f1f1f",
    "sel_bg": "#add6ff", "sel_fg": "#000000", "accent": "#0e639c", "accent_hi": "#1177bb",
    "accent_fg": "#ffffff", "ok": "#107c10", "warn": "#9a6700", "err": "#c42b1c",
    "approved": "#107c10", "draft": "#9a6700", "empty": "#9a9a9a",
    "log_cmd": "#0451a5", "log_ok": "#107c10", "log_err": "#c42b1c",
    "log_warn": "#9a6700", "log_info": "#1f1f1f", "log_raw": "#5a5a5a",
}
# C — активная палитра. Меняется целиком при переключении темы.
C = dict(PALETTE_DARK)


def set_palette(mode):
    """Переключает активную палитру (dark/light) прямо в словаре C."""
    C.clear()
    C.update(PALETTE_LIGHT if mode == "light" else PALETTE_DARK)
    return "light" if mode == "light" else "dark"


# --- Лимиты и таймауты -------------------------------------------------------
LIMITS = {
    "snapshot_keep": 100,     # сколько снапшотов храним
    "context_chars": 200000,  # лимит контекста прошлых этапов (свои ответы не режем)
    "log_lines": 5000,        # кольцевой буфер лога
    "autosave_ms": 1500,      # период автосохранения
    "timeout_cmd": 60,        # сек, обычные команды
    "timeout_venv": 300,      # сек, создание .venv
    "timeout_pip": 900,       # сек, установка зависимостей
    "image_max_mb": 15,       # картинки больше не встраиваем в HTML
}

FONT_MONO_CANDIDATES = ("Consolas", "Menlo", "DejaVu Sans Mono", "Courier New")
FONT_UI_SIZE = 10
FONT_MONO_SIZE = 10

# --- Этапы -------------------------------------------------------------------
STAGES = [
    ("idea", 1, "Идея", "Что за проект и для кого"),
    ("charter", 2, "Паспорт", "Цель, границы, критерии готовности"),
    ("arch", 3, "Архитектура", "Модули, потоки данных, контракты"),
    ("skeleton", 4, "Скелет", "Дерево файлов и заготовки"),
    ("feature", 5, "Фича", "Первая полезная функция"),
    ("debug", 6, "Отладка", "Ошибка, причина, фикс, регресс-тест"),
    ("summary", 7, "Итог", "Мастер-промпт и экспорт"),
]
STAGE_IDS = [s[0] for s in STAGES]
WORK_STAGE_IDS = [s[0] for s in STAGES if s[0] != "summary"]
STAGE_TITLES = {s[0]: s[2] for s in STAGES}
STAGE_NUM = {s[0]: s[1] for s in STAGES}

PROMPT_FILENAMES = {
    "summary": "00_master_prompt.txt", "idea": "01_idea.txt", "charter": "02_charter.txt",
    "arch": "03_architecture.txt", "skeleton": "04_skeleton.txt",
    "feature": "05_feature.txt", "debug": "06_debug.txt",
}
ARTIFACT_FILENAMES = {
    "idea": "01_idea_result.md", "charter": "02_charter_result.md",
    "arch": "03_architecture_result.md", "skeleton": "04_skeleton_result.md",
    "feature": "05_feature_result.md", "debug": "06_debug_result.md",
}

# --- Файловая структура проекта ---------------------------------------------
BASE_DIRS = ["src", "tests", "features", "docs", "data", "out",
             "scripts", "prompts", "artifacts", "images", "history"]
USER_FILES = ["README.md", "AGENTS.md", "CLAUDE.md", "PROJECT_CHARTER.md",
              "requirements.txt", ".gitignore", ".env.example", "pytest.ini"]
APP_FILES = {"state.json", "report.html", "pipeline.svg"}

STATE_FILE = "state.json"
REPORT_FILE = "report.html"
SVG_FILE = "pipeline.svg"

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
def is_windows():
    """Проверка платформы для выбора способа развернуть окно."""
    return os.name == "nt"