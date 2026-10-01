"""Окно «Алгоритмы» — расчёт остаточного ресурса ГРП по методике.

Окно не показывает «магическое» число: рядом с результатом всегда видно,
из каких данных он получен, какая формула применена и какие данные отсутствовали
(с явной пометкой, что соответствующий коэффициент принят равным 1).
"""
import copy
import tkinter as tk
from datetime import date, timedelta
from tkinter import messagebox, ttk

from core.config import FULL_CHECK_TERM
from core.timefmt import years_to_text
from ui.window_utils import fit_window
from logic.algorithms import (
    ALGORITHM_TITLES,
    DAMAGE_MARKERS,
    FAILURE_MARKERS,
    GRPResourceCalculator,
    POOR_REPAIR_MARKERS,
    WEAK_LINK_TOLERANCE,
    AlgorithmParams,
    algo_label,
    algo_number,
    calculate_all_algorithms,
    classify_critical,
    critical_short_title,
    critical_title,
    driving_part,
    num,
    signed_years,
)

BG = '#f4f6f9'
CARD = '#ffffff'
LINE = '#e3e8ef'
TEXT = '#1f2933'
MUTED = '#6b7785'
ACCENT = '#2f6fed'
GOOD = '#1e9e63'
WARN = '#e8a317'
BAD = '#d64545'

PRIMARY_ALGORITHM = 3
# Предел горизонта на ползунке «Срок замены»: пять лет — норма заменяемых
# деталей, дальше смотреть бессмысленно, там всё равно всё просрочено.
HORIZON_MAX = 5.0
# Ползунок щёлкает по месяцам: подписанный срок всегда получается ровным
# («2 года 5 мес»), а не «2 года 5 мес 2 дн» из-за дробного шага мыши.
HORIZON_SNAP = 1.0 / 12.0
CONSERVATIVE_NOTE = (
    'Сроки по методикам 3 и 4 показываются раздельно: сводить их в одну величину '
    'нельзя — они считают разные величины (по заменяемым деталям и по '
    'календарному сроку оборудования), поэтому расхождение между ними ожидаемо.'
)

TRACE_COLORS = {
    'title': (ACCENT, True, False),
    'formula': ('#0b3d91', True, False),
    'value': (TEXT, False, False),
    'note': (MUTED, False, True),
    'warn': (BAD, True, False),
}


def _btn(parent, text, command, color=ACCENT, font_size=10, padx=12):
    """Плоская кнопка с подсветкой при наведении."""
    palette = {
        'success': ('#1e9e63', '#17905a'),
        'danger': ('#d64545', '#bd3a3a'),
        'muted': ('#8b95a1', '#78828e'),
    }
    bg, bg_hover = palette.get(color, (color, _darken(color)))
    btn = tk.Button(
        parent, text=text, command=command, bg=bg, fg='#ffffff',
        font=('Segoe UI', font_size), padx=padx, pady=5,
        bd=0, relief='flat', cursor='hand2', activebackground=bg_hover,
        activeforeground='#ffffff', highlightthickness=0,
    )
    btn.bind('<Enter>', lambda e, b=btn, c=bg_hover: b.config(bg=c))
    btn.bind('<Leave>', lambda e, b=btn, c=bg: b.config(bg=c))
    return btn


def _darken(hex_color, factor=0.85):
    """Затемняет цвет для эффекта наведения."""
    try:
        r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    except (ValueError, IndexError):
        return hex_color
    return '#%02x%02x%02x' % (int(r * factor), int(g * factor), int(b * factor))


def _card(parent, **pack):
    """Белая карточка со скруглённой рамкой."""
    frame = tk.Frame(parent, bg=CARD, highlightbackground=LINE,
                     highlightthickness=1, bd=0)
    frame.pack(**pack)
    return frame


def _tree(parent, columns, widths, height=10, style=None, wide_first=False):
    """Дерево таблицы с вертикальным скроллбаром.

    wide_first растягивает только первую графу: числовые колонки остаются
    заданной ширины и не сплющиваются, когда ширины не хватает.
    """
    holder = tk.Frame(parent, bg=BG)
    holder.pack(fill=tk.BOTH, expand=True)

    tree = ttk.Treeview(holder, columns=columns, show='headings',
                        height=height, selectmode='browse', style=style)
    for index, column in enumerate(columns):
        tree.heading(column, text=column)
        tree.column(column, width=widths.get(column, 110), anchor=tk.W,
                    stretch=wide_first or index == 0)
    scrollbar = ttk.Scrollbar(holder, orient=tk.VERTICAL, command=tree.yview)
    tree.configure(yscrollcommand=scrollbar.set)
    tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
    return tree


def _text_block(parent, height=12, font=('Consolas', 10)):
    """Прокручиваемый текстовый блок с тегами подсветки."""
    holder = tk.Frame(parent, bg=BG)
    holder.pack(fill=tk.BOTH, expand=True)
    box = tk.Text(holder, wrap=tk.WORD, font=font, height=height, bd=0,
                  highlightthickness=0, bg='#fbfcfd', fg=TEXT, padx=10, pady=8)
    scrollbar = ttk.Scrollbar(holder, orient=tk.VERTICAL, command=box.yview)
    box.configure(yscrollcommand=scrollbar.set)
    box.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
    return box


def _part_residual(part):
    """Остаток заменяемой детали: заданный методикой, иначе норма минус возраст."""
    if not part:
        return None
    z = part.get('z_base')
    if z is None:
        z = (part.get('norm') or 0.0) - (part.get('age') or 0.0)
    return z


def _plural(count, one, few, many):
    """Русское склонение числительного: 1 год, 2 года, 5 лет."""
    tail = abs(count) % 100
    if 11 <= tail <= 14:
        return many
    tail %= 10
    if tail == 1:
        return one
    if 2 <= tail <= 4:
        return few
    return many


def _horizon_text(value):
    """Горизонт ползунка в виде срока.

    Ползунок щёлкает по месяцам, а years_to_text переводит в дни и печатает
    «6 мес 2 дн» вместо «6 мес». Здесь считаем целые месяцы сами, чтобы
    подпись всегда была ровной: «1 год 6 мес».
    """
    if not value or value <= 0:
        return '0 лет'
    months = int(round(value * 12))
    years, rest = divmod(months, 12)
    if not rest:
        return f'{years} {_plural(years, "год", "года", "лет")}'
    head = f'{years} {_plural(years, "год", "года", "лет")} ' if years else ''
    return f'{head}{rest} мес'


def _counted_parts(element):
    """Детали элемента, которые методика действительно учитывает (норма 5 лет)."""
    return [d for d in (element.details or []) if _is_counted_part(d)]


def _pick_parts(element):
    """Что менять у элемента: просроченные детали, иначе ближайшую к замене."""
    parts = _counted_parts(element)
    expired = [d for d in parts if _part_residual(d) <= 0]
    return expired or sorted(parts, key=_part_residual)[:1]


def _parts_text(parts, limit=3):
    """Перечень деталей для строки: первые несколько и сколько ещё."""
    names = [str(d.get('name')) for d in parts]
    if not names:
        return '—'
    shown = ', '.join(names[:limit])
    return shown if len(names) <= limit else f'{shown} и ещё {len(names) - limit}'


def _last_replacement_on(journal):
    """Самая поздняя дата замены в журнале ('ГГГГ-ММ-ДД').

    Журнал замен ведётся по типам оборудования, а не по запчастям, поэтому дата
    последнего ремонта — единственный ориентир для деталей без собственной даты
    установки. Допущение выносится в замечания к расчёту, чтобы пользователь
    видел, откуда взялась дата.
    """
    best = None
    for record in (journal or {}).values():
        for entry in record.get('entries') or []:
            value = entry.get('date')
            if not value:
                continue
            text = str(value).strip()[:10]
            if len(text) == 10 and (best is None or text > best):
                best = text
    return best


def _tree_hier(parent, columns, widths, height=8):
    """Дерево с раскрываемыми строками: оборудование → его детали."""
    holder = tk.Frame(parent, bg=BG)
    holder.pack(fill=tk.BOTH, expand=True)

    tree = ttk.Treeview(holder, columns=columns, show='tree headings',
                        height=height, selectmode='browse')
    tree.heading('#0', text='Оборудование / деталь')
    tree.column('#0', width=280, anchor=tk.W, stretch=False)
    for column in columns:
        tree.heading(column, text=column)
        tree.column(column, width=widths.get(column, 110), anchor=tk.W)
    scrollbar = ttk.Scrollbar(holder, orient=tk.VERTICAL, command=tree.yview)
    tree.configure(yscrollcommand=scrollbar.set)
    tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
    return tree


def _is_counted_part(detail):
    """Деталь входит в методику: норма ровно 5 лет."""
    if not detail:
        return False
    norm = detail.get('norm', detail.get('norm_years'))
    try:
        return abs(float(norm) - PART_NORM_YEARS) < 0.01
    except (TypeError, ValueError):
        return False


def _due_date(years):
    """Дата истечения срока, отсчитанная от сегодняшней даты."""
    days = int(round(float(years) * 365.25))
    return (date.today() + timedelta(days=days)).isoformat()


def _canvas_round_rect(canvas, x1, y1, x2, y2, radius, **kwargs):
    """Скруглённый прямоугольник на Canvas — у Tkinter нет create_round_rect."""
    radius = max(0.0, min(radius, (x2 - x1) / 2.0, (y2 - y1) / 2.0))
    points = [
        x1 + radius, y1, x2 - radius, y1,
        x2, y1, x2, y1 + radius,
        x2, y2 - radius, x2, y2,
        x2 - radius, y2, x1 + radius, y2,
        x1, y2, x1, y2 - radius,
        x1, y1 + radius, x1, y1,
    ]
    return canvas.create_polygon(points, smooth=True, splinesteps=16, **kwargs)


