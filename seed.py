# -*- coding: utf-8 -*-
"""Подготовка БД: создание базы, таблиц и наполнение запчастями по умолчанию.

Запуск:
    python seed.py                  # создание таблиц + дефолтные запчасти
    python seed.py --demo           # + демонстрационные ГРП (5 сценариев)

Логика демо-сценариев:
    Все ГРП, кроме каталога оборудования, удаляются и создаются заново —
    пять сценариев жизненного цикла (см. EXAMPLES). Оборудование всегда
    получает ВСЕ запчасти модели из каталога, меняются только даты их
    замены. Срок заменяемой детали — 5 лет, самого оборудования — срок
    полной проверки (20 лет) по config.FULL_CHECK_TERM.
"""
import sys
from datetime import date

import psycopg2

from core.config import DB_CONFIG

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
    from db.database_pg import DatabasePG
    DatabasePG(DB_CONFIG)
    print("[+] Таблицы готовы")


def seed_parts():
    """Наполняет справочник заменяемыми деталями (срок 5 лет)."""
    from core.config import DEFAULT_REPLACEABLE_PARTS, part_norm
    from db.database_pg import DatabasePG
    db = DatabasePG(DB_CONFIG)
    existing = {r[1]: r for r in db.get_all_parts()}
    added = 0
    for name in DEFAULT_REPLACEABLE_PARTS:
        row = existing.get(name)
        if row is None:
            db.add_part(name, part_norm(True), is_replaceable=True)
            added += 1
        elif not row[3] and abs(float(row[2]) - part_norm(True)) < 1e-9:
            # Деталь заведена старой версией seed: срок 5 лет, но признак
            # заменяемости не проставлен. Восстанавливаем признак, иначе
            # миграция ниже поднимет её норму до 20 лет.
            db.update_part_replaceable(row[0], True)
    print(f"[+] Запчасти добавлено: {added} / {len(DEFAULT_REPLACEABLE_PARTS)}")


def align_part_norms():
    """Приводит нормы деталей к правилу: заменяемые — 5 лет, остальные — 20."""
    from db.database_pg import DatabasePG
    db = DatabasePG(DB_CONFIG)
    counters = db.align_norms_with_replaceable()
    print(f"[+] Нормы деталей: поднято до 20 лет — {counters['raise_to']}, "
          f"оставлено 5 лет — {counters['lower_to']}, "
          f"задано вручную (не тронуто) — {counters['manual']}, "
          f"без изменений — {counters['ok']}")


# Каталог-справочник (в нём шаблоны моделей со всеми запчастями)
CATALOG_GRP_MARKER = 'каталог'

# Шаг сетки плановых замен заменяемых деталей, лет. Совпадает с их нормой.
PART_RENEW_STEP_YEARS = 5


def grid_renew_date(install: str, step_years: int = PART_RENEW_STEP_YEARS):
    """Последний узел сетки плановых замен, не позже сегодняшнего дня.

    Заменяемые детали обновляются планово по сетке «дата установки
    оборудования + 5·k лет». Благодаря этому 5-летние и 20-летние детали
    истекают в один день: 20 кратно 5, поэтому на 4-м шаге обе группы
    совпадают с датой полной проверки оборудования.

    Если первый узел сетки ещё не наступил, замен не было — None.
    """
    if not install:
        return None
    start = date.fromisoformat(install)
    today = date.today()
    renewed = None
    step = 0
    while True:
        step += 1
        try:
            node = start.replace(year=start.year + step_years * step)
        except ValueError:      # 29 февраля
            node = start.replace(year=start.year + step_years * step, day=28)
        if node > today:
            return renewed
        renewed = node.isoformat()


