# -*- coding: utf-8 -*-
"""Подготовка БД: создание базы, таблиц и наполнение нормами по умолчанию.

Запуск:
    python seed.py            # создание таблиц + дефолтные нормы
    python seed.py --demo     # + демо-ГРП и демо-оборудование
"""
import sys

import psycopg2

from config import DB_CONFIG, EQUIPMENT_NORMS

DB_NAME = DB_CONFIG['database']


def connect_admin():
    admin = dict(DB_CONFIG)
    admin["database"] = "postgres"
    return psycopg2.connect(**admin)


def ensure_database():
    conn = connect_admin()
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (DB_NAME,))
        if not cur.fetchone():
            cur.execute(f'CREATE DATABASE "{DB_NAME}"')
            print(f"[+] База '{DB_NAME}' создана")
        else:
            print(f"[=] База '{DB_NAME}' уже существует")
    conn.close()


def ensure_tables():
    from database_pg import DatabasePG
    DatabasePG(DB_CONFIG)
    print("[+] Таблицы готовы")


def seed_norms():
    from database_pg import DatabasePG
    db = DatabasePG(DB_CONFIG)
    existing = {r[1] for r in db.get_all_norms()}
    added = 0
    for name, years in EQUIPMENT_NORMS.items():
        if name not in existing:
            db.add_norm(name, years)
            added += 1
    print(f"[+] Нормы добавлено: {added} / {len(EQUIPMENT_NORMS)}")


def seed_parts():
    from config import DEFAULT_PARTS_NORMS
    from database_pg import DatabasePG
    db = DatabasePG(DB_CONFIG)
    existing = {r[1] for r in db.get_all_parts()}
    added = 0
    for name, years in DEFAULT_PARTS_NORMS.items():
        if name not in existing:
            db.add_part(name, float(years))
            added += 1
    print(f"[+] Запчасти добавлено: {added} / {len(DEFAULT_PARTS_NORMS)}")


def seed_demo():
    from database_pg import DatabasePG
    db = DatabasePG(DB_CONFIG)
    if any("Демо-ГРП" in r[1] for r in db.get_all_grp()):
        print("[=] Демо-ГРП уже есть, пропуск")
        return

    grp_id = db.add_grp("Демо-ГРП-1", 4, 16, 15)
    demo = [
        ("Редукционная арматура (РА)", "2008-01-01", None),
        ("Запорная арматура (ЗА1)", "2010-02-01", None),
        ("Запорная арматура (ЗА2)", "2015-03-01", None),
        ("Предохранительная арматура (ПА)", "2012-04-01", None),
        ("Отключающая арматура (ОА)", "2016-05-01", None),
        ("Фильтр (Ф)", "2013-06-01", None),
        ("Запорная арматура (ЗА3)", "2009-07-01", "2020-08-01"),
    ]
    equip_ids = {}
    for name, install, removal in demo:
        equip_ids[name] = db.add_equipment(grp_id, name, install, removal)

    # Привязка демо-запчастей: срок службы оборудования = мин. по запчастям
    parts = {p[1]: p[0] for p in db.get_all_parts()}

    def link(eq_name, part_name, install=None):
        if part_name in parts and eq_name in equip_ids:
            db.add_equipment_part(equip_ids[eq_name], parts[part_name], install)

    link("Редукционная арматура (РА)", "Седло клапана")                  # с 2008 → срок 10 лет
    link("Редукционная арматура (РА)", "Мембрана регулятора", "2021-03-01")
    link("Фильтр (Ф)", "Фильтрующий элемент", "2024-06-01")              # заменён → срок до 2029
    print(f"[+] Демо-ГРП #{grp_id} создан с {len(demo)} ед.")


def main():
    ensure_database()
    ensure_tables()
    seed_norms()
    seed_parts()
    if "--demo" in sys.argv:
        seed_demo()
    print("[ok] seed завершён")


if __name__ == "__main__":
    main()