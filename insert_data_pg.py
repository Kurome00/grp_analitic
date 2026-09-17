import psycopg2
from datetime import datetime
import os

DB_CONFIG = {
    'host': 'localhost',
    'port': '5432',
    'database': 'grp_analyzer',
    'user': 'postgres',
    'password': 'Dzanatyt2003' 
}

def get_connection():
    return psycopg2.connect(**DB_CONFIG)

def create_database():
    """Создание базы данных если её нет"""
    try:
        # Подключаемся к стандартной базе postgres
        conn = psycopg2.connect(
            host=DB_CONFIG['host'],
            port=DB_CONFIG['port'],
            database='postgres',
            user=DB_CONFIG['user'],
            password=DB_CONFIG['password']
        )
        conn.autocommit = True
        cursor = conn.cursor()
        
        # Проверяем существует ли база
        cursor.execute(f"SELECT 1 FROM pg_database WHERE datname = '{DB_CONFIG['database']}'")
        exists = cursor.fetchone()
        
        if not exists:
            cursor.execute(f"CREATE DATABASE {DB_CONFIG['database']}")
            print(f"✅ База данных '{DB_CONFIG['database']}' создана!")
        else:
            print(f"ℹ️ База данных '{DB_CONFIG['database']}' уже существует")
        
        conn.close()
        return True
    except Exception as e:
        print(f"❌ Ошибка создания БД: {e}")
        return False

