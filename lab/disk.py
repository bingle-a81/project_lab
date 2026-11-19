# lab/disk.py — внешние команды, структура, venv, pip, git, проверка, картинки.
import os
import shutil
import subprocess
import sys
from datetime import datetime

from .config import (APP_VERSION, BASE_DIRS, GITIGNORE_TEXT, LIMITS, STAGE_NUM, USER_FILES)
from .utils import (atomic_write, ensure_dir, fmt_cmd, is_inside, is_windows, log,
                    now_human, platform_name, read_text, sanitize_name, shorten)

LOG_OUTPUT_LIMIT = 20000
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".svg", ".webp")


def tool_hint(name):
    """Человеческая инструкция, когда инструмента нет. Ничего не запускаем сами."""
    low = (name or "").lower()
    if "git" in low:
        return "\n".join(["Как поставить Git:",
                          "  Windows: установщик с git-scm.com (оставьте «Git from PATH»).",
                          "  macOS:   xcode-select --install   либо   brew install git",
                          "  Debian/Ubuntu: sudo apt install git",
                          "  Fedora: sudo dnf install git",
                          "После установки перезапустите лабораторию, чтобы обновился PATH."])
    if "pip" in low:
        return "\n".join(["Похоже, в окружении нет pip. Проверенные способы:",
                          "  " + sys.executable + " -m ensurepip --upgrade",
                          "  затем пересоздайте окружение кнопкой «Создать окружение».",
                          "Если сеть закрыта — ставьте пакеты из локального кэша/зеркала."])
    if "venv" in low:
        return "\n".join(["Модуль venv недоступен или отключён в сборке python.",
                          "  Debian/Ubuntu: sudo apt install python3-venv",
                          "  Fedora: sudo dnf install python3-virtualenv (ТРЕБУЕТ ПРОВЕРКИ)",
                          "  Windows/macOS: используйте python с python.org."])
    if "python" in low:
        return "Python не найден по указанному пути. Проверьте, что .venv создано и не удалено."
    if "xdg-open" in low:
        return "Откройте папку вручную средствами файлового менеджера."
    return ""


def venv_python_in(folder):
    """Путь к python внутри .venv с учётом платформы."""
    if not folder:
        return ""
    if is_windows():
        return os.path.join(folder, ".venv", "Scripts", "python.exe")
    return os.path.join(folder, ".venv", "bin", "python")


class CommandResult:
    """Результат одной команды: то, что показываем в логе и в отчёте."""

    def __init__(self, args, cwd=""):
        self.args = list(args)
        self.cwd = cwd
        self.code = None
        self.stdout = ""
        self.stderr = ""
        self.seconds = 0.0
        self.error = ""

    @property
    def ok(self):
        return self.code == 0 and not self.error

    def status_text(self):
        if self.error:
            return "НЕ ЗАПУЩЕНО: " + self.error
        if self.code == 0:
            return "OK (код 0, %.1f с)" % self.seconds
        return "ОШИБКА (код %s)" % self.code

    def combined(self):
        return ((self.stdout or "") + ("\n" + self.stderr if self.stderr else "")).strip()


