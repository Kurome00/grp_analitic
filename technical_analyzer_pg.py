import psycopg2
from typing import Dict, List, Tuple, Optional
from datetime import datetime
from dataclasses import dataclass

@dataclass
class TechnicalDiagnosticReport:
    """Отчет о техническом диагностировании"""
    grp_id: int
    grp_name: str
    diagnosis_date: str
    a_coefficient: float
    b_coefficient: float
    c_coefficient: float
    k_coefficient: float
    n_count: int
    u_count: int
    m_count: int
    r_count: int


class TechnicalAnalyzer:
    """Анализатор технического состояния с PostgreSQL"""
    
    def __init__(self, 
                 host: str = 'localhost', 
                 port: str = '5432', 
                 database: str = 'grp_analyzer', 
                 user: str = 'postgres', 
                 password: str = 'Dzanatyt2003 '): 
        self.db_config = {
            'host': host,
            'port': port,
            'database': database,
            'user': user,
            'password': password
        }
    
    def get_connection(self):
        return psycopg2.connect(**self.db_config)
    
    def calculate_coefficient_b(self, n: int, u: int) -> float:
        """Расчет коэффициента B = min(0.1; n/u)"""
        if u == 0:
            return 0.0
        return min(0.1, n / u)
    
    def calculate_coefficient_c(self, m: int, r: int) -> float:
        """Расчет коэффициента C = min(0.1; m/r)"""
        if r == 0:
            return 0.0
        return min(0.1, m / r)
    
    def calculate_coefficient_k(self, a: float, b: float, c: float) -> float:
        """Расчет коэффициента K = 1 - (A + B + C)"""
        return max(0.0, min(1.0, 1 - (a + b + c)))
    
    def get_equipment_statistics(self, grp_id: int) -> Dict:
        """Получение статистики по оборудованию ГРП"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Общее количество оборудования
        cursor.execute('SELECT COUNT(*) FROM equipment WHERE grp_id = %s', (grp_id,))
        u_count = cursor.fetchone()[0]
        
        # Количество оборудования с неисправностями (превысивших норму)
        cursor.execute('''
            SELECT COUNT(*) FROM equipment e
            LEFT JOIN documentary_norms dn ON e.name = dn.equipment_name
            WHERE e.grp_id = %s 
            AND e.removal_date IS NULL
            AND dn.max_life_years IS NOT NULL
            AND (CURRENT_DATE - e.install_date) > dn.max_life_years * 365.25
        ''', (grp_id,))
        n_count = cursor.fetchone()[0]
        
        conn.close()
        return {
            'total_equipment': u_count,
            'faulty_equipment': n_count
        }
    
    def assess_coefficient_a(self, grp_id: int) -> float:
        """Оценка коэффициента A"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT COUNT(*) FROM equipment e
            LEFT JOIN documentary_norms dn ON e.name = dn.equipment_name
            WHERE e.grp_id = %s 
            AND (e.name LIKE '%редуцир%' OR e.name LIKE '%фильтр%' OR e.name LIKE '%редуктор%')
            AND e.removal_date IS NULL
            AND dn.max_life_years IS NOT NULL
            AND (CURRENT_DATE - e.install_date) > dn.max_life_years * 365.25 * 0.9
        ''', (grp_id,))
        
        critical_count = cursor.fetchone()[0]
        conn.close()
        
        return 0.1 if critical_count > 0 else 0.0
    
    def get_connection_statistics(self, grp_id: int) -> Tuple[int, int]:
        """Получение статистики по соединениям"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Общее количество соединений = количество оборудования * 2
        cursor.execute('SELECT COUNT(*) FROM equipment WHERE grp_id = %s', (grp_id,))
        equipment_count = cursor.fetchone()[0]
        r_count = equipment_count * 2
        
        # Количество соединений с утечками (условно 50% от проблемного оборудования)
        cursor.execute('''
            SELECT COUNT(*) FROM equipment e
            LEFT JOIN documentary_norms dn ON e.name = dn.equipment_name
            WHERE e.grp_id = %s 
            AND e.removal_date IS NULL
            AND dn.max_life_years IS NOT NULL
            AND (CURRENT_DATE - e.install_date) > dn.max_life_years * 365.25 * 0.8
        ''', (grp_id,))
        problem_count = cursor.fetchone()[0]
        m_count = int(problem_count * 0.5)
        
        conn.close()
        return m_count, r_count
    
    def create_technical_diagnostic(self, grp_id: int, a_coefficient: float = None,
                                   n_count: int = None, u_count: int = None,
                                   m_count: int = None, r_count: int = None) -> TechnicalDiagnosticReport:
        """Создание полного отчета о техническом диагностировании"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT type FROM grp WHERE id = %s', (grp_id,))
        grp_data = cursor.fetchone()
        grp_name = grp_data[0] if grp_data else f"ГРП-{grp_id}"
        conn.close()
        
        stats = self.get_equipment_statistics(grp_id)
        m_conn, r_conn = self.get_connection_statistics(grp_id)
        
        final_n = n_count if n_count is not None else stats['faulty_equipment']
        final_u = u_count if u_count is not None else stats['total_equipment']
        final_m = m_count if m_count is not None else m_conn
        final_r = r_count if r_count is not None else r_conn
        
        a = a_coefficient if a_coefficient is not None else self.assess_coefficient_a(grp_id)
        b = self.calculate_coefficient_b(final_n, final_u)
        c = self.calculate_coefficient_c(final_m, final_r)
        k = self.calculate_coefficient_k(a, b, c)
        
        return TechnicalDiagnosticReport(
            grp_id=grp_id,
            grp_name=grp_name,
            diagnosis_date=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            a_coefficient=a,
            b_coefficient=b,
            c_coefficient=c,
            k_coefficient=k,
            n_count=final_n,
            u_count=final_u,
            m_count=final_m,
            r_count=final_r
        )
    
    def get_technical_condition_rating(self, k_coefficient: float) -> Tuple[str, str]:
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
    
    def get_color_for_coefficient(self, k_coefficient: float) -> str:
        """Получение цвета для визуализации"""
        if k_coefficient >= 0.7:
            return "green"
        elif k_coefficient >= 0.5:
            return "yellow"
        elif k_coefficient >= 0.3:
            return "orange"
        else:
            return "red"
    
    def analyze_grp_technical_state(self, grp_id: int) -> Dict:
        """Комплексный анализ технического состояния ГРП"""
        report = self.create_technical_diagnostic(grp_id)
        rating, recommendation = self.get_technical_condition_rating(report.k_coefficient)
        
        return {
            'report': report,
            'rating': rating,
            'recommendation': recommendation,
            'analysis_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'color': self.get_color_for_coefficient(report.k_coefficient),
            'summary': f"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                     ТЕХНИЧЕСКОЕ ДИАГНОСТИРОВАНИЕ ГРП                          ║
╚══════════════════════════════════════════════════════════════════════════════╝

📋 ИНФОРМАЦИЯ ОБ ОБЪЕКТЕ:
   • ГРП: {report.grp_name} (ID: {report.grp_id})
   • Дата диагностирования: {report.diagnosis_date}

🔧 КОЭФФИЦИЕНТЫ ТЕХНИЧЕСКОГО СОСТОЯНИЯ:
   • A (узел редуцирования и фильтры): {report.a_coefficient}
   • B (прочее оборудование): {report.b_coefficient:.4f}
   • C (разъемные соединения): {report.c_coefficient:.4f}
   • K = 1 - (A+B+C): {report.k_coefficient:.4f}

📊 ИСХОДНЫЕ ДАННЫЕ:
   • n (оборудование с неисправностями): {report.n_count}
   • u (всего оборудования): {report.u_count}
   • m (соединения с утечками): {report.m_count}
   • r (всего соединений): {report.r_count}

🎯 ОЦЕНКА СОСТОЯНИЯ: {rating}

💡 РЕКОМЕНДАЦИИ:
   {recommendation}
"""
        }


class TechnicalHistoryAnalyzer:
    """Анализатор истории технических диагностирований"""
    
    def __init__(self, 
                 host: str = 'localhost', 
                 port: str = '5432', 
                 database: str = 'grp_analyzer', 
                 user: str = 'postgres', 
                 password: str = 'Dzanatyt2003'):  
        self.db_config = {
            'host': host,
            'port': port,
            'database': database,
            'user': user,
            'password': password
        }
    
    def get_connection(self):
        return psycopg2.connect(**self.db_config)
    
    def get_diagnostic_history(self, grp_id: int) -> List[Tuple]:
        """Получение полной истории диагностирований"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM technical_coefficients 
            WHERE grp_id = %s 
            ORDER BY diagnosis_date DESC
        ''', (grp_id,))
        history = cursor.fetchall()
        conn.close()
        return history
    
    def calculate_trend(self, grp_id: int) -> Dict:
        """Расчет тренда изменения технического состояния"""
        history = self.get_diagnostic_history(grp_id)
        
        if len(history) < 2:
            return {
                'trend': 'Недостаточно данных',
                'change': 0,
                'change_percent': 0,
                'recommendation': 'Проведите повторное диагностирование через 6 месяцев',
                'slope': 0
            }
        
        recent = history[:min(3, len(history))]
        
        total_change = 0
        for i in range(len(recent) - 1):
            change = recent[i][5] - recent[i+1][5]  # coefficient_k
            total_change += change
        
        avg_change = total_change / (len(recent) - 1)
        latest_k = recent[0][5]
        previous_k = recent[1][5] if len(recent) > 1 else latest_k
        
        change = latest_k - previous_k
        change_percent = (change / previous_k) * 100 if previous_k != 0 else 0
        
        if avg_change > 0.05:
            trend = "Значительное улучшение 📈📈"
            recommendation = "Отличная динамика! Продолжайте в том же духе."
        elif avg_change > 0:
            trend = "Улучшение 📈"
            recommendation = "Положительная динамика. Поддерживайте текущие мероприятия."
        elif avg_change > -0.05:
            trend = "Стабильно 📊"
            recommendation = "Состояние стабильное. Проводите плановые мероприятия."
        elif avg_change > -0.1:
            trend = "Ухудшение 📉"
            recommendation = "Отрицательная динамика! Требуется усиленный контроль."
        else:
            trend = "Значительное ухудшение 📉📉"
            recommendation = "КРИТИЧЕСКАЯ ДИНАМИКА! Немедленное вмешательство!"
        
        return {
            'trend': trend,
            'change': change,
            'change_percent': change_percent,
            'avg_change': avg_change,
            'latest_k': latest_k,
            'previous_k': previous_k,
            'recommendation': recommendation,
            'slope': avg_change
        }
    
    def get_prediction(self, grp_id: int) -> Dict:
        """Прогнозирование технического состояния"""
        history = self.get_diagnostic_history(grp_id)
        
        if len(history) < 2:
            return {
                'prediction': 'Недостаточно данных для прогнозирования',
                'estimated_months': None,
                'confidence': 'Низкая'
            }
        
        trend_data = self.calculate_trend(grp_id)
        latest_k = history[0][5]
        avg_change = trend_data['avg_change']
        
        if avg_change < 0 and latest_k > 0.3:
            months_to_critical = (latest_k - 0.3) / abs(avg_change) * 6
            estimated_months = int(min(months_to_critical, 24))
        else:
            estimated_months = None
        
        if latest_k < 0.3:
            prediction = "КРИТИЧЕСКОЕ - требуется немедленная замена"
            estimated_months = 1
            confidence = "Высокая"
        elif latest_k < 0.5:
            prediction = "ПЛОХОЕ - замена в ближайшее время"
            if estimated_months is None or estimated_months > 6:
                estimated_months = 6
            confidence = "Средняя"
        elif latest_k < 0.7:
            prediction = "УДОВЛЕТВОРИТЕЛЬНОЕ - плановая замена"
            if estimated_months is None or estimated_months > 12:
                estimated_months = 12
            confidence = "Средняя"
        elif latest_k < 0.85:
            prediction = "ХОРОШЕЕ - замена через 2+ года"
            if estimated_months is None or estimated_months > 24:
                estimated_months = 24
            confidence = "Хорошая"
        else:
            prediction = "ОТЛИЧНОЕ - замена через 3+ года"
            if estimated_months is None or estimated_months > 36:
                estimated_months = 36
            confidence = "Высокая"
        
        if avg_change < -0.05 and estimated_months:
            estimated_months = int(estimated_months * 0.7)
            prediction += " (с учетом ухудшающегося тренда)"
        
        return {
            'prediction': prediction,
            'estimated_months': estimated_months,
            'confidence': confidence,
            'current_k': latest_k,
            'trend': trend_data['trend'],
            'trend_value': avg_change
        }
    
    def get_comparative_analysis(self, grp_id: int) -> Dict:
        """Сравнительный анализ с предыдущими диагностированиями"""
        history = self.get_diagnostic_history(grp_id)
        
        if len(history) < 2:
            return {'has_comparison': False}
        
        latest = history[0]
        previous = history[1]
        
        comparison = {
            'has_comparison': True,
            'date_latest': latest[10],
            'date_previous': previous[10],
            'k_latest': latest[5],
            'k_previous': previous[5],
            'k_change': latest[5] - previous[5],
            'a_latest': latest[2],
            'a_previous': previous[2],
            'b_latest': latest[3],
            'b_previous': previous[3],
            'c_latest': latest[4],
            'c_previous': previous[4]
        }
        
        improvements = []
        deteriorations = []
        
        if comparison['k_change'] > 0:
            improvements.append(f"Коэффициент K улучшился на {comparison['k_change']:.4f}")
        else:
            deteriorations.append(f"Коэффициент K ухудшился на {abs(comparison['k_change']):.4f}")
        
        if latest[2] > previous[2]:
            deteriorations.append("Увеличился коэффициент A (проблемы с редуцированием)")
        elif latest[2] < previous[2]:
            improvements.append("Улучшился коэффициент A")
        
        if latest[3] > previous[3]:
            deteriorations.append("Увеличился коэффициент B (больше оборудования с неисправностями)")
        elif latest[3] < previous[3]:
            improvements.append("Улучшился коэффициент B")
        
        if latest[4] > previous[4]:
            deteriorations.append("Увеличился коэффициент C (больше утечек в соединениях)")
        elif latest[4] < previous[4]:
            improvements.append("Улучшился коэффициент C")
        
        return {
            **comparison,
            'improvements': improvements,
            'deteriorations': deteriorations
        }


def get_tech_analysis_summary(grp_id: int) -> str:
    """Утилита для получения краткой сводки технического анализа"""
    analyzer = TechnicalAnalyzer()
    history_analyzer = TechnicalHistoryAnalyzer()
    
    analysis = analyzer.analyze_grp_technical_state(grp_id)
    trend = history_analyzer.calculate_trend(grp_id)
    prediction = history_analyzer.get_prediction(grp_id)
    
    return f"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                         КРАТКАЯ СВОДКА СОСТОЯНИЯ                              ║
╚══════════════════════════════════════════════════════════════════════════════╝

📊 ТЕКУЩЕЕ СОСТОЯНИЕ:
   • Коэффициент K: {analysis['report'].k_coefficient:.4f}
   • Оценка: {analysis['rating']}

📈 ДИНАМИКА:
   • Тренд: {trend['trend']}
   • Изменение: {trend['change']:+.4f} ({trend['change_percent']:+.1f}%)

🔮 ПРОГНОЗ:
   • {prediction['prediction']}
   • Достоверность: {prediction.get('confidence', 'Н/Д')}

💡 {analysis['recommendation']}
"""