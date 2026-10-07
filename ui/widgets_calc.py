"""Оформление окон расчёта: приватная тема ttk, карточки, таблицы, прокрутка.

Здесь собраны виджеты, из которых строится окно «Алгоритмы»:

* `calc_theme` / `restore_theme` — своя тема clam, чтобы таблицы можно было
  покрасить в цвета приложения. Тема ttk в интерпретаторе общая для всех
  окон, поэтому тему, которая была до окна расчёта, нужно вернуть при выходе.
* `Pane` — колонка карточек с вертикальной прокруткой: содержимое вкладки
  «Алгоритмы» выше окна, и без прокрутки нижние таблицы просто не видны.
* `table` — таблица с обеими полосами прокрутки и пересчётом ширин граф: графы
  не должны ни обрезаться справа, ни болтаться пустым местом слева.
"""
import tkinter as tk
from tkinter import ttk

# --------------------------------------------------------------------- цвета
BG = '#eef1f6'
CARD = '#ffffff'
LINE = '#dbe2ec'
HEAD = '#e7ecf5'
TEXT = '#0f172a'
SUB = '#4a5568'
ACCENT = '#2158d4'
GOOD = '#0d8a4e'
WARN = '#a86a00'
BAD = '#c02f2f'

TINT_GOOD = '#e7f6ee'
TINT_WARN = '#fdf3e0'
TINT_BAD = '#fbeaea'
TINT_SKIP = '#f0f3f8'
TINT_PART = '#f5f8fc'
# Поправки, заданные вручную в окне расчёта: голубым, чтобы их было видно
# рядом с посчитанными по формулам.
TINT_MANUAL = '#e8f0fe'

# Единая шкала размеров: текст таблиц и подписей не мельче 10 pt.
F_TABLE = ('Segoe UI', 10)
F_TABLE_B = ('Segoe UI', 10, 'bold')
F_TITLE = ('Segoe UI', 12, 'bold')
F_BODY = ('Segoe UI', 10)
F_HERO = ('Segoe UI', 32, 'bold')

ROW_H = 30

_THEME_NAME = 'GrpCalc'
_THEME_BASES = ('clam', 'default', 'alt')


def _theme_base() -> str:
    """Первая существующая базовая тема: clam умеет цвета, остальные — нет."""
    style = ttk.Style()
    available = style.theme_names()
    for name in _THEME_BASES:
        if name in available:
            return name
    return style.theme_use()


def calc_theme() -> str:
    """Включает оформление таблиц. Возвращает тему, которую надо вернуть."""
    style = ttk.Style()
    saved = style.theme_use()
    if saved == _THEME_NAME:
        return ''
    if _THEME_NAME not in style.theme_names():
        style.theme_create(_THEME_NAME, parent=_theme_base())
    style.theme_use(_THEME_NAME)

    style.configure(
        'Grid.Treeview',
        background=CARD, fieldbackground=CARD, foreground=TEXT,
        selectbackground='#d3e2fb', selectforeground=TEXT,
        font=F_TABLE, rowheight=ROW_H, borderwidth=0, relief='flat',
        padding=(0, 0))
    style.configure(
        'Grid.Treeview.Heading',
        background=HEAD, foreground=TEXT, font=F_TABLE_B,
        relief='flat', borderwidth=0, padding=(8, 8))
    style.map('Grid.Treeview.Heading', background=[('active', '#d9e1ef')])

    for name, orient in (('Calc.Horizontal.TScrollbar', 'horizontal'),
                         ('Calc.Vertical.TScrollbar', 'vertical')):
        style.configure(
            name, background='#c3ccd9', troughcolor='#e9edf3',
            bordercolor='#e9edf3', arrowcolor='#5a6678',
            darkcolor='#c3ccd9', lightcolor='#c3ccd9',
            relief='flat', borderwidth=0, arrowsize=11,
            orient=orient)

    style.configure('Calc.TNotebook', background=BG, borderwidth=0,
                    tabmargins=(2, 6, 2, 0))
    style.configure('Calc.TNotebook.Tab', background='#e2e7ef',
                    foreground=SUB, font=F_TABLE_B,
                    padding=(16, 9), borderwidth=0)
    style.map('Calc.TNotebook.Tab',
              background=[('selected', CARD), ('active', '#d5dce8')],
              foreground=[('selected', ACCENT), ('active', ACCENT)])

    style.configure('Calc.TCombobox', fieldbackground=CARD, background=CARD,
                    foreground=TEXT, font=F_BODY, bordercolor=LINE,
                    arrowcolor=SUB, padding=(8, 6))
    style.configure('Calc.TEntry', fieldbackground=CARD, foreground=TEXT,
                    font=('Consolas', 11), bordercolor=LINE,
                    insertcolor=TEXT, padding=(6, 5))
    # Поле коэффициента с недопустимым значением: розовый фон и красная рамка.
    style.configure('CalcBad.TEntry', fieldbackground=TINT_BAD, foreground=BAD,
                    font=('Consolas', 11), bordercolor=BAD,
                    insertcolor=TEXT, padding=(6, 5))
    return saved


