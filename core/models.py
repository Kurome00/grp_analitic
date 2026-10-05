from dataclasses import dataclass
from typing import Optional

from core.lifetimes import lifetime_months


@dataclass
class Equipment:
    """Модель оборудования"""

    name: str
    install_date: str
    removal_date: Optional[str] = None
    id: Optional[int] = None

    @property
    def lifetime_months(self) -> Optional[float]:
        """Время жизни в месяцах (до снятия или до сегодняшнего дня).

        Считает core.lifetimes: тот же делитель, что и во всех остальных
        местах приложения.
        """
        return lifetime_months(self.install_date, self.removal_date)


@dataclass
class Part:
    """Модель типа запчасти (справочник)"""

    name: str
    norm_years: float