# Пять демонстрационных ГРП для разных сценариев жизненного цикла.
# Оборудование берёт ВСЕ запчасти модели из каталога.
# Поля единицы оборудования:
#   name          — точное название модели из каталога;
#   install       — дата установки (YYYY-MM-DD);
#   remove        — дата снятия (None — в эксплуатации);
#   parts_renewed — дата, на которую обновлены ВСЕ заменяемые детали
#                   (имитация плановой замены расходников). "grid" — дата
#                   берётся с сетки плановых замен (см. grid_renew_date),
#                   чтобы сроки 5- и 20-летних деталей совпадали; None —
#                   расходники не менялись;
#   fragments     — список подстрок: обновить только подходящие детали.
# Поле journal — записи журнала замен (таблица replacements):
#   (дата, обозначение, тип оборудования, модель, изготовитель,
#    вид работ, причина, ответственный)
EXAMPLES = [
    {
        "type": "Сценарий №1 — ГРП 2006 г.: подходит срок полной проверки (20 лет)",
        "lines_count": 2,
        "actual_life": 20,
        "design_life": 20,
        # Установлен в 2006 — к 2026 году исполняется 20 лет (срок полной
        # проверки). Оборудование исправно, расходники менялись планово по
        # сетке 2006→2011→2016→2021, поэтому 5- и 20-летние детали истекают
        # одновременно — 2026-11-01.
        "equipment": [
            {"name": "Регулятор давления газа комбинированный КРОН-50",
             "install": "2006-11-01", "parts_renewed": "grid"},
            {"name": "Клапан предохранительный запорный ПКН(В)-50А",
             "install": "2006-11-01", "parts_renewed": "grid"},
            {"name": "Клапан предохранительный сбросной ПСК-25",
             "install": "2006-11-01", "parts_renewed": "grid"},
            {"name": "Регулятор пилотный",
             "install": "2006-11-01", "parts_renewed": "grid"},
            {"name": "Механизм настройки ПЗК",
             "install": "2006-11-01", "parts_renewed": "grid"},
        ],
        "journal": [
            ("2011-11-01", "", "Регулятор", "КРОН-50", "АО «Газмаш»",
             "Плановый ремонт", "Замена мембраны и уплотнений регулятора (срок 5 лет)", "Петров П.П."),
            ("2016-11-01", "", "Регулятор", "КРОН-50", "АО «Газмаш»",
             "Плановый ремонт", "Замена клапана регулятора и мембраны (срок 5 лет)", "Петров П.П."),
            ("2021-11-01", "", "Регулятор", "КРОН-50", "АО «Газмаш»",
             "Плановый ремонт", "Замена мембраны, колец, клапана (срок 5 лет)", "Петров П.П."),
        ],
    },
    {
        "type": "Сценарий №2 — ГРП 2012 г.: в 2018 г. оборудование вышло из строя",
        "lines_count": 2,
        "actual_life": 14,
        "design_life": 20,
        # Основное оборудование с 2012 года. РГП-50 отказал в 2018 году
        # и был заменён новым. Остальные единицы продолжают работать.
        # Расходники обновлялись по сетке от даты установки каждой единицы.
        "equipment": [
            {"name": "Регулятор давления газа прямоточный комбинированный РГП-50",
             "install": "2012-04-10", "remove": "2018-08-22", "parts_renewed": None},
            {"name": "Регулятор давления газа прямоточный комбинированный РГП-50",
             "install": "2018-08-22", "parts_renewed": "grid"},
            {"name": "Клапан предохранительный запорный ПКН(В)-100А",
             "install": "2012-04-10", "parts_renewed": "grid"},
            {"name": "Клапан предохранительный сбросной ПСК-50",
             "install": "2012-04-10", "parts_renewed": "grid"},
            {"name": "Регулятор пилотный",
             "install": "2012-04-10", "parts_renewed": "grid"},
            {"name": "Механизм настройки ПЗК",
             "install": "2012-04-10", "parts_renewed": "grid"},
        ],
        "journal": [
            ("2018-08-22", "", "Регулятор", "РГП-50", "АО «Газмаш»",
             "Аварийная замена", "Отказ регулятора: разрыв мембраны, срабатывание ПЗК",
             "Сидоров С.С."),
            ("2023-08-22", "", "Регулятор", "РГП-50", "АО «Газмаш»",
             "Плановый ремонт", "Замена мембраны и уплотнительных колец (срок 5 лет)",
             "Сидоров С.С."),
        ],
    },
    {
        "type": "Сценарий №3 — ГРП 2012 г.: полная замена оборудования каждые 5 лет",
        "lines_count": 2,
        "actual_life": 14,
        "design_life": 20,
        # Оборудование полностью выходило из строя каждые 5 лет:
        # 2012 → 2017 → 2022 (текущий состав установлен в 2022 году).
        # С 2022 года прошло менее 5 лет, поэтому расходники ещё не менялись.
        "equipment": [
            {"name": "Регулятор давления газа комбинированный КРОН-150",
             "install": "2012-02-01", "remove": "2017-03-15", "parts_renewed": None},
            {"name": "Регулятор давления газа комбинированный КРОН-150",
             "install": "2017-03-15", "remove": "2022-05-20", "parts_renewed": None},
            {"name": "Регулятор давления газа комбинированный КРОН-150",
             "install": "2022-05-20", "parts_renewed": "grid"},
            {"name": "Клапан предохранительный запорный ПКН(В)-100А",
             "install": "2012-02-01", "remove": "2017-03-15", "parts_renewed": None},
            {"name": "Клапан предохранительный запорный ПКН(В)-100А",
             "install": "2017-03-15", "remove": "2022-05-20", "parts_renewed": None},
            {"name": "Клапан предохранительный запорный ПКН(В)-100А",
             "install": "2022-05-20", "parts_renewed": "grid"},
            {"name": "Клапан предохранительный сбросной ПСК-50",
             "install": "2012-02-01", "remove": "2017-03-15", "parts_renewed": None},
            {"name": "Клапан предохранительный сбросной ПСК-50",
             "install": "2017-03-15", "remove": "2022-05-20", "parts_renewed": None},
            {"name": "Клапан предохранительный сбросной ПСК-50",
             "install": "2022-05-20", "parts_renewed": "grid"},
            {"name": "Регулятор пилотный",
             "install": "2022-05-20", "parts_renewed": "grid"},
            {"name": "Механизм настройки ПЗК",
             "install": "2022-05-20", "parts_renewed": "grid"},
        ],
        "journal": [
            ("2017-03-15", "", "Регулятор", "КРОН-150", "АО «Газмаш»",
             "Аварийная замена", "Отказ оборудования: разрыв мембраны, потеря герметичности",
             "Кузнецов К.К."),
            ("2022-05-20", "", "Регулятор", "КРОН-150", "АО «Газмаш»",
             "Аварийная замена", "Разрушение клапана регулятора, аварийный сброс",
             "Кузнецов К.К."),
            ("2022-05-20", "", "Клапан", "ПСК-50", "АО «Газмаш»",
             "Аварийная замена", "Отказ предохранительного клапана", "Кузнецов К.К."),
        ],
    },
    {
        "type": "Сценарий №4 — ГРП 2016 г.: оборудование не менялось, ресурс в норме",
        "lines_count": 2,
        "actual_life": 10,
        "design_life": 20,
        # Установлен в 2016, блоки не менялись (возраст ~10 лет из 20),
        # заменяемые детали обновлялись планово каждые 5 лет по сетке
        # 2016 → 2021 → 2026.
        "equipment": [
            {"name": "Регулятор давления газа с предохранительным клапаном РДГПК-50М",
             "install": "2016-09-01", "parts_renewed": "grid"},
            {"name": "Клапан предохранительный запорный ПКН(В)-50А",
             "install": "2016-09-01", "parts_renewed": "grid"},
            {"name": "Клапан предохранительный сбросной ПСК-25",
             "install": "2016-09-01", "parts_renewed": "grid"},
            {"name": "Регулятор пилотный",
             "install": "2016-09-01", "parts_renewed": "grid"},
            {"name": "Механизм настройки ПЗК",
             "install": "2016-09-01", "parts_renewed": "grid"},
        ],
        "journal": [
            ("2021-09-01", "", "Регулятор", "РДГПК-50М", "АО «Газмаш»",
             "Плановый ремонт", "Замена мембраны и уплотнительных колец (срок 5 лет)",
             "Морозов М.М."),
            ("2026-09-01", "", "Регулятор", "РДГПК-50М", "АО «Газмаш»",
             "Плановый ремонт", "Замена мембраны, колец, фильтрующего элемента (срок 5 лет)",
             "Морозов М.М."),
        ],
    },
    {
        "type": "Сценарий №5 — ГРП 2001 г.: срок истёк, замен не проводилось",
        "lines_count": 2,
        "actual_life": 25,
        "design_life": 20,
        # Установлен в 2001 (возраст ~25 лет при сроке 20). Оборудование
        # всё ещё в эксплуатации, замены и ремонты не проводились —
        # наихудший сценарий с превышением срока.
        "equipment": [
            {"name": "Регулятор давления комбинированный РДК-50",
             "install": "2001-03-12", "parts_renewed": None},
            {"name": "Клапан предохранительный запорный ПКН(В)-100А",
             "install": "2001-03-12", "parts_renewed": None},
            {"name": "Клапан предохранительный сбросной ПСК-50",
             "install": "2001-03-12", "parts_renewed": None},
            {"name": "Регулятор пилотный",
             "install": "2001-03-12", "parts_renewed": None},
            {"name": "Механизм настройки ПЗК",
             "install": "2001-03-12", "parts_renewed": None},
        ],
        "journal": [
            ("2009-06-20", "", "Регулятор", "РДК-50", "АО «Газмаш»",
             "Плановый ремонт", "Замена мембраны", "Волков В.В."),
            ("2014-09-11", "", "Клапан", "ПКН(В)-100", "АО «Газмаш»",
             "Плановый ремонт", "Повреждение седла клапана, износ уплотнений", "Волков В.В."),
            ("2019-11-02", "", "Клапан", "ПСК-50", "АО «Газмаш»",
             "Текущий ремонт", "Течь по уплотнению, негерметичность", "Волков В.В."),
            ("2023-12-18", "", "Регулятор", "РДК-50", "АО «Газмаш»",
             "Текущий ремонт", "Износ клапана, деформация мембраны", "Волков В.В."),
        ],
    },
]


