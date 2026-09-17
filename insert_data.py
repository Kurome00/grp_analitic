import sqlite3
from datetime import datetime
import os

def insert_documentary_norms():
    """Добавление документальных норм"""
    conn = sqlite3.connect('grp_database.db')
    cursor = conn.cursor()
    
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
    
    now = datetime.now().strftime('%Y-%m-%d')
    
    for name, max_years, notes in norms:
        cursor.execute('''
            INSERT OR REPLACE INTO documentary_norms (equipment_name, max_life_years, notes, created_date, updated_date)
            VALUES (?, ?, ?, ?, ?)
        ''', (name, max_years, notes, now, now))
    
    conn.commit()
    conn.close()
    print(f"✅ Добавлено {len(norms)} документальных норм!")

def insert_equipment_data():
    """Добавление корректных данных об оборудовании"""
    conn = sqlite3.connect('grp_database.db')
    cursor = conn.cursor()
    
    # Проверяем все ГРП в базе
    cursor.execute("SELECT id, type FROM grp ORDER BY id")
    all_grps = cursor.fetchall()
    
    if not all_grps:
        print("❌ Нет ни одного ГРП в базе данных!")
        print("   Сначала запустите py main.py и создайте ГРП через кнопку 'Добавить ГРП'")
        conn.close()
        return False
    
    print(f"📋 Найдено ГРП в базе:")
    for g in all_grps:
        print(f"   ID={g[0]}, Тип={g[1]}")
    
    # Берем первый ГРП
    grp_id = all_grps[0][0]
    grp_name = all_grps[0][1]
    print(f"\n📌 Добавляем оборудование в ГРП: {grp_name} (ID={grp_id})")
    
    # Проверяем, есть ли уже оборудование
    cursor.execute("SELECT COUNT(*) FROM equipment WHERE grp_id = ?", (grp_id,))
    existing = cursor.fetchone()[0]
    if existing > 0:
        print(f"⚠️ В ГРП уже есть {existing} записей оборудования")
        response = input("   Удалить существующее оборудование и добавить новые данные? (y/n): ")
        if response.lower() == 'y':
            cursor.execute("DELETE FROM equipment WHERE grp_id = ?", (grp_id,))
            print("   Существующее оборудование удалено")
        else:
            print("   Добавляю новые данные к существующим...")
    
    # Данные оборудования
    equipment_data = [
        ('Редукционная арматура (РА)', '2018-05-01', None),
        ('Редукционная арматура (РА)', '2010-06-01', '2018-04-30'),
        ('Редукционная арматура (РА)', '2000-03-01', '2010-05-31'),
        ('Редукционная арматура (РА)', '1985-08-01', '2000-02-29'),
        
        ('Запорная арматура (ЗА1)', '2020-03-15', None),
        ('Запорная арматура (ЗА1)', '2013-02-01', '2020-03-14'),
        ('Запорная арматура (ЗА1)', '2000-05-10', '2013-01-31'),
        ('Запорная арматура (ЗА1)', '1988-08-01', '2000-05-09'),
        
        ('Запорная арматура (ЗА2)', '2019-07-20', None),
        ('Запорная арматура (ЗА2)', '2012-05-01', '2019-07-19'),
        ('Запорная арматура (ЗА2)', '2001-03-10', '2012-04-30'),
        ('Запорная арматура (ЗА2)', '1989-01-15', '2001-03-09'),
        
        ('Запорная арматура (ЗА3)', '2010-06-01', None),
        ('Запорная арматура (ЗА3)', '1998-03-10', '2010-05-31'),
        ('Запорная арматура (ЗА3)', '1986-05-15', '1998-03-09'),
        
        ('Запорная арматура (ЗА4)', '2021-01-10', None),
        ('Запорная арматура (ЗА4)', '2014-08-15', '2021-01-09'),
        ('Запорная арматура (ЗА4)', '2002-11-01', '2014-08-14'),
        ('Запорная арматура (ЗА4)', '1990-09-01', '2002-10-31'),
        
        ('Запорная арматура (ЗА5)', '2022-08-10', None),
        ('Запорная арматура (ЗА5)', '2015-03-01', '2022-08-09'),
        ('Запорная арматура (ЗА5)', '2003-06-15', '2015-02-28'),
        ('Запорная арматура (ЗА5)', '1991-04-10', '2003-06-14'),
        
        ('Запорная арматура (ЗА6)', '2018-09-15', None),
        ('Запорная арматура (ЗА6)', '2009-12-20', '2018-09-14'),
        ('Запорная арматура (ЗА6)', '1997-02-10', '2009-12-19'),
        
        ('Запорная арматура (ЗА7)', '2017-11-01', None),
        ('Запорная арматура (ЗА7)', '2008-04-15', '2017-10-31'),
        ('Запорная арматура (ЗА7)', '1996-01-20', '2008-04-14'),
        
        ('Предохранительная арматура (ПА)', '2019-10-08', None),
        ('Предохранительная арматура (ПА)', '2012-05-15', '2019-10-07'),
        ('Предохранительная арматура (ПА)', '2002-08-01', '2012-05-14'),
        ('Предохранительная арматура (ПА)', '1992-03-10', '2002-07-31'),
        ('Предохранительная арматура (ПА)', '1982-01-15', '1992-03-09'),
        
        ('Отключающая арматура (ОА)', '2020-06-01', None),
        ('Отключающая арматура (ОА)', '2012-10-10', '2020-05-31'),
        ('Отключающая арматура (ОА)', '2001-03-20', '2012-10-09'),
        ('Отключающая арматура (ОА)', '1989-08-05', '2001-03-19'),
        
        ('Фильтр (Ф)', '2021-04-01', None),
        ('Фильтр (Ф)', '2015-09-15', '2021-03-31'),
        ('Фильтр (Ф)', '2008-12-10', '2015-09-14'),
        ('Фильтр (Ф)', '2000-03-01', '2008-12-09'),
        ('Фильтр (Ф)', '1992-06-20', '2000-02-29'),
        ('Фильтр (Ф)', '1984-01-15', '1992-06-19'),
    ]
    
    count = 0
    for name, install_date, removal_date in equipment_data:
        try:
            cursor.execute('''
                INSERT INTO equipment (grp_id, name, install_date, removal_date)
                VALUES (?, ?, ?, ?)
            ''', (grp_id, name, install_date, removal_date))
            count += 1
        except Exception as e:
            print(f"Ошибка при вставке {name}: {e}")
    
    conn.commit()
    conn.close()
    
    current_count = sum(1 for d in equipment_data if d[2] is None)
    removed_count = count - current_count
    
    print(f"\n✅ Добавлено {count} записей оборудования!")
    print(f"   - В эксплуатации: {current_count} шт.")
    print(f"   - Демонтировано: {removed_count} шт.")
    
    return True

