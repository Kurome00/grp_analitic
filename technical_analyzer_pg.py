"""Чистая математика технического диагностирования ГРП.

Коэффициенты:
    A — узел редуцирования и фильтры (0 или 0.1)
    B = min(0.1, n / u) — прочее оборудование
    C = min(0.1, m / r) — разъемные соединения
    K = 1 - (A + B + C)
"""
from typing import Tuple


class TechnicalAnalyzer:

    @staticmethod
    def calculate_coefficient_b(n: int, u: int) -> float:
        """Расчет коэффициента B = min(0.1; n/u)"""
        if u == 0:
            return 0.0
        return min(0.1, n / u)

    @staticmethod
    def calculate_coefficient_c(m: int, r: int) -> float:
        """Расчет коэффициента C = min(0.1; m/r)"""
        if r == 0:
            return 0.0
        return min(0.1, m / r)

    @staticmethod
    def calculate_coefficient_k(a: float, b: float, c: float) -> float:
        """Расчет коэффициента K = 1 - (A + B + C)"""
        return max(0.0, min(1.0, 1 - (a + b + c)))

    @staticmethod
    def get_technical_condition_rating(k_coefficient: float) -> Tuple[str, str]:
        """Оценка технического состояния по коэффициенту K"""
        if k_coefficient >= 0.85:
            return ("Отличное 🌟", "✅ Оборудование в отличном состоянии. Плановое обслуживание.")
        elif k_coefficient >= 0.7:
            return ("Хорошее 👍", "👍 Состояние хорошее. Рекомендуется плановая диагностика раз в год.")
        elif k_coefficient >= 0.5:
            return ("Удовлетворительное ⚠️", "⚠️ Требуется дополнительная диагностика и обслуживание.")
        elif k_coefficient >= 0.3:
            return ("Неудовлетворительное ❌", "❌ Требуется капитальный ремонт или замена оборудования.")
        else:
            return ("Критическое 🚨", "🚨 КРИТИЧЕСКОЕ СОСТОЯНИЕ! НЕМЕДЛЕННАЯ ЗАМЕНА ОБОРУДОВАНИЯ!")