def insert_test_data():
    """Загрузка тестовых данных"""
    print("="*60)
    print("ЗАГРУЗКА ДАННЫХ В POSTGRESQL")
    print("="*60)
    
    # Сначала создаем БД
    if not create_database():
        return
    
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        # 1. Проверяем и создаем ГРП
        cursor.execute("SELECT COUNT(*) FROM grp")
        grp_count = cursor.fetchone()[0]
        
        if grp_count == 0:
            print("\n📌 Создаю новый ГРП...")
            cursor.execute('''
                INSERT INTO grp (type, lines_count, actual_life, design_life)
                VALUES (%s, %s, %s, %s)
                RETURNING id
            ''', ('ШРП-1 Уличный', 3, 15, 25))
            grp_id = cursor.fetchone()[0]
            print(f"✅ Создан ГРП с ID={grp_id}")
        else:
            cursor.execute("SELECT id FROM grp LIMIT 1")
            grp_id = cursor.fetchone()[0]
            print(f"\n✅ Найден ГРП с ID={grp_id}")
        
        # 2. Добавляем документальные нормы
        print("\n📋 Добавляю документальные нормы...")
        norms = [
            ('Редукционная арматура (РА)', 15, 'Редуктор давления'),
            ('Запорная арматура (ЗА1)', 12, 'Кран шаровой'),
            ('Запорная арматура (ЗА2)', 12, 'Кран шаровой'),
            ('Запорная арматура (ЗА3)', 12, 'Кран шаровой'),
            ('Запорная арматура (ЗА4)', 12, 'Кран шаровой'),
            ('Запорная арматура (ЗА5)', 12, 'Кран шаровой'),
            ('Запорная арматура (ЗА6)', 12, 'Кран шаровой'),
            ('Запорная арматура (ЗА7)', 12, 'Кран шаровой'),
            ('Предохранительная арматура (ПА)', 10, 'Предохранительный клапан'),
            ('Отключающая арматура (ОА)', 12, 'Отключающее устройство'),
            ('Фильтр (Ф)', 8, 'Газовый фильтр'),
        ]
        
        now = datetime.now().date()
        
        for name, max_years, notes in norms:
            cursor.execute('''
                INSERT INTO documentary_norms (equipment_name, max_life_years, notes, created_date, updated_date)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (equipment_name) DO UPDATE SET
                    max_life_years = EXCLUDED.max_life_years,
                    notes = EXCLUDED.notes,
                    updated_date = EXCLUDED.updated_date
            ''', (name, max_years, notes, now, now))
        
        print(f"✅ Добавлено {len(norms)} норм")
        
        # 3. Очищаем старые данные оборудования
        cursor.execute("DELETE FROM equipment WHERE grp_id = %s", (grp_id,))
        print(f"\n🗑 Очищены старые данные оборудования")
        
        # 4. Добавляем оборудование
        print("\n📦 Добавляю оборудование...")
        
        equipment_list = [
            ('Редукционная арматура (РА)', '2018-05-01', None),
            ('Редукционная арматура (РА)', '2010-06-01', '2018-04-30'),
            ('Редукционная арматура (РА)', '2000-03-01', '2010-05-31'),
            ('Запорная арматура (ЗА1)', '2020-03-15', None),
            ('Запорная арматура (ЗА1)', '2013-02-01', '2020-03-14'),
            ('Запорная арматура (ЗА1)', '2000-05-10', '2013-01-31'),
            ('Запорная арматура (ЗА2)', '2019-07-20', None),
            ('Запорная арматура (ЗА2)', '2012-05-01', '2019-07-19'),
            ('Запорная арматура (ЗА3)', '2010-06-01', None),
            ('Запорная арматура (ЗА3)', '1998-03-10', '2010-05-31'),
            ('Запорная арматура (ЗА4)', '2021-01-10', None),
            ('Запорная арматура (ЗА4)', '2014-08-15', '2021-01-09'),
            ('Запорная арматура (ЗА5)', '2022-08-10', None),
            ('Запорная арматура (ЗА5)', '2015-03-01', '2022-08-09'),
            ('Запорная арматура (ЗА6)', '2018-09-15', None),
            ('Запорная арматура (ЗА6)', '2009-12-20', '2018-09-14'),
            ('Запорная арматура (ЗА7)', '2017-11-01', None),
            ('Запорная арматура (ЗА7)', '2008-04-15', '2017-10-31'),
            ('Предохранительная арматура (ПА)', '2019-10-08', None),
            ('Предохранительная арматура (ПА)', '2012-05-15', '2019-10-07'),
            ('Предохранительная арматура (ПА)', '2002-08-01', '2012-05-14'),
            ('Отключающая арматура (ОА)', '2020-06-01', None),
            ('Отключающая арматура (ОА)', '2012-10-10', '2020-05-31'),
            ('Отключающая арматура (ОА)', '2001-03-20', '2012-10-09'),
            ('Фильтр (Ф)', '2021-04-01', None),
            ('Фильтр (Ф)', '2015-09-15', '2021-03-31'),
            ('Фильтр (Ф)', '2008-12-10', '2015-09-14'),
            ('Фильтр (Ф)', '2000-03-01', '2008-12-09'),
        ]
        
        for name, install_date, removal_date in equipment_list:
            cursor.execute('''
                INSERT INTO equipment (grp_id, name, install_date, removal_date)
                VALUES (%s, %s, %s, %s)
            ''', (grp_id, name, install_date, removal_date))
        
        print(f"✅ Добавлено {len(equipment_list)} записей оборудования")
        
        # 5. Добавляем технические коэффициенты
        print("\n🔧 Добавляю технические коэффициенты...")
        
        cursor.execute("DELETE FROM technical_coefficients WHERE grp_id = %s", (grp_id,))
        
        diagnostics = [
            (0, 2, 30, 1, 60, '2020-06-15'),
            (0, 3, 32, 2, 64, '2021-05-20'),
            (0.1, 4, 35, 3, 70, '2022-08-10'),
            (0, 5, 38, 2, 76, '2023-04-25'),
            (0.1, 6, 40, 4, 80, '2024-09-01'),
            (0, 7, 42, 3, 84, '2025-03-15'),
            (0.1, 8, 44, 5, 88, '2026-01-10'),
        ]
        
        for a, n, u, m, r, date_str in diagnostics:
            b = min(0.1, n / u) if u > 0 else 0
            c = min(0.1, m / r) if r > 0 else 0
            k = 1 - (a + b + c)
            
            cursor.execute('''
                INSERT INTO technical_coefficients 
                (grp_id, coefficient_a, coefficient_b, coefficient_c, coefficient_k,
                 n_count, u_count, m_count, r_count, diagnosis_date)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ''', (grp_id, a, b, c, k, n, u, m, r, date_str))
        
        print(f"✅ Добавлено {len(diagnostics)} записей технических коэффициентов")
        
        conn.commit()
        
        # Проверка результата
        print("\n" + "="*60)
        print("ПРОВЕРКА ДАННЫХ")
        print("="*60)
        
        cursor.execute("SELECT COUNT(*) FROM equipment WHERE grp_id = %s", (grp_id,))
        equip_count = cursor.fetchone()[0]
        print(f"📊 Оборудование: {equip_count} шт.")
        
        cursor.execute("SELECT COUNT(*) FROM documentary_norms")
        norms_count = cursor.fetchone()[0]
        print(f"📊 Документальные нормы: {norms_count} шт.")
        
        cursor.execute("SELECT COUNT(*) FROM technical_coefficients WHERE grp_id = %s", (grp_id,))
        tech_count = cursor.fetchone()[0]
        print(f"📊 Технические коэффициенты: {tech_count} шт.")
        
        # Показываем технические коэффициенты
        print("\n📋 Технические коэффициенты:")
        cursor.execute('''
            SELECT id, diagnosis_date, coefficient_a, coefficient_b, coefficient_c, coefficient_k, 
                   n_count, u_count, m_count, r_count 
            FROM technical_coefficients 
            WHERE grp_id = %s 
            ORDER BY diagnosis_date
        ''', (grp_id,))
        rows = cursor.fetchall()
        for row in rows:
            print(f"   ID={row[0]}, Дата={row[1]}, A={row[2]}, B={row[3]:.4f}, C={row[4]:.4f}, K={row[5]:.4f}, r={row[9]}")
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        conn.rollback()
    finally:
        conn.close()
    
    print("\n" + "="*60)
    print("✅ ГОТОВО! Теперь запускайте: py main_pg.py")
    print("="*60)

if __name__ == "__main__":
    insert_test_data()