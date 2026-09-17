import psycopg2
import sys

print("🔄 Проверка подключения к PostgreSQL...")
print(f"Параметры: localhost:5432, пользователь: postgres")

try:
    conn = psycopg2.connect(
        host='localhost',
        port='5432',
        database='postgres',
        user='postgres',
        password='Dzanatyt2003'
    )
    print("✅ ПОДКЛЮЧЕНИЕ УСПЕШНО!")
    conn.close()
except Exception as e:
    print(f"❌ ОШИБКА ПОДКЛЮЧЕНИЯ:")
    print(f"   {e}")
    sys.exit(1)