"""
Модуль с реализацией алгоритмов расчёта остаточного ресурса ГРП
Основан на документе "Алгоритмы-4.pdf"
"""

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime, date
import math


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
    
    def __init__(self):
        # Критические элементы ГРП
        self.critical_elements = [
            'Регулятор давления',
            'ПЗК (предохранительно-запорный клапан)',
            'ПСК (предохранительно-сбросный клапан)',
            'Фильтр',
            'Запорная арматура'
        ]
        
        # Весовые коэффициенты (калибруются)
        self.alpha = 0.6  # вес календарного ресурса (0.5-0.8)
        self.beta = 0.3   # вес повреждений
        self.gamma = 0.2  # вес качества ТО
        self.delta = 0.3  # вес качества ремонта
        self.theta = 0.2  # вес условий эксплуатации
        self.T_crit = 5   # порог переработки (лет)
    
    def get_equipment_age(self, install_date: str, removal_date: Optional[str] = None) -> float:
        """Расчёт возраста оборудования в годах"""
        try:
            install = datetime.strptime(install_date, '%Y-%m-%d').date()
            if removal_date:
                end = datetime.strptime(removal_date, '%Y-%m-%d').date()
            else:
                end = date.today()
            return (end - install).days / 365.25
        except:
            return 0
    
    def get_norm_for_equipment(self, equipment_name: str) -> float:
        """Получение нормативного срока для оборудования"""
        norms = {
            'Редукционная арматура (РА)': 15,
            'Запорная арматура (ЗА1)': 12,
            'Запорная арматура (ЗА2)': 12,
            'Запорная арматура (ЗА3)': 12,
            'Запорная арматура (ЗА4)': 12,
            'Запорная арматура (ЗА5)': 12,
            'Запорная арматура (ЗА6)': 12,
            'Запорная арматура (ЗА7)': 12,
            'Предохранительная арматура (ПА)': 10,
            'Отключающая арматура (ОА)': 12,
            'Фильтр (Ф)': 8,
            'Регулятор давления': 10,
            'ПЗК': 12,
            'ПСК': 10,
            'Запорная арматура': 15,
        }
        for key, norm in norms.items():
            if key in equipment_name or equipment_name in key:
                return norm
        return 20  # По умолчанию 20 лет
    
    def calculate_algorithm_0(self, equipment_data: List[Dict]) -> AlgorithmResult:
        """
        Алгоритм 0 - Утверждённая методика
        Z = S_назн - S_факт
        """
        results = []
        details = {}
        
        for equip in equipment_data:
            name = equip.get('name', '')
            install_date = equip.get('install_date', '')
            removal_date = equip.get('removal_date', None)
            
            if not install_date:
                continue
            
            age = self.get_equipment_age(install_date, removal_date)
            norm = self.get_norm_for_equipment(name)
            resource = norm - age
            
            # Если оборудование демонтировано, ресурс = 0
            if removal_date:
                resource = 0
            
            results.append({
                'name': name,
                'age': age,
                'norm': norm,
                'resource': max(0, resource),
                'status': '✅ В норме' if resource > 0 else '❌ Требуется замена'
            })
            
            details[name] = {
                'age': age,
                'norm': norm,
                'resource': max(0, resource)
            }
        
        # Средний ресурс по всем элементам
        avg_resource = sum(r['resource'] for r in results) / len(results) if results else 0
        
        # Слабое звено (минимальный ресурс)
        weak = min(results, key=lambda x: x['resource']) if results else None
        
        return AlgorithmResult(
            algorithm_name="Утверждённая методика",
            algorithm_number=0,
            result=avg_resource,
            weak_element=weak['name'] if weak else None,
            details={
                'elements': results,
                'avg_resource': avg_resource,
                'weak': weak
            },
            recommendation=self._get_recommendation(avg_resource, weak)
        )
    
    def calculate_algorithm_1(self, equipment_data: List[Dict]) -> AlgorithmResult:
        """
        Алгоритм 1 - Среднее арифметическое
        Z_ГРП = (Σ Z_элемент) / m * k_общ
        """
        results = []
        details = {}
        
        for equip in equipment_data:
            name = equip.get('name', '')
            install_date = equip.get('install_date', '')
            removal_date = equip.get('removal_date', None)
            
            if not install_date:
                continue
            
            age = self.get_equipment_age(install_date, removal_date)
            norm = self.get_norm_for_equipment(name)
            
            # Базовый ресурс
            Z_base = norm - age
            
            # Коэффициент технического состояния (непрерывный)
            K_state = self._calculate_state_coefficient(equip)
            
            # Коэффициент повреждений
            K_damage = self._calculate_damage_coefficient(equip)
            
            # Коэффициент ТО
            K_maintenance = self._calculate_maintenance_coefficient(equip)
            
            # Итоговый ресурс элемента
            Z_element = Z_base * K_state * K_damage * K_maintenance
            
            # Если оборудование демонтировано
            if removal_date:
                Z_element = 0
            
            results.append({
                'name': name,
                'Z_base': Z_base,
                'K_state': K_state,
                'K_damage': K_damage,
                'K_maintenance': K_maintenance,
                'Z_element': max(0, Z_element)
            })
            
            details[name] = {
                'Z_base': Z_base,
                'K_state': K_state,
                'K_damage': K_damage,
                'K_maintenance': K_maintenance,
                'Z_element': max(0, Z_element)
            }
        
        # Среднее арифметическое
        avg_Z = sum(r['Z_element'] for r in results) / len(results) if results else 0
        
        # Общий коэффициент (аналог K = 1 - (A+B+C))
        K_common = self._calculate_common_coefficient(equipment_data)
        
        # Итоговый ресурс ГРП
        Z_grp = avg_Z * K_common
        
        # Слабое звено
        weak = min(results, key=lambda x: x['Z_element']) if results else None
        
        return AlgorithmResult(
            algorithm_name="Среднее арифметическое",
            algorithm_number=1,
            result=max(0, Z_grp),
            weak_element=weak['name'] if weak else None,
            details={
                'elements': results,
                'avg_Z': avg_Z,
                'K_common': K_common,
                'Z_grp': Z_grp,
                'weak': weak
            },
            recommendation=self._get_recommendation(Z_grp, weak)
        )
    
    def calculate_algorithm_2(self, equipment_data: List[Dict]) -> AlgorithmResult:
        """
        Алгоритм 2 - REGION-gaz (принцип "слабого звена")
        Z_ГРП = min(Z_элемент) * K_общ_тех
        """
        critical_results = []
        details = {}
        
        for equip in equipment_data:
            name = equip.get('name', '')
            install_date = equip.get('install_date', '')
            removal_date = equip.get('removal_date', None)
            
            # Проверяем, является ли элемент критическим
            is_critical = any(c in name for c in self.critical_elements)
            
            if not install_date or not is_critical:
                continue
            
            age = self.get_equipment_age(install_date, removal_date)
            norm = self.get_norm_for_equipment(name)
            
            # Базовый ресурс
            Z_base = norm - age
            
            # Коэффициент технического состояния
            K_state = self._calculate_state_coefficient(equip)
            
            # Коэффициент условий эксплуатации
            K_conditions = self._calculate_conditions_coefficient(equip)
            
            # Коэффициент качества ремонта
            K_repair = self._calculate_repair_coefficient(equip)
            
            # Итоговый ресурс элемента
            Z_element = Z_base * K_state * K_conditions * K_repair
            
            if removal_date:
                Z_element = 0
            
            critical_results.append({
                'name': name,
                'Z_base': Z_base,
                'K_state': K_state,
                'K_conditions': K_conditions,
                'K_repair': K_repair,
                'Z_element': max(0, Z_element)
            })
            
            details[name] = {
                'Z_base': Z_base,
                'K_state': K_state,
                'K_conditions': K_conditions,
                'K_repair': K_repair,
                'Z_element': max(0, Z_element)
            }
        
        if not critical_results:
            return AlgorithmResult(
                algorithm_name="REGION-gaz",
                algorithm_number=2,
                result=0,
                weak_element=None,
                details={'error': 'Нет критических элементов'},
                recommendation="Нет данных для расчёта"
            )
        
        # Слабое звено (минимальный ресурс)
        weak = min(critical_results, key=lambda x: x['Z_element'])
        Z_weak = weak['Z_element']
        
        # Обобщённый коэффициент технического состояния ГРП
        K_common_tech = self._calculate_common_technical_coefficient(critical_results)
        
        # Итоговый ресурс ГРП
        Z_grp = Z_weak * K_common_tech
        
        # Срок следующего диагностирования
        T_next = min(Z_grp * 0.5, 5)
        
        return AlgorithmResult(
            algorithm_name="REGION-gaz (слабое звено)",
            algorithm_number=2,
            result=max(0, Z_grp),
            weak_element=weak['name'],
            details={
                'elements': critical_results,
                'Z_weak': Z_weak,
                'K_common_tech': K_common_tech,
                'Z_grp': Z_grp,
                'T_next_diagnosis': T_next,
                'weak': weak
            },
            recommendation=f"Слабое звено: {weak['name']}. Следующее диагностирование через {T_next:.1f} лет."
        )
    
    def calculate_algorithm_3(self, equipment_data: List[Dict]) -> AlgorithmResult:
        """
        Алгоритм 3 - Улучшенный (полный учёт всех факторов)
        Z_ГРП = min(Z_база * K_сост * K_усл * K_рем * K_повр) * K_общ_тех
        """
        critical_results = []
        details = {}
        
        for equip in equipment_data:
            name = equip.get('name', '')
            install_date = equip.get('install_date', '')
            removal_date = equip.get('removal_date', None)
            
            is_critical = any(c in name for c in self.critical_elements)
            
            if not install_date or not is_critical:
                continue
            
            age = self.get_equipment_age(install_date, removal_date)
            norm = self.get_norm_for_equipment(name)
            
            # Базовый ресурс (с учётом наработки)
            Z_base = self._calculate_base_resource(equip, norm, age)
            
            # Все коэффициенты
            K_state = self._calculate_state_coefficient(equip)
            K_conditions = self._calculate_conditions_coefficient(equip)
            K_repair = self._calculate_repair_coefficient(equip)
            K_damage = self._calculate_damage_coefficient(equip)
            
            # Учёт нескольких замен
            Z_element = self._apply_multi_replacement(equip, Z_base, K_state, K_conditions, K_repair, K_damage)
            
            if removal_date:
                Z_element = 0
            
            critical_results.append({
                'name': name,
                'Z_base': Z_base,
                'K_state': K_state,
                'K_conditions': K_conditions,
                'K_repair': K_repair,
                'K_damage': K_damage,
                'Z_element': max(0, Z_element)
            })
            
            details[name] = {
                'Z_base': Z_base,
                'K_state': K_state,
                'K_conditions': K_conditions,
                'K_repair': K_repair,
                'K_damage': K_damage,
                'Z_element': max(0, Z_element)
            }
        
        if not critical_results:
            return AlgorithmResult(
                algorithm_name="Улучшенный алгоритм",
                algorithm_number=3,
                result=0,
                weak_element=None,
                details={'error': 'Нет критических элементов'},
                recommendation="Нет данных для расчёта"
            )
        
        # Слабое звено
        weak = min(critical_results, key=lambda x: x['Z_element'])
        Z_weak = weak['Z_element']
        
        # Обобщённый коэффициент
        K_common_tech = self._calculate_common_technical_coefficient(critical_results)
        
        # Итоговый ресурс
        Z_grp = Z_weak * K_common_tech
        
        # Срок следующего диагностирования
        T_next = min(Z_grp * 0.5, 5)
        
        return AlgorithmResult(
            algorithm_name="Улучшенный алгоритм",
            algorithm_number=3,
            result=max(0, Z_grp),
            weak_element=weak['name'],
            details={
                'elements': critical_results,
                'Z_weak': Z_weak,
                'K_common_tech': K_common_tech,
                'Z_grp': Z_grp,
                'T_next_diagnosis': T_next,
                'weak': weak
            },
            recommendation=f"Слабое звено: {weak['name']}. Следующее диагностирование через {T_next:.1f} лет."
        )
    
    def calculate_algorithm_4(self, equipment_data: List[Dict]) -> AlgorithmResult:
        """
        Алгоритм 4 - Weighted Average (взвешенное среднее)
        Z_база = α * Z_календ + (1-α) * Z_наработка
        """
        critical_results = []
        details = {}
        
        for equip in equipment_data:
            name = equip.get('name', '')
            install_date = equip.get('install_date', '')
            removal_date = equip.get('removal_date', None)
            telemetry = equip.get('telemetry', {})  # Данные телеметрии
            
            is_critical = any(c in name for c in self.critical_elements)
            
            if not install_date or not is_critical:
                continue
            
            age = self.get_equipment_age(install_date, removal_date)
            norm = self.get_norm_for_equipment(name)
            
            # Календарный ресурс
            Z_calendar = norm - age
            
            # Ресурс по наработке (из телеметрии)
            if telemetry:
                H_norm = telemetry.get('norm_hours', 100)
                H_fact = telemetry.get('fact_hours', 0)
                Z_workload = (H_norm - H_fact) / H_norm * norm if H_norm > 0 else Z_calendar
            else:
                Z_workload = Z_calendar
            
            # Взвешенное среднее
            if Z_calendar < -self.T_crit:
                Z_base = Z_calendar  # Защита от абсурдных решений
            else:
                Z_base = self.alpha * Z_calendar + (1 - self.alpha) * Z_workload
            
            # Коэффициенты
            K_state = self._calculate_state_coefficient(equip)
            K_conditions = self._calculate_conditions_coefficient(equip)
            K_repair = self._calculate_repair_coefficient(equip)
            K_damage = self._calculate_damage_coefficient(equip)
            
            # Итоговый ресурс
            Z_element = Z_base * K_state * K_conditions * K_repair * K_damage
            
            if removal_date:
                Z_element = 0
            
            critical_results.append({
                'name': name,
                'Z_calendar': Z_calendar,
                'Z_workload': Z_workload,
                'Z_base': Z_base,
                'K_state': K_state,
                'K_conditions': K_conditions,
                'K_repair': K_repair,
                'K_damage': K_damage,
                'Z_element': max(0, Z_element),
                'alpha': self.alpha
            })
            
            details[name] = {
                'Z_calendar': Z_calendar,
                'Z_workload': Z_workload,
                'Z_base': Z_base,
                'K_state': K_state,
                'K_conditions': K_conditions,
                'K_repair': K_repair,
                'K_damage': K_damage,
                'Z_element': max(0, Z_element),
                'alpha': self.alpha
            }
        
        if not critical_results:
            return AlgorithmResult(
                algorithm_name="Weighted Average",
                algorithm_number=4,
                result=0,
                weak_element=None,
                details={'error': 'Нет критических элементов'},
                recommendation="Нет данных для расчёта"
            )
        
        # Слабое звено
        weak = min(critical_results, key=lambda x: x['Z_element'])
        Z_weak = weak['Z_element']
        
        # Обобщённый коэффициент
        K_common_tech = self._calculate_common_technical_coefficient(critical_results)
        
        # Итоговый ресурс
        Z_grp = Z_weak * K_common_tech
        
        # Срок следующего диагностирования
        T_next = min(Z_grp * 0.5, 5)
        
        return AlgorithmResult(
            algorithm_name="Weighted Average (взвешенное среднее)",
            algorithm_number=4,
            result=max(0, Z_grp),
            weak_element=weak['name'],
            details={
                'elements': critical_results,
                'Z_weak': Z_weak,
                'K_common_tech': K_common_tech,
                'Z_grp': Z_grp,
                'T_next_diagnosis': T_next,
                'weak': weak,
                'alpha': self.alpha
            },
            recommendation=f"Слабое звено: {weak['name']}. Следующее диагностирование через {T_next:.1f} лет."
        )
    
    # ============ ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ ============
    
    def _calculate_state_coefficient(self, equip: Dict) -> float:
        """Расчёт коэффициента технического состояния K_сост (непрерывный)"""
        # В реальности вычисляется по отклонениям параметров
        # Сейчас используем эмуляцию на основе возраста
        age = self.get_equipment_age(
            equip.get('install_date', ''),
            equip.get('removal_date', None)
        )
        norm = self.get_norm_for_equipment(equip.get('name', ''))
        
        if norm > 0:
            # Чем старше оборудование, тем хуже состояние
            ratio = min(age / norm, 1.5)
            K = max(0, 1 - ratio * 0.3)
        else:
            K = 1.0
        
        return max(0.1, min(1.0, K))
    
    def _calculate_conditions_coefficient(self, equip: Dict) -> float:
        """Расчёт коэффициента условий эксплуатации K_усл"""
        # Эмуляция: учитываем условия работы
        conditions = equip.get('conditions', {})
        
        # По умолчанию хорошие условия
        K = 1.0
        
        # Цикличность нагрузки
        if conditions.get('cyclic', False):
            K *= 0.9
        
        # Вибрации
        if conditions.get('vibration', False):
            K *= 0.85
        
        # Агрессивная среда
        if conditions.get('aggressive', False):
            K *= 0.8
        
        # Температура
        temp = conditions.get('temperature', 20)
        if temp < -20 or temp > 40:
            K *= 0.9
        
        return max(0.7, min(1.0, K))
    
    def _calculate_repair_coefficient(self, equip: Dict) -> float:
        """Расчёт коэффициента качества ремонта K_рем"""
        repairs = equip.get('repairs', [])
        
        if not repairs:
            return 1.0
        
        # Усреднённый коэффициент по всем ремонтам
        total_quality = 0
        for repair in repairs:
            quality = repair.get('quality', 1.0)  # 0-1
            total_quality += quality
        
        avg_quality = total_quality / len(repairs)
        
        return max(0.5, min(1.0, avg_quality))
    
    def _calculate_damage_coefficient(self, equip: Dict) -> float:
        """Расчёт коэффициента повреждений и отказов K_повр"""
        damages = equip.get('damages', [])
        failures = equip.get('failures', [])
        
        # Весовые коэффициенты
        alpha = 0.2  # за отказ
        beta = 0.1   # за повреждение
        
        N_failures = len(failures)
        N_damages = len(damages)
        
        K = 1 - alpha * N_failures - beta * N_damages
        
        return max(0.1, min(1.0, K))
    
    def _calculate_maintenance_coefficient(self, equip: Dict) -> float:
        """Расчёт коэффициента качества ТО"""
        maintenances = equip.get('maintenances', [])
        
        if not maintenances:
            return 1.0
        
        total_quality = 0
        for mt in maintenances:
            quality = mt.get('quality', 1.0)
            total_quality += quality
        
        avg_quality = total_quality / len(maintenances)
        
        return max(0.5, min(1.0, avg_quality))
    
    def _calculate_common_coefficient(self, equipment_data: List[Dict]) -> float:
        """Расчёт обобщённого коэффициента K_общ"""
        # Аналог K = 1 - (A + B + C)
        # Эмуляция: среднее состояние всех элементов
        total_state = 0
        count = 0
        
        for equip in equipment_data:
            state = self._calculate_state_coefficient(equip)
            total_state += state
            count += 1
        
        if count == 0:
            return 1.0
        
        avg_state = total_state / count
        
        return max(0.3, min(1.0, avg_state))
    
    def _calculate_common_technical_coefficient(self, critical_results: List[Dict]) -> float:
        """Расчёт обобщённого технического коэффициента ГРП (среднее геометрическое)"""
        if not critical_results:
            return 1.0
        
        product = 1.0
        for r in critical_results:
            K = r.get('K_state', 1.0)
            product *= K
        
        # Среднее геометрическое
        return product ** (1 / len(critical_results))
    
    def _calculate_base_resource(self, equip: Dict, norm: float, age: float) -> float:
        """Расчёт базового ресурса с учётом наработки"""
        telemetry = equip.get('telemetry', {})
        
        # Календарный ресурс
        Z_calendar = norm - age
        
        # Ресурс по наработке
        if telemetry:
            H_norm = telemetry.get('norm_hours', 100)
            H_fact = telemetry.get('fact_hours', 0)
            if H_norm > 0:
                Z_workload = (H_norm - H_fact) / H_norm * norm
            else:
                Z_workload = Z_calendar
        else:
            Z_workload = Z_calendar
        
        # Минимальный базовый ресурс
        return min(Z_calendar, Z_workload)
    
    def _apply_multi_replacement(self, equip: Dict, Z_base: float, 
                                 K_state: float, K_conditions: float,
                                 K_repair: float, K_damage: float) -> float:
        """Учёт нескольких замен оборудования"""
        replacements = equip.get('replacements', [])
        
        if not replacements:
            return Z_base * K_state * K_conditions * K_repair * K_damage
        
        # Проверяем неравенство: Σ(S_факт_p / S_назн_p) < 1
        total_ratio = 0
        for rep in replacements:
            fact = rep.get('fact_life', 0)
            norm = rep.get('norm_life', 20)
            total_ratio += fact / norm
        
        if total_ratio < 1:
            return Z_base * K_state * K_conditions * K_repair * K_damage
        else:
            # Альтернативная формула
            first_norm = replacements[0].get('norm_life', 20) if replacements else 20
            last_norm = replacements[-1].get('norm_life', 20) if replacements else 20
            last_fact = replacements[-1].get('fact_life', 0) if replacements else 0
            
            Z_alt = (sum(r.get('norm_life', 20) for r in replacements) / first_norm) * (last_norm - last_fact)
            
            return Z_alt * K_state * K_conditions * K_repair * K_damage
    
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


def calculate_all_algorithms(equipment_data: List[Dict]) -> Dict[int, AlgorithmResult]:
    """
    Функция для расчёта по всем алгоритмам
    """
    calculator = GRPResourceCalculator()
    
    results = {}
    
    # Алгоритм 0
    results[0] = calculator.calculate_algorithm_0(equipment_data)
    
    # Алгоритм 1
    results[1] = calculator.calculate_algorithm_1(equipment_data)
    
    # Алгоритм 2
    results[2] = calculator.calculate_algorithm_2(equipment_data)
    
    # Алгоритм 3
    results[3] = calculator.calculate_algorithm_3(equipment_data)
    
    # Алгоритм 4
    results[4] = calculator.calculate_algorithm_4(equipment_data)
    
    return results