def add_technical_coefficients():
    """Добавление данных для технических коэффициентов"""
    conn = sqlite3.connect('grp_database.db')
    cursor = conn.cursor()
    
    # Получаем первый ГРП
    cursor.execute("SELECT id FROM grp ORDER BY id LIMIT 1")
    grp = cursor.fetchone()
    
    if not grp:
        print("❌ Нет ГРП!")
        conn.close()
        return
    
    grp_id = grp[0]
    print(f"\n📌 Добавляем технические коэффициенты для ГРП ID={grp_id}")
    
    # Удаляем старые коэффициенты
    cursor.execute("DELETE FROM technical_coefficients WHERE grp_id = ?", (grp_id,))
    
    # Данные диагностирований
    diagnostics = [
        (0, 2, 30, 1, 60, '2020-06-15'),
        (0, 3, 32, 2, 64, '2021-05-20'),
        (0.1, 4, 35, 3, 70, '2022-08-10'),
        (0, 5, 38, 2, 76, '2023-04-25'),
        (0.1, 6, 40, 4, 80, '2024-09-01'),
        (0, 7, 42, 3, 84, '2025-03-15'),
        (0.1, 8, 44, 5, 88, '2026-01-10'),
    ]
    
    count = 0
    for a, n, u, m, r, date_str in diagnostics:
        b = min(0.1, n / u) if u > 0 else 0
        c = min(0.1, m / r) if r > 0 else 0
        k = 1 - (a + b + c)
        
        cursor.execute('''
            INSERT INTO technical_coefficients 
            (grp_id, coefficient_a, coefficient_b, coefficient_c, coefficient_k,
             n_count, u_count, m_count, r_count, diagnosis_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (grp_id, a, b, c, k, n, u, m, r, date_str))
        count += 1
    
    conn.commit()
    conn.close()
    
    print(f"✅ Добавлено {count} записей технических диагностирований!")
    
    # Показываем добавленные данные
    conn = sqlite3.connect('grp_database.db')
    cursor = conn.cursor()
    cursor.execute("SELECT id, diagnosis_date, coefficient_a, coefficient_k FROM technical_coefficients WHERE grp_id = ? ORDER BY diagnosis_date", (grp_id,))
    rows = cursor.fetchall()
    print("\n📋 Проверка добавленных коэффициентов:")
    for row in rows:
        print(f"   ID={row[0]}, Дата={row[1]}, A={row[2]}, K={row[3]:.4f}")
    conn.close()

if __name__ == "__main__":
    print("="*50)
    print("ЗАГРУЗКА ДАННЫХ В БАЗУ ДАННЫХ ГРП")
    print("="*50)
    
    # Проверяем существование БД
    if not os.path.exists('grp_database.db'):
        print("❌ База данных 'grp_database.db' не найдена!")
        print("   Сначала запустите: py main.py")
        print("   Затем в приложении нажмите 'Добавить ГРП' и создайте ГРП")
        print("   После этого закройте приложение и запустите этот скрипт снова")
        exit(1)
    
    # Проверяем наличие ГРП
    conn = sqlite3.connect('grp_database.db')
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM grp")
    grp_count = cursor.fetchone()[0]
    conn.close()
    
    if grp_count == 0:
        print("❌ В базе данных нет ни одного ГРП!")
        print("   Запустите py main.py, нажмите 'Добавить ГРП' и создайте ГРП")
        exit(1)
    
    print(f"✅ Найдено ГРП: {grp_count} шт.")
    
    # Загружаем данные
    insert_documentary_norms()
    insert_equipment_data()
    add_technical_coefficients()
    
    print("\n" + "="*50)
    print("✅ ВСЕ ДАННЫЕ УСПЕШНО ЗАГРУЖЕНЫ!")
    print("="*50)
    print("\nТеперь запускайте: py main.py")