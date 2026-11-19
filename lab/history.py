# lab/history.py — снапшоты и обратимые откаты. Источник правды — папка history/.
import difflib
import json
import os
from datetime import datetime

from .config import APP_VERSION, LIMITS, SCHEMA_VERSION, STAGE_IDS, STAGE_TITLES
from .utils import (atomic_write, ensure_dir, is_inside, log, now_human, now_stamp,
                    read_text, sanitize_name)

REASON_LABELS = {"manual": "вручную", "approve": "утверждение этапа",
                 "before_rollback": "перед откатом", "theme_change": "смена темы",
                 "before_import": "перед загрузкой состояния", "auto": "автосохранение"}
MEMORY_STACK_LIMIT = 20
DIFF_LINES_LIMIT = 600


class HistoryManager:
    """Снапшоты, откаты и сравнение состояний. Работает поверх AppState."""

    def __init__(self, state):
        self.state = state
        self._undo = []
        self._redo = []

    def history_dir(self):
        return os.path.join(self.state.folder, "history") if self.state.folder else ""

    def _safe_path(self, filename):
        """Проверяет имя снапшота и не пускает наружу папки history/."""
        name = os.path.basename(filename or "")
        if not name.startswith("snap_") or not name.endswith(".json"):
            log("Это не файл снапшота: " + str(filename), "err")
            return ""
        folder = self.history_dir()
        if not folder:
            log("Папка проекта не выбрана — история недоступна.", "warn")
            return ""
        path = os.path.join(folder, name)
        if not is_inside(path, folder):
            log("Путь вне папки истории запрещён: " + str(filename), "err")
            return ""
        return path

    def _sync_history_from_disk(self):
        """Пересобирает state['history'] по файлам на диске.
        После отката список должен отражать реальность, иначе откат нечем вернуть."""
        entries = self.list_snapshots()
        self.state.data["history"] = [
            {"file": e["file"], "time": e["time"], "reason": e["reason"],
             "stage": e["stage"], "progress": e["progress"]}
            for e in entries[:LIMITS["snapshot_keep"]]]

    def snapshot(self, reason="manual", stage_id="", quiet=False):
        """Полный слепок состояния. Возвращает путь или пустую строку."""
        if not self.state.folder:
            if not quiet:
                log("Снапшот не создан: папка проекта не выбрана.", "warn")
            return ""
        try:
            ensure_dir(self.history_dir())
            done, total = self.state.progress()
            reason_key = sanitize_name(reason, "manual")
            stage_key = sanitize_name(stage_id or "-", "none")
            stem = ("snap_" + now_stamp() + "__" + reason_key + "__" + stage_key
                    + "__" + str(done) + "of" + str(total))
            path = os.path.join(self.history_dir(), stem + ".json")
            i = 1
            while os.path.exists(path):
                path = os.path.join(self.history_dir(), stem + "_" + str(i) + ".json")
                i += 1
            payload = {"meta": {"created_at": now_human(), "reason": reason_key,
                                "stage": stage_id, "progress": "%d/%d" % (done, total),
                                "project": self.state.name,
                                "theme": self.state.data["theme"]["title"],
                                "app_version": APP_VERSION, "schema_version": SCHEMA_VERSION},
                       "state": self.state.to_dict()}
            atomic_write(path, json.dumps(payload, ensure_ascii=False, indent=2))
            self._sync_history_from_disk()
            self.state.touch()
            if not quiet:
                log("Снапшот создан: history/" + os.path.basename(path), "ok")
            self.prune(quiet=True)
            return path
        except OSError as e:
            log("Не удалось создать снапшот: " + str(e), "err")
            return ""

    def snapshot_on_approve(self, sid):
        return self.snapshot("approve", sid)

    def list_snapshots(self):
        """Список снапшотов, новые сверху. Читает только имена файлов — быстро."""
        folder = self.history_dir()
        if not folder or not os.path.isdir(folder):
            return []
        out = []
        try:
            names = sorted(os.listdir(folder), reverse=True)
        except OSError as e:
            log("Не удалось прочитать папку истории: " + str(e), "err")
            return []
        for name in names:
            if not (name.startswith("snap_") and name.endswith(".json")):
                continue
            parts = name[:-5].split("__")
            stamp = parts[0][5:] if parts else ""
            try:
                human = datetime.strptime(stamp, "%Y%m%d_%H%M%S").strftime("%Y-%m-%d %H:%M:%S")
            except ValueError:
                human = stamp or "время неизвестно"
            reason = parts[1] if len(parts) > 1 else "manual"
            stage = parts[2] if len(parts) > 2 else "-"
            progress = parts[3] if len(parts) > 3 else ""
            try:
                size = os.path.getsize(os.path.join(folder, name))
            except OSError:
                size = 0
            out.append({"file": name, "path": os.path.join(folder, name), "time": human,
                        "reason": reason, "reason_ru": REASON_LABELS.get(reason, reason),
                        "stage": stage, "stage_ru": STAGE_TITLES.get(stage, "—"),
                        "progress": progress, "size": size})
        return out

    def latest(self):
        items = self.list_snapshots()
        return items[0]["file"] if items else ""

    def summary_line(self):
        items = self.list_snapshots()
        if not items:
            return "Снапшотов пока нет."
        return ("Снапшотов: %d | последний: %s (%s)"
                % (len(items), items[0]["time"], items[0]["reason_ru"]))

    def read_snapshot(self, filename):
        """Возвращает состояние из снапшота или None (битый файл не роняет приложение)."""
        path = self._safe_path(filename)
        if not path or not os.path.isfile(path):
            log("Снапшот не найден: " + str(filename), "warn")
            return None
        try:
            payload = json.loads(read_text(path, ""))
        except ValueError as e:
            log("Снапшот повреждён (%s): %s" % (e, filename), "err")
            return None
        if isinstance(payload, dict) and isinstance(payload.get("state"), dict):
            return payload["state"]
        if isinstance(payload, dict) and "stages" in payload:
            return payload
        log("В файле нет состояния проекта: " + str(filename), "err")
        return None

    def _push(self, stack, data):
        stack.append(data)
        if len(stack) > MEMORY_STACK_LIMIT:
            del stack[0]

    def restore(self, filename):
        """Откат к снапшоту. Обратим: страхуемся файлом на диске и памятью."""
        data = self.read_snapshot(filename)
        if data is None:
            return False
        self.snapshot("before_rollback", quiet=True)
        self._push(self._undo, self.state.to_dict())
        self._redo.clear()
        self.state.load_dict(data)
        self._sync_history_from_disk()
        self.state.touch()
        log("Откат выполнен: " + filename + ". Вернуть — кнопкой «Вернуть откат».", "ok")
        return True

    def can_undo(self):
        return bool(self._undo)

    def can_redo(self):
        return bool(self._redo)

    def undo(self):
        """«Вернуть откат»: возвращает состояние, которое было до restore()."""
        if not self._undo:
            log("Возвращать нечего: откатов в этой сессии не было.", "warn")
            return False
        self._push(self._redo, self.state.to_dict())
        self.state.load_dict(self._undo.pop())
        self._sync_history_from_disk()
        self.state.touch()
        log("Откат отменён — вернулось состояние до него.", "ok")
        return True

    def redo(self):
        """«Повторить откат»: снова применяет то, что только что вернули."""
        if not self._redo:
            log("Повторять нечего.", "warn")
            return False
        self._push(self._undo, self.state.to_dict())
        self.state.load_dict(self._redo.pop())
        self._sync_history_from_disk()
        self.state.touch()
        log("Откат применён повторно.", "ok")
        return True

    def changes_summary(self, filename):
        """Человеческая сводка: что изменилось по этапам относительно текущего."""
        data = self.read_snapshot(filename)
        if data is None:
            return ""
        current = self.state.to_dict()
        old = {s.get("id"): s for s in data.get("stages", []) if isinstance(s, dict)}
        new = {s.get("id"): s for s in current.get("stages", []) if isinstance(s, dict)}
        status_ru = {"approved": "утверждён", "draft": "черновик", "empty": "пусто"}
        lines = ["Сравнение снапшота с текущим состоянием:"]
        for sid in STAGE_IDS:
            a, b = old.get(sid, {}), new.get(sid, {})
            changes = []
            if a.get("status") != b.get("status"):
                changes.append("статус: %s → %s" % (status_ru.get(a.get("status"), "—"),
                                                    status_ru.get(b.get("status"), "—")))
            la, lb = len(a.get("llm_result") or ""), len(b.get("llm_result") or "")
            if la != lb:
                changes.append("ответ LLM: %d → %d символов" % (la, lb))
            if (a.get("fields") or {}) != (b.get("fields") or {}):
                changes.append("поля изменены")
            if (a.get("images") or []) != (b.get("images") or []):
                changes.append("картинки изменены")
            if changes:
                lines.append("• " + STAGE_TITLES.get(sid, sid) + ": " + "; ".join(changes))
        if data.get("theme") != current.get("theme"):
            lines.append("• тема проекта изменена")
        if data.get("project") != current.get("project"):
            lines.append("• имя или папка проекта изменены")
        if len(lines) == 1:
            lines.append("Различий нет.")
        return "\n".join(lines)

    def diff_text(self, filename, other=None):
        """Построчные различия двух состояний (по умолчанию — против текущего)."""
        a = self.read_snapshot(filename)
        if a is None:
            return ""
        if other:
            b = self.read_snapshot(other)
            if b is None:
                return ""
            label_b = other
        else:
            b = self.state.to_dict()
            label_b = "текущее состояние"
        left = json.dumps(a, ensure_ascii=False, indent=2, sort_keys=True).splitlines()
        right = json.dumps(b, ensure_ascii=False, indent=2, sort_keys=True).splitlines()
        diff = list(difflib.unified_diff(left, right, fromfile=filename,
                                         tofile=label_b, lineterm="", n=2))
        if not diff:
            return "Различий нет."
        if len(diff) > DIFF_LINES_LIMIT:
            diff = diff[:DIFF_LINES_LIMIT] + ["… показаны первые %d строк различий …" % DIFF_LINES_LIMIT]
        return "\n".join(diff)

    def preview(self, filename):
        """Короткий предпросмотр снапшота для панели вкладки «История»."""
        data = self.read_snapshot(filename)
        if data is None:
            return ""
        status_ru = {"approved": "утверждён", "draft": "черновик", "empty": "пусто"}
        lines = ["Проект: " + ((data.get("project") or {}).get("name") or "без имени"),
                 "Тема: " + ((data.get("theme") or {}).get("title") or "не выбрана"),
                 "Изменено: " + (data.get("updated_at") or "—"), "Этапы:"]
        for s in data.get("stages", []):
            lines.append("  %s. %s — %s%s" % (s.get("num", "?"), s.get("title", "?"),
                                              status_ru.get(s.get("status"), "—"),
                                              (" (ответ %d симв.)" % len(s.get("llm_result") or ""))
                                              if s.get("llm_result") else ""))
        return "\n".join(lines)

    def prune(self, quiet=False):
        """Удаляет самые старые снапшоты сверх лимита."""
        items = self.list_snapshots()
        keep = LIMITS["snapshot_keep"]
        if len(items) <= keep:
            return 0
        removed = 0
        for item in items[keep:]:
            try:
                os.remove(item["path"])
                removed += 1
                if not quiet:
                    log("Удалён старый снапшот: " + item["file"], "info")
            except OSError as e:
                log("Не удалось удалить снапшот %s: %s" % (item["file"], e), "warn")
        if removed and not quiet:
            log("История очищена: удалено %d, оставлено %d" % (removed, keep), "info")
        return removed