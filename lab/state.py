# lab/state.py — модель состояния проекта (то, что уезжает в state.json).
import copy
import json
import os

from .config import (APP_VERSION, LIMITS, SCHEMA_VERSION, STAGES, START_FULLSCREEN,
                     STATE_FILE, WORK_STAGE_IDS)
from .utils import atomic_write, ensure_dir, log, now_human, read_text


def default_state():
    """Пустое состояние нового проекта. Никаких выдуманных ответов за пользователя."""
    return {
        "schema_version": SCHEMA_VERSION,
        "app_version": APP_VERSION,
        "created_at": now_human(),
        "updated_at": now_human(),
        "theme": {"key": "", "title": ""},
        "project": {"name": "", "folder": ""},
        "presets": {"stack": "", "structure": "", "questions": [], "invariants": ""},
        "flags": {"git": False, "venv": False, "tests": False, "html_report": False},
                "settings": {"theme_mode": "dark", "context_limit": LIMITS["context_chars"],
                     "last_tab": 0, "autosave": True, "fullscreen": START_FULLSCREEN},
        "stages": [
            {"id": sid, "num": num, "title": title, "status": "empty",
             "fields": {}, "prompt": "", "llm_result": "", "images": [],
             "approved_at": "", "updated_at": ""}
            for sid, num, title, _sub in STAGES
        ],
        "history": [],
    }


def normalize_state(raw):
    """Приводит загруженный словарь к текущему формату, додумывая недостающее."""
    base = default_state()
    if not isinstance(raw, dict):
        return base
    for key in ("created_at", "app_version"):
        if isinstance(raw.get(key), str):
            base[key] = raw[key]
    for key in ("theme", "project", "presets", "flags", "settings"):
        if isinstance(raw.get(key), dict):
            base[key].update({k: v for k, v in raw[key].items() if k in base[key]})
    if isinstance(raw.get("history"), list):
        base["history"] = raw["history"]
    old = {s.get("id"): s for s in raw.get("stages", []) if isinstance(s, dict)}
    for stage in base["stages"]:
        src = old.get(stage["id"])
        if not src:
            continue
        if isinstance(src.get("fields"), dict):
            stage["fields"] = src["fields"]
        for key in ("prompt", "llm_result", "approved_at", "updated_at"):
            if isinstance(src.get(key), str):
                stage[key] = src[key]
        if isinstance(src.get("images"), list):
            stage["images"] = [p for p in src["images"] if isinstance(p, str)]
        if src.get("status") in ("empty", "draft", "approved"):
            stage["status"] = src["status"]
    return base


