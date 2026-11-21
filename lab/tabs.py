# lab/tabs.py — вкладки: Старт, Идея, этапы, Скелет (с действиями на диске), Итог, История.
import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .config import (APP_NAME, C, PROMPT_FILENAMES, REPORT_FILE, STATE_FILE,
                     STAGE_NUM, STAGE_TITLES)
from .disk import IMAGE_EXTS
from .prompts import (load_prompt_config, prompt_stats, stats_line,
                      write_prompt_config_template)
from .themes import (THEMES, THEME_ORDER, assemble_idea_draft, clone_presets,
                     fields_of, get_theme, idea_questions, preset_hint_for,
                     questions_from_text, questions_to_text, stage_info,
                     write_themes_config_template)
from .utils import clipboard_put, log, open_folder, safe_action
from .widgets import (ScrollFrame, ToolTip, add_button, add_entry, add_hline,
                      add_label, add_text)


def theme_tooltip(key):
    """Текст подсказки над темой: что она предлагает и сколько вопросов добавит."""
    theme = get_theme(key)
    lines = [theme.get("title", key)]
    desc = (theme.get("desc") or "").strip()
    if desc:
        lines.append(desc)
    opts = [str(o) for o in (theme.get("stack_options") or [])]
    if opts:
        lines.append("")
        lines.append("Стек: " + ", ".join(opts[:3]) + (" …" if len(opts) > 3 else ""))
    extra = [str(d) for d in (theme.get("extra_dirs") or [])]
    if extra:
        lines.append("Доп. папки: " + ", ".join(extra[:3]) + (" …" if len(extra) > 3 else ""))
    lines.append("Вопросов темы: %d (плюс 10 базовых)" % len(theme.get("questions") or []))
    lines.append("")
    lines.append("Пресеты — черновики: правьте их на «Старте».")
    return "\n".join(lines)


