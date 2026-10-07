import os
import re
import tkinter as tk
from tkinter import ttk, messagebox, Toplevel, filedialog, scrolledtext
from datetime import datetime
from typing import List, Optional

from core.config import DB_CONFIG
from core import grp_passport
from core.models import Equipment
from core.timefmt import DurationError, parse_years_strict, years_to_text
from db.database_pg import DatabasePG
from integration import excel_sync, word_report_pg
from integration.pdf_parts_import import scan_pdf, import_to_db, create_catalog_equipment
from logic.algorithms import AlgorithmParams
from logic.documentary_analyzer import DocumentaryAnalyzer
from logic.technical_analyzer_pg import TechnicalAnalyzer

from .algorithms_view import AlgorithmsWindow
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
        ("➕ Добавить оборудование", "add_equipment", "grp"),
        ("🔩 Оборудование и запчасти", "view_equipment", "grp"),
        ("🛠 Замены (ремонт)", "view_repairs", "grp"),
        ("🔧 Замена запчасти", "replace_part", "grp"),
        ("📏 Отчёт по ГРП (Word)", "export_grp_word", "grp"),
        ("⚠️ Предупреждения", "show_warnings", "grp"),
        ("🧮 Расчёт алгоритмов", "open_algorithms", "grp"),
        ("🔧 Технические коэффициенты", "view_tech", "grp"),
    ]),
    ("Справочники", [
        ("📦 Каталог оборудования", "view_catalog", "always"),
        ("📂 Импорт из PDF-альбома", "import_catalog_pdf", "always"),
        ("📤 Обновить файл Excel", "sync_excel", "always"),
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


class GRPAppPG:
    """Главный класс приложения с PostgreSQL"""

    def __init__(self, root):
        self.root = root
        self.db = DatabasePG(DB_CONFIG)
        self.doc_analyzer = DocumentaryAnalyzer(self.db)
        self.tech_analyzer = TechnicalAnalyzer()
        self.current_grp_id: Optional[int] = None
        self.current_grp_name: str = ""
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
        self.tabs = {}
        views = [
            ("grp", "🏗️  Рабочее ГРП", self.setup_grp_tab),
            ("catalog", "📦  Каталог оборудования", self.setup_catalog_tab),
            ("tech", "🔧  Технические коэффициенты", self.setup_tech_tab),
            ("repairs", "🛠️  Замены (ремонт)", self.setup_replacements_tab),
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
        for _k, frame in self.tabs.items():
            frame.pack_forget()
        frame = self.tabs.get(key)
        if frame is not None:
            frame.pack(fill=tk.BOTH, expand=True)

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

    def choose_grp(self):
        """Окно выбора рабочего ГРП из списка."""
        grps = [g for g in self.db.get_all_grp() if not self._is_catalog_grp_name(g[1])]
        if not grps:
            messagebox.showinfo("Нет ГРП", "Список ГРП пуст.\nСоздайте ГРП через меню «Создать ГРП».")
            return

        window = Toplevel(self.root)
        window.title("Выбрать ГРП")
        window.transient(self.root)
        window.grab_set()

        tk.Label(window, text="🗂 Выбор рабочего ГРП",
                 font=("Arial", 13, "bold"), fg="#37474f").pack(pady=10)
        tk.Label(window, text="Двойной клик по строке — выбрать ГРП",
                 font=("Arial", 9), fg="#6c757d").pack()

        frame = tk.Frame(window)
        frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=8)

        columns = ("ID", "Тип ГРП", "Линии", "Факт. срок", "Проект. срок", "Оборудование", "Замены")
        tree = ttk.Treeview(frame, columns=columns, show="headings")
        widths = {"ID": 50, "Тип ГРП": 250, "Линии": 60, "Факт. срок": 80,
                  "Проект. срок": 80, "Оборудование": 90, "Замены": 70}
        for c in columns:
            tree.heading(c, text=c)
            tree.column(c, width=widths.get(c, 90))

        vsb = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        for g in grps:
            tree.insert('', tk.END, values=(
                g[0], g[1], g[2], years_to_text(g[3]), years_to_text(g[4]),
                len(self.db.get_equipment_by_grp(g[0])),
                self.db.count_replacements_by_grp(g[0]),
            ))

        def pick():
            sel = tree.selection()
            if not sel:
                messagebox.showwarning("Внимание", "Выберите ГРП из списка!")
                return
            grp_id = int(tree.item(sel[0])['values'][0])
            window.destroy()
            self.set_current_grp(grp_id)

        tree.bind('<Double-1>', lambda e: pick())

        buttons = tk.Frame(window)
        buttons.pack(pady=12)
        self._btn(buttons, "🗂 Выбрать", pick, color='primary', font_size=10, padx=20).pack(side=tk.LEFT, padx=10)
        self._btn(buttons, "❌ Отмена", window.destroy, color='danger', font_size=10, padx=20).pack(side=tk.LEFT, padx=10)
        fit_window(window, min_width=760, min_height=420)

    def show_help(self):
        """Справка для новых пользователей."""
        messagebox.showinfo(
            "❓ Справка",
            "Быстрый старт:\n\n"
            "1. Меню «☰» слева. Выберите пункт «🗂 Выбрать ГРП»\n"
            "   или создайте новый («➕ Создать ГРП»).\n"
            "2. Выбранный ГРП показывается вверху слева.\n"
            "3. Все действия в меню применяются к выбранному ГРП:\n"
            "   оборудование, замены, анализ, предупреждения, статистика.\n"
            "4. «Справочники» — каталог моделей оборудования и обновление Excel.\n"
            "5. Журнал замен автоматически пишется в файл «Замены.xlsx»."
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
        self._btn(equip_buttons, "➕ Добавить оборудование", self.add_equipment, color='success', font_size=9, padx=10).pack(side=tk.LEFT, padx=4)
        self._btn(equip_buttons, "🗑 Удалить оборудование", self._delete_selected_equipment, color='danger', font_size=9, padx=10).pack(side=tk.LEFT, padx=4)
        self._btn(equip_buttons, "🔍 Проверить по нормам", self._check_selected_norm, color='info', font_size=9, padx=10).pack(side=tk.LEFT, padx=4)

        # Остатка срока в списке нет: собственного срока у оборудования не
        # бывает, срок задают заменяемые запчасти, а по оборудованию проводится
        # полная проверка. Видны только даты установки и снятия.
        columns = ("ID", "Наименование", "Дата установки", "Дата снятия")
        self.home_tree = ttk.Treeview(equip_card, columns=columns, show="headings", height=7)
        widths = {"ID": 60, "Наименование": 440,
                  "Дата установки": 120, "Дата снятия": 150}
        for c in columns:
            self.home_tree.heading(c, text=c)
            self.home_tree.column(c, width=widths.get(c, 120))
        self.home_tree.pack(fill=tk.BOTH, expand=True)

        # === Запчасти выбранного оборудования ===
        self.parts_card = tk.LabelFrame(self.grp_tab, text="🔩 Запчасти выбранного оборудования",
                                        font=("Arial", 10, "bold"), padx=12, pady=8)
        self.parts_card.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 6))

        self.parts_buttons = tk.Frame(self.parts_card)
        self.parts_buttons.pack(fill=tk.X, pady=(0, 4))
        self._btn(self.parts_buttons, "➕ Добавить запчасть", self._add_part_to_selected, color='success', font_size=9, padx=10).pack(side=tk.LEFT, padx=4)
        self._btn(self.parts_buttons, "✏ Даты", self._edit_selected_part_dates, color='warning', font_size=9, padx=10).pack(side=tk.LEFT, padx=4)
        self._btn(self.parts_buttons, "✏ Норма", self._edit_selected_part_norm, color='warning', font_size=9, padx=10).pack(side=tk.LEFT, padx=4)
        self._btn(self.parts_buttons, "🔄 Заменяемая", self._toggle_selected_part_replaceable, color='info', font_size=9, padx=10).pack(side=tk.LEFT, padx=4)
        self._btn(self.parts_buttons, "🗑 Удалить из состава", self._remove_selected_part, color='danger', font_size=9, padx=10).pack(side=tk.LEFT, padx=4)

        self.parts_effective_label = tk.Label(self.parts_card, text="",
                                              font=("Arial", 10, "bold"), fg="#546E7A")
        self.parts_effective_label.pack(anchor=tk.W, pady=(0, 4))

        parts_frame = tk.Frame(self.parts_card)
        parts_frame.pack(fill=tk.BOTH, expand=True)

        pcolumns = ("ID", "Запчасть", "Обозначение", "Замен.", "Дата установки / замены")
        self.parts_tree = ttk.Treeview(parts_frame, columns=pcolumns, show="headings", height=7)
        pwidths = {"ID": 40, "Запчасть": 280, "Обозначение": 180, "Замен.": 55,
                   "Дата установки / замены": 160}
        for c in pcolumns:
            self.parts_tree.heading(c, text=c)
            self.parts_tree.column(c, width=pwidths.get(c, 100))

        pvsb = ttk.Scrollbar(parts_frame, orient=tk.VERTICAL, command=self.parts_tree.yview)
        self.parts_tree.configure(yscrollcommand=pvsb.set)
        self.parts_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        pvsb.pack(side=tk.RIGHT, fill=tk.Y)

        self.home_tree.bind('<<TreeviewSelect>>', self._on_home_select)
        self.home_tree.bind('<Double-1>', lambda e: self._select_equipment_parts())

    def _current_selected_equip(self):
        """Выбранное в главной таблице оборудование: (ep_id, name, install) или None."""
        sel = self.home_tree.selection()
        if not sel:
            return None
        values = self.home_tree.item(sel[0])['values']
        # values[2] — «Дата установки»: после удаления графы «Остаток срока»
        # индексы сдвинулись, и прежний values[3] отдавал дату снятия.
        return (int(values[0]), values[1], values[2])

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
        for ep in parts:
            if ep[5]:  # снятая запись (история замены) — в составе не показываем
                continue
            zam = "✓" if ep[7] else "—"
            has_replaceable = has_replaceable or bool(ep[7])
            # Срок запчасти считается от даты её установки, а если она не задана —
            # от даты установки оборудования.
            inst_date = ep[4] or equip_install
            self.parts_tree.insert('', tk.END, values=(
                ep[0], ep[2], ep[6] or "", zam, inst_date or "—"))

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
        return (int(values[0]), values[1])

    def _add_part_to_selected(self):
        ctx = self._current_selected_equip()
        if ctx is None:
            messagebox.showwarning("Внимание", "Сначала выберите оборудование в таблице!")
            return
        equip_id, _equip_name, equip_install = ctx
        self._add_equipment_part_dialog(equip_id, equip_install)

    def _add_equipment_part_dialog(self, equip_id: int, equip_install: Optional[str]):
        """Диалог добавления запчасти в состав выбранного оборудования."""
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

        tk.Label(frame, text="Дата снятия:", font=("Arial", 10)).grid(row=3, column=0, sticky=tk.W, pady=5)
        p_removal = tk.Entry(frame, width=25)
        p_removal.grid(row=3, column=1, sticky=tk.W, pady=5)

        def do_add():
            selection = part_combo.get()
            if not selection:
                messagebox.showwarning("Внимание", "Выберите запчасть!")
                return
            part_id = int(selection.split(" - ")[0])
            self.db.add_equipment_part(
                equip_id, part_id,
                p_install.get().strip() or None,
                p_removal.get().strip() or None
            )
            add_window.destroy()
            ctx = self._current_selected_equip()
            if ctx:
                self._refresh_parts_panel(ctx[0], ctx[1], ctx[2])

        btn_frame = tk.Frame(add_window)
        btn_frame.pack(pady=12)
        self._btn(btn_frame, "💾 Добавить", do_add, color='success', font_size=10, padx=15).pack(side=tk.LEFT, padx=8)
        self._btn(btn_frame, "❌ Отмена", add_window.destroy, color='danger', font_size=10, padx=15).pack(side=tk.LEFT, padx=8)
        fit_window(add_window, min_width=560, min_height=280)

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
        """Диалог изменения дат установки/снятия запчасти."""
        default_install = equip_install if not ep_data[4] else ep_data[4]

        edit_window = Toplevel(self.root)
        edit_window.title("Изменить даты запчасти")
        edit_window.transient(self.root)
        edit_window.grab_set()

        tk.Label(edit_window, text=f"✏ Изменение дат: {name}",
                 font=("Arial", 12, "bold")).pack(pady=10)

        frame = tk.Frame(edit_window)
        frame.pack(pady=8)

        install_entry = tk.Entry(frame, width=25)
        removal_entry = tk.Entry(frame, width=25)
        install_entry.insert(0, default_install or "")
        if ep_data[5]:
            removal_entry.insert(0, ep_data[5])

        tk.Label(frame, text="Дата установки:", font=("Arial", 10)).grid(row=0, column=0, sticky=tk.W, pady=5)
        install_entry.grid(row=0, column=1, sticky=tk.W, pady=5)
        tk.Label(frame, text="Дата снятия:", font=("Arial", 10)).grid(row=1, column=0, sticky=tk.W, pady=5)
        removal_entry.grid(row=1, column=1, sticky=tk.W, pady=5)

        def save():
            self.db.update_equipment_part(
                ep_id,
                install_entry.get().strip() or None,
                removal_entry.get().strip() or None
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
        fit_window(edit_window, min_width=480, min_height=260)

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
        values = self.home_tree.item(self.home_tree.selection()[0])['values']
        self.statusbar.config(text=f"Оборудование: {values[1]} (ID={values[0]})")
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

        for e in equipment:
            status = e[3] if e[3] else "в эксплуатации"
            self.home_tree.insert('', tk.END, values=(e[0], e[1], e[2] or "—", status))

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

    def view_catalog(self):
        self.show_view("catalog")

    # === РАЗДЕЛ «КАТАЛОГ ОБОРУДОВАНИЯ» ===

    def setup_catalog_tab(self):
        select_frame = tk.Frame(self.catalog_tab)
        select_frame.pack(pady=10)

        tk.Label(select_frame, text="Каталог:", font=("Arial", 10, "bold")).pack(side=tk.LEFT, padx=5)
        self.catalog_grp_combo = ttk.Combobox(select_frame, width=36)
        self.catalog_grp_combo.pack(side=tk.LEFT, padx=5)
        self.catalog_grp_combo.bind('<<ComboboxSelected>>', lambda e: self.load_catalog())

        self._btn(select_frame, "📂 Загрузить PDF-альбом", self.import_catalog_pdf, color='primary', font_size=9, padx=10).pack(side=tk.LEFT, padx=5)
        self._btn(select_frame, "➕ Оборудование", self.add_catalog_equipment, color='success', font_size=9, padx=10).pack(side=tk.LEFT, padx=5)
        self._btn(select_frame, "🔩 Запчасти", self._catalog_open_parts, color='brown', font_size=9, padx=10).pack(side=tk.LEFT, padx=5)
        self._btn(select_frame, "🔄 Обновить", self.load_catalog, color='neutral', font_size=9, padx=10).pack(side=tk.LEFT, padx=5)

        table_frame = tk.Frame(self.catalog_tab)
        table_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(10, 5))

        columns = ("ID", "Наименование", "Срок службы", "Запчасти")
        self.catalog_tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=12)

        col_widths = {"ID": 45, "Наименование": 560, "Срок службы": 110, "Запчасти": 80}
        for col in columns:
            self.catalog_tree.heading(col, text=col)
            self.catalog_tree.column(col, width=col_widths.get(col, 100))

        scrollbar = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.catalog_tree.yview)
        self.catalog_tree.configure(yscrollcommand=scrollbar.set)

        self.catalog_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Запчасти выбранной модели — встроенная панель (без отдельного окна)
        self.catalog_parts_card = tk.LabelFrame(self.catalog_tab, text="🔩 Запчасти модели",
                                                font=("Arial", 10, "bold"), padx=10, pady=6)
        self.catalog_parts_card.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 5))

        catalog_parts_toolbar = tk.Frame(self.catalog_parts_card)
        catalog_parts_toolbar.pack(fill=tk.X, pady=(0, 4))
        self._btn(catalog_parts_toolbar, "➕ Добавить запчасть", self._catalog_inline_add_part, color='success', font_size=9, padx=10).pack(side=tk.LEFT, padx=4)
        self._btn(catalog_parts_toolbar, "✏ Даты", self._catalog_inline_edit_dates, color='warning', font_size=9, padx=10).pack(side=tk.LEFT, padx=4)
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
        cat_cols = ("ID", "Запчасть", "Обозначение", "Замен.", "Дата установки / замены")
        self.catalog_parts_tree = ttk.Treeview(cpf, columns=cat_cols, show="headings", height=6)
        cat_w = {"ID": 40, "Запчасть": 280, "Обозначение": 200, "Замен.": 55,
                 "Дата установки / замены": 160}
        for c in cat_cols:
            self.catalog_parts_tree.heading(c, text=c)
            self.catalog_parts_tree.column(c, width=cat_w.get(c, 100))
        cvsb = ttk.Scrollbar(cpf, orient=tk.VERTICAL, command=self.catalog_parts_tree.yview)
        self.catalog_parts_tree.configure(yscrollcommand=cvsb.set)
        self.catalog_parts_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        cvsb.pack(side=tk.RIGHT, fill=tk.Y)

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
        for e in equipment:
            equip = self._to_equipment_list([e])[0]
            norm = self._parts_aware_norm(equip)
            norm_view = years_to_text(norm) if norm else "—"
            self.catalog_tree.insert('', tk.END, values=(
                e[0], e[1], norm_view, len(self.db.get_equipment_parts(e[0]))
            ))
        self.statusbar.config(text=f"Каталог: {len(equipment)} единиц оборудования")

    def import_catalog_pdf(self):
        """Загрузка PDF-альбома: парсинг и добавление оборудования + запчастей."""
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
        name_entry = AutocompleteCombobox(frame, values=self.db.get_all_equipment_names(), width=43)
        name_entry.grid(row=0, column=1, pady=5)

        tk.Label(frame, text="💡 Даты не нужны — срок службы определится запчастями",
                 font=("Arial", 8), fg="#6c757d").grid(row=1, column=1, sticky=tk.W)

        def save():
            try:
                name = name_entry.get().strip()
                if not name:
                    messagebox.showerror("Ошибка", "Введите наименование!")
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

    def _catalog_show_parts(self):
        """Показать запчасти выбранной модели в встроенной панели каталога."""
        selected = self.catalog_tree.selection()
        if not selected:
            return
        values = self.catalog_tree.item(selected[0])['values']
        self._catalog_refresh_parts(int(values[0]), values[1])

    def _catalog_refresh_parts(self, equip_id: int, equip_name: str):
        """Заполнение нижней панели каталога запчастями модели."""
        for row in self.catalog_parts_tree.get_children():
            self.catalog_parts_tree.delete(row)

        self.catalog_parts_card.config(text=f"🔩 Запчасти модели: {equip_name}")
        parts = self.db.get_equipment_parts_full(equip_id)
        for ep in parts:
            if ep[5]:  # история замен — не показываем
                continue
            zam = "✓" if ep[7] else "—"
            inst_date = ep[4]
            # Модель каталога — шаблон без даты установки, поэтому остатка
            # здесь не бывает (в ГРП он идёт от даты установки оборудования).
            self.catalog_parts_tree.insert('', tk.END, values=(
                ep[0], ep[2], ep[6] or "", zam, inst_date or "—"))
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
        return (int(values[0]), values[1])

    def _catalog_selected_part(self):
        """Выбранная запчасть модели: (ep_id, name) или None."""
        sel = self.catalog_parts_tree.selection()
        if not sel:
            messagebox.showwarning("Внимание", "Сначала выберите запчасть в списке!")
            return None
        values = self.catalog_parts_tree.item(sel[0])['values']
        return (int(values[0]), values[1])

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
        self._btn(select_frame, "🔄 Обновить", self.refresh_replacements, color='neutral', font_size=9, padx=10).pack(side=tk.LEFT, padx=5)

        table_frame = tk.LabelFrame(self.repairs_tab, text="Журнал замен запасных частей", padx=10, pady=10)
        table_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        columns = ("ID", "Дата", "Номер запчасти", "Тип оборудования", "Модель",
                   "Производитель", "Вид работ", "Причина", "ФИО", "Влияние на срок")
        self.repairs_tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=12)

        col_widths = {"ID": 40, "Дата": 95, "Номер запчасти": 170, "Тип оборудования": 105,
                      "Модель": 140, "Производитель": 140, "Вид работ": 190,
                      "Причина": 280, "ФИО": 130, "Влияние на срок": 250}
        for col in columns:
            self.repairs_tree.heading(col, text=col)
            self.repairs_tree.column(col, width=col_widths.get(col, 120))

        scrollbar = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.repairs_tree.yview)
        self.repairs_tree.configure(yscrollcommand=scrollbar.set)

        self.repairs_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

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
        for r in rows:
            if detailed:
                record, eq_id, part_id, effect, _new_eq_id, eq_name, part_name = r[:9], *r[9:]
                values = list(record) + [self._effect_label(effect, eq_name, part_name)]
                if effect:
                    effectful += 1
            else:
                values = list(r) + ['']
            self.repairs_tree.insert('', tk.END, values=values)

        if detailed:
            extra = (f", со сбросом срока: {effectful}" if effectful else "")
            self.statusbar.config(
                text=f"Замены ГРП «{grp_name}» (#{grp_id}): {len(rows)} записей{extra}")
        else:
            self.statusbar.config(
                text=f"Замены ГРП «{grp_name}» (#{grp_id}): {len(rows)} записей")
        return grp_id

    @staticmethod
    def _effect_label(effect: str, eq_name: str = '', part_name: str = '') -> str:
        """Человекочитаемая подпись влияния записи журнала на срок службы."""
        if effect == 'part':
            where = ' → '.join(x for x in (eq_name, part_name) if x)
            return f'срок заново: {where}' if where else 'срок запчасти заново'
        if effect == 'equipment':
            return f'срок заново: {eq_name} (целиком)' if eq_name else 'срок оборудования заново'
        return '—'

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

        def update_hint(*_args):
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
                        clear_links=(effect == ''))
                else:
                    self.db.add_replacement(
                        grp_id, *data, equipment_id=eq_id, part_id=part_id,
                        effect=effect, new_equipment_id=new_eq_id)
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
        fit_window(window, min_width=700, min_height=560)

    def add_replacement(self):
        grp = self._current_grp()
        if grp is None:
            return
        self._replacement_dialog(grp[0], grp[1])

    def replace_part(self):
        """Замена запчасти: дата + физ. замена запчасти в составе оборудования
        и строка в журнале замен (Excel в формате М.ГГГГ)."""
        grp = self._current_grp()
        if grp is None:
            return
        self._replace_part_dialog(grp[0], grp[1])

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

    def _replace_part_dialog(self, grp_id: int, grp_name: str):
        window = Toplevel(self.root)
        window.title(f"🔧 Замена запчасти — ГРП {grp_name}")
        window.transient(self.root)
        window.grab_set()

        tk.Label(window, text=f"🔧 Замена запасной части\nГРП #{grp_id}: {grp_name}",
                 font=("Arial", 12, "bold")).pack(pady=6)

        equipment = self.db.get_equipment_by_grp(grp_id)
        if not equipment:
            messagebox.showwarning("Внимание", "У ГРП нет оборудования.")
            window.destroy()
            return

        main = tk.Frame(window)
        main.pack(fill=tk.BOTH, expand=True, padx=10, pady=4)
        main.grid_columnconfigure(0, weight=1)
        main.grid_columnconfigure(1, weight=2)
        main.grid_rowconfigure(0, weight=1)

        # === Слева: список оборудования ===
        left = tk.LabelFrame(main, text="📦 Оборудование",
                             font=("Arial", 10, "bold"), padx=6, pady=4)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 4))

        eq_tree = ttk.Treeview(left, columns=("n", "d"), show="headings", height=12)
        eq_tree.heading("n", text="Наименование")
        eq_tree.heading("d", text="Установлено")
        eq_tree.column("n", width=230, anchor=tk.W)
        eq_tree.column("d", width=90, anchor=tk.CENTER)
        eq_tree.pack(fill=tk.BOTH, expand=True)

        # === Справа: запчасти оборудования ===
        right = tk.LabelFrame(main, text="🔩 Запчасти оборудования",
                              font=("Arial", 10, "bold"), padx=6, pady=4)
        right.grid(row=0, column=1, sticky="nsew")

        cols = ("ID", "Запчасть", "Обозначение", "Замен.", "Норма")
        parts_tree = ttk.Treeview(right, columns=cols, show="headings", height=12)
        widths = {"ID": 40, "Запчасть": 200, "Обозначение": 110, "Замен.": 55,
                  "Норма": 90}
        for c in cols:
            parts_tree.heading(c, text=c)
            parts_tree.column(c, width=widths[c], anchor=tk.W)
        parts_tree.pack(fill=tk.BOTH, expand=True)

        # === Форма: запись о замене (журнал) ===
        form = tk.LabelFrame(window, text="📝 Запись о замене (журнал)",
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

        fctrl(1, 0, "Дата замены:", date_entry)
        fctrl(1, 2, "Вид работ:", work_combo)
        fctrl(2, 0, "Причина:", reason_entry)
        fctrl(2, 2, "ФИО руководителя:", boss_entry)

        parts = {}
        current_eq = {"row": None}

        def load_equipment_parts(eq):
            current_eq["row"] = eq
            for row in parts_tree.get_children():
                parts_tree.delete(row)
            parts.clear()
            full = self.db.get_equipment_parts_full(eq[0])
            for ep in full:
                if ep[5]:  # снятая запись (история) — не показываем
                    continue
                ep_id, part_id, name, norm, p_install, _removal, pnum, is_repl = ep
                parts[ep_id] = (eq, part_id, name, norm, pnum or "", is_repl)
                parts_tree.insert('', tk.END, values=(
                    ep_id, name, pnum or "", "✓" if is_repl else "—",
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
            ep_id = int(parts_tree.item(sel[0])['values'][0])
            eq, _pid, _name, _norm, pnumber, is_repl = parts[ep_id]
            sel_info.config(text=f"Выбрано: {_name}  ·  обозначение: {pnumber or '—'}  ·  оборудование: {eq[1]}")
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
            ep_id = int(parts_tree.item(sel[0])['values'][0])
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
                                        effect='part')
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
                self.db.add_replacement(
                    grp_id, date_input, 'полная замена оборудования',
                    self._equipment_type_by_model(eq[1]), eq[1], None,
                    work_combo.get().strip() or 'Замена',
                    reason_entry.get().strip() or None,
                    boss_entry.get().strip() or None,
                    equipment_id=eq_id, effect='equipment',
                    new_equipment_id=new_id)
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
                    f"Создано новое оборудование (ID {new_id}) с датой установки "
                    f"{date_input}.\n\n"
                    f"Срок службы всех {len(active)} запчастей отсчитывается заново "
                    f"от этой даты.")
                window.destroy()
            except Exception as e:
                messagebox.showerror("Ошибка", str(e))

        btn_frame = tk.Frame(window)
        btn_frame.pack(pady=8)
        self._btn(btn_frame, "💾 Заменить запчасть", save, color='success', font_size=10, padx=20).pack(side=tk.LEFT, padx=8)
        self._btn(btn_frame, "🔄 Заменить оборудование полностью",
                  replace_whole_equipment, color='primary', font_size=10,
                  padx=20).pack(side=tk.LEFT, padx=8)
        self._btn(btn_frame, "❌ Закрыть", window.destroy, color='danger', font_size=10, padx=20).pack(side=tk.LEFT, padx=8)
        fit_window(window, min_width=900, min_height=560)

    def edit_replacement(self):
        grp = self._current_grp()
        if grp is None:
            return
        selected = self.repairs_tree.selection()
        if not selected:
            messagebox.showwarning("Внимание", "Выберите замену из списка!")
            return
        repl_id = int(self.repairs_tree.item(selected[0])['values'][0])
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
        repl_id = int(values[0])
        part_number = values[2]
        effect_text = values[9] if len(values) > 9 else ''

        question = f"Удалить замену '{part_number}' (ID={repl_id})?"
        if effect_text and effect_text != '—':
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
        self.statusbar.config(text=f"Замена #{repl_id} удалена{note}, Excel обновлён")

    def sync_excel(self, silent: bool = False):
        """Перезаписать файл «Замены.xlsx» из БД."""
        try:
            filename = excel_sync.sync_replacements_workbook(self.db)
            self.statusbar.config(text=f"Excel обновлён: {os.path.basename(filename)}")
        except Exception as e:
            msg = f"Не удалось обновить файл Excel:\n{e}"
            if silent:
                self.statusbar.config(text=f"⚠️ {msg}")
            else:
                messagebox.showwarning("Excel", msg)

    def refresh_replacements(self):
        if self.current_grp_id is not None:
            self.load_replacements()
        self.statusbar.config(text="Таблица замен обновлена")

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

        columns = ("ID", "Дата", "A", "B", "C", "K", "n", "u", "m", "r")
        self.tech_tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=8)

        col_widths = {"ID": 40, "Дата": 120, "A": 60, "B": 60, "C": 60, "K": 80, "n": 40, "u": 40, "m": 40, "r": 40}
        for col in columns:
            self.tech_tree.heading(col, text=col)
            self.tech_tree.column(col, width=col_widths.get(col, 60))

        scrollbar = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.tech_tree.yview)
        self.tech_tree.configure(yscrollcommand=scrollbar.set)

        self.tech_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

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

    def add_grp(self):
        window = Toplevel(self.root)
        window.title("Добавить ГРП")
        window.transient(self.root)
        window.grab_set()

        tk.Label(window, text="🏗️ Добавление нового ГРП",
                 font=("Arial", 14, "bold"), fg="#546E7A").pack(pady=15)

        frame = tk.Frame(window)
        frame.pack(pady=10)

        tk.Label(frame, text="Тип ГРП:", font=("Arial", 10)).grid(row=0, column=0, sticky=tk.W, pady=5)
        type_entry = tk.Entry(frame, width=35)
        type_entry.grid(row=0, column=1, pady=5)

        tk.Label(frame, text="Количество линий:", font=("Arial", 10)).grid(row=1, column=0, sticky=tk.W, pady=5)
        lines_entry = tk.Entry(frame, width=20)
        lines_entry.grid(row=1, column=1, pady=5)

        tk.Label(frame, text="Фактический срок:", font=("Arial", 10)).grid(row=2, column=0, sticky=tk.W, pady=5)
        actual_entry = tk.Entry(frame, width=20)
        actual_entry.grid(row=2, column=1, pady=5)

        tk.Label(frame, text="Проектный срок:", font=("Arial", 10)).grid(row=3, column=0, sticky=tk.W, pady=5)
        design_entry = tk.Entry(frame, width=20)
        design_entry.grid(row=3, column=1, pady=5)

        tk.Label(frame, text="срок можно ввести как «7 лет 4 мес», «7,3» или просто «7,3 года»",
                 font=("Arial", 8), fg="#6c757d").grid(row=4, column=0, columnspan=4,
                                                         sticky=tk.W, pady=(0, 4))

        tk.Label(frame, text="Сведения о ГРП (паспорт объекта)",
                 font=("Arial", 11, "bold"), fg="#546E7A").grid(
            row=5, column=0, columnspan=4, sticky=tk.W, pady=(12, 2))
        passport_widgets = _grp_passport_form(frame, start_row=6)

        def save():
            try:
                grp_type = type_entry.get().strip()
                if not grp_type:
                    messagebox.showerror("Ошибка", "Введите тип ГРП!")
                    return
                try:
                    lines = int(lines_entry.get().strip())
                except ValueError:
                    messagebox.showerror("Ошибка", "Количество линий — целое число!")
                    return
                actual = parse_years_strict(actual_entry.get(), "фактический срок")
                design = parse_years_strict(design_entry.get(), "проектный срок")

                new_id = self.db.add_grp(
                    grp_type, lines, actual, design,
                    passport=_grp_passport_values(passport_widgets))
                window.destroy()
                self.set_current_grp(new_id)
                self.statusbar.config(text=f"Добавлен ГРП: {grp_type}")
                messagebox.showinfo(
                    "Успех",
                    f"✅ ГРП добавлен и выбран!\n\n"
                    f"Фактический срок: {years_to_text(actual)}\n"
                    f"Проектный срок: {years_to_text(design)}")
            except DurationError as e:
                messagebox.showerror("Ошибка", str(e))
            except Exception as e:
                messagebox.showerror("Ошибка", str(e))

        btn_frame = tk.Frame(window)
        btn_frame.pack(pady=20)
        self._btn(btn_frame, "💾 Сохранить", save, color='success', font_size=10, padx=20).pack(side=tk.LEFT, padx=10)
        self._btn(btn_frame, "❌ Отмена", window.destroy, color='danger', font_size=10, padx=20).pack(side=tk.LEFT, padx=10)
        fit_window(window, min_width=880, min_height=620)

    def edit_grp(self):
        """Редактирование выбранного ГРП"""
        grp = self._current_grp()
        if grp is None:
            return
        grp_id = grp[0]

        grp_data = self.db.get_grp_by_id(grp_id)
        if not grp_data:
            messagebox.showerror("Ошибка", f"ГРП #{grp_id} не найден в базе")
            return

        window = Toplevel(self.root)
        window.title(f"Редактирование ГРП ID={grp_id}")
        window.transient(self.root)
        window.grab_set()

        tk.Label(window, text=f"✏ Редактирование ГРП #{grp_id}",
                 font=("Arial", 14, "bold"), fg="#546E7A").pack(pady=15)

        frame = tk.Frame(window)
        frame.pack(pady=10)

        tk.Label(frame, text="Тип ГРП:", font=("Arial", 10)).grid(row=0, column=0, sticky=tk.W, pady=5)
        type_entry = tk.Entry(frame, width=35)
        type_entry.insert(0, grp_data[1])
        type_entry.grid(row=0, column=1, pady=5)

        tk.Label(frame, text="Количество линий:", font=("Arial", 10)).grid(row=1, column=0, sticky=tk.W, pady=5)
        lines_entry = tk.Entry(frame, width=20)
        lines_entry.insert(0, str(grp_data[2]))
        lines_entry.grid(row=1, column=1, pady=5)

        tk.Label(frame, text="Фактический срок:", font=("Arial", 10)).grid(row=2, column=0, sticky=tk.W, pady=5)
        actual_entry = tk.Entry(frame, width=20)
        actual_entry.insert(0, years_to_text(grp_data[3]))
        actual_entry.grid(row=2, column=1, pady=5)

        tk.Label(frame, text="Проектный срок:", font=("Arial", 10)).grid(row=3, column=0, sticky=tk.W, pady=5)
        design_entry = tk.Entry(frame, width=20)
        design_entry.insert(0, years_to_text(grp_data[4]))
        design_entry.grid(row=3, column=1, pady=5)

        tk.Label(frame, text="срок можно ввести как «7 лет 4 мес», «7,3» или просто «7,3 года»",
                 font=("Arial", 8), fg="#6c757d").grid(row=4, column=0, columnspan=4,
                                                         sticky=tk.W, pady=(0, 4))

        tk.Label(frame, text="Сведения о ГРП (паспорт объекта)",
                 font=("Arial", 11, "bold"), fg="#546E7A").grid(
            row=5, column=0, columnspan=4, sticky=tk.W, pady=(12, 2))
        passport_widgets = _grp_passport_form(
            frame, start_row=6, values=grp_passport.values(grp_data))

        def save():
            try:
                grp_type = type_entry.get().strip()
                if not grp_type:
                    messagebox.showerror("Ошибка", "Введите тип ГРП!")
                    return
                try:
                    lines = int(lines_entry.get().strip())
                except ValueError:
                    messagebox.showerror("Ошибка", "Количество линий — целое число!")
                    return
                actual = parse_years_strict(actual_entry.get(), "фактический срок")
                design = parse_years_strict(design_entry.get(), "проектный срок")

                self.db.update_grp(
                    grp_id, grp_type, lines, actual, design,
                    passport=_grp_passport_values(passport_widgets))
                messagebox.showinfo("Успех", "✅ ГРП обновлён!")
                window.destroy()
                self.set_current_grp(grp_id)
                self.statusbar.config(text=f"ГРП #{grp_id} обновлён")
            except DurationError as e:
                messagebox.showerror("Ошибка", str(e))
            except Exception as e:
                messagebox.showerror("Ошибка", str(e))

        btn_frame = tk.Frame(window)
        btn_frame.pack(pady=20)
        self._btn(btn_frame, "💾 Сохранить", save, color='success', font_size=10, padx=20).pack(side=tk.LEFT, padx=10)
        self._btn(btn_frame, "❌ Отмена", window.destroy, color='danger', font_size=10, padx=20).pack(side=tk.LEFT, padx=10)
        fit_window(window, min_width=880, min_height=660)

    def delete_grp(self):
        """Удаление выбранного ГРП (вместе с оборудованием и историей)"""
        grp = self._current_grp()
        if grp is None:
            return
        grp_id = grp[0]
        grp_type = grp[1]

        if self._is_catalog_grp_name(grp_type):
            messagebox.showwarning("Внимание",
                                   "Каталог оборудования — служебный справочник, удалить его нельзя.")
            return

        if messagebox.askyesno("Подтверждение", f"Удалить ГРП '{grp_type}' (ID={grp_id})?\n"
                               f"Оборудование и история диагностик будут удалены!"):
            self.db.delete_grp(grp_id)
            self.clear_current_grp()
            self.statusbar.config(text=f"ГРП '{grp_type}' удалён")

    def add_equipment(self):
        grp = self._current_grp()
        if grp is None:
            return

        grp_id = grp[0]
        grp_name = grp[1]

        window = Toplevel(self.root)
        window.title(f"Добавить оборудование в ГРП {grp_name}")
        window.transient(self.root)
        window.grab_set()

        tk.Label(window, text=f"➕ Добавление оборудования в ГРП #{grp_id}: {grp_name}",
                 font=("Arial", 12, "bold"), fg="#546E7A").pack(pady=10)

        frame = tk.Frame(window)
        frame.pack(pady=10)

        tk.Label(frame, text="Наименование оборудования:", font=("Arial", 10)).grid(row=0, column=0, sticky=tk.W, pady=5)
        name_entry = AutocompleteCombobox(frame, values=self.db.get_all_equipment_names(), width=38)
        name_entry.grid(row=0, column=1, pady=5)
        tk.Label(frame, text="начните вводить — список отфильтруется; кнопка ▼ — открыть список", font=("Arial", 8), fg="#6c757d").grid(row=1, column=1, sticky=tk.W)

        tk.Label(frame, text="Дата установки (ГГГГ-ММ-ДД):", font=("Arial", 10)).grid(row=2, column=0, sticky=tk.W, pady=5)
        install_entry = tk.Entry(frame, width=20)
        install_entry.grid(row=2, column=1, pady=5)
        tk.Label(frame, text="например: 2020-01-15", font=("Arial", 8), fg="#6c757d").grid(row=3, column=1, sticky=tk.W)

        tk.Label(frame, text="Дата снятия (если есть):", font=("Arial", 10)).grid(row=4, column=0, sticky=tk.W, pady=5)
        removal_entry = tk.Entry(frame, width=20)
        removal_entry.grid(row=4, column=1, pady=5)
        tk.Label(frame, text="оставьте пустым, если в эксплуатации", font=("Arial", 8), fg="#6c757d").grid(row=5, column=1, sticky=tk.W)

        def save():
            try:
                install_date = install_entry.get().strip()
                if not install_date:
                    messagebox.showerror("Ошибка", "Дата установки обязательна!")
                    return

                name = name_entry.get().strip()
                if not name:
                    messagebox.showerror("Ошибка", "Введите наименование оборудования!")
                    return

                new_eq_id = self.db.add_equipment(
                    grp_id,
                    name,
                    install_date,
                    removal_entry.get().strip() if removal_entry.get().strip() else None
                )
                linked = self._auto_link_parts_from_catalog(new_eq_id, name)
                msg = "✅ Оборудование добавлено!"
                if linked:
                    msg += f"\n\nЗапчасти занесены автоматически из каталога: {linked} шт.\n(срок каждой запчасти — 5 лет, срок оборудования = мин. остаток среди запчастей)"
                else:
                    msg += "\n\n⚠️ В каталоге нет модели с таким названием.\nВнесите оборудование (запчасти) вручную — иначе у него не будет срока."
                messagebox.showinfo("Успех", msg)
                window.destroy()
                self.load_home()
                self.statusbar.config(text=f"Добавлено оборудование: {name}")
            except Exception as e:
                messagebox.showerror("Ошибка", str(e))

        btn_frame = tk.Frame(window)
        btn_frame.pack(pady=20)
        self._btn(btn_frame, "💾 Сохранить", save, color='success', font_size=10, padx=20).pack(side=tk.LEFT, padx=10)
        self._btn(btn_frame, "❌ Отмена", window.destroy, color='danger', font_size=10, padx=20).pack(side=tk.LEFT, padx=10)
        fit_window(window, min_width=620, min_height=420)

    def view_equipment(self):
        """Показать оборудование и запчасти в главном окне (выбранный ГРП)."""
        if self._current_grp() is None:
            return
        self.show_view("grp")
        self.load_home()
        self.statusbar.config(text=f"Оборудование и запчасти ГРП «{self.current_grp_name}»")

    def export_grp_word(self):
        """Сформировать отчёт по текущему ГРП в формате Word (.docx)."""
        grp = self._current_grp()
        if grp is None:
            return

        grp_id = grp[0]
        grp_name = grp[1]

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

    def show_warnings(self):
        grp = self._current_grp()
        if grp is None:
            return

        grp_id = grp[0]
        grp_name = grp[1]

        equipment_data = self.db.get_equipment_by_grp(grp_id)

        if not equipment_data:
            messagebox.showinfo("Информация", "У данного ГРП нет оборудования")
            return

        problems = self.doc_analyzer.get_current_problems(self._to_equipment_list(equipment_data))

        if (len(problems['overdue']) == 0 and len(problems['near_limit']) == 0
                and len(problems['no_data']) == 0):
            messagebox.showinfo("✅ Предупреждения", "✅ Нет оборудования, требующего внимания!")
            return

        window = Toplevel(self.root)
        window.title(f"⚠️ Предупреждения - ГРП {grp_name}")
        window.transient(self.root)

        text_area = scrolledtext.ScrolledText(window, wrap=tk.WORD, font=("Courier", 10))
        text_area.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        text_area.insert(tk.END, "=" * 80 + "\n")
        text_area.insert(tk.END, "⚠️ ПРЕДУПРЕЖДЕНИЯ ПО ТЕКУЩЕМУ ОБОРУДОВАНИЮ\n")
        text_area.insert(tk.END, f"ГРП: {grp_name}\n")
        text_area.insert(tk.END, "=" * 80 + "\n\n")

        if problems['overdue']:
            text_area.insert(tk.END, "❌ ОБОРУДОВАНИЕ, У КОТОРОГО СРОК ИСТЁК (ТРЕБУЕТ ЗАМЕНЫ):\n")
            text_area.insert(tk.END, "-" * 80 + "\n")
            for p in problems['overdue']:
                text_area.insert(tk.END, f"\n🔴 {p['name']}\n")
                text_area.insert(tk.END, f"   📅 Установлено: {p['install_date']}\n")
                text_area.insert(tk.END, f"   📆 Мин. остаток по запчастям: {years_to_text(p['remaining'])}\n")
                text_area.insert(tk.END, f"   ⚠️ ПРОСРОЧЕНО на: {years_to_text(p['exceeded'])}!\n")

        if problems['near_limit']:
            text_area.insert(tk.END, "\n⚠️ ОБОРУДОВАНИЕ, У КОТОРОГО СРОК ИСТЕЧЁТ В ТЕЧЕНИЕ ГОДА:\n")
            text_area.insert(tk.END, "-" * 80 + "\n")
            for p in problems['near_limit']:
                text_area.insert(tk.END, f"\n🟡 {p['name']}\n")
                text_area.insert(tk.END, f"   📅 Установлено: {p['install_date']}\n")
                text_area.insert(tk.END, f"   ⏰ Осталось по слабой запчасти: {years_to_text(p['left_years'])}\n")

        if problems['no_data']:
            text_area.insert(tk.END, "\n❓ ОБОРУДОВАНИЕ БЕЗ ЗАПЧАСТЕЙ (СРОКА НЕТ):\n")
            text_area.insert(tk.END, "-" * 80 + "\n")
            for p in problems['no_data']:
                text_area.insert(tk.END, f"\n❔ {p['name']}\n")
                text_area.insert(tk.END, f"   💡 Внесите оборудование (запчасти), чтобы появился срок\n")

        text_area.config(state=tk.DISABLED)

        def export_warnings():
            filename = filedialog.asksaveasfilename(
                defaultextension=".txt",
                filetypes=[("Text files", "*.txt")],
                initialfile=f"warnings_{grp_name}_{datetime.now().strftime('%Y%m%d')}.txt"
            )
            if filename:
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write(text_area.get(1.0, tk.END))
                messagebox.showinfo("Успех", f"Сохранено в:\n{filename}")

        btn_frame = tk.Frame(window)
        btn_frame.pack(pady=10)
        self._btn(btn_frame, "💾 Сохранить", export_warnings, color='success', font_size=9, padx=10).pack(side=tk.LEFT, padx=5)
        self._btn(btn_frame, "✖ Закрыть", window.destroy, color='danger', font_size=9, padx=10).pack(side=tk.LEFT, padx=5)
        fit_window(window, min_width=760, min_height=480)

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
        for coef in coefficients:
            self.tech_tree.insert('', tk.END, values=(
                coef[0],             # ID
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
        """Открытие окна с расчётом по алгоритмам для выбранного ГРП"""
        grp = self._current_grp()
        if grp is None:
            return

        grp_id = grp[0]
        grp_name = grp[1]

        equipment_data = self.db.get_equipment_by_grp(grp_id)

        if not equipment_data:
            messagebox.showinfo("Информация", "У данного ГРП нет оборудования для расчёта")
            return

        try:
            self._algorithms_window = AlgorithmsWindow(
                self.root, self.db, grp_id, equipment_data, grp_name,
                params=self.calc_params, on_params=self._remember_calc_params)
            self.statusbar.config(text=f"Открыт расчёт алгоритмов для ГРП: {grp_name}")
        except ImportError as e:
            messagebox.showerror("Ошибка", f"Не удалось загрузить модуль algorithms_view: {e}")
        except Exception as e:
            messagebox.showerror("Ошибка", f"Ошибка при открытии окна алгоритмов: {e}")

    def _remember_calc_params(self, params: AlgorithmParams):
        """Запомнить весовые коэффициенты, заданные в окне расчёта.

        Отчёт Word формируется с ними, иначе пользователь увидит в .docx
        числа, отличающиеся от только что посчитанных на экране.
        """
        self.calc_params = params