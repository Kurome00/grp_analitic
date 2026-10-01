"""Динамический размер окон Tkinter.

Задача модуля — окна открываются по содержимому, а не по захардкоженным
координатам: на маленьком экране диалог 980x640 не помещался целиком, а на
большом оставался маленьким островком посреди пустоты.

fit_window() измеряет запрошенный виджетами размер (winfo_reqwidth/reqheight),
ограничивает его рабочей областью экрана (с запасом на рамку и панель задач),
центрирует окно над родителем и задаёт минимальный размер, с которым
содержимое ещё можно увидеть.
"""

import tkinter as tk
from typing import Optional, Tuple

# Поля окна (рамка + заголовок) и запас на края экрана.
BORDER = 32
SCREEN_MARGIN = 24
MIN_W = 380
MIN_H = 260
# Доля экрана, ниже которой окно не сжимается: дерево с прокруткой должно
# оставаться осмысленным, а не превращаться в полоску.
MIN_SCREEN_RATIO = 0.45


def screen_workarea(master: tk.Misc = None) -> Tuple[int, int, int, int]:
    """Рабочая область экрана: (x, y, ширина, высота)."""
    root = master or tk._default_root
    try:
        return 0, 0, root.winfo_screenwidth(), root.winfo_screenheight()
    except tk.TclError:
        return 0, 0, 1920, 1080


def _required_size(window: tk.Toplevel) -> Tuple[int, int]:
    """Размер, который просят виджеты окна."""
    try:
        window.update_idletasks()
    except tk.TclError:
        return MIN_W, MIN_H
    width = window.winfo_reqwidth()
    height = window.winfo_reqheight()
    try:
        geom = window.geometry()          # «400x300+10+10» — учитываем прошлое
        if geom:
            w, h = geom.split('+')[0].split('x')
            width, height = max(width, int(w)), max(height, int(h))
    except (ValueError, tk.TclError):
        pass
    return width, height


def fit_window(window: tk.Toplevel, master: Optional[tk.Misc] = None,
               min_width: int = MIN_W, min_height: int = MIN_H,
               max_ratio: float = 0.96, center: bool = True) -> Tuple[int, int]:
    """Подогнать окно под содержимое и экран. Возвращает (ширина, высота)."""
    master = master or (window.master if window.master else tk._default_root)
    _x, _y, screen_w, screen_h = screen_workarea(master)

    req_w, req_h = _required_size(window)
    width = min(req_w + BORDER, int(screen_w * max_ratio))
    height = min(req_h + BORDER, int(screen_h * max_ratio))
    width = max(width, min_width, int(screen_w * MIN_SCREEN_RATIO))
    height = max(height, min_height, int(screen_h * MIN_SCREEN_RATIO))

    width = min(width, screen_w - SCREEN_MARGIN)
    height = min(height, screen_h - SCREEN_MARGIN)
    width = max(width, MIN_W)
    height = max(height, MIN_H)

    if center:
        try:
            master.update_idletasks()
            px, py = master.winfo_rootx(), master.winfo_rooty()
            pw, ph = master.winfo_width(), master.winfo_height()
            if pw <= 1 or ph <= 1:          # родитель ещё не показан
                px, py, pw, ph = 0, 0, screen_w, screen_h
        except tk.TclError:
            px, py, pw, ph = 0, 0, screen_w, screen_h
        x = px + (pw - width) // 2
        y = py + (ph - height) // 3       # чуть выше центра — ближе к рукам
        # Прижимаем окно к рабочей области: иначе широкое окно алгоритмов
        # (высота почти во весь экран) уезжает за нижний край.
        x = max(0, min(x, screen_w - width))
        y = max(0, min(y, screen_h - height))
    else:
        x = y = None

    geometry = f"{width}x{height}"
    if x is not None:
        geometry += f"+{int(x)}+{int(y)}"
    try:
        window.geometry(geometry)
        window.minsize(min(width, min_width), min(height, min_height))
    except tk.TclError:
        pass
    _keep_on_screen(window, screen_w, screen_h)
    return width, height


def _keep_on_screen(window: tk.Misc, screen_w: int, screen_h: int) -> None:
    """Сдвинуть окно обратно в экран, если система его переставила.

    Windows сама центрирует transient-окна над родителем и может увеличить
    координаты так, что нижний край уходит за пределы экрана. В геометрии
    Tk +Y — положение рамки окна, а winfo_rooty — клиентской области, поэтому
    сравниваем их и сдвигаем на найденную дельту.
    """
    try:
        window.update_idletasks()
        geom = window.geometry()
        if not geom or '+' not in geom:
            return
        pos = geom.split('+', 1)[1]
        want_x, want_y = (int(v) for v in pos.split('+', 1))
        got_x, got_y = window.winfo_rootx(), window.winfo_rooty()
        w, h = window.winfo_width(), window.winfo_height()
    except (ValueError, tk.TclError):
        return
    if w <= 1 or h <= 1:
        return
    new_x, new_y = want_x, want_y
    if got_x < 0:
        new_x -= got_x
    elif got_x + w > screen_w:
        new_x -= got_x + w - screen_w
    if got_y < 0:
        new_y -= got_y
    elif got_y + h > screen_h:
        new_y -= got_y + h - screen_h
    if (new_x, new_y) == (want_x, want_y):
        return
    try:
        window.geometry(f'+{max(0, new_x)}+{max(0, new_y)}')
    except tk.TclError:
        pass


def resize_root(root: tk.Tk, min_width: int = 1100, min_height: int = 700,
                max_ratio: float = 0.96) -> Tuple[int, int]:
    """Главное окно: во весь экран, но не больше содержимого."""
    screen_w, screen_h = root.winfo_screenwidth(), root.winfo_screenheight()
    limit_w, limit_h = screen_w - SCREEN_MARGIN, screen_h - SCREEN_MARGIN
    width = min(max(root.winfo_reqwidth() + BORDER, min_width), int(screen_w * max_ratio))
    height = min(max(root.winfo_reqheight() + BORDER, min_height), int(screen_h * max_ratio))
    # На маленьком экране (1024x600) заданные минимумы не должны выталкивать
    # окно за края — иначе нижние вкладки останутся за пределами экрана.
    width = min(width, limit_w)
    height = min(height, limit_h)
    width = max(width, MIN_W)
    height = max(height, MIN_H)
    x = max(0, (screen_w - width) // 2)
    y = max(0, (screen_h - height) // 2)
    root.geometry(f"{width}x{height}+{x}+{y}")
    root.minsize(min(min_width, screen_w), min(min_height, screen_h))
    return width, height
