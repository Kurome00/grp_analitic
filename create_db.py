import psycopg2

print("🔄 Создание базы данных grp_analyzer...")

try:
    conn = psycopg2.connect(
        host='localhost',
        port='5432',
        database='postgres',
        user='postgres',
        password='Dzanatyt2003'
    )
    conn.autocommit = True
    cursor = conn.cursor()
    
    # Проверяем, существует ли база
    cursor.execute("SELECT 1 FROM pg_database WHERE datname = 'grp_analyzer'")
    exists = cursor.fetchone()
    
    if exists:
        print("ℹ️ База данных 'grp_analyzer' уже существует")
    else:
        cursor.execute("CREATE DATABASE grp_analyzer")
        print("✅ База данных 'grp_analyzer' создана!")
    
    conn.close()
    
except Exception as e:
    print(f"❌ Ошибка: {e}")