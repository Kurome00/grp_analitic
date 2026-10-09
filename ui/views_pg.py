import os
import re
import tempfile
import tkinter as tk
from tkinter import ttk, messagebox, Toplevel, filedialog
from datetime import datetime
from typing import List, Optional

from core.config import DB_CONFIG
from core import diagnostic_log
from core import equipment_card
from core import failure_log
from core import grp_passport
from core import repair_journal
from core.lifetimes import parse_date
from core.models import Equipment
from core.timefmt import DurationError, parse_years_strict, years_to_text
from db.database_pg import DatabasePG
from integration import excel_sync, word_report_pg
from integration.pdf_parts_import import scan_pdf, import_to_db, create_catalog_equipment
from logic.algorithms import AlgorithmParams, algo_label
from logic.documentary_analyzer import DocumentaryAnalyzer
from logic.technical_analyzer_pg import TechnicalAnalyzer

from .algorithms_view import AlgorithmsWindow
from .widgets_calc import Pane
from .window_utils import fit_window, resize_root

# Варианты вида работ при замене запасной части (как в образце Лида.xlsx)
WORK_TYPES = [
    "При ТР",
    "ТР. Замена по графику",
    "Ремонт. Замена после ТО",
    "Ремонт. Замена после аварийной заявки",
    "Ремонт. Замена перед диагностики",
    "Замена после диагностики",
    "Замена по графику",
    "Замена после аварийной заявки",
]
EQUIPMENT_TYPES = ["Регулятор", "ПСК", "ПЗК", "Фильтр"]

# Палитра кнопок: цвет в норме → цвет при наведении.
# Интерфейс выполнен в единой серой гамме (голубовато-серый).
BTN_COLORS = {
    'primary': ('#546E7A', '#455A64'),
    'success': ('#546E7A', '#455A64'),
    'warning': ('#607D8B', '#455A64'),
    'danger':  ('#37474F', '#263238'),
    'info':    ('#607D8B', '#455A64'),
    'purple':  ('#546E7A', '#455A64'),
    'indigo':  ('#546E7A', '#455A64'),
    'brown':   ('#607D8B', '#455A64'),
    'neutral': ('#607D8B', '#455A64'),
}

# Меню слева: (заголовок группы, [(пункт, команда, доступность)]).
# доступность: 'always' — всегда активен, 'grp' — только при выбранном ГРП.
MENU_STRUCTURE = [
    ("ГРП", [
        ("➕ Создать ГРП", "add_grp", "always"),
        ("🗂 Выбрать ГРП", "choose_grp", "always"),
        ("✏ Редактировать ГРП", "edit_grp", "grp"),
        ("🗑 Удалить ГРП", "delete_grp", "grp"),
    ]),
    ("Действия с выбранным ГРП", [
        ("🔩 Оборудование и запчасти", "view_equipment", "grp"),
        ("🛠 Замены (ремонт)", "view_repairs", "grp"),
        ("⚠ Информация по отказам", "view_failures", "grp"),
        ("📏 Отчёт по ГРП (Word)", "view_report", "grp"),
        ("🧮 Расчёт алгоритмов", "open_algorithms", "grp"),
        ("🔧 Технические коэффициенты", "view_tech", "grp"),
        ("📋 Техническое диагностирование", "view_diagnostics", "grp"),
    ]),
    # Импорт PDF-альбома и обновление файла Excel — не пункты меню: это
    # действия внутри своих экранов (кнопка «📂 Загрузить PDF-альбом» в
    # каталоге, «📥 Обновить Excel» в журнале замен). Файл Excel, кроме того,
    # перезаписывается сам при каждой правке замен.
    ("Справочники", [
        ("📦 Каталог оборудования", "view_catalog", "always"),
    ]),
]


# ------------------------------------------------------------------ форма ГРП

