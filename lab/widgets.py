# lab/widgets.py — виджеты, прокрутка колесом/тачпадом, подсказки, лог-консоль, задачи.
import os
import sys
import threading
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

from .config import C, FONT_MONO_CANDIDATES, FONT_MONO_SIZE, FONT_UI_SIZE
from .utils import atomic_write, clipboard_put, ensure_dir, log, log_events, log_text

WHEEL_STEP = 96          # пикселей прокрутки на один щелчок колеса
WHEEL_FALLBACK_LINE = 18 # запасная высота строки, если шрифт ещё не измерен


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


def get_ui_font():
    """Пропорциональный шрифт интерфейса — для подсказок (читать прозу легче)."""
    try:
        f = tkfont.nametofont("TkDefaultFont").copy()
        f.configure(size=FONT_UI_SIZE)
        return f
    except Exception:
        return (get_mono_family(), FONT_UI_SIZE)


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


class ToolTip:
    """Всплывающая подсказка НАД виджетом.

    text — строка или функция без аргументов (текст берётся в момент показа,
    поэтому подхватывает актуальные данные и текущую палитру)."""

    def __init__(self, widget, text, delay=420, wrap=420):
        self.widget = widget
        self.text = text
        self.delay = delay
        self.wrap = wrap
        self._after = None
        self._tip = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self.hide, add="+")
        widget.bind("<ButtonPress>", self.hide, add="+")
        widget.bind("<Destroy>", self.hide, add="+")

    def _schedule(self, event=None):
        """Ставит показ на таймер: подсказка не мигает при быстром проходе мышью."""
        self._cancel()
        try:
            self._after = self.widget.after(self.delay, self._show)
        except tk.TclError:
            self._after = None

    def _cancel(self):
        if self._after:
            try:
                self.widget.after_cancel(self._after)
            except tk.TclError:
                pass
            self._after = None

    def _show(self):
        """Создаёт окошко подсказки над виджетом (или под ним, если сверху нет места)."""
        self._after = None
        if self._tip is not None:
            return
        try:
            if not self.widget.winfo_exists():
                return
        except tk.TclError:
            return
        text = self.text() if callable(self.text) else self.text
        if not text:
            return
        try:
            tip = tk.Toplevel(self.widget)
            tip.wm_overrideredirect(True)
            try:
                tip.attributes("-topmost", True)
            except tk.TclError:
                pass
            border = tk.Frame(tip, bg=C["accent"], padx=1, pady=1)
            border.pack(fill="both", expand=True)
            inner = tk.Frame(border, bg=C["panel2"])
            inner.pack(fill="both", expand=True)
            tk.Label(inner, text=text, justify="left", anchor="w",
                     bg=C["panel2"], fg=C["fg"], wraplength=self.wrap,
                     font=get_ui_font(), padx=12, pady=9).pack()
            tip.update_idletasks()
            w, h = tip.winfo_reqwidth(), tip.winfo_reqheight()
            x = self.widget.winfo_rootx()
            y = self.widget.winfo_rooty() - h - 8
            if y < 4:
                y = self.widget.winfo_rooty() + self.widget.winfo_height() + 8
            screen_w = self.widget.winfo_screenwidth()
            if x + w > screen_w - 8:
                x = max(8, screen_w - w - 8)
            tip.wm_geometry("+%d+%d" % (int(x), int(y)))
            self._tip = tip
        except tk.TclError:
            self._tip = None

    def hide(self, event=None):
        """Убирает подсказку и снимает таймер. Безопасно вызывать повторно."""
        self._cancel()
        if self._tip is not None:
            try:
                self._tip.destroy()
            except tk.TclError:
                pass
            self._tip = None


class ScrollFrame(tk.Frame):
    """Прокручиваемая страница вкладки: колесо, тачпад, перетаскивание полосы.
    Полоса и её цвета берутся из палитры через стиль Vertical.TScrollbar."""

    def __init__(self, parent):
        tk.Frame.__init__(self, parent)
        self.canvas = tk.Canvas(self, borderwidth=0, highlightthickness=0, takefocus=0)
        self.vsb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview,
                                 style="Vertical.TScrollbar")
        self.canvas.configure(yscrollcommand=self.vsb.set)
        self.vsb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner = tk.Frame(self.canvas)
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", self._on_inner_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        # Один общий обработчик колеса на окно — работает на всех вкладках сразу.
        install_wheel_scrolling(self.winfo_toplevel())

    def _on_inner_configure(self, event=None):
        """Содержимое изменило размер — обновляем область прокрутки."""
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        """Ширина страницы follows ширине окна: текст не уезжает вбок."""
        self.canvas.itemconfigure(self._win, width=event.width)
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def scroll_by(self, pixels):
        """Плавно сдвигает страницу на дробное число пикселей (тачпад шлёт мелкие шаги)."""
        bbox = self.canvas.bbox("all")
        if not bbox:
            return
        content = float(bbox[3] - bbox[1])
        view = float(self.canvas.winfo_height())
        if content <= view:
            return
        first = self.canvas.yview()[0]
        self.canvas.yview_moveto(max(0.0, min(1.0, first + pixels / content)))


