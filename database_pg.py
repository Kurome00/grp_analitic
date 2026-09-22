from contextlib import contextmanager
from typing import Dict, Iterator, List, Optional, Tuple
from datetime import datetime

import psycopg2

from config import DB_CONFIG


class DatabasePG:
    """Класс для работы с PostgreSQL базой данных"""

    _initialized = False

    def __init__(self, config: Dict = None):
        self.db_config = config or DB_CONFIG
        if not DatabasePG._initialized:
            self.init_db()
            DatabasePG._initialized = True

    @contextmanager
    def get_connection(self) -> Iterator['psycopg2.connection']:
        """Соединение с БД в виде контекст-менеджера."""
        conn = None
        try:
            conn = psycopg2.connect(**self.db_config)
            yield conn
            conn.commit()
        except Exception as e:
            if conn is not None:
                conn.rollback()
            print(f"❌ Ошибка работы с PostgreSQL: {e}")
            raise
        finally:
            if conn is not None:
                conn.close()

    def init_db(self):
        """Инициализация базы данных - создание всех таблиц"""
        with self.get_connection() as conn:
            cursor = conn.cursor()

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
                    install_date DATE,
                    removal_date DATE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # Миграция: дата установки перестала быть обязательной
            # (в каталоге срок службы определяется запчастями)
            try:
                cursor.execute('ALTER TABLE equipment ALTER COLUMN install_date DROP NOT NULL;')
            except Exception:
                pass

            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_equipment_grp_id ON equipment(grp_id);
                CREATE INDEX IF NOT EXISTS idx_equipment_name ON equipment(name);
            ''')

            # 3. Справочник запчастей
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS parts (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(255) NOT NULL UNIQUE,
                    norm_years DECIMAL(10,2) NOT NULL
                )
            ''')

            # 4. Состав оборудования из запчастей
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS equipment_parts (
                    id SERIAL PRIMARY KEY,
                    equipment_id INTEGER NOT NULL REFERENCES equipment(id) ON DELETE CASCADE,
                    part_id INTEGER NOT NULL REFERENCES parts(id) ON DELETE CASCADE,
                    install_date DATE,
                    removal_date DATE,
                    UNIQUE (equipment_id, part_id)
                )
            ''')

            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_eqparts_equipment_id ON equipment_parts(equipment_id);
            ''')

            # 5. Таблица документальных норм
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

            # 6. Таблица технических коэффициентов
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

            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_tech_coeff_grp_id ON technical_coefficients(grp_id);
                CREATE INDEX IF NOT EXISTS idx_tech_coeff_date ON technical_coefficients(diagnosis_date DESC);
            ''')

            # 7. Таблица замен (журнал ремонта запасных частей)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS replacements (
                    id SERIAL PRIMARY KEY,
                    grp_id INTEGER NOT NULL REFERENCES grp(id) ON DELETE CASCADE,
                    replace_date VARCHAR(255),
                    part_number VARCHAR(255),
                    equipment_type VARCHAR(255),
                    model VARCHAR(255),
                    manufacturer VARCHAR(255),
                    work_type VARCHAR(255),
                    reason TEXT,
                    supervisor VARCHAR(255),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_replacements_grp_id ON replacements(grp_id);
            ''')

        print("✅ База данных PostgreSQL инициализирована!")

    # === МЕТОДЫ ДЛЯ РАБОТЫ С ГРП ===

    def add_grp(self, grp_type: str, lines_count: int, actual_life: float, design_life: float) -> int:
        """Добавление нового ГРП"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO grp (type, lines_count, actual_life, design_life)
                VALUES (%s, %s, %s, %s)
                RETURNING id
            ''', (grp_type, lines_count, actual_life, design_life))
            return cursor.fetchone()[0]

    def update_grp(self, grp_id: int, grp_type: str, lines_count: int, actual_life: float, design_life: float):
        """Обновление данных ГРП"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE grp
                SET type = %s, lines_count = %s, actual_life = %s, design_life = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            ''', (grp_type, lines_count, actual_life, design_life, grp_id))

    def delete_grp(self, grp_id: int):
        """Удаление ГРП (оборудование и коэффициенты удаляются каскадом)"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM grp WHERE id = %s', (grp_id,))

    def get_all_grp(self) -> List[Tuple]:
        """Получение всех ГРП"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT id, type, lines_count, actual_life, design_life FROM grp ORDER BY id')
            return cursor.fetchall()

    def get_grp_by_id(self, grp_id: int) -> Optional[Tuple]:
        """Получение ГРП по ID"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT id, type, lines_count, actual_life, design_life FROM grp WHERE id = %s', (grp_id,))
            return cursor.fetchone()

    # === МЕТОДЫ ДЛЯ РАБОТЫ С ОБОРУДОВАНИЕМ ===

    def add_equipment(self, grp_id: int, name: str, install_date: str, removal_date: str = None) -> int:
        """Добавление оборудования"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO equipment (grp_id, name, install_date, removal_date)
                VALUES (%s, %s, %s, %s)
                RETURNING id
            ''', (grp_id, name, install_date, removal_date))
            return cursor.fetchone()[0]

    def get_equipment_by_grp(self, grp_id: int) -> List[Tuple]:
        """Получение оборудования по ГРП (id, name, install_date, removal_date)"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, name, install_date::text, removal_date::text
                FROM equipment WHERE grp_id = %s
                ORDER BY install_date DESC
            ''', (grp_id,))
            return cursor.fetchall()

    def update_equipment(self, equip_id: int, name: str, install_date: str, removal_date: str = None):
        """Обновление оборудования"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE equipment
                SET name = %s, install_date = %s, removal_date = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            ''', (name, install_date, removal_date, equip_id))

    def delete_equipment(self, equip_id: int):
        """Удаление оборудования"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM equipment WHERE id = %s', (equip_id,))

    def get_all_equipment_names(self) -> List[str]:
        """Уникальные наименования оборудования по всей БД (для автодополнения)."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT DISTINCT name FROM equipment ORDER BY name')
            return [r[0] for r in cursor.fetchall()]

    # === МЕТОДЫ ДЛЯ РАБОТЫ С ЗАПЧАСТЯМИ (СПРАВОЧНИК) ===

    def add_part(self, name: str, norm_years: float) -> int:
        """Добавление типа запчасти"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('INSERT INTO parts (name, norm_years) VALUES (%s, %s) ON CONFLICT (name) DO NOTHING RETURNING id', (name, norm_years))
            row = cursor.fetchone()
            if row:
                return row[0]
            return self.get_part_by_name(name)[0]

    def update_part(self, part_id: int, name: str, norm_years: float):
        """Обновление типа запчасти"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('UPDATE parts SET name = %s, norm_years = %s WHERE id = %s', (name, norm_years, part_id))

    def delete_part(self, part_id: int):
        """Удаление типа запчасти (связи удаляются каскадом)"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM parts WHERE id = %s', (part_id,))

    def get_all_parts(self) -> List[Tuple]:
        """Все типы запчастей (id, name, norm_years)"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT id, name, norm_years FROM parts ORDER BY name')
            return cursor.fetchall()

    def get_part_by_name(self, name: str) -> Optional[Tuple]:
        """Тип запчасти по имени (id, name, norm_years)"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT id, name, norm_years FROM parts WHERE name = %s', (name,))
            return cursor.fetchone()

    # === МЕТОДЫ ДЛЯ РАБОТЫ С СОСТАВОМ ОБОРУДОВАНИЯ ===

    def add_equipment_part(self, equipment_id: int, part_id: int,
                           install_date: str = None, removal_date: str = None) -> int:
        """Привязка запчасти к оборудованию (при повторе — обновление дат)"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO equipment_parts (equipment_id, part_id, install_date, removal_date)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (equipment_id, part_id)
                DO UPDATE SET install_date = EXCLUDED.install_date, removal_date = EXCLUDED.removal_date
                RETURNING id
            ''', (equipment_id, part_id, install_date, removal_date))
            return cursor.fetchone()[0]

    def update_equipment_part(self, ep_id: int, install_date: str = None, removal_date: str = None):
        """Обновление дат запчасти в составе оборудования"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE equipment_parts SET install_date = %s, removal_date = %s WHERE id = %s
            ''', (install_date, removal_date, ep_id))

    def remove_equipment_part(self, ep_id: int):
        """Удаление запчасти из состава оборудования"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM equipment_parts WHERE id = %s', (ep_id,))

    def remove_equipment_parts_by_grp(self, grp_id: int):
        """Удаление всех связей запчастей для оборудования выбранного ГРП"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                DELETE FROM equipment_parts
                WHERE equipment_id IN (SELECT id FROM equipment WHERE grp_id = %s)
            ''', (grp_id,))

    def get_equipment_parts(self, equipment_id: int) -> List[Tuple]:
        """Запчасти оборудования.

        (id, part_id, name, norm_years, install_date, removal_date)
        install_date = None означает 'дата установки оборудования'.
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT ep.id, ep.part_id, p.name, p.norm_years, ep.install_date::text, ep.removal_date::text
                FROM equipment_parts ep
                JOIN parts p ON p.id = ep.part_id
                WHERE ep.equipment_id = %s
                ORDER BY p.name
            ''', (equipment_id,))
            return cursor.fetchall()

    # === МЕТОДЫ ДЛЯ РАБОТЫ С ДОКУМЕНТАЛЬНЫМИ НОРМАМИ ===

    def get_all_norms(self) -> List[Tuple]:
        """Получение всех норм (id, equipment_name, max_life_years, notes)"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT id, equipment_name, max_life_years, notes FROM documentary_norms ORDER BY equipment_name')
            return cursor.fetchall()

    def get_norm_by_name(self, equipment_name: str) -> Optional[Tuple]:
        """Получение нормы по имени"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT id, equipment_name, max_life_years, notes FROM documentary_norms WHERE equipment_name = %s',
                (equipment_name,)
            )
            return cursor.fetchone()

    def add_norm(self, equipment_name: str, max_life_years: float, notes: str = ''):
        """Добавление нормы"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO documentary_norms (equipment_name, max_life_years, notes, created_date, updated_date)
                VALUES (%s, %s, %s, %s, %s)
            ''', (equipment_name, max_life_years, notes, datetime.now().date(), datetime.now().date()))

    def update_norm(self, norm_id: int, equipment_name: str, max_life_years: float, notes: str = ''):
        """Обновление нормы"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE documentary_norms
                SET equipment_name = %s, max_life_years = %s, notes = %s, updated_date = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            ''', (equipment_name, max_life_years, notes, datetime.now().date(), norm_id))

    def delete_norm(self, norm_id: int):
        """Удаление нормы"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM documentary_norms WHERE id = %s', (norm_id,))

    # === МЕТОДЫ ДЛЯ РАБОТЫ С ТЕХНИЧЕСКИМИ КОЭФФИЦИЕНТАМИ ===

    def save_technical_coefficients(self, grp_id: int, coef_data: Dict):
        """Сохранение технических коэффициентов"""
        with self.get_connection() as conn:
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

    def get_technical_coefficients(self, grp_id: int) -> List[Tuple]:
        """История технических коэффициентов.

        Кортежи с фиксированным порядком колонок:
        (id, diagnosis_date, a, b, c, k, n, u, m, r)
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, to_char(diagnosis_date, 'YYYY-MM-DD HH24:MI:SS') AS diagnosis_date,
                       coefficient_a, coefficient_b, coefficient_c, coefficient_k,
                       n_count, u_count, m_count, r_count
                FROM technical_coefficients
                WHERE grp_id = %s
                ORDER BY diagnosis_date DESC
            ''', (grp_id,))
            return cursor.fetchall()

    # === МЕТОДЫ ДЛЯ РАБОТЫ С ЖУРНАЛОМ ЗАМЕН ===

    def add_replacement(self, grp_id: int, replace_date: str, part_number: str,
                        equipment_type: str, model: str, manufacturer: str,
                        work_type: str, reason: str, supervisor: str) -> int:
        """Добавление записи о замене запасной части."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO replacements
                (grp_id, replace_date, part_number, equipment_type, model, manufacturer,
                 work_type, reason, supervisor)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            ''', (grp_id, replace_date, part_number, equipment_type, model, manufacturer,
                  work_type, reason, supervisor))
            return cursor.fetchone()[0]

    def update_replacement(self, repl_id: int, replace_date: str, part_number: str,
                           equipment_type: str, model: str, manufacturer: str,
                           work_type: str, reason: str, supervisor: str):
        """Обновление записи о замене запасной части."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE replacements
                SET replace_date = %s, part_number = %s, equipment_type = %s, model = %s,
                    manufacturer = %s, work_type = %s, reason = %s, supervisor = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            ''', (replace_date, part_number, equipment_type, model, manufacturer,
                  work_type, reason, supervisor, repl_id))

    def delete_replacement(self, repl_id: int):
        """Удаление записи о замене."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM replacements WHERE id = %s', (repl_id,))

    def get_replacements_by_grp(self, grp_id: int) -> List[Tuple]:
        """Замены по ГРП.

        Кортежи: (id, replace_date, part_number, equipment_type, model,
        manufacturer, work_type, reason, supervisor)
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, replace_date, part_number, equipment_type, model,
                       manufacturer, work_type, reason, supervisor
                FROM replacements
                WHERE grp_id = %s
                ORDER BY replace_date NULLS LAST, id
            ''', (grp_id,))
            return cursor.fetchall()

    def count_replacements_by_grp(self, grp_id: int) -> int:
        """Количество замен по ГРП."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM replacements WHERE grp_id = %s', (grp_id,))
            return cursor.fetchone()[0]

    def get_all_manufacturers(self) -> List[str]:
        """Уникальные производители из журнала замен (для автодополнения)."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT DISTINCT manufacturer FROM replacements
                WHERE manufacturer IS NOT NULL AND manufacturer <> ''
                ORDER BY manufacturer
            ''')
            return [r[0] for r in cursor.fetchall()]