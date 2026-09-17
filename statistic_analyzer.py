import numpy as np
import matplotlib.pyplot as plt
from typing import List, Dict
from models import Equipment
from datetime import datetime

class StatisticsAnalyzer:
    """Анализатор статистики оборудования"""
    
    def __init__(self, equipment_list: List[Equipment]):
        self.equipment = equipment_list
    
    def get_lifetimes(self) -> List[float]:
        """Получение списка времени жизни оборудования в месяцах"""
        lifetimes = []
        for equip in self.equipment:
            lifetime = equip.lifetime_months
            if lifetime is not None and lifetime > 0:
                lifetimes.append(lifetime)
        return lifetimes
    
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
        
        sorted_lifetimes = sorted(lifetimes)
        n = len(sorted_lifetimes)
        
        # СРЕДНЕЕ
        mean_val = np.mean(lifetimes)
        
        # МЕДИАНА - середина отсортированного ряда
        if n % 2 == 0:
            median_val = (sorted_lifetimes[n//2 - 1] + sorted_lifetimes[n//2]) / 2
        else:
            median_val = sorted_lifetimes[n//2]
        
        return {
            'mean': mean_val,
            'median': median_val,
            'std': np.std(lifetimes),
            'min': np.min(lifetimes),
            'max': np.max(lifetimes),
            'count': n,
            'sorted_lifetimes': sorted_lifetimes
        }
    
    def plot_lifetime_points(self, equipment_name: str = None):
        """
        График времени жизни каждого экземпляра оборудования
        Точки - каждое оборудование
        Линия - среднее значение
        """
        if equipment_name:
            filtered = [e for e in self.equipment if equipment_name.lower() in e.name.lower()]
        else:
            filtered = self.equipment
        
        if not filtered:
            print("Нет данных для построения графика")
            return
        
        # Собираем времена жизни
        lifetimes = []
        labels = []
        
        for i, equip in enumerate(filtered):
            lifetime = equip.lifetime_months
            if lifetime is not None and lifetime > 0:
                lifetimes.append(lifetime)
                # Создаем подпись: год установки
                try:
                    year = datetime.strptime(equip.install_date, '%Y-%m-%d').year
                    if equip.removal_date:
                        removal_year = datetime.strptime(equip.removal_date, '%Y-%m-%d').year
                        labels.append(f"{year}-{removal_year}")
                    else:
                        labels.append(f"{year}-наст.")
                except:
                    labels.append(f"№{i+1}")
        
        if not lifetimes:
            print("Нет данных о времени жизни")
            return
        
        # Расчет статистики
        sorted_lifetimes = sorted(lifetimes)
        n = len(sorted_lifetimes)
        mean_val = np.mean(lifetimes)
        
        # Медиана
        if n % 2 == 0:
            median_val = (sorted_lifetimes[n//2 - 1] + sorted_lifetimes[n//2]) / 2
        else:
            median_val = sorted_lifetimes[n//2]
        
        # Создание графика
        fig, ax = plt.subplots(figsize=(14, 6))
        
        # Точки - каждое оборудование
        x_positions = range(1, len(lifetimes) + 1)
        
        # Цвета в зависимости от превышения нормы
        norm = self.get_norm_for_equipment(equipment_name if equipment_name else filtered[0].name)
        colors = []
        for lt in lifetimes:
            if lt / 12 > norm:
                colors.append('red')
            elif lt / 12 > norm * 0.9:
                colors.append('orange')
            else:
                colors.append('green')
        
        # Рисуем точки
        ax.scatter(x_positions, lifetimes, c=colors, s=100, zorder=3, alpha=0.7)
        
        # Подписываем точки
        for i, (x, y, label) in enumerate(zip(x_positions, lifetimes, labels)):
            ax.annotate(f'{y:.0f} мес.\n({y/12:.1f} лет)', 
                       (x, y), textcoords="offset points", 
                       xytext=(0, 10), ha='center', fontsize=8)
            
            # Добавляем номер и подпись под точкой
            ax.text(x, -5, label, ha='center', fontsize=7, rotation=45)
        
        # Горизонтальная линия - СРЕДНЕЕ значение
        ax.axhline(y=mean_val, color='blue', linestyle='--', linewidth=2, 
                  label=f'Среднее = {mean_val:.1f} мес. ({mean_val/12:.1f} лет)')
        
        # Горизонтальная линия - МЕДИАНА
        ax.axhline(y=median_val, color='green', linestyle='-.', linewidth=2, 
                  label=f'Медиана = {median_val:.1f} мес. ({median_val/12:.1f} лет)')
        
        # Горизонтальная линия - норма (если есть)
        if norm:
            ax.axhline(y=norm * 12, color='red', linestyle=':', linewidth=2, 
                      label=f'Норма = {norm} лет ({norm*12:.0f} мес.)', alpha=0.7)
        
        # Настройки графика
        ax.set_xlabel('Порядковый номер оборудования (по дате установки)', fontsize=12)
        ax.set_ylabel('Время жизни (месяцы)', fontsize=12)
        title = f'Время жизни оборудования: {equipment_name if equipment_name else "Все"}'[:60]
        ax.set_title(title, fontsize=14)
        ax.grid(True, alpha=0.3, axis='y')
        ax.legend(loc='upper right')
        
        # Добавляем текстовую информацию
        text_str = f'Статистика:\n'
        text_str += f'Количество: {len(lifetimes)} шт.\n'
        text_str += f'Среднее: {mean_val:.1f} мес.\n'
        text_str += f'Медиана: {median_val:.1f} мес.\n'
        text_str += f'Мин/Макс: {min(lifetimes):.0f}/{max(lifetimes):.0f} мес.'
        
        ax.text(0.02, 0.98, text_str, transform=ax.transAxes, 
                verticalalignment='top', fontsize=10,
                bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8))
        
        plt.tight_layout()
        plt.show()
    
    def get_norm_for_equipment(self, name: str) -> float:
        """Получение нормы для оборудования"""
        norms = {
            'Редукционная': 15,
            'Запорная арматура (ЗА1)': 12, 'Запорная арматура (ЗА2)': 12,
            'Запорная арматура (ЗА3)': 12, 'Запорная арматура (ЗА4)': 12,
            'Запорная арматура (ЗА5)': 12, 'Запорная арматура (ЗА6)': 12,
            'Запорная арматура (ЗА7)': 12,
            'Предохранительная': 10,
            'Отключающая': 12,
            'Фильтр': 8
        }
        
        for key, norm in norms.items():
            if key in name:
                return norm
        return None