class CommandRunner:
    """Единая точка запуска внешних команд. Всегда списком, всегда без shell."""

    def __init__(self, cwd=""):
        self.cwd = cwd

    def run(self, args, cwd=None, timeout=None, show_output=True):
        """Запускает команду, пишет в лог команду/вывод/статус, возвращает CommandResult."""
        args = [str(a) for a in args]
        cwd = cwd or self.cwd or os.getcwd()
        timeout = timeout or LIMITS["timeout_cmd"]
        res = CommandResult(args, cwd)
        log("$ " + fmt_cmd(args) + "   [папка: " + cwd + "]", "cmd")
        if not os.path.isdir(cwd):
            res.error = "Рабочая папка не существует: " + cwd
            log(res.error, "err")
            return res
        kwargs = {"cwd": cwd, "capture_output": True, "text": True,
                  "encoding": "utf-8", "errors": "replace", "timeout": timeout}
        if is_windows() and hasattr(subprocess, "CREATE_NO_WINDOW"):
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        started = datetime.now()
        try:
            proc = subprocess.run(args, **kwargs)
            res.code = proc.returncode
            res.stdout = proc.stdout or ""
            res.stderr = proc.stderr or ""
        except FileNotFoundError:
            res.error = "Программа не найдена: " + args[0]
        except PermissionError as e:
            res.error = "Нет прав на запуск: " + str(e)
        except subprocess.TimeoutExpired:
            res.error = "Не успела за %d с — остановлена." % timeout
        except OSError as e:
            res.error = "Ошибка запуска: " + str(e)
        res.seconds = (datetime.now() - started).total_seconds()
        if show_output:
            if (res.stdout or "").strip():
                log(shorten(res.stdout.strip(), LOG_OUTPUT_LIMIT), "raw")
            if (res.stderr or "").strip():
                log(shorten(res.stderr.strip(), LOG_OUTPUT_LIMIT), "raw")
        if res.error:
            log(res.error, "err")
            hint = tool_hint(os.path.basename(args[0]))
            if hint:
                log(hint, "info")
        elif res.ok:
            log("Готово: " + res.status_text(), "ok")
        else:
            log("Команда завершилась с ошибкой: " + res.status_text(), "err")
        return res


