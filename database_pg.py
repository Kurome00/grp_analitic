import psycopg2
from psycopg2.extras import RealDictCursor
from typing import List, Dict, Tuple, Optional
from datetime import datetime

class DatabasePG:
    """Класс для работы с PostgreSQL базой данных"""
    
    def __init__(self, 
                 host: str = 'localhost',
                 port: str = '5432',
                 database: str = 'grp_analyzer',
                 user: str = 'postgres',
                 password: str = 'Dzanatyt2003'):  # ⚠️ ВАШ ПАРОЛЬ!
        
        self.host = host
        self.port = port
        self.database = database
        self.user = user
        self.password = password
        self.init_db()
    
    def get_connection(self):
        """Получение соединения с БД"""
        try:
            return psycopg2.connect(
                host=self.host,
                port=self.port,
                database=self.database,
                user=self.user,
                password=self.password
            )
        except Exception as e:
            print(f"❌ Ошибка подключения к PostgreSQL: {e}")
            raise
    
    def init_db(self):
        """Инициализация базы данных - создание всех таблиц"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Включаем расширение для UUID (если нужно)
        cursor.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp";')
        
        # 1. Таблица ГРП
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS grp (
                id SERIAL PRIMARY KEY,
                type VARCHAR(255) NOT NULL,
                lines_count INTEGER NOT NULL,
                actual_life DECIMAL(10,2) NOT NULL,
                design_life DECIMAL(10,2) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # 2. Таблица оборудования
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS equipment (
                id SERIAL PRIMARY KEY,
                grp_id INTEGER NOT NULL REFERENCES grp(id) ON DELETE CASCADE,
                name VARCHAR(255) NOT NULL,
                install_date DATE NOT NULL,
                removal_date DATE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Создаем индексы для ускорения поиска
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_equipment_grp_id ON equipment(grp_id);
            CREATE INDEX IF NOT EXISTS idx_equipment_name ON equipment(name);
        ''')
        
        # 3. Таблица документальных норм
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS documentary_norms (
                id SERIAL PRIMARY KEY,
                equipment_name VARCHAR(255) NOT NULL UNIQUE,
                max_life_years DECIMAL(10,2) NOT NULL,
                notes TEXT,
                created_date DATE,
                updated_date DATE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # 4. Таблица технических коэффициентов
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS technical_coefficients (
                id SERIAL PRIMARY KEY,
                grp_id INTEGER NOT NULL REFERENCES grp(id) ON DELETE CASCADE,
                coefficient_a DECIMAL(10,4),
                coefficient_b DECIMAL(10,4),
                coefficient_c DECIMAL(10,4),
                coefficient_k DECIMAL(10,4),
                n_count INTEGER,
                u_count INTEGER,
                m_count INTEGER,
                r_count INTEGER,
                diagnosis_date TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Создаем индексы
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_tech_coeff_grp_id ON technical_coefficients(grp_id);
            CREATE INDEX IF NOT EXISTS idx_tech_coeff_date ON technical_coefficients(diagnosis_date DESC);
        ''')
        
        conn.commit()
        conn.close()
        print("✅ База данных PostgreSQL инициализирована!")
    
    # === МЕТОДЫ ДЛЯ РАБОТЫ С ГРП ===
    
    def add_grp(self, grp_type: str, lines_count: int, actual_life: float, design_life: float) -> int:
        """Добавление нового ГРП"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO grp (type, lines_count, actual_life, design_life)
            VALUES (%s, %s, %s, %s)
            RETURNING id
        ''', (grp_type, lines_count, actual_life, design_life))
        grp_id = cursor.fetchone()[0]
        conn.commit()
        conn.close()
        return grp_id
    
    def update_grp(self, grp_id: int, grp_type: str, lines_count: int, actual_life: float, design_life: float):
        """Обновление данных ГРП"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE grp 
            SET type = %s, lines_count = %s, actual_life = %s, design_life = %s, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        ''', (grp_type, lines_count, actual_life, design_life, grp_id))
        conn.commit()
        conn.close()
    
    def get_all_grp(self) -> List[Tuple]:
        """Получение всех ГРП"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT id, type, lines_count, actual_life, design_life FROM grp ORDER BY id')
        result = cursor.fetchall()
        conn.close()
        return result
    
    def get_grp_by_id(self, grp_id: int) -> Optional[Tuple]:
        """Получение ГРП по ID"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT id, type, lines_count, actual_life, design_life FROM grp WHERE id = %s', (grp_id,))
        result = cursor.fetchone()
        conn.close()
        return result
    
    # === МЕТОДЫ ДЛЯ РАБОТЫ С ОБОРУДОВАНИЕМ ===
    
    def add_equipment(self, grp_id: int, name: str, install_date: str, removal_date: str = None) -> int:
        """Добавление оборудования"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO equipment (grp_id, name, install_date, removal_date)
            VALUES (%s, %s, %s, %s)
            RETURNING id
        ''', (grp_id, name, install_date, removal_date))
        equip_id = cursor.fetchone()[0]
        conn.commit()
        conn.close()
        return equip_id
    
    def get_equipment_by_grp(self, grp_id: int) -> List[Tuple]:
        """Получение оборудования по ГРП"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, name, install_date::text, removal_date::text
            FROM equipment WHERE grp_id = %s
            ORDER BY install_date DESC
        ''', (grp_id,))
        result = cursor.fetchall()
        conn.close()
        return result
    
    def update_equipment(self, equip_id: int, name: str, install_date: str, removal_date: str = None):
        """Обновление оборудования"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE equipment 
            SET name = %s, install_date = %s, removal_date = %s, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        ''', (name, install_date, removal_date, equip_id))
        conn.commit()
        conn.close()
    
    def delete_equipment(self, equip_id: int):
        """Удаление оборудования"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM equipment WHERE id = %s', (equip_id,))
        conn.commit()
        conn.close()
    
    # === МЕТОДЫ ДЛЯ РАБОТЫ С ДОКУМЕНТАЛЬНЫМИ НОРМАМИ ===
    
    def get_all_norms(self) -> List[Tuple]:
        """Получение всех норм"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT id, equipment_name, max_life_years, notes FROM documentary_norms ORDER BY equipment_name')
        result = cursor.fetchall()
        conn.close()
        return result
    
    def get_norm_by_name(self, equipment_name: str) -> Optional[Tuple]:
        """Получение нормы по имени"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT id, equipment_name, max_life_years, notes FROM documentary_norms WHERE equipment_name = %s', (equipment_name,))
        result = cursor.fetchone()
        conn.close()
        return result
    
    def add_norm(self, equipment_name: str, max_life_years: float, notes: str = ''):
        """Добавление нормы"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO documentary_norms (equipment_name, max_life_years, notes, created_date, updated_date)
            VALUES (%s, %s, %s, %s, %s)
        ''', (equipment_name, max_life_years, notes, datetime.now().date(), datetime.now().date()))
        conn.commit()
        conn.close()
    
    def update_norm(self, norm_id: int, equipment_name: str, max_life_years: float, notes: str = ''):
        """Обновление нормы"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE documentary_norms 
            SET equipment_name = %s, max_life_years = %s, notes = %s, updated_date = %s, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        ''', (equipment_name, max_life_years, notes, datetime.now().date(), norm_id))
        conn.commit()
        conn.close()
    
    def delete_norm(self, norm_id: int):
        """Удаление нормы"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM documentary_norms WHERE id = %s', (norm_id,))
        conn.commit()
        conn.close()
    
    # === МЕТОДЫ ДЛЯ РАБОТЫ С ТЕХНИЧЕСКИМИ КОЭФФИЦИЕНТАМИ ===
    
    def save_technical_coefficients(self, grp_id: int, coef_data: Dict):
        """Сохранение технических коэффициентов"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO technical_coefficients 
            (grp_id, coefficient_a, coefficient_b, coefficient_c, coefficient_k,
             n_count, u_count, m_count, r_count, diagnosis_date)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ''', (
            grp_id, coef_data['a'], coef_data['b'], coef_data['c'], coef_data['k'],
            coef_data['n'], coef_data['u'], coef_data['m'], coef_data['r'],
            coef_data['diagnosis_date']
        ))
        conn.commit()
        conn.close()
    
    def get_technical_coefficients(self, grp_id: int) -> List[Tuple]:
        """Получение истории технических коэффициентов"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, grp_id, coefficient_a, coefficient_b, coefficient_c, 
                   coefficient_k, n_count, u_count, m_count, r_count, 
                   to_char(diagnosis_date, 'YYYY-MM-DD HH24:MI:SS') as diagnosis_date
            FROM technical_coefficients 
            WHERE grp_id = %s
            ORDER BY diagnosis_date DESC
        ''', (grp_id,))
        result = cursor.fetchall()
        conn.close()
        return result