# Норма заменяемой детали, которую методика действительно учитывает. Детали
# с другой нормой в расчёт не попадают, поэтому и в списки на замену их
# показывать нельзя — иначе список будет врать про сроки.
PART_NORM_YEARS = 5.0
# «Скоро нужно менять»: остаток меньше года. Плюс всегда показывается
# ближайшее звено, даже если оно дальше года — иначе на календарной шкале
# (Алгоритм 4, где остаток измеряется годами до полной проверки) список был
# бы пустым и выглядел бы как ошибка.
SOON_HORIZON = 1.0
# Продление: сколько лет максимум просим и сколько шагов замен считаем.
EXTENSION_MAX = 20.0
EXTENSION_STEPS = 12

CONSERVATIVE_SCALE = (
    'Это срок до полной проверки оборудования (норма элемента '
    f'{num(FULL_CHECK_TERM, 0)} лет), а не срок службы детали: поэтому '
    'здесь он и больше 5 лет.'
)

HORIZON_LEVELS = {
    'none': (GOOD, 'ничего не просрочено'),
    'some': (WARN, 'часть просрочена'),
    'all': (BAD, 'почти всё просрочено'),
}


class HorizonSlider(tk.Frame):
    """Ползунок горизонта: рисуется сам, тянется мышью, щёлкает по месяцам.

    Стандартный ttk.Scale на этой теме выглядит серой полоской без ручки и без
    делений, а деления здесь несут смысл: по ним видно, где «через год» и
    «через три». Поэтому трек, заливка, ручка и деления рисуются на Canvas.
    """

    PADDING_X = 18
    TRACK_H = 8
    HANDLE_W = 22
    HANDLE_H = 30
    TICK_H = 7
    LABEL_H = 18
    HEIGHT = 78

    def __init__(self, parent, maximum: float, snap: float, command=None):
        super().__init__(parent, bg=CARD, height=self.HEIGHT)
        self.maximum = float(maximum)
        self.snap = float(snap) or 0.01
        self._command = command
        self._value = float(maximum)
        self._level = 'none'
        self._dragging = False
        self._hover = False

        self.canvas = tk.Canvas(self, bg=CARD, height=self.HEIGHT,
                                highlightthickness=0, bd=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.bind('<Configure>', lambda _e: self.redraw())
        self.canvas.bind('<Button-1>', self._on_press)
        self.canvas.bind('<B1-Motion>', self._on_drag)
        self.canvas.bind('<ButtonRelease-1>', self._on_release)
        self.canvas.bind('<Enter>', self._on_enter)
        self.canvas.bind('<Leave>', self._on_leave)
        self.canvas.bind('<Key>', self._on_key)
        self.canvas.configure(cursor='hand2', takefocus=True)

    # ------------------------------------------------------------- значения

    def get(self) -> float:
        return self._value

    def set(self, value: float, notify: bool = False):
        """Ставит значение с привязкой к шагу; notify=True — вызвать обработчик."""
        snapped = self._clamp(self._snap(float(value)))
        changed = abs(snapped - self._value) > 1e-9
        self._value = snapped
        self.redraw()
        if notify and changed and self._command:
            self._command(snapped)

    def step(self, months: int):
        self.set(self._value + months / 12.0, notify=True)

    def set_level(self, level: str):
        """Подсветка по срочности: никого / часть / всё."""
        if level not in HORIZON_LEVELS or level == self._level:
            return
        self._level = level
        self.redraw()

    def _snap(self, value: float) -> float:
        return round(value / self.snap) * self.snap

    def _clamp(self, value: float) -> float:
        return max(0.0, min(self.maximum, value))

    # -------------------------------------------------------------- события

    def _on_press(self, event):
        self._dragging = True
        self.canvas.focus_set()
        self._apply_x(event.x)

    def _on_drag(self, event):
        if self._dragging:
            self._apply_x(event.x)

    def _on_release(self, _event):
        self._dragging = False

    def _on_enter(self, _event):
        self._hover = True
        self.redraw()

    def _on_leave(self, _event):
        self._hover = False
        self._dragging = False
        self.redraw()

    def _on_key(self, event):
        if event.keysym in ('Left', 'Down'):
            self.step(-1)
            return 'break'
        if event.keysym in ('Right', 'Up'):
            self.step(1)
            return 'break'
        if event.keysym == 'Home':
            self.set(0.0, notify=True)
            return 'break'
        if event.keysym == 'End':
            self.set(self.maximum, notify=True)
            return 'break'
        return None

    def _apply_x(self, x: int):
        self.set(self._value_from_x(x), notify=True)

    # ------------------------------------------------------------ геометрия

    def _left(self) -> float:
        return float(self.PADDING_X + self.HANDLE_W / 2.0)

    def _right(self) -> float:
        return float(self.canvas.winfo_width() - self.PADDING_X - self.HANDLE_W / 2.0)

    def _value_from_x(self, x: float) -> float:
        left, right = self._left(), self._right()
        if right <= left:
            return 0.0
        return self._clamp((x - left) / (right - left) * self.maximum)

    def _x_from_value(self, value: float) -> float:
        left, right = self._left(), self._right()
        return left + (value / self.maximum) * (right - left) if self.maximum else left

    # --------------------------------------------------------------- отрисовка

    def redraw(self):
        canvas = self.canvas
        canvas.delete('all')
        width = canvas.winfo_width()
        if width <= 1:
            return

        left, right = self._left(), self._right()
        span = max(1.0, right - left)
        track_y = 22 + self.TRACK_H / 2.0
        color, _note = HORIZON_LEVELS.get(self._level, HORIZON_LEVELS['none'])
        handle_x = self._x_from_value(self._value)

        # Дорожка: серая «рельса» + заливка пройденного.
        canvas.create_line(left, track_y, right, track_y, fill='#dfe4ea',
                           width=self.TRACK_H, capstyle=tk.ROUND)
        canvas.create_line(left, track_y, handle_x, track_y, fill=color,
                           width=self.TRACK_H, capstyle=tk.ROUND)

        # Деления по годам: мелкие — по месяцам, крупные — по годам.
        months = int(round(self.maximum * 12))
        for month in range(months + 1):
            x = left + span * (month / 12.0) / self.maximum
            if month % 12 == 0:
                canvas.create_line(x, track_y + self.TRACK_H / 2 + 3,
                                   x, track_y + self.TRACK_H / 2 + 3 + self.TICK_H,
                                   fill='#aeb8c4', width=2)
                label = _horizon_text(float(month // 12))
                canvas.create_text(x, track_y + self.TRACK_H / 2 + 3 + self.TICK_H
                                   + self.LABEL_H / 2 + 1, text=label,
                                   fill=MUTED, font=('Segoe UI', 8))
            elif month % 3 == 0:
                canvas.create_line(x, track_y + self.TRACK_H / 2 + 4,
                                   x, track_y + self.TRACK_H / 2 + 3 + self.TICK_H - 1,
                                   fill='#cfd6de', width=1)

        # Ручка: тень, корпус, белая полоска-метка.
        height = self.HANDLE_H + (4 if self._hover or self._dragging else 0)
        top = track_y - height / 2.0
        _canvas_round_rect(canvas, handle_x - self.HANDLE_W / 2 + 1, top + 2,
                           handle_x + self.HANDLE_W / 2 + 1, top + height + 2,
                           7, fill='#c7ced8', outline='')
        _canvas_round_rect(canvas, handle_x - self.HANDLE_W / 2, top,
                           handle_x + self.HANDLE_W / 2, top + height,
                           7, fill='#ffffff', outline=color, width=2)
        canvas.create_line(handle_x, top + height / 2 - 3,
                           handle_x, top + height / 2 + 3, fill=color, width=2)


class AlgorithmsWindow:
    """Расчёт и разбор остаточного ресурса ГРП по всем алгоритмам."""

    def __init__(self, parent, db, grp_id, equipment_data, grp_name=None):
        self.parent = parent
        self.db = db
        self.grp_id = grp_id
        self.grp_name = grp_name or f'ГРП №{grp_id}'
        self.equipment_data = equipment_data or []
        self.params = AlgorithmParams()
        self.results = {}
        self.warnings = []
        self.journal = {}

        self.window = tk.Toplevel(parent)
        self.window.title(f'Остаточный ресурс · {self.grp_name}')
        self.window.configure(bg=BG)
        self.window.transient(parent)
        self.window.grab_set()

        self._build_ui()
        self.calculate_and_display()
        # Окно по содержимому: широкие таблицы требуют места, но на ноутбуке
        # 1560x900 не влезало — размер считается от запроса виджетов и экрана.
        fit_window(self.window, min_width=900, min_height=560)

    # ------------------------------------------------------------------ UI

    def _init_styles(self):
        """Шрифт и высота строк таблиц разбора.

        Tk по умолчанию рисует строки около 20 px шрифтом 8 pt, в таблице
        расчёта по элементам это читается мелко. Стиль задаётся один раз на
        окно и используется только таблицами разбора — вкладки ввода и
        коэффициентов остались как были.
        """
        style = ttk.Style()
        style.configure('Calc.Treeview', font=('Segoe UI', 10), rowheight=28)
        style.configure('Calc.Treeview.Heading', font=('Segoe UI', 10, 'bold'))

    def _build_ui(self):
        self._init_styles()
        self._build_header()
        self.notebook = ttk.Notebook(self.window)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=14, pady=(0, 14))

        # Методики переключаются вертикальной лентой слева, а не вкладками
        # ноутбука: их пять, они равноправны и должны быть видны одновременно,
        # чтобы можно было сравнивать остаток не переклюкаясь туда-сюда.
        self.tab_algorithms = tk.Frame(self.notebook, bg=BG)
        self.notebook.add(self.tab_algorithms, text='  Алгоритмы  ')

        self.tab_horizon = tk.Frame(self.notebook, bg=BG)
        self.notebook.add(self.tab_horizon, text='  Срок замены  ')

        self.tab_coefficients = tk.Frame(self.notebook, bg=BG)
        self.notebook.add(self.tab_coefficients, text='  Коэффициенты  ')

        self.tab_trace = tk.Frame(self.notebook, bg=BG)
        self.notebook.add(self.tab_trace, text='  Пошаговый расчёт  ')

        self.tab_inputs = tk.Frame(self.notebook, bg=BG)
        self.notebook.add(self.tab_inputs, text='  Исходные данные  ')

        self.tab_method = tk.Frame(self.notebook, bg=BG)
        self.notebook.add(self.tab_method, text='  Методика  ')
        self._build_method_tab()

        self._algo_var = tk.IntVar(value=PRIMARY_ALGORITHM)
        self._build_algorithm_bar()
        self._build_algorithms_tab()
        self._build_horizon_tab()
        self._build_coefficients_tab()
        self._build_trace_tab()
        self._build_inputs_tab()

    def _build_header(self):
        header = tk.Frame(self.window, bg='#ffffff', highlightbackground=LINE,
                          highlightthickness=1, bd=0)
        header.pack(fill=tk.X, side=tk.TOP)

        inner = tk.Frame(header, bg='#ffffff')
        inner.pack(fill=tk.X, padx=18, pady=12)

        left = tk.Frame(inner, bg='#ffffff')
        left.pack(side=tk.LEFT)
        tk.Label(left, text='Остаточный ресурс ГРП', bg='#ffffff', fg=TEXT,
                 font=('Segoe UI', 17, 'bold')).pack(anchor=tk.W)
        self.header_sub = tk.Label(left, text=self.grp_name, bg='#ffffff', fg=MUTED,
                                   font=('Segoe UI', 10))
        self.header_sub.pack(anchor=tk.W)

        right = tk.Frame(inner, bg='#ffffff')
        right.pack(side=tk.RIGHT)
        _btn(right, 'Пересчитать', self.calculate_and_display,
             color='success').pack(side=tk.RIGHT, padx=(6, 0))
        _btn(right, 'Закрыть', self.window.destroy, color='muted').pack(side=tk.RIGHT)

    def _build_algorithm_bar(self):
        """Переключатель методики для детальных вкладок."""
        bar = tk.Frame(self.window, bg=BG)
        bar.pack(fill=tk.X, padx=14, pady=(10, 0))

        left = tk.Frame(bar, bg=BG)
        left.pack(side=tk.LEFT)
        tk.Label(left, text='Методика:', bg=BG, fg=MUTED,
                 font=('Segoe UI', 10)).pack(side=tk.LEFT, padx=(0, 8))
        chooser = ttk.Combobox(left, state='readonly', width=46,
                               values=[f'{algo_label(i)} · {ALGORITHM_TITLES[i]}'
                                       for i in range(5)],
                               font=('Segoe UI', 10))
        chooser.current(PRIMARY_ALGORITHM)
        chooser.bind('<<ComboboxSelected>>', self._on_algorithm_changed)
        chooser.pack(side=tk.LEFT)
        self._combo_algo = chooser

        self.algo_hint = tk.Label(bar, text='', bg=BG, fg=MUTED, font=('Segoe UI', 10))
        self.algo_hint.pack(side=tk.LEFT, padx=12)

    def _on_algorithm_changed(self, _event=None):
        self._algo_var.set(self._combo_algo.current())
        self.render_coefficients()
        self.render_trace()
    # ------------------------------------------------- Вертикальные вкладки

    def _build_algorithms_tab(self):
        """Лента методик слева и панель выбранной методики справа."""
        wrap = tk.Frame(self.tab_algorithms, bg=BG)
        wrap.pack(fill=tk.BOTH, expand=True, padx=14, pady=10)

        self.algo_values, self.algo_metas, self.algo_notes = {}, {}, {}
        self.algo_trees, self.algo_recommends = {}, {}
        self.soon_trees, self.soon_counts = {}, {}
        self.ext_sliders, self.ext_trees = {}, {}
        self.ext_head, self.ext_targets, self.ext_notes = {}, {}, {}
        self.algo_panes, self.algo_tabs = [], []
        self._selected_algorithm = PRIMARY_ALGORITHM
        self._payload = []
        self._coefficients_now = {}
        self._ladders = {}

        rail = tk.Frame(wrap, bg=BG, width=236)
        rail.pack(side=tk.LEFT, fill=tk.Y)
        rail.pack_propagate(False)
        tk.Label(rail, text='МЕТОДИКА', bg=BG, fg=MUTED,
                 font=('Segoe UI', 9, 'bold')).pack(anchor=tk.W, pady=(0, 6))
        for number in range(5):
            self.algo_tabs.append(
                self._build_vertical_tab(rail, number))

        holder = tk.Frame(wrap, bg=BG)
        holder.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(12, 0))
        for number in range(5):
            pane = tk.Frame(holder, bg=BG)
            self.algo_panes.append(pane)
            self._build_algorithm_pane(pane, number)
        self._select_algorithm(PRIMARY_ALGORITHM)
    def _build_vertical_tab(self, parent, number):
        """Плитка методики в вертикальной ленте: номер, имя и остаток."""
        outer = tk.Frame(parent, bg=BG)
        outer.pack(fill=tk.X, pady=(0, 4))

        active = tk.Frame(outer, bg=BG, width=4)
        active.pack(side=tk.LEFT, fill=tk.Y)

        card = tk.Frame(outer, bg=CARD, highlightbackground=LINE,
                        highlightthickness=1, bd=0, cursor='hand2')
        card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(4, 0))

        head = tk.Frame(card, bg=CARD, cursor='hand2')
        head.pack(fill=tk.X, padx=12, pady=(9, 0))
        number_label = tk.Label(head, text=f'Алг {algo_number(number)}', bg=CARD, fg=ACCENT,
                                font=('Segoe UI', 12, 'bold'), cursor='hand2')
        number_label.pack(side=tk.LEFT)
        badge = tk.Label(head, text='—', bg=CARD, fg=MUTED,
                         font=('Segoe UI', 11, 'bold'), cursor='hand2')
        badge.pack(side=tk.RIGHT)

        title = tk.Label(card, text=ALGORITHM_TITLES[number], bg=CARD, fg=MUTED,
                         font=('Segoe UI', 9), wraplength=180, justify=tk.LEFT,
                         anchor=tk.W, cursor='hand2')
        title.pack(fill=tk.X, padx=12, pady=(2, 10))

        widgets = (outer, active, card, head, number_label, badge, title)
        for widget in widgets:
            widget.bind('<Button-1>',
                        lambda _e, n=number: self._select_algorithm(n))
            widget.bind('<Enter>', lambda _e, n=number: self._hover_tab(n, True))
            widget.bind('<Leave>', lambda _e, n=number: self._hover_tab(n, False))
        return {'outer': outer, 'active': active, 'card': card, 'head': head,
                'number': number_label, 'badge': badge, 'title': title}

    def _hover_tab(self, number, active):
        """Подсветка плитки под курсором, если она не выбрана."""
        if number == self._selected_algorithm:
            return
        card = self.algo_tabs[number]['card']
        card.config(bg='#eef3fe' if active else CARD)

    def _select_algorithm(self, number):
        """Показывает панель методики и перекрашивает ленту."""
        self._selected_algorithm = number
        self._algo_var.set(number)
        for other, pane in enumerate(self.algo_panes):
            pane.pack_forget()
        self.algo_panes[number].pack(fill=tk.BOTH, expand=True)
        self._paint_algo_tabs()
        if self.results:
            self._render_extension(number)

    def _paint_algo_tabs(self):
        """Активная методика — белой плиткой с полосой, остальные приглушены."""
        for number, tab in enumerate(self.algo_tabs):
            selected = number == self._selected_algorithm
            card, active = tab['card'], tab['active']
            card.config(bg=CARD if selected else '#f0f3f7',
                        highlightbackground=ACCENT if selected else LINE)
            active.config(bg=ACCENT if selected else BG)
            head, badge = tab['head'], tab['badge']
            head.config(bg=card.cget('bg'))
            badge.config(bg=card.cget('bg'),
                         font=('Segoe UI', 11, 'bold' if selected else 'normal'))
            tab['number'].config(
                bg=card.cget('bg'),
                fg=ACCENT if selected else MUTED,
                font=('Segoe UI', 12, 'bold') if selected else ('Segoe UI', 11))
            tab['title'].config(bg=card.cget('bg'),
                                fg=TEXT if selected else MUTED)

    def _build_algorithm_pane(self, tab, number):
        """Панель одной методики: остаток, список замен и продление срока."""
        top = _card(tab)
        top.pack(fill=tk.X)
        tk.Label(top, text=f'{algo_label(number)} · {ALGORITHM_TITLES[number]}',
                 bg=CARD, fg=MUTED, font=('Segoe UI', 10)).pack(
            anchor=tk.W, padx=18, pady=(12, 0))
        body = tk.Frame(top, bg=CARD)
        body.pack(fill=tk.X, padx=18, pady=(4, 12))
        self.algo_values[number] = tk.Label(body, text='—', bg=CARD, fg=TEXT,
                                           font=('Segoe UI', 34, 'bold'))
        self.algo_values[number].pack(side=tk.LEFT, anchor=tk.W)
        info = tk.Frame(body, bg=CARD)
        info.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(24, 0),
                  anchor=tk.W)
        self.algo_metas[number] = tk.Label(info, text='', bg=CARD, fg=MUTED,
                                          font=('Segoe UI', 10), justify=tk.LEFT)
        self.algo_metas[number].pack(anchor=tk.W)
        self.algo_notes[number] = tk.Label(info, text='', bg=CARD, fg=MUTED,
                                          font=('Segoe UI', 9), justify=tk.LEFT,
                                          wraplength=780)
        self.algo_notes[number].pack(anchor=tk.W, pady=(4, 0))

        self._build_soon_card(tab, number)
        self._build_extension_card(tab, number)
        self._build_elements_card(tab, number)

    # ------------------------------------------------- Скоро нужно менять

    def _build_soon_card(self, parent, number):
        """Список того, что скоро придётся менять, с деталями внутри строки."""
        card = _card(parent)
        card.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
        head = tk.Frame(card, bg=CARD)
        head.pack(fill=tk.X, padx=16, pady=(12, 0))
        tk.Label(head, text='Скоро нужно менять', bg=CARD, fg=TEXT,
                 font=('Segoe UI', 11, 'bold')).pack(side=tk.LEFT)
        tk.Label(head, text=f'остаток ≤ {_horizon_text(SOON_HORIZON)} или '
                            f'в пределах {num(WEAK_LINK_TOLERANCE, 1)} года от '
                            f'ближайшего · раскройте строку — внутри детали на '
                            f'{num(PART_NORM_YEARS, 0)} лет',
                 bg=CARD, fg=MUTED, font=('Segoe UI', 9)).pack(side=tk.LEFT, padx=12)
        self.soon_counts[number] = tk.Label(head, text='', bg=CARD, fg=MUTED,
                                            font=('Segoe UI', 9, 'bold'))
        self.soon_counts[number].pack(side=tk.RIGHT)

        self.soon_trees[number] = _tree_hier(
            card,
            columns=('Категория', 'Норма', 'Возраст', 'Осталось',
                     'Истекает', 'Статус'),
            widths={'Категория': 190, 'Норма': 90, 'Возраст': 95, 'Осталось': 115,
                    'Истекает': 105, 'Статус': 130},
            height=6,
        )
        for tag, color in (('soon', '#fdf3e0'), ('over', '#fbeaea'),
                           ('part', '#f7f9fc')):
            self.soon_trees[number].tag_configure(tag, background=color)

    def _render_soon_card(self, number):
        """Заполняет список замен: строка — элемент, вложенные — его детали."""
        tree = self.soon_trees[number]
        tree.delete(*tree.get_children())
        result = self.results.get(number)
        if result is None or result.error:
            self.soon_counts[number].config(text='', fg=MUTED)
            return

        used = result.used_elements
        if not used:
            self.soon_counts[number].config(text='нет элементов в расчёте', fg=BAD)
            return
        nearest = min(e.z_element for e in used)
        due = [e for e in used
               if e.z_element <= SOON_HORIZON
               or e.z_element <= nearest + WEAK_LINK_TOLERANCE]

        for element in sorted(due, key=lambda e: (e.z_element, e.name)):
            tag = 'over' if element.z_element <= 0 else 'soon'
            parent = tree.insert('', tk.END, open=True, tags=(tag,), text=(
                element.name[:80]), values=(
                critical_title(element.critical_key) if element.critical_key else '—',
                years_to_text(element.norm),
                years_to_text(element.age),
                years_to_text(element.z_element),
                _due_date(element.z_element),
                'просрочено' if element.z_element <= 0 else 'скоро',
            ))
            parts = [d for d in (element.details or []) if _is_counted_part(d)]
            if not parts:
                tree.insert(parent, tk.END, tags=('part',),
                            text='нет деталей с нормой 5 лет в расчёте',
                            values=('', '—', '—', '—', '', ''))
                continue
            for detail in sorted(parts, key=_part_residual):
                left = _part_residual(detail)
                tree.insert(parent, tk.END, tags=('part',), text=(
                    f'    {detail.get("name", "деталь")}'), values=(
                    'деталь', years_to_text(detail.get('norm')),
                    years_to_text(detail.get('age')), years_to_text(left),
                    _due_date(left),
                    'просрочена' if left <= 0 else 'осталось',
                ))

        self.soon_counts[number].config(
            text=f'{len(due)} из {len(used)} элементов', fg=BAD if due else GOOD)

    # ------------------------------------------------------------ Продление

    def _build_extension_card(self, parent, number):
        """Ползунок цели продления и список того, что придётся заменить."""
        card = _card(parent)
        card.pack(fill=tk.X, pady=(10, 0))

        head = tk.Frame(card, bg=CARD)
        head.pack(fill=tk.X, padx=16, pady=(12, 0))
        tk.Label(head, text='Продление срока', bg=CARD, fg=TEXT,
                 font=('Segoe UI', 11, 'bold')).pack(side=tk.LEFT)
        self.ext_head[number] = tk.Label(head, text='', bg=CARD, fg=MUTED,
                                         font=('Segoe UI', 9), justify=tk.LEFT)
        self.ext_head[number].pack(side=tk.LEFT, padx=12)

        self.ext_targets[number] = tk.Label(card, text='', bg=CARD, fg=MUTED,
                                            font=('Segoe UI', 11, 'bold'),
                                            justify=tk.LEFT)
        self.ext_targets[number].pack(anchor=tk.W, padx=16, pady=(4, 0))
        self.ext_notes[number] = tk.Label(card, text='', bg=CARD, fg=MUTED,
                                          font=('Segoe UI', 9), justify=tk.LEFT,
                                          wraplength=900, anchor=tk.W)
        self.ext_notes[number].pack(fill=tk.X, padx=16)

        self.ext_trees[number] = _tree_hier(
            card,
            columns=('Категория', 'Что менять', 'Срок сейчас',
                     'Срок после замены', 'Прирост'),
            widths={'Категория': 110, 'Что менять': 420, 'Срок сейчас': 130,
                    'Срок после замены': 140, 'Прирост': 110},
            height=3,
        )
        for tag, color in (('step', '#f7f9fc'), ('last', '#e6f6ee'),
                           ('stuck', '#fdf3e0')):
            self.ext_trees[number].tag_configure(tag, background=color)

        slider_row = tk.Frame(card, bg=CARD)
        slider_row.pack(fill=tk.X, padx=16, pady=(4, 8))
        tk.Label(slider_row, text='хочу продлить на', bg=CARD, fg=MUTED,
                 font=('Segoe UI', 9)).pack(anchor=tk.W)
        self.ext_sliders[number] = HorizonSlider(
            slider_row, EXTENSION_MAX, HORIZON_SNAP,
            command=lambda _value, n=number: self._render_extension(n))
        self.ext_sliders[number].pack(fill=tk.X, expand=True)
        self.ext_sliders[number].set(0.0)

    def _simulate(self, number, renewed_ids):
        """Пересчёт методики с условно заменёнными деталями.

        Идёт через настоящий движок, а не через копию формул: иначе лестница
        продления разошлась бы с расчётом при любой правке методики.
        """
        payload = copy.deepcopy(self._payload or [])
        today = date.today().isoformat()
        for equipment in payload:
            if equipment.get('equipment_id') not in renewed_ids:
                continue
            for detail in equipment.get('details') or []:
                if _is_counted_part({'norm': detail.get('norm_years')}):
                    detail['install_date'] = today
        calculator = GRPResourceCalculator(None, self.params, self._coefficients_now)
        return getattr(calculator, f'calculate_algorithm_{number}')(payload)

    def _extension_ladder(self, number):
        """Лестница: какая замена что даёт, шаг за шагом.

        Считается один раз на методику и кэшируется, иначе на каждое движение
        ползунка пришлось бы гонять пересчёт заново.

        Слабых звеньев обычно несколько: если у пяти элементов ресурс одинаковый,
        замена одного из них не двигает общий срок — минимум держит другой.
        Поэтому шаг продолжается, пока рядом есть ещё не тронутые равные звенья.
        """
        if number in self._ladders:
            return self._ladders[number]
        result = self.results.get(number)
        steps = []
        if result is not None and not result.error and result.used_elements:
            weak = min(result.used_elements, key=lambda e: (e.z_element, e.name))
            all_ids = {e.get('equipment_id') for e in (self._payload or [])
                       if e.get('equipment_id')}
            probe = self._simulate(number, all_ids).result if all_ids else None
            if probe is not None and abs(probe - result.result) <= 1e-9:
                # Замена всех учитываемых деталей не изменила срок — методика
                # считает ресурс по оборудованию, а не по износу деталей.
                steps = [{'element': weak, 'parts': _counted_parts(weak),
                          'before': result.result, 'after': result.result,
                          'gain': 0.0, 'stuck': True, 'parts_ineffective': True}]
            else:
                renewed, seen = set(), set()
                for _ in range(EXTENSION_STEPS):
                    sim = self._simulate(number, renewed)
                    if sim.error or not sim.used_elements:
                        break
                    weak = min(sim.used_elements, key=lambda e: (e.z_element, e.name))
                    parts = _pick_parts(weak)
                    if weak.equipment_id in seen:
                        steps.append({'element': weak, 'parts': [],
                                      'before': sim.result, 'after': sim.result,
                                      'gain': 0.0, 'stuck': True})
                        break
                    seen.add(weak.equipment_id)
                    renewed.add(weak.equipment_id)
                    after = self._simulate(number, renewed).result
                    gain = after - sim.result
                    tied = any(e.equipment_id not in seen
                               and e.z_element <= sim.result + WEAK_LINK_TOLERANCE
                               for e in sim.used_elements)
                    steps.append({'element': weak, 'parts': parts,
                                  'before': sim.result, 'after': after,
                                  'gain': gain, 'stuck': gain <= 0 and not tied})
                    if gain <= 0 and not tied:
                        break
        self._ladders[number] = steps
        return steps

    def _render_extension(self, number):
        """Показывает шаги до цели ползунка и итог продления."""
        target = float(self.ext_sliders[number].get())
        tree = self.ext_trees[number]
        tree.delete(*tree.get_children())
        result = self.results.get(number)
        steps = self._extension_ladder(number)
        head, note = self.ext_head[number], self.ext_notes[number]

        if result is None or result.error:
            head.config(text='')
            note.config(text='', fg=MUTED)
            self.ext_targets[number].config(text='', fg=MUTED)
            return

        if not steps:
            head.config(text='')
            self.ext_targets[number].config(
                text='продлить нечем: в расчёт не вошёл ни один элемент', fg=BAD)
            note.config(text='', fg=MUTED)
            return

        first = steps[0]
        if first.get('parts_ineffective'):
            head.config(text=f'{num(PART_NORM_YEARS, 0)}-летние детали не входят '
                             f'в эту методику — их замена срок не двигает')
        elif first['gain'] > 0:
            head.config(text=f'замена «{first["element"].name[:40]}» даёт '
                             f'+{years_to_text(first["gain"])}')
        else:
            reach = steps[-1]['after'] - result.result
            head.config(text=f'слабых звеньев сразу несколько: по одному с '
                             f'+{years_to_text(reach)} всего')

        goal = result.result + target
        needed, reach = [], result.result
        for step in steps:
            if reach >= goal - 1e-9:
                break
            needed.append(step)
            reach = step['after']

        for index, step in enumerate(needed, 1):
            last = index == len(needed)
            tree.insert('', tk.END, text=f'{index}. {step["element"].name[:64]}',
                        tags=('stuck' if step['stuck']
                              else 'last' if last and reach >= goal - 1e-9
                              else 'step',),
                        values=(
                            critical_title(step['element'].critical_key)
                            if step['element'].critical_key else '—',
                            _parts_text(step['parts']),
                            years_to_text(step['before']),
                            years_to_text(step['after']),
                            f'+{years_to_text(step["gain"])}',
                        ))

        if target <= 0:
            self.ext_targets[number].config(
                text=f'сейчас {years_to_text(result.result)} — сдвиньте ползунок, '
                     f'чтобы увидеть, что менять', fg=MUTED)
            note.config(text='Продление считается заменой ближайшего слабого звена: '
                             'по одному элементу за раз, пока не наберётся срок.',
                        fg=MUTED)
            return

        if reach >= goal - 1e-9:
            self.ext_targets[number].config(
                text=f'продлить на {years_to_text(target)} → '
                     f'{years_to_text(goal)}: замен {len(needed)}', fg=GOOD)
            note.config(text=f'Заменами подряд срок дорастает до '
                             f'{years_to_text(reach)} (было '
                             f'{years_to_text(result.result)}).', fg=MUTED)
        else:
            gained = max(0.0, reach - result.result)
            self.ext_targets[number].config(
                text=f'на {years_to_text(target)} не хватает: максимум '
                     f'+{years_to_text(gained)}', fg=WARN)
            note.config(
                text=(f'{algo_label(number)} считает ресурс оборудования до полной '
                      f'проверки ({num(FULL_CHECK_TERM, 0)} лет) и не зависит от '
                      f'износа деталей: замена деталей его срок не двигает. '
                      f'Продление возможно только заменой оборудования целиком.')
                if steps[0].get('parts_ineffective') else
                (f'Больше продлить нельзя: слабыми оказались все элементы, '
                 f'последняя замена выводит срок на {years_to_text(reach)}. '
                 f'Дальше растёт уже не ресурс, а необходимость менять '
                 f'оборудование целиком.'),
                fg=MUTED)

    # ----------------------------------------------- Элементы и коэффициенты

    def _build_elements_card(self, parent, number):
        """Разбор расчёта по элементам: база, коэффициенты, остаток."""
        card = _card(parent)
        card.pack(fill=tk.X, pady=(10, 0))
        tk.Label(card, text='Как посчитано: элементы и коэффициенты', bg=CARD,
                 fg=MUTED, font=('Segoe UI', 10)).pack(anchor=tk.W, padx=14,
                                                       pady=(10, 4))
        self.algo_trees[number] = _tree(
            card,
            columns=('Элемент', 'Категория', 'Норма', 'Возраст', 'Z база',
                     'K сост', 'K эксл', 'K рем', 'k повр', 'Осталось'),
            widths={'Элемент': 330, 'Категория': 140, 'Норма': 105, 'Возраст': 110,
                    'Z база': 100, 'K сост': 95, 'K эксл': 95, 'K рем': 95,
                    'k повр': 95, 'Осталось': 130},
            height=4,
            style='Calc.Treeview',
            wide_first=True,
        )
        for tag, color in (('good', '#e6f6ee'), ('warn', '#fdf3e0'),
                           ('bad', '#fbeaea'), ('skip', '#f2f4f7')):
            self.algo_trees[number].tag_configure(tag, background=color)
        self.algo_recommends[number] = tk.Label(
            card, text='', bg=CARD, fg=ACCENT, font=('Segoe UI', 10, 'bold'),
            justify=tk.LEFT, wraplength=1400)
        self.algo_recommends[number].pack(anchor=tk.W, padx=14, pady=(8, 12))


    def _render_algorithm_pane(self, number):
        """Заполняет панель методики по свежему результату расчёта."""
        result = self.results.get(number)
        value_label = self.algo_values[number]
        meta_label = self.algo_metas[number]
        note_label = self.algo_notes[number]
        tree = self.algo_trees[number]
        recommend = self.algo_recommends[number]

        tree.delete(*tree.get_children())
        badge = self.algo_tabs[number]['badge']

        if result is None:
            value_label.config(text='\u2014', fg=BAD)
            meta_label.config(text='методика не рассчитана')
            note_label.config(text='')
            recommend.config(text='')
            badge.config(text='\u2014', fg=MUTED)
            self._render_soon_card(number)
            return

        if result.error:
            value_label.config(text='\u2014', fg=BAD)
            meta_label.config(text=result.error)
            note_label.config(text='')
            recommend.config(text='')
            badge.config(text='ошибка', fg=BAD)
            self._render_soon_card(number)
            return

        value_label.config(text=years_to_text(result.result),
                           fg=self._color(result.result))
        meta_label.config(text=f'{self._rating(result.result)}\n'
                               f'T диагн. = {years_to_text(result.next_diagnosis)}\n'
                               f'элементов в расчёте: {len(result.used_elements)} '
                               f'из {len(result.elements)}')
        badge.config(text=years_to_text(result.result),
                     fg=self._color(result.result))

        skipped = [e for e in result.elements if not e.used]
        note = ''
        if number in (3, 4):
            note = CONSERVATIVE_NOTE + '  '
        note += (CONSERVATIVE_SCALE if number == 4 else '')
        if skipped:
            note += (f'не вошло в расчёт: {len(skipped)} '
                     f'({skipped[0].skip_reason})')
        note_label.config(text=note)

        for element in sorted(result.elements,
                              key=lambda e: (not e.used, e.z_element)):
            tag = ('skip' if not element.used
                   else 'bad' if element.z_element <= 0
                   else 'warn' if element.z_element < 1.0 else 'good')
            tree.insert('', tk.END, tags=(tag,), values=(
                element.name[:70],
                critical_short_title(element.critical_key) if element.critical_key else '—',
                years_to_text(element.norm),
                years_to_text(element.age),
                num(element.z_base, 2),
                num(element.k_state, 3),
                num(element.k_cond, 3),
                num(element.k_repair, 3),
                num(element.k_fail, 3),
                '—' if not element.used else years_to_text(element.z_element),
            ))
        recommend.config(text=result.recommendation or '')

        self._render_soon_card(number)
        self._render_extension(number)

    # ------------------------------------------------------- Срок замены

    def _build_horizon_tab(self):
        """Ползунок горизонта 0-5 лет и список того, что к нему истекает."""
        wrap = tk.Frame(self.tab_horizon, bg=BG)
        wrap.pack(fill=tk.BOTH, expand=True, padx=14, pady=10)

        top = _card(wrap)
        top.pack(fill=tk.X)

        head = tk.Frame(top, bg=CARD)
        head.pack(fill=tk.X, padx=18, pady=(12, 0))
        tk.Label(head, text='Что нужно заменить', bg=CARD, fg=MUTED,
                 font=('Segoe UI', 10)).pack(side=tk.LEFT)
        chooser = ttk.Combobox(head, state='readonly', width=42,
                               values=[f'{algo_label(i)} · {ALGORITHM_TITLES[i]}'
                                       for i in range(5)],
                               font=('Segoe UI', 10))
        chooser.current(PRIMARY_ALGORITHM)
        chooser.bind('<<ComboboxSelected>>', self._on_horizon_algorithm)
        chooser.pack(side=tk.RIGHT)
        self._combo_horizon_algo = chooser

        slider_row = tk.Frame(top, bg=CARD)
        slider_row.pack(fill=tk.X, padx=18, pady=(6, 0))
        self.horizon_slider = HorizonSlider(slider_row, HORIZON_MAX,
                                            HORIZON_SNAP,
                                            command=self._on_horizon_changed)
        self.horizon_slider.pack(fill=tk.X, expand=True)
        tk.Label(slider_row, text='тяните мышью · ← → по месяцу · Home/End',
                 bg=CARD, fg=MUTED, font=('Segoe UI', 8)).pack(
            anchor=tk.E, pady=(0, 4))

        readout = tk.Frame(top, bg=CARD)
        readout.pack(fill=tk.X, padx=18, pady=(0, 12))
        self.horizon_label = tk.Label(readout, text='', bg=CARD, fg=TEXT,
                                      font=('Segoe UI', 15, 'bold'))
        self.horizon_label.pack(side=tk.LEFT)
        self.horizon_count = tk.Label(readout, text='', bg=CARD, fg=MUTED,
                                      font=('Segoe UI', 10), justify=tk.LEFT)
        self.horizon_count.pack(side=tk.LEFT, padx=(18, 0))

        table = _card(wrap)
        table.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
        self.tree_horizon = _tree(
            table,
            columns=('Элемент', 'Тип', 'Деталь', 'Норма детали', 'Возраст детали',
                     'Осталось детали', 'Осталось элемента', 'К замене'),
            widths={'Элемент': 300, 'Тип': 110, 'Деталь': 330, 'Норма детали': 100,
                    'Возраст детали': 110, 'Осталось детали': 120,
                    'Осталось элемента': 130, 'К замене': 100},
            height=12,
        )
        for tag, color in (('good', '#e6f6ee'), ('warn', '#fdf3e0'),
                           ('bad', '#fbeaea')):
            self.tree_horizon.tag_configure(tag, background=color)

    def _on_horizon_algorithm(self, _event=None):
        index = self._combo_horizon_algo.current()
        if index < 0:
            return
        self._algo_var.set(index)
        self._combo_algo.current(index)
        self.render_horizon()

    def _on_horizon_changed(self, _value=None):
        self.render_horizon()

    def _horizon_number(self) -> int:
        index = self._combo_horizon_algo.current()
        return index if index >= 0 else PRIMARY_ALGORITHM

    def render_horizon(self):
        """Перерисовывает список замен под текущий горизонт и методику."""
        number = self._horizon_number()
        horizon = float(self.horizon_slider.get())
        result = self.results.get(number)
        tree = self.tree_horizon
        tree.delete(*tree.get_children())

        self.horizon_label.config(
            text=f'Горизонт {_horizon_text(horizon)}',
            fg=self._color(horizon) if horizon < 1.0 else TEXT)

        if result is None or result.error:
            self.horizon_count.config(
                text=result.error if result else 'методика не рассчитана', fg=BAD)
            self.horizon_slider.set_level('none')
            return

        due, later = [], []
        for element in result.used_elements:
            part = driving_part(element)
            part_z = _part_residual(part)
            row = (
                element.name[:70],
                critical_title(element.critical_key) if element.critical_key else '—',
                (part.get('name') if part else '—'),
                years_to_text(part.get('norm')) if part else '—',
                years_to_text(part.get('age')) if part else '—',
                years_to_text(part_z) if part_z is not None else '—',
                years_to_text(element.z_element),
                'да' if element.z_element <= horizon else 'нет',
            )
            (due if element.z_element <= horizon else later).append(
                (element, part, part_z, row))

        due.sort(key=lambda item: (item[0].z_element, item[0].name))
        later.sort(key=lambda item: (item[0].z_element, item[0].name))
        for element, _part, _z, row in due + later:
            tag = ('bad' if element.z_element <= 0
                   else 'warn' if element.z_element <= horizon else 'good')
            tree.insert('', tk.END, tags=(tag,), values=row)

        total = len(result.used_elements)
        if not due:
            self.horizon_slider.set_level('none')
            text = (f'к {_horizon_text(horizon)} не истекает ни один элемент: '
                    f'ближайший — '
                    f'{years_to_text(later[0][0].z_element) if later else "—"}')
            color = GOOD
        elif len(due) >= total:
            self.horizon_slider.set_level('all')
            text = (f'к {_horizon_text(horizon)} просрочено всё: {len(due)} из '
                    f'{total} элементов ({len({e.equipment_id for e, _, _, _ in due})}'
                    f' ед. оборудования)')
            color = BAD
        else:
            self.horizon_slider.set_level('some')
            text = (f'к {_horizon_text(horizon)} истекает: {len(due)} из {total} '
                    f'элементов ({len({e.equipment_id for e, _, _, _ in due})}'
                    f' ед. оборудования)')
            color = WARN
        self.horizon_count.config(text=text, fg=color)

    # -------------------------------------------------------- Коэффициенты

    def _build_coefficients_tab(self):
        tk.Label(self.tab_coefficients,
                 text='Поэлементный расчёт коэффициентов. Пустая ячейка с прочерком '
                      'означает, что данных нет и коэффициент принят равным 1.',
                 bg=BG, fg=MUTED, font=('Segoe UI', 9)).pack(anchor=tk.W, pady=(10, 6))

        self.tree_coefficients = _tree(
            self.tab_coefficients,
            columns=('Элемент', 'Категория', 'S_нач', 'Возраст', 'Z_база', 'Вариант',
                     'K_сост', 'K_эксл', 'K_рем', 'k_повр', 'Z_эл', 'Формула Z_эл'),
            widths={'Элемент': 240, 'Категория': 190, 'S_нач': 90, 'Возраст': 95,
                    'Z_база': 80, 'Вариант': 70, 'K_сост': 80, 'K_эксл': 75,
                    'K_рем': 70, 'k_повр': 75, 'Z_эл': 85, 'Формула Z_эл': 430},
            height=16,
        )
        self.tree_coefficients.tag_configure('weak', background='#fbeaea')
        self.tree_coefficients.tag_configure('skip', foreground='#9aa5b1')
        self.tree_coefficients.tag_configure('zero', background='#fdf3e0')

    # ------------------------------------------------------------ Трассировка

    def _build_trace_tab(self):
        bar = tk.Frame(self.tab_trace, bg=BG)
        bar.pack(fill=tk.X, padx=14, pady=(10, 0))
        _btn(bar, 'Скопировать трассировку', self._copy_trace,
             color='muted', font_size=9).pack(side=tk.RIGHT)

        self.text_trace = _text_block(self.tab_trace, height=30)
        for level, (color, bold, italic) in TRACE_COLORS.items():
            self.text_trace.tag_configure(
                level, foreground=color,
                font=('Consolas', 10, 'bold') if bold else ('Consolas', 10, 'italic')
                if italic else ('Consolas', 10),
            )
        self.text_trace.tag_configure('element', foreground='#7b3fa0', font=('Consolas', 10, 'bold'))

    def _copy_trace(self):
        text = self.text_trace.get('1.0', tk.END)
        self.window.clipboard_clear()
        self.window.clipboard_append(text)
        messagebox.showinfo('Скопировано', 'Трассировка расчёта скопирована в буфер обмена')

    # ------------------------------------------------------- Исходные данные

    def _build_inputs_tab(self):
        wrap = tk.Frame(self.tab_inputs, bg=BG)
        wrap.pack(fill=tk.BOTH, expand=True, padx=14, pady=10)

        params_card = _card(wrap)
        params_card.pack(fill=tk.X, pady=(0, 10))
        self._build_params_panel(params_card)

        journal_card = _card(wrap)
        journal_card.pack(fill=tk.X, pady=(0, 10))
        self._build_journal_panel(journal_card)

        tk.Label(wrap, text='Что поступило в расчёт по каждому элементу',
                 bg=BG, fg=MUTED, font=('Segoe UI', 10)).pack(anchor=tk.W)
        self.tree_inputs = _tree(
            wrap,
            columns=('Элемент', 'Категория', 'S_нач', 'Источник', 'Детали',
                     'Z_база', 'Отказы', 'Повреж.', 'Ремонт', 'В расчёте'),
            widths={'Элемент': 230, 'Категория': 170, 'S_нач': 90, 'Источник': 175,
                    'Детали': 70, 'Z_база': 70, 'Отказы': 60, 'Повреж.': 70,
                    'Ремонт': 145, 'В расчёте': 210},
            height=9,
        )
        self.tree_inputs.tag_configure('skip', foreground='#9aa5b1')
        self.tree_inputs.tag_configure('weak', background='#fbeaea')

    def _build_params_panel(self, parent):
        head = tk.Frame(parent, bg=CARD)
        head.pack(fill=tk.X, padx=16, pady=(12, 0))
        tk.Label(head, text='Весовые коэффициенты методики', bg=CARD, fg=TEXT,
                 font=('Segoe UI', 11, 'bold')).pack(side=tk.LEFT)
        tk.Label(head, text='значения по умолчанию — рекомендуемые методикой; '
                            'меняются под конкретный объект',
                 bg=CARD, fg=MUTED, font=('Segoe UI', 9)).pack(side=tk.LEFT, padx=12)

        body = tk.Frame(parent, bg=CARD)
        body.pack(fill=tk.X, padx=16, pady=(8, 12))

        fields = [
            ('alpha_fail', 'α — вес отказа', '0,15'),
            ('beta_damage', 'β — вес повреждения', '0,10'),
            ('theta_conditions', 'θ — условия эксплуатации', '0,10'),
            ('delta_repair', 'δ — качество ремонта', '0,10'),
            ('reserve', 'K запаса', '0,50'),
            ('max_diag_interval', 'T макс. диагностики', '5'),
        ]
        self._param_entries = {}
        for row, (attr, label, default) in enumerate(fields):
            column = row % 4
            block = tk.Frame(body, bg=CARD)
            block.grid(row=row // 4, column=column, sticky=tk.W,
                       padx=(0, 22), pady=4)
            tk.Label(block, text=label, bg=CARD, fg=MUTED,
                     font=('Segoe UI', 9)).pack(anchor=tk.W)
            entry = tk.Entry(block, width=8, font=('Consolas', 10), bd=1,
                             relief='solid', highlightthickness=0, justify=tk.RIGHT)
            entry.insert(tk.END, default)
            entry.pack(anchor=tk.W, pady=(2, 0))
            self._param_entries[attr] = entry

        actions = tk.Frame(body, bg=CARD)
        actions.grid(row=2, column=0, columnspan=4, sticky=tk.W, pady=(8, 0))
        _btn(actions, 'Пересчитать с этими коэффициентами',
             self._apply_params, color='success').pack(side=tk.LEFT)
        _btn(actions, 'Вернуть методические значения',
             self._reset_params, color='muted').pack(side=tk.LEFT, padx=8)

    def _build_journal_panel(self, parent):
        head = tk.Frame(parent, bg=CARD)
        head.pack(fill=tk.X, padx=16, pady=(12, 0))
        tk.Label(head, text='Журнал технической диагностики (A, B, C → K общ)',
                 bg=CARD, fg=TEXT, font=('Segoe UI', 11, 'bold')).pack(side=tk.LEFT)

        body = tk.Frame(parent, bg=CARD)
        body.pack(fill=tk.X, padx=16, pady=(8, 12))
        self._journal_text = tk.Label(body, text='—', bg=CARD, fg=MUTED,
                                      font=('Segoe UI', 10), justify=tk.LEFT,
                                      anchor=tk.W)
        self._journal_text.pack(fill=tk.X)

    def _read_params(self) -> AlgorithmParams:
        values = {}
        for attr, entry in self._param_entries.items():
            raw = entry.get().replace(',', '.').strip()
            try:
                values[attr] = float(raw)
            except ValueError:
                pass
        base = AlgorithmParams()
        for attr in values:
            setattr(base, attr, values[attr])
        return base

    def _apply_params(self):
        self.params = self._read_params()
        self.calculate_and_display()

    def _reset_params(self):
        self.params = AlgorithmParams()
        digits = {'max_diag_interval': 1}
        for attr, entry in self._param_entries.items():
            entry.delete(0, tk.END)
            entry.insert(tk.END, num(getattr(self.params, attr), digits.get(attr, 2)))
        self.calculate_and_display()

    # ------------------------------------------------------------ Методика

    def _build_method_tab(self):
        wrap = tk.Frame(self.tab_method, bg=BG)
        wrap.pack(fill=tk.BOTH, expand=True, padx=14, pady=10)
        box = _text_block(wrap, height=30, font=('Segoe UI', 10))
        box.tag_configure('h', foreground=ACCENT, font=('Segoe UI', 12, 'bold'))
        box.tag_configure('f', foreground='#0b3d91', font=('Consolas', 10))
        box.tag_configure('s', foreground=MUTED, font=('Segoe UI', 9, 'italic'))

        def put(text, tag=None):
            box.insert(tk.END, text, tag)

        put('КАК СЧИТАЕТСЯ ОСТАТОЧНЫЙ РЕСУРС\n', 'h')
        put('Методика описана пошагово: результат любого элемента можно воспроизвести '
            'вручную по данным, которые видны во вкладке «Исходные данные».\n\n')

        put('Шаг 1. Отбор критических элементов\n', 'h')
        put('В расчёт входят только: регулятор давления, ПЗК, ПСК, фильтр, '
            'запорная арматура. ГРП — последовательная система, отказ любого из них '
            'останавливает весь пункт.\n\n')

        put('Шаг 2. Базовый ресурс Zбаза — каскад оценок\n', 'h')
        put('А. По фактической наработке (телеметрия):\n', 'f')
        put('   Z = (Sнач − Sфакт) / Sнач · Sнач,эл\n\n', 'f')
        put('Б1. По протоколу диагностики детали:\n', 'f')
        put('   Zд = Kсост,д · Sнач,д\n\n', 'f')
        put('Б2. Документальная (экспертная) оценка остаточного ресурса детали:\n', 'f')
        put('   Zд = Sнач,д − Sфакт,д\n\n', 'f')
        put('В. Календарный (резервный) вариант при отсутствии деталей:\n', 'f')
        put('   Z = Sнач − Sфакт\n\n', 'f')
        put('Ресурс элемента — минимум по его деталям (слабейшая деталь).\n\n')

        put('Шаги 3-6. Поправки\n', 'h')
        put('Kсост = 1 − (1/n) · Σ |Δij| / Допускij\n', 'f')
        put('Kэксл = 1 − θ · (1 − Услфакт / Услнорм)\n', 'f')
        put('Kрем  = 1 − δ · (1 − Ремфакт / Ремнорм);  замена на новое → 1, '
            'некачественный ремонт → 0,9\n', 'f')
        put('kповр = max(0; 1 − α·Nотказ − β·Nповрежд)\n\n', 'f')
        put('Если данных нет — коэффициент принимается равным 1, и это обязательно '
            'показывается в трассировке.\n\n')

        put('Шаг 7. Некратные замены\n', 'h')
        put('Сумма израсходованного ресурса замен Σ (Sфакт,д / Sнач,д): если она меньше 1, '
            'ресурс деталей не исчерпан, в трассировке это отмечается отдельной строкой.\n\n')

        put('Шаг 8. Ресурс элемента\n', 'h')
        put('Zэл = Zбаза · Kсост · Kэксл · Kрем · kповр\n\n', 'f')

        put('Шаги 9-11. Итог по ГРП\n', 'h')
        put('Алгоритмы 3, 4, 5:  ZГРП = min (Zрег; Zпзк; Zпск; Zфильтр; Zарматура)\n', 'f')
        put('Алгоритм 1:  ZГРП = Σ Zэл / m      (среднее арифметическое)\n', 'f')
        put('Алгоритм 2:  ZГРП = (Σ Zэл / m) · Kобщ,  Kобщ = 1 − (A + B + C)\n', 'f')
        put('Алгоритм 5:  Zбаза = Zкаленд = Sнач − Sфакт (срок полной проверки '
            'минус возраст оборудования)\n', 'f')
        put('Взвешивание с фактической наработкой (α·Zкаленд + (1−α)·Zнаработка) '
            'не применяется: телеметрии по элементам нет.\n', 's')
        put('Tдиагн = min (ZГРП · Kзапаса ; Tмакс)\n\n', 'f')

        put('ИСТОЧНИКИ (папка docs/)\n', 'h')
        put('«Алгоритм 3-без календаря-5+.pdf» — скорректированная редакция методики 4: '
            'приоритет наработки, двойной учёт Kсост, некратные замены, Tдиагн.\n', 's')
        put('«Алг3-схема данных.pdf» — привязка шагов к цифровому паспорту ГРП, '
            'сквозной пример ГРП №26.\n', 's')
        put('«Алгоритм4.pdf» — источник методики 5; из него взята календарная база, '
            'взвешивание с наработкой отключено.\n', 's')
        put('«Алгоритмы-(все до корректировки).pdf» — методики 1-3.\n', 's')
        put('«Методика оценки фактической наработки отключающего устройства на входе.docx» '
            '— правила учёта наработки.\n', 's')
        put('«Методика определения назначенных показателей долговечности элементов ГРП '
            'при отсутствии нормативных данных производителя.docx» — правила нормативов.\n', 's')
        box.config(state=tk.DISABLED)

    # ------------------------------------------------------------- Расчёт

    def calculate_and_display(self):
        """Собирает данные из БД, считает все алгоритмы и обновляет вкладки."""
        try:
            coefficients = self._coefficients()
            payload, self.warnings, self.journal = self._collect_input(coefficients)
            self.results = calculate_all_algorithms(
                payload,
                params=self.params,
                coefficients=coefficients,
            )
            self._payload = payload
            self._coefficients_now = coefficients
            self._ladders = {}
        except Exception as exc:  # noqa: BLE001 — окно не должно падать
            messagebox.showerror('Ошибка расчёта', f'Не удалось выполнить расчёт:\n{exc}')
            return

        self._audit_results()
        for number in range(5):
            self._render_algorithm_pane(number)
        self.render_horizon()
        self.render_coefficients()
        self.render_trace()
        self._render_inputs()
        self._render_journal_card(coefficients)
        self._update_header()

    def _row_to_dict(self, row):
        """Кортеж БД → словарь элемента."""
        row = list(row) + [None] * 4
        return {
            'name': row[1] or '',
            'equipment_id': row[0],
            'install_date': row[2],
            'removal_date': row[3],
        }

    def _collect_input(self, coefficients):
        """Готовит вход для расчёта и список замечаний по данным."""
        journal = self._load_journal()
        grp_renewed = _last_replacement_on(journal)
        payload, warnings = [], []

        for row in self.equipment_data:
            equip = self._row_to_dict(row)
            equip['details'] = self._load_details(equip, warnings)
            record = self._match_journal(equip, journal)
            if record:
                equip['failures'] = record['fail']
                equip['damages'] = record['damage']
                if record['poor']:
                    equip['repair'] = {'quality': 'poor'}
                elif record['total']:
                    equip['repair'] = {'quality': 'new'}
                # Дата последней замены по этому элементу: от неё считается
                # возраст заменяемых деталей без собственной даты установки.
                equip['replaced_on'] = (_last_replacement_on({'x': record})
                                        or grp_renewed)
            else:
                equip['replaced_on'] = grp_renewed
            payload.append(equip)

        critical = [e for e in payload if classify_critical(e['name'])]
        if not critical:
            warnings.append(
                'Ни один элемент не распознан как критический (регулятор, ПЗК, ПСК, '
                'фильтр, запорная арматура) — проверьте наименования в справочнике.')
        if not any(e['details'] for e in payload):
            warnings.append(
                'Нет данных о деталях и нормативных сроках службы. Заведите запчасти '
                'с нормами (вкладка «Запчасти») или укажите срок службы вручную — '
                'иначе используется упрощённый календарный вариант.')
        if not coefficients:
            warnings.append(
                'Журнал технической диагностики пуст: в Алгоритме 1 общий коэффициент '
                'Kобщ = 1, оценка получается завышенной.')
        if not journal:
            warnings.append(
                'Журнал замен пуст: Nотказ = 0 и Nповрежд = 0, поэтому kповр = 1 для '
                'всех элементов.')
        else:
            covered = sum(1 for e in payload
                          if self._match_journal(e, journal))
            if covered < len(payload):
                warnings.append(
                    f'Записи журнала замен найдены только для {covered} из '
                    f'{len(payload)} элементов (сопоставление по типу оборудования).')
        dated = sum(1 for e in payload for d in (e.get('details') or [])
                    if d.get('is_replaceable') and not d.get('install_date'))
        if dated and grp_renewed:
            warnings.append(
                f'У {dated} заменяемых деталей не указана дата установки — принята '
                f'дата последней замены по ГРП ({grp_renewed}). Укажите дату в '
                f'вкладке «Запчасти», если деталь менялась отдельно.')
        return payload, warnings, journal

    def _load_details(self, equip, warnings):
        """Активные детали элемента для варианта Б2 базового ресурса."""
        eq_id = equip.get('equipment_id')
        if eq_id is None:
            return []
        try:
            rows = self.db.get_equipment_parts_full(eq_id) or []
        except Exception as exc:  # noqa: BLE001
            warnings.append(f'Не удалось загрузить детали «{equip["name"]}»: {exc}')
            return []

        details = []
        for row in rows:
            row = list(row) + [None] * 8
            norm_years, install_date, removal_date, replaceable = row[3], row[4], row[5], row[7]
            if removal_date or not norm_years or float(norm_years) <= 0:
                continue
            details.append({
                'name': row[2] or 'Деталь',
                'norm_years': float(norm_years),
                # Своя дата установки детали: если её нет, расчёт берёт дату
                # последней замены из журнала, а подставлять сюда дату
                # оборудования нельзя — деталь с 5-летней нормой выглядела бы
                # просроченной на все годы эксплуатации ГРП.
                'install_date': install_date,
                'equip_install_date': equip.get('install_date'),
                'is_replaceable': bool(replaceable),
            })
        replaceable = [d for d in details if d['is_replaceable']]
        return replaceable or details

    def _load_journal(self):
        """Журнал замен, сгруппированный по типу оборудования."""
        index = {}
        try:
            rows = self.db.get_replacements_by_grp(self.grp_id) or []
        except Exception:  # noqa: BLE001 — журнал не критичен для расчёта
            return {}
        for row in rows:
            row = list(row) + [None] * 9
            replace_date, part_number, equipment_type = row[1], row[2], row[3]
            model, work_type, reason = row[4], row[6], row[7]
            haystack = ' '.join(str(v or '') for v in
                                (work_type, reason, model, part_number)).lower()
            key = str(equipment_type or '').strip().lower()
            record = index.setdefault(key, {'fail': 0, 'damage': 0, 'poor': 0,
                                            'total': 0, 'entries': []})
            record['total'] += 1
            record['entries'].append({'date': replace_date, 'part': part_number,
                                      'work': work_type, 'reason': reason})
            if any(marker in haystack for marker in FAILURE_MARKERS):
                record['fail'] += 1
            if any(marker in haystack for marker in DAMAGE_MARKERS):
                record['damage'] += 1
            if any(marker in haystack for marker in POOR_REPAIR_MARKERS):
                record['poor'] += 1
        return index

    @staticmethod
    def _match_journal(equip, journal):
        """Находит записи журнала для элемента по типу оборудования."""
        name = str(equip.get('name') or '').strip().lower()
        for key, record in journal.items():
            if not key:
                continue
            if key == name or key in name or name in key:
                return record
        return None

    def _coefficients(self):
        """Актуальная запись журнала диагностики: A, B, C → Kобщ."""
        try:
            rows = self.db.get_technical_coefficients(self.grp_id) or []
        except Exception:  # noqa: BLE001
            return {}
        if not rows:
            return {}
        row = list(rows[0]) + [None] * 10
        return {'a': row[2], 'b': row[3], 'c': row[4],
                'source': f'журнал диагностики от {row[1]}',
                'k_db': row[5], 'date': row[1]}

    def _audit_results(self):
        """Добавляет замечания, которые видны только после самого расчёта."""
        result = self._result(PRIMARY_ALGORITHM)
        if result is None or result.error:
            return

        overdue, exhausted, no_data, skipped = [], [], [], []
        for element in result.elements:
            if element is None:
                continue
            if not element.used:
                skipped.append(element.name)
                continue
            if (element.z_base or 0) > 0 and element.z_element <= 0:
                exhausted.append(element.name)
            for detail in element.details:
                if (detail.get('z_base') is not None
                        and detail['z_base'] <= 0 < detail['age']):
                    overdue.append(f'{detail["name"]} ({element.name})')

        if overdue:
            self.warnings.append(
                f'Нормативный срок отработан деталями ({len(overdue)}): '
                + ', '.join(overdue[:4])
                + ('…' if len(overdue) > 4 else '')
                + ' — их ресурс принят равным нулю.')
        if exhausted:
            self.warnings.append(
                f'Ресурс исчерпан поправками у элементов: {", ".join(exhausted)}.')
        if skipped:
            self.warnings.append(
                f'Не вошли в расчёт как некритические: {len(skipped)} элементов '
                f'(учитываются только в Алгоритмах 0 и 1).')

    def _render_journal_card(self, coefficients):
        if not coefficients:
            self._journal_text.config(text='Записей нет — Kобщ = 1,000 (Алгоритм 2 '
                                           'не снижает оценку)')
            return
        a, b, c = coefficients.get('a'), coefficients.get('b'), coefficients.get('c')
        computed = 1 - sum(float(v) for v in (a, b, c) if v is not None) \
            if any(v is not None for v in (a, b, c)) else None
        text = (f"дата: {coefficients.get('date')}\n"
                f"A = {num(a, 4)}    B = {num(b, 4)}    C = {num(c, 4)}"
                f"    →    Kобщ = 1 − (A + B + C) = {num(computed, 4)}")
        if coefficients.get('k_db') is not None and computed is not None:
            if abs(float(coefficients['k_db']) - computed) > 0.0001:
                text += f"\nв базе хранится K = {num(coefficients['k_db'], 4)} — " \
                        f'расхождение с формулой, в расчёте используется формула'
        self._journal_text.config(text=text)

    # ---------------------------------------------------------- Рендеринг

    def _result(self, number):
        return self.results.get(number)

    def _rating(self, value):
        if value <= 0:
            return 'РЕСУРС ИСЧЕРПАН'
        if value < 1:
            return 'КРИТИЧЕСКИЙ · менее 1 года'
        if value < 3:
            return 'НИЗКИЙ · 1-3 года'
        if value < 5:
            return 'СРЕДНИЙ · 3-5 лет'
        return 'ВЫСОКИЙ · более 5 лет'

    def _color(self, value):
        if value <= 0:
            return BAD
        if value < 1:
            return BAD
        if value < 3:
            return WARN
        if value < 5:
            return '#b8860b'
        return GOOD

    def _tag(self, value):
        if value <= 0:
            return 'bad'
        if value < 3:
            return 'warn'
        return 'good'

    def _update_header(self):
        result = self._result(PRIMARY_ALGORITHM)
        used = len(result.used_elements) if result else 0
        self.header_sub.config(
            text=f'{self.grp_name}  ·  элементов в расчёте: {used}'
                 f'  ·  методика: алгоритм {PRIMARY_ALGORITHM}')

    def render_coefficients(self):
        """Таблица коэффициентов по элементам выбранного алгоритма."""
        tree = self.tree_coefficients
        tree.delete(*tree.get_children())
        result = self._result(self._algo_var.get())
        if result is None:
            return
        if result.error:
            tree.insert('', tk.END, values=(result.error,) + ('',) * 11)
            return

        weak = result.weak_element
        for element in result.elements:
            if not element.used:
                tree.insert('', tk.END, tags=('skip',), values=(
                    element.name, element.skip_reason, '—', '—', '—', '—',
                    '—', '—', '—', '—', '—', 'не входит в расчёт'))
                continue
            tag = 'weak' if element.name == weak else ('zero' if element.z_element <= 0 else '')
            tree.insert('', tk.END, tags=(tag,) if tag else (), values=(
                element.name,
                critical_title(element.critical_key) if element.critical_key else '—',
                years_to_text(element.norm),
                years_to_text(element.age),
                signed_years(element.z_base),
                element.z_base_variant or '—',
                num(element.k_state, 3),
                num(element.k_cond, 3),
                num(element.k_repair, 3),
                num(element.k_fail, 3),
                signed_years(element.z_element),
                element.z_element_formula,
            ))

    def render_trace(self):
        """Пошаговая трассировка выбранного алгоритма."""
        box = self.text_trace
        box.config(state=tk.NORMAL)
        box.delete('1.0', tk.END)
        result = self._result(self._algo_var.get())
        if result is None:
            box.config(state=tk.DISABLED)
            return

        for step in result.steps:
            level = step.level if step.level in TRACE_COLORS else 'value'
            box.insert(tk.END, step.text + '\n', level)
            if level == 'title':
                box.insert(tk.END, '\n')

        if result.error:
            box.insert(tk.END, '\nРасчёт не выполнен: ' + result.error + '\n', 'warn')
        box.config(state=tk.DISABLED)

        self.algo_hint.config(
            text=f'в расчёте {len(result.used_elements)} элементов'
                 + (f', слабое звено — {result.weak_element}' if result.weak_element else ''))

    def _render_inputs(self):
        """Что именно поступило в расчёт и чего не хватило."""
        tree = self.tree_inputs
        tree.delete(*tree.get_children())
        result = self._result(PRIMARY_ALGORITHM)
        if result is None:
            return

        by_id = {element.equipment_id: element for element in result.elements}
        journal = self.journal

        for row in self.equipment_data:
            equip = self._row_to_dict(row)
            element = by_id.get(equip['equipment_id'])
            name = equip['name']
            record = None
            for key, value in journal.items():
                if key and (key == name.lower() or key in name.lower()
                            or name.lower() in key):
                    record = value
                    break

            repair = '—'
            if record:
                if record['poor']:
                    repair = f'некачественный ({record["poor"]})'
                elif record['total']:
                    repair = f'замена ({record["total"]})'

            in_calc = 'да'
            if element is None:
                in_calc = 'нет: нет нормы и деталей'
            elif not element.used:
                in_calc = f'нет: {element.skip_reason}'

            tag = 'weak' if element and element.name == result.weak_element else (
                'skip' if element is None or not element.used else '')

            tree.insert('', tk.END, tags=(tag,) if tag else (), values=(
                name,
                critical_title(element.critical_key) if element and element.critical_key else '—',
                years_to_text(element.norm) if element else '—',
                (element.norm_source if element and element.norm_source else '—'),
                (len(element.details) if element else 0),
                signed_years(element.z_base) if element and element.z_base is not None else '—',
                (record['fail'] if record else 0),
                (record['damage'] if record else 0),
                repair,
                in_calc,
            ))
