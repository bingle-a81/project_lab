# lab/widgets.py — виджеты, лог-консоль, фоновые задачи, диалог конфликта.
import threading
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk


#LogConsole использует os для пути — добавим импорт
import os  # noqa: E402

from .config import C, FONT_MONO_CANDIDATES, FONT_MONO_SIZE
from .utils import atomic_write, clipboard_put, ensure_dir, log, log_events, log_text


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
    """Многострочное поле ввода."""
    return _pack(tk.Text(parent, height=rows, wrap="word", undo=True, relief="flat",
                         font=(get_mono_family(), FONT_MONO_SIZE)))


def add_entry(parent, text=""):
    """Однострочное поле ввода."""
    ent = tk.Entry(parent, relief="flat", font=(get_mono_family(), FONT_MONO_SIZE))
    if text:
        ent.insert(0, text)
    return _pack(ent)


def _pack(widget):
    widget.pack(fill="x", padx=8, pady=(2, 6))
    return widget


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
    """Прокручиваемая область: длинная форма этапа не обрезается по высоте окна."""

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


class LogConsole(tk.Frame):
    """Лог-консоль внизу окна. Забирает строки из очереди по таймеру, красит по типу."""

    def __init__(self, parent, app):
        tk.Frame.__init__(self, parent)
        self.app = app
        bar = tk.Frame(self)
        bar.pack(fill="x")
        tk.Label(bar, text="Лог-консоль", anchor="w").pack(side="left", padx=8)
        tk.Button(bar, text="Копировать всё",
                  command=lambda: clipboard_put(self, log_text())).pack(side="right", padx=4)
        tk.Button(bar, text="Сохранить в файл", command=self._save).pack(side="right", padx=4)
        tk.Button(bar, text="Очистить", command=self.clear).pack(side="right", padx=4)
        self.text = tk.Text(self, height=8, wrap="word", state="disabled", undo=False,
                            font=(get_mono_family(), FONT_MONO_SIZE))
        self.text.pack(fill="both", expand=True, padx=4, pady=(2, 4))
        self.retag()
        for t, k, m in log_events():
            self.append(t, k, m)

    def retag(self):
        """Перенастраивает цвета строк — вызывается при смене темы."""
        for kind, color in (("cmd", C["log_cmd"]), ("ok", C["log_ok"]), ("err", C["log_err"]),
                            ("warn", C["log_warn"]), ("raw", C["log_raw"]), ("info", C["log_info"])):
            self.text.tag_configure(kind, foreground=color)

    def append(self, when, kind, msg):
        """Добавляет одну строку. Теги красят её по типу."""
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
    через app.after — напрямую трогать tkinter из потока нельзя."""

    def __init__(self, app):
        self.app = app

    def submit(self, fn, on_done=None, label=""):
        def worker():
            try:
                result = fn()
            except Exception as e:
                log("Сбой фоновой задачи «" + (label or "?") + "»: " + str(e), "err")
                result = None
            self.app.after(0, lambda r=result: on_done(r) if on_done else None)
        threading.Thread(target=worker, daemon=True).start()


class ConflictDialog(tk.Toplevel):
    """Диалог разрешения конфликта файла: пропустить / перезаписать / сохранить рядом."""

    def __init__(self, parent, rel, old, new):
        tk.Toplevel.__init__(self, parent)
        self.title("Файл уже существует")
        self.result = "skip"
        self.apply_all = False
        self.transient(parent)
        self.grab_set()
        add_label(self, "Файл уже существует и отличается от заготовки:")
        add_label(self, rel, kind="err")
        add_label(self, "Старый размер: %d симв. | Новая заготовка: %d симв."
                  % (len(old or ""), len(new or "")), muted=True)
        self.var_all = tk.BooleanVar(value=False)
        tk.Checkbutton(self, text="Применить ко всем файлам",
                       variable=self.var_all).pack(anchor="w", padx=8, pady=4)
        row = tk.Frame(self)
        row.pack(pady=8)
        tk.Button(row, text="Пропустить (оставить мой)",
                  command=lambda: self._done("skip")).pack(side="left", padx=4)
        tk.Button(row, text="Перезаписать",
                  command=lambda: self._done("overwrite")).pack(side="left", padx=4)
        tk.Button(row, text="Сохранить рядом (.new)",
                  command=lambda: self._done("copy")).pack(side="left", padx=4)
        self.wait_window(self)

    def _done(self, choice):
        self.result = choice
        self.apply_all = bool(self.var_all.get())
        self.destroy()