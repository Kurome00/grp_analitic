import psycopg2
from datetime import datetime, date
import random

# ⚠️ НАСТРОЙТЕ ПАРАМЕТРЫ ПОДКЛЮЧЕНИЯ!
DB_CONFIG = {
    'host': 'localhost',
    'port': '5432',
    'database': 'grp_analyzer',
    'user': 'postgres',
    'password': 'Dzanatyt2003'  # ВАШ ПАРОЛЬ
}

def get_connection():
    return psycopg2.connect(**DB_CONFIG)

def insert_data_for_all_grp():
    """Загрузка тестовых данных для ВСЕХ ГРП"""
    print("="*60)
    print("ЗАГРУЗКА ДАННЫХ ДЛЯ ВСЕХ ГРП")
    print("="*60)
    
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        # Проверяем, есть ли ГРП
        cursor.execute("SELECT id, type FROM grp ORDER BY id")
        grps = cursor.fetchall()
        
        if len(grps) < 3:
            print("❌ В базе меньше 3 ГРП! Сначала добавьте ГРП через приложение.")
            print(f"   Сейчас в базе: {len(grps)} ГРП")
            conn.close()
            return
        
        print(f"\n📌 Найдено ГРП: {len(grps)}")
        
        # ============================================
        # 1. ДОБАВЛЯЕМ ДОКУМЕНТАЛЬНЫЕ НОРМЫ (если нет)
        # ============================================
        print("\n📋 Проверка документальных норм...")
        cursor.execute("SELECT COUNT(*) FROM documentary_norms")
        if cursor.fetchone()[0] == 0:
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
                ('Регулятор давления', 10, 'РДГ'),
                ('Фильтр газовый', 8, 'Сетчатый фильтр'),
                ('Предохранительный клапан', 12, 'ПКН'),
                ('Запорная арматура', 15, 'Краны шаровые'),
                ('Манометр', 5, 'Контрольно-измерительный'),
                ('Импульсная трубка', 8, 'Медная трубка'),
            ]
            now = datetime.now().date()
            for name, max_years, notes in norms:
                cursor.execute('''
                    INSERT INTO documentary_norms (equipment_name, max_life_years, notes, created_date, updated_date)
                    VALUES (%s, %s, %s, %s, %s)
                ''', (name, max_years, notes, now, now))
            print(f"✅ Добавлено {len(norms)} норм")
        else:
            print("✅ Нормы уже есть")
        
        # ============================================
        # 2. ОЧИЩАЕМ СТАРОЕ ОБОРУДОВАНИЕ
        # ============================================
        for grp in grps:
            grp_id = grp[0]
            grp_name = grp[1]
            cursor.execute("DELETE FROM equipment WHERE grp_id = %s", (grp_id,))
            cursor.execute("DELETE FROM technical_coefficients WHERE grp_id = %s", (grp_id,))
            print(f"🗑 Очищены данные для ГРП: {grp_name} (ID={grp_id})")
        
        # ============================================
        # 3. ДОБАВЛЯЕМ ОБОРУДОВАНИЕ ДЛЯ КАЖДОГО ГРП
        # ============================================
        
        # Оборудование для ГРП #1 (полный набор)
        equipment_grp1 = [
            ('Редукционная арматура (РА)', '2018-05-01', None),
            ('Редукционная арматура (РА)', '2010-06-01', '2018-04-30'),
            ('Редукционная арматура (РА)', '2000-03-01', '2010-05-31'),
            ('Запорная арматура (ЗА1)', '2020-03-15', None),
            ('Запорная арматура (ЗА1)', '2013-02-01', '2020-03-14'),
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
            ('Отключающая арматура (ОА)', '2020-06-01', None),
            ('Отключающая арматура (ОА)', '2012-10-10', '2020-05-31'),
            ('Фильтр (Ф)', '2021-04-01', None),
            ('Фильтр (Ф)', '2015-09-15', '2021-03-31'),
            ('Фильтр (Ф)', '2008-12-10', '2015-09-14'),
            ('Фильтр (Ф)', '2000-03-01', '2008-12-09'),
        ]
        
        # Оборудование для ГРП #2 (средний набор)
        equipment_grp2 = [
            ('Редукционная арматура (РА)', '2019-06-01', None),
            ('Редукционная арматура (РА)', '2011-05-01', '2019-05-31'),
            ('Запорная арматура (ЗА1)', '2020-08-15', None),
            ('Запорная арматура (ЗА1)', '2014-03-01', '2020-08-14'),
            ('Запорная арматура (ЗА2)', '2021-02-20', None),
            ('Запорная арматура (ЗА2)', '2015-07-01', '2021-02-19'),
            ('Предохранительная арматура (ПА)', '2020-11-08', None),
            ('Предохранительная арматура (ПА)', '2013-09-15', '2020-11-07'),
            ('Отключающая арматура (ОА)', '2021-03-01', None),
            ('Отключающая арматура (ОА)', '2013-11-10', '2021-02-28'),
            ('Фильтр (Ф)', '2022-01-15', None),
            ('Фильтр (Ф)', '2016-06-20', '2022-01-14'),
            ('Регулятор давления', '2019-06-01', None),
            ('Фильтр газовый', '2019-06-01', None),
            ('Предохранительный клапан', '2019-06-01', None),
            ('Манометр', '2020-06-01', None),
            ('Импульсная трубка', '2019-06-01', None),
        ]
        
        # Оборудование для ГРП #3 (минимальный набор)
        equipment_grp3 = [
            ('Редукционная арматура (РА)', '2020-01-01', None),
            ('Запорная арматура (ЗА1)', '2020-01-01', None),
            ('Запорная арматура (ЗА2)', '2020-01-01', None),
            ('Предохранительная арматура (ПА)', '2020-01-01', None),
            ('Отключающая арматура (ОА)', '2020-01-01', None),
            ('Фильтр (Ф)', '2020-01-01', None),
            ('Регулятор давления', '2020-01-01', None),
            ('Фильтр газовый', '2020-01-01', None),
            ('Предохранительный клапан', '2020-01-01', None),
            ('Манометр', '2020-01-01', None),
        ]
        
        # Добавляем оборудование для ГРП #1
        grp_id_1 = grps[0][0]
        print(f"\n📦 Добавляю оборудование для ГРП: {grps[0][1]} (ID={grp_id_1})")
        count = 0
        for name, install_date, removal_date in equipment_grp1:
            cursor.execute('''
                INSERT INTO equipment (grp_id, name, install_date, removal_date)
                VALUES (%s, %s, %s, %s)
            ''', (grp_id_1, name, install_date, removal_date))
            count += 1
        print(f"   ✅ Добавлено {count} записей")
        
        # Добавляем оборудование для ГРП #2
        grp_id_2 = grps[1][0]
        print(f"\n📦 Добавляю оборудование для ГРП: {grps[1][1]} (ID={grp_id_2})")
        count = 0
        for name, install_date, removal_date in equipment_grp2:
            cursor.execute('''
                INSERT INTO equipment (grp_id, name, install_date, removal_date)
                VALUES (%s, %s, %s, %s)
            ''', (grp_id_2, name, install_date, removal_date))
            count += 1
        print(f"   ✅ Добавлено {count} записей")
        
        # Добавляем оборудование для ГРП #3
        grp_id_3 = grps[2][0]
        print(f"\n📦 Добавляю оборудование для ГРП: {grps[2][1]} (ID={grp_id_3})")
        count = 0
        for name, install_date, removal_date in equipment_grp3:
            cursor.execute('''
                INSERT INTO equipment (grp_id, name, install_date, removal_date)
                VALUES (%s, %s, %s, %s)
            ''', (grp_id_3, name, install_date, removal_date))
            count += 1
        print(f"   ✅ Добавлено {count} записей")
        
        # ============================================
        # 4. ДОБАВЛЯЕМ ТЕХНИЧЕСКИЕ КОЭФФИЦИЕНТЫ ДЛЯ КАЖДОГО ГРП
        # ============================================
        print("\n🔧 Добавляю технические коэффициенты...")
        
        diagnostics = [
            (0, 2, 30, 1, 60, '2020-06-15'),
            (0, 3, 32, 2, 64, '2021-05-20'),
            (0.1, 4, 35, 3, 70, '2022-08-10'),
            (0, 5, 38, 2, 76, '2023-04-25'),
            (0.1, 6, 40, 4, 80, '2024-09-01'),
            (0, 7, 42, 3, 84, '2025-03-15'),
            (0.1, 8, 44, 5, 88, '2026-01-10'),
        ]
        
        # Для ГРП #1 - полная история
        for a, n, u, m, r, date_str in diagnostics:
            b = min(0.1, n / u) if u > 0 else 0
            c = min(0.1, m / r) if r > 0 else 0
            k = 1 - (a + b + c)
            cursor.execute('''
                INSERT INTO technical_coefficients 
                (grp_id, coefficient_a, coefficient_b, coefficient_c, coefficient_k,
                 n_count, u_count, m_count, r_count, diagnosis_date)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ''', (grp_id_1, a, b, c, k, n, u, m, r, date_str))
        print(f"   ✅ ГРП #{grp_id_1}: добавлено {len(diagnostics)} записей")
        
        # Для ГРП #2 - средняя история
        diagnostics_grp2 = [
            (0, 1, 15, 0, 30, '2021-06-15'),
            (0, 2, 16, 1, 32, '2022-05-20'),
            (0, 3, 17, 1, 34, '2023-08-10'),
            (0.1, 3, 18, 2, 36, '2024-04-25'),
            (0, 4, 19, 2, 38, '2025-09-01'),
        ]
        for a, n, u, m, r, date_str in diagnostics_grp2:
            b = min(0.1, n / u) if u > 0 else 0
            c = min(0.1, m / r) if r > 0 else 0
            k = 1 - (a + b + c)
            cursor.execute('''
                INSERT INTO technical_coefficients 
                (grp_id, coefficient_a, coefficient_b, coefficient_c, coefficient_k,
                 n_count, u_count, m_count, r_count, diagnosis_date)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ''', (grp_id_2, a, b, c, k, n, u, m, r, date_str))
        print(f"   ✅ ГРП #{grp_id_2}: добавлено {len(diagnostics_grp2)} записей")
        
        # Для ГРП #3 - короткая история
        diagnostics_grp3 = [
            (0, 0, 10, 0, 20, '2022-06-15'),
            (0, 1, 10, 0, 20, '2023-05-20'),
            (0.1, 1, 10, 1, 20, '2024-08-10'),
        ]
        for a, n, u, m, r, date_str in diagnostics_grp3:
            b = min(0.1, n / u) if u > 0 else 0
            c = min(0.1, m / r) if r > 0 else 0
            k = 1 - (a + b + c)
            cursor.execute('''
                INSERT INTO technical_coefficients 
                (grp_id, coefficient_a, coefficient_b, coefficient_c, coefficient_k,
                 n_count, u_count, m_count, r_count, diagnosis_date)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ''', (grp_id_3, a, b, c, k, n, u, m, r, date_str))
        print(f"   ✅ ГРП #{grp_id_3}: добавлено {len(diagnostics_grp3)} записей")
        
        # ============================================
        # 5. ПРОВЕРКА ДАННЫХ
        # ============================================
        print("\n" + "="*60)
        print("ПРОВЕРКА ДАННЫХ")
        print("="*60)
        
        cursor.execute("SELECT COUNT(*) FROM grp")
        grp_count = cursor.fetchone()[0]
        print(f"📊 ГРП: {grp_count} шт.")
        
        cursor.execute("SELECT COUNT(*) FROM equipment")
        equip_count = cursor.fetchone()[0]
        print(f"📊 Оборудование: {equip_count} шт.")
        
        cursor.execute("SELECT COUNT(*) FROM documentary_norms")
        norms_count = cursor.fetchone()[0]
        print(f"📊 Документальные нормы: {norms_count} шт.")
        
        cursor.execute("SELECT COUNT(*) FROM technical_coefficients")
        tech_count = cursor.fetchone()[0]
        print(f"📊 Технические коэффициенты: {tech_count} шт.")
        
        # Статистика по каждому ГРП
        print("\n📋 Статистика по ГРП:")
        for grp in grps:
            grp_id = grp[0]
            grp_name = grp[1]
            cursor.execute("SELECT COUNT(*) FROM equipment WHERE grp_id = %s", (grp_id,))
            equip_cnt = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM technical_coefficients WHERE grp_id = %s", (grp_id,))
            tech_cnt = cursor.fetchone()[0]
            print(f"   • {grp_name} (ID={grp_id}): оборудование={equip_cnt} шт., коэффицентов={tech_cnt} шт.")
        
        conn.commit()
        
    except Exception as e:
        print(f"❌ ОШИБКА: {e}")
        conn.rollback()
    finally:
        conn.close()
    
    print("\n" + "="*60)
    print("✅ ДАННЫЕ УСПЕШНО ЗАГРУЖЕНЫ!")
    print("="*60)
    print("\nТеперь запускайте приложение:")
    print("   py main_pg.py")

if __name__ == "__main__":
    insert_data_for_all_grp()