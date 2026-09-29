import os
import sys
import tkinter as tk
from ui.views_pg import GRPAppPG


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
    app = GRPAppPG(root)
    root.mainloop()


if __name__ == "__main__":
    main()