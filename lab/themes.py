# lab/themes.py — пресеты тем, поля этапов, наводящие вопросы + themes_config.
import copy
import json
import os

from .config import APP_ROOT, BASE_DIRS
from .utils import atomic_write, log, sanitize_name

# Общая приписка к любому черновику — чтобы человек не принял его за решение.
# Подставляется к стеку и инвариантам при загрузке пресетов (см. _with_disclaimer).
PRESET_DISCLAIMER = (
    "# ЧЕРНОВИК-ПРЕДЛОЖЕНИЕ, а не готовый ответ. Правьте под себя.\n"
    "# Внешние библиотеки — только если вы их согласовали; наличие и версии\n"
    "# помечайте как ТРЕБУЕТ ПРОВЕРКИ. Сама «Лаборатория» использует только stdlib.\n")


def make_question(qid, question, hint="", options=None):
    """Единый формат наводящего вопроса. options — подсказки для клика, не ответы."""
    return {"id": qid, "kind": "question", "question": question,
            "hint": hint, "options": list(options or [])}


def make_field(key, label, kind="text", hint="", rows=4, options=None):
    """Единый формат поля этапа. kind: line | text | checks."""
    return {"key": key, "label": label, "kind": kind, "hint": hint,
            "rows": int(rows), "options": list(options or [])}


# --- 10 базовых вопросов «Идеи» (одинаковы для всех тем) --------------------
IDEA_QUESTIONS = [
    make_question("one_liner", "Что делает проект — одним предложением?",
                  "Формула: «Инструмент, который помогает <кому> делать <что> из <чего>».",
                  ["Собирает данные из … и складывает в …", "Считает … по правилам …",
                   "Готовит отчёт о …", "Управляет … через …"]),
    make_question("user", "Кто пользователь?",
                  "Один человек или отдел? Работает сам или запускает по расписанию?",
                  ["Только я", "Коллеги / отдел", "Внешние заказчики",
                   "Другая программа (по API)", "Оператор у станка/пульта"]),
    make_question("input", "Что на входе?", "Форматы, откуда берётся, кто кладёт.",
                  ["Файлы (csv / xlsx / pdf)", "Сайт / веб-страницы", "Ручной ввод",
                   "Другое ПО / API", "Оборудование / порт"]),
    make_question("output", "Что на выходе?", "Что именно человек получает и куда кладётся.",
                  ["Файл (csv / xlsx / pdf)", "HTML-отчёт", "Графики",
                   "Код / конфиг для другого ПО", "Команды оборудованию", "Запись в БД"]),
    make_question("internet", "Нужен ли доступ в интернет?",
                  "Если да — куда именно и что будет, когда связи нет.",
                  ["Нет, полностью оффлайн", "Да, только чтение данных",
                   "Да, API стороннего сервиса", "Не знаю — уточнить"]),
    make_question("data", "Откуда данные, какой объём, нужно ли хранить историю?",
                  "Источник, сколько записей/файлов за раз, как часто, сколько хранить.",
                  ["До 1 тыс. записей", "1 тыс. — 1 млн", "Поток / постоянно",
                   "Историю хранить обязательно", "История не нужна"]),
    make_question("external", "Есть ли внешнее ПО, лицензии, ключи?",
                  "Что должно быть установлено, кто выдаёт доступ, где лежат ключи.",
                  ["Нет", "Excel / 1С / CRM", "CAD / CAE / CAM",
                   "Лицензионный сервер или ключ", "API-ключи (в .env)"]),
    make_question("limits", "Ограничения: оффлайн, бюджет, время?",
                  "Что нельзя нарушить: сроки, деньги, права администратора, политика ИБ.",
                  ["Только оффлайн", "Бюджет 0 — только бесплатное", "Срок — дни",
                   "Срок — недели", "Работа без прав администратора"]),
    make_question("stack", "Какой стек предпочитаешь?",
                  "Варианты ниже — предложения для выбранной темы. Можно оставить пусто.", []),
    {"id": "tooling", "kind": "flags", "question": "Что подключаем сразу?",
     "hint": "Отметьте нужное. Кнопки на «Старте» работают независимо от галочек.",
     "flags": [("git", "Git и первый коммит"), ("venv", "Виртуальное окружение .venv"),
               ("tests", "Тесты (pytest / unittest)"), ("html_report", "HTML-отчёт")]},
]

# --- Пресеты тем: стандартные значения во внешнем файле ---------------------
# Путь к файлу стандартных пресетов тем — лежит рядом с этим модулем.
# Все пресеты тем живут в этом файле, а не в коде.
_THEMES_DEFAULTS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     "themes_defaults.json")