def _wheel_pixels(event):
    """Переводит событие колеса/тачпада в пиксели (вниз — положительно)."""
    num = getattr(event, "num", None)
    if num == 4:                       # Linux: колесо вверх
        return -WHEEL_STEP
    if num == 5:                       # Linux: колесо вниз
        return WHEEL_STEP
    delta = getattr(event, "delta", 0) or 0
    if not delta:
        return 0
    if sys.platform == "darwin":       # macOS: delta уже в «строках»
        return -delta * 16
    # Windows: колесо даёт ±120, точный тачпад — мелкие дробные значения.
    return (delta / 120.0) * WHEEL_STEP


def _line_height(widget):
    """Высота строки внутреннего виджета — чтобы шаг прокрутки был естественным."""
    try:
        if isinstance(widget, tk.Text):
            info = widget.dlineinfo("1.0")
            if info:
                return max(1, info[3])
    except tk.TclError:
        pass
    try:
        return max(1, tkfont.Font(font=widget.cget("font")).metrics("linespace"))
    except Exception:
        return WHEEL_FALLBACK_LINE


def _scroll_inner(widget, pixels):
    """Прокручивает сам виджет. False — он на краю, и событие уходит странице."""
    try:
        first, last = widget.yview()
    except tk.TclError:
        return False
    if last - first >= 0.999:          # всё влезает — скроллить нечего
        return False
    if pixels < 0 and first <= 0.0001:  # уже наверху
        return False
    if pixels > 0 and last >= 0.9999:   # уже внизу
        return False
    units = int(round(pixels / float(_line_height(widget))))
    if units == 0:
        units = 1 if pixels > 0 else -1
    widget.yview_scroll(units, "units")
    return True


def _find_scroll_frame(widget):
    """Поднимается по родителям до страницы вкладки, которой принадлежит виджет."""
    w = widget
    while w is not None:
        if isinstance(w, ScrollFrame):
            return w
        w = getattr(w, "master", None)
    return None


def _dispatch_wheel(event):
    """Единый обработчик: сначала внутренний виджет, затем страница под курсором."""
    try:
        root = event.widget.winfo_toplevel()
        target = root.winfo_containing(event.x_root, event.y_root)
    except (tk.TclError, AttributeError):
        return None
    if target is None:
        return None
    pixels = _wheel_pixels(event)
    if not pixels:
        return None
    if isinstance(target, (tk.Text, tk.Listbox)) and _scroll_inner(target, pixels):
        return "break"
    page = _find_scroll_frame(target)
    if page is not None:
        page.scroll_by(pixels)
        return "break"
    return None


def install_wheel_scrolling(root):
    """Вешает прокрутку один раз на окно.

    Классовые привязки Text/Listbox переопределяются: иначе их собственная
    прокрутка сработала бы раньше нашей и страница прыгала бы дважды."""
    if getattr(root, "_lab_wheel_installed", False):
        return
    root._lab_wheel_installed = True
    for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
        root.bind_all(seq, _dispatch_wheel, add="+")
        for cls in ("Text", "Listbox"):
            root.bind_class(cls, seq, _dispatch_wheel)


class LogConsole(tk.Frame):
    """Лог-консоль внизу окна: своя полоса прокрутки, колесо и цвета по типу строк."""

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

        body = tk.Frame(self)
        body.pack(fill="both", expand=True, padx=4, pady=(2, 4))
        self.vsb = ttk.Scrollbar(body, orient="vertical", style="Vertical.TScrollbar")
        self.vsb.pack(side="right", fill="y")
        self.text = tk.Text(body, height=8, wrap="word", state="disabled", undo=False,
                            font=(get_mono_family(), FONT_MONO_SIZE),
                            yscrollcommand=self.vsb.set)
        self.text.pack(side="left", fill="both", expand=True)
        self.vsb.configure(command=self.text.yview)

        self.retag()
        install_wheel_scrolling(self.winfo_toplevel())
        for t, k, m in log_events():
            self.append(t, k, m)

    def retag(self):
        """Перенастраивает цвета строк — вызывается при смене темы."""
        for kind, color in (("cmd", C["log_cmd"]), ("ok", C["log_ok"]), ("err", C["log_err"]),
                            ("warn", C["log_warn"]), ("raw", C["log_raw"]), ("info", C["log_info"])):
            self.text.tag_configure(kind, foreground=color)

    def append(self, when, kind, msg):
        """Добавляет строку, не сбивая позицию прокрутки, если человек читает выше."""
        try:
            at_bottom = self.text.yview()[1] >= 0.999
        except tk.TclError:
            at_bottom = True
        self.text.configure(state="normal")
        self.text.insert("end", "[" + when + "] " + msg + "\n", kind)
        self.text.configure(state="disabled")
        if at_bottom:
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