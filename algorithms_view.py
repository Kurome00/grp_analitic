import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext

from algorithms import calculate_all_algorithms
from documentary_analyzer import DocumentaryAnalyzer


def _btn(parent, text, command, color='primary', font_size=10, padx=10):
    """Цветная кнопка с эффектом наведения."""
    palette = {
        'success': ('#4CAF50', '#388E3C'),
        'danger': ('#F44336', '#D32F2F'),
    }
    c1, c2 = palette.get(color, ('#2196F3', '#1976D2'))
    btn = tk.Button(
        parent, text=text, command=command, bg=c1, fg="white",
        font=("Arial", font_size, "bold"), padx=padx,
        bd=0, relief="flat", cursor="hand2",
        activebackground=c2, activeforeground="white",
    )
    btn.bind("<Enter>", lambda e, b=btn, bg=c2: b.config(bg=bg))
    btn.bind("<Leave>", lambda e, b=btn, bg=c1: b.config(bg=bg))
    return btn


class AlgorithmsWindow:
    """Окно для расчёта и отображения алгоритмов"""

    def __init__(self, parent, db, grp_id: int, equipment_data: list):
        self.parent = parent
        self.db = db
        self.grp_id = grp_id
        self.equipment_data = equipment_data
        self.doc_analyzer = DocumentaryAnalyzer(db)

        self.window = tk.Toplevel(parent)
        self.window.title(f"Расчёт остаточного ресурса ГРП (все алгоритмы)")
        self.window.geometry("1500x850")
        self.window.transient(parent)
        self.window.grab_set()

        self.setup_ui()
        self.calculate_and_display()

    def setup_ui(self):
        """Настройка интерфейса"""
        top_frame = tk.Frame(self.window, bg="#f0f0f0")
        top_frame.pack(fill=tk.X, padx=10, pady=10)

        tk.Label(top_frame, text="🧮 Расчёт остаточного ресурса ГРП",
                 font=("Arial", 16, "bold"), bg="#f0f0f0").pack(side=tk.LEFT)

        info_frame = tk.Frame(top_frame, bg="#f0f0f0")
        info_frame.pack(side=tk.RIGHT)

        _btn(info_frame, "🔄 Пересчитать", self.calculate_and_display,
             color='success').pack(side=tk.RIGHT, padx=5)
        _btn(info_frame, "✖ Закрыть", self.window.destroy,
             color='danger').pack(side=tk.RIGHT, padx=5)

        self.notebook = ttk.Notebook(self.window)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        self.comparison_tab = tk.Frame(self.notebook)
        self.notebook.add(self.comparison_tab, text="📊 Сравнение алгоритмов")

        self.details_tab = tk.Frame(self.notebook)
        self.notebook.add(self.details_tab, text="📋 Детальный расчёт")

        self.weak_tab = tk.Frame(self.notebook)
        self.notebook.add(self.weak_tab, text="🎯 Слабое звено")

        self.help_tab = tk.Frame(self.notebook)
        self.notebook.add(self.help_tab, text="❓ Что такое результат?")
        self.setup_help_tab()

    def setup_help_tab(self):
        """Вкладка с пояснениями"""
        help_text = scrolledtext.ScrolledText(self.help_tab, wrap=tk.WORD, font=("Arial", 11))
        help_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        help_text.insert(tk.END, """
╔══════════════════════════════════════════════════════════════════════════════╗
║                    ЧТО ТАКОЕ "РЕЗУЛЬТАТ" В АЛГОРИТМАХ?                       ║
╚══════════════════════════════════════════════════════════════════════════════╝

📊 РЕЗУЛЬТАТ — это остаточный ресурс ГРП в ГОДАХ.
    Показывает, сколько лет оборудование может ещё работать до замены.

═══════════════════════════════════════════════════════════════════════════════

🔢 РАСШИФРОВКА ЗНАЧЕНИЙ:

    > 5 лет     — Отличное состояние. Плановое обслуживание.
    3-5 лет     — Хорошее состояние. Рекомендуется диагностика.
    1-3 года    — Удовлетворительное. Требуется внимание.
    < 1 года    — Критическое! Нужна замена.
    < 0 лет     — Ресурс исчерпан! Срочная замена!

═══════════════════════════════════════════════════════════════════════════════

📋 АЛГОРИТМЫ:

    Алгоритм 0   — Утверждённая методика (базовая)
    Алгоритм 1   — Среднее арифметическое по всем элементам
    Алгоритм 2   — REGION-gaz (принцип "слабого звена")
    Алгоритм 3   — Улучшенный (слабый элемент с учётом общего состояния)
    Алгоритм 4   — Weighted Average (взвешенное среднее)

═══════════════════════════════════════════════════════════════════════════════

💡 ЧТО ТАКОЕ "СЛАБОЕ ЗВЕНО"?

    Это элемент ГРП с НАИМЕНЬШИМ остаточным ресурсом.
    Так как ГРП — последовательная система, отказ одного элемента
    приводит к отказу всего пункта.

═══════════════════════════════════════════════════════════════════════════════

🎯 КАК ИСПОЛЬЗОВАТЬ?

    1. Выберите ГРП в списке
    2. Нажмите "🧮 Расчёт по алгоритмам"
    3. Сравните результаты разных алгоритмов
    4. Ориентируйтесь на НАИМЕНЬШЕЕ значение
    5. Планируйте замену оборудования

═══════════════════════════════════════════════════════════════════════════════
""")
        help_text.config(state=tk.DISABLED)

    def calculate_and_display(self):
        """Расчёт по всем алгоритмам и отображение"""
        try:
            equipment_list = []
            for equip in self.equipment_data:
                equipment_list.append({
                    'name': equip[1] if len(equip) > 1 else '',
                    'equipment_id': equip[0] if len(equip) > 0 else None,
                    'install_date': equip[2] if len(equip) > 2 else '',
                    'removal_date': equip[3] if len(equip) > 3 else None,
                    'telemetry': {},
                })

            def parts_norm_resolver(element):
                eq_id = element.get('equipment_id')
                if eq_id is not None:
                    effective = self.doc_analyzer.get_effective_norm(eq_id, element.get('install_date'))
                    if effective is not None:
                        return effective
                return self.doc_analyzer.get_norm_for_equipment(element.get('name', ''))

            self.results = calculate_all_algorithms(
                equipment_list,
                norm_func=parts_norm_resolver
            )

            self.display_comparison()
            self.display_details()
            self.display_weak_element()

        except Exception as e:
            messagebox.showerror("Ошибка", f"Ошибка при расчёте: {e}")

    def display_comparison(self):
        """Отображение сравнительной таблицы"""
        for widget in self.comparison_tab.winfo_children():
            widget.destroy()

        header_frame = tk.Frame(self.comparison_tab, bg="#e8f0fe")
        header_frame.pack(fill=tk.X, padx=10, pady=10)

        tk.Label(header_frame, text="📊 Сравнение алгоритмов расчёта остаточного ресурса",
                 font=("Arial", 14, "bold"), bg="#e8f0fe").pack(side=tk.LEFT)

        legend_frame = tk.Frame(header_frame, bg="#e8f0fe")
        legend_frame.pack(side=tk.RIGHT)

        tk.Label(legend_frame, text="Оценка:", font=("Arial", 10, "bold"), bg="#e8f0fe").pack(side=tk.LEFT)

        colors = [
            ("Отлично (>5 лет)", "#4CAF50"),
            ("Хорошо (3-5 лет)", "#FFC107"),
            ("Удовл. (1-3 года)", "#FF9800"),
            ("Критично (<1 года)", "#F44336"),
        ]
        for text, color in colors:
            lbl = tk.Label(legend_frame, text=text, bg="#e8f0fe", font=("Arial", 9))
            lbl.pack(side=tk.LEFT, padx=5)

        frame = tk.Frame(self.comparison_tab)
        frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        columns = ("Алгоритм", "Название", "Результат (лет)", "Слабое звено", "Рекомендация")
        self.comparison_tree = ttk.Treeview(frame, columns=columns, show="headings", height=6)

        col_widths = {
            "Алгоритм": 100,
            "Название": 220,
            "Результат (лет)": 150,
            "Слабое звено": 200,
            "Рекомендация": 500
        }

        for col in columns:
            self.comparison_tree.heading(col, text=col)
            self.comparison_tree.column(col, width=col_widths.get(col, 150), minwidth=50)

        scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self.comparison_tree.yview)
        self.comparison_tree.configure(yscrollcommand=scrollbar.set)

        algo_names = {
            0: "Утверждённая методика",
            1: "Среднее арифметическое",
            2: "REGION-gaz (слабое звено)",
            3: "Улучшенный алгоритм",
            4: "Weighted Average (взвеш. среднее)"
        }

        for algo_num, result in sorted(self.results.items()):
            result_value = result.result
            weak = result.weak_element or "-"
            rec = result.recommendation

            if result_value < 1:
                status = "🔴"
                tag = 'danger'
            elif result_value < 3:
                status = "🟠"
                tag = 'warning'
            elif result_value < 5:
                status = "🟡"
                tag = 'warning'
            else:
                status = "🟢"
                tag = 'good'

            self.comparison_tree.insert('', tk.END, values=(
                f"Алг. {algo_num}",
                algo_names.get(algo_num, result.algorithm_name),
                f"{status} {result_value:.2f}",
                weak,
                rec
            ), tags=(tag,))

        self.comparison_tree.tag_configure('good', background='#d4edda')
        self.comparison_tree.tag_configure('warning', background='#fff3cd')
        self.comparison_tree.tag_configure('danger', background='#f8d7da')

        self.comparison_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        hint_frame = tk.Frame(self.comparison_tab, bg="#f8f9fa", relief=tk.RIDGE, bd=1)
        hint_frame.pack(fill=tk.X, padx=10, pady=5)
        tk.Label(hint_frame, text="💡 Ориентируйтесь на наименьшее значение результата.",
                 font=("Arial", 9), bg="#f8f9fa", fg="#6c757d").pack(pady=5)

    def display_details(self):
        """Отображение детального расчёта"""
        for widget in self.details_tab.winfo_children():
            widget.destroy()

        text_frame = tk.Frame(self.details_tab)
        text_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        text_area = scrolledtext.ScrolledText(text_frame, wrap=tk.WORD, font=("Courier", 10))
        text_area.pack(fill=tk.BOTH, expand=True)

        text_area.insert(tk.END, "=" * 90 + "\n")
        text_area.insert(tk.END, "ДЕТАЛЬНЫЙ РАСЧЁТ ПО ВСЕМ АЛГОРИТМАМ\n")
        text_area.insert(tk.END, "=" * 90 + "\n\n")

        for algo_num, result in sorted(self.results.items()):
            text_area.insert(tk.END, f"\n{'─'*90}\n")
            text_area.insert(tk.END, f"АЛГОРИТМ {algo_num}: {result.algorithm_name}\n")
            text_area.insert(tk.END, f"{'─'*90}\n")

            if result.details and 'error' in result.details:
                text_area.insert(tk.END, f"❌ {result.details['error']}\n")
                continue

            result_value = result.result

            if result_value <= 0:
                status_text = "КРИТИЧЕСКИЙ (ресурс исчерпан)"
            elif result_value < 1:
                status_text = "КРИТИЧЕСКИЙ (менее 1 года)"
            elif result_value < 3:
                status_text = "НИЗКИЙ (1-3 года)"
            elif result_value < 5:
                status_text = "СРЕДНИЙ (3-5 лет)"
            else:
                status_text = "ВЫСОКИЙ (более 5 лет)"

            text_area.insert(tk.END, f"📊 Остаточный ресурс: {result_value:.2f} лет\n")
            text_area.insert(tk.END, f"📈 Оценка состояния: {status_text}\n")

            if result.weak_element:
                text_area.insert(tk.END, f"🎯 Слабое звено: {result.weak_element}\n")

            text_area.insert(tk.END, f"💡 Рекомендация: {result.recommendation}\n")

            if result.details and 'elements' in result.details:
                text_area.insert(tk.END, f"\n📋 Детали по элементам:\n")
                text_area.insert(tk.END, f"{'─'*60}\n")

                for elem in result.details['elements']:
                    name = elem.get('name', 'Неизвестно')
                    z_element = elem.get('Z_element', 0)

                    if z_element <= 0:
                        status = "❌ КРИТИЧЕСКИ"
                    elif z_element < 1:
                        status = "🔴 Срочная замена"
                    elif z_element < 3:
                        status = "🟠 Планировать замену"
                    else:
                        status = "✅ В норме"

                    text_area.insert(tk.END, f"  • {name}: {z_element:.2f} лет  {status}\n")

                    for key, value in elem.items():
                        if key not in ['name', 'Z_element'] and isinstance(value, (int, float)):
                            text_area.insert(tk.END, f"      {key}: {value:.4f}\n")

            if algo_num == 4 and result.details and 'alpha' in result.details:
                text_area.insert(tk.END, f"\n⚙️ Параметры:\n")
                text_area.insert(tk.END, f"  α (вес календаря): {result.details['alpha']:.2f}\n")

                for elem in result.details.get('elements', []):
                    if 'Z_calendar' in elem:
                        text_area.insert(tk.END, f"  • {elem.get('name', '')}: ")
                        text_area.insert(tk.END, f"Z_календ={elem.get('Z_calendar', 0):.2f}, ")
                        text_area.insert(tk.END, f"Z_наработка={elem.get('Z_workload', 0):.2f}, ")
                        text_area.insert(tk.END, f"Z_база={elem.get('Z_base', 0):.2f}\n")

            if result.details and 'T_next_diagnosis' in result.details:
                text_area.insert(tk.END, f"\n📅 Следующее диагностирование: {result.details['T_next_diagnosis']:.1f} лет\n")

            text_area.insert(tk.END, "\n")

        text_area.config(state=tk.DISABLED)

    def display_weak_element(self):
        """Отображение слабого звена"""
        for widget in self.weak_tab.winfo_children():
            widget.destroy()

        tk.Label(self.weak_tab, text="🎯 Анализ слабого звена ГРП",
                 font=("Arial", 14, "bold")).pack(pady=10)

        info_frame = tk.LabelFrame(self.weak_tab, text="Результаты", padx=10, pady=10)
        info_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        text_area = scrolledtext.ScrolledText(info_frame, wrap=tk.WORD, font=("Courier", 10))
        text_area.pack(fill=tk.BOTH, expand=True)

        text_area.insert(tk.END, "=" * 70 + "\n")
        text_area.insert(tk.END, "СЛАБОЕ ЗВЕНО ПО АЛГОРИТМАМ\n")
        text_area.insert(tk.END, "=" * 70 + "\n\n")

        weak_elements = {}
        for algo_num, result in sorted(self.results.items()):
            if result.weak_element:
                if result.weak_element not in weak_elements:
                    weak_elements[result.weak_element] = []
                weak_elements[result.weak_element].append({
                    'algo': algo_num,
                    'name': result.algorithm_name,
                    'result': result.result
                })

        for element, data_list in weak_elements.items():
            text_area.insert(tk.END, f"🔴 {element}\n")
            text_area.insert(tk.END, f"{'─'*50}\n")
            for data in data_list:
                text_area.insert(tk.END, f"   Алг.{data['algo']} ({data['name']}): {data['result']:.2f} лет\n")
            text_area.insert(tk.END, "\n")

        text_area.insert(tk.END, "=" * 70 + "\n")
        text_area.insert(tk.END, "РЕКОМЕНДАЦИИ\n")
        text_area.insert(tk.END, "=" * 70 + "\n")

        min_algo = min(self.results.items(), key=lambda x: x[1].result)
        text_area.insert(tk.END, f"\n⚠️ Наиболее критичный алгоритм: {min_algo[1].algorithm_name}\n")
        text_area.insert(tk.END, f"   Остаточный ресурс: {min_algo[1].result:.2f} лет\n")
        if min_algo[1].weak_element:
            text_area.insert(tk.END, f"   Слабое звено: {min_algo[1].weak_element}\n")
        text_area.insert(tk.END, f"\n💡 {min_algo[1].recommendation}\n")

        if min_algo[1].result <= 0:
            text_area.insert(tk.END, "\n🚨 КРИТИЧЕСКОЕ СОСТОЯНИЕ! Требуется немедленная замена оборудования!\n")
        elif min_algo[1].result < 1:
            text_area.insert(tk.END, "\n⚠️ Остаточный ресурс менее 1 года. Срочно планируйте замену!\n")
        elif min_algo[1].result < 3:
            text_area.insert(tk.END, "\n⚠️ Рекомендуется замена в течение 1-2 лет.\n")

        text_area.config(state=tk.DISABLED)