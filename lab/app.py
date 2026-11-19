
# lab/app.py — класс App: окно, темы, вкладки, автосейв, перекраска.
import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .config import APP_NAME, APP_VERSION, C, LIMITS, STAGE_IDS, STAGE_NUM, set_palette
from .disk import Scaffolder
from .export import Exporter
from .history import HistoryManager
from .prompts import PromptBuilder
from .state import AppState
from .tabs import HistoryTab, IdeaTab, StageTab, StartTab, SummaryTab
from .themes import apply_themes_config
from .utils import log
from .widgets import ConflictDialog, LogConsole


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
        self.tasks = None                       # создан ниже, после self
        self._conflict_all = None
        self.scaffolder = Scaffolder(self.state,
                                     confirm=lambda t, m: messagebox.askyesno(t, m),
                                     ask_conflict=self._ask_conflict)

        apply_themes_config("")                 # глобальный themes_config.json рядом со скриптом
        set_palette("dark")                     # тёмная тема по умолчанию
        self._build_menu()
        self._build_ui()
        from .widgets import TaskRunner
        self.tasks = TaskRunner(self)
        self._configure_styles()
        self._recolor(self)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self.after(200, self._poll_log)
        self.after(LIMITS["autosave_ms"], self._autosave_loop)
        self._update_status()

    def _ask_conflict(self, rel, old, new):
        """Если уже выбран режим «для всех» — не спрашиваем повторно."""
        if self._conflict_all in ("skip", "overwrite", "copy"):
            return self._conflict_all
        dlg = ConflictDialog(self, rel, old, new)
        if dlg.apply_all:
            self._conflict_all = dlg.result
        return dlg.result

    def _build_menu(self):
        menubar = tk.Menu(self)
        mfile = tk.Menu(menubar, tearoff=0)
        mfile.add_command(label="Сохранить состояние", command=self.save_now)
        mfile.add_command(label="Экспорт всего", command=lambda: self.exporter.export_all())
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

    def _build_ui(self):
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True)
        self.tabs = []
        self.tabs_by_sid = {}
        self.start_tab = StartTab(self.nb, self)
        self.nb.add(self.start_tab.frame, text="Старт")
        self.tabs.append(self.start_tab)
        for sid in STAGE_IDS:
            if sid == "idea":
                tab = IdeaTab(self.nb, self)
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
        # Лог-консоль внизу, общая для всех вкладок.
        self.logconsole = LogConsole(self, self)
        self.logconsole.pack(fill="x", side="bottom")
        self.statusbar = tk.Label(self, text="", anchor="w")
        self.statusbar.pack(fill="x", side="bottom")

    def _configure_styles(self):
        """Настройка ttk (Notebook, скроллбары) под текущую палитру."""
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("TNotebook", background=C["bg"], borderwidth=0)
        style.configure("TNotebook.Tab", background=C["panel"], foreground=C["fg"], padding=(12, 5))
        style.map("TNotebook.Tab", background=[("selected", C["panel2"])],
                  foreground=[("selected", C["fg"])])
        style.configure("Vertical.TScrollbar", background=C["panel2"], troughcolor=C["bg"],
                        bordercolor=C["border"], arrowcolor=C["fg"])
        style.configure("Horizontal.TScrollbar", background=C["panel2"], troughcolor=C["bg"],
                        bordercolor=C["border"], arrowcolor=C["fg"])

    def _recolor(self, widget):
        """Рекурсивно красит обычные tk-виджеты. Каждый configure обёрнут в try:
        разные виджеты принимают разные опции (у Listbox нет insertbackground)."""
        try:
            cls = widget.winfo_class()
        except Exception:
            return
        try:
            if cls in ("Frame", "Labelframe", "Canvas"):
                widget.configure(bg=C["border"] if getattr(widget, "_hline", False) else C["panel"])
            elif isinstance(widget, tk.Tk) or cls == "Toplevel":
                widget.configure(bg=C["bg"])
            elif cls == "Label":
                kind = getattr(widget, "_lbl", "normal")
                if kind == "muted":
                    fg = C["muted"]
                elif kind == "warn":
                    fg = C["warn"]
                elif kind in ("err", "status"):
                    fg = C["err"]
                elif kind == "ok":
                    fg = C["ok"]
                else:
                    fg = C["fg"]
                widget.configure(bg=C["panel"], fg=fg)
            elif cls in ("Text", "Entry"):
                widget.configure(bg=C["input"], fg=C["input_fg"], insertbackground=C["input_fg"],
                                 selectbackground=C["sel_bg"], selectforeground=C["sel_fg"],
                                 highlightbackground=C["border"], highlightcolor=C["accent"],
                                 relief="flat")
            elif cls == "Listbox":
                # У Listbox нет курсора вставки — не передаём insertbackground.
                widget.configure(bg=C["input"], fg=C["input_fg"], selectbackground=C["sel_bg"],
                                 selectforeground=C["sel_fg"], highlightbackground=C["border"],
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
                                 disabledforeground=C["muted"], relief="flat", highlightthickness=0)
            elif cls in ("Checkbutton", "Radiobutton"):
                widget.configure(bg=C["panel"], fg=C["fg"], selectcolor=C["input"],
                                 activebackground=C["panel"], activeforeground=C["fg"])
            elif cls == "Menu":
                widget.configure(bg=C["panel2"], fg=C["fg"], activebackground=C["accent"],
                                 activeforeground=C["accent_fg"])
        except tk.TclError:
            pass                              # виджет не принял опцию — пропускаем
        for child in widget.winfo_children():
            self._recolor(child)

    def apply_theme(self, mode):
        """Применяет тёмную/светлую палитру ко всему окну и запоминает выбор."""
        mode = set_palette(mode)
        self.state.set_setting("theme_mode", mode)
        self._configure_styles()
        self._recolor(self)
        self.logconsole.retag()
        self._update_status()
        log("Применена тема: " + ("тёмная" if mode == "dark" else "светлая"), "info")

    def reload_themes(self):
        """Применяет пресеты тем из внешнего файла и обновляет селектор на «Старте»."""
        apply_themes_config(self.state.folder)
        self.start_tab._build_theme_selector()
        self.start_tab.refresh()

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
                log("Не удалось обновить вкладку: " + str(e), "warn")
        self.refresh_stage_tabs()

    def reload_all(self):
        """Полное перечитывание интерфейса из состояния (используют откаты)."""
        self.start_tab.refresh()
        self.refresh_all_tabs()

    def _update_status(self):
        done, total = self.state.progress()
        folder = self.state.folder or "папка не выбрана"
        dirty = " • есть несохранённые изменения" if self.state.dirty else ""
        self.statusbar.configure(text="Проект: %s | Утверждено: %d/%d | %s%s"
                                     % (self.state.name or "без имени", done, total, folder, dirty),
                                 bg=C["panel2"], fg=C["fg"])

    def save_now(self):
        self.state.save()
        self._update_status()

    def schedule_autosave(self):
        """Просто помечаем состояние изменённым — фактически сохраняет цикл."""
        self.state.touch()

    def _autosave_loop(self):
        """Каждые ~1.5 с: если есть изменения и выбрана папка — тихо сохраняем."""
        try:
            if self.state.dirty and self.state.folder:
                self.state.save(quiet=True)
                self._update_status()
        except Exception:
            pass
        self.after(LIMITS["autosave_ms"], self._autosave_loop)

    def _poll_log(self):
        self.logconsole.poll()
        self.after(200, self._poll_log)

    def _about(self):
        messagebox.showinfo(APP_NAME,
                            APP_NAME + " " + APP_VERSION + "\n\n"
                            "Пошаговый конструктор проекта через промпты для внешней LLM,\n"
                            "который заодно реально создаёт проект на компьютере.\n"
                            "Только стандартная библиотека. Тёмная тема по умолчанию.")

    def _on_close(self):
        """Перед выходом предлагаем сохранить, если есть изменения."""
        if self.state.dirty:
            answer = messagebox.askyesnocancel("Выход", "Есть несохранённые изменения. Сохранить?")
            if answer is None:
                return
            if answer:
                if not self.state.folder:
                    path = filedialog.askdirectory(title="Выберите папку для сохранения")
                    if not path:
                        return
                    self.state.set_folder(path)
                self.state.save(quiet=True)
        self.destroy()

    def update(self):
        """Полное обновление интерфейса (обёртка, чтобы вкладки перечитали данные)."""
        self.refresh_all_tabs()
        self._update_status()