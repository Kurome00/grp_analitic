import tkinter as tk
from tkinter import ttk, messagebox, Toplevel, filedialog, scrolledtext  # <-- ДОБАВЛЕН scrolledtext
from datetime import datetime
from database_pg import DatabasePG
from models import Equipment
from documentary_analyzer import DocumentaryAnalyzer
from statistic_analyzer import StatisticsAnalyzer
from technical_analyzer_pg import TechnicalAnalyzer, TechnicalHistoryAnalyzer
import numpy as np


class GRPAppPG:
    """Главный класс приложения с PostgreSQL"""
    
    def __init__(self, root):
        self.root = root
        # ⚠️ ЗАМЕНИТЕ ПАРОЛЬ НА ВАШ!
        self.db = DatabasePG(
            host='localhost',
            port='5432',
            database='grp_analyzer',
            user='postgres',
            password='Dzanatyt2003'  # ⚠️ ЗАМЕНИТЕ НА ВАШ ПАРОЛЬ!
        )
        self.doc_analyzer = DocumentaryAnalyzer(self.db)
        self.setup_ui()
        self.refresh_grp_list()
        self.refresh_norms_table()
    
    def setup_ui(self):
        self.root.title("🏭 Система анализа ГРП (PostgreSQL)")
        self.root.geometry("1350x780")
        
        # Настройка стилей
        style = ttk.Style()
        style.configure('Header.TLabel', font=('Arial', 12, 'bold'))
        style.configure('Info.TLabel', font=('Arial', 9), foreground='#6c757d')
        style.configure('Success.TButton', font=('Arial', 10, 'bold'))
        
        # Статусбар
        self.statusbar = tk.Label(self.root, text="Готов к работе", 
                                  relief=tk.SUNKEN, anchor=tk.W, font=("Arial", 9))
        self.statusbar.pack(side=tk.BOTTOM, fill=tk.X)
        
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        self.grp_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.grp_tab, text="🏗️ Управление ГРП")
        self.setup_grp_tab()
        
        self.norms_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.norms_tab, text="📋 Документальные нормы")
        self.setup_norms_tab()
        
        self.tech_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.tech_tab, text="🔧 Технические коэффициенты")
        self.setup_tech_tab()
        
        self.stats_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.stats_tab, text="📊 Статистика")
        self.setup_stats_tab()
    
    def setup_grp_tab(self):
        # Верхняя панель с кнопками
        top_frame = tk.Frame(self.grp_tab, bg="#f8f9fa", relief=tk.RIDGE, bd=1)
        top_frame.pack(fill=tk.X, padx=5, pady=5)
        
        # Левая группа кнопок
        left_btn_frame = tk.Frame(top_frame, bg="#f8f9fa")
        left_btn_frame.pack(side=tk.LEFT, padx=5, pady=5)
        
        tk.Button(left_btn_frame, text="➕ Добавить ГРП", command=self.add_grp,
                 bg="#2196F3", fg="white", font=("Arial", 9, "bold"), padx=10).pack(side=tk.LEFT, padx=2)
        tk.Button(left_btn_frame, text="✏ Редактировать ГРП", command=self.edit_grp,
                 bg="#FF9800", fg="white", font=("Arial", 9, "bold"), padx=10).pack(side=tk.LEFT, padx=2)
        tk.Button(left_btn_frame, text="➕ Добавить оборудование", command=self.add_equipment,
                 bg="#4CAF50", fg="white", font=("Arial", 9, "bold"), padx=10).pack(side=tk.LEFT, padx=2)
        tk.Button(left_btn_frame, text="👁️ Показать оборудование", command=self.view_equipment,
                 bg="#00BCD4", fg="white", font=("Arial", 9, "bold"), padx=10).pack(side=tk.LEFT, padx=2)
        
        # Правая группа кнопок
        right_btn_frame = tk.Frame(top_frame, bg="#f8f9fa")
        right_btn_frame.pack(side=tk.RIGHT, padx=5, pady=5)
        
        tk.Button(right_btn_frame, text="📄 Документальный анализ", command=self.documentary_analysis,
                 bg="#9C27B0", fg="white", font=("Arial", 9, "bold"), padx=10).pack(side=tk.LEFT, padx=2)
        tk.Button(right_btn_frame, text="⚠️ Предупреждения", command=self.show_warnings,
                 bg="#F44336", fg="white", font=("Arial", 9, "bold"), padx=10).pack(side=tk.LEFT, padx=2)
        tk.Button(right_btn_frame, text="🧮 Расчёт алгоритмов", command=self.open_algorithms,
                 bg="#673AB7", fg="white", font=("Arial", 9, "bold"), padx=10).pack(side=tk.LEFT, padx=2)
        tk.Button(right_btn_frame, text="🔄 Обновить", command=self.refresh_grp_list,
                 bg="#607D8B", fg="white", font=("Arial", 9, "bold"), padx=10).pack(side=tk.LEFT, padx=2)
        
        # Таблица ГРП
        tree_frame = tk.Frame(self.grp_tab)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        columns = ("ID", "Тип ГРП", "Линии", "Факт. срок", "Проект. срок", "Оборудование")
        self.grp_list = ttk.Treeview(tree_frame, columns=columns, show="headings", height=8)
        
        col_widths = {"ID": 50, "Тип ГРП": 250, "Линии": 80, "Факт. срок": 100, "Проект. срок": 100, "Оборудование": 120}
        for col in columns:
            self.grp_list.heading(col, text=col)
            self.grp_list.column(col, width=col_widths.get(col, 100))
        
        scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.grp_list.yview)
        self.grp_list.configure(yscrollcommand=scrollbar.set)
        
        self.grp_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Привязываем событие для обновления статуса
        self.grp_list.bind('<<TreeviewSelect>>', self.on_grp_select)
        
        # Информационная панель
        info_frame = tk.Frame(self.grp_tab, bg="#f8f9fa", relief=tk.RIDGE, bd=1)
        info_frame.pack(fill=tk.X, padx=5, pady=5)
        
        self.info_label = tk.Label(info_frame, text="💡 Выберите ГРП для просмотра информации",
                                   font=("Arial", 9), bg="#f8f9fa", fg="#6c757d")
        self.info_label.pack(pady=5)
    
    def on_grp_select(self, event):
        """Обработчик выбора ГРП"""
        selected = self.grp_list.selection()
        if selected:
            grp_data = self.grp_list.item(selected[0])['values']
            grp_id = grp_data[0]
            grp_type = grp_data[1]
            
            # Получаем количество оборудования
            equipment = self.db.get_equipment_by_grp(grp_id)
            equip_count = len(equipment)
            
            self.info_label.config(
                text=f"📌 ГРП #{grp_id}: {grp_type} | Оборудование: {equip_count} шт. | "
                     f"Факт. срок: {grp_data[3]} лет | Проект. срок: {grp_data[4]} лет"
            )
            self.statusbar.config(text=f"Выбран ГРП: {grp_type} (ID={grp_id})")
    
    def setup_norms_tab(self):
        btn_frame = tk.Frame(self.norms_tab)
        btn_frame.pack(pady=10)
        
        tk.Button(btn_frame, text="➕ Добавить норму", command=self.add_norm,
                 bg="#4CAF50", fg="white", font=("Arial", 9, "bold"), padx=10).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="✏ Редактировать", command=self.edit_norm,
                 bg="#FF9800", fg="white", font=("Arial", 9, "bold"), padx=10).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="🗑 Удалить", command=self.delete_norm,
                 bg="#F44336", fg="white", font=("Arial", 9, "bold"), padx=10).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="🔄 Обновить", command=self.refresh_norms_table,
                 bg="#607D8B", fg="white", font=("Arial", 9, "bold"), padx=10).pack(side=tk.LEFT, padx=5)
        
        table_frame = tk.Frame(self.norms_tab)
        table_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        columns = ("ID", "Оборудование", "Макс. срок (лет)", "Примечания")
        self.norms_tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=15)
        
        col_widths = {"ID": 50, "Оборудование": 300, "Макс. срок (лет)": 150, "Примечания": 350}
        for col in columns:
            self.norms_tree.heading(col, text=col)
            self.norms_tree.column(col, width=col_widths.get(col, 150))
        
        scrollbar = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.norms_tree.yview)
        self.norms_tree.configure(yscrollcommand=scrollbar.set)
        
        self.norms_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
    
    def setup_tech_tab(self):
        select_frame = tk.Frame(self.tech_tab)
        select_frame.pack(pady=10)
        
        tk.Label(select_frame, text="Выберите ГРП:", font=("Arial", 10, "bold")).pack(side=tk.LEFT, padx=5)
        self.tech_grp_combo = ttk.Combobox(select_frame, width=30)
        self.tech_grp_combo.pack(side=tk.LEFT, padx=5)
        self.tech_grp_combo.bind('<<ComboboxSelected>>', lambda e: self.load_tech_history())
        
        tk.Button(select_frame, text="📊 Загрузить историю", command=self.load_tech_history,
                 bg="#2196F3", fg="white", font=("Arial", 9, "bold")).pack(side=tk.LEFT, padx=5)
        tk.Button(select_frame, text="🔧 Новая диагностика", command=self.add_tech_diagnostic,
                 bg="#4CAF50", fg="white", font=("Arial", 9, "bold")).pack(side=tk.LEFT, padx=5)
        
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
        """
        
        tk.Label(info_frame, text=formula_text, justify=tk.LEFT, font=("Arial", 9), fg="#495057").pack(fill=tk.X)
    
    def setup_stats_tab(self):
        select_frame = tk.Frame(self.stats_tab)
        select_frame.pack(pady=10)
        
        tk.Label(select_frame, text="Выберите ГРП:", font=("Arial", 10, "bold")).pack(side=tk.LEFT, padx=5)
        self.stats_grp_combo = ttk.Combobox(select_frame, width=30)
        self.stats_grp_combo.pack(side=tk.LEFT, padx=5)
        
        tk.Button(select_frame, text="📊 Показать статистику", command=self.show_statistics,
                 bg="#2196F3", fg="white", font=("Arial", 9, "bold")).pack(side=tk.LEFT, padx=5)
        tk.Button(select_frame, text="🔍 Проверить оборудование", command=self.check_equipment_stats,
                 bg="#FF9800", fg="white", font=("Arial", 9, "bold")).pack(side=tk.LEFT, padx=5)
        
        self.stats_text = scrolledtext.ScrolledText(self.stats_tab, wrap=tk.WORD, height=20, font=("Courier", 10))
        self.stats_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
    
    def edit_grp(self):
        """Редактирование выбранного ГРП"""
        selected = self.grp_list.selection()
        if not selected:
            messagebox.showwarning("Внимание", "Выберите ГРП для редактирования!")
            return
        
        grp_id = self.grp_list.item(selected[0])['values'][0]
        grp_data = self.grp_list.item(selected[0])['values']
        
        window = Toplevel(self.root)
        window.title(f"Редактирование ГРП ID={grp_id}")
        window.geometry("450x380")
        window.transient(self.root)
        window.grab_set()
        
        tk.Label(window, text=f"✏ Редактирование ГРП #{grp_id}", 
                 font=("Arial", 14, "bold"), fg="#FF9800").pack(pady=15)
        
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
        
        tk.Label(frame, text="Фактический срок (лет):", font=("Arial", 10)).grid(row=2, column=0, sticky=tk.W, pady=5)
        actual_entry = tk.Entry(frame, width=20)
        actual_entry.insert(0, str(grp_data[3]))
        actual_entry.grid(row=2, column=1, pady=5)
        
        tk.Label(frame, text="Проектный срок (лет):", font=("Arial", 10)).grid(row=3, column=0, sticky=tk.W, pady=5)
        design_entry = tk.Entry(frame, width=20)
        design_entry.insert(0, str(grp_data[4]))
        design_entry.grid(row=3, column=1, pady=5)
        
        def save():
            try:
                grp_type = type_entry.get().strip()
                if not grp_type:
                    messagebox.showerror("Ошибка", "Введите тип ГРП!")
                    return
                
                self.db.update_grp(
                    grp_id,
                    grp_type,
                    int(lines_entry.get()),
                    float(actual_entry.get()),
                    float(design_entry.get())
                )
                messagebox.showinfo("Успех", "✅ ГРП обновлён!")
                window.destroy()
                self.refresh_grp_list()
                self.update_combos()
                self.statusbar.config(text=f"ГРП #{grp_id} обновлён")
            except ValueError as e:
                messagebox.showerror("Ошибка", f"Неверный формат данных: {e}")
            except Exception as e:
                messagebox.showerror("Ошибка", str(e))
        
        btn_frame = tk.Frame(window)
        btn_frame.pack(pady=20)
        tk.Button(btn_frame, text="💾 Сохранить", command=save, 
                 bg="#4CAF50", fg="white", font=("Arial", 10, "bold"), padx=20).pack(side=tk.LEFT, padx=10)
        tk.Button(btn_frame, text="❌ Отмена", command=window.destroy, 
                 bg="#F44336", fg="white", font=("Arial", 10, "bold"), padx=20).pack(side=tk.LEFT, padx=10)
    
    def add_grp(self):
        window = Toplevel(self.root)
        window.title("Добавить ГРП")
        window.geometry("400x350")
        window.transient(self.root)
        window.grab_set()
        
        tk.Label(window, text="🏗️ Добавление нового ГРП", 
                 font=("Arial", 14, "bold"), fg="#2196F3").pack(pady=15)
        
        frame = tk.Frame(window)
        frame.pack(pady=10)
        
        tk.Label(frame, text="Тип ГРП:", font=("Arial", 10)).grid(row=0, column=0, sticky=tk.W, pady=5)
        type_entry = tk.Entry(frame, width=35)
        type_entry.grid(row=0, column=1, pady=5)
        
        tk.Label(frame, text="Количество линий:", font=("Arial", 10)).grid(row=1, column=0, sticky=tk.W, pady=5)
        lines_entry = tk.Entry(frame, width=20)
        lines_entry.grid(row=1, column=1, pady=5)
        
        tk.Label(frame, text="Фактический срок (лет):", font=("Arial", 10)).grid(row=2, column=0, sticky=tk.W, pady=5)
        actual_entry = tk.Entry(frame, width=20)
        actual_entry.grid(row=2, column=1, pady=5)
        
        tk.Label(frame, text="Проектный срок (лет):", font=("Arial", 10)).grid(row=3, column=0, sticky=tk.W, pady=5)
        design_entry = tk.Entry(frame, width=20)
        design_entry.grid(row=3, column=1, pady=5)
        
        def save():
            try:
                grp_type = type_entry.get().strip()
                if not grp_type:
                    messagebox.showerror("Ошибка", "Введите тип ГРП!")
                    return
                
                self.db.add_grp(
                    grp_type,
                    int(lines_entry.get()),
                    float(actual_entry.get()),
                    float(design_entry.get())
                )
                messagebox.showinfo("Успех", "✅ ГРП добавлен!")
                window.destroy()
                self.refresh_grp_list()
                self.update_combos()
                self.statusbar.config(text=f"Добавлен ГРП: {grp_type}")
            except ValueError as e:
                messagebox.showerror("Ошибка", f"Неверный формат данных: {e}")
            except Exception as e:
                messagebox.showerror("Ошибка", str(e))
        
        btn_frame = tk.Frame(window)
        btn_frame.pack(pady=20)
        tk.Button(btn_frame, text="💾 Сохранить", command=save, 
                 bg="#4CAF50", fg="white", font=("Arial", 10, "bold"), padx=20).pack(side=tk.LEFT, padx=10)
        tk.Button(btn_frame, text="❌ Отмена", command=window.destroy, 
                 bg="#F44336", fg="white", font=("Arial", 10, "bold"), padx=20).pack(side=tk.LEFT, padx=10)
    
    def add_equipment(self):
        selected = self.grp_list.selection()
        if not selected:
            messagebox.showwarning("Внимание", "Сначала выберите ГРП из списка!")
            return
        
        grp_id = self.grp_list.item(selected[0])['values'][0]
        grp_name = self.grp_list.item(selected[0])['values'][1]
        
        window = Toplevel(self.root)
        window.title(f"Добавить оборудование в ГРП {grp_name}")
        window.geometry("500x450")
        window.transient(self.root)
        window.grab_set()
        
        tk.Label(window, text=f"➕ Добавление оборудования в ГРП #{grp_id}: {grp_name}", 
                 font=("Arial", 12, "bold"), fg="#4CAF50").pack(pady=10)
        
        frame = tk.Frame(window)
        frame.pack(pady=10)
        
        tk.Label(frame, text="Наименование оборудования:", font=("Arial", 10)).grid(row=0, column=0, sticky=tk.W, pady=5)
        name_entry = tk.Entry(frame, width=40)
        name_entry.grid(row=0, column=1, pady=5)
        
        tk.Label(frame, text="Дата установки (ГГГГ-ММ-ДД):", font=("Arial", 10)).grid(row=1, column=0, sticky=tk.W, pady=5)
        install_entry = tk.Entry(frame, width=20)
        install_entry.grid(row=1, column=1, pady=5)
        tk.Label(frame, text="например: 2020-01-15", font=("Arial", 8), fg="#6c757d").grid(row=2, column=1, sticky=tk.W)
        
        tk.Label(frame, text="Дата снятия (если есть):", font=("Arial", 10)).grid(row=3, column=0, sticky=tk.W, pady=5)
        removal_entry = tk.Entry(frame, width=20)
        removal_entry.grid(row=3, column=1, pady=5)
        tk.Label(frame, text="оставьте пустым, если в эксплуатации", font=("Arial", 8), fg="#6c757d").grid(row=4, column=1, sticky=tk.W)
        
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
                
                self.db.add_equipment(
                    grp_id,
                    name,
                    install_date,
                    removal_entry.get().strip() if removal_entry.get().strip() else None
                )
                messagebox.showinfo("Успех", "✅ Оборудование добавлено!")
                window.destroy()
                self.refresh_grp_list()
                self.update_combos()
                self.statusbar.config(text=f"Добавлено оборудование: {name}")
            except Exception as e:
                messagebox.showerror("Ошибка", str(e))
        
        btn_frame = tk.Frame(window)
        btn_frame.pack(pady=20)
        tk.Button(btn_frame, text="💾 Сохранить", command=save, 
                 bg="#4CAF50", fg="white", font=("Arial", 10, "bold"), padx=20).pack(side=tk.LEFT, padx=10)
        tk.Button(btn_frame, text="❌ Отмена", command=window.destroy, 
                 bg="#F44336", fg="white", font=("Arial", 10, "bold"), padx=20).pack(side=tk.LEFT, padx=10)
    
    def view_equipment(self):
        selected = self.grp_list.selection()
        if not selected:
            messagebox.showwarning("Внимание", "Сначала выберите ГРП из списка!")
            return
        
        grp_id = self.grp_list.item(selected[0])['values'][0]
        grp_name = self.grp_list.item(selected[0])['values'][1]
        
        equipment = self.db.get_equipment_by_grp(grp_id)
        
        window = Toplevel(self.root)
        window.title(f"Оборудование ГРП: {grp_name}")
        window.geometry("850x550")
        window.transient(self.root)
        
        if not equipment:
            tk.Label(window, text="❌ Нет оборудования для данного ГРП",
                    font=("Arial", 14), fg="red").pack(pady=50)
            tk.Button(window, text="✖ Закрыть", command=window.destroy,
                     bg="#F44336", fg="white", font=("Arial", 10, "bold"), padx=20).pack(pady=10)
            return
        
        tk.Label(window, text=f"📋 Оборудование ГРП: {grp_name}", 
                 font=("Arial", 14, "bold")).pack(pady=10)
        
        columns = ("ID", "Наименование", "Дата установки", "Дата снятия")
        tree = ttk.Treeview(window, columns=columns, show="headings", height=15)
        
        col_widths = {"ID": 50, "Наименование": 350, "Дата установки": 150, "Дата снятия": 150}
        for col in columns:
            tree.heading(col, text=col)
            tree.column(col, width=col_widths.get(col, 150))
        
        for equip in equipment:
            status = equip[3] if equip[3] else "✅ В эксплуатации"
            tree.insert('', tk.END, values=(equip[0], equip[1], equip[2], status))
        
        scrollbar = ttk.Scrollbar(window, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10, pady=10)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        btn_frame = tk.Frame(window)
        btn_frame.pack(pady=10)
        
        def check_selected_norms():
            selected_item = tree.selection()
            if selected_item:
                equip_data = tree.item(selected_item[0])['values']
                equip_name = equip_data[1]
                install_date = equip_data[2]
                
                norm = self.db.get_norm_by_name(equip_name)
                if norm:
                    age = self.doc_analyzer.get_equipment_age_years(install_date, None)
                    status = "✅ В норме" if age <= norm[2] else "❌ Требуется замена!"
                    messagebox.showinfo("Проверка нормы", 
                        f"📌 Оборудование: {equip_name}\n"
                        f"📅 Установлено: {install_date}\n"
                        f"⏱ Возраст: {age:.1f} лет\n"
                        f"📋 Норма: {norm[2]} лет\n"
                        f"📊 Статус: {status}")
                else:
                    messagebox.showwarning("Нет нормы", f"Для '{equip_name}' нет документальной нормы!\nДобавьте её на вкладке 'Документальные нормы'")
        
        tk.Button(btn_frame, text="🔍 Проверить по нормам", command=check_selected_norms,
                 bg="#2196F3", fg="white", font=("Arial", 9, "bold"), padx=10).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="✖ Закрыть", command=window.destroy,
                 bg="#F44336", fg="white", font=("Arial", 9, "bold"), padx=10).pack(side=tk.LEFT, padx=5)
    
    def documentary_analysis(self):
        selected = self.grp_list.selection()
        if not selected:
            messagebox.showwarning("Внимание", "Выберите ГРП для анализа!")
            return
        
        grp_id = self.grp_list.item(selected[0])['values'][0]
        grp_name = self.grp_list.item(selected[0])['values'][1]
        
        equipment_data = self.db.get_equipment_by_grp(grp_id)
        
        if not equipment_data:
            messagebox.showinfo("Информация", "У данного ГРП нет оборудования для анализа")
            return
        
        equipment_list = []
        for equip in equipment_data:
            equip_obj = Equipment(
                id=equip[0],
                grp_id=grp_id,
                name=equip[1],
                install_date=equip[2],
                removal_date=equip[3]
            )
            equipment_list.append(equip_obj)
        
        try:
            report = self.doc_analyzer.generate_documentary_report(grp_id, grp_name, equipment_list)
            
            window = Toplevel(self.root)
            window.title(f"📄 Документальный анализ ГРП {grp_name}")
            window.geometry("1100x800")
            window.transient(self.root)
            
            text_area = scrolledtext.ScrolledText(window, wrap=tk.WORD, font=("Courier", 9))
            text_area.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
            
            text_area.insert(tk.END, report)
            text_area.config(state=tk.DISABLED)
            
            def export_to_file():
                filename = filedialog.asksaveasfilename(
                    defaultextension=".txt",
                    filetypes=[("Text files", "*.txt")],
                    initialfile=f"doc_analysis_grp_{grp_id}_{datetime.now().strftime('%Y%m%d')}.txt"
                )
                if filename:
                    with open(filename, 'w', encoding='utf-8') as f:
                        f.write(report)
                    messagebox.showinfo("Успех", f"Отчет сохранен в:\n{filename}")
            
            btn_frame = tk.Frame(window)
            btn_frame.pack(pady=10)
            
            tk.Button(btn_frame, text="💾 Сохранить отчет", command=export_to_file,
                     bg="#2196F3", fg="white", font=("Arial", 9, "bold"), padx=10).pack(side=tk.LEFT, padx=5)
            tk.Button(btn_frame, text="📋 Копировать", 
                     command=lambda: (window.clipboard_clear(), window.clipboard_append(report),
                                     messagebox.showinfo("Успех", "Отчет скопирован в буфер обмена")),
                     bg="#4CAF50", fg="white", font=("Arial", 9, "bold"), padx=10).pack(side=tk.LEFT, padx=5)
            tk.Button(btn_frame, text="✖ Закрыть", command=window.destroy,
                     bg="#F44336", fg="white", font=("Arial", 9, "bold"), padx=10).pack(side=tk.LEFT, padx=5)
            
            self.statusbar.config(text=f"Документальный анализ для ГРП {grp_name} выполнен")
            
        except Exception as e:
            messagebox.showerror("Ошибка", f"Ошибка при выполнении анализа:\n{str(e)}")
            self.statusbar.config(text=f"Ошибка: {str(e)}")
    
    def show_warnings(self):
        selected = self.grp_list.selection()
        if not selected:
            messagebox.showwarning("Внимание", "Выберите ГРП!")
            return
        
        grp_id = self.grp_list.item(selected[0])['values'][0]
        grp_name = self.grp_list.item(selected[0])['values'][1]
        
        equipment_data = self.db.get_equipment_by_grp(grp_id)
        
        if not equipment_data:
            messagebox.showinfo("Информация", "У данного ГРП нет оборудования")
            return
        
        equipment_list = []
        for equip in equipment_data:
            equip_obj = Equipment(
                id=equip[0],
                grp_id=grp_id,
                name=equip[1],
                install_date=equip[2],
                removal_date=equip[3]
            )
            equipment_list.append(equip_obj)
        
        problems = self.doc_analyzer.get_current_problems(equipment_list)
        
        if len(problems['overdue']) == 0 and len(problems['near_limit']) == 0:
            messagebox.showinfo("✅ Предупреждения", "✅ Нет оборудования, требующего внимания!")
            return
        
        window = Toplevel(self.root)
        window.title(f"⚠️ Предупреждения - ГРП {grp_name}")
        window.geometry("900x600")
        window.transient(self.root)
        
        text_area = scrolledtext.ScrolledText(window, wrap=tk.WORD, font=("Courier", 10))
        text_area.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        text_area.insert(tk.END, "="*80 + "\n")
        text_area.insert(tk.END, f"⚠️ ПРЕДУПРЕЖДЕНИЯ ПО ТЕКУЩЕМУ ОБОРУДОВАНИЮ\n")
        text_area.insert(tk.END, f"ГРП: {grp_name}\n")
        text_area.insert(tk.END, "="*80 + "\n\n")
        
        if problems['overdue']:
            text_area.insert(tk.END, "❌ ОБОРУДОВАНИЕ, ПРЕВЫСИВШЕЕ НОРМУ (ТРЕБУЕТ ЗАМЕНЫ):\n")
            text_area.insert(tk.END, "-"*80 + "\n")
            for p in problems['overdue']:
                text_area.insert(tk.END, f"\n🔴 {p['name']}\n")
                text_area.insert(tk.END, f"   📅 Установлено: {p['install_date']}\n")
                text_area.insert(tk.END, f"   ⏱ Возраст: {p['age_years']:.1f} / {p['norm_years']} лет\n")
                text_area.insert(tk.END, f"   ⚠️ ПРЕВЫШЕНИЕ: {p['exceeded']:.1f} лет!\n")
        
        if problems['near_limit']:
            text_area.insert(tk.END, "\n⚠️ ОБОРУДОВАНИЕ, КОТОРОЕ ПРЕВЫСИТ НОРМУ В ТЕЧЕНИЕ ГОДА:\n")
            text_area.insert(tk.END, "-"*80 + "\n")
            for p in problems['near_limit']:
                text_area.insert(tk.END, f"\n🟡 {p['name']}\n")
                text_area.insert(tk.END, f"   📅 Установлено: {p['install_date']}\n")
                text_area.insert(tk.END, f"   ⏱ Возраст: {p['age_years']:.1f} / {p['norm_years']} лет\n")
                text_area.insert(tk.END, f"   ⏰ Осталось: {p['left_years']:.1f} лет\n")
        
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
        tk.Button(btn_frame, text="💾 Сохранить", command=export_warnings,
                 bg="#2196F3", fg="white", font=("Arial", 9, "bold"), padx=10).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="✖ Закрыть", command=window.destroy,
                 bg="#F44336", fg="white", font=("Arial", 9, "bold"), padx=10).pack(side=tk.LEFT, padx=5)
    
    def add_norm(self):
        window = Toplevel(self.root)
        window.title("Добавить документальную норму")
        window.geometry("500x400")
        window.transient(self.root)
        window.grab_set()
        
        tk.Label(window, text="📋 Добавление документальной нормы", 
                 font=("Arial", 14, "bold"), fg="#4CAF50").pack(pady=10)
        
        frame = tk.Frame(window)
        frame.pack(pady=10)
        
        tk.Label(frame, text="Наименование оборудования:", font=("Arial", 10)).grid(row=0, column=0, sticky=tk.W, pady=5)
        name_entry = tk.Entry(frame, width=40)
        name_entry.grid(row=0, column=1, pady=5)
        
        tk.Label(frame, text="Максимальный срок службы (лет):", font=("Arial", 10)).grid(row=1, column=0, sticky=tk.W, pady=5)
        years_entry = tk.Entry(frame, width=20)
        years_entry.grid(row=1, column=1, pady=5)
        
        tk.Label(frame, text="Примечания:", font=("Arial", 10)).grid(row=2, column=0, sticky=tk.W, pady=5)
        notes_entry = tk.Entry(frame, width=40)
        notes_entry.grid(row=2, column=1, pady=5)
        
        def save():
            try:
                name = name_entry.get().strip()
                if not name:
                    messagebox.showerror("Ошибка", "Введите наименование оборудования!")
                    return
                
                years = float(years_entry.get())
                if years <= 0:
                    messagebox.showerror("Ошибка", "Срок службы должен быть больше 0!")
                    return
                
                self.db.add_norm(name, years, notes_entry.get())
                messagebox.showinfo("Успех", "✅ Норма добавлена!")
                window.destroy()
                self.refresh_norms_table()
                self.statusbar.config(text=f"Добавлена норма для: {name}")
            except ValueError:
                messagebox.showerror("Ошибка", "Неверный формат числа!")
            except Exception as e:
                messagebox.showerror("Ошибка", str(e))
        
        btn_frame = tk.Frame(window)
        btn_frame.pack(pady=20)
        tk.Button(btn_frame, text="💾 Сохранить", command=save, 
                 bg="#4CAF50", fg="white", font=("Arial", 10, "bold"), padx=20).pack(side=tk.LEFT, padx=10)
        tk.Button(btn_frame, text="❌ Отмена", command=window.destroy, 
                 bg="#F44336", fg="white", font=("Arial", 10, "bold"), padx=20).pack(side=tk.LEFT, padx=10)
    
    def edit_norm(self):
        selected = self.norms_tree.selection()
        if not selected:
            messagebox.showwarning("Внимание", "Выберите норму для редактирования!")
            return
        
        norm_id = self.norms_tree.item(selected[0])['values'][0]
        norm_data = self.db.get_all_norms()
        norm = next((n for n in norm_data if n[0] == norm_id), None)
        
        if not norm:
            return
        
        window = Toplevel(self.root)
        window.title("Редактировать норму")
        window.geometry("500x400")
        window.transient(self.root)
        window.grab_set()
        
        tk.Label(window, text="✏ Редактирование нормы", 
                 font=("Arial", 14, "bold"), fg="#FF9800").pack(pady=10)
        
        frame = tk.Frame(window)
        frame.pack(pady=10)
        
        tk.Label(frame, text="Наименование оборудования:", font=("Arial", 10)).grid(row=0, column=0, sticky=tk.W, pady=5)
        name_entry = tk.Entry(frame, width=40)
        name_entry.insert(0, norm[1])
        name_entry.grid(row=0, column=1, pady=5)
        
        tk.Label(frame, text="Максимальный срок службы (лет):", font=("Arial", 10)).grid(row=1, column=0, sticky=tk.W, pady=5)
        years_entry = tk.Entry(frame, width=20)
        years_entry.insert(0, str(norm[2]))
        years_entry.grid(row=1, column=1, pady=5)
        
        tk.Label(frame, text="Примечания:", font=("Arial", 10)).grid(row=2, column=0, sticky=tk.W, pady=5)
        notes_entry = tk.Entry(frame, width=40)
        notes_entry.insert(0, norm[3] if norm[3] else "")
        notes_entry.grid(row=2, column=1, pady=5)
        
        def save():
            try:
                name = name_entry.get().strip()
                if not name:
                    messagebox.showerror("Ошибка", "Введите наименование оборудования!")
                    return
                
                years = float(years_entry.get())
                if years <= 0:
                    messagebox.showerror("Ошибка", "Срок службы должен быть больше 0!")
                    return
                
                self.db.update_norm(norm_id, name, years, notes_entry.get())
                messagebox.showinfo("Успех", "✅ Норма обновлена!")
                window.destroy()
                self.refresh_norms_table()
                self.statusbar.config(text=f"Обновлена норма для: {name}")
            except ValueError:
                messagebox.showerror("Ошибка", "Неверный формат числа!")
            except Exception as e:
                messagebox.showerror("Ошибка", str(e))
        
        btn_frame = tk.Frame(window)
        btn_frame.pack(pady=20)
        tk.Button(btn_frame, text="💾 Сохранить", command=save, 
                 bg="#4CAF50", fg="white", font=("Arial", 10, "bold"), padx=20).pack(side=tk.LEFT, padx=10)
        tk.Button(btn_frame, text="❌ Отмена", command=window.destroy, 
                 bg="#F44336", fg="white", font=("Arial", 10, "bold"), padx=20).pack(side=tk.LEFT, padx=10)
    
    def delete_norm(self):
        selected = self.norms_tree.selection()
        if not selected:
            messagebox.showwarning("Внимание", "Выберите норму для удаления!")
            return
        
        norm_id = self.norms_tree.item(selected[0])['values'][0]
        norm_name = self.norms_tree.item(selected[0])['values'][1]
        
        if messagebox.askyesno("Подтверждение", f"Удалить норму для '{norm_name}'?"):
            self.db.delete_norm(norm_id)
            messagebox.showinfo("Успех", "Норма удалена!")
            self.refresh_norms_table()
            self.statusbar.config(text=f"Удалена норма для: {norm_name}")
    
    def refresh_norms_table(self):
        for row in self.norms_tree.get_children():
            self.norms_tree.delete(row)
        
        norms = self.db.get_all_norms()
        for norm in norms:
            self.norms_tree.insert('', tk.END, values=norm)
    
    def add_tech_diagnostic(self):
        if not self.tech_grp_combo.get():
            messagebox.showwarning("Внимание", "Выберите ГРП!")
            return
        
        grp_id = int(self.tech_grp_combo.get().split(" - ")[0])
        
        window = Toplevel(self.root)
        window.title("Техническое диагностирование")
        window.geometry("500x550")
        window.transient(self.root)
        window.grab_set()
        
        tk.Label(window, text="🔧 Техническое диагностирование", 
                 font=("Arial", 14, "bold"), fg="#2196F3").pack(pady=10)
        
        frame = tk.Frame(window)
        frame.pack(pady=10)
        
        tk.Label(frame, text="Коэффициент A (0 или 0.1):", font=("Arial", 10)).grid(row=0, column=0, sticky=tk.W, pady=5)
        a_entry = tk.Entry(frame, width=20)
        a_entry.insert(0, "0")
        a_entry.grid(row=0, column=1, pady=5)
        
        tk.Label(frame, text="n - количество оборудования с неисправностями:", font=("Arial", 10)).grid(row=1, column=0, sticky=tk.W, pady=5)
        n_entry = tk.Entry(frame, width=20)
        n_entry.grid(row=1, column=1, pady=5)
        
        tk.Label(frame, text="u - общее количество оборудования:", font=("Arial", 10)).grid(row=2, column=0, sticky=tk.W, pady=5)
        u_entry = tk.Entry(frame, width=20)
        u_entry.grid(row=2, column=1, pady=5)
        
        tk.Label(frame, text="m - количество соединений с утечками:", font=("Arial", 10)).grid(row=3, column=0, sticky=tk.W, pady=5)
        m_entry = tk.Entry(frame, width=20)
        m_entry.grid(row=3, column=1, pady=5)
        
        tk.Label(frame, text="r - общее количество соединений:", font=("Arial", 10)).grid(row=4, column=0, sticky=tk.W, pady=5)
        r_entry = tk.Entry(frame, width=20)
        r_entry.grid(row=4, column=1, pady=5)
        
        def calculate_and_save():
            try:
                a = float(a_entry.get())
                n = int(n_entry.get()) if n_entry.get() else 0
                u = int(u_entry.get()) if u_entry.get() else 1
                m = int(m_entry.get()) if m_entry.get() else 0
                r = int(r_entry.get()) if r_entry.get() else 1
                
                analyzer = TechnicalAnalyzer(
                    host='localhost',
                    port='5432',
                    database='grp_analyzer',
                    user='postgres',
                    password='Dzanatyt2003'
                )
                
                b = analyzer.calculate_coefficient_b(n, u)
                c = analyzer.calculate_coefficient_c(m, r)
                k = analyzer.calculate_coefficient_k(a, b, c)
                
                coef_data = {
                    'a': a,
                    'b': b,
                    'c': c,
                    'k': k,
                    'n': n,
                    'u': u,
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
                
                Оценка состояния: {rating}
                Рекомендация: {rec}
                """
                
                messagebox.showinfo("Результаты", result_text)
                window.destroy()
                self.load_tech_history()
                self.statusbar.config(text=f"Техническая диагностика для ГРП #{grp_id} выполнена")
                
            except Exception as e:
                messagebox.showerror("Ошибка", str(e))
        
        btn_frame = tk.Frame(window)
        btn_frame.pack(pady=20)
        tk.Button(btn_frame, text="🧮 Рассчитать и сохранить", command=calculate_and_save, 
                 bg="#4CAF50", fg="white", font=("Arial", 10, "bold"), padx=20).pack(side=tk.LEFT, padx=10)
        tk.Button(btn_frame, text="❌ Отмена", command=window.destroy, 
                 bg="#F44336", fg="white", font=("Arial", 10, "bold"), padx=20).pack(side=tk.LEFT, padx=10)
    
    def load_tech_history(self):
        if not self.tech_grp_combo.get():
            return
        
        grp_id = int(self.tech_grp_combo.get().split(" - ")[0])
        coefficients = self.db.get_technical_coefficients(grp_id)
        
        for row in self.tech_tree.get_children():
            self.tech_tree.delete(row)
        
        for coef in coefficients:
            self.tech_tree.insert('', tk.END, values=(
                coef[0],     # ID
                coef[10],    # Дата
                coef[2],     # A
                f"{coef[3]:.4f}",  # B
                f"{coef[4]:.4f}",  # C
                f"{coef[5]:.4f}",  # K
                coef[6],     # n
                coef[7],     # u
                coef[8],     # m
                coef[9]      # r
            ))
        
        self.statusbar.config(text=f"Загружена история для ГРП #{grp_id}: {len(coefficients)} записей")
    
    def show_statistics(self):
        if not self.stats_grp_combo.get():
            messagebox.showwarning("Внимание", "Выберите ГРП!")
            return
        
        grp_id = int(self.stats_grp_combo.get().split(" - ")[0])
        equipment_data = self.db.get_equipment_by_grp(grp_id)
        
        if not equipment_data:
            self.stats_text.delete(1.0, tk.END)
            self.stats_text.insert(tk.END, "❌ Нет данных об оборудовании")
            return
        
        equipment_list = []
        for equip in equipment_data:
            equip_obj = Equipment(
                id=equip[0],
                grp_id=grp_id,
                name=equip[1],
                install_date=equip[2],
                removal_date=equip[3]
            )
            equipment_list.append(equip_obj)
        
        analyzer = StatisticsAnalyzer(equipment_list)
        stats = analyzer.calculate_statistics()
        
        self.stats_text.delete(1.0, tk.END)
        
        self.stats_text.insert(tk.END, "="*70 + "\n")
        self.stats_text.insert(tk.END, "📊 ОБЩАЯ СТАТИСТИКА ПО ВСЕМУ ОБОРУДОВАНИЮ\n")
        self.stats_text.insert(tk.END, "="*70 + "\n\n")
        
        if stats['count'] == 0:
            self.stats_text.insert(tk.END, "❌ Нет данных для анализа!\n")
            return
        
        self.stats_text.insert(tk.END, f"📊 Количество образцов: {stats['count']} шт.\n")
        self.stats_text.insert(tk.END, f"📈 СРЕДНЕЕ время жизни: {stats['mean']:.1f} мес. ({stats['mean']/12:.1f} лет)\n")
        self.stats_text.insert(tk.END, f"📉 МЕДИАНА время жизни: {stats['median']:.1f} мес. ({stats['median']/12:.1f} лет)\n")
        self.stats_text.insert(tk.END, f"📏 Стандартное отклонение: {stats['std']:.1f} мес.\n")
        self.stats_text.insert(tk.END, f"🔽 Минимальное: {stats['min']:.1f} мес. ({stats['min']/12:.1f} лет)\n")
        self.stats_text.insert(tk.END, f"🔼 Максимальное: {stats['max']:.1f} мес. ({stats['max']/12:.1f} лет)\n")
        
        self.stats_text.config(state=tk.DISABLED)
        self.statusbar.config(text=f"Статистика для ГРП #{grp_id} загружена")
    
    def check_equipment_stats(self):
        if not self.stats_grp_combo.get():
            messagebox.showwarning("Внимание", "Выберите ГРП!")
            return
        
        grp_id = int(self.stats_grp_combo.get().split(" - ")[0])
        equipment_data = self.db.get_equipment_by_grp(grp_id)
        
        if not equipment_data:
            messagebox.showinfo("Информация", "Нет данных об оборудовании")
            return
        
        select_window = Toplevel(self.root)
        select_window.title("Выбор оборудования для анализа")
        select_window.geometry("500x500")
        select_window.transient(self.root)
        select_window.grab_set()
        
        tk.Label(select_window, text="🔍 Выберите оборудование:", font=("Arial", 12, "bold")).pack(pady=10)
        
        unique_names = list(set([e[1] for e in equipment_data]))
        unique_names.sort()
        
        list_frame = tk.Frame(select_window)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        
        scrollbar = tk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        listbox = tk.Listbox(list_frame, height=15, font=("Arial", 10), yscrollcommand=scrollbar.set)
        for name in unique_names:
            count = sum(1 for e in equipment_data if e[1] == name)
            listbox.insert(tk.END, f"{name}  ({count} шт.)")
        listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=listbox.yview)
        
        def analyze_selected():
            selected = listbox.curselection()
            if not selected:
                messagebox.showwarning("Внимание", "Выберите оборудование!")
                return
            
            selected_text = listbox.get(selected[0])
            equip_name = selected_text.split("  (")[0]
            select_window.destroy()
            
            filtered_equipment = []
            for equip in equipment_data:
                if equip[1] == equip_name:
                    equip_obj = Equipment(
                        id=equip[0],
                        grp_id=grp_id,
                        name=equip[1],
                        install_date=equip[2],
                        removal_date=equip[3]
                    )
                    filtered_equipment.append(equip_obj)
            
            analyzer = StatisticsAnalyzer(filtered_equipment)
            stats = analyzer.calculate_statistics()
            norm = analyzer.get_norm_for_equipment(equip_name)
            
            result_window = Toplevel(self.root)
            result_window.title(f"Статистика: {equip_name}")
            result_window.geometry("850x650")
            result_window.transient(self.root)
            
            text_area = scrolledtext.ScrolledText(result_window, wrap=tk.WORD, font=("Courier", 10))
            text_area.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
            
            text_area.insert(tk.END, "="*80 + "\n")
            text_area.insert(tk.END, f"📊 СТАТИСТИКА ОБОРУДОВАНИЯ: {equip_name}\n")
            text_area.insert(tk.END, "="*80 + "\n\n")
            
            text_area.insert(tk.END, f"📊 Количество образцов: {stats['count']} шт.\n")
            text_area.insert(tk.END, f"📈 СРЕДНЕЕ время жизни: {stats['mean']:.1f} мес. ({stats['mean']/12:.1f} лет)\n")
            text_area.insert(tk.END, f"📉 МЕДИАНА время жизни: {stats['median']:.1f} мес. ({stats['median']/12:.1f} лет)\n")
            text_area.insert(tk.END, f"📏 Стандартное отклонение: {stats['std']:.1f} мес.\n")
            text_area.insert(tk.END, f"🔽 Минимальное: {stats['min']:.1f} мес. ({stats['min']/12:.1f} лет)\n")
            text_area.insert(tk.END, f"🔼 Максимальное: {stats['max']:.1f} мес. ({stats['max']/12:.1f} лет)\n\n")
            
            text_area.insert(tk.END, "="*80 + "\n")
            text_area.insert(tk.END, "📋 ПОДРОБНЫЙ СПИСОК ВСЕХ ЭКЗЕМПЛЯРОВ:\n")
            text_area.insert(tk.END, "="*80 + "\n\n")
            
            for i, equip in enumerate(filtered_equipment, 1):
                lifetime = equip.lifetime_months
                if lifetime:
                    lifetime_years = lifetime / 12
                    install_year = equip.install_date[:4] if equip.install_date else "?"
                    removal_info = equip.removal_date[:4] if equip.removal_date else "в эксплуатации"
                    
                    if norm:
                        if lifetime_years > norm:
                            status = "❌ ПРЕВЫШЕНИЕ"
                        elif lifetime_years >= norm - 1:
                            status = "⚠️ СКОРО ЗАМЕНА"
                        else:
                            status = "✅ НОРМА"
                    else:
                        status = "❓ НЕТ НОРМЫ"
                    
                    text_area.insert(tk.END, f"{i:2d}. {equip.name}\n")
                    text_area.insert(tk.END, f"     📅 Установка: {equip.install_date} → {removal_info}\n")
                    text_area.insert(tk.END, f"     ⏱ Время жизни: {lifetime:.1f} мес. ({lifetime_years:.1f} лет)  {status}\n\n")
            
            if norm:
                text_area.insert(tk.END, f"\n📋 Документальная норма: {norm} лет\n")
                if stats['mean']/12 > norm:
                    text_area.insert(tk.END, "⚠️ СРЕДНЕЕ время жизни ПРЕВЫШАЕТ норму!\n")
                elif stats['median']/12 > norm:
                    text_area.insert(tk.END, "⚠️ МЕДИАННОЕ время жизни ПРЕВЫШАЕТ норму!\n")
                else:
                    text_area.insert(tk.END, "✅ Среднее и медианное время жизни в пределах нормы\n")
                
                exceeded_count = sum(1 for e in filtered_equipment if e.lifetime_months and (e.lifetime_months/12) > norm)
                text_area.insert(tk.END, f"\n📊 Из {stats['count']} экземпляров:\n")
                text_area.insert(tk.END, f"   • Превысили норму: {exceeded_count} шт.\n")
                text_area.insert(tk.END, f"   • В пределах нормы: {stats['count'] - exceeded_count} шт.\n")
            
            text_area.config(state=tk.DISABLED)
            
            btn_frame = tk.Frame(result_window)
            btn_frame.pack(pady=10)
            
            def export_stats():
                filename = filedialog.asksaveasfilename(
                    defaultextension=".txt",
                    filetypes=[("Text files", "*.txt")],
                    initialfile=f"stats_{equip_name}_{datetime.now().strftime('%Y%m%d')}.txt"
                )
                if filename:
                    with open(filename, 'w', encoding='utf-8') as f:
                        f.write(text_area.get(1.0, tk.END))
                    messagebox.showinfo("Успех", f"Сохранено в:\n{filename}")
            
            tk.Button(btn_frame, text="💾 Сохранить отчет", command=export_stats,
                     bg="#2196F3", fg="white", font=("Arial", 9, "bold"), padx=10).pack(side=tk.LEFT, padx=5)
            tk.Button(btn_frame, text="✖ Закрыть", command=result_window.destroy,
                     bg="#F44336", fg="white", font=("Arial", 9, "bold"), padx=10).pack(side=tk.LEFT, padx=5)
        
        tk.Button(select_window, text="🔍 Анализировать выбранное", command=analyze_selected,
                 bg="#4CAF50", fg="white", font=("Arial", 10, "bold"), padx=15).pack(pady=10)
        tk.Button(select_window, text="❌ Отмена", command=select_window.destroy,
                 bg="#F44336", fg="white", font=("Arial", 10, "bold"), padx=15).pack(pady=5)
    
    def refresh_grp_list(self):
        for row in self.grp_list.get_children():
            self.grp_list.delete(row)
        
        grps = self.db.get_all_grp()
        for grp in grps:
            grp_id = grp[0]
            equipment = self.db.get_equipment_by_grp(grp_id)
            equip_count = len(equipment)
            self.grp_list.insert('', tk.END, values=(grp[0], grp[1], grp[2], grp[3], grp[4], equip_count))
        
        self.update_combos()
        self.statusbar.config(text=f"Обновлено: {len(grps)} ГРП")
    
    def update_combos(self):
        grps = self.db.get_all_grp()
        grp_names = [f"{grp[0]} - {grp[1]}" for grp in grps]
        
        if hasattr(self, 'tech_grp_combo'):
            self.tech_grp_combo['values'] = grp_names
            if grp_names:
                self.tech_grp_combo.set(grp_names[0])
                self.load_tech_history()
        
        if hasattr(self, 'stats_grp_combo'):
            self.stats_grp_combo['values'] = grp_names
            if grp_names:
                self.stats_grp_combo.set(grp_names[0])
    
    def open_algorithms(self):
        """Открытие окна с расчётом по алгоритмам"""
        selected = self.grp_list.selection()
        if not selected:
            messagebox.showwarning("Внимание", "Выберите ГРП для расчёта!")
            return
        
        grp_id = self.grp_list.item(selected[0])['values'][0]
        grp_name = self.grp_list.item(selected[0])['values'][1]
        
        equipment_data = self.db.get_equipment_by_grp(grp_id)
        
        if not equipment_data:
            messagebox.showinfo("Информация", "У данного ГРП нет оборудования для расчёта")
            return
        
        try:
            from algorithms_view import AlgorithmsWindow
            AlgorithmsWindow(self.root, self.db, grp_id, equipment_data)
            self.statusbar.config(text=f"Открыт расчёт алгоритмов для ГРП: {grp_name}")
        except ImportError as e:
            messagebox.showerror("Ошибка", f"Не удалось загрузить модуль algorithms_view: {e}")
        except Exception as e:
            messagebox.showerror("Ошибка", f"Ошибка при открытии окна алгоритмов: {e}")