class Scaffolder:
    """Прикладные действия в папке проекта.

    ВАЖНО ПРО ПОТОКИ: create_structure / ensure_gitignore / write_user_file задают
    вопросы и вызываются из UI-потока; create_venv / install_deps / git_init_commit /
    check_env — без диалогов, их можно запускать в фоне."""

    def __init__(self, state, confirm=None, ask_conflict=None):
        self.state = state
        self.confirm = confirm or (lambda title, text: False)
        self.ask_conflict = ask_conflict or (lambda rel, old, new: "skip")
        self.runner = CommandRunner()

    def folder_ready(self):
        if not self.state.folder:
            log("Сначала выберите папку проекта на вкладке «Старт».", "warn")
            return False
        return True

    def project_path(self, rel):
        """Абсолютный путь внутри проекта. Выход наружу запрещён."""
        folder = self.state.folder
        if not folder:
            raise ValueError("Папка проекта не выбрана")
        path = os.path.abspath(os.path.join(folder, rel))
        if not is_inside(path, folder):
            raise ValueError("Путь вне проекта запрещён: " + str(rel))
        return path

    def venv_python(self):
        return venv_python_in(self.state.folder)

    def extra_dirs_from_presets(self):
        """Читает черновик структуры: строки вида path/ = дополнительные папки."""
        text = self.state.data["presets"].get("structure") or ""
        out = []
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or not line.endswith("/"):
                continue
            rel = line.rstrip("/").replace("\\", "/")
            parts = [p for p in rel.split("/") if p]
            if rel.startswith("/") or ":" in rel or ".." in parts:
                continue
            rel = "/".join(sanitize_name(p) for p in parts)
            if rel and rel not in BASE_DIRS and rel not in out:
                out.append(rel)
        return out

    def write_user_file(self, rel, text):
        """Пишет файл пользователя, НИКОГДА не перезаписывая молча."""
        path = self.project_path(rel)
        if not os.path.exists(path):
            atomic_write(path, text)
            log("Создан файл: " + rel, "ok")
            return "created"
        old = read_text(path, "")
        if old == text:
            log("Файл уже актуален, не трогаем: " + rel, "info")
            return "same"
        choice = self.ask_conflict(rel, old, text)
        if choice == "overwrite":
            atomic_write(path, text)
            log("Перезаписан по вашему выбору: " + rel, "warn")
            return "overwritten"
        if choice == "copy":
            newpath = path + ".new"
            i = 1
            while os.path.exists(newpath):
                newpath = path + ".new" + str(i)
                i += 1
            atomic_write(newpath, text)
            log("Ваш файл оставлен, заготовка рядом: " + os.path.basename(newpath), "ok")
            return "copy"
        log("Пропущен, оставлен ваш файл: " + rel, "warn")
        return "skipped"

    def file_templates(self):
        """Содержимое стартовых файлов — КАРКАС, а не выдуманный проект."""
        name = self.state.name or "Новый проект"
        theme = self.state.data["theme"]["title"] or "не выбрана"
        stamp = now_human()
        head = "<!-- Каркас создан «Лабораторией проекта» %s (%s). -->" % (APP_VERSION, stamp)
        readme = "\n".join(["# " + name, "", head, "", "Тема: " + theme, "",
                            "## Что это", "<!-- Одно предложение. Заполните после этапа «Идея». -->", "",
                            "## Как запустить", "<!-- Замените на реальные команды после «Скелета». -->", "",
                            "```", "python -m venv .venv",
                            "# Windows: .venv\\Scripts\\python.exe -m pip install -r requirements.txt",
                            "# Linux/macOS: .venv/bin/python -m pip install -r requirements.txt", "```", "",
                            "## Структура",
                            "- src/ — код, tests/ — тесты, features/ — описания фич",
                            "- prompts/ — промпты этапов, artifacts/ — утверждённые ответы",
                            "- images/ — схемы и скриншоты, history/ — снапшоты", "",
                            "## Отчёт по проекту",
                            "report.html — вся конструкция этапов; pipeline.svg — схема прогресса.", ""])
        agents = "\n".join(["# AGENTS.md — правила для ИИ-агентов в этом репозитории", "", head, "",
                            "1. Только стандартная библиотека, пока иное не согласовано явно.",
                            "2. Комментарии обязательны: каждая функция — что делает и зачем.",
                            "3. Код — целыми файлами, первая строка — комментарий с путём.",
                            "4. Непроверенное помечать ТРЕБУЕТ ПРОВЕРКИ.",
                            "5. Не перезаписывать файлы пользователя молча.",
                            "6. Кроссплатформенность: os.path, без shell=True.",
                            "7. Секреты — только в .env, в коде — ссылки на переменные.", "",
                            "## Где что лежит", "- prompts/ — промпты, artifacts/ — результаты",
                            "- PROJECT_CHARTER.md — цель и границы", "- history/ — снапшоты", ""])
        claude = "\n".join(["# CLAUDE.md — то же соглашение, отдельным файлом", "", head, "",
                            "См. AGENTS.md — правила одинаковые для всех ассистентов.", "",
                            "Порядок работы: Идея → Паспорт → Архитектура → Скелет → Фича → Отладка → Итог.",
                            "Контекст берём из prompts/ и artifacts/, а не додумываем.", "",
                            "Проверка перед сдачей:",
                            "- [ ] код запускается на чистой машине по README",
                            "- [ ] есть комментарии и понятные имена",
                            "- [ ] ошибки окружения не роняют программу",
                            "- [ ] файлы пользователя не перезаписаны молча", ""])
        charter = "\n".join(["# Паспорт проекта: " + name, "", head, "", "Тема: " + theme, "",
                             "## Цель", "<!-- Заполняется на этапе «Паспорт». -->", "",
                             "## Границы: что входит", "", "## Границы: что НЕ делаем", "",
                             "## Критерии готовности", "", "## Инварианты", "",
                             "## Ограничения (оффлайн, бюджет, время, права)", "",
                             "## Данные: источник, объём, история, приватность", "",
                             "## Внешнее ПО, лицензии, ключи", "", "## Риски", ""])
        requirements = "\n".join(["# Зависимости проекта. Пусто — нормальный старт на стандартной библиотеке.",
                                  "# Добавляйте по одной строке с обоснованием в комментарии.", ""])
        env_example = "\n".join(["# Пример переменных окружения. Скопируйте в .env и заполните.",
                                 "# Настоящий .env в git не попадает (см. .gitignore).",
                                 "API_URL=", "API_KEY=", "LOG_LEVEL=INFO", ""])
        pytest_ini = "\n".join(["[pytest]", "testpaths = tests", "python_files = test_*.py",
                                "addopts = -q", ""])
        return {"README.md": readme, "AGENTS.md": agents, "CLAUDE.md": claude,
                "PROJECT_CHARTER.md": charter, "requirements.txt": requirements,
                ".gitignore": GITIGNORE_TEXT, ".env.example": env_example, "pytest.ini": pytest_ini}

    def create_structure(self, with_extra=True):
        """Создаёт папки и стартовые файлы. В непустой папке — сначала подтверждение."""
        if not self.folder_ready():
            return None
        folder = self.state.folder
        ensure_dir(folder)
        entries = sorted(os.listdir(folder))
        if entries:
            preview = "\n".join("  • " + e for e in entries[:15])
            more = ("\n  … и ещё %d" % (len(entries) - 15)) if len(entries) > 15 else ""
            if not self.confirm("Папка не пустая",
                                "В папке уже есть объекты (%d):\n%s%s\n\nСуществующие файлы не будут "
                                "перезаписаны молча — по каждому будет вопрос.\nПродолжить?"
                                % (len(entries), preview, more)):
                log("Создание структуры отменено: папка не пустая.", "warn")
                return None
        stats = {"dirs": 0, "created": [], "overwritten": [], "same": [], "skipped": [], "copies": []}
        for d in BASE_DIRS:
            if not os.path.isdir(self.project_path(d)):
                os.makedirs(self.project_path(d), exist_ok=True)
                stats["dirs"] += 1
        extra = self.extra_dirs_from_presets() if with_extra else []
        if extra and self.confirm("Дополнительные папки темы",
                                  "Создать также папки из черновика структуры?\n\n"
                                  + "\n".join("  " + d + "/" for d in extra)):
            for d in extra:
                if not os.path.isdir(self.project_path(d)):
                    os.makedirs(self.project_path(d), exist_ok=True)
                    stats["dirs"] += 1
        keymap = {"created": "created", "overwritten": "overwritten", "same": "same",
                  "skipped": "skipped", "copy": "copies"}
        for rel, text in self.file_templates().items():
            stats[keymap[self.write_user_file(rel, text)]].append(rel)
        log("Структура готова: новых папок %d, создано файлов %d, перезаписано %d, пропущено %d, копий %d"
            % (stats["dirs"], len(stats["created"]), len(stats["overwritten"]),
               len(stats["skipped"]), len(stats["copies"])), "ok")
        return stats

    def create_venv(self, force=False):
        """python -m venv .venv тем же интерпретатором, которым запущена лаборатория."""
        if not self.folder_ready():
            return False
        ensure_dir(self.state.folder)
        py = self.venv_python()
        if os.path.exists(py) and not force:
            log("Окружение .venv уже есть. Пересоздание — только после подтверждения.", "warn")
            return False
        res = self.runner.run([sys.executable, "-m", "venv", ".venv"],
                              cwd=self.state.folder, timeout=LIMITS["timeout_venv"])
        if not res.ok:
            log("Не удалось создать окружение.", "err")
            log(tool_hint("venv"), "info")
            return False
        if not os.path.exists(py):
            log("Команда прошла, но python окружения не найден: " + py, "warn")
            return False
        log("Окружение готово: " + py, "ok")
        return True

    def install_deps(self):
        """.venv/python -m pip install -r requirements.txt (путь зависит от ОС)."""
        if not self.folder_ready():
            return False
        py = self.venv_python()
        if not os.path.exists(py):
            log("Нет окружения .venv — сначала нажмите «Создать окружение».", "err")
            return False
        req = self.project_path("requirements.txt")
        if not os.path.isfile(req):
            log("Нет requirements.txt — сначала «Создать структуру».", "err")
            return False
        meaningful = [ln.strip() for ln in read_text(req, "").splitlines()
                      if ln.strip() and not ln.strip().startswith("#")]
        if not meaningful:
            log("requirements.txt пуст (только комментарии) — ставить нечего.", "ok")
            return True
        res = self.runner.run([py, "-m", "pip", "install", "-r", "requirements.txt"],
                              cwd=self.state.folder, timeout=LIMITS["timeout_pip"])
        if not res.ok:
            log("Установка не удалась. Проверьте сеть, имена пакетов и права.", "err")
            log(tool_hint("pip"), "info")
        return res.ok

    def ensure_gitignore(self):
        """UI-поток: создаёт .gitignore или предлагает дописать недостающие строки."""
        if not self.folder_ready():
            return False
        path = self.project_path(".gitignore")
        if not os.path.exists(path):
            atomic_write(path, GITIGNORE_TEXT)
            log("Создан .gitignore", "ok")
            return True
        current = read_text(path, "")
        required = [".venv/", "__pycache__/", "out/", "data/", "*.env"]
        missing = [p for p in required if p not in current]
        if not missing:
            log(".gitignore уже содержит нужные исключения.", "info")
            return True
        if self.confirm(".gitignore неполный",
                        "В вашем .gitignore нет строк:\n  " + "\n  ".join(missing)
                        + "\n\nДописать их в конец файла? Существующие строки не меняются."):
            new = (current.rstrip("\n") + "\n\n# --- добавлено Лабораторией проекта ---\n"
                   + "\n".join(missing) + "\n")
            atomic_write(path, new)
            log(".gitignore дополнен.", "ok")
            return True
        log(".gitignore оставлен без изменений по вашему выбору.", "warn")
        return False

    def git_init_commit(self):
        """Фоновый поток: git init → add -A → commit. Диалогов здесь нет."""
        if not self.folder_ready():
            return False
        if not shutil.which("git"):
            log("Git не найден в PATH.", "err")
            log(tool_hint("git"), "info")
            return False
        folder = self.state.folder
        if os.path.isdir(os.path.join(folder, ".git")):
            log("Репозиторий уже существует — git init пропускаем.", "info")
        elif not self.runner.run(["git", "init"], cwd=folder).ok:
            return False
        if not self.runner.run(["git", "add", "-A"], cwd=folder).ok:
            return False
        status = self.runner.run(["git", "status", "--porcelain"], cwd=folder)
        if status.ok and not status.stdout.strip():
            log("Изменений нет — коммитить нечего, репозиторий чистый.", "info")
            return True
        res = self.runner.run(["git", "commit", "-m", "стартовый коммит"], cwd=folder)
        if not res.ok:
            text = ((res.stderr or "") + (res.stdout or "")).lower()
            if ("user.email" in text or "user.name" in text
                    or "author identity" in text or "tell me who you are" in text):
                log("Git не знает автора коммита. Задайте имя и почту ДЛЯ ЭТОГО репозитория "
                    "(без --global), затем повторите кнопку:", "err")
                log('  git config user.name "Ваше имя"\n  git config user.email "you@example.com"', "info")
            return False
        self.runner.run(["git", "log", "-1", "--oneline"], cwd=folder)
        log("Первый коммит создан.", "ok")
        return True

    def _write_test(self, folder):
        """Реальная проверка права записи: создаём и удаляем пробный файл."""
        probe = os.path.join(folder, ".lab_write_test.tmp")
        try:
            with open(probe, "w", encoding="utf-8") as f:
                f.write("ok")
        except OSError as e:
            return False, str(e)
        try:
            os.remove(probe)
        except OSError:
            pass
        return True, ""

    def check_env(self):
        """Собирает отчёт об окружении, пишет его в artifacts/env_report.txt."""
        lines = ["ОТЧЁТ ОБ ОКРУЖЕНИИ — " + now_human(),
                 "Лаборатория проекта " + APP_VERSION, ""]
        lines += ["## Система", "ОС: " + platform_name(),
                  "Python лаборатории: " + sys.version.split()[0],
                  "Исполняемый файл: " + sys.executable, ""]
        lines += ["## Инструменты в PATH"]
        for tool in ("git", "python", "python3", "pip"):
            found = shutil.which(tool)
            lines.append(tool + ": " + (found if found else "не найден"))
        lines.append("")
        folder = self.state.folder
        lines += ["## Папка проекта", "Путь: " + (folder or "не выбрана")]
        if folder:
            exists = os.path.isdir(folder)
            lines.append("Существует: " + ("да" if exists else "нет"))
            if exists:
                ok, err = self._write_test(folder)
                lines.append("Доступна на запись: " + ("да" if ok else "НЕТ — " + err))
                missing_dirs = [d for d in BASE_DIRS if not os.path.isdir(os.path.join(folder, d))]
                missing_files = [f for f in USER_FILES if not os.path.isfile(os.path.join(folder, f))]
                lines.append("Нет папок: " + (", ".join(missing_dirs) if missing_dirs else "все на месте"))
                lines.append("Нет файлов: " + (", ".join(missing_files) if missing_files else "все на месте"))
        lines.append("")
        lines += ["## Окружение .venv"]
        py = self.venv_python()
        if folder and os.path.exists(py):
            lines.append("Python окружения: " + py)
            r = self.runner.run([py, "--version"], cwd=folder)
            lines.append("Версия: " + (r.combined() or r.status_text()))
            r = self.runner.run([py, "-m", "pip", "--version"], cwd=folder)
            lines.append("pip: " + (r.combined() or r.status_text()))
        else:
            lines.append("Окружение не создано (кнопка «Создать окружение»).")
        lines.append("")
        lines += ["## Git"]
        if shutil.which("git"):
            r = self.runner.run(["git", "--version"], cwd=folder or os.getcwd())
            lines.append("Версия: " + (r.combined() or r.status_text()))
            if folder and os.path.isdir(folder):
                r = self.runner.run(["git", "rev-parse", "--is-inside-work-tree"], cwd=folder)
                is_repo = r.ok and r.stdout.strip() == "true"
                lines.append("Репозиторий: " + ("да" if is_repo else "нет"))
                if is_repo:
                    r = self.runner.run(["git", "status", "--porcelain"], cwd=folder)
                    changes = [ln for ln in r.stdout.splitlines() if ln.strip()]
                    lines.append("Незакоммиченных изменений: " + str(len(changes)))
                    r = self.runner.run(["git", "log", "-1", "--oneline"], cwd=folder)
                    lines.append("Последний коммит: " + (r.stdout.strip() or "коммитов ещё нет"))
        else:
            lines.append("Git не установлен.")
            lines.append(tool_hint("git"))
        text = "\n".join(lines) + "\n"
        log(text, "raw")
        if folder and os.path.isdir(folder):
            try:
                ensure_dir(os.path.join(folder, "artifacts"))
                atomic_write(os.path.join(folder, "artifacts", "env_report.txt"), text)
                log("Отчёт сохранён: artifacts/env_report.txt", "ok")
            except OSError as e:
                log("Не удалось сохранить отчёт: " + str(e), "warn")
        return text

    def attach_image(self, sid, src):
        """Копирует картинку в images/ под безопасным именем и регистрирует её в этапе."""
        if not self.folder_ready():
            return ""
        if not os.path.isfile(src):
            log("Файл не найден: " + str(src), "err")
            return ""
        ext = os.path.splitext(src)[1].lower()
        if ext not in IMAGE_EXTS:
            log("Неподдерживаемый формат картинки: " + ext
                + ". Допустимы: " + ", ".join(IMAGE_EXTS), "err")
            return ""
        ensure_dir(self.project_path("images"))
        base = sanitize_name(os.path.basename(src), "image" + ext)
        stem, ext2 = os.path.splitext(base)
        prefix = str(STAGE_NUM.get(sid, 0)).zfill(2) + "_" + sid + "_"
        rel = os.path.join("images", prefix + stem + ext2)
        i = 1
        while os.path.exists(self.project_path(rel)):
            rel = os.path.join("images", prefix + stem + "_" + str(i) + ext2)
            i += 1
        shutil.copy2(src, self.project_path(rel))
        rel = rel.replace("\\", "/")
        self.state.add_image(sid, rel)
        log("Картинка приложена: " + rel, "ok")
        return rel