class AppState:
    """Единственный источник правды о проекте."""

    def __init__(self):
        self.data = default_state()
        self.dirty = False
        self.loaded_from = ""

    @property
    def folder(self):
        return self.data["project"]["folder"]

    @property
    def name(self):
        return self.data["project"]["name"]

    def stage(self, sid):
        """Запись этапа по id."""
        for s in self.data["stages"]:
            if s["id"] == sid:
                return s
        return None

    def touch(self):
        """Отмечает изменение: время обновления + флаг «надо сохранить»."""
        self.data["updated_at"] = now_human()
        self.dirty = True

    def set_folder(self, path):
        """Задаёт рабочую папку — всё приложение работает только с ней."""
        if not path:
            return False
        path = os.path.abspath(os.path.expanduser(path))
        if os.path.isfile(path):
            log("Выбран файл, а не папка: %s" % path, "err")
            return False
        self.data["project"]["folder"] = path
        if not self.data["project"]["name"]:
            self.data["project"]["name"] = os.path.basename(path)
        self.touch()
        log("Рабочая папка проекта: %s" % path, "ok")
        return True

    def set_name(self, name):
        self.data["project"]["name"] = (name or "").strip()
        self.touch()

    def set_theme(self, key, title, presets=None):
        """Запоминает тему и (опционально) её редактируемые пресеты."""
        self.data["theme"] = {"key": key, "title": title}
        if presets is not None:
            self.data["presets"] = copy.deepcopy(presets)
        self.touch()

    def set_flag(self, key, value):
        """Флаги git/venv/тесты/HTML — ответы пользователя, не наши догадки."""
        if key in self.data["flags"]:
            self.data["flags"][key] = bool(value)
            self.touch()

    def set_setting(self, key, value):
        if key in self.data["settings"]:
            self.data["settings"][key] = value
            self.touch()

    def set_field(self, sid, key, value):
        """Ответ пользователя на поле этапа. Пустой этап становится черновиком."""
        st = self.stage(sid)
        if st is None:
            return
        st["fields"][key] = value
        st["updated_at"] = now_human()
        if st["status"] == "empty" and str(value).strip():
            st["status"] = "draft"
        self.touch()

    def set_prompt(self, sid, text):
        st = self.stage(sid)
        if st is not None:
            st["prompt"] = text or ""
            st["updated_at"] = now_human()
            if st["status"] == "empty" and st["prompt"].strip():
                st["status"] = "draft"
            self.touch()

    def set_result(self, sid, text):
        st = self.stage(sid)
        if st is not None:
            st["llm_result"] = text or ""
            st["updated_at"] = now_human()
            if st["status"] == "empty" and st["llm_result"].strip():
                st["status"] = "draft"
            self.touch()

    def approve(self, sid):
        """Утверждает этап: его результат пойдёт в контекст следующих промптов."""
        st = self.stage(sid)
        if st is None:
            return False
        st["status"] = "approved"
        st["approved_at"] = now_human()
        self.touch()
        log("Этап «%s» утверждён." % st["title"], "ok")
        return True

    def unapprove(self, sid):
        st = self.stage(sid)
        if st is None:
            return False
        st["status"] = "draft" if (st["llm_result"].strip() or st["fields"]) else "empty"
        st["approved_at"] = ""
        self.touch()
        log("Снято утверждение этапа «%s»." % st["title"], "warn")
        return True

    def add_image(self, sid, rel_path):
        st = self.stage(sid)
        if st is not None and rel_path not in st["images"]:
            st["images"].append(rel_path)
            self.touch()

    def remove_image(self, sid, rel_path):
        st = self.stage(sid)
        if st is not None and rel_path in st["images"]:
            st["images"].remove(rel_path)
            self.touch()

    def approved_before(self, sid):
        """Утверждённые этапы ДО указанного — контекст промпта."""
        from .config import STAGE_IDS
        if sid not in STAGE_IDS:
            return []
        cut = STAGE_IDS.index(sid)
        return [s for s in self.data["stages"][:cut] if s["status"] == "approved"]

    def approved_ids(self):
        return [s["id"] for s in self.data["stages"] if s["status"] == "approved"]

    def progress(self):
        """(сколько рабочих этапов утверждено, всего рабочих этапов)."""
        done = sum(1 for s in self.data["stages"]
                   if s["id"] in WORK_STAGE_IDS and s["status"] == "approved")
        return done, len(WORK_STAGE_IDS)

    def state_path(self):
        return os.path.join(self.folder, STATE_FILE) if self.folder else ""

    def to_dict(self):
        return copy.deepcopy(self.data)

    def load_dict(self, raw):
        """Заменяет состояние нормализованными данными (используется и при откате)."""
        self.data = normalize_state(raw)
        self.dirty = True

    def save(self, quiet=False):
        """Пишет state.json. Без папки — честно сообщает и не падает."""
        if not self.folder:
            if not quiet:
                log("Папка проекта не выбрана — сохранять некуда.", "warn")
            return False
        ensure_dir(self.folder)
        atomic_write(self.state_path(), json.dumps(self.data, ensure_ascii=False, indent=2))
        self.dirty = False
        if not quiet:
            log("Состояние сохранено: %s" % self.state_path(), "ok")
        return True

    def load(self, path):
        """Читает state.json. Битый файл не роняет приложение."""
        text = read_text(path, "")
        if not text:
            log("Файл состояния не найден или пуст: %s" % path, "warn")
            return False
        try:
            raw = json.loads(text)
        except ValueError as e:
            log("state.json повреждён (%s). Загружено пустое состояние." % e, "err")
            return False
        self.data = normalize_state(raw)
        self.loaded_from = path
        self.dirty = False
        log("Состояние загружено: %s" % path, "ok")
        return True