def restore_theme(saved: str):
    """Возвращает тему ttk, которая была до включения оформления."""
    style = ttk.Style()
    if saved and saved != _THEME_NAME and saved in style.theme_names():
        try:
            style.theme_use(saved)
        except tk.TclError:
            pass


# -------------------------------------------------------------------- карточка

def card(parent, bg: str = CARD, **pack):
    """Белая карточка с рамкой в цвет линии."""
    frame = tk.Frame(parent, bg=bg, highlightbackground=LINE,
                     highlightthickness=1, bd=0)
    frame.pack(**pack)
    return frame


def card_title(parent, text, bg: str = CARD):
    """Заголовок карточки: тёмный, полужирный, без серых пояснений рядом."""
    return tk.Label(parent, text=text, bg=bg, fg=TEXT, font=F_TITLE,
                    anchor=tk.W, justify=tk.LEFT)


def head_row(parent, bg: str = CARD, padx: int = 16, pady=(11, 0)):
    """Ряд заголовков карточки — отступы карточки в одном месте."""
    row = tk.Frame(parent, bg=bg)
    row.pack(fill=tk.X, padx=padx, pady=pady)
    return row


def note(parent, text, bg: str = CARD, color: str = SUB,
         font: tuple = F_BODY, **pack):
    """Пояснительная строка читаемым цветом, а не блёклой мелочью.

    Длинный текст переносится по ширине родителя: без переноса строка уходила
    бы за правый край карточки и обрывалась на полуслове.
    """
    label = tk.Label(parent, text=text, bg=bg, fg=color, font=font,
                     justify=tk.LEFT, anchor=tk.W)
    label.pack(**pack)

    def on_resize(event):
        label.configure(wraplength=max(240, event.width - 40))

    parent.bind('<Configure>', on_resize, add='+')
    return label


# ------------------------------------------------------------------ прокрутка

class Pane(tk.Frame):
    """Колонка карточек с вертикальной прокруткой.

    Содержимое кладётся в `body`; отступы задаются здесь, при создании панели.
    `body` упакован внутри рамки, которая лежит в canvas, и **сам в canvas не
    кладётся повторно**: если упаковать `body` ещё и средствами pack, canvas
    перестаёт видеть его размер (высота обрезается по высоте окна, а область
    прокрутки вырождается в точку) — панель перестаёт листаться целиком.

    Колонка повторяет ширину окна, поэтому карточки внутри растягиваются на всю
    доступную ширину. Ползунок появляется только когда содержимое выше окна, и
    колёсико мыши работает только пока указатель над этой панелью: у таблиц
    внутри своя прокрутка, и без проверки колесо прокручивало бы обе сразу.
    """

    def __init__(self, parent, bg: str = BG, padx: int = 14, pady=10):
        super().__init__(parent, bg=bg, bd=0)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.vbar = ttk.Scrollbar(self, orient=tk.VERTICAL,
                                  command=self.canvas.yview,
                                  style='Calc.Vertical.TScrollbar')
        # Рамка-обёртка — единственный элемент canvas; отступы живут внутри неё,
        # чтобы тело панели оставалось обычным упакованным фреймом.
        outer = tk.Frame(self.canvas, bg=bg, bd=0)
        self._window = self.canvas.create_window((0, 0), window=outer,
                                                 anchor='nw')
        self.body = tk.Frame(outer, bg=bg, bd=0)
        self.body.pack(fill=tk.X, padx=padx, pady=pady)
        self.canvas.configure(yscrollcommand=self.vbar.set)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.vbar.pack(side=tk.RIGHT, fill=tk.Y)

        self._armed = False
        self._wheel_ids = []
        outer.bind('<Configure>', self._resize)
        self.canvas.bind('<Configure>', self._resize)
        # Содержимое растёт не сразу: таблицы подгоняют высоту через after().
        self.after(20, self._resize)
        self.after(60, self._resize)
        self.bind('<Enter>', self._arm_wheel, add='+')
        self.bind('<Leave>', self._disarm_wheel, add='+')

    def _resize(self, event=None):
        try:
            if event is not None and event.widget is self.canvas:
                self.canvas.itemconfigure(self._window, width=event.width)
            self.canvas.configure(scrollregion=self.canvas.bbox('all'))
        except tk.TclError:
            # Окно закрыли раньше, чем отработал отложенный пересчёт.
            pass

    def _arm_wheel(self, _event=None):
        """Колесо над панелью листает панель.

        Привязка живёт на окне и снимается по своему идентификатору: панелей в
        окне несколько, и общий `bind_all` копился бы с каждым входом курсора,
        прокручивая вниз всё быстрее.
        """
        if self._armed:
            return
        self._armed = True
        toplevel = self.winfo_toplevel()
        self._wheel_ids = [toplevel.bind('<MouseWheel>', self._on_wheel,
                                         add='+')]

    def _disarm_wheel(self, _event=None):
        if not self._armed:
            return
        self._armed = False
        toplevel = self.winfo_toplevel()
        for funcid in self._wheel_ids:
            try:
                toplevel.unbind('<MouseWheel>', funcid)
            except tk.TclError:
                pass
        self._wheel_ids = []

    def _contains(self, x_root, y_root) -> bool:
        try:
            widget = self.winfo_containing(x_root, y_root)
        except (KeyError, tk.TclError):
            return False
        while widget is not None:
            if widget is self:
                return True
            widget = getattr(widget, 'master', None)
        return False

    def _on_wheel(self, event):
        if not self._contains(event.x_root, event.y_root):
            return
        self.canvas.yview_scroll(-int(event.delta / 120), 'units')
        return 'break'

    def to_top(self):
        self.canvas.yview_moveto(0.0)


