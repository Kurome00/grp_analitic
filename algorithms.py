"""
Модуль с реализацией алгоритмов расчёта остаточного ресурса ГРП.
Основан на документе "Алгоритмы-4.pdf".
"""

from datetime import date, datetime
from typing import Callable, Dict, List, Optional
from dataclasses import dataclass

from config import EQUIPMENT_NORMS


@dataclass
class AlgorithmResult:
    """Результат расчёта по алгоритму"""
    algorithm_name: str
    algorithm_number: int
    result: float  # Остаточный ресурс в годах
    weak_element: Optional[str] = None  # Слабое звено (для алгоритмов 2,3,4)
    details: Dict = None  # Детали расчёта
    recommendation: str = ""  # Рекомендация


class GRPResourceCalculator:
    """Калькулятор остаточного ресурса ГРП по различным алгоритмам"""

    def __init__(self, norm_func: Optional[Callable[[str], Optional[float]]] = None):
        # Критические элементы ГРП (для алгоритмов 2,3,4)
        self.critical_elements = [
            'Регулятор давления',
            'ПЗК (предохранительно-запорный клапан)',
            'ПСК (предохранительно-сбросный клапан)',
            'Фильтр',
            'Запорная арматура'
        ]

        # Вес календарного ресурса в алгоритме 4 (0.5-0.8)
        self.alpha = 0.6
        # Порог переработки (лет), ниже которого используется календарный ресурс
        self.T_crit = 5

        self.norm_func = norm_func

    def get_equipment_age(self, install_date: str, removal_date: Optional[str] = None) -> float:
        """Расчёт возраста оборудования в годах"""
        try:
            install = datetime.strptime(install_date, '%Y-%m-%d').date()
            if removal_date:
                end = datetime.strptime(removal_date, '%Y-%m-%d').date()
            else:
                end = date.today()
            return (end - install).days / 365.25
        except Exception:
            return 0.0

    def get_norm_for_element(self, element: Dict) -> Optional[float]:
        """Нормативный срок для элемента.

        Через переданный norm_func(element) — например, нормы по запчастям
        (equipment_id внутри element), иначе базовые нормы config.
        Возвращает None, если норма не найдена.
        """
        if self.norm_func:
            norm = self.norm_func(element)
            if norm is not None:
                return float(norm)

        name = element.get('name', '')
        for key, years in EQUIPMENT_NORMS.items():
            if key in name or name in key:
                return float(years)
        return None

    def _prepare_elements(self, equipment_data: List[Dict], critical_only: bool = False) -> List[Dict]:
        """Отбирает элементы с датой установки и известной нормой."""
        elements = []
        for equip in equipment_data:
            name = equip.get('name', '')
            install_date = equip.get('install_date', '')
            if not install_date:
                continue

            if critical_only and not any(c in name for c in self.critical_elements):
                continue

            element = {
                'name': name,
                'equipment_id': equip.get('equipment_id'),
                'install_date': install_date,
                'age': self.get_equipment_age(install_date, equip.get('removal_date')),
                'removed': bool(equip.get('removal_date')),
                'telemetry': equip.get('telemetry', {})
            }

            norm = self.get_norm_for_element(element)
            if norm is None:
                continue

            element['norm'] = norm
            elements.append(element)
        return elements

    def _calculate_state_coefficient(self, age: float, norm: float) -> float:
        """Коэффициент технического состояния K_сост (непрерывный, на основе возраста)"""
        if norm > 0:
            ratio = min(age / norm, 1.5)
            k = max(0.0, 1 - ratio * 0.3)
        else:
            k = 1.0
        return max(0.1, min(1.0, k))

    def _calculate_common_technical_coefficient(self, elements: List[Dict]) -> float:
        """Обобщённый технический коэффициент (среднее геометрическое K_сост)"""
        if not elements:
            return 1.0
        product = 1.0
        for e in elements:
            product *= e['K_state']
        return product ** (1 / len(elements))

    def _empty_result(self, name: str, number: int) -> AlgorithmResult:
        return AlgorithmResult(
            algorithm_name=name,
            algorithm_number=number,
            result=0,
            details={'error': 'Нет данных для расчёта'},
            recommendation="Нет данных для расчёта"
        )

    def _get_recommendation(self, resource: float, weak: Optional[Dict]) -> str:
        """Формирование рекомендации"""
        if resource <= 0:
            return "🚨 КРИТИЧЕСКОЕ СОСТОЯНИЕ! Требуется немедленная замена оборудования!"
        elif resource < 1:
            return "⚠️ Остаточный ресурс менее 1 года. Рекомендуется срочная замена!"
        elif resource < 3:
            return f"⚠️ Остаточный ресурс {resource:.1f} лет. Рекомендуется планировать замену в ближайшее время."
        elif resource < 5:
            return f"ℹ️ Остаточный ресурс {resource:.1f} лет. Плановое диагностирование через 1-2 года."
        else:
            return f"✅ Остаточный ресурс {resource:.1f} лет. Состояние удовлетворительное."

    def calculate_algorithm_0(self, equipment_data: List[Dict]) -> AlgorithmResult:
        """
        Алгоритм 0 - Утверждённая методика.
        Z_ГРП = средний остаточный ресурс по всем элементам (Z = S_назн - S_факт).
        """
        results = []
        for e in self._prepare_elements(equipment_data):
            resource = 0.0 if e['removed'] else max(0.0, e['norm'] - e['age'])
            results.append({'name': e['name'], 'age': e['age'], 'norm': e['norm'], 'resource': resource})

        if not results:
            return self._empty_result("Утверждённая методика", 0)

        avg_resource = sum(r['resource'] for r in results) / len(results)
        weak = min(results, key=lambda r: r['resource'])

        return AlgorithmResult(
            algorithm_name="Утверждённая методика",
            algorithm_number=0,
            result=avg_resource,
            weak_element=weak['name'],
            details={'elements': results, 'avg_resource': avg_resource, 'weak': weak},
            recommendation=self._get_recommendation(avg_resource, weak)
        )

    def calculate_algorithm_1(self, equipment_data: List[Dict]) -> AlgorithmResult:
        """
        Алгоритм 1 - Среднее арифметическое.
        Z_ГРП = (Σ Z_элемент) / m * K_общ, где K_общ = среднее K_сост.
        """
        results = []
        for e in self._prepare_elements(equipment_data):
            z_base = max(0.0, e['norm'] - e['age']) if not e['removed'] else 0.0
            k_state = self._calculate_state_coefficient(e['age'], e['norm'])
            results.append({
                'name': e['name'],
                'Z_base': z_base,
                'K_state': k_state,
                'Z_element': max(0.0, z_base * k_state)
            })

        if not results:
            return self._empty_result("Среднее арифметическое", 1)

        avg_z = sum(r['Z_element'] for r in results) / len(results)
        k_common = sum(r['K_state'] for r in results) / len(results)
        z_grp = avg_z * k_common
        weak = min(results, key=lambda r: r['Z_element'])

        return AlgorithmResult(
            algorithm_name="Среднее арифметическое",
            algorithm_number=1,
            result=max(0.0, z_grp),
            weak_element=weak['name'],
            details={'elements': results, 'avg_Z': avg_z, 'K_common': k_common, 'Z_grp': z_grp, 'weak': weak},
            recommendation=self._get_recommendation(z_grp, weak)
        )

    def calculate_algorithm_2(self, equipment_data: List[Dict]) -> AlgorithmResult:
        """
        Алгоритм 2 - REGION-gaz (принцип "слабого звена").
        Z_ГРП = min(Z_элемент) по критическим элементам.
        """
        results = []
        for e in self._prepare_elements(equipment_data, critical_only=True):
            z_base = max(0.0, e['norm'] - e['age']) if not e['removed'] else 0.0
            k_state = self._calculate_state_coefficient(e['age'], e['norm'])
            results.append({
                'name': e['name'],
                'Z_base': z_base,
                'K_state': k_state,
                'Z_element': max(0.0, z_base * k_state)
            })

        if not results:
            return self._empty_result("REGION-gaz (слабое звено)", 2)

        weak = min(results, key=lambda r: r['Z_element'])
        z_grp = weak['Z_element']
        t_next = min(z_grp * 0.5, 5)

        return AlgorithmResult(
            algorithm_name="REGION-gaz (слабое звено)",
            algorithm_number=2,
            result=z_grp,
            weak_element=weak['name'],
            details={
                'elements': results,
                'Z_weak': z_grp,
                'Z_grp': z_grp,
                'T_next_diagnosis': t_next,
                'weak': weak
            },
            recommendation=f"Слабое звено: {weak['name']}. Следующее диагностирование через {t_next:.1f} лет."
        )

    def calculate_algorithm_3(self, equipment_data: List[Dict]) -> AlgorithmResult:
        """
        Алгоритм 3 - Улучшенный (слабое звено с учётом общего состояния).
        Z_ГРП = min(Z_элемент) * K_общ_тех (среднее геометрическое K_сост).
        """
        results = []
        for e in self._prepare_elements(equipment_data, critical_only=True):
            z_base = max(0.0, e['norm'] - e['age']) if not e['removed'] else 0.0
            k_state = self._calculate_state_coefficient(e['age'], e['norm'])
            results.append({
                'name': e['name'],
                'Z_base': z_base,
                'K_state': k_state,
                'Z_element': max(0.0, z_base * k_state)
            })

        if not results:
            return self._empty_result("Улучшенный алгоритм", 3)

        weak = min(results, key=lambda r: r['Z_element'])
        k_common_tech = self._calculate_common_technical_coefficient(results)
        z_grp = weak['Z_element'] * k_common_tech
        t_next = min(z_grp * 0.5, 5)

        return AlgorithmResult(
            algorithm_name="Улучшенный алгоритм",
            algorithm_number=3,
            result=max(0.0, z_grp),
            weak_element=weak['name'],
            details={
                'elements': results,
                'Z_weak': weak['Z_element'],
                'K_common_tech': k_common_tech,
                'Z_grp': z_grp,
                'T_next_diagnosis': t_next,
                'weak': weak
            },
            recommendation=f"Слабое звено: {weak['name']}. Следующее диагностирование через {t_next:.1f} лет."
        )

    def calculate_algorithm_4(self, equipment_data: List[Dict]) -> AlgorithmResult:
        """
        Алгоритм 4 - Weighted Average (взвешенное среднее).
        Z_база = α * Z_календ + (1-α) * Z_наработка.
        Z_наработка берётся из телеметрии, при её отсутствии = Z_календ.
        """
        results = []
        for e in self._prepare_elements(equipment_data, critical_only=True):
            age = e['age']
            norm = e['norm']
            telemetry = e['telemetry']

            z_calendar = norm - age

            # Ресурс по наработке (из телеметрии)
            if telemetry.get('norm_hours'):
                h_norm = float(telemetry.get('norm_hours', 0))
                h_fact = float(telemetry.get('fact_hours', 0))
                z_workload = (h_norm - h_fact) / h_norm * norm if h_norm > 0 else z_calendar
            else:
                z_workload = z_calendar

            # Защита от абсурдных решений при сильной переработке
            if z_calendar < -self.T_crit:
                z_base = z_calendar
            else:
                z_base = self.alpha * z_calendar + (1 - self.alpha) * z_workload

            k_state = self._calculate_state_coefficient(age, norm)
            z_element = max(0.0, z_base * k_state) if not e['removed'] else 0.0

            results.append({
                'name': e['name'],
                'Z_calendar': z_calendar,
                'Z_workload': z_workload,
                'Z_base': z_base,
                'K_state': k_state,
                'Z_element': z_element
            })

        if not results:
            return self._empty_result("Weighted Average (взвешенное среднее)", 4)

        weak = min(results, key=lambda r: r['Z_element'])
        k_common_tech = self._calculate_common_technical_coefficient(results)
        z_grp = weak['Z_element'] * k_common_tech
        t_next = min(z_grp * 0.5, 5)

        return AlgorithmResult(
            algorithm_name="Weighted Average (взвешенное среднее)",
            algorithm_number=4,
            result=max(0.0, z_grp),
            weak_element=weak['name'],
            details={
                'elements': results,
                'Z_weak': weak['Z_element'],
                'K_common_tech': k_common_tech,
                'Z_grp': z_grp,
                'T_next_diagnosis': t_next,
                'weak': weak,
                'alpha': self.alpha
            },
            recommendation=f"Слабое звено: {weak['name']}. Следующее диагностирование через {t_next:.1f} лет."
        )


def calculate_all_algorithms(equipment_data: List[Dict],
                             norm_func: Optional[Callable[[str], Optional[float]]] = None) -> Dict[int, AlgorithmResult]:
    """Расчёт по всем алгоритмам"""
    calculator = GRPResourceCalculator(norm_func)

    return {
        0: calculator.calculate_algorithm_0(equipment_data),
        1: calculator.calculate_algorithm_1(equipment_data),
        2: calculator.calculate_algorithm_2(equipment_data),
        3: calculator.calculate_algorithm_3(equipment_data),
        4: calculator.calculate_algorithm_4(equipment_data),
    }