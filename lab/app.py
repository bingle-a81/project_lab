# lab/app.py — класс App: окно, режим экрана, темы, вкладки, автосейв, перекраска.
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .config import (APP_NAME, APP_VERSION, C, LIMITS, STAGE_IDS, STAGE_NUM,
                     START_FULLSCREEN, WINDOW_GEOMETRY, WINDOW_MIN, is_windows, set_palette)
from .disk import Scaffolder
from .export import Exporter
from .history import HistoryManager
from .prompts import PromptBuilder
from .state import AppState
from .tabs import HistoryTab, IdeaTab, SkeletonTab, StageTab, StartTab, SummaryTab
from .themes import apply_themes_config
from .utils import log
from .widgets import ConflictDialog, LogConsole, TaskRunner


class App(tk.Tk):
    """Главное окно. Держит состояние и все менеджеры, строит вкладки,
    управляет режимом экрана, перекрашивает интерфейс и автосохраняет состояние."""

    def __init__(self):
        tk.Tk.__init__(self)
        self.title(APP_NAME + " " + APP_VERSION)

        # Ядро приложения: состояние и зависимые менеджеры.
        self.state = AppState()
        self.builder = PromptBuilder(self.state)
        self.history = HistoryManager(self.state)
        self.exporter = Exporter(self.state, self.builder)
        self.tasks = TaskRunner(self)
        self._conflict_all = None
        self.scaffolder = Scaffolder(self.state,
                                     confirm=lambda t, m: messagebox.askyesno(t, m),
                                     ask_conflict=self._ask_conflict)

        # Режим окна: берём из состояния, при первом запуске — из config.START_FULLSCREEN.
        self._fullscreen_var = tk.BooleanVar(
            value=bool(self.state.data["settings"].get("fullscreen", START_FULLSCREEN)))

        # Минимальный размер не должен превышать экран (иначе окно не влезет).
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.minsize(min(WINDOW_MIN[0], max(640, sw - 40)),
                     min(WINDOW_MIN[1], max(480, sh - 80)))
        self.geometry(WINDOW_GEOMETRY)

        apply_themes_config("")                 # глобальный themes_config.json рядом с main.py
        set_palette(self.state.data["settings"].get("theme_mode", "dark"))
        self._build_menu()
        self._build_ui()
        self._configure_styles()
        self._recolor(self)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Горячие клавиши режима экрана: F11 — переключить, Esc — выйти из полного экрана.
        self.bind("<F11>", lambda e: self.toggle_fullscreen())
        self.bind("<Escape>", lambda e: self.set_fullscreen(False))
        # Применяем режим после построения окна — так надёжнее на всех оконных менеджерах.
        self.after(0, self._apply_window_mode)

        self.after(200, self._poll_log)
        self.after(LIMITS["autosave_ms"], self._autosave_loop)
        self._update_status()

    # --- режим экрана --------------------------------------------------------
    def _apply_window_mode(self):
        """Ставит окно в сохранённый режим: полный экран или развёрнутое окно."""
        try:
            if self._fullscreen_var.get():
                self.set_fullscreen(True, remember=False)
            else:
                self._maximize()
        except tk.TclError:
            pass                                  # окно уже закрыто — молча выходим
        log("Режим окна: %s. F11 — переключить полный экран, Esc — выйти из него."
            % ("полный экран" if self._fullscreen_var.get() else "развёрнутое окно"), "info")

    def _maximize(self):
        """Разворачивает окно средствами ОС. Если способ недоступен — просто большое окно."""
        # ВАЖНО: self.state занято объектом AppState, поэтому используем wm_state, а не state.
        if is_windows():
            try:
                self.wm_state("zoomed")
                return
            except tk.TclError:
                pass
        try:
            self.attributes("-zoomed", True)      # многие оконные менеджеры Linux
            return
        except tk.TclError:
            pass
        self.geometry("%dx%d+0+0" % (max(640, self.winfo_screenwidth() - 40),
                                     max(480, self.winfo_screenheight() - 80)))

    def set_fullscreen(self, on, remember=True):
        """Включает/выключает полный экран. Запоминает выбор в состоянии проекта."""
        on = bool(on)
        self._fullscreen_var.set(on)
        try:
            self.attributes("-fullscreen", on)
        except tk.TclError:
            log("Полноэкранный режим недоступен в этой системе — разворачиваю окно.", "warn")
            self._maximize()
            return
        if not on:
            self._maximize()                      # выходим не в маленькое окно, а в развёрнутое
        if remember:
            self.state.set_setting("fullscreen", on)
            self.schedule_autosave()
        self._update_status()

    def toggle_fullscreen(self):
        """F11: полный экран ↔ развёрнутое окно."""
        self.set_fullscreen(not self._fullscreen_var.get())

    def _normal_window(self):
        """Возвращает обычное окно фиксированного размера из config.WINDOW_GEOMETRY."""
        self._fullscreen_var.set(False)
        try:
            self.attributes("-fullscreen", False)
        except tk.TclError:
            pass
        try:
            self.attributes("-zoomed", False)
        except tk.TclError:
            pass
        try:
            self.wm_state("normal")
        except tk.TclError:
            pass
        self.geometry(WINDOW_GEOMETRY)
        self.state.set_setting("fullscreen", False)
        self.schedule_autosave()
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
        mfile.add_command(label="Экспорт всего", command=lambda: self.exporter.export_all())
        mfile.add_separator()
        mfile.add_command(label="Выход", command=self._on_close)
        menubar.add_cascade(label="Файл", menu=mfile)

        mview = tk.Menu(menubar, tearoff=0)
        mview.add_checkbutton(label="Полноэкранный режим", accelerator="F11",
                              variable=self._fullscreen_var,
                              command=lambda: self.set_fullscreen(self._fullscreen_var.get()))
        mview.add_command(label="Развернуть окно", accelerator="Esc",
                          command=lambda: self.set_fullscreen(False))
        mview.add_command(label="Обычное окно", command=self._normal_window)
        menubar.add_cascade(label="Вид", menu=mview)

        mtheme = tk.Menu(menubar, tearoff=0)
        mtheme.add_command(label="Тёмная тема", command=lambda: self.apply_theme("dark"))
        mtheme.add_command(label="Светлая тема", command=lambda: self.apply_theme("light"))
        menubar.add_cascade(label="Тема", menu=mtheme)

        mhelp = tk.Menu(menubar, tearoff=0)
        mhelp.add_command(label="О программе", command=self._about)
        menubar.add_cascade(label="Справка", menu=mhelp)
        self.config(menu=menubar)
        self.menubar = menubar

    # --- интерфейс ------------------------------------------------------------
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
            elif sid == "skeleton":
                tab = SkeletonTab(self.nb, self)     # здесь живут действия на диске
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

    # --- темы -----------------------------------------------------------------
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
        # Полоса прокрутки в палитре приложения: своя ширина, дорожка, ползунок и отклик.
        for orient in ("Vertical", "Horizontal"):
            name = orient + ".TScrollbar"
            style.configure(name, background=C["panel2"], troughcolor=C["bg"],
                            bordercolor=C["border"], arrowcolor=C["muted"],
                            relief="flat", borderwidth=0, width=14, arrowsize=13)
            style.map(name,
                      background=[("pressed", C["accent"]), ("active", C["accent_hi"])],
                      arrowcolor=[("pressed", C["accent_fg"]), ("active", C["accent_fg"])],
                      troughcolor=[("active", C["bg"])])

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
        self._recolor(self.start_tab.theme_row)

    # --- навигация и статус ---------------------------------------------------
    def go_to_stage(self, sid):
        """Открывает вкладку нужного этапа (индекс вкладки = номер этапа)."""
        idx = STAGE_NUM.get(sid, 0)
        if 0 <= idx < len(self.tabs):
            self.nb.select(idx)

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
        mode = "полный экран" if self._fullscreen_var.get() else "окно"
        self.statusbar.configure(
            text="Проект: %s | Утверждено: %d/%d | %s | %s (F11)%s"
                 % (self.state.name or "без имени", done, total, folder, mode, dirty),
            bg=C["panel2"], fg=C["fg"])

    # --- сохранение -----------------------------------------------------------
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

    # --- лог ------------------------------------------------------------------
    def _poll_log(self):
        self.logconsole.poll()
        self.after(200, self._poll_log)

    # --- служебное -------------------------------------------------------------
    def _about(self):
        messagebox.showinfo(APP_NAME,
                            APP_NAME + " " + APP_VERSION + "\n\n"
                            "Пошаговый конструктор проекта через промпты для внешней LLM,\n"
                            "который заодно реально создаёт проект на компьютере.\n\n"
                            "F11 — полный экран, Esc — выйти из полного экрана.\n"
                            "Только стандартная библиотека.")

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