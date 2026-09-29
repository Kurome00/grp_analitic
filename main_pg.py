import os
import sys
import tkinter as tk
from tkinter import messagebox

from core.config import DB_CONFIG
from ui.views_pg import GRPAppPG


DB_HELP = (
    "Не удалось подключиться к PostgreSQL.\n\n"
    "Проверьте по порядку:\n"
    "1. Установлен и запущен ли PostgreSQL "
    f"(хост {DB_CONFIG['host']}, порт {DB_CONFIG['port']}).\n"
    f"2. Верен ли пароль пользователя «{DB_CONFIG['user']}».\n"
    "   Если он другой, задайте переменные окружения перед запуском:\n"
    "      set GRP_DB_PASSWORD=ваш_пароль\n"
    "      set GRP_DB_USER=postgres\n"
    "      set GRP_DB_HOST=localhost\n"
    "      set GRP_DB_PORT=5432\n"
    f"3. Есть ли у пользователя право создать базу «{DB_CONFIG['database']}».\n\n"
    "Подробная инструкция по установке — в файле README.md."
)


def _resource_dir():
    """Папка ресурсов: папка скрипта или _MEIPASS при сборке PyInstaller."""
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def _set_app_icon(root: tk.Tk):
    """Иконка окна: icon.ico (приоритет) или icon.png из папки приложения."""
    base = _resource_dir()

    ico = os.path.join(base, "icon.ico")
    if os.path.isfile(ico):
        try:
            root.iconbitmap(ico)
            return
        except tk.TclError:
            pass

    png = os.path.join(base, "icon.png")
    if os.path.isfile(png):
        try:
            img = tk.PhotoImage(file=png)
            root.iconphoto(True, img)
            root._icon_ref = img
        except tk.TclError:
            pass


def main():
    root = tk.Tk()
    _set_app_icon(root)
    try:
        app = GRPAppPG(root)
    except Exception:
        # База недоступна: показываем понятную инструкцию вместо трассировки.
        messagebox.showerror("База данных недоступна", DB_HELP, parent=root)
        root.destroy()
        return
    root.mainloop()


if __name__ == "__main__":
    main()