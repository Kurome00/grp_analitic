from dataclasses import dataclass
from typing import Optional
from datetime import datetime, date
from decimal import Decimal

@dataclass
class GRP:
    """Модель ГРП"""
    id: int
    type: str
    lines_count: int
    actual_life: float
    design_life: float

@dataclass
class Equipment:
    """Модель оборудования"""
    id: int
    grp_id: int
    name: str
    install_date: str  
    removal_date: Optional[str] = None  
    
    @property
    def lifetime_months(self) -> Optional[float]:
        """Вычисление времени жизни в месяцах"""
        try:
            # Обработка install_date
            if isinstance(self.install_date, date):
                install = self.install_date
            else:
                install = datetime.strptime(self.install_date, '%Y-%m-%d').date()
            
            # Обработка removal_date
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
class DocumentaryNorm:
    """Документальная норма"""
    id: int
    equipment_name: str
    max_life_years: float
    notes: str

@dataclass
class TechnicalCoefficients:
    """Модель технических коэффициентов"""
    grp_id: int
    a: float
    b: float
    c: float
    k: float
    n: int
    u: int
    m: int
    r: int
    diagnosis_date: str