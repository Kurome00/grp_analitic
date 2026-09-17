from typing import Dict, Tuple, Optional

class RemainingLifeCalculator:
    """Калькулятор остаточного ресурса (Open/Closed Principle)"""
    
    @staticmethod
    def calculate(equip_data: Dict) -> Tuple[Optional[float], str]:
        """Расчет остаточного ресурса"""
        
        has_first_replace = all([
            equip_data.get('first_man') is not None,
            equip_data.get('first_fact') is not None
        ])
        
        has_second_replace = all([
            equip_data.get('second_man') is not None,
            equip_data.get('second_fact') is not None
        ])
        
        has_diagnostic = all([
            equip_data.get('diag_man') is not None,
            equip_data.get('diag_fact') is not None
        ])
        
        # Случай 1: только диагностика
        if has_diagnostic and not has_first_replace:
            result = (equip_data['diag_man'] - equip_data['diag_fact'])
            return result, "Случай 1 (только диагностика)"
        
        # Случай 2: первая замена + диагностика
        elif has_first_replace and has_diagnostic and not has_second_replace:
            try:
                part1 = (equip_data['first_fact'] / equip_data['first_man'])
                part2 = (equip_data['diag_man'] / equip_data['diag_fact'])
                result = part1 * part2
                return result, "Случай 2 (первая замена + диагностика)"
            except ZeroDivisionError:
                return None, "Ошибка: деление на ноль"
        
        # Случай 3: все данные
        elif has_first_replace and has_second_replace and has_diagnostic:
            try:
                part1 = (equip_data['first_fact'] / equip_data['first_man'])
                part2 = (equip_data['second_fact'] / equip_data['second_man'])
                avg = (part1 + part2) / 2
                diff = (equip_data['diag_man'] - equip_data['diag_fact'])
                result = avg * diff
                return result, "Случай 3 (полные данные)"
            except ZeroDivisionError:
                return None, "Ошибка: деление на ноль"
        
        else:
            return None, "Недостаточно данных для расчета"

class TechnicalCoefficientCalculator:
    """Калькулятор технических коэффициентов"""
    
    @staticmethod
    def calculate_b(n: int, u: int) -> float:
        """Расчет коэффициента B"""
        if u == 0:
            return 0
        return min(0.1, n / u)
    
    @staticmethod
    def calculate_c(m: int, r: int) -> float:
        """Расчет коэффициента C"""
        if r == 0:
            return 0
        return min(0.1, m / r)
    
    @staticmethod
    def calculate_k(a: float, b: float, c: float) -> float:
        """Расчет коэффициента K"""
        return 1 - (a + b + c)