# -------------------------------------------------------------------- таблица

def table(parent, columns, widths, *, height=8, expand=True, tree=False,
          tree_title='Оборудование', tree_width=300):
    """Таблица с вертикальной и горизонтальной прокруткой.

    Ширины граф заданы в пикселях. Последняя графа добирает остаток окна; если
    места не хватает, включается горизонтальная прокрутка, и ни одна графа не
    пропадает. Высота задаётся в строках, поэтому таблица растёт под содержимое,
    а лишнее уезжает под вертикальный ползунок.
    """
    holder = tk.Frame(parent, bg=BG)
    holder.pack(fill=tk.BOTH if expand else tk.X, expand=expand)

    columns = list(columns)

    view = ttk.Treeview(holder, columns=columns,
                        show=('tree headings' if tree else 'headings'),
                        height=height, selectmode='browse',
                        style='Grid.Treeview')
    if tree:
        view.heading('#0', text=tree_title)
        view.column('#0', width=tree_width, anchor=tk.W,
                    stretch=False, minwidth=120)

    total = 0
    for column in columns:
        view.heading(column, text=column)
        view.column(column, width=widths.get(column, 110), anchor=tk.W,
                    stretch=False, minwidth=60)
        total += view.column(column, 'width')
    if tree:
        total += tree_width

    grow_col = columns[-1] if columns else None
    grow_base = widths.get(grow_col, 110) if grow_col else 0

    vbar = ttk.Scrollbar(holder, orient=tk.VERTICAL, command=view.yview,
                          style='Calc.Vertical.TScrollbar')
    hbar = ttk.Scrollbar(holder, orient=tk.HORIZONTAL, command=view.xview,
                          style='Calc.Horizontal.TScrollbar')
    view.configure(yscrollcommand=vbar.set, xscrollcommand=hbar.set)
    view.grid(row=0, column=0, sticky='nsew')
    vbar.grid(row=0, column=1, sticky='ns')
    hbar.grid(row=1, column=0, sticky='ew')
    holder.rowconfigure(0, weight=1)
    holder.columnconfigure(0, weight=1)

    def on_configure(_event=None):
        width = view.winfo_width()
        if width <= 1:
            view.after(10, on_configure)
            return
        if grow_col is None:
            return
        gap = width - total
        if gap > 0:
            view.column(grow_col, width=grow_base + gap)
        hbar.set(*view.xview())

    def on_holder_config(_event=None):
        width = view.winfo_width()
        if width <= 1:
            view.after(10, on_configure)
            return
        on_configure()

    def on_wheel(event):
        view.yview_scroll(-int(event.delta / 120), 'units')
        return 'break'

    def on_shift_wheel(event):
        view.xview_scroll(-int(event.delta / 120), 'units')
        return 'break'

    view.bind('<Configure>', on_configure)
    holder.bind('<Configure>', on_holder_config, add='+')
    view.bind('<MouseWheel>', on_wheel)
    view.bind('<Shift-MouseWheel>', on_shift_wheel)
    view.after(5, on_configure)
    view.after(15, on_configure)
    view.after(40, on_configure)
    view.holder = holder
    return view


def fit_table(view, rows: int, minimum: int = 3, cap: int = 14):
    """Высота таблицы под содержимое: пустой белый прямоугольник не нужен."""
    view.configure(height=min(max(int(rows or 0), minimum), cap))