class StagePanel:
    """Нижняя половина любого этапа: промпт → копирование → результат → картинки → утверждение."""

    def __init__(self, parent, app, sid, collect_fn):
        self.app = app
        self.sid = sid
        self.collect_fn = collect_fn
        add_label(parent, "Контекст: " + app.builder.context_summary(sid), muted=True, kind="ctx")
        self.ctx_lbl = parent.winfo_children()[-1]
        add_label(parent, "Промпт для внешней LLM (можно править вручную)")
        self.prompt_txt = add_text(parent, rows=8)
        brow = tk.Frame(parent)
        brow.pack(fill="x", padx=4)
        add_button(brow, "Собрать промпт", self.build_prompt, "accent")
        add_button(brow, "Копировать промпт", self.copy_prompt, "warn")
        add_button(brow, "Сохранить промпт в файл", self.save_prompt, "warn")
        self.stats_lbl = add_label(parent, "", muted=True)
        add_label(parent, "Результат от внешней LLM (вставьте ответ сюда)")
        self.result_txt = add_text(parent, rows=8)
        rrow = tk.Frame(parent)
        rrow.pack(fill="x", padx=4)
        add_button(rrow, "Вставить из буфера", self.paste_result, "warn")
        add_button(rrow, "Сохранить результат", self.save_result, "warn")
        add_label(parent, "Картинки этапа (схемы, скриншоты)")
        irow = tk.Frame(parent)
        irow.pack(fill="x", padx=4)
        add_button(irow, "Прикрепить картинку", self.attach_image, "warn")
        add_button(irow, "Удалить выбранную", self.remove_image, "warn")
        add_button(irow, "Открыть папку images", self.open_images, "warn")
        self.img_list = tk.Listbox(parent, height=4)
        self.img_list.pack(fill="x", padx=8, pady=(2, 6))
        arow = tk.Frame(parent)
        arow.pack(fill="x", padx=4)
        self.approve_btn = add_button(arow, "Утвердить этап и перейти дальше", self.approve, "ok")
        add_button(arow, "Снять утверждение", self.unapprove, "warn")
        add_button(arow, "Снапшот сейчас", self.manual_snapshot, "warn")
        self.status_lbl = add_label(arow, "", kind="status")

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
        """Цветной ярлык статуса этапа."""
        st = self.app.state.stage(self.sid)
        ru = {"approved": "✓ утверждён", "draft": "черновик", "empty": "пусто"}
        self.status_lbl.configure(text=ru.get(st["status"], st["status"]))

    @safe_action("сборка промпта")
    def build_prompt(self):
        self.collect_fn()
        text = self.app.builder.build_stage_prompt(self.sid)
        self.app.state.set_prompt(self.sid, text)
        self.app.schedule_autosave()
        self.refresh()
        log("Промпт этапа «%s» собран (%d символов)."
            % (STAGE_TITLES[self.sid], prompt_stats(text)["chars"]), "ok")

    def copy_prompt(self):
        clipboard_put(self.prompt_txt, self.prompt_txt.get("1.0", "end").strip())

    def save_prompt(self):
        """Сохраняет промпт этапа в отдельный файл (полезно без полного экспорта)."""
        self.collect_fn()
        if not self.app.state.folder:
            log("Папка не выбрана.", "warn")
            return
        text = self.prompt_txt.get("1.0", "end").strip() \
            or self.app.builder.build_stage_prompt(self.sid)
        self.app.state.set_prompt(self.sid, text)
        path = os.path.join(self.app.state.folder, "prompts", PROMPT_FILENAMES[self.sid])
        os.makedirs(os.path.dirname(path), exist_ok=True)
        from .utils import atomic_write
        atomic_write(path, text)
        log("Промпт сохранён: prompts/" + PROMPT_FILENAMES[self.sid], "ok")

    def paste_result(self):
        """Вставляет ответ модели из буфера обмена в поле результата."""
        try:
            text = self.app.clipboard_get()
        except Exception:
            text = ""
        self.result_txt.delete("1.0", "end")
        self.result_txt.insert("1.0", text)
        self.save_result(quiet=True)

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
            filetypes=[("Картинки", " ".join("*" + e for e in IMAGE_EXTS)), ("Все файлы", "*.*")])
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
        add_label(body, "Этап 1. Идея — ответьте на вопросы своими словами. Варианты — "
                        "подсказки: клик добавляет текст в поле ответа.")
        self.warn_lbl = add_label(body, "", kind="warn")
        self.q_frame = tk.Frame(body)
        self.q_frame.pack(fill="x")
        add_hline(body)
        add_label(body, "Поля этапа")
        self.field_widgets = {}
        for f in fields_of("idea"):
            add_label(body, f["label"], muted=True)
            if f["hint"]:
                add_label(body, f["hint"], muted=True)
            self.field_widgets[f["key"]] = add_text(body, rows=f["rows"])
            if f["key"] == "draft":
                drow = tk.Frame(body)
                drow.pack(fill="x", padx=4)
                add_button(drow, "Собрать черновик из ответов", self.assemble_draft, "accent")
                add_button(drow, "Копировать черновик", self.copy_draft, "warn")
        self.panel = StagePanel(body, app, "idea", self.collect)
        self.refresh()

    def _render_questions(self):
        """Перестраивает мастер вопросов под текущую тему и пресеты."""
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
                    tk.Button(orow, text=opt, relief="flat",
                              command=lambda t=txt, o=opt: self._append_option(t, o)
                              ).pack(side="left", padx=2, pady=1)

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
        """Кнопка-подсказка дописывает вариант в поле ответа."""
        cur = txt.get("1.0", "end").strip()
        txt.delete("1.0", "end")
        txt.insert("1.0", (cur + " " if cur else "") + opt)

    def collect(self):
        """Собирает ответы мастера и поля в состояние."""
        for qid, txt in self.q_entries.items():
            self.app.state.set_field("idea", qid, txt.get("1.0", "end").strip())
        for key, txt in self.field_widgets.items():
            self.app.state.set_field("idea", key, txt.get("1.0", "end").strip())
        self.app.schedule_autosave()

    def assemble_draft(self):
        """Кнопка «Собрать черновик» склеивает ответы в единый текст и красит его."""
        self.collect()
        draft = assemble_idea_draft(self.app.state)
        self.field_widgets["draft"].delete("1.0", "end")
        self.field_widgets["draft"].insert("1.0", draft)
        self.app.state.set_field("idea", "draft", draft)
        self.app.schedule_autosave()
        self._colorize_draft()
        log("Черновик идеи собран.", "ok")

    def copy_draft(self):
        """Копирует чистый черновик идеи в буфер — можно вставить в LLM напрямую."""
        text = self.field_widgets["draft"].get("1.0", "end").strip()
        if not text:
            self.collect()
            text = assemble_idea_draft(self.app.state)
            self.field_widgets["draft"].delete("1.0", "end")
            self.field_widgets["draft"].insert("1.0", text)
            self._colorize_draft()
        clipboard_put(self.field_widgets["draft"], text)

    def _colorize_draft(self):
        """Раскрашивает строки черновика по смыслу: вопросы, ответы, «не заполнено», шапка."""
        txt = self.field_widgets["draft"]
        txt.tag_configure("qhead", foreground=C["accent_hi"])
        txt.tag_configure("meta", foreground=C["muted"])
        txt.tag_configure("answer", foreground=C["fg"])
        txt.tag_configure("missing", foreground=C["warn"])
        for tag in ("qhead", "meta", "answer", "missing"):
            txt.tag_remove(tag, "1.0", "end")
        for i, line in enumerate(txt.get("1.0", "end").split("\n"), start=1):
            start, end = "%d.0" % i, "%d.end" % i
            if line.startswith("• "):
                txt.tag_add("qhead", start, end)
            elif line.startswith("Тема проекта:") or line.startswith("Имя проекта:"):
                txt.tag_add("meta", start, end)
            elif line.strip():
                if ("не заполнено" in line) or ("не отмечено" in line):
                    txt.tag_add("missing", start, end)
                else:
                    txt.tag_add("answer", start, end)

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
    """Универсальная вкладка этапа: поля из STAGE_SPECS + StagePanel."""

    def __init__(self, parent, app, sid):
        self.app = app
        self.sid = sid
        self.frame = ttk.Frame(parent)
        scroll = ScrollFrame(self.frame)
        scroll.pack(fill="both", expand=True)
        body = scroll.inner
        self.body = body
        self.title = str(STAGE_NUM[sid]) + ". " + STAGE_TITLES[sid]
        add_label(body, "Этап %d. %s — %s" % (STAGE_NUM[sid], STAGE_TITLES[sid],
                                               stage_info(sid, "goal")))
        self.warn_lbl = add_label(body, "", kind="warn")
        self._build_extra_top(body)          # точка расширения для подклассов
        self.field_widgets = {}
        for f in fields_of(sid):
            add_label(body, f["label"])
            if f["hint"]:
                add_label(body, f["hint"], muted=True)
            if f["kind"] == "line":
                self.field_widgets[f["key"]] = add_entry(body)
            else:
                self.field_widgets[f["key"]] = add_text(body, rows=f["rows"])
            if preset_hint_for(app.state, sid, f["key"]):
                add_button(body, "Подставить черновик темы",
                           lambda k=f["key"]: self._apply_hint(k), kind="warn", pady=1)
        self.panel = StagePanel(body, app, sid, self.collect)
        self.refresh()

    def _build_extra_top(self, body):
        """Подклассы вставляют сюда свой блок над полями (по умолчанию пусто)."""
        pass

    def _apply_hint(self, key):
        """Вставляет черновик темы в поле, спрашивая подтверждение при непустом поле."""
        widget = self.field_widgets[key]
        current = widget.get("1.0", "end").strip() if isinstance(widget, tk.Text) else widget.get()
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
            value = widget.get("1.0", "end").strip() if isinstance(widget, tk.Text) \
                else widget.get().strip()
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