def _grp_passport_form(frame, start_row: int, values: dict = None,
                       columns: int = 2):
    """Поля паспорта ГРП в сетке формы → {ключ: виджет}.

    Двенадцать полей в один столбец не помещаются на экран ноутбука, а форма
    должна читаться целиком, без прокрутки, — поэтому в две колонки.
    Подписи, порядок и виды полей берутся из core.grp_passport: оттуда же их
    берёт таблица «Сведения о ГРП» в отчёте, поэтому форма и отчёт не
    разъедутся.
    """
    values = values or {}
    fields = list(grp_passport.FORM_FIELDS)
    per_column = -(-len(fields) // columns)      # округление вверх
    widgets = {}
    for index, (key, label, kind) in enumerate(fields):
        column, row = divmod(index, per_column)
        left = column * 2
        tk.Label(frame, text=label + ':', font=("Arial", 10),
                 wraplength=200, justify=tk.LEFT).grid(
            row=start_row + row, column=left, sticky=tk.W, pady=4)
        current = values.get(key, '')
        if kind == 'choice':
            widget = ttk.Combobox(frame, width=24, state='readonly',
                                  values=list(grp_passport.COATING_CHOICES))
            widget.set(current)
        else:
            widget = tk.Entry(frame, width=26)
            widget.insert(0, current)
        widget.grid(row=start_row + row, column=left + 1, sticky=tk.W,
                    pady=4, padx=(0, 18))
        widgets[key] = widget
    return widgets


def _grp_passport_values(widgets) -> dict:
    """Сведения паспорта из формы: {ключ: строка} — как их принимает база."""
    return {key: widget.get().strip() for key, widget in widgets.items()}


def _grp_passport_rows(columns: int = 2) -> int:
    """Сколько строк сетки занимает форма паспорта — считают блоки под ней."""
    return -(-len(grp_passport.FORM_FIELDS) // columns)


class AutocompleteCombobox(ttk.Combobox):
    """Комбобокс с фильтрацией по мере ввода: буквы отсекают несовпадения."""

    def __init__(self, parent, values=(), *args, **kwargs):
        super().__init__(parent, *args, **kwargs)
        self._all_values = sorted(set(values))
        self['values'] = self._all_values
        self.bind('<KeyRelease>', self._on_keyrelease)

    def _on_keyrelease(self, event):
        if event.keysym in ('Up', 'Down', 'Left', 'Right', 'Escape', 'Return', 'Tab'):
            return
        text = self.get().strip()
        if not text:
            self['values'] = self._all_values
        else:
            low = text.lower()
            self['values'] = [v for v in self._all_values if low in v.lower()]


def _equipment_row_dialog(app, item=None):
    """Форма одной единицы оборудования ГРП.

    Поля и их порядок задаёт core.equipment_card.FORM_FIELDS — тот же
    перечень, по которому строится таблица оборудования, поэтому ввести можно
    ровно то, что потом видно в списке.

    Возвращает {'name', 'install_date', 'removal_date'} и паспортные сведения
    (тип, изготовитель, ДУ, количество, номер по схеме, назначенный срок и
    наработки, примечание) — или None при отказе. Наименование подсказывается
    из каталога: по нему подтянутся запчасти.

    Даты снятия в форме нет: её ставит приложение при замене единицы целиком,
    и в форме она не показывается — но значение переносится без изменений,
    иначе правка паспорта отменила бы снятие с учёта.
    """
    catalog_id = app._catalog_grp_id()
    names = sorted({e[1].strip() for e in app.db.get_equipment_by_grp(catalog_id)}) \
        if catalog_id else []
    if not names:
        names = sorted(set(app.db.get_all_equipment_names()))

    item = item or {}
    window = Toplevel(app.root)
    window.title("Оборудование в составе ГРП")
    window.transient(app.root)
    window.grab_set()

    tk.Label(window, text="🔩 Единица оборудования",
             font=("Arial", 12, "bold"), fg="#546E7A").pack(pady=(12, 6))

    frame = tk.Frame(window)
    frame.pack(padx=16, pady=6)

    widgets = {}
    row = 0
    for key, label, hint in equipment_card.FORM_FIELDS:
        tk.Label(frame, text=label + ':', font=("Arial", 10)).grid(
            row=row, column=0, sticky=tk.W, pady=3, padx=(0, 10))
        if key == 'name':
            widget = AutocompleteCombobox(frame, values=names, width=46)
        else:
            widget = tk.Entry(frame, width=48)
        widget.grid(row=row, column=1, sticky=tk.W, pady=3)
        widgets[key] = widget
        row += 1
        if hint:
            tk.Label(frame, text=hint, font=("Arial", 8), fg="#6c757d").grid(
                row=row, column=1, sticky=tk.W)
            row += 1

    widgets['name'].set(item.get('name') or '')
    widgets['install_date'].insert(
        0, item.get('install_date') or datetime.now().strftime('%Y-%m-%d'))
    for key, current in equipment_card.details(item).items():
        if current:
            widgets[key].insert(0, current)

    result = {}

    def save():
        name = widgets['name'].get().strip()
        if not name:
            messagebox.showerror("Ошибка", "Введите наименование оборудования!",
                                 parent=window)
            return
        install = widgets['install_date'].get().strip()
        if not install:
            messagebox.showerror("Ошибка", "Дата монтажа (установки) обязательна!",
                                 parent=window)
            return
        if parse_date(install) is None:
            messagebox.showerror("Ошибка", "Дата монтажа непонятна.\n"
                                           "Пример: 2020-01-15", parent=window)
            return
        try:
            assigned_life = equipment_card.parse_life(
                widgets['assigned_life'].get())
        except DurationError as e:
            messagebox.showerror("Ошибка", str(e), parent=window)
            return
        # Дата снятия не спрашивается, а переносится как есть: единицу снимает
        # с учёта замена оборудования целиком, а не правка паспорта.
        result.update({'name': name, 'install_date': install,
                       'removal_date': item.get('removal_date') or None})
        result.update({
            key: widgets[key].get().strip()
            for key, _label, _hint in equipment_card.FORM_FIELDS
            if key not in ('name', 'install_date')})
        result['assigned_life'] = assigned_life
        window.destroy()

    buttons = tk.Frame(window)
    buttons.pack(pady=14)
    app._btn(buttons, "💾 Сохранить", save, color='success',
             font_size=10, padx=20).pack(side=tk.LEFT, padx=10)
    app._btn(buttons, "❌ Отмена", window.destroy, color='danger',
             font_size=10, padx=20).pack(side=tk.LEFT, padx=10)
    fit_window(window, min_width=700, min_height=620)

    app.root.wait_window(window)
    return result or None


class EquipmentListEditor:
    """Список оборудования ГРП внутри форм «Создать ГРП» и «Редактировать ГРП».

    Строка списка — одна единица оборудования: {'id', 'name', 'install_date',
    'removal_date'} и паспортные сведения (ключи core.equipment_card).
    id равно None у ещё не сохранённой единицы; номер строки 1..n нигде не
    хранится — это место единицы в списке.
    """

    COLUMNS = ("№",) + tuple(label for _key, label, _width in
                             equipment_card.TABLE_COLUMNS)
    WIDTHS = {"№": 40}
    WIDTHS.update({label: width for _key, label, width in
                   equipment_card.TABLE_COLUMNS})

    def __init__(self, app, parent, grid_row: int):
        self.app = app
        self.items = []

        self.card = tk.LabelFrame(parent, text="Оборудование в составе ГРП",
                                  font=("Arial", 10, "bold"), padx=10, pady=8)
        self.card.grid(row=grid_row, column=0, columnspan=4, sticky="we",
                       pady=(12, 0))

        buttons = tk.Frame(self.card)
        buttons.pack(fill=tk.X, pady=(0, 4))
        app._btn(buttons, "➕ Добавить оборудование", self.add, color='success',
                 font_size=9, padx=10).pack(side=tk.LEFT, padx=4)
        app._btn(buttons, "✏ Изменить", self.edit, color='warning',
                 font_size=9, padx=10).pack(side=tk.LEFT, padx=4)
        app._btn(buttons, "🗑 Убрать", self.remove, color='danger',
                 font_size=9, padx=10).pack(side=tk.LEFT, padx=4)

        self.tree = app._scroll_table(self.card, self.COLUMNS, self.WIDTHS,
                                      height=5)
        self.tree.bind('<Double-1>', lambda e: self.edit())

        tk.Label(self.card,
                 text="💡 Отметьте оборудование, которое стоит внутри ГРП. "
                      "Запчасти подтянутся из каталога по названию "
                      "оборудования.",
                 font=("Arial", 8), fg="#6c757d", anchor=tk.W,
                 justify=tk.LEFT).pack(anchor=tk.W, pady=(4, 0))

    def load(self, items):
        """Заполнить список единицами оборудования (см. описание класса)."""
        self.items = [dict(item) for item in items]
        self._refresh()

    def values(self):
        return [dict(item) for item in self.items]

    def _refresh(self):
        for row in self.tree.get_children():
            self.tree.delete(row)
        for number, item in enumerate(self.items, start=1):
            self.tree.insert('', tk.END,
                             values=[number] + equipment_card.table_cells(item))

    def _selected_index(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("Внимание", "Выберите оборудование в списке!")
            return None
        return self.tree.index(selected[0])

    def add(self):
        item = _equipment_row_dialog(self.app)
        if item is None:
            return
        item['id'] = None
        self.items.append(item)
        self._refresh()
        self.tree.selection_set(self.tree.get_children()[-1])

    def edit(self):
        index = self._selected_index()
        if index is None:
            return
        item = _equipment_row_dialog(self.app, self.items[index])
        if item is None:
            return
        item['id'] = self.items[index]['id']
        self.items[index] = item
        self._refresh()

    def remove(self):
        index = self._selected_index()
        if index is None:
            return
        name = self.items[index]['name']
        if not messagebox.askyesno("Подтверждение",
                                   f"Убрать '{name}' из состава ГРП?"):
            return
        del self.items[index]
        self._refresh()


class GRPAppPG:
    """Главный класс приложения с PostgreSQL"""

    def __init__(self, root):
        self.root = root
        self.db = DatabasePG(DB_CONFIG)
        self.doc_analyzer = DocumentaryAnalyzer(self.db)
        self.tech_analyzer = TechnicalAnalyzer()
        self.current_grp_id: Optional[int] = None
        self.current_grp_name: str = ""
        # Экраны основной области. Часть собирается один раз при запуске
        # (setup_*_tab), часть — заново при каждом открытии: форма ГРП и расчёт
        # зависят от текущего ГРП и от свежих данных базы.
        self.tabs = {}
        self._embedded = {}
        self._current_view: Optional[str] = None
        # Параметры расчёта, заданные пользователем в окне алгоритмов.
        # Отчёт Word должен считаться с ними же, иначе числа в отчёте
        # разойдутся с тем, что пользователь видел на экране.
        self.calc_params: Optional[AlgorithmParams] = None
        self.setup_ui()
        self.update_catalog_combo()
        self.sync_excel(silent=True)

    def _to_equipment_list(self, equipment_rows: List[tuple]) -> List[Equipment]:
        """Преобразование строк из БД в список объектов Equipment."""
        return [
            Equipment(
                name=e[1],
                install_date=e[2],
                removal_date=e[3],
                id=e[0]
            )
            for e in equipment_rows
        ]

    def _parts_aware_norm(self, equip: Equipment) -> Optional[float]:
        """Норма оборудования по заменяемым запчастям (слабое звено)."""
        return self.doc_analyzer.get_norm_for_equipment(
            equip.name,
            getattr(equip, 'id', None),
            equip.install_date if hasattr(equip, 'install_date') else None
        )

    def _btn(self, parent, text, command, color='primary', font_size=9, padx=10, **extra):
        """Единая цветная кнопка интерфейса с эффектом наведения."""
        c1, c2 = BTN_COLORS.get(color, BTN_COLORS['primary'])
        btn = tk.Button(
            parent, text=text, command=command, bg=c1, fg="white",
            font=("Arial", font_size, "bold"), padx=padx,
            bd=0, relief="flat", cursor="hand2",
            activebackground=c2, activeforeground="white", **extra
        )
        btn.bind("<Enter>", lambda e, b=btn, bg=c2: b.config(bg=bg))
        btn.bind("<Leave>", lambda e, b=btn, bg=c1: b.config(bg=bg))
        return btn

    def _scroll_table(self, parent, columns, widths, height=10, headings=None):
        """Таблица с вертикальным и горизонтальным ползунками.

        Нижний ползунок нужен всегда: набор граф шире окна, а без него
        правые графы просто обрезались бы. Ползунки ставятся сеткой, чтобы
        занимать только края, а не отнимать место у самой таблицы.
        `headings` — подписи граф, если они отличаются от служебных имён.
        """
        box = tk.Frame(parent)
        box.pack(fill=tk.BOTH, expand=True)
        box.grid_rowconfigure(0, weight=1)
        box.grid_columnconfigure(0, weight=1)

        tree = ttk.Treeview(box, columns=columns, show="headings", height=height)
        for col in columns:
            tree.heading(col, text=(headings or {}).get(col, col))
            tree.column(col, width=widths.get(col, 100), minwidth=40)

        vsb = ttk.Scrollbar(box, orient=tk.VERTICAL, command=tree.yview)
        hsb = ttk.Scrollbar(box, orient=tk.HORIZONTAL, command=tree.xview)
        tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        return tree

    def setup_ui(self):
        self.root.title("🏭 Система анализа ГРП (PostgreSQL)")

        # Настройка стилей
        style = ttk.Style()
        style.configure('Header.TLabel', font=('Arial', 12, 'bold'))
        style.configure('Info.TLabel', font=('Arial', 9), foreground='#6c757d')
        style.configure('Success.TButton', font=('Arial', 10, 'bold'))

        # === Верхняя панель ===
        self.top_bar = tk.Frame(self.root, bg="#263238", height=52)
        self.top_bar.pack(side=tk.TOP, fill=tk.X)
        self.top_bar.pack_propagate(False)

        # Значок открытия меню
        self.menu_btn = tk.Button(
            self.top_bar, text="☰", font=("Arial", 16, "bold"),
            bg="#263238", fg="white", bd=0, activebackground="#455a64",
            activeforeground="white", cursor="hand2", command=self.toggle_sidebar
        )
        self.menu_btn.pack(side=tk.LEFT, padx=(14, 6), pady=6)

        # Надпись выбранного ГРП (слева сверху): белый текст, без рамки
        self.grp_badge_label = tk.Label(
            self.top_bar, text="ГРП не выбран",
            font=("Arial", 11, "bold"), bg="#263238", fg="#90a4ae"
        )
        self.grp_badge_label.pack(side=tk.LEFT, padx=(10, 0))

        # Значок справки
        self.help_btn = tk.Button(
            self.top_bar, text="❓", font=("Arial", 16, "bold"),
            bg="#263238", fg="white", bd=0, activebackground="#455a64",
            activeforeground="white", cursor="hand2", command=self.show_help
        )
        self.help_btn.pack(side=tk.RIGHT, padx=14, pady=6)

        # === Основная область: серое меню слева + контент ===
        self.body = tk.Frame(self.root, bg="#eceff1")
        self.body.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        self.sidebar = tk.Frame(self.body, bg="#263238", width=250)
        self.sidebar.pack_propagate(False)
        self.sidebar.pack(side=tk.LEFT, fill=tk.Y)

        self.content = tk.Frame(self.body, bg="#ffffff")
        self.content.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Статусбар
        self.statusbar = tk.Label(self.root, text="Готов к работе",
                                  relief=tk.SUNKEN, anchor=tk.W, font=("Arial", 9))
        self.statusbar.pack(side=tk.BOTTOM, fill=tk.X)

        # === Представления (экраны приложения) ===
        views = [
            ("grp", "🏗️  Рабочее ГРП", self.setup_grp_tab),
            ("catalog", "📦  Каталог оборудования", self.setup_catalog_tab),
            ("tech", "🔧  Технические коэффициенты", self.setup_tech_tab),
            ("repairs", "🛠️  Замены (ремонт)", self.setup_replacements_tab),
            ("failures", "⚠️  Информация по отказам", self.setup_failures_tab),
            ("diagnostics", "📋  Техническое диагностирование",
             self.setup_diagnostics_tab),
        ]

        for key, _title, builder in views:
            frame = ttk.Frame(self.content)
            setattr(self, f"{key}_tab", frame)
            self.tabs[key] = frame
            builder()

        self._build_menu()

        # Показываем стартовый экран (пустая таблица, ГРП не выбран)
        self.show_view("grp")

        # Окно по содержимому, но не больше экрана
        self.root.after(60, lambda: resize_root(self.root, min_width=1100, min_height=700))

    def _build_menu(self):
        """Сборка серого меню слева из MENU_STRUCTURE."""
        self.menu_buttons = {}
        for section, items in MENU_STRUCTURE:
            tk.Label(
                self.sidebar, text=section.upper(),
                font=("Arial", 8, "bold"), bg="#263238", fg="#90a4ae",
                anchor=tk.W, padx=8
            ).pack(fill=tk.X, padx=10, pady=(12, 3))

            for label, cmd, scope in items:
                btn = tk.Button(
                    self.sidebar, text=label, font=("Arial", 10),
                    bg="#37474f", fg="#eceff1", bd=0, anchor=tk.W,
                    padx=16, pady=7, cursor="hand2",
                    activebackground="#546e7a", activeforeground="white",
                    command=lambda c=cmd: self._dispatch(c)
                )
                btn.bind("<Enter>", lambda e, b=btn: b.config(bg="#546e7a"))
                btn.bind("<Leave>", lambda e, b=btn: b.config(bg="#37474f" if b["state"] != "disabled" else "#37474f"))
                btn.pack(fill=tk.X, padx=4, pady=1)
                self.menu_buttons[cmd] = (btn, scope)

        self._set_menu_grp_state(False)

    def _dispatch(self, cmd: str):
        handler = getattr(self, cmd, None)
        if handler:
            handler()

    def _set_menu_grp_state(self, enabled: bool):
        """Включает/отключает пункты меню, требующие выбранного ГРП."""
        for cmd, (btn, scope) in self.menu_buttons.items():
            if scope == 'grp':
                btn.config(state="normal" if enabled else "disabled")

    def toggle_sidebar(self):
        """Открыть/закрыть серое меню.

        Меню всегда возвращается СЛЕВА: pack() размещает виджет после уже
        упакованных, поэтому без before=self.content повторное открытие
        уводило панель вправо от контента.
        """
        if self.sidebar.winfo_manager():
            self.sidebar.pack_forget()
            return
        try:
            self.sidebar.pack(side=tk.LEFT, fill=tk.Y, before=self.content)
        except tk.TclError:
            self.sidebar.pack(side=tk.LEFT, fill=tk.Y)

    def show_view(self, key: str):
        """Переключение представления в основной области."""
        if key != self._current_view:
            # Уходя с экрана, отпускаем то, что было в него встроено: расчёт
            # держит свою тему ttk, и без возврата она осталась бы на всём окне.
            self._release_view(self._current_view)
        for _k, frame in self.tabs.items():
            frame.pack_forget()
        frame = self.tabs.get(key)
        if frame is not None:
            frame.pack(fill=tk.BOTH, expand=True)
        self._current_view = key
        self._grow_for_view()

    def _grow_for_view(self):
        """Подрастить окно, если экран в него не влезает.

        Расчёт раньше открывался отдельным окном по содержимому; в главном окне
        то же место даёт подросшее окно — обрезать таблицы хуже, чем занять
        почти весь экран. Окно только растёт: при возврате на низкий экран оно
        не сжимается и не дёргается.
        """
        try:
            self.root.update_idletasks()
            need = self.content.winfo_reqheight()
            have = self.content.winfo_height()
            if need <= have:
                return
            height = min(self.root.winfo_height() + (need - have),
                         int(self.root.winfo_screenheight() * 0.96))
            if height > self.root.winfo_height():
                self.root.geometry(f"{self.root.winfo_width()}x{height}")
        except tk.TclError:
            # Окно уже закрывается — подгонять нечего.
            pass

    def _release_view(self, key: Optional[str]):
        """Отпустить встроенный экран: вернуть тему ttk, снять обработчики."""
        view = self._embedded.pop(key, None)
        if view is None:
            return
        close = getattr(view, 'close', None)
        if close is not None:
            close()

    def _dynamic_view(self, key: str, builder, scroll: bool = False):
        """Экран, который собирается заново при каждом открытии.

        Формы ГРП, отчёт и расчёт зависят от текущего ГРП и от
        свежих данных базы, поэтому построенными с запуска они не держатся.
        builder может вернуть объект с методом close() — его вызовут, когда
        пользователь уйдёт с экрана.

        `scroll=True` для экранов выше окна: содержимое кладётся в листаемую
        панель. Экранам, которые растягиваются (таблицы, расчёт), прокрутка
        не нужна — она отняла бы у них растяжение.
        """
        self._release_view(key)
        frame = self.tabs.get(key)
        if frame is None:
            # tk.Frame, а не ttk: экран расчёта перекрашивает контейнер под себя.
            frame = tk.Frame(self.content, bg="#ffffff")
            self.tabs[key] = frame
        for child in frame.winfo_children():
            child.destroy()
        holder = frame
        if scroll:
            pane = Pane(frame, bg="#ffffff")
            pane.pack(fill=tk.BOTH, expand=True)
            holder = pane.body
        view = builder(holder)
        if view is not None:
            self._embedded[key] = view
        return frame

    # === Состояние выбранного ГРП ===

    def set_current_grp(self, grp_id: int):
        """Выбрать ГРП: обновляет бейдж, включает пункты меню, загружает таблицу."""
        grp = self.db.get_grp_by_id(grp_id)
        if not grp:
            return
        self.current_grp_id = grp[0]
        self.current_grp_name = grp[1]
        self.grp_badge_label.config(text=self.current_grp_name, fg="#ffffff")
        self._set_menu_grp_state(True)
        self.show_view("grp")
        self.load_home()
        self.statusbar.config(text=f"Выбран ГРП: {self.current_grp_name} (ID={self.current_grp_id})")

    def clear_current_grp(self):
        """Сбросить выбор ГРП: меню гаснет, таблица очищается."""
        self.current_grp_id = None
        self.current_grp_name = ""
        self.grp_badge_label.config(text="ГРП не выбран", fg="#90a4ae")
        self._set_menu_grp_state(False)
        self.info_name_label.config(text="ГРП не выбран", fg="#90a4ae")
        self.load_home()

    def _current_grp(self) -> Optional[tuple]:
        """(id, name) текущего ГРП или None, если не выбран."""
        if self.current_grp_id is None:
            messagebox.showwarning("Внимание", "Сначала выберите ГРП в меню «☰» → «Выбрать ГРП»!")
            return None
        return (self.current_grp_id, self.current_grp_name)

    def _grp_rows(self) -> list:
        """Рабочие ГРП: каталог оборудования — служебный, в список не входит."""
        return [g for g in self.db.get_all_grp()
                if not self._is_catalog_grp_name(g[1])]

    def _build_grp_list(self, frame, action: str):
        """Список ГРП в основном окне: выбрать рабочий ГРП или удалить его."""
        card = tk.LabelFrame(frame, text="Список ГРП", font=("Arial", 10, "bold"),
                             padx=12, pady=10)
        card.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)

        hint = ("Двойной клик по строке — выбрать ГРП"
                if action == 'select' else
                "Выберите ГРП и нажмите «Удалить»: вместе с ним уйдут "
                "оборудование, запчасти и история")
        tk.Label(card, text=hint, font=("Arial", 9), fg="#6c757d").pack(anchor=tk.W)

        table_frame = tk.Frame(card)
        table_frame.pack(fill=tk.BOTH, expand=True, pady=6)

        columns = ("ID", "Тип ГРП", "Линии", "Факт. срок", "Проект. срок",
                   "Оборудование", "Замены")
        widths = {"ID": 50, "Тип ГРП": 250, "Линии": 60, "Факт. срок": 90,
                  "Проект. срок": 90, "Оборудование": 100, "Замены": 70}
        tree = self._scroll_table(table_frame, columns, widths)

        def fill():
            tree.delete(*tree.get_children())
            for g in self._grp_rows():
                tree.insert('', tk.END, values=(
                    g[0], g[1], g[2], years_to_text(g[3]), years_to_text(g[4]),
                    len(self.db.get_equipment_by_grp(g[0])),
                    self.db.count_replacements_by_grp(g[0]),
                ))
            if not tree.get_children():
                self.statusbar.config(text="Список ГРП пуст — создайте ГРП в меню «Создать ГРП»")

        def selected_grp() -> Optional[tuple]:
            sel = tree.selection()
            if not sel:
                messagebox.showwarning("Внимание", "Выберите ГРП из списка!")
                return None
            return self.db.get_grp_by_id(int(tree.item(sel[0])['values'][0]))

        buttons = tk.Frame(card)
        buttons.pack(fill=tk.X)

        if action == 'select':
            # Кнопок «Обновить» и «Закрыть» на экране выбора нет: список
            # пересобирается при каждом открытии, а выбранный ГРП сам
            # возвращает на рабочий экран.
            def pick():
                grp = selected_grp()
                if grp is not None:
                    self.set_current_grp(grp[0])

            tree.bind('<Double-1>', lambda e: pick())
            self._btn(buttons, "🗂 Выбрать", pick, color='primary',
                      font_size=10, padx=20).pack(side=tk.LEFT, padx=(0, 8))
        else:
            def remove():
                grp = selected_grp()
                if grp is None:
                    return
                if self._is_catalog_grp_name(grp[1]):
                    messagebox.showwarning(
                        "Внимание",
                        "Каталог оборудования — служебный справочник, "
                        "удалить его нельзя.")
                    return
                if not messagebox.askyesno(
                        "Подтверждение",
                        f"Удалить ГРП '{grp[1]}' (ID={grp[0]})?\n"
                        f"Оборудование и история диагностик будут удалены!"):
                    return
                self.db.delete_grp(grp[0])
                if grp[0] == self.current_grp_id:
                    self.clear_current_grp()
                fill()
                self.statusbar.config(text=f"ГРП '{grp[1]}' удалён")

            self._btn(buttons, "🗑 Удалить", remove, color='danger',
                      font_size=10, padx=20).pack(side=tk.LEFT, padx=(0, 8))
            self._btn(buttons, "🔄 Обновить", fill, color='neutral',
                      font_size=9, padx=10).pack(side=tk.LEFT)
            self._btn(buttons, "✖ Закрыть", self._back_to_grp, color='muted',
                      font_size=9, padx=10).pack(side=tk.LEFT, padx=(8, 0))
        fill()

    def choose_grp(self):
        """Экран выбора рабочего ГРП."""
        self._dynamic_view('grp_choose',
                           lambda frame: self._build_grp_list(frame, 'select'))
        self.show_view('grp_choose')
        self.statusbar.config(text="Выберите ГРП из списка")

    def show_help(self):
        """Справка для новых пользователей."""
        messagebox.showinfo(
            "❓ Справка",
            "Быстрый старт:\n\n"
            "1. Меню «☰» слева. Выберите пункт «🗂 Выбрать ГРП»\n"
            "   или создайте новый («➕ Создать ГРП»).\n"
            "2. Выбранный ГРП показывается вверху слева.\n"
            "3. Каждый пункт меню открывает свой экран в этом же окне.\n"
            "   Все действия применяются к выбранному ГРП: оборудование\n"
            "   и запчасти, замены, расчёт алгоритмов, отчёт.\n"
            "4. «Справочники» — каталог моделей оборудования: из него\n"
            "   подтягиваются запчасти. Альбом запчастей загружается кнопкой\n"
            "   «📂 Загрузить PDF-альбом» в каталоге.\n"
            "5. Журнал замен автоматически пишется в файл «Замены.xlsx»;\n"
            "   пересобрать его вручную — кнопка «📥 Обновить Excel» на экране замен."
        )

    def setup_grp_tab(self):
        """Рабочий экран: карточка информации, оборудование и его запчасти в одном окне."""
        self.info_card = tk.LabelFrame(self.grp_tab, text="Информация о ГРП",
                                       font=("Arial", 10, "bold"), padx=12, pady=10)
        self.info_card.pack(fill=tk.X, padx=12, pady=(12, 6))

        self.info_name_label = tk.Label(
            self.info_card, text="ГРП не выбран",
            font=("Arial", 15, "bold"), fg="#90a4ae", anchor=tk.W
        )
        self.info_name_label.pack(anchor=tk.W)

        self.info_label = tk.Label(
            self.info_card,
            text="",
            font=("Arial", 10), fg="#6c757d", justify=tk.LEFT, anchor=tk.W, wraplength=1050
        )
        self.info_label.pack(anchor=tk.W, pady=(4, 0))

        # === Оборудование текущего ГРП ===
        equip_card = tk.LabelFrame(self.grp_tab, text="Оборудование",
                                   font=("Arial", 10, "bold"), padx=12, pady=8)
        equip_card.pack(fill=tk.X, padx=12, pady=(0, 6))

        equip_buttons = tk.Frame(equip_card)
        equip_buttons.pack(fill=tk.X, pady=(0, 4))
        self._btn(equip_buttons, "➕ Добавить оборудование", self._add_equipment_to_grp, color='success', font_size=9, padx=10).pack(side=tk.LEFT, padx=4)
        self._btn(equip_buttons, "✏ Изменить", self._edit_selected_equipment, color='warning', font_size=9, padx=10).pack(side=tk.LEFT, padx=4)
        self._btn(equip_buttons, "🗑 Удалить оборудование", self._delete_selected_equipment, color='danger', font_size=9, padx=10).pack(side=tk.LEFT, padx=4)
        self._btn(equip_buttons, "🔍 Проверить по нормам", self._check_selected_norm, color='info', font_size=9, padx=10).pack(side=tk.LEFT, padx=4)

        # Графы — паспортные сведения единицы (core.equipment_card): первой
        # идёт «№», то есть место единицы в списке. Идентификатор записи
        # пользователю не показывается — он хранится в iid строки.
        columns = ("№",) + tuple(label for _key, label, _width
                                 in equipment_card.TABLE_COLUMNS)
        widths = {"№": 45}
        widths.update({label: width for _key, label, width
                       in equipment_card.TABLE_COLUMNS})
        self.home_tree = self._scroll_table(equip_card, columns, widths, height=7)

        # === Запчасти выбранного оборудования ===
        self.parts_card = tk.LabelFrame(self.grp_tab, text="🔩 Запчасти выбранного оборудования",
                                        font=("Arial", 10, "bold"), padx=12, pady=8)
        self.parts_card.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 6))

        self.parts_buttons = tk.Frame(self.parts_card)
        self.parts_buttons.pack(fill=tk.X, pady=(0, 4))
        self._btn(self.parts_buttons, "➕ Добавить запчасть", self._add_part_to_selected, color='success', font_size=9, padx=10).pack(side=tk.LEFT, padx=4)
        self._btn(self.parts_buttons, "✏ Дата установки", self._edit_selected_part_dates, color='warning', font_size=9, padx=10).pack(side=tk.LEFT, padx=4)
        self._btn(self.parts_buttons, "✏ Норма", self._edit_selected_part_norm, color='warning', font_size=9, padx=10).pack(side=tk.LEFT, padx=4)
        self._btn(self.parts_buttons, "🔄 Заменяемая", self._toggle_selected_part_replaceable, color='info', font_size=9, padx=10).pack(side=tk.LEFT, padx=4)
        self._btn(self.parts_buttons, "🗑 Удалить из состава", self._remove_selected_part, color='danger', font_size=9, padx=10).pack(side=tk.LEFT, padx=4)

        self.parts_effective_label = tk.Label(self.parts_card, text="",
                                              font=("Arial", 10, "bold"), fg="#546E7A")
        self.parts_effective_label.pack(anchor=tk.W, pady=(0, 4))

        parts_frame = tk.Frame(self.parts_card)
        parts_frame.pack(fill=tk.BOTH, expand=True)

        pcolumns = ("№", "Запчасть", "Обозначение", "Замен.", "Дата установки / замены")
        pwidths = {"№": 45, "Запчасть": 280, "Обозначение": 180, "Замен.": 55,
                   "Дата установки / замены": 160}
        self.parts_tree = self._scroll_table(parts_frame, pcolumns, pwidths, height=7)

        self.home_tree.bind('<<TreeviewSelect>>', self._on_home_select)
        self.home_tree.bind('<Double-1>', lambda e: self._select_equipment_parts())

    def _current_selected_equip(self):
        """Выбранное в главной таблице оборудование: (id, name, install) или None.

        Идентификатор берётся из iid строки: в графах таблицы его нет —
        первой графой идёт номер строки 1..n.
        """
        sel = self.home_tree.selection()
        if not sel:
            return None
        values = self.home_tree.item(sel[0])['values']
        install = values[equipment_card.table_index('install_date')]
        return (int(sel[0]), values[1], install)

    def _select_equipment_parts(self):
        """Показать запчасти выбранного оборудования в нижней панели."""
        ctx = self._current_selected_equip()
        if ctx is None:
            return
        self._refresh_parts_panel(ctx[0], ctx[1], ctx[2])

    def _refresh_parts_panel(self, equip_id: int, equip_name: str, equip_install: Optional[str]):
        """Заполнение нижней панели запчастями выбранного оборудования."""
        for row in self.parts_tree.get_children():
            self.parts_tree.delete(row)

        parts = self.db.get_equipment_parts_full(equip_id)
        install_txt = equip_install or "—"
        self.parts_card.config(text=f"🔩 Запчасти: {equip_name}  (срок от даты установки: {install_txt})")

        has_replaceable = False
        number = 0
        for ep in parts:
            if ep[5]:  # снятая запись (история замены) — в составе не показываем
                continue
            number += 1
            zam = "✓" if ep[7] else "—"
            has_replaceable = has_replaceable or bool(ep[7])
            # Срок запчасти считается от даты её установки, а если она не задана —
            # от даты установки оборудования.
            inst_date = ep[4] or equip_install
            # Идентификатор записи — в iid строки: в графах его нет, первой
            # графой идёт номер строки.
            self.parts_tree.insert('', tk.END, iid=str(ep[0]), values=(
                number, ep[2], ep[6] or "", zam, inst_date or "—"))

        # Сколько осталось, здесь не пишем: срок задают только заменяемые
        # запчасти (норма 5 лет), и отсчитывается он от даты их установки.
        self.parts_effective_label.config(
            text=("📆 Срок оборудования задают заменяемые запчасти (норма 5 лет) — "
                  "от даты установки запчасти, а без неё от даты установки оборудования."
                  if has_replaceable else
                  "💡 Заменяемых запчастей нет — собственного срока у оборудования нет"))

    def _selected_part_row(self):
        """Строка выбранной запчасти из нижней панели: (ep_id, name) или None."""
        sel = self.parts_tree.selection()
        if not sel:
            messagebox.showwarning("Внимание", "Сначала выберите запчасть в списке!")
            return None
        values = self.parts_tree.item(sel[0])['values']
        return (int(sel[0]), values[1])

    def _add_part_to_selected(self):
        ctx = self._current_selected_equip()
        if ctx is None:
            messagebox.showwarning("Внимание", "Сначала выберите оборудование в таблице!")
            return
        equip_id, _equip_name, equip_install = ctx
        self._add_equipment_part_dialog(equip_id, equip_install)

    def _add_equipment_part_dialog(self, equip_id: int, equip_install: Optional[str]):
        """Диалог добавления запчасти в состав выбранного оборудования.

        Даты снятия в форме нет: добавляемая запчасть стоит в оборудовании,
        а снятие ставит замена (или кнопка «Даты» в списке запчастей) — при
        добавлении спрашивать её не о чем.
        """
        all_parts = self.db.get_all_parts()
        if not all_parts:
            messagebox.showwarning("Внимание", "Справочник запчастей пуст. Добавьте запчасти через импорт PDF-альбома или вручную.")
            return

        add_window = Toplevel(self.root)
        add_window.title("Добавить запчасть")
        add_window.transient(self.root)
        add_window.grab_set()

        tk.Label(add_window, text="➕ Добавление запчасти в состав",
                 font=("Arial", 12, "bold")).pack(pady=10)

        frame = tk.Frame(add_window)
        frame.pack(pady=8)

        tk.Label(frame, text="Запчасть:", font=("Arial", 10)).grid(row=0, column=0, sticky=tk.W, pady=5)
        part_combo = ttk.Combobox(frame, width=42,
                                  values=[f"{p[0]} - {p[1]} ({p[2]} лет){(' — зам.)' if p[3] else '')}" for p in all_parts])
        part_combo.grid(row=0, column=1, pady=5)

        tk.Label(frame, text="Дата установки:", font=("Arial", 10)).grid(row=1, column=0, sticky=tk.W, pady=5)
        p_install = tk.Entry(frame, width=25)
        p_install.grid(row=1, column=1, sticky=tk.W, pady=5)
        tk.Label(frame, text="пусто = как у оборудования", font=("Arial", 8), fg="#6c757d").grid(row=2, column=1, sticky=tk.W)

        def do_add():
            selection = part_combo.get()
            if not selection:
                messagebox.showwarning("Внимание", "Выберите запчасть!")
                return
            part_id = int(selection.split(" - ")[0])
            self.db.add_equipment_part(
                equip_id, part_id,
                p_install.get().strip() or None,
                None
            )
            add_window.destroy()
            ctx = self._current_selected_equip()
            if ctx:
                self._refresh_parts_panel(ctx[0], ctx[1], ctx[2])

        btn_frame = tk.Frame(add_window)
        btn_frame.pack(pady=12)
        self._btn(btn_frame, "💾 Добавить", do_add, color='success', font_size=10, padx=15).pack(side=tk.LEFT, padx=8)
        self._btn(btn_frame, "❌ Отмена", add_window.destroy, color='danger', font_size=10, padx=15).pack(side=tk.LEFT, padx=8)
        fit_window(add_window, min_width=560, min_height=240)

    def _edit_selected_part_dates(self):
        ctx = self._current_selected_equip()
        if ctx is None:
            messagebox.showwarning("Внимание", "Сначала выберите оборудование в таблице!")
            return
        equip_id, _equip_name, equip_install = ctx
        sel = self._selected_part_row()
        if sel is None:
            return
        ep_id, name = sel
        ep_data = next((ep for ep in self.db.get_equipment_parts_full(equip_id) if ep[0] == ep_id), None)
        if not ep_data:
            return
        self._edit_part_dates_dialog(equip_id, ep_id, name, equip_install, ep_data)

    def _edit_part_dates_dialog(self, equip_id: int, ep_id: int, name: str,
                                equip_install: Optional[str], ep_data: tuple):
        """Диалог изменения даты установки (замены) запчасти.

        Даты снятия в форме нет: снятие ставит замена — и запчастью, и
        единицей оборудования целиком. Значение при этом переносится как
        есть (removal_date записи): иначе правка даты установки отменила бы
        снятие с учёта.
        """
        default_install = equip_install if not ep_data[4] else ep_data[4]
        removal_date = ep_data[5]

        edit_window = Toplevel(self.root)
        edit_window.title("Изменить дату установки запчасти")
        edit_window.transient(self.root)
        edit_window.grab_set()

        tk.Label(edit_window, text=f"✏ Дата установки: {name}",
                 font=("Arial", 12, "bold")).pack(pady=10)

        frame = tk.Frame(edit_window)
        frame.pack(pady=8)

        install_entry = tk.Entry(frame, width=25)
        install_entry.insert(0, default_install or "")

        tk.Label(frame, text="Дата установки:", font=("Arial", 10)).grid(row=0, column=0, sticky=tk.W, pady=5)
        install_entry.grid(row=0, column=1, sticky=tk.W, pady=5)
        tk.Label(frame, text="пусто = как у оборудования", font=("Arial", 8),
                 fg="#6c757d").grid(row=1, column=1, sticky=tk.W)

        def save():
            self.db.update_equipment_part(
                ep_id,
                install_entry.get().strip() or None,
                removal_date
            )
            edit_window.destroy()
            ctx = self._current_selected_equip()
            if ctx:
                self._refresh_parts_panel(ctx[0], ctx[1], ctx[2])
                self.load_home()

        btn_frame = tk.Frame(edit_window)
        btn_frame.pack(pady=12)
        self._btn(btn_frame, "💾 Сохранить", save, color='success', font_size=10, padx=15).pack(side=tk.LEFT, padx=8)
        self._btn(btn_frame, "❌ Отмена", edit_window.destroy, color='danger', font_size=10, padx=15).pack(side=tk.LEFT, padx=8)
        fit_window(edit_window, min_width=480, min_height=220)

    def _edit_selected_part_norm(self):
        ctx = self._current_selected_equip()
        if ctx is None:
            messagebox.showwarning("Внимание", "Сначала выберите оборудование в таблице!")
            return
        equip_id, _equip_name, _install = ctx
        sel = self._selected_part_row()
        if sel is None:
            return
        ep_id, name = sel
        ep_data = next((ep for ep in self.db.get_equipment_parts_full(equip_id) if ep[0] == ep_id), None)
        if not ep_data:
            return
        self._edit_part_norm_dialog(ep_data)

    def _edit_part_norm_dialog(self, ep_data: tuple):
        """Диалог изменения нормы (срока службы) запчасти."""
        norm_window = Toplevel(self.root)
        norm_window.title("Изменить норму запчасти")
        norm_window.transient(self.root)
        norm_window.grab_set()

        tk.Label(norm_window, text=f"✏ Норма запчасти: {ep_data[2]}",
                 font=("Arial", 12, "bold")).pack(pady=10)

        frame = tk.Frame(norm_window)
        frame.pack(pady=8)

        tk.Label(frame, text="Срок службы:", font=("Arial", 10)).grid(row=0, column=0, sticky=tk.W, pady=5)
        years_entry = tk.Entry(frame, width=16)
        years_entry.insert(0, years_to_text(ep_data[3]))
        years_entry.grid(row=0, column=1, sticky=tk.W, pady=5)
        tk.Label(frame, text="например: 7 лет 4 мес или 7,3",
                 font=("Arial", 8), fg="#6c757d").grid(row=1, column=1, sticky=tk.W)

        def save_norm():
            try:
                years = parse_years_strict(years_entry.get(), "срок службы")
                if years <= 0:
                    raise DurationError("Срок службы должен быть больше нуля.")
                self.db.update_part(ep_data[1], ep_data[2], years)
                norm_window.destroy()
                ctx = self._current_selected_equip()
                if ctx:
                    self._refresh_parts_panel(ctx[0], ctx[1], ctx[2])
                self.statusbar.config(
                    text=f"Норма '{ep_data[2]}' = {years_to_text(years)}")
            except DurationError as e:
                messagebox.showerror("Ошибка", str(e))

        btn_frame = tk.Frame(norm_window)
        btn_frame.pack(pady=12)
        self._btn(btn_frame, "💾 Сохранить", save_norm, color='success', font_size=10, padx=15).pack(side=tk.LEFT, padx=8)
        self._btn(btn_frame, "❌ Отмена", norm_window.destroy, color='danger', font_size=10, padx=15).pack(side=tk.LEFT, padx=8)
        fit_window(norm_window, min_width=480, min_height=250)

    def _toggle_selected_part_replaceable(self):
        ctx = self._current_selected_equip()
        if ctx is None:
            messagebox.showwarning("Внимание", "Сначала выберите оборудование в таблице!")
            return
        equip_id, _equip_name, _install = ctx
        sel = self._selected_part_row()
        if sel is None:
            return
        ep_id, name = sel
        ep_data = next((ep for ep in self.db.get_equipment_parts_full(equip_id) if ep[0] == ep_id), None)
        if not ep_data:
            return
        self.db.update_part_replaceable(ep_data[1], not ep_data[7])
        self._refresh_parts_panel(equip_id, ctx[1], ctx[2])
        part = self.db.get_part_by_name(ep_data[2])
        mark = 'заменяемая (5 лет)' if part and part[3] else 'не заменяемая'
        self.statusbar.config(text=f"Запчасть '{ep_data[2]}' — {mark}")

    def _remove_selected_part(self):
        ctx = self._current_selected_equip()
        if ctx is None:
            messagebox.showwarning("Внимание", "Сначала выберите оборудование в таблице!")
            return
        equip_id, equip_name, equip_install = ctx
        sel = self._selected_part_row()
        if sel is None:
            return
        ep_id, name = sel
        if messagebox.askyesno("Подтверждение", f"Удалить '{name}' из состава оборудования?"):
            self.db.remove_equipment_part(ep_id)
            self._refresh_parts_panel(equip_id, equip_name, equip_install)

    def _add_equipment_to_grp(self):
        """Добавить единицу оборудования прямо на рабочем экране.

        Паспортные сведения вводятся той же формой, что и в составе ГРП, —
        второй формы с другим набором полей не заводится. Запчасти, как и при
        создании ГРП, подтягиваются из каталога по наименованию.
        """
        if self._current_grp() is None:
            return
        item = _equipment_row_dialog(self)
        if item is None:
            return
        name = item['name']
        equip_id = self.db.add_equipment(
            self.current_grp_id, name, item['install_date'],
            item.get('removal_date') or None,
            details=equipment_card.details(item))
        linked = self._auto_link_parts_from_catalog(equip_id, name)
        self.load_home()
        self.statusbar.config(
            text=f"Оборудование '{name}' добавлено "
                 f"(запчастей из каталога: {linked})")

    def _edit_selected_equipment(self):
        """Изменить единицу оборудования, выбранную в таблице."""
        ctx = self._current_selected_equip()
        if ctx is None:
            messagebox.showwarning("Внимание", "Выберите оборудование для правки!")
            return
        equip_id, equip_name, _install = ctx
        row = next((e for e in self.db.get_equipment_by_grp(self.current_grp_id)
                    if e[0] == equip_id), None)
        if row is None:
            return
        item = _equipment_row_dialog(self, equipment_card.form_item(row))
        if item is None:
            return
        self.db.update_equipment(
            equip_id, item['name'], item['install_date'],
            item.get('removal_date') or None,
            details=equipment_card.details(item))
        self.load_home()
        self.statusbar.config(text=f"Оборудование '{equip_name}' изменено")

    def _delete_selected_equipment(self):
        ctx = self._current_selected_equip()
        if ctx is None:
            messagebox.showwarning("Внимание", "Выберите оборудование для удаления!")
            return
        equip_id, equip_name, _install = ctx
        if messagebox.askyesno("Подтверждение", f"Удалить оборудование '{equip_name}'?"):
            self.db.delete_equipment(equip_id)
            self.load_home()
            self.statusbar.config(text=f"Оборудование '{equip_name}' удалено")

    def _check_selected_norm(self):
        ctx = self._current_selected_equip()
        if ctx is None:
            messagebox.showwarning("Внимание", "Выберите оборудование!")
            return
        equip_id, equip_name, install_date = ctx
        remaining = self.doc_analyzer.get_remaining_life(equip_id, install_date)
        if remaining is not None:
            if remaining < 0:
                status = "❌ СРОК ИСТЁК, требуется замена!"
                note = f"⚠️ Просрочено на {years_to_text(-remaining)}"
            elif remaining < 1:
                status = "⚠️ Требует внимания"
                note = f"⏰ Осталось {years_to_text(remaining)}"
            else:
                status = "✅ В пределах срока"
                note = f"⏰ Остаток {years_to_text(remaining)}"
            messagebox.showinfo("Проверка срока",
                                f"📌 Оборудование: {equip_name}\n"
                                f"📅 Установлено: {install_date}\n"
                                f"🔧 Срок определяется по запчастям\n"
                                f"📆 Мин. остаток среди запчастей: {years_to_text(remaining)}\n"
                                f"📊 Статус: {status}\n({note})")
        else:
            messagebox.showwarning("Нет запчастей", f"Для '{equip_name}' нет запчастей.\n"
                                                    f"Срока у оборудования нет.\n"
                                                    f"Внесите оборудование (запчасти), чтобы появился срок.")

    def _on_home_select(self, event):
        ctx = self._current_selected_equip()
        if ctx is None:
            return
        row = self.home_tree.index(self.home_tree.selection()[0]) + 1
        self.statusbar.config(text=f"Оборудование №{row}: {ctx[1]}")
        self._refresh_parts_panel(ctx[0], ctx[1], ctx[2])

    def load_home(self):
        """Обновление рабочего экрана для текущего ГРП (таблица пуста, если ГРП не выбран)."""
        for row in self.home_tree.get_children():
            self.home_tree.delete(row)
        for row in self.parts_tree.get_children():
            self.parts_tree.delete(row)

        if self.current_grp_id is None:
            self.info_name_label.config(text="ГРП не выбран", fg="#90a4ae")
            self.info_label.config(text="")
            self.parts_card.config(text="🔩 Запчасти выбранного оборудования")
            self.parts_effective_label.config(text="")
            return

        grp = self.db.get_grp_by_id(self.current_grp_id)
        if not grp:
            return

        equipment = self.db.get_equipment_by_grp(grp[0])
        repl_count = self.db.count_replacements_by_grp(grp[0])

        passport = grp_passport.values(grp)
        self.info_name_label.config(text=grp[1], fg="#37474F")
        self.info_label.config(text=(
            f"Линий: {grp[2]}   |   Фактический срок: {years_to_text(grp[3])}   |   Проектный срок: {years_to_text(grp[4])}   |   "
            f"Оборудование: {len(equipment)} шт.   |   Замены (ремонт): {repl_count}\n"
            f"Адрес: {passport.get('address') or '—'}   |   "
            f"Рег. №: {passport.get('reg_number') or '—'}"
        ))

        for number, e in enumerate(equipment, start=1):
            # Идентификатор записи — в iid строки: в графах его нет, первой
            # графой идёт номер оборудования.
            self.home_tree.insert('', tk.END, iid=str(e[0]),
                                  values=[number] + equipment_card.table_view(e))

        self.parts_card.config(text="🔩 Запчасти выбранного оборудования")
        self.parts_effective_label.config(text="")

    def view_repairs(self):
        """Перейти к журналу замен выбранного ГРП."""
        if self._current_grp() is None:
            return
        self.show_view("repairs")
        self.load_replacements()

    def view_tech(self):
        """Перейти к техническим коэффициентам выбранного ГРП."""
        if self._current_grp() is None:
            return
        self.show_view("tech")
        self.load_tech_history()

    def view_failures(self):
        """Перейти к информации по отказам выбранного ГРП."""
        if self._current_grp() is None:
            return
        self.show_view("failures")
        self.load_failures()

    def view_diagnostics(self):
        """Перейти к техническому диагностированию выбранного ГРП."""
        if self._current_grp() is None:
            return
        self.show_view("diagnostics")
        self.load_diagnostics()

    def view_catalog(self):
        """Открыть каталог оборудования: список всегда перечитывается из базы."""
        self.show_view("catalog")
        self.load_catalog()

    # === РАЗДЕЛ «КАТАЛОГ ОБОРУДОВАНИЯ» ===

    def setup_catalog_tab(self):
        select_frame = tk.Frame(self.catalog_tab)
        select_frame.pack(pady=10)

        tk.Label(select_frame, text="Каталог:", font=("Arial", 10, "bold")).pack(side=tk.LEFT, padx=5)
        self.catalog_grp_combo = ttk.Combobox(select_frame, width=36)
        self.catalog_grp_combo.pack(side=tk.LEFT, padx=5)
        self.catalog_grp_combo.bind('<<ComboboxSelected>>', lambda e: self.load_catalog())

        self._btn(select_frame, "📂 Загрузить PDF-альбом", self.view_pdf_import, color='primary', font_size=9, padx=10).pack(side=tk.LEFT, padx=5)
        self._btn(select_frame, "➕ Оборудование", self.add_catalog_equipment, color='success', font_size=9, padx=10).pack(side=tk.LEFT, padx=5)
        self._btn(select_frame, "🔩 Запчасти", self._catalog_open_parts, color='brown', font_size=9, padx=10).pack(side=tk.LEFT, padx=5)

        table_frame = tk.Frame(self.catalog_tab)
        table_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(10, 5))

        # Модели каталога нумеруются по порядку: идентификатор записи
        # пользователю не показывается, он хранится в iid строки.
        columns = ("№", "Наименование", "Срок службы", "Запчасти")
        col_widths = {"№": 45, "Наименование": 560, "Срок службы": 110, "Запчасти": 80}
        self.catalog_tree = self._scroll_table(table_frame, columns, col_widths, height=12)

        # Запчасти выбранной модели — встроенная панель (без отдельного окна)
        self.catalog_parts_card = tk.LabelFrame(self.catalog_tab, text="🔩 Запчасти модели",
                                                font=("Arial", 10, "bold"), padx=10, pady=6)
        self.catalog_parts_card.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 5))

        catalog_parts_toolbar = tk.Frame(self.catalog_parts_card)
        catalog_parts_toolbar.pack(fill=tk.X, pady=(0, 4))
        self._btn(catalog_parts_toolbar, "➕ Добавить запчасть", self._catalog_inline_add_part, color='success', font_size=9, padx=10).pack(side=tk.LEFT, padx=4)
        self._btn(catalog_parts_toolbar, "✏ Дата установки", self._catalog_inline_edit_dates, color='warning', font_size=9, padx=10).pack(side=tk.LEFT, padx=4)
        self._btn(catalog_parts_toolbar, "✏ Норма", self._catalog_inline_edit_norm, color='warning', font_size=9, padx=10).pack(side=tk.LEFT, padx=4)
        self._btn(catalog_parts_toolbar, "🔄 Заменяемая", self._catalog_inline_toggle_replaceable, color='info', font_size=9, padx=10).pack(side=tk.LEFT, padx=4)
        self._btn(catalog_parts_toolbar, "🗑 Удалить из состава", self._catalog_inline_remove_part, color='danger', font_size=9, padx=10).pack(side=tk.LEFT, padx=4)

        self.catalog_parts_effective = tk.Label(self.catalog_parts_card,
                                                text="",
                                                font=("Arial", 9, "bold"), fg="#546E7A")
        self.catalog_parts_effective.pack(anchor=tk.W, pady=(0, 4))

        cpf = tk.Frame(self.catalog_parts_card)
        cpf.pack(fill=tk.BOTH, expand=True)
        # У модели каталога остатка быть не может: отсчёт идёт от даты
        # установки в ГРП, а её у каталожной позиции нет — поэтому и графы нет.
        cat_cols = ("№", "Запчасть", "Обозначение", "Замен.", "Дата установки / замены")
        cat_w = {"№": 45, "Запчасть": 280, "Обозначение": 200, "Замен.": 55,
                 "Дата установки / замены": 160}
        self.catalog_parts_tree = self._scroll_table(cpf, cat_cols, cat_w, height=6)

        # Выбор строки или двойной клик — показать запчасти модели
        self.catalog_tree.bind('<<TreeviewSelect>>', lambda e: self._catalog_show_parts())
        self.catalog_tree.bind('<Double-1>', lambda e: self._catalog_show_parts())

    def _is_catalog_grp_name(self, name: str) -> bool:
        """Признак служебного ГРП-каталога (не выводится в списке ГРП)."""
        return bool(name and 'каталог' in name.lower())

    def _auto_link_parts_from_catalog(self, equipment_id: int, equip_name: str) -> int:
        """Копирует запчасти из каталога с тем же названием оборудования.

        Возвращает количество привязанных запчастей (0 — модели нет в каталоге).
        Даты запчастей не задаём (по умолчанию — дата установки оборудования),
        срок каждой запчасти — 5 лет. Срок оборудования = мин. остаток среди них.
        """
        catalog_id = self._catalog_grp_id()
        if not catalog_id:
            return 0
        catalog_equipment = self.db.get_equipment_by_grp(catalog_id)
        template = next((e for e in catalog_equipment if e[1].strip() == equip_name.strip()), None)
        if not template:
            token = equip_name.strip().split()[-1]
            matches = [e for e in catalog_equipment if e[1].strip().split()[-1] == token]
            if len(matches) == 1:
                template = matches[0]
        if not template:
            return 0
        parts = self.db.get_equipment_parts_full(template[0])
        for part in parts:
            self.db.add_equipment_part(equipment_id, part[1], None, None, part[6])
        return len(parts)

    def _catalog_grp_id(self) -> Optional[int]:
        """ID выбранного ГРП-каталога (или ближайшего по имени)."""
        if self.catalog_grp_combo.get():
            return int(self.catalog_grp_combo.get().split(" - ")[0])
        grps = self.db.get_all_grp()
        if not grps:
            return None
        for g in grps:
            if 'каталог' in g[1].lower():
                return g[0]
        return grps[0][0]

    def load_catalog(self):
        grp_id = self._catalog_grp_id()
        if grp_id is None:
            return

        for row in self.catalog_tree.get_children():
            self.catalog_tree.delete(row)

        equipment = self.db.get_equipment_by_grp(grp_id)
        for number, e in enumerate(equipment, start=1):
            equip = self._to_equipment_list([e])[0]
            norm = self._parts_aware_norm(equip)
            norm_view = years_to_text(norm) if norm else "—"
            self.catalog_tree.insert('', tk.END, iid=str(e[0]), values=(
                number, e[1], norm_view, len(self.db.get_equipment_parts(e[0]))
            ))
        self.statusbar.config(text=f"Каталог: {len(equipment)} единиц оборудования")

    def _build_pdf_import(self, frame):
        """Экран импорта альбома: что произойдёт и кнопка выбора файла."""
        card = tk.LabelFrame(frame, text="📂 Импорт из PDF-альбома",
                             font=("Arial", 10, "bold"), padx=14, pady=10)
        card.pack(fill=tk.X, padx=12, pady=12)

        tk.Label(card, text="Из альбома запчастей читаются модели оборудования "
                            "и их состав запчастей.",
                 font=("Arial", 11, "bold"), fg="#546E7A", anchor=tk.W).pack(anchor=tk.W)

        steps = [
            "1. Разбор таблиц альбома: модели оборудования и их запчасти.",
            "2. Пополнение справочника запчастей (норма заменяемых — 5 лет).",
            "3. Создание моделей в каталоге оборудования.",
            "4. Привязка запчастей к моделям каталога.",
            "Страницы разборки узлов моделями не становятся.",
        ]
        for step in steps:
            tk.Label(card, text=step, font=("Arial", 9), anchor=tk.W,
                     justify=tk.LEFT).pack(anchor=tk.W, pady=1)

        grp_name = (self.catalog_grp_combo.get().split(" - ", 1)[1]
                    if self.catalog_grp_combo.get() else "Каталог оборудования")
        tk.Label(card, text=f"Каталог: {grp_name}", font=("Arial", 9),
                 fg="#6c757d", anchor=tk.W).pack(anchor=tk.W, pady=(8, 0))

        buttons = tk.Frame(frame)
        buttons.pack(fill=tk.X, padx=12, pady=6)
        self._btn(buttons, "📂 Выбрать PDF-альбом",
                  self._run_pdf_import, color='primary', font_size=10,
                  padx=20).pack(side=tk.LEFT)
        self._btn(buttons, "📦 Открыть каталог", self.view_catalog,
                  color='neutral', font_size=10, padx=20).pack(side=tk.LEFT, padx=8)

    def view_pdf_import(self):
        """Экран импорта альбома запчастей из PDF."""
        self._dynamic_view('pdf_import', self._build_pdf_import)
        self.show_view('pdf_import')
        self.statusbar.config(text="Импорт из PDF-альбома")

    def _run_pdf_import(self):
        """Выбор файла альбома и импорт: справочник, каталог, привязка."""
        try:
            from integration.pdf_parts_import import scan_pdf, import_to_db, create_catalog_equipment
        except ImportError:
            messagebox.showerror("Ошибка", "Модуль integration.pdf_parts_import не найден")
            return

        filename = filedialog.askopenfilename(
            title="Выберите PDF-альбом запчастей",
            filetypes=[("PDF файлы", "*.pdf"), ("Все файлы", "*.*")]
        )
        if not filename:
            return

        self.statusbar.config(text="⏳ Чтение PDF и импорт...")
        self.root.update_idletasks()

        try:
            units = scan_pdf(filename)

            # Пополняем справочник запчастей (без привязки)
            import_to_db(self.db, units, link_to_equipment=False)

            # Добавляем оборудование в выбранный ГРП-каталог
            grp_name = self.catalog_grp_combo.get().split(" - ", 1)[1] if self.catalog_grp_combo.get() else "Каталог оборудования"
            create_catalog_equipment(self.db, units, grp_name)

            # Привязываем запчасти к оборудованию каталога
            import_to_db(self.db, units, link_to_equipment=True)

            self.update_catalog_combo()
            self.load_catalog()

            messagebox.showinfo(
                "✅ Импорт завершён",
                f"Из альбома прочитано единиц оборудования: {len(units)}\n"
                f"Запчасти добавлены в справочник и привязаны к оборудованию каталога.\n\n"
                f"Источник: {filename}"
            )
        except Exception as e:
            messagebox.showerror("Ошибка импорта", str(e))
        finally:
            self.statusbar.config(text="Готов к работе")

    def add_catalog_equipment(self):
        grp_id = self._catalog_grp_id()
        if grp_id is None:
            messagebox.showwarning("Внимание", "Сначала создайте ГРП-каталог!")
            return
        grp_name = next((g[1] for g in self.db.get_all_grp() if g[0] == grp_id), "")

        window = Toplevel(self.root)
        window.title(f"Добавить оборудование в каталог: {grp_name}")
        window.transient(self.root)
        window.grab_set()

        tk.Label(window, text=f"➕ Оборудование в каталог: {grp_name}",
                 font=("Arial", 12, "bold"), fg="#546E7A").pack(pady=10)

        frame = tk.Frame(window)
        frame.pack(pady=10)

        tk.Label(frame, text="Наименование (модель):", font=("Arial", 10)).grid(row=0, column=0, sticky=tk.W, pady=5)
        # Списка готовых наименований здесь нет: каталог — перечень моделей
        # предприятия, и выбирать модель из чужого каталога нечего. Вместо
        # подсказки — проверка, что такая единица в каталоге уже не заведена.
        name_entry = tk.Entry(frame, width=45)
        name_entry.grid(row=0, column=1, sticky=tk.W, pady=5)

        tk.Label(frame, text="💡 Даты не нужны — срок службы определится запчастями",
                 font=("Arial", 8), fg="#6c757d").grid(row=1, column=1, sticky=tk.W)

        def save():
            try:
                name = name_entry.get().strip()
                if not name:
                    messagebox.showerror("Ошибка", "Введите наименование!")
                    return
                same = self._catalog_same_equipment(grp_id, name)
                if same is not None:
                    messagebox.showerror(
                        "Ошибка",
                        f"Такое оборудование в каталоге уже есть: "
                        f"«{same[1]}» (строка №{same[0]}).\n"
                        "Откройте его и добавьте запчасти либо впишите другое "
                        "наименование.")
                    return
                self.db.add_equipment(grp_id, name, None, None)
                messagebox.showinfo("Успех", "✅ Оборудование добавлено в каталог!")
                window.destroy()
                self.load_catalog()
            except Exception as e:
                messagebox.showerror("Ошибка", str(e))

        btn_frame = tk.Frame(window)
        btn_frame.pack(pady=15)
        self._btn(btn_frame, "💾 Сохранить", save, color='success', font_size=10, padx=20).pack(side=tk.LEFT, padx=10)
        self._btn(btn_frame, "❌ Отмена", window.destroy, color='danger', font_size=10, padx=20).pack(side=tk.LEFT, padx=10)
        fit_window(window, min_width=560, min_height=260)

    def _catalog_same_equipment(self, grp_id: int, name: str):
        """Такая же модель уже есть в каталоге? → (номер строки, название).

        Номер — место записи в списке каталога (как в графе «№»), а не
        идентификатор в базе: по нему запись и находят на экране. Сравнение
        наименований — в core.equipment_card: «РДС-32» и «рдс-32» это одна
        модель, и заводить её второй раз незачем.
        """
        equipment = self.db.get_equipment_by_grp(grp_id)
        twin = equipment_card.find_by_name(equipment, name)
        if twin is None:
            return None
        number = [row[0] for row in equipment].index(twin[0]) + 1
        return number, equipment_card.value(twin, 'name')

    def _catalog_show_parts(self):
        """Показать запчасти выбранной модели в встроенной панели каталога."""
        selected = self.catalog_tree.selection()
        if not selected:
            return
        values = self.catalog_tree.item(selected[0])['values']
        self._catalog_refresh_parts(int(selected[0]), values[1])

    def _catalog_refresh_parts(self, equip_id: int, equip_name: str):
        """Заполнение нижней панели каталога запчастями модели."""
        for row in self.catalog_parts_tree.get_children():
            self.catalog_parts_tree.delete(row)

        self.catalog_parts_card.config(text=f"🔩 Запчасти модели: {equip_name}")
        parts = self.db.get_equipment_parts_full(equip_id)
        number = 0
        for ep in parts:
            if ep[5]:  # история замен — не показываем
                continue
            number += 1
            zam = "✓" if ep[7] else "—"
            inst_date = ep[4]
            # Модель каталога — шаблон без даты установки, поэтому остатка
            # здесь не бывает (в ГРП он идёт от даты установки оборудования).
            self.catalog_parts_tree.insert('', tk.END, iid=str(ep[0]), values=(
                number, ep[2], ep[6] or "", zam, inst_date or "—"))
        if parts:
            self.catalog_parts_effective.config(
                text=f"📋 Запчастей: {len(parts)} · норма: заменяемые — 5 лет, "
                     f"остальные — 20 лет. Срок считается от даты установки "
                     f"оборудования в ГРП.",
                fg="#546E7A")
        else:
            self.catalog_parts_effective.config(
                text="💡 Запчастей нет",
                fg="#6c757d")

    def _catalog_selected_equip(self):
        """Выбранная модель каталога: (equip_id, name) или None."""
        selected = self.catalog_tree.selection()
        if not selected:
            messagebox.showwarning("Внимание", "Выберите модель в каталоге!")
            return None
        values = self.catalog_tree.item(selected[0])['values']
        return (int(selected[0]), values[1])

    def _catalog_selected_part(self):
        """Выбранная запчасть модели: (ep_id, name) или None."""
        sel = self.catalog_parts_tree.selection()
        if not sel:
            messagebox.showwarning("Внимание", "Сначала выберите запчасть в списке!")
            return None
        values = self.catalog_parts_tree.item(sel[0])['values']
        return (int(sel[0]), values[1])

    def _catalog_inline_add_part(self):
        sel = self._catalog_selected_equip()
        if sel is None:
            return
        equip_id, equip_name = sel
        self._add_equipment_part_dialog(equip_id, None)
        self._catalog_refresh_parts(equip_id, equip_name)

    def _catalog_inline_edit_dates(self):
        sel = self._catalog_selected_equip()
        if sel is None:
            return
        equip_id, equip_name = sel
        part = self._catalog_selected_part()
        if part is None:
            return
        ep_id, name = part
        ep_data = next((ep for ep in self.db.get_equipment_parts_full(equip_id) if ep[0] == ep_id), None)
        if not ep_data:
            return
        self._edit_part_dates_dialog(equip_id, ep_id, name, None, ep_data)
        self._catalog_refresh_parts(equip_id, equip_name)

    def _catalog_inline_edit_norm(self):
        sel = self._catalog_selected_equip()
        if sel is None:
            return
        equip_id, equip_name = sel
        part = self._catalog_selected_part()
        if part is None:
            return
        ep_id, name = part
        ep_data = next((ep for ep in self.db.get_equipment_parts_full(equip_id) if ep[0] == ep_id), None)
        if not ep_data:
            return
        self._edit_part_norm_dialog(ep_data)
        self._catalog_refresh_parts(equip_id, equip_name)

    def _catalog_inline_toggle_replaceable(self):
        sel = self._catalog_selected_equip()
        if sel is None:
            return
        equip_id, equip_name = sel
        part = self._catalog_selected_part()
        if part is None:
            return
        ep_id, name = part
        ep_data = next((ep for ep in self.db.get_equipment_parts_full(equip_id) if ep[0] == ep_id), None)
        if not ep_data:
            return
        self.db.update_part_replaceable(ep_data[1], not ep_data[7])
        self._catalog_refresh_parts(equip_id, equip_name)
        part_row = self.db.get_part_by_name(ep_data[2])
        mark = 'заменяемая (5 лет)' if part_row and part_row[3] else 'не заменяемая'
        self.statusbar.config(text=f"Запчасть '{ep_data[2]}' — {mark}")

    def _catalog_inline_remove_part(self):
        sel = self._catalog_selected_equip()
        if sel is None:
            return
        equip_id, equip_name = sel
        part = self._catalog_selected_part()
        if part is None:
            return
        ep_id, name = part
        if messagebox.askyesno("Подтверждение", f"Удалить '{name}' из состава модели?"):
            self.db.remove_equipment_part(ep_id)
            self._catalog_refresh_parts(equip_id, equip_name)

    def _catalog_open_parts(self):
        self._catalog_show_parts()

    def setup_replacements_tab(self):
        select_frame = tk.Frame(self.repairs_tab)
        select_frame.pack(pady=10)

        tk.Label(select_frame, text="Текущий ГРП:", font=("Arial", 10, "bold")).pack(side=tk.LEFT, padx=5)
        self.repairs_grp_label = tk.Label(select_frame, text="—", font=("Arial", 10, "bold"), fg="#546E7A")
        self.repairs_grp_label.pack(side=tk.LEFT, padx=8)

        self._btn(select_frame, "➕ Добавить замену", self.add_replacement, color='success', font_size=9, padx=10).pack(side=tk.LEFT, padx=5)
        self._btn(select_frame, "✏ Редактировать", self.edit_replacement, color='warning', font_size=9, padx=10).pack(side=tk.LEFT, padx=5)
        self._btn(select_frame, "🗑 Удалить", self.delete_replacement, color='danger', font_size=9, padx=10).pack(side=tk.LEFT, padx=5)
        self._btn(select_frame, "📥 Обновить Excel", self.sync_excel, color='indigo', font_size=9, padx=10).pack(side=tk.LEFT, padx=5)

        table_frame = tk.LabelFrame(self.repairs_tab, text="Журнал замен запасных частей", padx=10, pady=10)
        table_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Графы и их порядок — в core.repair_journal: тот же список читает
        # строка выборки, поэтому подписи и порядок не разъезжаются.
        columns = ("№",) + tuple(label for _key, label, _width
                                 in repair_journal.TABLE_COLUMNS)
        # Графы подобраны так, чтобы в развёрнутом окне журнал помещался
        # целиком; в обычном окне правые графы достаёт нижний ползунок.
        col_widths = {"№": 38}
        col_widths.update({label: width for _key, label, width
                           in repair_journal.TABLE_COLUMNS})
        self.repairs_tree = self._scroll_table(table_frame, columns, col_widths, height=12)

        tk.Label(self.repairs_tab,
                 text="💡 Замены хранятся в БД и автоматически записываются в файл «Замены.xlsx»\n"
                      "(один лист «Ремонт …» на каждый ГРП, формат как в «Лида.xlsx»).\n"
                      "⚙️ Если в записи выбрано «сбросить срок запчасти» или «заменить оборудование "
                      "целиком», срок службы пересчитывается заново от даты замены.",
                 fg="#6c757d", font=("Arial", 9), justify=tk.CENTER).pack(pady=5)

    def load_replacements(self):
        grp = self._current_grp()
        if grp is None:
            return None
        grp_id = grp[0]
        grp_name = grp[1]
        self.repairs_grp_label.config(text=grp_name)

        for row in self.repairs_tree.get_children():
            self.repairs_tree.delete(row)

        detailed = getattr(self.db, 'get_replacements_detailed', None)
        rows = detailed(grp_id) if detailed else self.db.get_replacements_by_grp(grp_id)
        effectful = 0
        for number, row in enumerate(rows, start=1):
            if detailed:
                cells = repair_journal.table_cells(row)
                if repair_journal.value(row, 'effect'):
                    effectful += 1
            else:
                # Запасная выборка без привязки к оборудованию: те же графы,
                # но собранные по своему списку колонок.
                cells = repair_journal.table_cells(
                    dict(zip(repair_journal.BY_GRP_COLUMNS, row)))
            # Идентификатор записи — в iid строки: в графах его нет, первой
            # графой идёт номер записи.
            self.repairs_tree.insert('', tk.END, iid=str(row[0]),
                                     values=[number] + cells)

        if detailed:
            extra = (f", со сбросом срока: {effectful}" if effectful else "")
            self.statusbar.config(
                text=f"Замены ГРП «{grp_name}» (#{grp_id}): {len(rows)} записей{extra}")
        else:
            self.statusbar.config(
                text=f"Замены ГРП «{grp_name}» (#{grp_id}): {len(rows)} записей")
        return grp_id

    def _replacement_dialog(self, grp_id: int, grp_name: str, repl: Optional[tuple] = None):
        """Окно добавления/редактирования замены. repl — кортеж из БД или None."""
        window = Toplevel(self.root)
        window.title(f"Замена — ГРП {grp_name}")
        window.transient(self.root)
        window.grab_set()

        is_edit = repl is not None
        title = "✏ Редактирование замены" if is_edit else "➕ Добавление замены запчасти"
        tk.Label(window, text=f"{title}\nГРП #{grp_id}: {grp_name}",
                 font=("Arial", 12, "bold"), fg="#546E7A").pack(pady=10)

        body = tk.Frame(window)
        body.pack(fill=tk.BOTH, expand=True, padx=12)

        def ctrl(row, label, widget, hint=None, col=0):
            tk.Label(body, text=label, font=("Arial", 10)).grid(
                row=row, column=col, sticky=tk.W, pady=5)
            widget.grid(row=row, column=col + 1, sticky=tk.W, pady=5)
            if hint:
                tk.Label(body, text=hint, font=("Arial", 8),
                         fg="#6c757d").grid(row=row, column=col + 2, sticky=tk.W, padx=6)

        date_entry = tk.Entry(body, width=34)
        part_entry = tk.Entry(body, width=34)
        type_combo = ttk.Combobox(body, width=32, values=EQUIPMENT_TYPES)
        model_entry = tk.Entry(body, width=34)
        maker_entry = AutocompleteCombobox(body, width=32, values=self.db.get_all_manufacturers())
        work_combo = ttk.Combobox(body, width=32, values=WORK_TYPES)
        reason_entry = tk.Entry(body, width=34)
        boss_entry = tk.Entry(body, width=34)

        ctrl(0, "Дата замены:", date_entry, "📝 05.2023 или 12.01.2023г.")
        ctrl(1, "Номер запчасти:", part_entry)
        ctrl(2, "Тип оборудования:", type_combo)
        ctrl(3, "Модель оборудования:", model_entry)
        ctrl(4, "Производитель:", maker_entry, "💡 начните вводить — список отфильтруется")
        ctrl(5, "Вид работ:", work_combo)
        ctrl(6, "Причина замены:", reason_entry)
        ctrl(7, "ФИО руководителя:", boss_entry)

        # === Графы ремонтного журнала (см. core.repair_journal) ===
        journal_entries = {}
        for row, (key, label, hint) in enumerate(repair_journal.FORM_FIELDS,
                                                 start=8):
            entry = tk.Entry(body, width=34)
            journal_entries[key] = entry
            ctrl(row, f"{label}:", entry, hint)

        # === Влияние записи на срок службы ===
        effect_frame = tk.LabelFrame(
            window, text="🔄 Влияние на срок службы (выберите заменённый объект)",
            font=("Arial", 10, "bold"), padx=10, pady=6)
        effect_frame.pack(fill=tk.X, padx=12, pady=(4, 0))

        equipment = [e for e in self.db.get_equipment_by_grp(grp_id) if not e[3]]
        eq_by_name = {e[1]: e for e in equipment}
        eq_names = [e[1] for e in equipment]
        removed_eq = {}
        if is_edit and repl[9]:
            # При редактировании записи о полной замене исходное оборудование
            # уже снято — показываем его в списке, иначе выбор не восстановится.
            old = next((e for e in self.db.get_equipment_by_grp(grp_id)
                        if e[0] == repl[9] and e[3]), None)
            if old and old[1] not in eq_by_name:
                label = f'{old[1]} (снято {old[3]})'
                removed_eq[label] = old
                equipment.append((old[0], label, old[2], old[3]))
                eq_by_name[label] = old
                eq_names.append(label)

        eq_combo = ttk.Combobox(effect_frame, width=32, values=eq_names, state="readonly")
        part_combo = ttk.Combobox(effect_frame, width=32, state="readonly")
        part_choice = {}          # подпись запчасти → (part_id, part_number, is_replaceable, norm)
        eff_var = tk.StringVar(value='')

        tk.Label(effect_frame, text="Оборудование:", font=("Arial", 9)).grid(
            row=0, column=0, sticky=tk.E, padx=(0, 4), pady=3)
        eq_combo.grid(row=0, column=1, sticky=tk.W, pady=3)
        tk.Label(effect_frame, text="Запчасть:", font=("Arial", 9)).grid(
            row=1, column=0, sticky=tk.E, padx=(0, 4), pady=3)
        part_combo.grid(row=1, column=1, sticky=tk.W, pady=3)
        tk.Label(effect_frame, text="Что сделать со сроком:",
                 font=("Arial", 9)).grid(row=2, column=0, sticky=tk.E, padx=(0, 4), pady=3)

        effects = tk.Frame(effect_frame)
        effects.grid(row=2, column=1, sticky=tk.W, pady=3)
        eff_none = tk.Radiobutton(effects, text="только журнал",
                                  variable=eff_var, value='', font=("Arial", 9))
        eff_part = tk.Radiobutton(effects, text="сбросить срок запчасти",
                                  variable=eff_var, value='part', font=("Arial", 9))
        eff_eq = tk.Radiobutton(effects, text="заменить оборудование целиком",
                                variable=eff_var, value='equipment', font=("Arial", 9))
        eff_none.pack(side=tk.LEFT, padx=(0, 10))
        eff_part.pack(side=tk.LEFT, padx=(0, 10))
        eff_eq.pack(side=tk.LEFT)

        effect_hint = tk.Label(effect_frame, text="", font=("Arial", 8),
                               fg="#546E7A", anchor=tk.W, justify=tk.LEFT)
        effect_hint.grid(row=3, column=0, columnspan=2, sticky=tk.W, pady=(2, 0))

        # Остаточный ресурс после ремонта приложение знает само: сброс срока
        # запчасти возвращает ей нормативный срок, полная замена оборудования —
        # назначенный срок службы новой единицы. Значение подставляется в поле
        # на виду (auto_residual помнит подставленное, чтобы не затирать
        # вписанное вручную) и сохраняется только вместе с записью.
        auto_residual = {'value': ''}
        residual_entry = journal_entries['residual_after']

        def suggested_residual() -> str:
            effect = eff_var.get()
            if effect == 'part':
                choice = part_choice.get(part_combo.get())
                return repair_journal.residual_after(
                    'part', choice[3] if choice else None)
            if effect == 'equipment':
                eq = eq_by_name.get(eq_combo.get())
                return repair_journal.residual_after(
                    'equipment',
                    assigned_life=equipment_card.value(eq, 'assigned_life') if eq else '')
            return ''

        def refresh_residual(*_args):
            current = residual_entry.get().strip()
            if current and current != auto_residual['value']:
                return               # значение вписано вручную — не трогаем
            suggested = suggested_residual()
            if suggested != current:
                residual_entry.delete(0, tk.END)
                if suggested:
                    residual_entry.insert(0, suggested)
            auto_residual['value'] = suggested

        def update_hint(*_args):
            refresh_residual()
            effect = eff_var.get()
            if effect == '':
                effect_hint.config(text="Срок службы не изменится — запись попадёт только в журнал.")
            elif effect == 'part':
                part_name = part_combo.get()
                choice = part_choice.get(part_name)
                if not choice:
                    effect_hint.config(text="⚠️ Выберите запчасть — без неё сбросить срок нечего.")
                elif not choice[2]:
                    effect_hint.config(
                        text=f"⚠️ «{part_name}» не заменяемая: сброс срока возможен, "
                             "но запчасть не относится к расходным.")
                else:
                    effect_hint.config(
                        text=f"✅ Срок «{part_name}» ({years_to_text(choice[3])}) "
                             "будет отсчитываться заново с даты замены.")
            else:
                eq = eq_by_name.get(eq_combo.get())
                if not eq:
                    effect_hint.config(text="⚠️ Выберите оборудование.")
                elif eq[3]:
                    effect_hint.config(
                        text=f"ℹ «{eq[1]}» уже снято с эксплуатации "
                             f"{eq[3]} — повторная замена не выполняется.")
                else:
                    n = len([p for p in self.db.get_equipment_parts_full(eq[0]) if not p[5]])
                    effect_hint.config(
                        text=f"✅ Оборудование «{eq[1]}» будет снято {date_entry.get().strip() or '—'}, "
                             f"создано новое, сроки всех {n} запчастей — заново.")

        def active_parts(eq):
            """Активные запчасти оборудования: подпись → (part_id, номер, заменяемая, норма)."""
            found = {}
            if not eq:
                return found
            for _ep_id, pid, name, norm, _inst, removal, pnum, is_repl in \
                    self.db.get_equipment_parts_full(eq[0]):
                if removal:
                    continue
                found[f"{name}" + (f" · {pnum}" if pnum else "")] = (
                    pid, pnum or "", is_repl, norm)
            return found

        def on_eq_change(_event=None):
            eq = eq_by_name.get(eq_combo.get())
            found = active_parts(eq)
            part_choice.clear()
            part_choice.update(found)
            part_combo.configure(values=list(found))
            part_combo.set('')
            if eq and not model_entry.get().strip():
                model_entry.insert(0, eq[1])
                type_combo.set(self._equipment_type_by_model(eq[1]))
            update_hint()

        eq_combo.bind('<<ComboboxSelected>>', on_eq_change)
        part_combo.bind('<<ComboboxSelected>>', update_hint)
        for var in (eff_var,):
            var.trace_add('write', update_hint)
        date_entry.bind('<KeyRelease>', update_hint)

        if is_edit:
            date_entry.insert(0, repl[1] or "")
            part_entry.insert(0, repl[2] or "")
            type_combo.set(repl[3] or "")
            model_entry.insert(0, repl[4] or "")
            maker_entry.set(repl[5] or "")
            work_combo.set(repl[6] or "")
            reason_entry.insert(0, repl[7] or "")
            boss_entry.insert(0, repl[8] or "")
            for key, text in repair_journal.form_values(repl).items():
                if text:
                    journal_entries[key].insert(0, text)
            eq_id, part_id, effect = repl[9], repl[10], repl[11]
            if eq_id:
                eq = next((e for e in equipment if e[0] == eq_id), None)
                if eq:
                    eq_combo.set(eq[1])
                    on_eq_change()
            if part_id and not eq_id:
                # привязка только к запчасти: ищем оборудование, где она установлена
                for cand in equipment:
                    if any(c[0] == part_id for c in active_parts(cand).values()):
                        eq_combo.set(cand[1])
                        on_eq_change()
                        break
            for label, choice in part_choice.items():
                if choice[0] == part_id:
                    part_combo.set(label)
                    break
            eff_var.set(effect or '')
        update_hint()

        def save():
            effect = eff_var.get()
            eq = eq_by_name.get(eq_combo.get())
            part_id = part_number = None
            if effect == 'part':
                choice = part_choice.get(part_combo.get())
                if not choice:
                    messagebox.showerror(
                        "Ошибка",
                        "Выбран режим «сбросить срок запчасти», но запчасть не указана.\n\n"
                        "Выберите запчасть в списке или переключите режим на «только журнал».")
                    return
                part_id, part_number, _is_repl, _norm = choice
                part_entry.delete(0, tk.END)
                part_entry.insert(0, part_number)
            elif effect == 'equipment':
                if not eq:
                    messagebox.showerror(
                        "Ошибка",
                        "Выбран режим «заменить оборудование целиком», "
                        "но оборудование не указано.")
                    return
                model_entry.delete(0, tk.END)
                model_entry.insert(0, eq[1])
                type_combo.set(self._equipment_type_by_model(eq[1]))

            date_text = date_entry.get().strip()
            iso = self._to_iso_date(date_text)
            if effect in ('part', 'equipment') and not iso:
                messagebox.showerror(
                    "Ошибка",
                    "Для сброса срока нужна дата в формате ДД.ММ.ГГГГ или ММ.ГГГГ.")
                return
            eq_id = eq[0] if eq else None

            # Графы ремонтного журнала: остаточный ресурс проверяется так же,
            # как назначенный срок службы в паспорте единицы.
            journal = {key: entry.get().strip()
                       for key, entry in journal_entries.items()}
            try:
                journal['residual_after'] = repair_journal.parse_residual(
                    journal['residual_after'])
            except DurationError as e:
                messagebox.showerror("Ошибка", str(e), parent=window)
                return

            # Дату храним в ISO: откат эффекта сопоставляет её с install_date.
            data = (
                iso or date_text or None,
                part_entry.get().strip() or None,
                type_combo.get().strip() or None,
                model_entry.get().strip() or None,
                maker_entry.get().strip() or None,
                work_combo.get().strip() or None,
                reason_entry.get().strip() or None,
                boss_entry.get().strip() or None,
            )

            prev_effect = (repl[11] or '') if is_edit else ''
            prev_eq = repl[9] if is_edit else None
            prev_part = repl[10] if is_edit else None
            prev_date = (repl[1] or '') if is_edit else ''
            prev_new_eq = repl[12] if is_edit else None
            # Правка текста не должна заново менять физическое состояние:
            # переустановка выполняется только если действие реально изменилось.
            unchanged = (is_edit and effect == prev_effect and eq_id == prev_eq
                         and part_id == prev_part
                         and (iso or date_text) == prev_date)
            apply_effect = effect in ('part', 'equipment') and not unchanged

            if effect == 'equipment' and apply_effect:
                active = [p for p in self.db.get_equipment_parts_full(eq_id) if not p[5]]
                if not messagebox.askyesno(
                        "Подтверждение замены оборудования",
                        f"Оборудование «{eq[1]}» будет полностью заменено {date_text}.\n\n"
                        f"Оно и все его запчасти ({len(active)} шт.) будут сняты с "
                        f"эксплуатации {date_text}, будет создано новое оборудование, "
                        f"и срок службы каждой запчасти начнётся заново.\n\n"
                        f"Прежняя история запчастей сохранится. Продолжить?"):
                    return
            new_eq_id = None
            try:
                if apply_effect and effect == 'equipment' and eq[3]:
                    messagebox.showerror(
                        "Ошибка",
                        f"Оборудование «{eq[1]}» уже снято с эксплуатации {eq[3]}.\n\n"
                        "Повторную замену выполнить нельзя. Удалите прежнюю запись "
                        "о замене, если нужно вернуть срок службы.")
                    return
                reverted = ''
                if is_edit and not unchanged and prev_effect in ('part', 'equipment'):
                    reverted = self.db.revert_replacement_effect(repl[0])
                if effect == 'part' and apply_effect:
                    self.db.replace_equipment_part(eq_id, part_id, iso)
                elif effect == 'equipment' and apply_effect:
                    new_eq_id = self.db.replace_equipment_completely(
                        eq_id, iso, add_journal=False)
                if is_edit:
                    self.db.update_replacement(
                        repl[0], *data, equipment_id=eq_id, part_id=part_id,
                        effect=effect, new_equipment_id=(new_eq_id or prev_new_eq),
                        clear_links=(effect == ''),
                        extras=repair_journal.extras(journal))
                else:
                    self.db.add_replacement(
                        grp_id, *data, equipment_id=eq_id, part_id=part_id,
                        effect=effect, new_equipment_id=new_eq_id,
                        extras=repair_journal.extras(journal))
                window.destroy()
                self.load_replacements()
                self.load_home()
                self.sync_excel(silent=True)
                notes = {
                    '': "срок не изменён",
                    'part': f"срок запчасти отсчитывается заново с {date_text}",
                    'equipment': f"оборудование заменено {date_text}, сроки заново",
                }
                extra = f" ({reverted})" if reverted else ""
                extra += " — прежняя замена не применялась повторно" if unchanged else ""
                self.statusbar.config(
                    text=f"Замена сохранена, Excel обновлён — {notes[effect]}{extra}")
            except Exception as e:
                messagebox.showerror("Ошибка", str(e))

        btn_frame = tk.Frame(window)
        btn_frame.pack(pady=10)
        self._btn(btn_frame, "💾 Сохранить", save, color='success', font_size=10, padx=20).pack(side=tk.LEFT, padx=10)
        self._btn(btn_frame, "❌ Отмена", window.destroy, color='danger', font_size=10, padx=20).pack(side=tk.LEFT, padx=10)
        fit_window(window, min_width=760, min_height=760)

    def add_replacement(self):
        """Кнопка «➕ Добавить замену» журнала замен — всплывающее окно замены.

        Запись в журнал создаётся вместе с самой заменой: окно сначала
        выбирает оборудование и запчасть, поэтому отдельной формы «только
        запись в журнал» для новой замены нет — она осталась при
        редактировании существующей записи («✏ Редактировать»).
        """
        grp = self._current_grp()
        if grp is None:
            return
        self._replace_part_dialog(grp[0], grp[1])

    def _replace_part_dialog(self, grp_id: int, grp_name: str):
        """Всплывающее окно замены запчасти по выбранному ГРП.

        Окно открывается кнопкой внутри журнала замен, поэтому оно именно
        всплывающее, а не отдельный экран. После сохранения окно остаётся
        открытым: список запчастей перечитывается, и подряд можно оформить
        несколько замен.
        """
        window = Toplevel(self.root)
        window.title(f"🔧 Замена запчасти — ГРП {grp_name}")
        window.configure(bg="#ffffff")

        holder = tk.Frame(window, bg="#ffffff")
        holder.pack(fill=tk.BOTH, expand=True)

        def rebuild():
            for child in holder.winfo_children():
                child.destroy()
            self._build_replace_part(holder, grp_id, grp_name,
                                     on_close=window.destroy,
                                     on_rebuild=rebuild)

        rebuild()
        fit_window(window, min_width=980, min_height=600)
        window.transient(self.root)

    @staticmethod
    def _to_iso_date(value: str) -> Optional[str]:
        """'ГГГГ-ММ-ДД' / 'ДД.ММ.ГГГГ' / 'ММ.ГГГГ' → 'ГГГГ-ММ-ДД'."""
        value = (value or '').strip()
        m = re.match(r'^(\d{4})-(\d{1,2})-(\d{1,2})', value)
        if m:
            year, month, day = m.group(1), int(m.group(2)), int(m.group(3))
            return f'{year}-{month:02d}-{day:02d}'
        m = re.match(r'^(\d{1,2})[.\-](\d{1,2})[.\-](\d{2,4})', value)
        if m:
            day, month, year = int(m.group(1)), int(m.group(2)), m.group(3)
            if len(year) == 2:
                year = '20' + year
            return f'{year}-{month:02d}-{day:02d}'
        m = re.match(r'^(\d{1,2})[.\-](\d{2,4})$', value)
        if m:
            month, year = int(m.group(1)), m.group(2)
            if len(year) == 2:
                year = '20' + year
            return f'{year}-{month:02d}-01'
        return None

    @staticmethod
    def _equipment_type_by_model(model: str) -> str:
        low = (model or '').lower()
        if 'пск' in low or 'сбросн' in low:
            return 'ПСК'
        if 'пзк' in low or 'запорн' in low:
            return 'ПЗК'
        if 'фильтр' in low:
            return 'Фильтр'
        return 'Регулятор'

    def _build_replace_part(self, frame, grp_id: int, grp_name: str,
                            on_close=None, on_rebuild=None):
        """Содержимое замены запчасти: оборудование, его запчасти, запись в журнал.

        Собирается в переданный контейнер: сейчас это всплывающее окно,
        поэтому закрытие и пересборку содержимого задаёт вызывающий код.
        """
        tk.Label(frame, text=f"🔧 Замена запасной части\nГРП #{grp_id}: {grp_name}",
                 font=("Arial", 12, "bold")).pack(pady=6)

        equipment = self.db.get_equipment_by_grp(grp_id)
        if not equipment:
            tk.Label(frame, text="У ГРП нет оборудования — заменять нечего.",
                     font=("Arial", 11), fg="#6c757d").pack(pady=20)
            self._btn(frame, "✖ Закрыть", on_close or self.view_repairs,
                      color='danger', font_size=10, padx=20).pack(pady=8)
            return

        main = tk.Frame(frame)
        main.pack(fill=tk.BOTH, expand=True, padx=10, pady=4)
        main.grid_columnconfigure(0, weight=1)
        main.grid_columnconfigure(1, weight=2)
        main.grid_rowconfigure(0, weight=1)

        # === Слева: список оборудования ===
        left = tk.LabelFrame(main, text="📦 Оборудование",
                             font=("Arial", 10, "bold"), padx=6, pady=4)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 4))

        eq_tree = self._scroll_table(
            left, ("n", "d"), {"n": 230, "d": 90}, height=12,
            headings={"n": "Наименование", "d": "Установлено"})

        # === Справа: запчасти оборудования ===
        right = tk.LabelFrame(main, text="🔩 Запчасти оборудования",
                              font=("Arial", 10, "bold"), padx=6, pady=4)
        right.grid(row=0, column=1, sticky="nsew")

        cols = ("№", "Запчасть", "Обозначение", "Замен.", "Норма")
        widths = {"№": 45, "Запчасть": 200, "Обозначение": 110, "Замен.": 55,
                  "Норма": 90}
        parts_tree = self._scroll_table(right, cols, widths, height=12)

        # === Форма: запись о замене (журнал) ===
        form = tk.LabelFrame(frame, text="📝 Запись о замене (журнал)",
                             font=("Arial", 10, "bold"), padx=10, pady=6)
        form.pack(fill=tk.X, padx=10, pady=4)

        sel_info = tk.Label(form, text="",
                            font=("Arial", 9, "bold"), fg="#546E7A", anchor=tk.W)
        sel_info.grid(row=0, column=0, columnspan=6, sticky=tk.W, pady=(0, 6))

        def fctrl(row, col, label, widget):
            tk.Label(form, text=label, font=("Arial", 9)).grid(row=row, column=col, sticky=tk.E, padx=(4, 2), pady=3)
            widget.grid(row=row, column=col + 1, sticky=tk.W, padx=(0, 8), pady=3)

        date_entry = tk.Entry(form, width=12)
        date_entry.insert(0, datetime.now().strftime('%d.%m.%Y'))
        work_combo = ttk.Combobox(form, width=22, values=WORK_TYPES)
        reason_entry = tk.Entry(form, width=32)
        boss_entry = tk.Entry(form, width=28)

        # Графы ремонтного журнала (см. core.repair_journal). Остаточный
        # ресурс подставляется по выбранной запчасти на виду и правится вручную.
        journal_entries = {key: tk.Entry(form, width=24)
                           for key, _label, _hint in repair_journal.FORM_FIELDS}
        auto_residual = {'value': ''}

        fctrl(1, 0, "Дата замены:", date_entry)
        fctrl(1, 2, "Вид работ:", work_combo)
        fctrl(2, 0, "Причина:", reason_entry)
        fctrl(2, 2, "ФИО руководителя:", boss_entry)
        fctrl(3, 0, "Наработка до замены:",
              journal_entries['hours_before'])
        fctrl(3, 2, "Остаточный ресурс, лет:",
              journal_entries['residual_after'])
        fctrl(4, 0, "Документ-основание:", journal_entries['document'])
        fctrl(4, 2, "Примечание:", journal_entries['note'])

        def refresh_residual(*_args):
            """Подставить остаточный ресурс, пока его не вписали вручную."""
            entry = journal_entries['residual_after']
            current = entry.get().strip()
            if current and current != auto_residual['value']:
                return
            suggested = ''
            sel = parts_tree.selection()
            if sel and int(sel[0]) in parts:
                suggested = repair_journal.residual_after(
                    'part', parts[int(sel[0])][3])
            if suggested != current:
                entry.delete(0, tk.END)
                if suggested:
                    entry.insert(0, suggested)
            auto_residual['value'] = suggested

        parts = {}
        current_eq = {"row": None}

        def load_equipment_parts(eq):
            current_eq["row"] = eq
            for row in parts_tree.get_children():
                parts_tree.delete(row)
            parts.clear()
            full = self.db.get_equipment_parts_full(eq[0])
            number = 0
            for ep in full:
                if ep[5]:  # снятая запись (история) — не показываем
                    continue
                number += 1
                ep_id, part_id, name, norm, p_install, _removal, pnum, is_repl = ep
                parts[ep_id] = (eq, part_id, name, norm, pnum or "", is_repl)
                # Идентификатор записи — в iid строки: в графах его нет.
                parts_tree.insert('', tk.END, iid=str(ep_id), values=(
                    number, name, pnum or "", "✓" if is_repl else "—",
                    years_to_text(norm)))

        def on_equipment_select(_event=None):
            sel = eq_tree.selection()
            if not sel:
                return
            eq = equipment[eq_tree.index(sel[0])]
            load_equipment_parts(eq)
            self.statusbar.config(text=f"Замена запчасти: оборудование «{eq[1]}»")

        def on_part_select(_event=None):
            sel = parts_tree.selection()
            if not sel:
                return
            ep_id = int(sel[0])
            eq, _pid, _name, _norm, pnumber, is_repl = parts[ep_id]
            sel_info.config(text=f"Выбрано: {_name}  ·  обозначение: {pnumber or '—'}  ·  оборудование: {eq[1]}")
            refresh_residual()
            self.statusbar.config(text=f"Запчасть «{_name}» — {'заменяемая ✓' if is_repl else 'НЕ заменяемая'}")

        eq_tree.bind('<<TreeviewSelect>>', on_equipment_select)
        parts_tree.bind('<<TreeviewSelect>>', on_part_select)

        for eq in equipment:
            eq_tree.insert('', tk.END, values=(eq[1], eq[2] or "—"))
        if equipment:
            eq_tree.selection_set(eq_tree.get_children()[0])
            load_equipment_parts(equipment[0])

        def save():
            sel = parts_tree.selection()
            if not sel:
                messagebox.showwarning("Внимание", "Сначала выберите запчасть в списке!")
                return
            ep_id = int(sel[0])
            eq, part_id, name, norm, pnumber, is_repl = parts[ep_id]
            if not is_repl:
                messagebox.showerror(
                    "Ошибка",
                    f"Запчасть «{name}» НЕ заменяемая.\n\n"
                    "Заменять можно только запчасти, отмеченные «✓» "
                    "(в «Запчастях оборудования» кнопка «🔄 Заменяемая»).")
                return
            num = pnumber
            date_input = date_entry.get().strip()
            iso = self._to_iso_date(date_input)
            if not iso:
                messagebox.showerror("Ошибка", "Неверная дата. Формат: ДД.ММ.ГГГГ или ММ.ГГГГ")
                return
            journal = {key: entry.get().strip()
                       for key, entry in journal_entries.items()}
            try:
                journal['residual_after'] = repair_journal.parse_residual(
                    journal['residual_after'])
            except DurationError as e:
                messagebox.showerror("Ошибка", str(e), parent=frame)
                return
            data = (
                date_input or None,
                num or None,
                self._equipment_type_by_model(eq[1]),
                eq[1],
                None,
                work_combo.get().strip() or None,
                reason_entry.get().strip() or None,
                boss_entry.get().strip() or None,
            )
            try:
                self.db.replace_equipment_part(eq[0], part_id, iso)
                self.db.add_replacement(grp_id, *data,
                                        equipment_id=eq[0], part_id=part_id,
                                        effect='part',
                                        extras=repair_journal.extras(journal))
                load_equipment_parts(eq)
                self.load_home()
                self.load_replacements()
                self.sync_excel(silent=True)
                self.statusbar.config(text=f"Замена «{name}» от {date_input} — новый срок {years_to_text(norm)}")
                messagebox.showinfo("✅ Замена выполнена",
                                    f"Запчасть «{name}» заменена на такую же новую.\n\n"
                                    f"Дата установки (замены): {date_input}\n"
                                    f"Новый срок службы: {years_to_text(norm)} — снова с этой даты.")
            except Exception as e:
                messagebox.showerror("Ошибка", str(e))

        def replace_whole_equipment():
            """Полная замена оборудования: сроки всех его запчастей — заново."""
            sel = eq_tree.selection()
            if not sel:
                messagebox.showwarning("Внимание", "Сначала выберите оборудование!")
                return
            eq = equipment[eq_tree.index(sel[0])]
            eq_id = eq[0]

            date_input = date_entry.get().strip()
            iso = self._to_iso_date(date_input)
            if not iso:
                messagebox.showerror("Ошибка", "Неверная дата. Формат: ДД.ММ.ГГГГ или ММ.ГГГГ")
                return

            active = [p for p in self.db.get_equipment_parts_full(eq_id)
                      if not p[5]]
            norm_list = '\n'.join(
                f'  • {p[2]} — {years_to_text(p[3])} (срок заново с {date_input})'
                for p in active) or '  • состав запчастей не заполнен'

            if not messagebox.askyesno(
                    "Подтверждение полной замены",
                    f"Оборудование «{eq[1]}» будет полностью заменено "
                    f"{date_input}.\n\n"
                    f"Прежнее оборудование и все его запчасти будут сняты "
                    f"с эксплуатации этой датой. Будет создано новое "
                    f"оборудование с датой установки {date_input}, и срок службы "
                    f"каждой запчасти начнётся заново:\n\n{norm_list}\n\n"
                    f"Прежняя история запчастей сохранится. Продолжить?"):
                return

            try:
                new_id = self.db.replace_equipment_completely(
                    eq_id, iso, add_journal=False)
                journal = {key: entry.get().strip()
                           for key, entry in journal_entries.items()}
                # Остаточный ресурс после полной замены — назначенный срок
                # службы новой единицы: паспорт при замене переносится.
                journal['residual_after'] = repair_journal.residual_after(
                    'equipment',
                    assigned_life=equipment_card.value(eq, 'assigned_life'))
                self.db.add_replacement(
                    grp_id, date_input, 'полная замена оборудования',
                    self._equipment_type_by_model(eq[1]), eq[1], None,
                    work_combo.get().strip() or 'Замена',
                    reason_entry.get().strip() or None,
                    boss_entry.get().strip() or None,
                    equipment_id=eq_id, effect='equipment',
                    new_equipment_id=new_id,
                    extras=repair_journal.extras(journal))
                self.load_home()
                self.load_replacements()
                self.sync_excel(silent=True)
                self.statusbar.config(
                    text=f"Оборудование «{eq[1]}» полностью заменено "
                         f"{date_input} — сроки запчастей с новой даты")
                messagebox.showinfo(
                    "✅ Оборудование заменено",
                    f"«{eq[1]}» полностью заменено {date_input}.\n\n"
                    f"Прежнее оборудование и его запчасти сняты с эксплуатации.\n"
                    f"Создано новое оборудование с датой установки "
                    f"{date_input}.\n\n"
                    f"Срок службы всех {len(active)} запчастей отсчитывается заново "
                    f"от этой даты.")
                # Состав оборудования изменился — содержимое собирается заново,
                # чтобы в списках были уже новые единицы и запчасти.
                if on_rebuild is not None:
                    on_rebuild()
            except Exception as e:
                messagebox.showerror("Ошибка", str(e))

        btn_frame = tk.Frame(frame)
        btn_frame.pack(pady=8)
        self._btn(btn_frame, "💾 Заменить запчасть", save, color='success', font_size=10, padx=20).pack(side=tk.LEFT, padx=8)
        self._btn(btn_frame, "🔄 Заменить оборудование полностью",
                  replace_whole_equipment, color='primary', font_size=10,
                  padx=20).pack(side=tk.LEFT, padx=8)
        self._btn(btn_frame, "✖ Закрыть", on_close or self.view_repairs, color='danger', font_size=10, padx=20).pack(side=tk.LEFT, padx=8)

    def edit_replacement(self):
        grp = self._current_grp()
        if grp is None:
            return
        selected = self.repairs_tree.selection()
        if not selected:
            messagebox.showwarning("Внимание", "Выберите замену из списка!")
            return
        repl_id = int(selected[0])
        # Полная запись из БД: в Treeview нет equipment_id/part_id/effect,
        # без них редактирование записи сбросила бы метку влияния на срок.
        record = self.db.get_replacement(repl_id)
        if not record:
            messagebox.showerror("Ошибка", f"Запись #{repl_id} не найдена в базе.")
            return
        self._replacement_dialog(grp[0], grp[1], record)

    def delete_replacement(self):
        selected = self.repairs_tree.selection()
        if not selected:
            messagebox.showwarning("Внимание", "Выберите замену из списка!")
            return
        values = self.repairs_tree.item(selected[0])['values']
        repl_id = int(selected[0])
        # Номера граф считаются по описанию журнала, а не пишутся числом:
        # порядок граф задан заказчиком и может меняться.
        number = values[0]
        part_number = values[repair_journal.table_index('part')]
        # Влияние записи на срок в таблице не показывается: для предупреждения
        # оно берётся из самой записи.
        record = self.db.get_replacement(repl_id)
        effect = (repair_journal.value(record, 'effect',
                                       repair_journal.RECORD_COLUMNS)
                  if record else '')

        question = f"Удалить замену №{number} '{part_number}'?"
        if effect:
            question += ("\n\nЗапись сбрасывала срок службы, и срок будет "
                         "восстановлен на прежний.")
        if not messagebox.askyesno("Подтверждение", question):
            return
        try:
            restored = self.db.revert_replacement_effect(repl_id)
        except AttributeError:
            restored = ''
        self.db.delete_replacement(repl_id)
        self.load_replacements()
        self.load_home()
        self.sync_excel(silent=True)
        note = f", {restored}" if restored else ""
        self.statusbar.config(
            text=f"Замена №{number} ('{part_number}') удалена{note}, Excel обновлён")

    # === РАЗДЕЛ «ИНФОРМАЦИЯ ПО ОТКАЗАМ» ===

    def setup_failures_tab(self):
        """Экран «Информация по отказам»: список отказов текущего ГРП."""
        select_frame = tk.Frame(self.failures_tab)
        select_frame.pack(pady=10)

        tk.Label(select_frame, text="Текущий ГРП:", font=("Arial", 10, "bold")).pack(side=tk.LEFT, padx=5)
        self.failures_grp_label = tk.Label(select_frame, text="—", font=("Arial", 10, "bold"), fg="#546E7A")
        self.failures_grp_label.pack(side=tk.LEFT, padx=8)

        self._btn(select_frame, "➕ Добавить отказ", self.add_failure, color='success', font_size=9, padx=10).pack(side=tk.LEFT, padx=5)
        self._btn(select_frame, "✏ Редактировать", self.edit_failure, color='warning', font_size=9, padx=10).pack(side=tk.LEFT, padx=5)
        self._btn(select_frame, "🗑 Удалить", self.delete_failure, color='danger', font_size=9, padx=10).pack(side=tk.LEFT, padx=5)
        self._btn(select_frame, "📷 Открыть фото", self.open_failure_photo, color='info', font_size=9, padx=10).pack(side=tk.LEFT, padx=5)

        table_frame = tk.LabelFrame(self.failures_tab, text="Информация по отказам",
                                    padx=10, pady=10)
        table_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Графы и их порядок — в core.failure_log: тот же список читает строка
        # выборки, поэтому подписи и порядок не разъезжаются.
        columns = ("№",) + tuple(label for _key, label, _width
                                 in failure_log.TABLE_COLUMNS)
        col_widths = {"№": 38}
        col_widths.update({label: width for _key, label, width
                           in failure_log.TABLE_COLUMNS})
        self.failures_tree = self._scroll_table(table_frame, columns,
                                                col_widths, height=12)

        tk.Label(self.failures_tab,
                 text="💡 Отказы хранятся в БД по каждому ГРП.\n"
                      "В примечания вписывают номер акта и рекомендации, а снимок "
                      "прикладывают кнопкой — фото хранится вместе с записью.",
                 fg="#6c757d", font=("Arial", 9), justify=tk.CENTER).pack(pady=5)

    def load_failures(self):
        """Заполнить таблицу отказов текущего ГРП (свежие сверху)."""
        grp = self._current_grp()
        if grp is None:
            return None
        grp_id, grp_name = grp[0], grp[1]
        self.failures_grp_label.config(text=grp_name)

        for row in self.failures_tree.get_children():
            self.failures_tree.delete(row)

        rows = self.db.get_failures_by_grp(grp_id)
        for number, row in enumerate(rows, start=1):
            # Идентификатор записи — в iid строки: в графах его нет, первой
            # графой идёт номер записи.
            self.failures_tree.insert('', tk.END, iid=str(row[0]),
                                      values=[number] + failure_log.table_cells(row))

        photos = sum(1 for row in rows if failure_log.has_photo(row))
        extra = f", с фото: {photos}" if photos else ""
        self.statusbar.config(
            text=f"Отказы ГРП «{grp_name}» (#{grp_id}): {len(rows)} записей{extra}")
        return grp_id

    def _selected_failure(self):
        """Запись об отказе, выбранная в таблице (или None с предупреждением)."""
        selected = self.failures_tree.selection()
        if not selected:
            messagebox.showwarning("Внимание", "Выберите отказ из списка!")
            return None
        return int(selected[0])

    def add_failure(self):
        """Кнопка «➕ Добавить отказ»: всплывающее окно новой записи."""
        grp = self._current_grp()
        if grp is None:
            return
        self._failure_dialog(grp[0], grp[1])

    def edit_failure(self):
        """Кнопка «✏ Редактировать»: правка выбранной записи об отказе."""
        grp = self._current_grp()
        if grp is None:
            return
        failure_id = self._selected_failure()
        if failure_id is None:
            return
        # Запись берётся из базы целиком: в таблице нет отметки о фото, без
        # неё правка потеряла бы приложенный снимок.
        record = self.db.get_failure(failure_id)
        if not record:
            messagebox.showerror("Ошибка", f"Запись #{failure_id} не найдена в базе.")
            return
        self._failure_dialog(grp[0], grp[1], record)

    def delete_failure(self):
        """Кнопка «🗑 Удалить»: удаление выбранного отказа вместе с фото."""
        selected = self.failures_tree.selection()
        if not selected:
            messagebox.showwarning("Внимание", "Выберите отказ из списка!")
            return
        failure_id = int(selected[0])
        # Номера граф считаются по описанию отказов, а не пишутся числом:
        # порядок граф задан заказчиком и может меняться.
        values = self.failures_tree.item(selected[0])['values']
        number = values[0]
        event = values[failure_log.table_index('event_type')]
        if not messagebox.askyesno(
                "Подтверждение",
                f"Удалить отказ №{number} «{event}»?\n\n"
                f"Приложенное фото будет удалено вместе с записью."):
            return
        self.db.delete_failure(failure_id)
        self.load_failures()
        self.statusbar.config(text=f"Отказ №{number} ('{event}') удалён")

    def open_failure_photo(self):
        """Кнопка «📷 Открыть фото»: показать снимок выбранного отказа."""
        failure_id = self._selected_failure()
        if failure_id is None:
            return
        data = self.db.get_failure_photo(failure_id)
        if not data:
            messagebox.showinfo("Фото", "К этому отказу фото не приложено.")
            return
        self._open_attached(data, failure_id)
        self.statusbar.config(
            text=f"Фото отказа №{self.failures_tree.item(str(failure_id))['values'][0]} "
                 f"открыто во внешней программе")

    @staticmethod
    def _open_attached(data: bytes, failure_id: int) -> str:
        """Показать приложенный файл во внешней программе.

        Фото хранится в базе, а система открывает файл с диска и по
        расширению выбирает программу. Поэтому на время просмотра данные
        пишутся во временный файл, а расширение определяется по содержимому:
        имя приложенного файла в базе не хранится.
        """
        path = os.path.join(
            tempfile.gettempdir(),
            f'grp_failure_{failure_id}{failure_log.photo_extension(data)}')
        with open(path, 'wb') as handle:
            handle.write(data)
        os.startfile(path)          # Windows: открыть программой по умолчанию
        return path

    def _failure_dialog(self, grp_id: int, grp_name: str,
                        record: Optional[tuple] = None):
        """Окно добавления/редактирования отказа. record — строка из БД или None."""
        window = Toplevel(self.root)
        window.title(f"Отказ — ГРП {grp_name}")
        window.transient(self.root)
        window.grab_set()

        is_edit = record is not None
        failure_id = record[0] if is_edit else None
        title = "✏ Редактирование отказа" if is_edit else "➕ Добавление отказа"
        tk.Label(window, text=f"{title}\nГРП #{grp_id}: {grp_name}",
                 font=("Arial", 12, "bold"), fg="#546E7A").pack(pady=10)

        body = tk.Frame(window)
        body.pack(fill=tk.BOTH, expand=True, padx=12)

        # Поля строятся по описанию отказов (core.failure_log): подписи,
        # порядок и виды полей заданы там же, где графы таблицы.
        current = failure_log.form_values(record) if is_edit else {}
        entries = {}
        for row, (key, label, kind, hint) in enumerate(failure_log.FORM_FIELDS):
            tk.Label(body, text=f"{label}:", font=("Arial", 10)).grid(
                row=row, column=0, sticky=tk.W, pady=5)
            if kind == 'criticality':
                widget = ttk.Combobox(body, width=32, state='readonly',
                                      values=('',) + failure_log.CRITICALITY_LEVELS)
            elif kind == 'yes_no':
                widget = ttk.Combobox(body, width=32, state='readonly',
                                      values=('',) + failure_log.YES_NO)
            elif kind == 'choice':
                widget = ttk.Combobox(body, width=32,
                                      values=failure_log.EVENT_TYPES)
            else:
                widget = tk.Entry(body, width=34)
            text = current.get(key, '')
            if not is_edit and key == 'document':
                text = failure_log.DEFAULT_DOCUMENT
            if isinstance(widget, ttk.Combobox):
                widget.set(text)
            else:
                widget.insert(0, text)
            widget.grid(row=row, column=1, sticky=tk.W, pady=5)
            tk.Label(body, text=hint, font=("Arial", 8),
                     fg="#6c757d").grid(row=row, column=2, sticky=tk.W, padx=6)
            entries[key] = widget

        # === Фото записи ===
        # Байты читаются из базы только при показе и при сохранении: держать
        # снимок в памяти формы незачем, а 'changed' отмечает, что его
        # тронули, — иначе сохранение текста перезаписало бы фото пустотой.
        photo = {'data': None, 'changed': False}
        photo_frame = tk.LabelFrame(window, text="📷 Фото отказа",
                                    font=("Arial", 10, "bold"), padx=10, pady=6)
        photo_frame.pack(fill=tk.X, padx=12, pady=(8, 0))

        def photo_state() -> str:
            if photo['changed']:
                data = photo['data']
                if data is None:
                    return 'фото будет убрано'
                return f'приложено ({len(data) // 1024 + 1} КБ) — сохранится с записью'
            if is_edit and failure_log.has_photo(record):
                return 'фото приложено'
            return 'фото не приложено'

        photo_label = tk.Label(photo_frame, text=photo_state(),
                               font=("Arial", 9), fg="#546E7A")

        def attach_photo():
            path = filedialog.askopenfilename(
                title="Выберите фото отказа", parent=window,
                filetypes=[("Изображения", "*.png *.jpg *.jpeg *.gif *.bmp *.webp"),
                           ("Скан акта (PDF)", "*.pdf"),
                           ("Все файлы", "*.*")])
            if not path:
                return
            try:
                with open(path, 'rb') as handle:
                    data = handle.read()
            except OSError as e:
                messagebox.showerror("Ошибка",
                                     f"Не удалось прочитать файл:\n{e}",
                                     parent=window)
                return
            photo['data'] = data
            photo['changed'] = True
            photo_label.config(text=photo_state())

        def remove_photo():
            attached = (photo['data'] is not None if photo['changed']
                        else bool(is_edit and failure_log.has_photo(record)))
            if not attached:
                messagebox.showinfo("Фото", "К отказу фото не приложено.",
                                    parent=window)
                return
            photo['data'] = None
            photo['changed'] = True
            photo_label.config(text=photo_state())

        def view_photo():
            if photo['changed']:
                data = photo['data']
            else:
                data = self.db.get_failure_photo(failure_id) if is_edit else None
            if not data:
                messagebox.showinfo("Фото", "К отказу фото не приложено.",
                                    parent=window)
                return
            self._open_attached(data, failure_id or 0)

        self._btn(photo_frame, "📷 Приложить фото", attach_photo,
                  color='info', font_size=9, padx=8).pack(side=tk.LEFT, padx=4)
        self._btn(photo_frame, "👁 Посмотреть", view_photo,
                  color='info', font_size=9, padx=8).pack(side=tk.LEFT, padx=4)
        self._btn(photo_frame, "🗑 Убрать фото", remove_photo,
                  color='danger', font_size=9, padx=8).pack(side=tk.LEFT, padx=4)
        photo_label.pack(side=tk.LEFT, padx=10)

        def save():
            entered = {key: widget.get().strip()
                       for key, widget in entries.items()}
            # Слова в графах проверяются: «средняя (устранено)» в графе
            # критичности неотличимо от описки.
            try:
                entered['event_type'] = failure_log.parse_event(entered['event_type'])
                entered['criticality'] = failure_log.parse_criticality(
                    entered['criticality'])
                entered['resolved'] = failure_log.parse_resolved(entered['resolved'])
            except failure_log.FailureError as e:
                messagebox.showerror("Ошибка", str(e), parent=window)
                return
            # Дату храним в ISO: по ней список показывает свежие отказы сверху.
            raw_date = entered['detected_date']
            entered['detected_date'] = self._to_iso_date(raw_date) or raw_date

            values = failure_log.values(entered)
            try:
                if is_edit:
                    self.db.update_failure(failure_id, values)
                    target = failure_id
                else:
                    target = self.db.add_failure(grp_id, values)
                if photo['changed']:
                    self.db.set_failure_photo(target, photo['data'])
            except Exception as e:
                messagebox.showerror("Ошибка", str(e), parent=window)
                return

            window.destroy()
            self.load_failures()
            note = ""
            if photo['changed']:
                note = ", фото приложено" if photo['data'] else ", фото убрано"
            self.statusbar.config(
                text=f"{'Отказ изменён' if is_edit else 'Отказ добавлен'}"
                     f" — ГРП «{grp_name}»{note}")

        btn_frame = tk.Frame(window)
        btn_frame.pack(pady=10)
        self._btn(btn_frame, "💾 Сохранить", save, color='success',
                  font_size=10, padx=20).pack(side=tk.LEFT, padx=10)
        self._btn(btn_frame, "❌ Отмена", window.destroy, color='danger',
                  font_size=10, padx=20).pack(side=tk.LEFT, padx=10)
        fit_window(window, min_width=820, min_height=580)

    def sync_excel(self, silent: bool = False):
        """Перезаписать файл «Замены.xlsx» из БД."""
        try:
            filename = excel_sync.sync_replacements_workbook(self.db)
            self.statusbar.config(text=f"Excel обновлён: {os.path.basename(filename)}")
            return filename
        except Exception as e:
            msg = f"Не удалось обновить файл Excel:\n{e}"
            if silent:
                self.statusbar.config(text=f"⚠️ {msg}")
            else:
                messagebox.showwarning("Excel", msg)
            return None

    def _build_excel_sync(self, frame):
        """Экран обновления файла «Замены.xlsx»."""
        path = excel_sync.default_filename()
        card = tk.LabelFrame(frame, text="📤 Обновить файл Excel",
                             font=("Arial", 10, "bold"), padx=14, pady=10)
        card.pack(fill=tk.X, padx=12, pady=12)

        tk.Label(card, text="Листы «Ремонт …» пересоздаются из базы: по листу "
                            "на каждый рабочий ГРП.",
                 font=("Arial", 11, "bold"), fg="#546E7A", anchor=tk.W).pack(anchor=tk.W)
        tk.Label(card, text=f"Файл: {path}", font=("Arial", 9), fg="#6c757d",
                 anchor=tk.W, wraplength=860, justify=tk.LEFT).pack(anchor=tk.W, pady=(6, 2))
        tk.Label(card, text="Посторонние листы файла сохраняются; каталог "
                            "оборудования в файл не пишется.",
                 font=("Arial", 9), fg="#6c757d", anchor=tk.W).pack(anchor=tk.W)

        self._excel_status = tk.Label(card, text="", font=("Arial", 10, "bold"),
                                      fg="#546E7A", anchor=tk.W)
        self._excel_status.pack(anchor=tk.W, pady=(8, 0))

        def run():
            filename = self.sync_excel()
            self._excel_status.config(
                text=(f"✅ Обновлено: {os.path.basename(filename)}"
                      if filename else "⚠️ Не удалось обновить файл"),
                fg="#2E7D32" if filename else "#C62828")

        buttons = tk.Frame(frame)
        buttons.pack(fill=tk.X, padx=12, pady=6)
        self._btn(buttons, "📤 Обновить файл Excel", run, color='indigo',
                  font_size=10, padx=20).pack(side=tk.LEFT)

    def view_excel_sync(self):
        """Экран синхронизации журнала замен с файлом Excel."""
        self._dynamic_view('excel', self._build_excel_sync)
        self.show_view('excel')
        self.statusbar.config(text="Обновление файла Excel")

    def setup_tech_tab(self):
        select_frame = tk.Frame(self.tech_tab)
        select_frame.pack(pady=10)

        tk.Label(select_frame, text="Текущий ГРП:", font=("Arial", 10, "bold")).pack(side=tk.LEFT, padx=5)
        self.tech_grp_label = tk.Label(select_frame, text="—", font=("Arial", 10, "bold"), fg="#546E7A")
        self.tech_grp_label.pack(side=tk.LEFT, padx=8)

        self._btn(select_frame, "📊 Загрузить историю", self.load_tech_history, color='primary', font_size=9, padx=10).pack(side=tk.LEFT, padx=5)
        self._btn(select_frame, "🔧 Новая диагностика", self.add_tech_diagnostic, color='success', font_size=9, padx=10).pack(side=tk.LEFT, padx=5)

        table_frame = tk.LabelFrame(self.tech_tab, text="История технических диагностирований", padx=10, pady=10)
        table_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        columns = ("№", "Дата", "A", "B", "C", "K", "n", "u", "m", "r")
        col_widths = {"№": 40, "Дата": 120, "A": 60, "B": 60, "C": 60, "K": 80, "n": 40, "u": 40, "m": 40, "r": 40}
        self.tech_tree = self._scroll_table(table_frame, columns, col_widths, height=8)

        # Информационная панель
        info_frame = tk.LabelFrame(self.tech_tab, text="Формула расчета K = 1 - (A + B + C)", padx=10, pady=5)
        info_frame.pack(fill=tk.X, padx=10, pady=10)

        formula_text = """
        📌 A - Коэффициент узла редуцирования и фильтров (0 или 0.1)
        📌 B - Коэффициент прочего оборудования = min(0.1; n/u)
        📌 C - Коэффициент разъемных соединений = min(0.1; m/r)

        n - количество оборудования с неисправностями | u - общее количество оборудования
        m - количество соединений с утечками | r - общее количество соединений

        В диагностировании A выбирается из списка, n — отметкой неисправного
        оборудования из списка ГРП, u считается автоматически,
        m и r выбираются стрелками.
        """

        tk.Label(info_frame, text=formula_text, justify=tk.LEFT, font=("Arial", 9), fg="#495057").pack(fill=tk.X)

    def _save_equipment(self, grp_id: int, items) -> tuple:
        """Записать набранное в форме ГРП оборудование.

        Возвращает (единиц оборудования, привязанных запчастей): запчасти
        берутся из каталога по названию модели, дальше их срок считает расчёт.
        """
        linked = 0
        for item in items:
            equip_id = self.db.add_equipment(
                grp_id, item['name'], item['install_date'],
                item.get('removal_date') or None,
                details=equipment_card.details(item))
            linked += self._auto_link_parts_from_catalog(equip_id, item['name'])
        return len(items), linked

    def _sync_equipment(self, grp_id: int, items, original) -> str:
        """Привести состав оборудования ГРП к набранному в форме правки.

        original — оборудование на момент открытия формы. Убранное оборудование
        удаляется только после подтверждения: вместе с ним уходит его состав
        запчастей.
        """
        originals = {row[0]: row for row in original}
        kept, added, changed = set(), 0, 0
        for item in items:
            equip_id = item['id']
            row = originals.get(equip_id)
            if row is None:
                new_id = self.db.add_equipment(
                    grp_id, item['name'], item['install_date'],
                    item.get('removal_date') or None,
                    details=equipment_card.details(item))
                self._auto_link_parts_from_catalog(new_id, item['name'])
                added += 1
                continue
            kept.add(equip_id)
            was = (row[1], row[2], row[3] or None, equipment_card.values(row))
            now = (item['name'], item['install_date'],
                   item.get('removal_date') or None, equipment_card.details(item))
            if now != was:
                self.db.update_equipment(
                    equip_id, item['name'], item['install_date'],
                    item.get('removal_date') or None,
                    details=equipment_card.details(item))
                changed += 1

        removed = [row for row in original if row[0] not in kept]
        if removed:
            names = "\n".join(f"• {row[1]}" for row in removed)
            if messagebox.askyesno(
                    "Подтверждение",
                    f"Убрать из ГРП оборудование:\n{names}\n\n"
                    f"Вместе с ним удалится его состав запчастей."):
                for row in removed:
                    self.db.delete_equipment(row[0])
            else:
                removed = []

        done = []
        if added:
            done.append(f"добавлено: {added}")
        if changed:
            done.append(f"изменено: {changed}")
        if removed:
            done.append(f"убрано: {len(removed)}")
        return ", ".join(done) if done else "состав не изменился"

    def _build_grp_form(self, frame, grp_data=None):
        """Форма ГРП в основном окне: паспорт и состав оборудования.

        grp_data — строка ГРП из базы при редактировании, None при создании:
        этим различаются только подписи, начальные значения полей и то, что
        делает «Сохранить». Оборудование набирается здесь же — отдельного
        пункта «Добавить оборудование» в меню нет.
        """
        editing = grp_data is not None
        grp_id = grp_data[0] if editing else None
        values = grp_passport.values(grp_data) if editing else {}

        # Кнопки прижаты к низу и упакованы раньше формы: на низком экране
        # режется тогда список оборудования, а не «Сохранить».
        btn_frame = tk.Frame(frame)
        btn_frame.pack(side=tk.BOTTOM, pady=14)

        tk.Label(frame, text=(f"✏ Редактирование ГРП #{grp_id}" if editing
                              else "🏗️ Новый ГРП"),
                 font=("Arial", 14, "bold"), fg="#546E7A").pack(pady=(14, 8))

        form = tk.Frame(frame)
        form.pack(padx=16, pady=6)

        def field(row, label, width=20, initial=''):
            tk.Label(form, text=label, font=("Arial", 10)).grid(
                row=row, column=0, sticky=tk.W, pady=5)
            entry = tk.Entry(form, width=width)
            if initial:
                entry.insert(0, initial)
            entry.grid(row=row, column=1, pady=5)
            return entry

        type_entry = field(0, "Тип ГРП:", 35, grp_data[1] if editing else '')
        lines_entry = field(1, "Количество линий:",
                            initial=str(grp_data[2]) if editing else '')
        actual_entry = field(2, "Фактический срок:",
                             initial=years_to_text(grp_data[3]) if editing else '')
        design_entry = field(3, "Проектный срок:",
                             initial=years_to_text(grp_data[4]) if editing else '')

        tk.Label(form, text="срок можно ввести как «7 лет 4 мес», «7,3» или просто «7,3 года»",
                 font=("Arial", 8), fg="#6c757d").grid(row=4, column=0, columnspan=4,
                                                       sticky=tk.W, pady=(0, 4))

        tk.Label(form, text="Сведения о ГРП (паспорт объекта)",
                 font=("Arial", 11, "bold"), fg="#546E7A").grid(
            row=5, column=0, columnspan=4, sticky=tk.W, pady=(12, 2))
        passport_widgets = _grp_passport_form(form, start_row=6, values=values)

        original = self.db.get_equipment_by_grp(grp_id) if editing else []
        equipment_editor = EquipmentListEditor(
            self, form, grid_row=6 + _grp_passport_rows())
        equipment_editor.load([equipment_card.form_item(row)
                               for row in original])

        def read_fields():
            """Поля формы → (тип, линии, факт. срок, проект. срок) или None."""
            grp_type = type_entry.get().strip()
            if not grp_type:
                messagebox.showerror("Ошибка", "Введите тип ГРП!")
                return None
            try:
                lines = int(lines_entry.get().strip())
            except ValueError:
                messagebox.showerror("Ошибка", "Количество линий — целое число!")
                return None
            return (grp_type, lines,
                    parse_years_strict(actual_entry.get(), "фактический срок"),
                    parse_years_strict(design_entry.get(), "проектный срок"))

        def save():
            try:
                fields = read_fields()
                if fields is None:
                    return
                grp_type, lines, actual, design = fields
                passport = _grp_passport_values(passport_widgets)

                if editing:
                    self.db.update_grp(grp_id, grp_type, lines, actual, design,
                                       passport=passport)
                    done = self._sync_equipment(grp_id, equipment_editor.values(),
                                                original)
                    messagebox.showinfo("Успех",
                                        f"✅ ГРП обновлён!\nОборудование — {done}")
                    self.set_current_grp(grp_id)
                    self.statusbar.config(text=f"ГРП #{grp_id} обновлён")
                    return

                new_id = self.db.add_grp(grp_type, lines, actual, design,
                                         passport=passport)
                units, linked = self._save_equipment(new_id, equipment_editor.values())
                self.set_current_grp(new_id)
                self.statusbar.config(text=f"Добавлен ГРП: {grp_type}")
                messagebox.showinfo(
                    "Успех",
                    f"✅ ГРП добавлен и выбран!\n\n"
                    f"Фактический срок: {years_to_text(actual)}\n"
                    f"Проектный срок: {years_to_text(design)}\n"
                    f"Оборудование: {units} шт., запчастей из каталога: {linked}")
            except DurationError as e:
                messagebox.showerror("Ошибка", str(e))
            except Exception as e:
                messagebox.showerror("Ошибка", str(e))

        self._btn(btn_frame, "💾 Сохранить", save, color='success',
                  font_size=10, padx=20).pack(side=tk.LEFT, padx=10)
        self._btn(btn_frame, "✖ Закрыть", self._back_to_grp,
                  color='danger', font_size=10, padx=20).pack(side=tk.LEFT, padx=10)

    def _back_to_grp(self):
        """Вернуться с формы ГРП на рабочий экран."""
        self.show_view("grp")
        self.load_home()

    def add_grp(self):
        """Экран создания ГРП."""
        self._dynamic_view('grp_new', lambda frame: self._build_grp_form(frame),
                           scroll=True)
        self.show_view('grp_new')
        self.statusbar.config(text="Новый ГРП: заполните поля и состав оборудования")

    def edit_grp(self):
        """Экран редактирования выбранного ГРП."""
        grp = self._current_grp()
        if grp is None:
            return
        grp_data = self.db.get_grp_by_id(grp[0])
        if not grp_data:
            messagebox.showerror("Ошибка", f"ГРП #{grp[0]} не найден в базе")
            return
        self._dynamic_view('grp_edit',
                           lambda frame: self._build_grp_form(frame, grp_data),
                           scroll=True)
        self.show_view('grp_edit')
        self.statusbar.config(text=f"Редактирование ГРП «{grp[1]}»")

    def delete_grp(self):
        """Экран удаления ГРП."""
        if self._current_grp() is None:
            return
        self._dynamic_view('grp_delete',
                           lambda frame: self._build_grp_list(frame, 'delete'))
        self.show_view('grp_delete')
        self.statusbar.config(text="Удаление ГРП: выберите ГРП из списка")

    def view_equipment(self):
        """Показать оборудование и запчасти в главном окне (выбранный ГРП)."""
        if self._current_grp() is None:
            return
        self.show_view("grp")
        self.load_home()
        self.statusbar.config(text=f"Оборудование и запчасти ГРП «{self.current_grp_name}»")

    def _export_grp_word(self, grp_id: int, grp_name: str):
        """Диалог сохранения и сборка .docx по текущему ГРП."""
        filename = filedialog.asksaveasfilename(
            defaultextension=".docx",
            filetypes=[("Word документы", "*.docx")],
            initialfile="Отчёт_ГРП.docx"
        )
        if not filename:
            return

        try:
            saved = word_report_pg.generate_grp_docx(
                self.db, grp_id, grp_name, filename, params=self.calc_params)
            messagebox.showinfo("Успех", f"Отчёт по ГРП «{grp_name}» сохранён:\n{saved}")
            self.statusbar.config(text=f"Word-отчёт по ГРП {grp_name} сохранён")
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось сформировать отчёт:\n{e}")

    def _build_report(self, frame, grp_id: int, grp_name: str):
        """Экран отчёта: что попадёт в документ, и кнопка его сборки."""
        card = tk.LabelFrame(frame, text="📏 Отчёт по ГРП (Word)",
                             font=("Arial", 10, "bold"), padx=14, pady=10)
        card.pack(fill=tk.X, padx=12, pady=(12, 6))

        tk.Label(card, text=f"ГРП «{grp_name}»  (ID={grp_id})",
                 font=("Arial", 13, "bold"), fg="#546E7A", anchor=tk.W).pack(anchor=tk.W)

        equipment = self.db.get_equipment_by_grp(grp_id)
        labels = ' и '.join(algo_label(number)
                            for number in word_report_pg.FORM62_ALGORITHMS)
        rows = [
            ("Раздел", "1 Сведения о ГРП — паспорт объекта, как он заполнен в карточке"),
            ("Раздел", f"2 Результаты расчёта по форме 6.2 — {labels}"),
            ("Оборудование", f"{len(equipment)} ед."),
            ("Замены в журнале", f"{self.db.count_replacements_by_grp(grp_id)}"),
            ("Коэффициенты расчёта",
             "заданы в окне расчёта" if self.calc_params is not None
             else "рекомендуемые методикой"),
        ]
        for name, value in rows:
            line = tk.Frame(card)
            line.pack(fill=tk.X, pady=1)
            tk.Label(line, text=name + ':', font=("Arial", 9, "bold"),
                     width=20, anchor=tk.W).pack(side=tk.LEFT)
            tk.Label(line, text=value, font=("Arial", 9), anchor=tk.W,
                     wraplength=760, justify=tk.LEFT).pack(side=tk.LEFT)

        tk.Label(card,
                 text="Коэффициенты берутся те же, что показаны в «Расчёте "
                      "алгоритмов»: экран и документ считаются одним и тем же "
                      "ядром и не расходятся.",
                 font=("Arial", 8), fg="#6c757d", anchor=tk.W,
                 justify=tk.LEFT, wraplength=860).pack(anchor=tk.W, pady=(8, 0))

        buttons = tk.Frame(frame)
        buttons.pack(fill=tk.X, padx=12, pady=6)
        self._btn(buttons, "📄 Сформировать Word-отчёт",
                  lambda: self._export_grp_word(grp_id, grp_name),
                  color='success', font_size=10, padx=20).pack(side=tk.LEFT)
        self._btn(buttons, "✖ Закрыть", self._back_to_grp, color='danger',
                  font_size=10, padx=20).pack(side=tk.LEFT, padx=8)

    def view_report(self):
        """Экран формирования Word-отчёта по выбранному ГРП."""
        grp = self._current_grp()
        if grp is None:
            return
        self._dynamic_view(
            'report', lambda frame: self._build_report(frame, grp[0], grp[1]))
        self.show_view('report')
        self.statusbar.config(text=f"Отчёт по ГРП «{grp[1]}»")

    def add_tech_diagnostic(self):
        grp = self._current_grp()
        if grp is None:
            return
        grp_id = grp[0]

        # Оборудование в работе: из него выбираются неисправности (n)
        # и автоматически берётся общее количество (u).
        active = [e for e in self.db.get_equipment_by_grp(grp_id) if not e[3]]
        u_count = len(active)
        if not u_count:
            messagebox.showinfo(
                "Информация",
                "У ГРП нет оборудования в эксплуатации — диагностирование не выполняется")
            return

        window = Toplevel(self.root)
        window.title("Техническое диагностирование")
        window.transient(self.root)
        window.grab_set()

        tk.Label(window, text="🔧 Техническое диагностирование",
                 font=("Arial", 14, "bold"), fg="#546E7A").pack(pady=10)

        frame = tk.Frame(window)
        frame.pack(pady=10, fill=tk.BOTH, expand=True)

        # --- A: выбор из списка, ввод вручную не требуется
        tk.Label(frame, text="Коэффициент A — узел редуцирования и фильтры:",
                 font=("Arial", 10)).grid(row=0, column=0, columnspan=2, sticky=tk.W)
        A_CHOICES = ("0 — замечаний нет", "0.1 — есть замечания")
        a_var = tk.StringVar(value=A_CHOICES[0])
        a_box = ttk.Combobox(frame, textvariable=a_var, values=A_CHOICES,
                             state="readonly", width=36)
        a_box.grid(row=1, column=0, sticky=tk.W, pady=(2, 12))

        def _a() -> float:
            return float(a_var.get().split(" — ")[0])

        # --- n: отметка неисправного оборудования из списка
        tk.Label(frame, text="n — отметьте оборудование с неисправностями "
                             "(Ctrl для выбора нескольких):",
                 font=("Arial", 10)).grid(row=2, column=0, columnspan=2, sticky=tk.W)

        list_frame = tk.Frame(frame)
        list_frame.grid(row=3, column=0, columnspan=2, sticky=tk.W, pady=5)
        eq_list = tk.Listbox(list_frame, selectmode=tk.MULTIPLE, width=60, height=8,
                             font=("Arial", 9), exportselection=False, bd=1, relief="solid")
        eq_scroll = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=eq_list.yview)
        eq_list.configure(yscrollcommand=eq_scroll.set)
        eq_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        eq_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        for eq in active:
            eq_list.insert(tk.END, str(eq[1]))

        marks = tk.Frame(frame)
        marks.grid(row=4, column=0, columnspan=2, sticky=tk.W)
        self._btn(marks, "Отметить все", lambda: eq_list.selection_set(0, tk.END),
                  color='neutral', font_size=8, padx=8).pack(side=tk.LEFT, padx=(0, 6))
        self._btn(marks, "Снять отметки", lambda: eq_list.selection_clear(0, tk.END),
                  color='neutral', font_size=8, padx=8).pack(side=tk.LEFT)

        # --- u: считается само, вручную не вводится
        tk.Label(frame, text=f"u — всего оборудования в работе: {u_count}",
                 font=("Arial", 10, "bold"), fg="#546E7A").grid(
            row=5, column=0, columnspan=2, sticky=tk.W, pady=(12, 5))

        # --- m и r: выбор стрелками
        tk.Label(frame, text="m — разъёмных соединений с утечками:",
                 font=("Arial", 10)).grid(row=6, column=0, sticky=tk.W, pady=4)
        m_var = tk.StringVar(value="0")
        ttk.Spinbox(frame, from_=0, to=999, textvariable=m_var,
                    width=12).grid(row=6, column=1, sticky=tk.W, pady=4)

        tk.Label(frame, text="r — всего разъёмных соединений:",
                 font=("Arial", 10)).grid(row=7, column=0, sticky=tk.W, pady=4)
        r_var = tk.StringVar(value=str(u_count))
        ttk.Spinbox(frame, from_=0, to=999, textvariable=r_var,
                    width=12).grid(row=7, column=1, sticky=tk.W, pady=4)

        # --- живой пересчёт: выбор сразу виден в результате
        preview = tk.Label(frame, text="", font=("Consolas", 10, "bold"),
                           fg="#37474F", justify=tk.LEFT)
        preview.grid(row=8, column=0, columnspan=2, sticky=tk.W, pady=(14, 0))

        analyzer = self.tech_analyzer

        def _ints(strict: bool = False):
            try:
                return int(m_var.get() or 0), int(r_var.get() or 0)
            except ValueError:
                if strict:
                    raise ValueError("m и r должны быть целыми числами")
                return 0, 0

        def refresh(*_args):
            m, r = _ints()
            n = len(eq_list.curselection())
            b = analyzer.calculate_coefficient_b(n, u_count)
            c = analyzer.calculate_coefficient_c(m, r)
            k = analyzer.calculate_coefficient_k(_a(), b, c)
            rating, _rec = analyzer.get_technical_condition_rating(k)
            preview.config(text=(
                f"K = 1 - ({_a()} + {b:.4f} + {c:.4f}) = {k:.4f}\n"
                f"n = {n}, u = {u_count}, m = {m}, r = {r}   →   {rating}"))

        eq_list.bind('<<ListboxSelect>>', refresh)
        a_box.bind('<<ComboboxSelected>>', refresh)
        m_var.trace_add('write', refresh)
        r_var.trace_add('write', refresh)
        refresh()

        def calculate_and_save():
            try:
                a = _a()
                m, r = _ints(strict=True)
                if r <= 0:
                    raise ValueError("r должно быть больше нуля")
                if m > r:
                    raise ValueError(f"m ({m}) не может быть больше r ({r})")
                n = len(eq_list.curselection())

                b = analyzer.calculate_coefficient_b(n, u_count)
                c = analyzer.calculate_coefficient_c(m, r)
                k = analyzer.calculate_coefficient_k(a, b, c)

                coef_data = {
                    'a': a,
                    'b': b,
                    'c': c,
                    'k': k,
                    'n': n,
                    'u': u_count,
                    'm': m,
                    'r': r,
                    'diagnosis_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }

                self.db.save_technical_coefficients(grp_id, coef_data)

                rating, rec = analyzer.get_technical_condition_rating(k)

                result_text = f"""
                ═══════════════════════════════════════
                РЕЗУЛЬТАТЫ ДИАГНОСТИРОВАНИЯ
                ═══════════════════════════════════════

                A = {a}
                B = {b:.4f}
                C = {c:.4f}
                K = 1 - ({a} + {b:.4f} + {c:.4f}) = {k:.4f}

                n = {n}, u = {u_count}, m = {m}, r = {r}

                Оценка состояния: {rating}
                Рекомендация: {rec}
                """

                messagebox.showinfo("Результаты", result_text, parent=window)
                window.destroy()
                self.load_tech_history()
                self.statusbar.config(text=f"Техническая диагностика для ГРП #{grp_id} выполнена")

            except Exception as e:
                messagebox.showerror("Ошибка", str(e), parent=window)

        btn_frame = tk.Frame(window)
        btn_frame.pack(pady=16)
        self._btn(btn_frame, "🧮 Рассчитать и сохранить", calculate_and_save, color='indigo', font_size=10, padx=20).pack(side=tk.LEFT, padx=10)
        self._btn(btn_frame, "❌ Отмена", window.destroy, color='danger', font_size=10, padx=20).pack(side=tk.LEFT, padx=10)
        fit_window(window, min_width=700, min_height=600)

    def load_tech_history(self):
        grp = self._current_grp()
        if grp is None:
            return
        grp_id = grp[0]
        grp_name = grp[1]
        self.tech_grp_label.config(text=grp_name)

        coefficients = self.db.get_technical_coefficients(grp_id)

        for row in self.tech_tree.get_children():
            self.tech_tree.delete(row)

        # (id, diagnosis_date, a, b, c, k, n, u, m, r)
        for number, coef in enumerate(coefficients, start=1):
            # Идентификатор записи — в iid строки: в графах его нет.
            self.tech_tree.insert('', tk.END, iid=str(coef[0]), values=(
                number,              # №
                coef[1],             # Дата
                coef[2],             # A
                f"{coef[3]:.4f}",    # B
                f"{coef[4]:.4f}",    # C
                f"{coef[5]:.4f}",    # K
                coef[6],             # n
                coef[7],             # u
                coef[8],             # m
                coef[9]              # r
            ))

        self.statusbar.config(text=f"Загружена история для ГРП #{grp_id}: {len(coefficients)} записей")

    # === РАЗДЕЛ «ТЕХНИЧЕСКОЕ ДИАГНОСТИРОВАНИЕ» (ПРОТОКОЛ ПРОВЕРОК) ===

    def setup_diagnostics_tab(self):
        """Экран «Техническое диагностирование»: протокол проверок текущего ГРП."""
        select_frame = tk.Frame(self.diagnostics_tab)
        select_frame.pack(pady=10)

        tk.Label(select_frame, text="Текущий ГРП:", font=("Arial", 10, "bold")).pack(side=tk.LEFT, padx=5)
        self.diagnostics_grp_label = tk.Label(select_frame, text="—", font=("Arial", 10, "bold"), fg="#546E7A")
        self.diagnostics_grp_label.pack(side=tk.LEFT, padx=8)

        self._btn(select_frame, "➕ Добавить проверку", self.add_diagnostic_check,
                  color='success', font_size=9, padx=10).pack(side=tk.LEFT, padx=5)
        self._btn(select_frame, "✏ Редактировать", self.edit_diagnostic_check,
                  color='warning', font_size=9, padx=10).pack(side=tk.LEFT, padx=5)
        self._btn(select_frame, "🗑 Удалить", self.delete_diagnostic_check,
                  color='danger', font_size=9, padx=10).pack(side=tk.LEFT, padx=5)

        table_frame = tk.LabelFrame(self.diagnostics_tab,
                                    text="Техническое диагностирование",
                                    padx=10, pady=10)
        table_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Графы и их порядок — в core.diagnostic_log: тот же список читает
        # строка выборки, поэтому подписи и порядок не разъезжаются.
        columns = ("№",) + tuple(label for _key, label, _width
                                 in diagnostic_log.TABLE_COLUMNS)
        col_widths = {"№": 38}
        col_widths.update({label: width for _key, label, width
                           in diagnostic_log.TABLE_COLUMNS})
        self.diag_tree = self._scroll_table(table_frame, columns, col_widths,
                                            height=12)

        tk.Label(self.diagnostics_tab,
                 text="💡 Запись — итог одной проверки одного параметра: «режим» — "
                      "значение параметра при проверке, «допуск мин/макс» — границы\n"
                      "по документации, «факт мин/макс» — что показала проверка.\n"
                      "Результат выводится по числам: факт в допуске — «норма», "
                      "вышел за границу — «отклонение от нормы».",
                 fg="#6c757d", font=("Arial", 9), justify=tk.CENTER).pack(pady=5)

    def load_diagnostics(self):
        """Заполнить таблицу проверок текущего ГРП (свежие сверху)."""
        grp = self._current_grp()
        if grp is None:
            return None
        grp_id, grp_name = grp[0], grp[1]
        self.diagnostics_grp_label.config(text=grp_name)

        for row in self.diag_tree.get_children():
            self.diag_tree.delete(row)

        rows = self.db.get_diagnostic_checks(grp_id)
        for number, row in enumerate(rows, start=1):
            # Идентификатор записи — в iid строки: в графах его нет, первой
            # графой идёт номер записи.
            self.diag_tree.insert('', tk.END, iid=str(row[0]),
                                  values=[number] + diagnostic_log.table_cells(row))

        self.statusbar.config(
            text=f"Техническое диагностирование ГРП «{grp_name}» (#{grp_id}): "
                 f"{len(rows)} записей")
        return grp_id

    def _selected_diagnostic_check(self):
        """Запись проверки, выбранная в таблице (или None с предупреждением)."""
        selected = self.diag_tree.selection()
        if not selected:
            messagebox.showwarning("Внимание", "Выберите проверку из списка!")
            return None
        return int(selected[0])

    def add_diagnostic_check(self):
        """Кнопка «➕ Добавить проверку»: всплывающее окно новой записи."""
        grp = self._current_grp()
        if grp is None:
            return
        self._diagnostic_check_dialog(grp[0], grp[1])

    def edit_diagnostic_check(self):
        """Кнопка «✏ Редактировать»: правка выбранной проверки."""
        grp = self._current_grp()
        if grp is None:
            return
        check_id = self._selected_diagnostic_check()
        if check_id is None:
            return
        record = self.db.get_diagnostic_check(check_id)
        if not record:
            messagebox.showerror("Ошибка",
                                 f"Запись #{check_id} не найдена в базе.")
            return
        self._diagnostic_check_dialog(grp[0], grp[1], record)

    def delete_diagnostic_check(self):
        """Кнопка «🗑 Удалить»: удаление выбранной проверки."""
        selected = self.diag_tree.selection()
        if not selected:
            messagebox.showwarning("Внимание", "Выберите проверку из списка!")
            return
        check_id = int(selected[0])
        # Номера граф считаются по описанию проверок, а не пишутся числом:
        # порядок граф задан заказчиком и может меняться.
        values = self.diag_tree.item(selected[0])['values']
        number = values[0]
        parameter = values[diagnostic_log.table_index('parameter')]
        if not messagebox.askyesno(
                "Подтверждение",
                f"Удалить проверку №{number} «{parameter}»?"):
            return
        self.db.delete_diagnostic_check(check_id)
        self.load_diagnostics()
        self.statusbar.config(
            text=f"Проверка №{number} ('{parameter}') удалена")

    def _diagnostic_check_dialog(self, grp_id: int, grp_name: str,
                                 record: Optional[tuple] = None):
        """Окно добавления/редактирования проверки. record — строка из БД или None."""
        window = Toplevel(self.root)
        window.title(f"Техническое диагностирование — ГРП {grp_name}")
        window.transient(self.root)
        window.grab_set()

        is_edit = record is not None
        check_id = record[0] if is_edit else None
        title = "✏ Редактирование проверки" if is_edit else "➕ Добавление проверки"
        tk.Label(window, text=f"{title}\nГРП #{grp_id}: {grp_name}",
                 font=("Arial", 12, "bold"), fg="#546E7A").pack(pady=10)

        body = tk.Frame(window)
        body.pack(fill=tk.BOTH, expand=True, padx=12)

        # Поля строятся по описанию проверок (core.diagnostic_log): подписи,
        # порядок и виды полей заданы там же, где графы таблицы.
        current = diagnostic_log.form_values(record) if is_edit else {}
        if is_edit:
            # В базе дата лежит в ISO (по ней список ставит свежие сверху), а
            # в форме показывается как в документах — и правится тоже.
            current['check_date'] = diagnostic_log.date_text(current['check_date'])
        labels = {key: label for key, label, _kind, _hint
                  in diagnostic_log.FORM_FIELDS}
        # Оборудование выбирается из состава ГРП, но список открытый: единицу
        # могли снять, а запись проверки должна читаться и после этого.
        equipment_values = tuple(row[1] for row
                                 in self.db.get_equipment_by_grp(grp_id))
        entries = {}
        pressure_vars = {}
        for row, (key, label, kind, hint) in enumerate(diagnostic_log.FORM_FIELDS):
            tk.Label(body, text=f"{label}:", font=("Arial", 10)).grid(
                row=row, column=0, sticky=tk.W, pady=5)
            text = current.get(key, '')
            if kind in ('equipment', 'choice'):
                widget = ttk.Combobox(
                    body, width=32,
                    values=(equipment_values if kind == 'equipment'
                            else diagnostic_log.PARAMETERS))
                widget.set(text)
            elif kind == 'result':
                widget = ttk.Combobox(body, width=32, state='readonly',
                                      values=('',) + diagnostic_log.RESULTS)
                widget.set(text)
            else:
                var = tk.StringVar(value=text)
                widget = tk.Entry(body, width=34, textvariable=var)
                if kind == 'pressure':
                    pressure_vars[key] = var
            widget.grid(row=row, column=1, sticky=tk.W, pady=5)
            tk.Label(body, text=hint, font=("Arial", 8),
                     fg="#6c757d").grid(row=row, column=2, sticky=tk.W, padx=6)
            entries[key] = widget

        # Результат подставляется по числам, но выбранный вручную не
        # переписывается: выход за допуск могли признать допустимым. Помним,
        # что именно вывела программа: пока в графе стоит её значение, его
        # можно пересчитать, а вписанное человеком — нет.
        auto = {'result': ''}
        if is_edit:
            stored = current.get('result', '')
            if stored and stored == diagnostic_log.suggested_result(
                    current.get('tolerance_min'), current.get('tolerance_max'),
                    current.get('fact_min'), current.get('fact_max')):
                auto['result'] = stored

        def refresh_result(*_args):
            """Пересчитать результат по четырём числам в кПа."""
            suggested = diagnostic_log.suggested_result(
                *[pressure_vars[key].get()
                  for key in diagnostic_log.RESULT_FIELDS])
            shown = entries['result'].get()
            if shown and shown != auto['result']:
                return                      # выбрано вручную — не трогаем
            if shown != suggested:
                entries['result'].set(suggested)
            auto['result'] = suggested

        for var in pressure_vars.values():
            var.trace_add('write', refresh_result)

        tk.Label(window,
                 text="Результат: пока факт укладывается в допуск — «норма», "
                      "как только выходит за границу — «отклонение от нормы».",
                 fg="#6c757d", font=("Arial", 9), justify=tk.LEFT,
                 wraplength=680).pack(anchor=tk.W, padx=14, pady=(8, 0))

        def save():
            entered = {key: widget.get().strip()
                       for key, widget in entries.items()}
            # Числа в кПа и слова проверяются: описка в графе допуска
            # неотличима от значения, а по ней выводится результат.
            try:
                entered['parameter'] = diagnostic_log.parse_parameter(
                    entered['parameter'])
                for key in diagnostic_log.PRESSURE_FIELDS:
                    entered[key] = diagnostic_log.parse_pressure(
                        entered[key], labels[key])
                entered['result'] = diagnostic_log.parse_result(
                    entered['result'])
            except diagnostic_log.DiagnosticError as e:
                messagebox.showerror("Ошибка", str(e), parent=window)
                return
            # Дату храним в ISO: по ней список показывает свежие проверки сверху.
            raw_date = entered['check_date']
            entered['check_date'] = self._to_iso_date(raw_date) or raw_date

            values = diagnostic_log.values(entered)
            try:
                if is_edit:
                    self.db.update_diagnostic_check(check_id, values)
                else:
                    self.db.add_diagnostic_check(grp_id, values)
            except Exception as e:
                messagebox.showerror("Ошибка", str(e), parent=window)
                return

            window.destroy()
            self.load_diagnostics()
            self.statusbar.config(
                text=f"{'Проверка изменена' if is_edit else 'Проверка добавлена'}"
                     f" — ГРП «{grp_name}», {entered['parameter']}")

        btn_frame = tk.Frame(window)
        btn_frame.pack(pady=10)
        self._btn(btn_frame, "💾 Сохранить", save, color='success',
                  font_size=10, padx=20).pack(side=tk.LEFT, padx=10)
        self._btn(btn_frame, "❌ Отмена", window.destroy, color='danger',
                  font_size=10, padx=20).pack(side=tk.LEFT, padx=10)
        fit_window(window, min_width=820, min_height=560)

    def update_catalog_combo(self):
        """Обновление списка ГРП-каталогов в разделе «Каталог оборудования»."""
        grps = self.db.get_all_grp()
        catalog_grps = [g for g in grps if self._is_catalog_grp_name(g[1])]
        catalog_names = [f"{g[0]} - {g[1]}" for g in catalog_grps]
        if not catalog_names:
            catalog_names = [f"{g[0]} - {g[1]}" for g in grps]

        if hasattr(self, 'catalog_grp_combo'):
            default = next((n for n in catalog_names if 'каталог' in n.lower()),
                           catalog_names[0] if catalog_names else "")
            self.catalog_grp_combo['values'] = catalog_names
            self.catalog_grp_combo.set(default)
            self.load_catalog()

    def open_algorithms(self):
        """Показать расчёт по алгоритмам для выбранного ГРП в основном окне."""
        grp = self._current_grp()
        if grp is None:
            return

        grp_id, grp_name = grp[0], grp[1]
        equipment_data = self.db.get_equipment_by_grp(grp_id)

        if not equipment_data:
            messagebox.showinfo("Информация", "У данного ГРП нет оборудования для расчёта")
            return

        try:
            def build(frame):
                return AlgorithmsWindow(
                    self.root, self.db, grp_id, equipment_data, grp_name,
                    params=self.calc_params,
                    on_params=self._remember_calc_params,
                    container=frame, on_close=self._close_algorithms)

            self._dynamic_view('algorithms', build)
            self.show_view('algorithms')
            self.statusbar.config(text=f"Расчёт алгоритмов для ГРП: {grp_name}")
        except Exception as e:
            messagebox.showerror("Ошибка", f"Ошибка при открытии расчёта алгоритмов: {e}")

    def _close_algorithms(self):
        """Вернуться с расчёта на рабочий экран ГРП."""
        self.show_view("grp")
        self.load_home()

    def _remember_calc_params(self, params: AlgorithmParams):
        """Запомнить весовые коэффициенты, заданные в окне расчёта.

        Отчёт Word формируется с ними, иначе пользователь увидит в .docx
        числа, отличающиеся от только что посчитанных на экране.
        """
        self.calc_params = params