def _catalog_templates(db) -> dict:
    """Шаблоны каталога: {нормированное имя модели: [(part_id, part_number), ...]}."""
    catalog_id = None
    for g in db.get_all_grp():
        if CATALOG_GRP_MARKER in g[1].lower():
            catalog_id = g[0]
            break
    if catalog_id is None:
        return {}
    templates = {}
    for eq in db.get_equipment_by_grp(catalog_id):
        full = db.get_equipment_parts_full(eq[0])
        templates[eq[1].strip().lower()] = [(p[1], p[6]) for p in full]
    return templates


def _link_full_parts(db, templates: dict, equipment_id: int, equip_name: str) -> int:
    """Привязка ВСЕХ запчастей модели из каталога к оборудованию.

    Даты запчастей не задаём (install_date = None) — значит срок каждой
    детали отсчитывается от даты установки оборудования. Возвращает
    количество привязанных запчастей (0 — модели нет в каталоге).
    """
    name_l = (equip_name or '').strip().lower()
    tpl = templates.get(name_l)
    if not tpl:
        token = name_l.split()[-1]
        matches = [t for n, t in templates.items() if n.split()[-1] == token]
        if len(matches) == 1:
            tpl = matches[0]
    if not tpl:
        return 0
    for part_id, part_number in tpl:
        db.add_equipment_part(equipment_id, part_id, None, None, part_number)
    return len(tpl)