def _blank_theme():
    """Минимальная тема-запас, чтобы приложение работало без файла пресетов."""
    return {"title": "Другое (чистый лист)", "desc": "", "stack": "",
            "stack_options": [], "extra_dirs": [], "questions": [], "invariants": ""}


def _load_theme_defaults_raw():
    """Читает themes_defaults.json как есть. Нет файла или он битый — тема «blank»."""
    fallback_order = ["blank"]
    fallback_themes = {"blank": _blank_theme()}
    try:
        with open(_THEMES_DEFAULTS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (ValueError, OSError) as e:
        log("themes_defaults.json не найден или бит (%s) — доступна только тема «blank»." % e, "warn")
        return fallback_order, fallback_themes
    if not isinstance(data, dict):
        return fallback_order, fallback_themes
    themes = data.get("themes") if isinstance(data.get("themes"), dict) else fallback_themes
    if not themes:
        themes = fallback_themes
    order = data.get("order") if isinstance(data.get("order"), list) else list(themes.keys())
    order = [k for k in order if k in themes] or list(themes.keys())
    return order, themes


def _with_disclaimer(themes):
    """Добавляет шапку-дисклеймер к стеку и инвариантам каждой темы (если её ещё нет)."""
    out = {}
    for key, theme in themes.items():
        t = dict(theme)
        for field in ("stack", "invariants"):
            val = t.get(field) or ""
            if val and not val.startswith("#"):
                t[field] = PRESET_DISCLAIMER + val
        out[key] = t
    return out


# «Живые» пресеты: по умолчанию из файла, заменяются themes_config.json через
# apply_themes_config(). Весь остальной код читает именно их.
_init_order, _init_themes = _load_theme_defaults_raw()
THEMES = _with_disclaimer(_init_themes)
THEME_ORDER = list(_init_order)
THEME_TITLES = [(k, THEMES[k].get("title", k)) for k in THEME_ORDER]


def get_theme(key):
    """Тема по ключу. Неизвестный ключ → «чистый лист», а не ошибка."""
    return THEMES.get(key, THEMES["blank"])


def theme_title(key):
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
    """Копия пресетов темы в формат state['presets'] (копия, не ссылка)."""
    theme = get_theme(key)
    return {"stack": theme["stack"], "structure": structure_text(key),
            "questions": copy.deepcopy(theme["questions"]), "invariants": theme["invariants"]}


def questions_to_text(questions):
    """Вопросы темы → редактируемый текст (один вопрос на строку)."""
    lines = ["# Формат:  id | вопрос | подсказка | вариант1; вариант2",
             "# Это черновик вопросов темы. Строки с # игнорируются."]
    for qd in questions or []:
        if not isinstance(qd, dict) or qd.get("kind") == "flags":
            continue
        lines.append(" | ".join([qd.get("id", ""), qd.get("question", ""),
                                 qd.get("hint", ""), "; ".join(qd.get("options") or [])]))
    return "\n".join(lines)


def questions_from_text(text):
    """Текст пользователя → список вопросов. Терпим к неполным строкам."""
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
    """Полный список вопросов «Идеи»: 10 базовых + вопросы темы (галочки в конце)."""
    theme = get_theme(state.data["theme"]["key"])
    base = copy.deepcopy(IDEA_QUESTIONS)
    for qd in base:
        if qd["id"] == "stack":
            qd["options"] = list(theme.get("stack_options") or [])
    extras = state.data["presets"].get("questions")
    if not isinstance(extras, list) or not extras:
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
        head.append(make_question(qid, qd["question"], qd.get("hint", ""), qd.get("options") or []))
        seen.add(qid)
    return head + tail


def assemble_idea_draft(state, include_empty=True):
    """Склеивает ответы мастера в черновик идеи.
    include_empty=True — для экрана (пустые помечаются); False — для промпта (пустые не идут)."""
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
            if include_empty:
                lines.append("• %s" % qd["question"])
                lines.append("  " + ("— не отмечено —" if qd.get("kind") == "flags"
                                     else "— не заполнено —"))
            continue
        lines.append("• %s" % qd["question"])
        lines.append("  " + answer.replace("\n", "\n  "))
    return "\n".join(lines)


# --- Описания этапов ---------------------------------------------------------
# Примечание: текст промптов (задача, секции ответа, границы) теперь живёт в
# prompts_defaults.json; здесь оставлены цель и структура полей формы.
STAGE_SPECS = {
    "idea": {"goal": "Собрать ответы на наводящие вопросы и получить черновик идеи.",
             "fields": [make_field("draft", "Черновик идеи (собирается из ответов, можно править)",
                                   "text", "Нажмите «Собрать черновик» или напишите сами.", 10),
                        make_field("extra", "Что ещё важно знать о проекте", "text",
                                   "Контекст, который не покрыт вопросами.", 4)]},
    "charter": {"goal": "Зафиксировать цель, границы и критерии готовности проекта.",
                "fields": [make_field("goal", "Цель: какой результат считаем успехом", "text", "", 4),
                           make_field("scope_in", "Что входит в первую версию", "text", "", 4),
                           make_field("scope_out", "Что НЕ делаем (границы)", "text", "", 4),
                           make_field("done_criteria", "Критерии готовности — как проверим", "text", "", 5),
                           make_field("invariants", "Инварианты — что не должно ломаться никогда", "text",
                                      "Есть черновик темы — кнопка «Подставить черновик».", 5),
                           make_field("constraints", "Ограничения: оффлайн, бюджет, время, права", "text", "", 3),
                           make_field("data_policy", "Данные: источник, объём, история, приватность", "text", "", 3),
                           make_field("licenses", "Внешнее ПО, лицензии, ключи", "text", "", 2),
                           make_field("risks", "Риски и что с ними делаем", "text", "", 4),
                           make_field("nfr", "Нефункциональные требования", "text", "", 3)]},
    "arch": {"goal": "Разложить проект на модули и описать потоки данных и контракты.",
             "fields": [make_field("modules", "Модули и их ответственность", "text", "", 6),
                        make_field("data_flow", "Поток данных: вход → шаги → выход", "text", "", 5),
                        make_field("contracts", "Интерфейсы и контракты", "text", "", 5),
                        make_field("formats", "Форматы файлов и структура данных", "text", "", 3),
                        make_field("deps", "Зависимости и почему они нужны", "text",
                                   "Есть черновик стека темы — кнопка «Подставить черновик».", 3),
                        make_field("errors_logging", "Ошибки, логи, диагностика", "text", "", 4),
                        make_field("config", "Конфигурация и секреты (.env)", "text", "", 3),
                        make_field("diagram_note", "Что изображено на приложенной схеме", "line", "", 1)]},
    "skeleton": {"goal": "Получить дерево файлов и заготовки, которые можно сразу создать.",
                 "fields": [make_field("tree", "Дерево файлов первой версии", "text",
                                       "Есть черновик структуры темы — кнопка «Подставить черновик».", 8),
                            make_field("entrypoints", "Точки входа: что и чем запускаем", "text", "", 3),
                            make_field("stubs", "Что должно быть в заготовках", "text", "", 5),
                            make_field("requirements", "Зависимости для requirements.txt", "text",
                                       "Пустой файл — тоже нормальный старт.", 3),
                            make_field("run_how", "Как запускать и проверять", "text", "", 3),
                            make_field("config_files", "Служебные файлы: .env.example, pytest.ini, .gitignore",
                                       "text", "", 3)]},
    "feature": {"goal": "Описать первую полезную функцию и критерии её приёмки.",
                "fields": [make_field("feature_name", "Название фичи", "line", "", 1),
                           make_field("user_story", "Что делает фича для пользователя", "text", "", 3),
                           make_field("acceptance", "Критерии приёмки", "text", "", 4),
                           make_field("io_example", "Пример входа и ожидаемого выхода", "text", "", 4),
                           make_field("changes", "Какие файлы скелета меняем", "text", "", 4),
                           make_field("tests", "Тест-кейсы", "text", "", 4),
                           make_field("edge_cases", "Краевые случаи и что делать при ошибке", "text", "", 3)]},
    "debug": {"goal": "Разобрать ошибку: воспроизведение, причина, фикс, регресс-тест.",
              "fields": [make_field("symptom", "Симптом: что видим", "text", "", 3),
                         make_field("reproduce", "Шаги воспроизведения", "text", "", 4),
                         make_field("expected_actual", "Ожидание и факт", "text", "", 3),
                         make_field("logs", "Логи и текст ошибки", "text", "Вставляйте как есть.", 5),
                         make_field("hypotheses", "Гипотезы и что уже проверено", "text", "", 3),
                         make_field("fix", "Что меняем (если уже понятно)", "text", "", 4),
                         make_field("regression", "Как поймать это в будущем (регресс-тест)", "text", "", 3)]},
    "summary": {"goal": "Собрать мастер-промпт и выгрузить всю конструкцию проекта.",
                "fields": [make_field("final_notes", "Что дописать в мастер-промпт от себя", "text", "", 4),
                           make_field("checklist", "Чек-лист готовности", "text", "", 5),
                           make_field("next_steps", "Следующие шаги после первой версии", "text", "", 3)]},
}

# Какие поля могут быть предзаполнены черновиком темы (по кнопке, не автоматически).
PRESET_HINT_MAP = {
    ("idea", "stack"): "stack", ("charter", "invariants"): "invariants",
    ("arch", "deps"): "stack", ("skeleton", "tree"): "structure",
    ("skeleton", "requirements"): "stack",
}


def fields_of(sid):
    """Список полей этапа (пустой список для неизвестного id)."""
    return STAGE_SPECS.get(sid, {}).get("fields", [])


def stage_info(sid, key, default=""):
    """Безопасный доступ к описанию этапа: например, goal."""
    return STAGE_SPECS.get(sid, {}).get(key, default)


def preset_hint_for(state, sid, key):
    """Текст черновика темы для конкретного поля. Пустая строка = кнопки нет."""
    preset_key = PRESET_HINT_MAP.get((sid, key))
    if not preset_key:
        return ""
    return state.data["presets"].get(preset_key, "") or ""


# --- themes_config.json ------------------------------------------------------
def default_themes_config():
    """Стандартные пресеты тем из внешнего файла — они же идут в файл-шаблон."""
    order, themes = _load_theme_defaults_raw()
    return {"order": list(order), "themes": _with_disclaimer(themes)}


def _find_themes_config_path(folder):
    """Ищем themes_config.json: сначала в папке проекта, затем в корне приложения."""
    candidates = []
    if folder:
        candidates.append(os.path.join(folder, "themes_config.json"))
    candidates.append(os.path.join(APP_ROOT, "themes_config.json"))
    for path in candidates:
        if os.path.isfile(path):
            return path
    return ""


def _normalize_question(q, idx):
    """Приводит вопрос из файла к единому формату (как после make_question)."""
    return {"id": str(q.get("id") or ("q%d" % idx)), "kind": "question",
            "question": str(q.get("question") or ""), "hint": str(q.get("hint") or ""),
            "options": [str(o) for o in (q.get("options") or [])]}


def load_themes_config(folder):
    """Возвращает (порядок, темы) — эффективные пресеты: файл поверх стандарта.
    Битый или отсутствующий файл не ломает приложение."""
    order, themes = _load_theme_defaults_raw()
    themes = _with_disclaimer(themes)
    order = list(order)
    path = _find_themes_config_path(folder)
    if not path:
        return order, themes
    try:
        with open(path, "r", encoding="utf-8") as f:
            user = json.load(f)
    except (ValueError, OSError) as e:
        log("Настройки тем не прочитаны (" + str(e) + ") — использую стандартные.", "warn")
        return order, themes
    if not isinstance(user, dict):
        return order, themes
    uthemes = user.get("themes")
    if isinstance(uthemes, dict):
        for key, block in uthemes.items():
            if not isinstance(block, dict):
                continue
            if key not in themes:                 # новая тема, добавленная пользователем
                themes[key] = _blank_theme()
                themes[key]["title"] = key
            for field in ("title", "desc", "stack", "invariants"):
                if isinstance(block.get(field), str):
                    themes[key][field] = block[field]
            for field in ("stack_options", "extra_dirs"):
                if isinstance(block.get(field), list):
                    themes[key][field] = [str(x) for x in block[field]]
            if isinstance(block.get("questions"), list):
                themes[key]["questions"] = [_normalize_question(q, i)
                                            for i, q in enumerate(block["questions"], 1)
                                            if isinstance(q, dict)]
    if isinstance(user.get("order"), list):
        new_order = [k for k in user["order"] if k in themes]
        for k in themes:                          # темы вне порядка — в конец
            if k not in new_order:
                new_order.append(k)
        order = new_order
    return order, themes


def apply_themes_config(folder):
    """Применяет пресеты тем из файла: обновляет глобальные THEMES/THEME_ORDER/THEME_TITLES."""
    global THEMES, THEME_ORDER, THEME_TITLES
    order, themes = load_themes_config(folder)
    THEMES = themes
    THEME_ORDER = order
    THEME_TITLES = [(k, themes[k].get("title", k)) for k in order]
    log("Пресеты тем применены: тем — " + str(len(order)), "info")


def write_themes_config_template(folder):
    """Пишет файл-шаблон со всеми текущими пресетами для внешнего редактирования."""
    path = os.path.join(folder, "themes_config.json")
    atomic_write(path, json.dumps(default_themes_config(), ensure_ascii=False, indent=2))
    log("Шаблон пресетов тем записан: " + path, "ok")
    return path