class SkeletonTab(StageTab):
    """Этап «Скелет»: поля + реальные действия на диске (перенесены со «Старта»)."""

    def __init__(self, parent, app):
        self.disk_buttons = []
        self._action_tips = []
        StageTab.__init__(self, parent, app, "skeleton")

    def _build_extra_top(self, body):
        """Панель реальных действий: структура, .venv, зависимости, git, проверка."""
        add_hline(body)
        add_label(body, "Реальные действия на диске")
        self.folder_lbl = add_label(body, "", muted=True)
        frow = tk.Frame(body)
        frow.pack(fill="x", padx=4)
        add_button(frow, "Выбрать папку", self._choose_folder, "warn")
        add_button(frow, "Открыть папку", self._open_folder, "warn")

        row1 = tk.Frame(body)
        row1.pack(fill="x", padx=4)
        row2 = tk.Frame(body)
        row2.pack(fill="x", padx=4)
        specs = [
            (row1, "Создать структуру", self._create_structure, "accent",
             "Создаёт папки src/ tests/ features/ docs/ data/ out/ scripts/\n"
             "prompts/ artifacts/ images/ history/ и стартовые файлы.\n\n"
             "В непустой папке спросит подтверждение.\n"
             "Существующие файлы не затираются молча: по каждому будет\n"
             "диалог «Пропустить / Перезаписать / Сохранить рядом (.new)»."),
            (row1, "Создать окружение .venv", self._create_venv, "accent",
             "Команда:  python -m venv .venv\n\n"
             "Запускается тем же интерпретатором, которым открыта лаборатория.\n"
             "Если .venv уже есть — спросит, пересоздавать ли.\n"
             "Выполняется в фоне, кнопки на это время блокируются."),
            (row1, "Установить зависимости", self._install_deps, "accent",
             "Windows:  .venv\\Scripts\\python.exe -m pip install -r requirements.txt\n"
             "Linux/macOS:  .venv/bin/python -m pip install -r requirements.txt\n\n"
             "Если requirements.txt пуст (только комментарии) — ставить нечего,\n"
             "команда не запускается."),
            (row2, "Инициализировать git", self._git_init, "accent",
             "git init  →  проверка .gitignore  →  git add -A  →\n"
             "git commit -m \"стартовый коммит\"\n\n"
             "Готовый репозиторий не переинициализируется, пустой коммит не создаётся.\n"
             "Если git не знает автора — покажет команды git config для этого репозитория."),
            (row2, "Проверить окружение", self._check_env, "warn",
             "Собирает отчёт: версии python / pip / git, наличие папок и файлов,\n"
             "реальная проверка права записи, состояние репозитория.\n\n"
             "Результат — в поле ниже и в artifacts/env_report.txt."),
        ]
        for row, text, cmd, kind, tip in specs:
            btn = add_button(row, text, cmd, kind)
            self.disk_buttons.append(btn)
            self._action_tips.append(ToolTip(btn, tip))

        add_label(body, "Отчёт об окружении (заполняется кнопкой «Проверить окружение»)",
                  muted=True)
        self.env_txt = add_text(body, rows=9)
        self.env_txt.configure(state="disabled")
        add_hline(body)

    # --- папка ---------------------------------------------------------------
    def _choose_folder(self):
        """Тот же выбор папки, что и на «Старте»: грузит состояние и конфиги проекта."""
        self.app.start_tab._choose_folder()
        self.refresh()

    def _open_folder(self):
        if self.app.state.folder:
            open_folder(self.app.state.folder)
        else:
            log("Папка ещё не выбрана.", "warn")

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

    # --- действия ------------------------------------------------------------
    @safe_action("создание структуры")
    def _create_structure(self):
        if not self._require_folder():
            return
        self.app.scaffolder.create_structure()      # диалоги — в UI-потоке
        self.app.update()

    def _create_venv(self):
        if not self._require_folder():
            return
        py = self.app.scaffolder.venv_python()
        force = False
        if os.path.exists(py):
            force = messagebox.askyesno("Окружение уже есть", ".venv уже существует. Пересоздать его?")
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

    def refresh(self):
        StageTab.refresh(self)
        if hasattr(self, "folder_lbl"):
            folder = self.app.state.folder
            self.folder_lbl.configure(
                text=("Папка проекта: " + folder) if folder
                else "Папка проекта не выбрана — нажмите «Выбрать папку».")


