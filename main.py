# main.py — точка входа. Запуск:  python main.py
import sys

# Проверяем tkinter до импорта пакета, чтобы дать понятную инструкцию, а не трассировку.
try:
    import tkinter  # noqa: F401
except ImportError:
    sys.stderr.write(
        "Не найден tkinter — графическая часть стандартной библиотеки.\n"
        "Windows/macOS: переустановите python с python.org (tkinter входит в комплект).\n"
        "Debian/Ubuntu: sudo apt install python3-tk\n"
        "Fedora:        sudo dnf install python3-tkinter\n")
    raise SystemExit(1)

from lab.app import App          # noqa: E402  (импорт после проверки tkinter)
from lab.utils import log        # noqa: E402


def main():
    log("Лаборатория проекта запущена. Тема: тёмная.", "info")
    log("Подсказка: сначала выберите тему и папку на вкладке «Старт».", "info")
    App().mainloop()


if __name__ == "__main__":
    main()