"""Окно «Алгоритмы» — расчёт остаточного ресурса ГРП по методике.

Окно не показывает «магическое» число: рядом с результатом всегда видно,
из каких данных он получен, какая формула применена и какие данные отсутствовали
(с явной пометкой, что соответствующий коэффициент принят равным 1).
"""

import tkinter as tk
from tkinter import messagebox, ttk

from core.timefmt import years_to_text
from logic.algorithms import (
    ALGORITHM_TITLES,
    DAMAGE_MARKERS,
    FAILURE_MARKERS,
    POOR_REPAIR_MARKERS,
    AlgorithmParams,
    calculate_all_algorithms,
    classify_critical,
    critical_title,
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
CONSERVATIVE_NOTE = (
    'Консервативная оценка — минимум по всем алгоритмам. Её используют для '
    'планирования замен с запасом; в отчётность идут результаты выбранной методики.'
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


def _tree(parent, columns, widths, height=10):
    """Дерево таблицы с вертикальным скроллбаром."""
    holder = tk.Frame(parent, bg=BG)
    holder.pack(fill=tk.BOTH, expand=True)

    tree = ttk.Treeview(holder, columns=columns, show='headings',
                        height=height, selectmode='browse')
    for column in columns:
        tree.heading(column, text=column)
        tree.column(column, width=widths.get(column, 110), anchor=tk.W)
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
        self.window.geometry('1560x900')
        self.window.configure(bg=BG)
        self.window.transient(parent)
        self.window.grab_set()

        self._build_ui()
        self.calculate_and_display()

    # ------------------------------------------------------------------ UI

    def _build_ui(self):
        self._build_header()
        self.notebook = ttk.Notebook(self.window)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=14, pady=(0, 14))

        self.tab_summary = tk.Frame(self.notebook, bg=BG)
        self.notebook.add(self.tab_summary, text='  Сводка  ')

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
        self._build_summary_tab()
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
                               values=[f'Алгоритм {i} · {ALGORITHM_TITLES[i]}'
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

    # ------------------------------------------------------------- Сводка

    def _build_summary_tab(self):
        wrap = tk.Frame(self.tab_summary, bg=BG)
        wrap.pack(fill=tk.BOTH, expand=True, padx=14, pady=10)

        cards = tk.Frame(wrap, bg=BG)
        cards.pack(fill=tk.X)

        self.card_main = _card(cards)
        self.card_main.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 7))
        self.card_side = _card(cards)
        self.card_side.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(7, 0))

        self.tree_comparison = _tree(
            wrap,
            columns=('Методика', 'Ресурс', 'T диагн.', 'Слабое звено', 'Рекомендация'),
            widths={'Методика': 300, 'Ресурс': 130, 'T диагн.': 130,
                    'Слабое звено': 250, 'Рекомендация': 620},
            height=7,
        )
        self.tree_comparison.tag_configure('good', background='#e6f6ee')
        self.tree_comparison.tag_configure('warn', background='#fdf3e0')
        self.tree_comparison.tag_configure('bad', background='#fbeaea')
        self.tree_comparison.tag_configure('error', foreground='#9aa5b1')

        tk.Label(wrap, text=CONSERVATIVE_NOTE, bg=BG, fg=MUTED,
                 font=('Segoe UI', 9), wraplength=1500, justify=tk.LEFT
                 ).pack(anchor=tk.W, pady=(8, 0))

    def _render_main_card(self):
        for widget in self.card_main.winfo_children():
            widget.destroy()

        result = self.results.get(PRIMARY_ALGORITHM)
        inner = tk.Frame(self.card_main, bg=CARD)
        inner.pack(fill=tk.BOTH, expand=True, padx=18, pady=14)

        head = tk.Frame(inner, bg=CARD)
        head.pack(fill=tk.X)
        tk.Label(head, text=f'Алгоритм {PRIMARY_ALGORITHM} · {ALGORITHM_TITLES[PRIMARY_ALGORITHM]}',
                 bg=CARD, fg=MUTED, font=('Segoe UI', 10)).pack(side=tk.LEFT)
        if result and not result.error:
            tk.Label(head, text=self._rating(result.result), bg=CARD,
                     fg=self._color(result.result), font=('Segoe UI', 10, 'bold')
                     ).pack(side=tk.RIGHT)

        if result is None or result.error:
            tk.Label(inner, text='Расчёт не выполнен', bg=CARD, fg=BAD,
                     font=('Segoe UI', 22, 'bold')).pack(anchor=tk.W, pady=(6, 2))
            tk.Label(inner, text=(result.error if result else 'нет данных'),
                     bg=CARD, fg=MUTED, font=('Segoe UI', 10), wraplength=520,
                     justify=tk.LEFT).pack(anchor=tk.W)
            return

        value = tk.Label(inner, text=years_to_text(result.result), bg=CARD,
                         fg=self._color(result.result), font=('Segoe UI', 30, 'bold'))
        value.pack(anchor=tk.W, pady=(4, 0))
        tk.Label(inner, text=f'{num(result.result, 2)} года'
                             f'   ·   T_диагн = {years_to_text(result.next_diagnosis)}'
                             f'   ·   запас ×{num(self.params.reserve, 2)}',
                 bg=CARD, fg=MUTED, font=('Segoe UI', 10)).pack(anchor=tk.W)

        if result.weak_element:
            weak = tk.Frame(inner, bg=CARD)
            weak.pack(fill=tk.X, pady=(12, 0))
            tk.Label(weak, text='Слабое звено', bg=CARD, fg=MUTED,
                     font=('Segoe UI', 9)).pack(anchor=tk.W)
            tk.Label(weak, text=result.weak_element, bg=CARD, fg=TEXT,
                     font=('Segoe UI', 12, 'bold'), wraplength=520,
                     justify=tk.LEFT).pack(anchor=tk.W)

        tk.Label(inner, text=result.recommendation, bg=CARD, fg=MUTED,
                 font=('Segoe UI', 10), wraplength=520, justify=tk.LEFT
                 ).pack(anchor=tk.W, pady=(12, 0))

    def _render_side_card(self):
        for widget in self.card_side.winfo_children():
            widget.destroy()

        inner = tk.Frame(self.card_side, bg=CARD)
        inner.pack(fill=tk.BOTH, expand=True, padx=18, pady=14)

        tk.Label(inner, text='Контрольная оценка', bg=CARD, fg=MUTED,
                 font=('Segoe UI', 10)).pack(anchor=tk.W)
        usable = [r for r in self.results.values() if r and not r.error]
        if not usable:
            tk.Label(inner, text='нет результатов', bg=CARD, fg=BAD,
                     font=('Segoe UI', 12, 'bold')).pack(anchor=tk.W, pady=6)
            return

        worst = min(usable, key=lambda r: r.result)
        tk.Label(inner, text=years_to_text(worst.result), bg=CARD, fg=self._color(worst.result),
                 font=('Segoe UI', 20, 'bold')).pack(anchor=tk.W, pady=(2, 0))
        tk.Label(inner, text=f'минимум по всем методикам · {worst.algorithm_name}',
                 bg=CARD, fg=MUTED, font=('Segoe UI', 9)).pack(anchor=tk.W)

        spread = max(r.result for r in usable) - worst.result
        tk.Label(inner, text=f'Разброс между методиками: {num(spread, 2)} года',
                 bg=CARD, fg=MUTED, font=('Segoe UI', 9)).pack(anchor=tk.W, pady=(8, 0))

        used = len(self._result(PRIMARY_ALGORITHM).used_elements) if self.results else 0
        critical = sum(1 for e in (self._result(PRIMARY_ALGORITHM).elements
                                   if self.results else []) if e.critical_key)
        tk.Label(inner, text=f'Элементов в расчёте: {used} (из них критических: {critical})',
                 bg=CARD, fg=MUTED, font=('Segoe UI', 9)).pack(anchor=tk.W)

        if self.warnings:
            box = tk.Frame(inner, bg=CARD)
            box.pack(fill=tk.X, pady=(10, 0))
            tk.Label(box, text=f'Замечания по данным: {len(self.warnings)}',
                     bg=CARD, fg=WARN, font=('Segoe UI', 9, 'bold')).pack(anchor=tk.W)
            for text in self.warnings[:3]:
                tk.Label(box, text=f'• {text}', bg=CARD, fg=MUTED, font=('Segoe UI', 9),
                         wraplength=520, justify=tk.LEFT).pack(anchor=tk.W)
            if len(self.warnings) > 3:
                tk.Label(box, text=f'… ещё {len(self.warnings) - 3} — см. «Исходные данные»',
                         bg=CARD, fg=MUTED, font=('Segoe UI', 9)).pack(anchor=tk.W)

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
            widths={'Элемент': 240, 'Категория': 190, 'S_нач': 70, 'Возраст': 80,
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
            widths={'Элемент': 230, 'Категория': 170, 'S_нач': 65, 'Источник': 175,
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
            ('alpha_wa', 'α — Weighted Average', '0,60'),
            ('t_crit', 'T крит. переработки', '5'),
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
        digits = {'max_diag_interval': 1, 't_crit': 1}
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
        put('Алгоритмы 2, 3, 4:  ZГРП = min (Zрег; Zпзк; Zпск; Zфильтр; Zарматура)\n', 'f')
        put('Алгоритм 0:  ZГРП = Σ Zэл / m      (среднее арифметическое)\n', 'f')
        put('Алгоритм 1:  ZГРП = (Σ Zэл / m) · Kобщ,  Kобщ = 1 − (A + B + C)\n', 'f')
        put('Алгоритм 4:  Zбаза = α·Zкаленд + (1−α)·Zнаработка; при Zкаленд < −Tкрит '
            'основа — календарный срок\n', 'f')
        put('Tдиагн = min (ZГРП · Kзапаса ; Tмакс)\n\n', 'f')

        put('ИСТОЧНИКИ (папка docs/)\n', 'h')
        put('«Алгоритм 3-без календаря-5+.pdf» — скорректированная редакция Алгоритма 3: '
            'приоритет наработки, двойной учёт Kсост, некратные замены, Tдиагн.\n', 's')
        put('«Алг3-схема данных.pdf» — привязка шагов к цифровому паспорту ГРП, '
            'сквозной пример ГРП №26.\n', 's')
        put('«Алгоритм4.pdf» — Weighted Average и порог переработки Tкрит.\n', 's')
        put('«Алгоритмы-(все до корректировки).pdf» — Алгоритмы 0-2.\n', 's')
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
        except Exception as exc:  # noqa: BLE001 — окно не должно падать
            messagebox.showerror('Ошибка расчёта', f'Не удалось выполнить расчёт:\n{exc}')
            return

        self._audit_results()
        self._render_main_card()
        self._render_side_card()
        self._render_comparison()
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
                'install_date': install_date or equip.get('install_date'),
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
            self._journal_text.config(text='Записей нет — Kобщ = 1,000 (Алгоритм 1 '
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

    def _render_comparison(self):
        self.tree_comparison.delete(*self.tree_comparison.get_children())
        for number, result in sorted(self.results.items()):
            if result.error:
                self.tree_comparison.insert(
                    '', tk.END, tags=('error',),
                    values=(f'Алгоритм {number} · {result.algorithm_name}', '—', '—',
                            '—', result.error))
                continue
            tag = self._tag(result.result)
            if result is self._result(PRIMARY_ALGORITHM):
                values = (f'▶ Алгоритм {number} · {result.algorithm_name}',)
            else:
                values = (f'Алгоритм {number} · {result.algorithm_name}',)
            self.tree_comparison.insert(
                '', tk.END, tags=(tag,),
                values=values + (years_to_text(result.result),
                                 years_to_text(result.next_diagnosis),
                                 result.weak_element or '—',
                                 result.recommendation))

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
                num(element.norm, 1),
                num(element.age, 1),
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
                num(element.norm, 1) if element else '—',
                (element.norm_source if element and element.norm_source else '—'),
                (len(element.details) if element else 0),
                signed_years(element.z_base) if element and element.z_base is not None else '—',
                (record['fail'] if record else 0),
                (record['damage'] if record else 0),
                repair,
                in_calc,
            ))