class SummaryTab(StageTab):
    """Этап «Итог»: поля сводки + мастер-промпт + кнопки экспорта."""

    def __init__(self, parent, app):
        StageTab.__init__(self, parent, app, "summary")
        body = self.body
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

    def _show_master(self):
        text = self.app.builder.build_master_prompt()
        self.master_txt.configure(state="normal")
        self.master_txt.delete("1.0", "end")
        self.master_txt.insert("1.0", text)
        self.master_txt.configure(state="disabled")
        log("Мастер-промпт собран (%d символов)." % prompt_stats(text)["chars"], "ok")

    def _export_all(self):
        self.app.exporter.export_all()
        self.app.update()

    def _export_prompts(self):
        self.app.exporter.export_prompts()

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
            self.list.insert("end", "%s | %-18s | %s | %s"
                             % (item["time"], item["reason_ru"], item["stage_ru"], item["progress"]))
        self.summary_lbl.configure(text=self.app.history.summary_line())

    def _manual(self):
        self.app.history.snapshot("manual")
        self.refresh()

    def _restore(self):
        f = self._selected()
        if not f:
            log("Выберите снапшот в списке.", "warn")
            return
        if not messagebox.askyesno("Откат", "Откатиться к выбранному снапшоту?\n"
                                            "Текущее состояние будет сохранено как «перед откатом»."):
            return
        self.app.history.restore(f)
        self.app.schedule_autosave()
        self.app.reload_all()
        self.refresh()

    def _undo(self):
        self.app.history.undo()
        self.app.schedule_autosave()
        self.app.reload_all()
        self.refresh()

    def _redo(self):
        self.app.history.redo()
        self.app.schedule_autosave()
        self.app.reload_all()
        self.refresh()

    def _preview(self):
        f = self._selected()
        if f:
            self._show(self.app.history.preview(f))

    def _changes(self):
        f = self._selected()
        if f:
            self._show(self.app.history.changes_summary(f))

    def _diff(self):
        f = self._selected()
        if f:
            self._show(self.app.history.diff_text(f))

    def _show(self, text):
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        self.detail.insert("1.0", text or "(пусто)")
        self.detail.configure(state="disabled")


