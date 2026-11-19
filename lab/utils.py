# lab/utils.py — утилиты: время, пути, атомарная запись, лог, защита кнопок.
import functools
import os
import platform
import queue
import re
import shlex
import subprocess
import threading
import traceback
from datetime import datetime

from .config import APP_NAME, LIMITS


def now_stamp():
    """Метка для имён файлов снапшотов: 20261119_142530."""
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def now_human():
    """Читаемая метка времени для состояния, лога и отчёта."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def platform_name():
    """Человеческое имя ОС — попадает в промпт и в отчёт."""
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
    """Пишет файл атомарно: сначала .tmp, потом os.replace — не будет битого файла."""
    ensure_dir(os.path.dirname(os.path.abspath(path)))
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def read_text(path, default=""):
    """Читает текст в UTF-8; при ошибке ввода-вывода возвращает default."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return default


def sanitize_name(name, fallback="file"):
    """Безопасное имя файла: без путей, пробелов и служебных символов."""
    name = os.path.basename(str(name).strip())
    name = re.sub(r"[^\w.\-]+", "_", name, flags=re.UNICODE)
    name = re.sub(r"_{2,}", "_", name).strip("._")
    return (name or fallback)[:80]


def is_inside(child, parent):
    """True, если child лежит внутри parent — защита от записи мимо проекта."""
    try:
        child = os.path.normcase(os.path.abspath(child))
        parent = os.path.normcase(os.path.abspath(parent))
        return os.path.commonpath([child, parent]) == parent
    except (ValueError, OSError):
        return False


def shorten(text, limit):
    """Обрезает длинный текст с явной пометкой (для контекста прошлых этапов)."""
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
    """Открывает папку/файл средствами ОС. Нет инструмента — подсказка в лог."""
    if not path or not os.path.exists(path):
        log("Путь не существует: %s" % path, "warn")
        return False
    try:
        if is_windows():
            os.startfile(path)
            return True
        cmd = ["open", path] if platform.system() == "Darwin" else ["xdg-open", path]
        log("$ " + fmt_cmd(cmd), "cmd")
        subprocess.run(cmd, capture_output=True, timeout=LIMITS["timeout_cmd"])
        return True
    except FileNotFoundError:
        log("Не найдена программа для открытия папки. Откройте вручную: %s" % path, "warn")
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
# Пишут и UI-поток, и фоновые задачи. Буфер под замком, интерфейс забирает
# строки из очереди по таймеру (tkinter не потокобезопасен).
LOG_LOCK = threading.Lock()
LOG_BUFFER = []
LOG_QUEUE = queue.Queue()


def log(text, kind="info"):
    """Добавляет строку в лог. kind: info | cmd | ok | warn | err | raw."""
    rec = (now_human(), kind, str(text))
    with LOG_LOCK:
        LOG_BUFFER.append(rec)
        overflow = len(LOG_BUFFER) - LIMITS["log_lines"]
        if overflow > 0:
            del LOG_BUFFER[:overflow]
    LOG_QUEUE.put(rec)


def log_events():
    """Забирает накопившиеся строки лога (вызывается из UI-потока по таймеру)."""
    out = []
    while True:
        try:
            out.append(LOG_QUEUE.get_nowait())
        except queue.Empty:
            break
    return out


def log_text():
    """Весь лог одной строкой — для «Копировать» и сохранения в файл."""
    with LOG_LOCK:
        return "\n".join("[%s] %s: %s" % rec for rec in LOG_BUFFER)


def show_error(title, detail):
    """Окно с ошибкой. Если GUI не готов — только лог."""
    try:
        from tkinter import messagebox
        messagebox.showerror(APP_NAME + " — " + title, detail)
    except Exception:
        pass


def safe_action(title):
    """Декоратор обработчиков кнопок: ни одно исключение не роняет приложение."""
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except Exception as e:
                log("Сбой в действии «%s»: %s: %s" % (title, type(e).__name__, e), "err")
                log(traceback.format_exc(), "raw")
                show_error(title, "%s: %s\n\nПодробности — в лог-консоли внизу."
                           % (type(e).__name__, e))
                return None
        return wrapper
    return decorator