def _apply_replacements(db, equipment_id: int, renewed_date, fragments=None,
                        only_replaceable: bool = True):
    """Имитация замены деталей: срок отсчитывается от даты замены.

    Обновляет install_date у активных деталей. only_replaceable — трогаем
    только заменяемые (расходные) детали. fragments — список подстрок: если
    задан, обновляются только подходящие детали.
    """
    if not renewed_date:
        return
    for ep in db.get_equipment_parts_full(equipment_id):
        ep_id, _pid, pname, _norm, _p_install, p_removal, _pnumb, is_repl = ep
        if p_removal:
            continue
        if only_replaceable and not is_repl:
            continue
        if fragments and not any(f.lower() in pname.lower() for f in fragments):
            continue
        db.update_equipment_part(ep_id, install_date=renewed_date)


def seed_examples():
    """Пересоздаёт демонстрационные ГРП по сценариям.

    Удаляет все ГРП, кроме каталога оборудования, и создаёт пять сценариев
    заново. Запускается из seed.py --demo.
    """
    from db.database_pg import DatabasePG
    db = DatabasePG(DB_CONFIG)

    # Все ГРП, кроме каталога, удаляются — сценарии пересоздаются с нуля.
    removed = 0
    for g in db.get_all_grp():
        if CATALOG_GRP_MARKER in g[1].lower():
            continue
        db.delete_grp(g[0])
        removed += 1
    if removed:
        print(f"[~] Удалено ГРП: {removed} (каталог сохранён)")

    templates = _catalog_templates(db)
    if not templates:
        print("[!] Каталог оборудования не найден — сначала импортируйте PDF-альбом")
        return

    created = 0
    for ex in EXAMPLES:
        grp_id = db.add_grp(ex["type"], ex["lines_count"],
                             ex["actual_life"], ex["design_life"])
        for item in ex["equipment"]:
            name = item["name"]
            install = item.get("install")
            remove = item.get("remove")
            eq_id = db.add_equipment(grp_id, name, install, remove)
            linked = _link_full_parts(db, templates, eq_id, name)
            renewed = item.get("parts_renewed")
            if renewed == "grid":
                # Дата плановой замены расходников — последний узел сетки
                # «установка + 5·k лет», чтобы сроки 5- и 20-летних деталей
                # истекали в один день.
                renewed = grid_renew_date(install)
            _apply_replacements(db, eq_id, renewed, item.get("fragments"))
            if not linked:
                print(f"    ⚠️ {name} — модели нет в каталоге, запчасти не привязаны")
        for rec in ex.get("journal") or []:
            db.add_replacement(grp_id, *rec)
        created += 1
        print(f"[+] Создан сценарий: «{ex['type']}» (ID={grp_id}, "
              f"единиц: {len(ex['equipment'])}, записей журнала: {len(ex.get('journal') or [])})")
    print(f"[ok] Сценарии готовы: создано ГРП — {created}")


def main():
    ensure_database()
    ensure_tables()
    seed_parts()
    align_part_norms()
    if "--demo" in sys.argv:
        seed_examples()
    print("[ok] seed завершён")


if __name__ == "__main__":
    main()