class StartTab:
    """Вкладка «Старт»: тема с подсказками, пресеты, папка, внешние конфиги."""

    def __init__(self, parent, app):
        self.app = app
        self.frame = ttk.Frame(parent)
        scroll = ScrollFrame(self.frame)
        scroll.pack(fill="both", expand=True)
        body = scroll.inner
        self.title = "Старт"
        self._theme_tips = []

        # --- тема ------------------------------------------------------------
        add_label(body, "Тема проекта — наведите курсор на название, чтобы увидеть подсказку")
        self.theme_var = tk.StringVar(value=app.state.data["theme"]["key"] or "blank")
        self.theme_row = tk.Frame(body)
        self.theme_row.pack(fill="x", padx=8)
        self._build_theme_selector()
        self.theme_desc = add_label(body, get_theme("blank")["desc"], muted=True, kind="theme_desc")

        # --- имя и папка -----------------------------------------------------
        add_label(body, "Имя проекта")
        self.name_ent = add_entry(body, app.state.name)
        self.name_ent.bind("<FocusOut>", lambda e: self._on_name())
        prow = tk.Frame(body)
        prow.pack(fill="x", padx=8, pady=(4, 0))
        add_label(prow, "Папка проекта:")
        self.folder_lbl = tk.Label(prow, text=app.state.folder or "— не выбрана —", anchor="w")
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

        # --- внешние файлы настроек -----------------------------------------
        add_hline(body)
        add_label(body, "Внешние файлы настроек (правятся в любом редакторе)")
        add_label(body, "prompts_config.json — роли/правила/задачи/границы промптов; "
                        "themes_config.json — пресеты тем. Пока файлов нет — работают "
                        "стандартные значения из lab/*_defaults.json.", muted=True)
        cfgrow = tk.Frame(body)
        cfgrow.pack(fill="x", padx=8)
        add_button(cfgrow, "Шаблон настроек промптов", self._write_prompt_cfg, kind="warn")
        add_button(cfgrow, "Перечитать промпты", self._reload_prompt_cfg, kind="warn")
        add_button(cfgrow, "Шаблон пресетов тем", self._write_themes_cfg, kind="warn")
        add_button(cfgrow, "Перечитать темы", self._reload_themes_cfg, kind="warn")

        # --- куда переехали действия на диске --------------------------------
        add_hline(body)
        add_label(body, "Создание структуры, .venv, установка зависимостей, git и проверка "
                        "окружения — на вкладке «4. Скелет».", muted=True)
        navrow = tk.Frame(body)
        navrow.pack(fill="x", padx=8)
        btn = add_button(navrow, "Перейти к «4. Скелет»",
                         lambda: self.app.go_to_stage("skeleton"), kind="accent")
        ToolTip(btn, "Открывает вкладку «Скелет»: там панель реальных действий на диске\n"
                     "и отчёт об окружении.")
        self.refresh()

    def _build_theme_selector(self):
        """(Пере)строит радиокнопки тем и вешает на каждую всплывающую подсказку."""
        for tip in self._theme_tips:
            tip.hide()
        self._theme_tips = []
        for child in self.theme_row.winfo_children():
            child.destroy()
        self.theme_buttons = []
        for key in THEME_ORDER:
            title = THEMES.get(key, {}).get("title", key)
            rb = tk.Radiobutton(self.theme_row, text=title, value=key,
                                variable=self.theme_var, command=self._on_theme)
            rb.pack(side="left", padx=6, pady=2)
            self.theme_buttons.append(rb)
            self._theme_tips.append(ToolTip(rb, lambda k=key: theme_tooltip(k)))

    def _on_name(self):
        self.app.state.set_name(self.name_ent.get())
        self.app.schedule_autosave()

    def _on_theme(self):
        key = self.theme_var.get()
        theme = get_theme(key)
        current = self.app.state.data["presets"]
        filled = any((current.get(k) or "").strip() for k in ("stack", "invariants"))
        if filled and not messagebox.askyesno(
                "Смена темы", "Пресеты уже изменены. Заменить их пресетами темы «"
                + theme["title"] + "»?"):
            self.app.state.set_theme(key, theme["title"])
        else:
            self.app.state.set_theme(key, theme["title"], clone_presets(key))
        self.app.history.snapshot("theme_change", quiet=True)
        self.app.schedule_autosave()
        self.refresh()
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
        self.app.refresh_stage_tabs()
        log("Пресеты сохранены.", "ok")

    def _choose_folder(self):
        path = filedialog.askdirectory(title="Выберите папку проекта")
        if not path:
            return
        if self.app.state.set_folder(path):
            self.app.reload_themes()            # подхватить themes_config.json из папки
            state_file = os.path.join(path, STATE_FILE)
            if os.path.isfile(state_file):
                if messagebox.askyesno("Найден state.json",
                                       "В папке уже есть состояние проекта. Загрузить его?"):
                    self.app.state.load(state_file)
            self.app.history._sync_history_from_disk()
            self.app.schedule_autosave()
            self.refresh()
            self.app.refresh_stage_tabs()
            self.app.update()

    def _open_folder(self):
        if self.app.state.folder:
            open_folder(self.app.state.folder)
        else:
            log("Папка ещё не выбрана.", "warn")

    # --- внешние конфиги -----------------------------------------------------
    def _write_prompt_cfg(self):
        """Пишет файл-шаблон настроек промптов (с защитой от перезаписи)."""
        if not self.app.state.folder:
            messagebox.showwarning(APP_NAME, "Сначала выберите папку проекта.")
            return
        path = os.path.join(self.app.state.folder, "prompts_config.json")
        if os.path.isfile(path) and not messagebox.askyesno(
                "Файл уже есть", "prompts_config.json уже существует.\n"
                                 "Перезаписать его шаблоном по умолчанию? Правки будут потеряны."):
            return
        write_prompt_config_template(self.app.state.folder)

    def _reload_prompt_cfg(self):
        """Файл читается при каждой сборке промпта; здесь просто даём обратную связь."""
        cfg = load_prompt_config(self.app.state.folder)
        log("Настройки промптов перечитаны: правил — %d, границ на этапе «Идея» — %d."
            % (len(cfg["rules"]), len(cfg["stages"]["idea"]["boundaries"])), "ok")

    def _write_themes_cfg(self):
        """Пишет файл-шаблон пресетов тем (с защитой от перезаписи)."""
        if not self.app.state.folder:
            messagebox.showwarning(APP_NAME, "Сначала выберите папку проекта.")
            return
        path = os.path.join(self.app.state.folder, "themes_config.json")
        if os.path.isfile(path) and not messagebox.askyesno(
                "Файл уже есть", "themes_config.json уже существует.\n"
                                 "Перезаписать его шаблоном по умолчанию? Правки будут потеряны."):
            return
        write_themes_config_template(self.app.state.folder)

    def _reload_themes_cfg(self):
        self.app.reload_themes()

    def refresh(self):
        """Подтягивает состояние в виджеты (после загрузки/отката/смены темы)."""
        st = self.app.state
        self.name_ent.delete(0, "end")
        self.name_ent.insert(0, st.name)
        self.folder_lbl.configure(text=st.folder or "— не выбрана —")
        self.theme_var.set(st.data["theme"]["key"] or "blank")
        key = st.data["theme"]["key"] or "blank"
        self.theme_desc.configure(text=get_theme(key)["desc"])
        p = st.data["presets"]
        for widget, text in ((self.stack_txt, p.get("stack", "")),
                             (self.struct_txt, p.get("structure", "")),
                             (self.inv_txt, p.get("invariants", ""))):
            widget.delete("1.0", "end")
            widget.insert("1.0", text)
        self.q_txt.delete("1.0", "end")
        self.q_txt.insert("1.0", questions_to_text(p.get("questions") or []))