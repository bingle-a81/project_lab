# lab/prompts.py — правила, границы этапов, PromptBuilder + prompts_config.json.
import json
import os
import sys

from .config import (APP_ROOT, APP_VERSION, LIMITS, STAGE_IDS, STAGE_NUM,
                     STAGE_TITLES, WORK_STAGE_IDS)
from .themes import assemble_idea_draft, fields_of
from .utils import atomic_write, log, now_human, platform_name, shorten

PROMPT_SEP = "=" * 78
FLAG_LABELS = {"git": "Git", "venv": "Виртуальное окружение .venv",
               "tests": "Тесты", "html_report": "HTML-отчёт"}

# Путь к файлу стандартных настроек промптов — лежит рядом с этим модулем.
# Весь текст промптов живёт в этом файле, а не в коде.
_DEFAULTS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "prompts_defaults.json")


def _empty_prompt_config():
    """Пустая основа — на случай, если файл стандартных настроек отсутствует."""
    return {"role": "", "rules": [], "footer": [],
            "stages": {sid: {"task": "", "answer_sections": [], "boundaries": []}
                       for sid in STAGE_IDS}}


def default_prompt_config():
    """Стандартные настройки промптов из внешнего файла prompts_defaults.json.
    Нет файла или он битый — пустая основа и предупреждение, без падения."""
    try:
        with open(_DEFAULTS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (ValueError, OSError) as e:
        log("prompts_defaults.json не найден или бит (%s) — использую пустую основу." % e, "warn")
        return _empty_prompt_config()
    if not isinstance(data, dict):
        return _empty_prompt_config()
    data.setdefault("role", "")
    data.setdefault("rules", [])
    data.setdefault("footer", [])
    stages = data.get("stages") if isinstance(data.get("stages"), dict) else {}
    for sid in STAGE_IDS:                       # гарантия, что каждый этап на месте
        stages.setdefault(sid, {"task": "", "answer_sections": [], "boundaries": []})
    data["stages"] = stages
    return data


def numbered(items):
    """Список строк → нумерованный текст."""
    return "\n".join(str(i) + ". " + str(t) for i, t in enumerate(items, start=1))


def bullets(items):
    """Список строк → маркированный текст."""
    return "\n".join("- " + str(t) for t in items)


def render_fields(sid, fields, skip=(), include_unknown=True, skip_empty=False):
    """Поля этапа → читаемый текст «подпись → ответ».
    skip_empty=True — пустые поля не попадают в вывод (нужно для промпта)."""
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
            continue
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


def prompt_stats(text):
    """Размер промпта — чтобы человек понимал, влезет ли в окно модели."""
    text = text or ""
    return {"chars": len(text), "lines": (text.count("\n") + 1) if text else 0,
            "words": len(text.split())}


def stats_line(text):
    """Короткая строка для интерфейса под полем промпта."""
    s = prompt_stats(text)
    return "символов: %d | строк: %d | слов: %d" % (s["chars"], s["lines"], s["words"])


def strip_idea_placeholders(text):
    """Убирает из черновика строки-заполнители и «осиротевшие» заголовки вопросов."""
    lines = (text or "").split("\n")
    placeholders = ("— не заполнено —", "— не отмечено —")
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.strip().startswith("• "):
            j = i + 1
            answer = []
            while j < len(lines) and not lines[j].strip().startswith("• "):
                answer.append(lines[j])
                j += 1
            real = [a for a in answer if a.strip() and a.strip() not in placeholders]
            if real:
                out.append(line)
                out.extend(real)
            i = j
        else:
            if line.strip() not in placeholders:
                out.append(line)
            i += 1
    return "\n".join(out)


# --- prompts_config.json -----------------------------------------------------
def _find_prompt_config_path(folder):
    """Ищем prompts_config.json: сначала в папке проекта, затем в корне приложения."""
    candidates = []
    if folder:
        candidates.append(os.path.join(folder, "prompts_config.json"))
    candidates.append(os.path.join(APP_ROOT, "prompts_config.json"))
    for path in candidates:
        if os.path.isfile(path):
            return path
    return ""


def load_prompt_config(folder):
    """Читает prompts_config.json и подмешивает его к значениям по умолчанию."""
    cfg = default_prompt_config()
    path = _find_prompt_config_path(folder)
    if not path:
        return cfg
    try:
        with open(path, "r", encoding="utf-8") as f:
            user = json.load(f)
    except (ValueError, OSError) as e:
        log("Настройки промптов не прочитаны (" + str(e) + ") — значения по умолчанию.", "warn")
        return cfg
    if not isinstance(user, dict):
        return cfg
    if isinstance(user.get("role"), str) and user["role"].strip():
        cfg["role"] = user["role"].strip()
    if isinstance(user.get("rules"), list):
        cfg["rules"] = [str(r) for r in user["rules"] if str(r).strip()]
    if isinstance(user.get("footer"), list):
        cfg["footer"] = [str(x) for x in user["footer"] if str(x).strip()]
    stages = user.get("stages")
    if isinstance(stages, dict):
        for sid, block in stages.items():
            if sid not in cfg["stages"] or not isinstance(block, dict):
                continue
            if isinstance(block.get("task"), str) and block["task"].strip():
                cfg["stages"][sid]["task"] = block["task"].strip()
            if isinstance(block.get("answer_sections"), list):
                cfg["stages"][sid]["answer_sections"] = [
                    str(s) for s in block["answer_sections"] if str(s).strip()]
            if isinstance(block.get("boundaries"), list):
                cfg["stages"][sid]["boundaries"] = [
                    str(s) for s in block["boundaries"] if str(s).strip()]
    return cfg


def write_prompt_config_template(folder):
    """Пишет файл-шаблон со всеми текущими значениями для внешнего редактирования."""
    path = os.path.join(folder, "prompts_config.json")
    atomic_write(path, json.dumps(default_prompt_config(), ensure_ascii=False, indent=2))
    log("Шаблон настроек промптов записан: " + path, "ok")
    return path


class PromptBuilder:
    """Собирает промпты этапов и мастер-промпт из состояния проекта."""

    def __init__(self, state):
        self.state = state

    def _cfg(self):
        """Свежие настройки промптов: файл подмешан к значениям по умолчанию."""
        return load_prompt_config(self.state.folder)

    def context_limit(self):
        """Лимит символов на один этап в контексте (свои ответы не режем)."""
        raw = self.state.data["settings"].get("context_limit", LIMITS["context_chars"])
        try:
            value = int(raw)
        except (TypeError, ValueError):
            value = LIMITS["context_chars"]
        return max(500, value)

    def flags_line(self):
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
        approved = self.state.approved_before(sid)
        if not approved:
            return "пока пусто — это первый содержательный этап."
        return ", ".join(s["title"] for s in approved)

    def project_block(self):
        """Постоянный контекст проекта: кто, где, на чём, с какими черновиками."""
        st = self.state
        presets = st.data["presets"]
        lim = self.context_limit()
        done, total = st.progress()
        lines = ["- Имя проекта: " + (st.name or "— не задано —"),
                 "- Тема: " + (st.data["theme"]["title"] or "— не выбрана —"),
                 "- Папка проекта: " + (st.folder or "— не выбрана —"),
                 "- ОС пользователя: " + platform_name(),
                 "- Python лаборатории: " + sys.version.split()[0],
                 "- Инструменты: " + self.flags_line(),
                 "- Прогресс: утверждено %d из %d рабочих этапов" % (done, total)]
        for key, title in (("stack", "Черновик стека (предложение, не решение)"),
                           ("invariants", "Черновик инвариантов"),
                           ("structure", "Черновик структуры папок")):
            text = (presets.get(key) or "").strip()
            if text:
                lines += ["", title + ":", shorten(text, lim)]
        return "\n".join(lines)

    def previous_block(self, sid):
        """Утверждённые предыдущие этапы. Неутверждённые не подмешиваем, но перечисляем."""
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
                    body = render_fields(s["id"], s["fields"]) or "— содержимое пустое —"
                chunks.append("### Этап %d «%s» (утверждён %s)\n%s"
                              % (s["num"], s["title"], s["approved_at"] or "время не указано",
                                 shorten(body, lim)))
            text = "\n\n".join(chunks)
        missing = self.missing_previous(sid)
        if missing:
            text += ("\n\nВНИМАНИЕ: предыдущие этапы не утверждены: " + ", ".join(missing)
                     + ". Их содержимого в контексте нет — не додумывай его. Если данных не "
                       "хватает, задай вопросы.")
        return text

    def answers_block(self, sid):
        """Ответы текущего этапа. Свои ответы НЕ обрезаются. Для «Идеи» в промпт
        попадают только заполненные ответы."""
        st = self.state.stage(sid)
        if st is None:
            return "— этап неизвестен —"
        parts = []
        if sid == "idea":
            filled = assemble_idea_draft(self.state, include_empty=False)
            parts += ["Ответы наводящих вопросов (только заполненные):", filled]
            draft_raw = (st["fields"].get("draft") or "").strip()
            auto = assemble_idea_draft(self.state, include_empty=True).strip()
            if draft_raw and draft_raw != auto:
                cleaned = strip_idea_placeholders(draft_raw).strip()
                if cleaned:
                    parts += ["Черновик идеи (текст пользователя):", cleaned]
            extra = str(st["fields"].get("extra", "")).strip()
            if extra:
                parts += ["Что ещё важно знать о проекте:", extra]
            rendered = ""
        else:
            rendered = render_fields(sid, st["fields"])
        if rendered:
            parts += ["Поля этапа:", rendered]
        if not parts:
            parts = ["— поля не заполнены. Задай уточняющие вопросы и не выдумывай ответы. —"]
        return "\n\n".join(parts)

    def images_block(self, sid):
        """Список приложенных картинок. Файлы человек прикладывает к сообщению вручную."""
        st = self.state.stage(sid)
        images = st["images"] if st else []
        if not images:
            return "Картинок к этапу не приложено."
        lines = ["К этапу приложены файлы (пользователь прикладывает их к сообщению вручную):"]
        lines += ["- " + rel for rel in images]
        lines.append("Если файлы не приложены — скажи об этом и работай по текстовому описанию.")
        return "\n".join(lines)

    def task_block(self, sid, cfg):
        """Задача этапа + формат ответа + жёсткие границы (чего НЕ делать).
        Всё берётся из настроек (файла), а не из констант в коде."""
        scfg = (cfg or {}).get("stages", {}).get(sid, {})
        task = scfg.get("task") or ("Помоги с этапом «" + STAGE_TITLES.get(sid, sid) + "».")
        lines = [task]
        sections = scfg.get("answer_sections") or []
        if sections:
            lines += ["", "Ответ дай строго по секциям, с этими же заголовками:",
                      numbered(sections)]
        bounds = scfg.get("boundaries") or []
        if bounds:
            lines += ["", "ЖЁСТКИЕ ГРАНИЦЫ ЭТАПА — на этом шаге ЗАПРЕЩЕНО:", bullets(bounds)]
            lines.append("Если данных не хватает в рамках этого этапа — задай уточняющие "
                         "вопросы, а не переходи к работе других этапов.")
        return "\n".join(lines)

    def build_stage_prompt(self, sid):
        """Полный промпт одного этапа. Для «Итога» возвращает мастер-промпт."""
        if sid == "summary":
            return self.build_master_prompt()
        cfg = self._cfg()
        title = STAGE_TITLES.get(sid, sid)
        num = STAGE_NUM.get(sid, 0)
        head = [PROMPT_SEP,
                "ЛАБОРАТОРИЯ ПРОЕКТА — ПРОМПТ ЭТАПА %d/7: %s" % (num, title.upper()),
                "Проект: %s | Тема: %s" % (self.state.name or "без имени",
                                            self.state.data["theme"]["title"] or "не выбрана"),
                "Собран: %s | Лаборатория версии %s" % (now_human(), APP_VERSION),
                PROMPT_SEP, ""]
        blocks = [("1. РОЛЬ", cfg["role"]),
                  ("2. ПРАВИЛА РАБОТЫ", numbered(cfg["rules"])),
                  ("3. КОНТЕКСТ ПРОЕКТА", self.project_block()),
                  ("4. ЧТО УЖЕ УТВЕРЖДЕНО (контекст предыдущих этапов)", self.previous_block(sid)),
                  ("5. ОТВЕТЫ ТЕКУЩЕГО ЭТАПА", self.answers_block(sid)),
                  ("6. КАРТИНКИ ЭТАПА", self.images_block(sid)),
                  ("7. ЗАДАЧА, ФОРМАТ ОТВЕТА И ГРАНИЦЫ ЭТАПА", self.task_block(sid, cfg)),
                  ("8. ЧТО ВЕРНУТЬ В КОНЦЕ", bullets(cfg["footer"]))]
        body = []
        for name, text in blocks:
            body += ["## " + name, (text or "").strip(), ""]
        return "\n".join(head + body).rstrip() + "\n"

    def build_master_prompt(self):
        """Сводный промпт по всему проекту (с настройками из внешнего файла)."""
        st = self.state
        cfg = self._cfg()
        lim = self.context_limit()
        done, total = st.progress()
        head = [PROMPT_SEP, "ЛАБОРАТОРИЯ ПРОЕКТА — МАСТЕР-ПРОМПТ ПРОЕКТА",
                "Проект: %s | Тема: %s" % (st.name or "без имени",
                                            st.data["theme"]["title"] or "не выбрана"),
                "Собран: %s | Утверждено этапов: %d/%d" % (now_human(), done, total),
                PROMPT_SEP, ""]
        status_ru = {"approved": "утверждён", "draft": "черновик", "empty": "пусто"}
        toc = ["Состав проекта по этапам:"]
        for s in st.data["stages"]:
            if s["id"] == "summary":
                continue
            toc.append("- Этап %d «%s» — %s" % (s["num"], s["title"],
                                                status_ru.get(s["status"], s["status"])))
        approved_chunks = []
        truncated = False
        for s in st.data["stages"]:
            if s["id"] not in WORK_STAGE_IDS or s["status"] != "approved":
                continue
            fields_text = render_fields(s["id"], s["fields"])
            result_text = (s["llm_result"] or "").strip()
            chunk = ["### Этап %d «%s» (утверждён %s)"
                     % (s["num"], s["title"], s["approved_at"] or "время не указано")]
            if fields_text:
                chunk += ["Исходные ответы пользователя:", shorten(fields_text, lim)]
            if result_text:
                chunk += ["Утверждённый результат:", shorten(result_text, lim)]
                truncated = truncated or len(result_text) > lim
            if s["images"]:
                chunk += ["Приложенные файлы: " + ", ".join(s["images"])]
            approved_chunks.append("\n\n".join(chunk))
        if not approved_chunks:
            approved_chunks = ["Ни один этап пока не утверждён. Начни с уточняющих вопросов "
                               "и плана работ, не проектируй проект на пустом месте."]
        gaps = [s["title"] for s in st.data["stages"]
                if s["id"] in WORK_STAGE_IDS and s["status"] != "approved"]
        gaps_text = ("Не утверждены: " + ", ".join(gaps)
                     + ". Содержимого этих этапов нет — не выдумывай его, вынеси в открытые вопросы.") \
            if gaps else "Все рабочие этапы утверждены."
        summary_fields = render_fields("summary", st.stage("summary")["fields"])
        all_images = []
        for s in st.data["stages"]:
            all_images += list(s["images"])
        images_text = bullets(all_images) if all_images else "Картинок нет."
        # Задача/секции/границы «Итога» — только из настроек (файла).
        summary_scfg = cfg["stages"].get("summary", {})
        task = ((summary_scfg.get("task") or "Собери итоговую сводку.")
                + " Собери проект воедино по утверждённым этапам: не противоречь им, не переделывай "
                  "утверждённые решения без явной причины. Если между этапами есть противоречие — "
                  "назови его и предложи, какое решение считать главным.")
        sections = summary_scfg.get("answer_sections") or []
        bounds = summary_scfg.get("boundaries") or []
        task_text = task + "\n\nОтвет дай строго по секциям:\n" + numbered(sections)
        if bounds:
            task_text += "\n\nЖЁСТКИЕ ГРАНИЦЫ:\n" + bullets(bounds)
        blocks = [("1. РОЛЬ", cfg["role"]),
                  ("2. ПРАВИЛА РАБОТЫ", numbered(cfg["rules"])),
                  ("3. КОНТЕКСТ ПРОЕКТА", self.project_block()),
                  ("4. СОСТАВ И СОСТОЯНИЕ ЭТАПОВ", "\n".join(toc)),
                  ("5. УТВЕРЖДЁННЫЕ ЭТАПЫ (главный источник истины)", "\n\n".join(approved_chunks)),
                  ("6. ПРОБЕЛЫ", gaps_text),
                  ("7. ПОЖЕЛАНИЯ К ИТОГУ", summary_fields or "— не заполнены —"),
                  ("8. ЗАДАЧА И ФОРМАТ ОТВЕТА", task_text),
                  ("9. ПРИЛОЖЕННЫЕ ФАЙЛЫ", images_text),
                  ("10. ЧТО ВЕРНУТЬ В КОНЦЕ", bullets(cfg["footer"]))]
        body = []
        for name, text in blocks:
            body += ["## " + name, (text or "").strip(), ""]
        if truncated:
            body += ["Примечание: длинные результаты обрезаны по %d символов на этап. "
                     "Полные версии лежат в artifacts/ проекта." % lim, ""]
        return "\n".join(head + body).rstrip() + "\n"

    def build_all(self):
        """Свежие промпты всех этапов — для кнопки «Экспорт всего»."""
        return {sid: self.build_stage_prompt(sid) for sid in STAGE_IDS}