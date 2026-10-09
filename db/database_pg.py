from contextlib import contextmanager
from typing import Dict, Iterator, List, Optional, Tuple
from datetime import datetime

import psycopg2

from core.config import DB_CONFIG, REPLACEABLE_NORM_YEARS, part_norm
from core.grp_passport import BASE_COLUMNS, COLUMNS, PASSPORT_COLUMNS, ROW_COLUMNS
from core.equipment_card import DETAIL_COLUMNS as CARD_COLUMNS
from core.equipment_card import ROW_COLUMNS as EQUIPMENT_ROW_COLUMNS
from core import diagnostic_log
from core import failure_log
from core import repair_journal


class DatabasePG:
    """Класс для работы с PostgreSQL базой данных"""

    _initialized = False

    def __init__(self, config: Dict = None):
        self.db_config = config or DB_CONFIG
        if not DatabasePG._initialized:
            self.init_db()
            DatabasePG._initialized = True

    @staticmethod
    def _error_text(exc: Exception) -> str:
        """Текст ошибки PostgreSQL.

        psycopg2 декодирует служебные сообщения сервера в кодировке клиента.
        На части установок (Windows, не-UTF8 локаль) текст остаётся в
        cp1251, и обычный str(exc) сам падает с UnicodeDecodeError, заменяя
        исходную ошибку. Поэтому приводим текст безопасно, с заменой
        нечитаемых байтов, — иначе пользователь видит «codec can't decode»
        вместо причины.
        """
        try:
            return str(exc)
        except UnicodeDecodeError:
            return exc.__class__.__name__ + ' (сообщение сервера в нечитаемой кодировке)'

    def ensure_database_exists(self) -> bool:
        """Создаёт базу из DB_CONFIG, если её ещё нет.

        Нужна для свежей установки: после git clone базы grp_analyzer
        на компьютере нет, и без этого шага приложение падает при старте.
        Требуется право CREATEDB у пользователя из DB_CONFIG.
        """
        dbname = self.db_config.get('database')
        if not dbname:
            return False
        try:
            probe = psycopg2.connect(**self.db_config)
            probe.close()
            return False          # база уже есть — ничего создавать не нужно
        except (psycopg2.OperationalError, UnicodeDecodeError):
            # Базы нет: сервер отвечает ошибкой, которую psycopg2 на части
            # установок не может декодировать. Пробуем создать базу.
            pass
        except Exception as e:
            print('⚠️  Проверка базы не удалась:', self._error_text(e))

        admin = dict(self.db_config, database='postgres')
        conn = psycopg2.connect(**admin)
        conn.autocommit = True
        try:
            with conn.cursor() as cur:
                cur.execute('SELECT 1 FROM pg_database WHERE datname = %s', (dbname,))
                if cur.fetchone():
                    return False
                cur.execute(f'CREATE DATABASE "{dbname}"')
                print(f"[+] База данных '{dbname}' создана")
                return True
        finally:
            conn.close()

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
            print("❌ Ошибка работы с PostgreSQL:", self._error_text(e))
            raise
        finally:
            if conn is not None:
                conn.close()

    def init_db(self):
        """Инициализация базы данных - создание всех таблиц"""
        self.ensure_database_exists()
        with self.get_connection() as conn:
            cursor = conn.cursor()

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

            # 1.1 Сведения паспорта ГРП (раздел 1). Хранятся текстом: даты
            # приёмки и ввода в паспорте указаны с точностью до месяца
            # («01.1981», «10.2007»), DATE такого не представляет, а
            # «Закольцован с» — свободный список объектов. NOT NULL DEFAULT ''
            # убирает третье состояние (NULL рядом с пустой строкой): отчёт
            # печатает прочерк по пустому значению.
            for column in PASSPORT_COLUMNS:
                cursor.execute(
                    f"ALTER TABLE grp ADD COLUMN IF NOT EXISTS {column} "
                    f"TEXT NOT NULL DEFAULT ''")

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

            # Паспортные сведения единицы оборудования (core.equipment_card).
            # Добавляются колонками в конец: прежние поля сохраняют индексы,
            # по которым их читают расчёт и интерфейс. Текстом — как раздел 1
            # паспорта ГРП: числа переносятся так, как написаны в документации,
            # и в расчёте не участвуют.
            for column in CARD_COLUMNS:
                cursor.execute(
                    f"ALTER TABLE equipment ADD COLUMN IF NOT EXISTS {column} "
                    f"TEXT NOT NULL DEFAULT ''")

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
            cursor.execute('ALTER TABLE parts ADD COLUMN IF NOT EXISTS is_replaceable BOOLEAN NOT NULL DEFAULT FALSE')

            # 4. Состав оборудования из запчастей
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS equipment_parts (
                    id SERIAL PRIMARY KEY,
                    equipment_id INTEGER NOT NULL REFERENCES equipment(id) ON DELETE CASCADE,
                    part_id INTEGER NOT NULL REFERENCES parts(id) ON DELETE CASCADE,
                    install_date DATE,
                    removal_date DATE
                )
            ''')
            # Обозначение детали (каталожный номер) у каждой модели своё —
            # держим его на связи оборудования с деталью.
            cursor.execute('ALTER TABLE equipment_parts ADD COLUMN IF NOT EXISTS part_number VARCHAR(255)')
            # История замен: активной может быть только одна запись одной детали.
            # Снимаем старый UNIQUE в пользу частичного индекса.
            cursor.execute('''
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1 FROM pg_constraint
                        WHERE conname = 'equipment_parts_equipment_id_part_id_key'
                    ) THEN
                        ALTER TABLE equipment_parts DROP CONSTRAINT equipment_parts_equipment_id_part_id_key;
                    END IF;
                END $$;
            ''')
            cursor.execute('''
                CREATE UNIQUE INDEX IF NOT EXISTS uq_eqparts_active
                ON equipment_parts (equipment_id, part_id) WHERE removal_date IS NULL
            ''')

            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_eqparts_equipment_id ON equipment_parts(equipment_id);
            ''')
            cursor.execute('DROP TABLE IF EXISTS documentary_norms')

            # 5. Таблица технических коэффициентов
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

            # 7.1 Связь записи журнала с физическим объектом.
            # effect: '' — журнал без влияния на срок, 'part' — сброшен срок
            # детали, 'equipment' — сброшены сроки всего оборудования.
            # Внешних ключей намеренно нет: журнал — исторический документ и
            # должен пережить удаление оборудования.
            # hours_before / residual_after / document / note — графы
            # ремонтного журнала (см. core.repair_journal): наработка до
            # замены, остаточный ресурс после ремонта, документ-основание и
            # примечание. Добавлены в конец, поэтому прежние поля записи
            # сохранили свои индексы — по ним читают «Замены.xlsx», отчёт Word
            # и расчёт методик.
            for column, dtype in (('equipment_id', 'INTEGER'),
                                  ('part_id', 'INTEGER'),
                                  ('new_equipment_id', 'INTEGER'),
                                  ('effect', "VARCHAR(16) NOT NULL DEFAULT ''"),
                                  ('hours_before', 'VARCHAR(64)'),
                                  ('residual_after', 'VARCHAR(64)'),
                                  ('document', 'VARCHAR(255)'),
                                  ('note', 'TEXT')):
                cursor.execute(
                    f'ALTER TABLE replacements ADD COLUMN IF NOT EXISTS {column} {dtype}')

            # 8. Таблица отказов (информация по отказам).
            # Графы записи — те же, что в таблице экрана (см. core.failure_log):
            # дата выявления, тип события, причина, критичность, признак
            # устранения, документ, куда отказ вносится, и примечания.
            # Критичность и признак устранения NOT NULL DEFAULT '': пустая
            # строка здесь значит «не указано», третье состояние (NULL) не
            # нужно.
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS failures (
                    id SERIAL PRIMARY KEY,
                    grp_id INTEGER NOT NULL REFERENCES grp(id) ON DELETE CASCADE,
                    detected_date VARCHAR(255),
                    event_type VARCHAR(255),
                    reason TEXT,
                    criticality VARCHAR(32) NOT NULL DEFAULT '',
                    resolved VARCHAR(16) NOT NULL DEFAULT '',
                    document VARCHAR(255),
                    note TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            # Фото (или скан акта) хранится в базе отдельной колонкой: к
            # записи может быть приложен снимок, но список отказов читается
            # без него — иначе таблица тянула бы из базы всё содержимое
            # снимков.
            cursor.execute('ALTER TABLE failures ADD COLUMN IF NOT EXISTS photo BYTEA')

            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_failures_grp_id ON failures(grp_id);
            ''')

            # 9. Таблица технического диагностирования (протокол проверок).
            # Графы записи — те же, что в таблице экрана (см.
            # core.diagnostic_log): дата, оборудование, проверяемый параметр,
            # режим, допуск мин/макс, факт мин/макс, результат и примечание.
            # Все значения в кПа хранятся текстом, как их перенесли из
            # протокола: «1,3» и «1,30» — одно и то же число, но запись должна
            # читаться так, как её вписал специалист.
            # Результат NOT NULL DEFAULT '': пустая строка значит «не указан»,
            # третье состояние (NULL) не нужно.
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS diagnostic_checks (
                    id SERIAL PRIMARY KEY,
                    grp_id INTEGER NOT NULL REFERENCES grp(id) ON DELETE CASCADE,
                    check_date VARCHAR(255),
                    equipment VARCHAR(255),
                    parameter VARCHAR(255),
                    mode VARCHAR(64),
                    tolerance_min VARCHAR(64),
                    tolerance_max VARCHAR(64),
                    fact_min VARCHAR(64),
                    fact_max VARCHAR(64),
                    result VARCHAR(32) NOT NULL DEFAULT '',
                    note TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_diagnostic_checks_grp_id
                    ON diagnostic_checks(grp_id);
            ''')

            print("✅ База данных PostgreSQL инициализирована!")

    # === МЕТОДЫ ДЛЯ РАБОТЫ С ГРП ===

    def add_grp(self, grp_type: str, lines_count: int, actual_life: float,
                design_life: float, passport: Dict = None) -> int:
        """Добавление нового ГРП.

        passport — сведения паспорта {ключ: значение} (см. core.grp_passport);
        незаполненные поля сохраняются пустыми строками. Параметр
        необязательный, поэтому старые вызовы с четырьмя аргументами
        (seed.py) продолжают работать.
        """
        fields = dict(passport or {})
        columns = list(COLUMNS)
        params = [grp_type, lines_count, actual_life, design_life] + [
            fields.get(column) or '' for column in PASSPORT_COLUMNS]
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f'INSERT INTO grp ({", ".join(columns)}) '
                f'VALUES ({", ".join(["%s"] * len(columns))}) '
                f'RETURNING id',
                params)
            return cursor.fetchone()[0]

    def update_grp(self, grp_id: int, grp_type: str, lines_count: int,
                   actual_life: float, design_life: float,
                   passport: Dict = None):
        """Обновление данных ГРП.

        passport=None — паспортные поля не трогаем: так обновляют ГРП из
        кода, которому сведения паспорта не нужны.
        """
        fields = dict(passport or {})
        columns = list(BASE_COLUMNS)
        params = [grp_type, lines_count, actual_life, design_life]
        if passport is not None:
            columns += list(PASSPORT_COLUMNS)
            params += [fields.get(column) or '' for column in PASSPORT_COLUMNS]
        params.append(grp_id)
        assignments = ', '.join(f'{column} = %s' for column in columns)
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f'UPDATE grp SET {assignments}, '
                f'updated_at = CURRENT_TIMESTAMP WHERE id = %s',
                params)

    def delete_grp(self, grp_id: int):
        """Удаление ГРП (оборудование и коэффициенты удаляются каскадом)"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM grp WHERE id = %s', (grp_id,))

    def get_all_grp(self) -> List[Tuple]:
        """Получение всех ГРП (id, type, lines_count, actual_life, design_life)"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT id, type, lines_count, actual_life, design_life FROM grp ORDER BY id')
            return cursor.fetchall()

    def get_grp_by_id(self, grp_id: int) -> Optional[Tuple]:
        """Получение ГРП по ID.

        Порядок колонок — core.grp_passport.ROW_COLUMNS: сначала id и четыре
        прежних поля (по их индексам читают интерфейс и отчёт), затем сведения
        паспорта. Спискам паспорт не нужен, поэтому get_all_grp не расширяется.
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f'SELECT {", ".join(ROW_COLUMNS)} FROM grp WHERE id = %s',
                (grp_id,))
            return cursor.fetchone()

    # === МЕТОДЫ ДЛЯ РАБОТЫ С ОБОРУДОВАНИЕМ ===

    @staticmethod
    def _card_values(details: Optional[Dict]) -> List[str]:
        """Паспортные сведения для записи: чего не передали — пустая строка.

        Пустая строка, а не NULL: у колонок NOT NULL DEFAULT '', и «не
        заполнено» в паспорте изображается прочерком, а не третьим состоянием.
        """
        details = details or {}
        return [str(details.get(column) or '') for column in CARD_COLUMNS]

    def add_equipment(self, grp_id: int, name: str, install_date: str,
                      removal_date: str = None,
                      details: Optional[Dict] = None) -> int:
        """Добавление оборудования.

        details — паспортные сведения единицы (core.equipment_card.
        DETAIL_COLUMNS): тип (модель), изготовитель, ДУ, количество, номер по
        схеме, назначенный срок и наработки, примечание.
        """
        columns = ('grp_id', 'name', 'install_date', 'removal_date') + CARD_COLUMNS
        placeholders = ', '.join(['%s'] * len(columns))
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f'''
                INSERT INTO equipment ({', '.join(columns)})
                VALUES ({placeholders})
                RETURNING id
                ''',
                (grp_id, name, install_date, removal_date)
                + tuple(self._card_values(details)))
            return cursor.fetchone()[0]

    def get_equipment_by_grp(self, grp_id: int) -> List[Tuple]:
        """Оборудование ГРП: id, name, install_date, removal_date и паспортные
        сведения — порядок колонок задаёт core.equipment_card.ROW_COLUMNS."""
        columns = ', '.join(
            f'{column}::text' if column in ('install_date', 'removal_date')
            else column
            for column in EQUIPMENT_ROW_COLUMNS)
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f'''
                SELECT {columns}
                FROM equipment WHERE grp_id = %s
                ORDER BY install_date DESC
                ''', (grp_id,))
            return cursor.fetchall()

    def update_equipment(self, equip_id: int, name: str, install_date: str,
                         removal_date: str = None,
                         details: Optional[Dict] = None):
        """Обновление оборудования вместе с паспортными сведениями.

        Сведения, которых нет в details, обнуляются — форма всегда присылает
        полный набор полей, поэтому «очистил поле» значит «стёр значение».
        """
        assignments = ', '.join(f'{column} = %s' for column in CARD_COLUMNS)
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f'''
                UPDATE equipment
                SET name = %s, install_date = %s, removal_date = %s, {assignments},
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                ''',
                (name, install_date, removal_date)
                + tuple(self._card_values(details)) + (equip_id,))

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

    def add_part(self, name: str, norm_years: float,
                 is_replaceable: bool = False) -> int:
        """Добавление типа запчасти.

        norm_years — нормативный срок службы. Если не задан, берётся из
        config.part_norm(is_replaceable): 5 лет для заменяемой детали,
        срок полной проверки (20 лет) для остальной.
        """
        if norm_years is None:
            norm_years = part_norm(is_replaceable)
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'INSERT INTO parts (name, norm_years, is_replaceable) VALUES (%s, %s, %s) '
                'ON CONFLICT (name) DO NOTHING RETURNING id',
                (name, norm_years, is_replaceable))
            row = cursor.fetchone()
            if row:
                return row[0]
            # Деталь уже была в справочнике: ON CONFLICT ничего не вставил.
            existing = self.get_part_by_name(name)
            if existing is None:
                # Строка не нашлась — имя отличается от записанного в БД
                # (регистр, пробелы) либо его удалили между запросами.
                # Раньше здесь возникал TypeError: NoneType не поддерживает
                # индексацию, и импорт падал без внятной причины.
                raise ValueError(
                    f'Не удалось добавить запчасть «{name}»: запись с таким '
                    f'именем уже существует, но прочитать её не удалось. '
                    f'Проверьте имя на совпадение (регистр, лишние пробелы).')
            return existing[0]

    def update_part(self, part_id: int, name: str, norm_years: float):
        """Обновление типа запчасти"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('UPDATE parts SET name = %s, norm_years = %s WHERE id = %s', (name, norm_years, part_id))

    def update_part_norm(self, part_id: int, norm_years: float):
        """Задать нормативный срок службы детали"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('UPDATE parts SET norm_years = %s WHERE id = %s',
                           (norm_years, part_id))

    def align_norms_with_replaceable(self) -> Dict[str, int]:
        """Миграция норм: заменяемые детали — 5 лет, остальные — 20 лет.

        Прежний дефолт для всех деталей был 5 лет, поэтому норма ровно
        REPLACEABLE_NORM_YEARS считалась не заданной вручную: она
        приводится к сроку, который полагается по признаку заменяемости.
        Значения, не равные ни прежнему дефолту, ни ожидаемому сроку,
        оставлены как есть. Возвращает счётчики: raise_to / lower_to /
        manual / ok.
        """
        counters = {'raise_to': 0, 'lower_to': 0, 'manual': 0, 'ok': 0}
        legacy = REPLACEABLE_NORM_YEARS
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT id, norm_years, is_replaceable FROM parts')
            rows = cursor.fetchall()
        for part_id, norm_years, is_replaceable in rows:
            expected = part_norm(bool(is_replaceable))
            current = float(norm_years)
            if abs(current - expected) <= 1e-9:
                counters['ok'] += 1
                continue
            if abs(current - legacy) > 1e-9:
                counters['manual'] += 1
                continue
            self.update_part_norm(part_id, expected)
            counters['lower_to' if expected < legacy else 'raise_to'] += 1
        return counters

    def get_all_parts(self) -> List[Tuple]:
        """Все типы запчастей (id, name, norm_years, is_replaceable)"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT id, name, norm_years, is_replaceable FROM parts ORDER BY name')
            return cursor.fetchall()

    def get_part_by_name(self, name: str) -> Optional[Tuple]:
        """Тип запчасти по имени (id, name, norm_years, is_replaceable)"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT id, name, norm_years, is_replaceable FROM parts WHERE name = %s', (name,))
            return cursor.fetchone()

    # === МЕТОДЫ ДЛЯ РАБОТЫ С СОСТАВОМ ОБОРУДОВАНИЯ ===

    def add_equipment_part(self, equipment_id: int, part_id: int,
                           install_date: str = None, removal_date: str = None,
                           part_number: str = None) -> int:
        """Привязка запчасти к оборудованию.

        Активная запись детали может быть только одна (частичный индекс
        на removal_date IS NULL). При повторном активном связывании —
        обновление дат. part_number — обозначение (каталожный номер) детали
        в составе данной модели.
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO equipment_parts (equipment_id, part_id, install_date, removal_date, part_number)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (equipment_id, part_id) WHERE removal_date IS NULL
                DO UPDATE SET install_date = EXCLUDED.install_date, removal_date = EXCLUDED.removal_date,
                              part_number = EXCLUDED.part_number
                RETURNING id
            ''', (equipment_id, part_id, install_date, removal_date, part_number))
            return cursor.fetchone()[0]

    def replace_equipment_part(self, equipment_id: int, part_id: int, replace_date: str) -> int:
        """Физическая замена детали в составе оборудования.

        Отмечает снятие текущей активной записи (removal_date = дата замены)
        и создаёт новую активную запись той же детали с датой установки =
        дата замены, перенося обозначение. Возвращает id новой записи.
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT ep.id, ep.part_number FROM equipment_parts ep
                WHERE ep.equipment_id = %s AND ep.part_id = %s AND ep.removal_date IS NULL
            ''', (equipment_id, part_id))
            current = cursor.fetchone()
            if current is None:
                raise ValueError('Активная запись детали не найдена')
            old_ep_id, part_number = current
            cursor.execute(
                'UPDATE equipment_parts SET removal_date = %s WHERE id = %s',
                (replace_date, old_ep_id))
            cursor.execute('''
                INSERT INTO equipment_parts (equipment_id, part_id, install_date, removal_date, part_number)
                VALUES (%s, %s, %s, NULL, %s) RETURNING id
            ''', (equipment_id, part_id, replace_date, part_number))
            return cursor.fetchone()[0]

    def replace_equipment_completely(self, equipment_id: int, replace_date: str,
                                     new_name: str = None,
                                     part_dates: Dict[int, str] = None,
                                     add_journal: bool = True,
                                     equipment_type: str = None,
                                     manufacturer: str = None,
                                     work_type: str = None,
                                     reason: str = None,
                                     supervisor: str = None,
                                     grp_id: int = None) -> int:
        """Полная замена оборудования целиком.

        Прежнее оборудование снимается с эксплуатации датой замены, все его
        активные детали закрываются той же датой. Создаётся новая запись
        оборудования с датой установки = дата замены, и прежний состав
        деталей переносится на неё с той же датой установки.

        Из этого следует главное для расчёта: срок службы каждой детали
        отсчитывается заново от даты замены, а не от даты установки старого
        оборудования. Для деталей, у которых индивидуальная дата установки
        отличалась от даты установки оборудования, её можно задать явно через
        part_dates: {equipment_part_id: 'ДД.ММ.ГГГГ'}; остальные получают дату
        замены. Если состав деталей нужно оставить прежним — передайте
        part_dates = None (переносится весь прежний состав).

        Возвращает id новой записи оборудования.
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT e.grp_id, e.name, e.install_date::text
                FROM equipment e WHERE e.id = %s
            ''', (equipment_id,))
            current = cursor.fetchone()
            if current is None:
                raise ValueError('Оборудование не найдено')
            old_grp_id, old_name, old_install = current

            if not replace_date:
                raise ValueError('Не указана дата замены')
            if old_install and replace_date < old_install:
                raise ValueError(
                    f'Дата замены ({replace_date}) раньше даты установки '
                    f'оборудования ({old_install})')

            # Состав прежних активных деталей: (equipment_part_id, part_id, part_number)
            cursor.execute('''
                SELECT ep.id, ep.part_id, ep.part_number
                FROM equipment_parts ep
                WHERE ep.equipment_id = %s AND ep.removal_date IS NULL
                ORDER BY ep.id
            ''', (equipment_id,))
            parts = cursor.fetchall()

            # Прежнее оборудование и его детали выводятся из эксплуатации
            cursor.execute(
                'UPDATE equipment SET removal_date = %s, updated_at = CURRENT_TIMESTAMP '
                'WHERE id = %s', (replace_date, equipment_id))
            cursor.execute(
                'UPDATE equipment_parts SET removal_date = %s '
                'WHERE equipment_id = %s AND removal_date IS NULL',
                (replace_date, equipment_id))

            # Новое оборудование с новой датой установки. Паспортные сведения
            # переносятся от прежней единицы: меняется единица, а не её
            # характеристики (тип, изготовитель, ДУ, назначенный срок).
            card_columns = ', '.join(CARD_COLUMNS)
            cursor.execute(
                f'''
                INSERT INTO equipment
                    (grp_id, name, install_date, removal_date, {card_columns})
                SELECT %s, %s, %s, NULL, {card_columns}
                FROM equipment WHERE id = %s
                RETURNING id
                ''', (old_grp_id, new_name or old_name, replace_date, equipment_id))
            new_equipment_id = cursor.fetchone()[0]

            # Состав переносится с новой датой установки — сроки заново
            for ep_id, part_id, part_number in parts:
                part_install = (part_dates or {}).get(ep_id, replace_date)
                cursor.execute('''
                    INSERT INTO equipment_parts
                        (equipment_id, part_id, install_date, removal_date, part_number)
                    VALUES (%s, %s, %s, NULL, %s)
                ''', (new_equipment_id, part_id, part_install, part_number))

            if add_journal:
                cursor.execute('''
                    INSERT INTO replacements
                        (grp_id, replace_date, part_number, equipment_type, model,
                         manufacturer, work_type, reason, supervisor)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ''', (grp_id or old_grp_id, replace_date,
                      'полная замена оборудования', equipment_type, old_name,
                      manufacturer, work_type or 'Замена',
                      reason or 'полная замена оборудования', supervisor))
            return new_equipment_id

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

    def get_equipment_parts_full(self, equipment_id: int) -> List[Tuple]:
        """Запчасти оборудования с доп. полями.

        (id, part_id, name, norm_years, install_date, removal_date,
         part_number, is_replaceable)
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT ep.id, ep.part_id, p.name, p.norm_years,
                       ep.install_date::text, ep.removal_date::text,
                       ep.part_number, p.is_replaceable
                FROM equipment_parts ep
                JOIN parts p ON p.id = ep.part_id
                WHERE ep.equipment_id = %s
                ORDER BY p.name, ep.install_date NULLS FIRST, ep.id
            ''', (equipment_id,))
            return cursor.fetchall()

    def update_part_replaceable(self, part_id: int, is_replaceable: bool):
        """Отметить деталь в справочнике как заменяемую / не заменяемую."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('UPDATE parts SET is_replaceable = %s WHERE id = %s', (is_replaceable, part_id))

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
                        work_type: str, reason: str, supervisor: str,
                        equipment_id: int = None, part_id: int = None,
                        effect: str = '', new_equipment_id: int = None,
                        extras: Dict = None) -> int:
        """Добавление записи о замене запасной части.

        equipment_id / part_id / effect связывают запись с физическим объектом
        и определяют, что делает запись со сроком службы:
          effect=''         — только журнал, сроки не меняются;
          effect='part'     — срок детали отсчитывается заново с replace_date;
          effect='equipment' — срок всего оборудования (new_equipment_id).

        extras — графы ремонтного журнала {ключ: значение} (см.
        core.repair_journal): наработка до замены, остаточный ресурс после
        ремонта, документ-основание, примечание.
        """
        extras = extras or {}
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO replacements
                (grp_id, replace_date, part_number, equipment_type, model, manufacturer,
                 work_type, reason, supervisor, equipment_id, part_id, effect,
                 new_equipment_id, hours_before, residual_after, document, note)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s)
                RETURNING id
            ''', (grp_id, replace_date, part_number, equipment_type, model, manufacturer,
                  work_type, reason, supervisor, equipment_id, part_id,
                  effect or '', new_equipment_id,
                  extras.get('hours_before'), extras.get('residual_after'),
                  extras.get('document'), extras.get('note')))
            return cursor.fetchone()[0]

    def update_replacement(self, repl_id: int, replace_date: str, part_number: str,
                           equipment_type: str, model: str, manufacturer: str,
                           work_type: str, reason: str, supervisor: str,
                           equipment_id: int = None, part_id: int = None,
                           effect: str = None, new_equipment_id: int = None,
                           clear_links: bool = False, extras: Dict = None):
        """Обновление записи о замене запасной части.

        effect=None — оставить прежнюю привязку к оборудованию/детали;
        effect='' — привязка остаётся, но запись на сроки не влияет.
        clear_links=True — привязку снести (NULL), в том числе effect.
        extras — графы ремонтного журнала (см. add_replacement); записываются
        как показаны в форме, поэтому пустое значение стирает прежнее.
        """
        extras = extras or {}
        if clear_links:
            equipment_id = part_id = new_equipment_id = None
            effect = effect or ''
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE replacements
                SET replace_date = %s, part_number = %s, equipment_type = %s, model = %s,
                    manufacturer = %s, work_type = %s, reason = %s, supervisor = %s,
                    equipment_id = COALESCE(%s, equipment_id),
                    part_id = COALESCE(%s, part_id),
                    effect = COALESCE(%s, effect),
                    new_equipment_id = COALESCE(%s, new_equipment_id),
                    hours_before = %s, residual_after = %s, document = %s, note = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            ''', (replace_date, part_number, equipment_type, model, manufacturer,
                  work_type, reason, supervisor, equipment_id, part_id, effect,
                  new_equipment_id, extras.get('hours_before'),
                  extras.get('residual_after'), extras.get('document'),
                  extras.get('note'), repl_id))
            if clear_links:
                cursor.execute('''
                    UPDATE replacements
                    SET equipment_id = NULL, part_id = NULL, new_equipment_id = NULL,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                ''', (repl_id,))

    def delete_replacement(self, repl_id: int):
        """Удаление записи о замене."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM replacements WHERE id = %s', (repl_id,))

    def get_replacement(self, repl_id: int) -> Optional[Tuple]:
        """Одна запись журнала.

        Порядок полей — core.repair_journal.RECORD_COLUMNS: девять прежних
        полей, привязка (equipment_id, part_id, effect, new_equipment_id) и
        графы ремонтного журнала.
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, replace_date, part_number, equipment_type, model,
                       manufacturer, work_type, reason, supervisor,
                       equipment_id, part_id, effect, new_equipment_id,
                       hours_before, residual_after, document, note
                FROM replacements WHERE id = %s
            ''', (repl_id,))
            return cursor.fetchone()

    def get_replacements_by_grp(self, grp_id: int) -> List[Tuple]:
        """Замены по ГРП.

        Порядок полей — core.repair_journal.BY_GRP_COLUMNS: восемь прежних
        полей («Замены.xlsx», отчёт Word, расчёт методик читают их по
        индексам) и графы ремонтного журнала в конце.
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, replace_date, part_number, equipment_type, model,
                       manufacturer, work_type, reason, supervisor,
                       hours_before, residual_after, document, note
                FROM replacements
                WHERE grp_id = %s
                ORDER BY replace_date NULLS LAST, id
            ''', (grp_id,))
            return cursor.fetchall()

    def get_replacements_detailed(self, grp_id: int) -> List[Tuple]:
        """Замены по ГРП с привязкой к физическому объекту.

        Порядок полей — core.repair_journal.DETAILED_COLUMNS: запись целиком,
        затем названия оборудования и запчасти и номер по схеме — из них
        собираются графы журнала.
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT r.id, r.replace_date, r.part_number, r.equipment_type, r.model,
                       r.manufacturer, r.work_type, r.reason, r.supervisor,
                       r.equipment_id, r.part_id, r.effect, r.new_equipment_id,
                       r.hours_before, r.residual_after, r.document, r.note,
                       e.name, p.name, e.scheme_number
                FROM replacements r
                LEFT JOIN equipment e ON e.id = r.equipment_id
                LEFT JOIN parts p ON p.id = r.part_id
                WHERE r.grp_id = %s
                ORDER BY r.replace_date NULLS LAST, r.id
            ''', (grp_id,))
            return cursor.fetchall()

    def revert_replacement_effect(self, repl_id: int) -> str:
        """Отменить влияние записи журнала на сроки.

        Возвращает описание того, что восстановлено ('' — ничего не менялось).
        """
        record = self.get_replacement(repl_id)
        if not record:
            return ''
        # Поля читаются по именам, а не распаковкой: строка выборки растёт
        # (см. core.repair_journal), и числовая распаковка сломалась бы.
        columns = repair_journal.RECORD_COLUMNS
        row = list(record) + [None] * len(columns)
        effect = row[columns.index('effect')]
        if effect not in ('part', 'equipment'):
            return ''
        replace_date = row[columns.index('replace_date')]
        equipment_id = row[columns.index('equipment_id')]
        part_id = row[columns.index('part_id')]
        new_equipment_id = row[columns.index('new_equipment_id')]
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if effect == 'part' and equipment_id and part_id:
                cursor.execute('''
                    DELETE FROM equipment_parts
                    WHERE id = (SELECT id FROM equipment_parts
                                WHERE equipment_id = %s AND part_id = %s
                                  AND removal_date IS NULL AND install_date::text = %s
                                ORDER BY id DESC LIMIT 1)
                ''', (equipment_id, part_id, replace_date))
                cursor.execute('''
                    UPDATE equipment_parts SET removal_date = NULL
                    WHERE id = (SELECT id FROM equipment_parts
                                WHERE equipment_id = %s AND part_id = %s
                                  AND removal_date::text = %s
                                ORDER BY id DESC LIMIT 1)
                ''', (equipment_id, part_id, replace_date))
                return 'срок запчасти восстановлен'
            if effect == 'equipment' and equipment_id:
                if new_equipment_id:
                    cursor.execute('DELETE FROM equipment WHERE id = %s', (new_equipment_id,))
                cursor.execute(
                    'UPDATE equipment SET removal_date = NULL, updated_at = CURRENT_TIMESTAMP '
                    'WHERE id = %s', (equipment_id,))
                cursor.execute('''
                    UPDATE equipment_parts SET removal_date = NULL
                    WHERE equipment_id = %s AND removal_date::text = %s
                      AND (install_date::text IS DISTINCT FROM %s)
                ''', (equipment_id, replace_date, replace_date))
                return 'срок оборудования восстановлен'
        return ''

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

    # === МЕТОДЫ ДЛЯ РАБОТЫ С ОТКАЗАМИ ===

    def add_failure(self, grp_id: int, fields: Dict,
                    photo: bytes = None) -> int:
        """Добавление записи об отказе.

        fields — графы записи {ключ: значение} (см. core.failure_log.values):
        дата выявления, тип события, причина, критичность, устранён, документ
        и примечания. photo — снимок (или скан акта) байтами: он хранится
        отдельной колонкой и в графы записи не входит.
        """
        values = dict(fields or {})
        columns = ['grp_id'] + list(failure_log.FIELDS)
        params = [grp_id] + [values.get(key) for key in failure_log.FIELDS]
        if photo is not None:
            columns.append('photo')
            params.append(psycopg2.Binary(photo))
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f'INSERT INTO failures ({", ".join(columns)}) '
                f'VALUES ({", ".join(["%s"] * len(columns))}) RETURNING id',
                params)
            return cursor.fetchone()[0]

    def update_failure(self, failure_id: int, fields: Dict):
        """Обновление граф записи об отказе (фото меняется отдельно).

        Графы записываются как показаны в форме, поэтому пустое значение
        стирает прежнее.
        """
        values = dict(fields or {})
        assignments = ', '.join(f'{key} = %s' for key in failure_log.FIELDS)
        params = [values.get(key) for key in failure_log.FIELDS] + [failure_id]
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f'UPDATE failures SET {assignments}, '
                f'updated_at = CURRENT_TIMESTAMP WHERE id = %s',
                params)

    def delete_failure(self, failure_id: int):
        """Удаление записи об отказе вместе с приложенным фото."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM failures WHERE id = %s', (failure_id,))

    def get_failure(self, failure_id: int) -> Optional[Tuple]:
        """Одна запись об отказе.

        Порядок полей — core.failure_log.RECORD_COLUMNS: графы записи и
        отметка о приложенном фото (сами байты берёт get_failure_photo).
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, detected_date, event_type, reason, criticality,
                       resolved, document, note, (photo IS NOT NULL) AS has_photo
                FROM failures WHERE id = %s
            ''', (failure_id,))
            return cursor.fetchone()

    def get_failures_by_grp(self, grp_id: int) -> List[Tuple]:
        """Отказы по ГРП — свежие сверху.

        Порядок полей — core.failure_log.RECORD_COLUMNS. Даты записаны
        текстом, поэтому свежие сверху стоят по ISO-виду (его и пишет форма).
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, detected_date, event_type, reason, criticality,
                       resolved, document, note, (photo IS NOT NULL) AS has_photo
                FROM failures
                WHERE grp_id = %s
                ORDER BY detected_date DESC NULLS LAST, id DESC
            ''', (grp_id,))
            return cursor.fetchall()

    def get_failure_photo(self, failure_id: int) -> Optional[bytes]:
        """Фото записи об отказе байтами; None — фото не приложено."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT photo FROM failures WHERE id = %s',
                           (failure_id,))
            row = cursor.fetchone()
        if not row or row[0] is None:
            return None
        # psycopg2 отдаёт bytea как memoryview.
        return bytes(row[0])

    def set_failure_photo(self, failure_id: int, data: bytes = None):
        """Приложить фото к записи (data=None — убрать приложенное)."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'UPDATE failures SET photo = %s, updated_at = CURRENT_TIMESTAMP '
                'WHERE id = %s',
                (psycopg2.Binary(data) if data is not None else None,
                 failure_id))

    # === МЕТОДЫ ДЛЯ РАБОТЫ С ТЕХНИЧЕСКИМ ДИАГНОСТИРОВАНИЕМ ===

    @staticmethod
    def _diagnostic_select() -> str:
        """Список полей выборки проверок — по описанию core.diagnostic_log.

        Порядок граф берётся из описания, а не пишется в запросе: строка
        выборки читается по RECORD_COLUMNS, и перестановка граф в описании
        должна переносить за собой и запрос.
        """
        return 'id, ' + ', '.join(diagnostic_log.FIELDS)

    def add_diagnostic_check(self, grp_id: int, fields: Dict) -> int:
        """Добавление записи технического диагностирования.

        fields — графы записи {ключ: значение} (см. core.diagnostic_log.values):
        дата, оборудование, проверяемый параметр, режим, допуск мин/макс,
        факт мин/макс, результат и примечание.
        """
        values = dict(fields or {})
        columns = ['grp_id'] + list(diagnostic_log.FIELDS)
        params = [grp_id] + [values.get(key) for key in diagnostic_log.FIELDS]
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f'INSERT INTO diagnostic_checks ({", ".join(columns)}) '
                f'VALUES ({", ".join(["%s"] * len(columns))}) RETURNING id',
                params)
            return cursor.fetchone()[0]

    def update_diagnostic_check(self, check_id: int, fields: Dict):
        """Обновление граф записи проверки.

        Графы записываются как показаны в форме, поэтому пустое значение
        стирает прежнее.
        """
        values = dict(fields or {})
        assignments = ', '.join(f'{key} = %s' for key in diagnostic_log.FIELDS)
        params = [values.get(key) for key in diagnostic_log.FIELDS] + [check_id]
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f'UPDATE diagnostic_checks SET {assignments}, '
                f'updated_at = CURRENT_TIMESTAMP WHERE id = %s',
                params)

    def delete_diagnostic_check(self, check_id: int):
        """Удаление записи проверки."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM diagnostic_checks WHERE id = %s',
                           (check_id,))

    def get_diagnostic_check(self, check_id: int) -> Optional[Tuple]:
        """Одна запись проверки; порядок полей — core.diagnostic_log.RECORD_COLUMNS."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f'SELECT {self._diagnostic_select()} '
                f'FROM diagnostic_checks WHERE id = %s', (check_id,))
            return cursor.fetchone()

    def get_diagnostic_checks(self, grp_id: int) -> List[Tuple]:
        """Проверки по ГРП — свежие сверху.

        Порядок полей — core.diagnostic_log.RECORD_COLUMNS. Даты записаны
        текстом, поэтому свежие сверху стоят по ISO-виду (его и пишет форма).
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f'SELECT {self._diagnostic_select()} FROM diagnostic_checks '
                f'WHERE grp_id = %s '
                f'ORDER BY check_date DESC NULLS LAST, id DESC', (grp_id,))
            return cursor.fetchall()