# lab/themes.py — пресеты тем, поля этапов, наводящие вопросы + themes_config.
import copy
import json
import os

from .config import APP_ROOT, BASE_DIRS
# from .utils import log, sanitize_name
from .utils import atomic_write, log, sanitize_name

# Общая приписка к любому черновику — чтобы человек не принял его за решение.
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

# --- Встроенные пресеты тем (запасные; перекрываются themes_config.json) ----
_BUILTIN_THEMES = {
    "engineering": {
        "title": "Инженерный",
        "desc": "Автоматизация оборудования, интеграция с инженерным ПО, расчёты.",
        "stack": PRESET_DISCLAIMER + "Python 3.10+\nОбмен с оборудованием: pyserial / pymodbus (внешние)\nРасчёты: чистый Python; numpy — если нужны массивы\nФайлы: csv, json (stdlib); xlsx — openpyxl (внешняя)\nОтчёты: HTML на string.Template (stdlib)\nТесты: unittest (stdlib) или pytest (внешний)\n",
        "stack_options": ["Python + stdlib", "Python + pyserial/pymodbus", "Python + numpy",
                          "Обмен файлами с CAD/CAM", "Симулятор вместо реального железа"],
        "extra_dirs": ["src/drivers", "src/calc", "docs/specs", "data/raw", "data/samples"],
        "questions": [
            make_question("eq_link", "С каким оборудованием или ПО идёт обмен и по какому протоколу?",
                          "Порт, скорость, протокол, кто инициатор обмена.",
                          ["COM / RS-485 (Modbus)", "TCP/IP", "Файловый обмен", "Обмена нет, только расчёт"]),
            make_question("eq_safety", "Что нельзя делать ни при каких условиях?",
                          "Аварийные ограничения и обязательные подтверждения оператора.",
                          ["Команда только после подтверждения", "Запрет записи в рабочее ПО", "Только чтение"]),
            make_question("eq_units", "Какие единицы измерения и допуски?",
                          "Что считаем ошибкой: выход за допуск, потеря связи, рассинхрон.",
                          ["мм / мм в минуту", "градусы", "мбар / литры", "допуск задан в ТЗ"]),
            make_question("eq_sim", "Нужен ли режим без реального оборудования (симулятор)?",
                          "Чтобы разрабатывать и тестировать оффлайн.",
                          ["Да, симулятор обязателен", "Нет", "Позже"]),
            make_question("eq_time", "Есть ли требования по времени отклика?",
                          "Если реальное время — это отдельная архитектура, отметьте как риск.",
                          ["Нет, пакетная обработка", "Секунды", "Миллисекунды — ТРЕБУЕТ ПРОВЕРКИ"]),
        ],
        "invariants": PRESET_DISCLAIMER + "- Исходные данные не изменяются: работаем с копиями.\n- Единицы измерения указываются явно, перевод — в одном месте.\n- Каждая команда оборудованию логируется: время, параметры, ответ.\n- Потеря связи не приводит к молчаливому продолжению работы.\n- Расчётные функции чистые: вход → выход, без побочных эффектов.\n",
    },
    "finance": {
        "title": "Экономический",
        "desc": "Финансы, бюджеты, цены, отчёты.",
        "stack": PRESET_DISCLAIMER + "Python 3.10+\nДеньги: decimal.Decimal (stdlib), никаких float\nФайлы: csv, json (stdlib); xlsx — openpyxl (внешняя)\nХранение: sqlite3 (stdlib)\nОтчёты: HTML (stdlib) + сводные таблицы\nТесты: на округлениях обязательно\n",
        "stack_options": ["Python + Decimal + csv", "Python + sqlite3",
                          "Python + openpyxl (xlsx)", "HTML-отчёт на stdlib", "Выгрузка для 1С / ERP"],
        "extra_dirs": ["src/importers", "src/reports", "data/raw", "data/dicts", "docs/methodology"],
        "questions": [
            make_question("fin_source", "Откуда берутся цифры?", "Выгрузка, прайсы, банк, ручной ввод.",
                          ["1С / ERP", "Банковская выписка", "Прайсы поставщиков", "Ручной ввод"]),
            make_question("fin_period", "Какой период и как он закрывается?",
                          "День / месяц / квартал; можно ли пересчитывать закрытый период.",
                          ["День", "Месяц", "Квартал", "Пересчёт запрещён после закрытия"]),
            make_question("fin_round", "Правила округления и валюты?",
                          "Сколько знаков, на каком шаге округляем, что с курсами.",
                          ["2 знака, ROUND_HALF_UP", "Округление только в конце",
                           "Одна валюта", "Мультивалютность + курсы"]),
            make_question("fin_match", "Как сопоставляются справочники?",
                          "По коду, по имени, вручную; что делать с несопоставленным.",
                          ["По артикулу / коду", "По названию", "Таблица соответствий", "Вручную"]),
            make_question("fin_check", "Как проверяем, что цифры сошлись?",
                          "Контрольные суммы, сверка с источником, кто подписывает отчёт.",
                          ["Контрольные итоги", "Сверка с выгрузкой", "Двойная проверка человеком"]),
            make_question("fin_privacy", "Насколько данные чувствительные?",
                          "Персональные данные, коммерческая тайна, где можно хранить.",
                          ["Обычные рабочие", "Коммерческая тайна", "Персональные данные", "Только локально"]),
        ],
        "invariants": PRESET_DISCLAIMER + "- Деньги только в Decimal; float запрещён.\n- Округление по единому правилу и в одном месте кода.\n- Итоги отчёта сходятся с источником до копейки.\n- Закрытый период не меняется: только новая версия расчёта.\n- Ключи и пароли — в .env, не в коде и не в git.\n",
    },
    "data": {
        "title": "Аналитика данных",
        "desc": "Парсинг, обработка, отчёты, графики.",
        "stack": PRESET_DISCLAIMER + "Python 3.10+\nЗагрузка: urllib.request (stdlib); requests — по согласованию\nОбработка: csv, json, statistics (stdlib); pandas — если объёмы большие\nХранение: sqlite3 (stdlib)\nГрафики: matplotlib (внешняя) или SVG вручную (stdlib)\nОтчёты: HTML (stdlib)\n",
        "stack_options": ["Python + stdlib (csv/json)", "Python + pandas", "Python + requests",
                          "sqlite3 как хранилище", "SVG-графики без библиотек"],
        "extra_dirs": ["src/parsers", "src/transforms", "data/raw", "data/processed", "out/reports"],
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
        "invariants": PRESET_DISCLAIMER + "- Сырые данные неизменяемы: все шаги работают с копиями.\n- Каждый шаг обработки воспроизводим и логируется.\n- Пропуски и дубликаты не «исчезают» молча — попадают в отчёт.\n- В отчёте всегда есть дата, источник и версия расчёта.\n- Парсинг уважает ограничения источника (частота, robots).\n",
    },
    "web": {
        "title": "Веб / сервисы",
        "desc": "Сайты, API, внутренние сервисы.",
        "stack": PRESET_DISCLAIMER + "Python 3.10+\nПрототип: http.server (stdlib)\nСервис: Flask или FastAPI (внешние, по согласованию)\nХранение: sqlite3 (stdlib)\nШаблоны: string.Template (stdlib) или Jinja2 (внешняя)\nКлиент: urllib.request (stdlib)\n",
        "stack_options": ["stdlib http.server (прототип)", "Flask", "FastAPI",
                          "sqlite3", "Только API без интерфейса"],
        "extra_dirs": ["src/api", "src/web", "static", "templates", "docs/api"],
        "questions": [
            make_question("web_client", "Кто ходит в сервис?", "Браузер человека, скрипт, другая система.",
                          ["Браузер", "Скрипт / cron", "Другая система", "Смешанно"]),
            make_question("web_api", "Какие эндпоинты и контракты нужны?",
                          "Метод, путь, вход, выход, коды ошибок.",
                          ["GET /items", "POST /jobs", "GET /report", "Список уточню позже"]),
            make_question("web_auth", "Нужна ли авторизация?", "Кто и как доказывает, что ему можно.",
                          ["Нет, только localhost", "Токен в заголовке", "Логин/пароль", "Внешний SSO"]),
            make_question("web_host", "Где это будет работать?",
                          "Локальная машина, сервер в сети, контейнер; есть ли интернет.",
                          ["Только мой компьютер", "Сервер в локальной сети", "Внешний хостинг", "Контейнер"]),
            make_question("web_load", "Какая ожидается нагрузка?",
                          "Запросов в минуту, размер ответа, нужен ли фон/очередь.",
                          ["Единицы запросов", "Десятки в минуту", "Сотни и больше", "Не знаю"]),
        ],
        "invariants": PRESET_DISCLAIMER + "- Секреты не попадают в код, логи и git.\n- Любой вход валидируется до использования.\n- Ошибки возвращаются с понятным кодом и текстом, без стектрейса наружу.\n- Изменение контракта API — только с новой версией.\n- Сервис поднимается одной командой из README.\n",
    },
    "science": {
        "title": "Научный / исследовательский",
        "desc": "Модели, эксперименты, проверка гипотез.",
        "stack": PRESET_DISCLAIMER + "Python 3.10+\nРасчёты: чистый Python; numpy / scipy — по согласованию\nГрафики: matplotlib (внешняя) или SVG (stdlib)\nЭксперименты: json/csv + фиксация параметров запуска\nТесты: unittest (stdlib) на ключевых формулах\n",
        "stack_options": ["Python + stdlib", "Python + numpy/scipy", "matplotlib",
                          "Эксперименты в json/csv", "SVG-графики"],
        "extra_dirs": ["src/model", "experiments", "data/raw", "data/results", "docs/paper"],
        "questions": [
            make_question("sci_hypo", "Какую гипотезу проверяем?",
                          "Что должно получиться, чтобы работа считалась успешной.",
                          ["Сравнить два метода", "Оценить влияние параметра",
                           "Построить модель процесса", "Проверить качество данных"]),
            make_question("sci_metric", "Метрики и критерий успеха?",
                          "Чем измеряем и какой порог считаем достаточным.",
                          ["Ошибка (MAE/RMSE)", "Точность/полнота", "Время счёта", "Порог задан в ТЗ"]),
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
        "invariants": PRESET_DISCLAIMER + "- Seed и версии фиксируются в каждом эксперименте.\n- Сырые данные неприкосновенны.\n- Один эксперимент = папка с параметрами, логами и результатом.\n- Выводы отделены от данных: сначала цифры, потом трактовка.\n- Отрицательный результат тоже сохраняется.\n",
    },
    "office": {
        "title": "Автоматизация офиса / скрипты",
        "desc": "Рутинные операции с файлами, отчёты, рассылки.",
        "stack": PRESET_DISCLAIMER + "Python 3.10+\nФайлы и папки: os, shutil, pathlib, zipfile (stdlib)\nТаблицы: csv (stdlib); xlsx — openpyxl, docx — python-docx (внешние)\nПланировщик: средства ОС (Планировщик Windows / cron)\nЛоги: logging (stdlib)\n",
        "stack_options": ["Python + stdlib", "openpyxl (xlsx)", "python-docx",
                          "Запуск по расписанию ОС", "Один .bat/.sh для запуска"],
        "extra_dirs": ["src/jobs", "inbox", "out", "docs/runbooks"],
        "questions": [
            make_question("off_routine", "Какая рутина и сколько времени она занимает?",
                          "Опишите шаги как есть сейчас — это основа сценария.",
                          ["Переименование файлов", "Сборка отчёта из файлов", "Рассылка", "Перекладывание по папкам"]),
            make_question("off_files", "Где лежат файлы и как называются?",
                          "Шаблон имени, кодировка, что делать с неожиданными именами.",
                          ["Шаблон имени есть", "Имена произвольные", "Сетевая папка", "Локальная папка"]),
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
        "invariants": PRESET_DISCLAIMER + "- Сначала сухой прогон: показываем, что будет сделано.\n- Ничего не удаляем без бэкапа или корзины.\n- Повторный запуск не создаёт дубликаты.\n- Каждый запуск пишет отчёт: что сделано, что пропущено, почему.\n- Пути и имена — через os.path, без «зашитых» дисков.\n",
    },
    "blank": {
        "title": "Другое (чистый лист)",
        "desc": "Без пресетов: только базовая структура и общие вопросы.",
        "stack": PRESET_DISCLAIMER + "Python 3.x\nСтандартная библиотека — по умолчанию\nВнешние библиотеки — только по вашему явному решению\n",
        "stack_options": ["Python + stdlib", "Свой вариант (напишу сам)"],
        "extra_dirs": [],
        "questions": [],
        "invariants": PRESET_DISCLAIMER + "- Исходные данные не портим.\n- Ошибки не глотаем молча.\n- Секреты — в .env, не в коде.\n",
    },
}
_BUILTIN_THEME_ORDER = ["engineering", "finance", "data", "web", "science", "office", "blank"]

# «Живые» пресеты: по умолчанию равны встроенным, заменяются themes_config.json.
THEMES = copy.deepcopy(_BUILTIN_THEMES)
THEME_ORDER = list(_BUILTIN_THEME_ORDER)
THEME_TITLES = [(k, THEMES[k]["title"]) for k in THEME_ORDER]


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
STAGE_SPECS = {
    "idea": {"goal": "Собрать ответы на наводящие вопросы и получить черновик идеи.",
             "task": "Помоги превратить сырые ответы в чёткую формулировку проекта. "
                     "Не додумывай факты: чего не хватает — задай уточняющие вопросы.",
             "answer_sections": ["Краткое резюме идеи (3–5 строк)",
                                 "Уточняющие вопросы, если данных не хватает",
                                 "Предложение стека с обоснованием и пометками ТРЕБУЕТ ПРОВЕРКИ",
                                 "Риски и что проверить в первую очередь",
                                 "Следующий шаг: что заполняем на этапе «Паспорт»"],
             "fields": [make_field("draft", "Черновик идеи (собирается из ответов, можно править)",
                                   "text", "Нажмите «Собрать черновик» или напишите сами.", 10),
                        make_field("extra", "Что ещё важно знать о проекте", "text",
                                   "Контекст, который не покрыт вопросами.", 4)]},
    "charter": {"goal": "Зафиксировать цель, границы и критерии готовности проекта.",
                "task": "Собери паспорт проекта (PROJECT_CHARTER.md). Границы важнее хотелок: "
                        "явно выпиши, чего в первой версии НЕ будет.",
                "answer_sections": ["PROJECT_CHARTER.md целиком (готовый текст файла)",
                                    "Критерии готовности — проверяемый список", "Инварианты списком",
                                    "Что вынесено за границы первой версии", "Открытые вопросы"],
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
             "task": "Предложи архитектуру под паспорт проекта. Модули должны быть проверяемыми "
                     "по отдельности, зависимости — минимальными.",
             "answer_sections": ["Модули: имя файла → ответственность", "Потоки данных: вход → шаги → выход",
                                 "Контракты: сигнатуры функций, форматы, коды ошибок",
                                 "Обработка ошибок и логирование", "Зависимости и обоснование каждой",
                                 "Схема текстом (ASCII), если картинки нет"],
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
                 "task": "Собери скелет проекта: дерево файлов и минимальные заготовки. "
                         "Каждый файл — целиком, путь в комментарии первой строкой.",
                 "answer_sections": ["Дерево файлов проекта",
                                     "Содержимое заготовок: каждый файл целиком, путь в комментарии",
                                     "requirements.txt", "Как запустить и проверить (команды)",
                                     "Что оставить пустым и почему"],
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
                "task": "Реализуй одну фичу целиком, с тестами. Не трогай то, что вне её границ; "
                        "изменения по файлам давай явно.",
                "answer_sections": ["Постановка фичи и критерии приёмки",
                                    "Изменения по файлам (целиком или патчи с контекстом)",
                                    "Тест-кейсы: вход → ожидание", "Краевые случаи", "Как проверить вручную"],
                "fields": [make_field("feature_name", "Название фичи", "line", "", 1),
                           make_field("user_story", "Что делает фича для пользователя", "text", "", 3),
                           make_field("acceptance", "Критерии приёмки", "text", "", 4),
                           make_field("io_example", "Пример входа и ожидаемого выхода", "text", "", 4),
                           make_field("changes", "Какие файлы скелета меняем", "text", "", 4),
                           make_field("tests", "Тест-кейсы", "text", "", 4),
                           make_field("edge_cases", "Краевые случаи и что делать при ошибке", "text", "", 3)]},
    "debug": {"goal": "Разобрать ошибку: воспроизведение, причина, фикс, регресс-тест.",
              "task": "Найди причину ошибки, а не симптом. Дай минимальный пример воспроизведения, "
                      "исправление и тест, который поймает регресс в будущем.",
              "answer_sections": ["Диагноз: причина простыми словами", "Минимальный пример воспроизведения",
                                  "Исправление: файлы целиком", "Регресс-тест", "Что ещё может сломаться рядом"],
              "fields": [make_field("symptom", "Симптом: что видим", "text", "", 3),
                         make_field("reproduce", "Шаги воспроизведения", "text", "", 4),
                         make_field("expected_actual", "Ожидание и факт", "text", "", 3),
                         make_field("logs", "Логи и текст ошибки", "text", "Вставляйте как есть.", 5),
                         make_field("hypotheses", "Гипотезы и что уже проверено", "text", "", 3),
                         make_field("fix", "Что меняем (если уже понятно)", "text", "", 4),
                         make_field("regression", "Как поймать это в будущем (регресс-тест)", "text", "", 3)]},
    "summary": {"goal": "Собрать мастер-промпт и выгрузить всю конструкцию проекта.",
                "task": "Собери итоговую сводку: что построено, как запускать, что дальше.",
                "answer_sections": ["Сводка проекта", "Порядок работ по шагам",
                                    "Чек-лист приёмки", "Что осталось за границами"],
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
    """Безопасный доступ к описанию этапа: goal / task / answer_sections."""
    return STAGE_SPECS.get(sid, {}).get(key, default)


def preset_hint_for(state, sid, key):
    """Текст черновика темы для конкретного поля. Пустая строка = кнопки нет."""
    preset_key = PRESET_HINT_MAP.get((sid, key))
    if not preset_key:
        return ""
    return state.data["presets"].get(preset_key, "") or ""


# --- themes_config.json ------------------------------------------------------
def default_themes_config():
    """Встроенные пресеты тем по умолчанию — они же записываются в файл-шаблон."""
    return {"order": list(_BUILTIN_THEME_ORDER), "themes": copy.deepcopy(_BUILTIN_THEMES)}


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
    """Возвращает (порядок, темы) — файл поверх встроенных. Битый файл не ломает."""
    order = list(_BUILTIN_THEME_ORDER)
    themes = copy.deepcopy(_BUILTIN_THEMES)
    path = _find_themes_config_path(folder)
    if not path:
        return order, themes
    try:
        with open(path, "r", encoding="utf-8") as f:
            user = json.load(f)
    except (ValueError, OSError) as e:
        log("Настройки тем не прочитаны (" + str(e) + ") — использую встроенные.", "warn")
        return order, themes
    if not isinstance(user, dict):
        return order, themes
    uthemes = user.get("themes")
    if isinstance(uthemes, dict):
        for key, block in uthemes.items():
            if not isinstance(block, dict):
                continue
            if key not in themes:
                themes[key] = {"title": key, "desc": "", "stack": "", "stack_options": [],
                               "extra_dirs": [], "questions": [], "invariants": ""}
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
        for k in themes:
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