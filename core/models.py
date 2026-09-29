from dataclasses import dataclass
from typing import Optional
from datetime import datetime, date


@dataclass
class Equipment:
    """Модель оборудования"""
    name: str
    install_date: str
    removal_date: Optional[str] = None
    id: Optional[int] = None

    @property
    def lifetime_months(self) -> Optional[float]:
        """Вычисление времени жизни в месяцах"""
        try:
            if isinstance(self.install_date, date):
                install = self.install_date
            else:
                install = datetime.strptime(self.install_date, '%Y-%m-%d').date()

            if self.removal_date:
                if isinstance(self.removal_date, date):
                    removal = self.removal_date
                else:
                    removal = datetime.strptime(self.removal_date, '%Y-%m-%d').date()
            else:
                removal = date.today()

            return (removal - install).days / 30.44
        except Exception:
            return None


@dataclass
class Part:
    """Модель типа запчасти (справочник)"""
    name: str
    norm_years: float