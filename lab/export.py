# lab/export.py — prompts/, artifacts/, report.html, pipeline.svg.
import base64
import html
import json
import os

from .config import (ARTIFACT_FILENAMES, LIMITS, PROMPT_FILENAMES, REPORT_FILE,
                     STAGE_NUM, STAGE_TITLES, SVG_FILE)
from .themes import fields_of
from .utils import atomic_write, ensure_dir, log, now_human, platform_name, read_text

MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".gif": "image/gif", ".bmp": "image/bmp", ".svg": "image/svg+xml",
        ".webp": "image/webp"}


class Exporter:
    """Выгружает конструкцию проекта в файлы. Работает только внутри папки проекта."""

    def __init__(self, state, builder):
        self.state = state
        self.builder = builder

    def _dir(self, name):
        path = os.path.join(self.state.folder, name)
        ensure_dir(path)
        return path

    def ready(self):
        if not self.state.folder:
            log("Экспорт невозможен: папка проекта не выбрана.", "warn")
            return False
        return True

    def export_prompts(self):
        """prompts/00..06. Берёт сохранённый промпт этапа, иначе собирает свежий."""
        if not self.ready():
            return []
        out = []
        for sid, fname in PROMPT_FILENAMES.items():
            st = self.state.stage(sid)
            text = (st["prompt"] or "").strip() if st else ""
            if not text:
                text = self.builder.build_stage_prompt(sid)
            path = os.path.join(self._dir("prompts"), fname)
            atomic_write(path, text)
            out.append(path)
            log("Промпт записан: prompts/" + fname, "ok")
        return out

    def export_artifacts(self):
        """artifacts/0X_*_result.md + answers.json со всеми полями и флагами."""
        if not self.ready():
            return []
        out = []
        for sid, fname in ARTIFACT_FILENAMES.items():
            st = self.state.stage(sid)
            body = (st["llm_result"] or "").strip() if st else ""
            if not body:
                continue
            header = ("# Этап %d «%s» — утверждённый результат\nУтверждён: %s\n\n"
                      % (STAGE_NUM.get(sid, 0), STAGE_TITLES.get(sid, sid),
                         st["approved_at"] or "—"))
            path = os.path.join(self._dir("artifacts"), fname)
            atomic_write(path, header + body + "\n")
            out.append(path)
            log("Артефакт записан: artifacts/" + fname, "ok")
        answers = {"project": self.state.name, "theme": self.state.data["theme"]["title"],
                   "flags": self.state.data["flags"],
                   "stages": {s["id"]: {"status": s["status"], "fields": s["fields"],
                                        "images": s["images"]}
                              for s in self.state.data["stages"]}}
        path = os.path.join(self._dir("artifacts"), "answers.json")
        atomic_write(path, json.dumps(answers, ensure_ascii=False, indent=2))
        out.append(path)
        log("Артефакт записан: artifacts/answers.json", "ok")
        return out

    def _image_src(self, rel):
        """Возвращает <img> для картинки: base64-данные или ссылку, если большая."""
        path = os.path.join(self.state.folder, rel.replace("/", os.sep))
        if not os.path.isfile(path):
            return "<p>(файл не найден: " + html.escape(rel) + ")</p>"
        ext = os.path.splitext(path)[1].lower()
        try:
            size = os.path.getsize(path)
        except OSError:
            size = 0
        if size <= LIMITS["image_max_mb"] * 1024 * 1024:
            try:
                with open(path, "rb") as f:
                    data = base64.b64encode(f.read()).decode("ascii")
                return ('<img src="data:' + MIME.get(ext, "application/octet-stream")
                        + ';base64,' + data + '" alt="' + html.escape(rel) + '">')
            except OSError as e:
                return "<p>(не удалось прочитать %s: %s)</p>" % (html.escape(rel), html.escape(str(e)))
        return ('<p>Картинка слишком большая для встраивания, смотрите файл:</p>'
                '<p><code>' + html.escape(rel) + "</code></p>")

    def build_svg(self):
        """Цветная схема этапов. Цвет зависит от статуса, а не от темы интерфейса."""
        fixed = {"approved": "#2ea043", "draft": "#d7ba7d", "empty": "#6a6a6a"}
        stages = self.state.data["stages"]
        bw, bh, gap, margin = 150, 70, 34, 24
        n = len(stages)
        width = margin * 2 + n * bw + (n - 1) * gap
        height = margin * 2 + bh + 46
        parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" '
                 'viewBox="0 0 %d %d" font-family="Segoe UI, Arial, sans-serif">'
                 % (width, height, width, height)]
        parts.append('<rect x="0" y="0" width="%d" height="%d" fill="#1e1e1e"/>' % (width, height))
        x, y = margin, margin
        status_ru = {"approved": "утверждён", "draft": "черновик", "empty": "пусто"}
        for s in stages:
            color = fixed.get(s["status"], "#6a6a6a")
            parts.append('<rect x="%d" y="%d" width="%d" height="%d" rx="8" fill="%s" '
                         'stroke="#3c3c3c"/>' % (x, y, bw, bh, color))
            parts.append('<text x="%d" y="%d" fill="#ffffff" font-size="13" text-anchor="middle" '
                         'font-weight="bold">%d. %s</text>'
                         % (x + bw // 2, y + 28, s["num"], html.escape(s["title"])))
            parts.append('<text x="%d" y="%d" fill="#e8e8e8" font-size="11" text-anchor="middle">%s</text>'
                         % (x + bw // 2, y + 50, status_ru.get(s["status"], s["status"])))
            if s["num"] < n:
                ax = x + bw
                parts.append('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="#9a9a9a" stroke-width="2"/>'
                             % (ax + 2, y + bh // 2, ax + gap - 2, y + bh // 2))
                parts.append('<polygon points="%d,%d %d,%d %d,%d" fill="#9a9a9a"/>'
                             % (ax + gap - 2, y + bh // 2 - 5, ax + gap - 2, y + bh // 2 + 5,
                                ax + gap + 4, y + bh // 2))
            x += bw + gap
        ly = y + bh + 26
        for i, (label, color) in enumerate((("утверждён", fixed["approved"]),
                                            ("черновик", fixed["draft"]), ("пусто", fixed["empty"]))):
            lx = margin + i * 170
            parts.append('<rect x="%d" y="%d" width="14" height="14" fill="%s"/>' % (lx, ly, color))
            parts.append('<text x="%d" y="%d" fill="#d4d4d4" font-size="12">%s</text>' % (lx + 20, ly + 12, label))
        parts.append('<text x="%d" y="%d" fill="#6a6a6a" font-size="10" text-anchor="end">%s</text>'
                     % (width - margin, height - 8, now_human()))
        parts.append("</svg>")
        return "\n".join(parts)

    def export_svg(self):
        if not self.ready():
            return ""
        path = os.path.join(self.state.folder, SVG_FILE)
        atomic_write(path, self.build_svg())
        log("Схема прогресса записана: " + SVG_FILE, "ok")
        return path

    def _stage_html(self, s):
        """Один блок этапа в отчёте: статус, поля, промпт, результат, картинки."""
        status_ru = {"approved": "утверждён", "draft": "черновик", "empty": "пусто"}
        scolor = {"approved": "#2ea043", "draft": "#d7ba7d", "empty": "#6a6a6a"}
        lines = ['<section class="stage">']
        lines.append('<h2>%d. %s <span class="badge" style="background:%s">%s</span></h2>'
                     % (s["num"], html.escape(s["title"]),
                        scolor.get(s["status"], "#6a6a6a"), status_ru.get(s["status"], s["status"])))
        if s["approved_at"]:
            lines.append('<p class="muted">Утверждён: %s</p>' % html.escape(s["approved_at"]))
        fields = fields_of(s["id"])
        if fields:
            lines.append('<table><tr><th>Поле</th><th>Значение</th></tr>')
            for f in fields:
                val = s["fields"].get(f["key"], "")
                if isinstance(val, list):
                    val = ", ".join(str(v) for v in val)
                val = str(val).strip() or "— не заполнено —"
                lines.append('<tr><td>%s</td><td><pre>%s</pre></td></tr>'
                             % (html.escape(f["label"]), html.escape(val)))
            lines.append("</table>")
        if (s["prompt"] or "").strip():
            lines.append("<h3>Промпт</h3><pre>%s</pre>" % html.escape(s["prompt"]))
        if (s["llm_result"] or "").strip():
            lines.append("<h3>Результат от LLM</h3><pre>%s</pre>" % html.escape(s["llm_result"]))
        if s["images"]:
            lines.append("<h3>Картинки</h3>")
            for rel in s["images"]:
                lines.append(self._image_src(rel))
        lines.append("</section>")
        return "\n".join(lines)

    def export_html(self):
        """Самодостаточный тёмный отчёт: шапка, схема, этапы, окружение, история."""
        if not self.ready():
            return ""
        st = self.state
        done, total = st.progress()
        env_text = read_text(os.path.join(st.folder, "artifacts", "env_report.txt"), "")
        parts = ["<!DOCTYPE html>", '<html lang="ru"><head><meta charset="utf-8">',
                 "<title>Отчёт: %s</title>" % html.escape(st.name or "Проект"),
                 "<style>",
                 "body{background:#1e1e1e;color:#d4d4d4;font-family:'Segoe UI',Arial,sans-serif;margin:0;padding:24px;line-height:1.5;}",
                 "h1{color:#ffffff}h2{color:#4ec9b0;border-bottom:1px solid #3c3c3c;padding-bottom:4px}",
                 "h3{color:#d7ba7d}",
                 ".muted{color:#9a9a9a}.badge{color:#fff;border-radius:6px;padding:2px 10px;font-size:14px}",
                 "table{border-collapse:collapse;width:100%;margin:8px 0}",
                 "th,td{border:1px solid #3c3c3c;padding:6px 10px;text-align:left;vertical-align:top}",
                 "th{background:#2d2d30;color:#d4d4d4}td pre{white-space:pre-wrap;margin:0}",
                 "pre{background:#1b1b1c;border:1px solid #3c3c3c;border-radius:6px;padding:12px;white-space:pre-wrap;word-wrap:break-word;overflow:auto}",
                 "img{max-width:100%;border:1px solid #3c3c3c;border-radius:6px;margin:6px 0}",
                 ".scheme{background:#1e1e1e;border:1px solid #3c3c3c;border-radius:8px;padding:12px;overflow:auto;margin:12px 0}",
                 "</style></head><body>"]
        parts.append("<h1>%s</h1>" % html.escape(st.name or "Проект"))
        parts.append('<p class="muted">Тема: %s &nbsp;|&nbsp; Утверждено этапов: %d/%d &nbsp;|&nbsp; '
                     "Собран: %s &nbsp;|&nbsp; ОС: %s</p>"
                     % (html.escape(st.data["theme"]["title"] or "не выбрана"),
                        done, total, now_human(), platform_name()))
        parts.append('<div class="scheme">%s</div>' % self.build_svg())
        for s in st.data["stages"]:
            parts.append(self._stage_html(s))
        if env_text.strip():
            parts.append("<h2>Отчёт об окружении</h2><pre>%s</pre>" % html.escape(env_text))
        hist = self.state.data.get("history") or []
        if hist:
            parts.append("<h2>Снапшоты</h2><table><tr><th>Время</th><th>Причина</th>"
                         "<th>Этап</th><th>Прогресс</th></tr>")
            for h in hist:
                parts.append("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>"
                             % (html.escape(str(h.get("time", ""))), html.escape(str(h.get("reason", ""))),
                                html.escape(str(h.get("stage", ""))), html.escape(str(h.get("progress", "")))))
            parts.append("</table>")
        parts.append('<p class="muted">Создано «Лабораторией проекта» %s</p>' % __import__("lab.config", fromlist=["APP_VERSION"]).APP_VERSION)
        parts.append("</body></html>")
        path = os.path.join(st.folder, REPORT_FILE)
        atomic_write(path, "\n".join(parts))
        log("Отчёт записан: " + REPORT_FILE, "ok")
        return path

    def export_all(self):
        """Полный экспорт + свежий state.json. Возвращает список записанных файлов."""
        if not self.ready():
            return []
        files = []
        files += self.export_prompts()
        files += self.export_artifacts()
        files.append(self.export_svg())
        files.append(self.export_html())
        self.state.save(quiet=True)
        files.append(self.state.state_path())
        log("Экспорт завершён: записано файлов — " + str(len(files)), "ok")
        return files