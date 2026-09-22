import statistics
from typing import Callable, Dict, List, Optional

from config import EQUIPMENT_NORMS
from models import Equipment


class StatisticsAnalyzer:
    """Анализатор статистики оборудования"""

    def __init__(self, equipment_list: List[Equipment],
                 norm_resolver: Optional[Callable[[Equipment], Optional[float]]] = None):
        self.equipment = equipment_list
        self._norm_resolver = norm_resolver

    def get_lifetimes(self) -> List[float]:
        """Список времени жизни оборудования в месяцах"""
        return [
            lifetime for equip in self.equipment
            if (lifetime := equip.lifetime_months) is not None and lifetime > 0
        ]

    def calculate_statistics(self) -> Dict:
        """Расчет статистических показателей"""
        lifetimes = self.get_lifetimes()

        if not lifetimes:
            return {
                'mean': 0,
                'median': 0,
                'std': 0,
                'min': 0,
                'max': 0,
                'count': 0
            }

        return {
            'mean': statistics.mean(lifetimes),
            'median': statistics.median(lifetimes),
            'std': statistics.pstdev(lifetimes),
            'min': min(lifetimes),
            'max': max(lifetimes),
            'count': len(lifetimes)
        }

    def get_norm_for_equipment(self, equip: Equipment) -> Optional[float]:
        """Нормативный срок для оборудования.

        Сначала через переданный resolver (нормы из БД, в т.ч. по запчастям),
        затем через базовые нормы config.EQUIPMENT_NORMS.
        """
        if self._norm_resolver:
            norm = self._norm_resolver(equip)
            if norm is not None:
                return float(norm)

        for key, years in EQUIPMENT_NORMS.items():
            if key in equip.name:
                return float(years)
        return None