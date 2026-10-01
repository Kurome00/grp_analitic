# -*- coding: utf-8 -*-
"""Подготовка БД: создание базы, таблиц и наполнение запчастями по умолчанию.

Запуск:
    python seed.py                       # создание таблиц + дефолтные запчасти
    python seed.py --demo                # + 3 демонстрационных ГРП (создаются
                                        #   один раз, повторно НЕ пересоздаются)
    python seed.py --demo --reset-demo   # пересоздать демо-ГРП заново

Логика демо-сценариев:
    Три сценария замены запчастей (см. EXAMPLES):
      №1 — ГРП 2008 г., плановые замены всех деталей раз в 5 лет;
      №2 — ГРП 2012 г., по 2-3 разные детали раз в полгода;
      №3 — ГРП 2008 г., 2-3 детали планово раз в 5 лет, одна — каждые полгода.
    Оборудование получает ВСЕ заменяемые запчасти модели из каталога; сценарии
    различаются только датами замен. Срок заменяемой детали — 5 лет
    (config.REPLACEABLE_NORM_YEARS), срок полной проверки оборудования — 20 лет
    (config.FULL_CHECK_TERM).
    Каталог оборудования при пересоздании демо-данных не удаляется.
"""
import os
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
CATALOG_GRP_NAME = 'Каталог оборудования'

# Префикс типа ГРП у демо-сценариев. По нему seed находит свои сценарии и
# отличает их от реальных ГРП, заведённых пользователем.
DEMO_PREFIX = 'Сценарий №'

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


# Демонстрационные ГРП: три сценария замены запчастей.
# Сценарии НЕ пересоздаются при каждом запуске — они создаются один раз, а
# повторный запуск только проверяет, что они на месте (см. seed_examples).
# Пересоздать принудительно: seed.py --demo --reset-demo.
#
# Оборудование берёт ВСЕ заменяемые запчасти модели из каталога. Различаются
# сценарии только датами замены запчастей.
#
# Схемы замены (режим, поле «schedule» единицы оборудования):
#   "grid5"     — все заменяемые детали обновляются планово по сетке
#                 «установка + 5·k лет» (для оборудования 2008 г.);
#   "rotate"    — раз в полгода меняются 2-3 РАЗНЫЕ детали по кругу
#                 (для оборудования 2012 г.);
#   "fast_one"  — 2-3 детали обновляются планово раз в 5 лет, а одна
#                 «расходная» деталь меняется каждые полгода
#                 (для оборудования 2008 г.).
#
# Поля единицы оборудования:
#   name     — точное название модели из каталога;
#   install  — дата установки (YYYY-MM-DD);
#   schedule — схема замены запчастей (см. выше);
#   fast     — подстрока для выбора «быстрой» детали в схеме fast_one
#              (необязательно, подбирается автоматически).
#
# Поле journal — записи журнала замен (таблица replacements):
#   (дата, обозначение, тип оборудования, модель, изготовитель,
#    вид работ, причина, ответственный)
#
# Модели обязаны совпадать с названиями из каталога оборудования, иначе
# запчасти не привяжутся (seed сообщит об этом построчно).

EXAMPLES = [
    {
        "type": "Сценарий №1 — ГРП 2008 г.: плановые замены запчастей каждые 5 лет",
        "lines_count": 2,
        "design_life": 20,
        "install": "2008-04-01",
        "equipment": [
            {"name": "Регулятор давления газа с предохранительным клапаном РДГПК-100",
             "schedule": "grid5"},
            {"name": "Клапан предохранительный запорный ПКН(В)-100А",
             "schedule": "grid5"},
            {"name": "Клапан предохранительный сбросной ПСК-50",
             "schedule": "grid5"},
            {"name": "Регулятор пилотный", "schedule": "grid5"},
            {"name": "Механизм настройки ПЗК", "schedule": "grid5"},
        ],
        "journal": [
            ("2013-04-05", "", "Регулятор", "РДГПК-100", "АО «Газмаш»",
             "Плановый ремонт", "Замена мембраны, пружины, седла, колец (срок 5 лет)",
             "Волков В.В."),
            ("2018-04-07", "", "Регулятор", "РДГПК-100", "АО «Газмаш»",
             "Плановый ремонт", "Замена мембраны, пружины, седла, колец (срок 5 лет)",
             "Волков В.В."),
            ("2023-04-06", "", "Регулятор", "РДГПК-100", "АО «Газмаш»",
             "Плановый ремонт", "Замена мембраны, пружины, седла, колец (срок 5 лет)",
             "Волков В.В."),
            ("2023-04-06", "", "Клапан", "ПКН(В)-100А", "АО «Газмаш»",
             "Плановый ремонт", "Замена пружины, втулки, колец", "Морозов М.М."),
            ("2023-04-06", "", "Клапан", "ПСК-50", "АО «Газмаш»",
             "Плановый ремонт", "Замена клапана, винта, колец", "Морозов М.М."),
        ],
    },
    {
        "type": "Сценарий №2 — ГРП 2012 г.: по 2-3 разные запчасти раз в полгода",
        "lines_count": 2,
        "design_life": 20,
        "install": "2012-03-15",
        "equipment": [
            {"name": "Регулятор давления газа прямоточный комбинированный РГП-50",
             "schedule": "rotate"},
            {"name": "Клапан предохранительный запорный ПКН(В)-100А",
             "schedule": "rotate"},
            {"name": "Клапан предохранительный сбросной ПСК-50",
             "schedule": "rotate"},
            {"name": "Регулятор пилотный", "schedule": "rotate"},
            {"name": "Механизм настройки ПЗК", "schedule": "rotate"},
        ],
        "journal": [
            ("2013-09-16", "", "Регулятор", "РГП-50", "АО «Газмаш»",
             "Текущий ремонт", "Замена 3 деталей: мембрана, седло, прокладка",
             "Волков В.В."),
            ("2014-03-14", "", "Регулятор", "РГП-50", "АО «Газмаш»",
             "Текущий ремонт", "Замена 3 деталей: втулка, тарелка, кольцо",
             "Волков В.В."),
            ("2015-09-15", "", "Регулятор", "РГП-50", "АО «Газмаш»",
             "Текущий ремонт", "Замена 2 деталей: шток, гайка", "Волков В.В."),
            ("2016-03-16", "", "Клапан", "ПКН(В)-100А", "АО «Газмаш»",
             "Текущий ремонт", "Замена 3 деталей: пружина, втулка, кольцо",
             "Морозов М.М."),
            ("2017-09-15", "", "Клапан", "ПСК-50", "АО «Газмаш»",
             "Текущий ремонт", "Замена 2 деталей: клапан, винт", "Морозов М.М."),
        ],
    },
    {
        "type": "Сценарий №3 — ГРП 2008 г.: 2-3 запчасти планово, одна — каждые полгода",
        "lines_count": 2,
        "design_life": 20,
        "install": "2008-05-10",
        "equipment": [
            {"name": "Регулятор давления газа комбинированный КРОН-150",
             "schedule": "fast_one", "fast": "Мембрана"},
            {"name": "Клапан предохранительный запорный ПКН(В)-50А",
             "schedule": "fast_one", "fast": "Пружина"},
            {"name": "Клапан предохранительный сбросной ПСК-25",
             "schedule": "fast_one", "fast": "Мембрана"},
            {"name": "Регулятор пилотный", "schedule": "fast_one", "fast": "Мембрана"},
            {"name": "Регулятор давления газа РДС-32", "schedule": "fast_one"},
        ],
        "journal": [
            ("2013-05-12", "", "Регулятор", "КРОН-150", "ООО «Газпроммаш»",
             "Плановый ремонт", "Замена 3 деталей: седло, пружина, прокладка",
             "Волков В.В."),
            ("2018-05-14", "", "Регулятор", "КРОН-150", "ООО «Газпроммаш»",
             "Плановый ремонт", "Замена 3 деталей: седло, пружина, прокладка",
             "Волков В.В."),
            ("2023-05-10", "", "Регулятор", "КРОН-150", "ООО «Газпроммаш»",
             "Плановый ремонт", "Замена 3 деталей: седло, пружина, прокладка",
             "Волков В.В."),
            ("2026-03-12", "", "Регулятор", "КРОН-150", "ООО «Газпроммаш»",
             "Текущий ремонт", "Замена мембраны — расходной детали, срок менее года",
             "Волков В.В."),
        ],
    },
]


def _add_months(start: date, months: int) -> date:
    """Дата через N месяцев. 29 февраля схлопывается на 28-е."""
    total = start.month - 1 + months
    year = start.year + total // 12
    month = total % 12 + 1
    day = start.day
    while True:
        try:
            return date(year, month, day)
        except ValueError:
            day -= 1


def half_year_nodes(install: str, today=None):
    """Узлы сетки «раз в полгода» от даты установки до текущего дня.

    Используется в сценариях, где детали меняются чаще, чем раз в 5 лет:
    срок службы заменяемой детали 5 лет, а полгода — типичный межремонтный
    интервал по конкретной детали (мембрана, пружина, прокладка).
    """
    if not install:
        return []
    start = date.fromisoformat(install)
    today = today or date.today()
    nodes, step = [], 1
    while True:
        node = _add_months(start, step * 6)
        if node > today:
            return nodes
        nodes.append(node.isoformat())
        step += 1


def _active_replaceable_parts(db, equipment_id: int):
    """Активные заменяемые детали единицы: [(equipment_part_id, название), ...]."""
    rows = []
    for ep in db.get_equipment_parts_full(equipment_id):
        ep_id, _pid, pname, _norm, _install, removal, _number, is_repl = ep
        if removal or not is_repl:
            continue
        rows.append((ep_id, pname))
    return rows


def _schedule_grid5(db, equipment_id: int, install: str) -> int:
    """Схема grid5: все заменяемые детали обновлены на последнем узле
    пятилетней сетки плановых замен."""
    renewed = grid_renew_date(install)
    if not renewed:
        return 0
    parts = _active_replaceable_parts(db, equipment_id)
    for ep_id, _name in parts:
        db.update_equipment_part(ep_id, install_date=renewed)
    return len(parts)


def _schedule_rotate(db, equipment_id: int, install: str, per_node: int = 3) -> int:
    """Схема rotate: каждый узел полугодовой сетки меняет per_node РАЗНЫХ деталей.

    Детали берутся по кругу, поэтому в один узел попадают разные детали, а
    каждая деталь в итоге получает дату последней своей замены. Именно эта
    дата определяет остаточный срок: чем свежее замена, тем дольше живёт деталь.
    """
    nodes = half_year_nodes(install)
    parts = _active_replaceable_parts(db, equipment_id)
    if not nodes or not parts:
        return 0
    for i, node in enumerate(nodes):
        for k in range(per_node):
            ep_id, _name = parts[(i * per_node + k) % len(parts)]
            db.update_equipment_part(ep_id, install_date=node)
    return len(parts)


# Приоритет выбора «быстрой» детали в схеме fast_one: изношенные расходники,
# которые в реальности меняют чаще всего.
FAST_PART_PREFERENCES = ('мембран', 'пружин', 'седл', 'прокладк', 'фильтр',
                         'клапан', 'втулк', 'тарелк')


def _schedule_fast_one(db, equipment_id: int, install: str, fast: str = None,
                       per_cycle: int = 3) -> int:
    """Схема fast_one: 2-3 детали обновляются планово раз в 5 лет,
    а одна выбранная деталь меняется каждые полгода."""
    parts = _active_replaceable_parts(db, equipment_id)
    if not parts:
        return 0

    needles = [fast.lower()] if fast else list(FAST_PART_PREFERENCES)
    fast_index = None
    for needle in needles:
        for index, (_ep_id, name) in enumerate(parts):
            if needle and needle.lower() in name.lower():
                fast_index = index
                break
        if fast_index is not None:
            break
    if fast_index is None:
        fast_index = 0

    grid_date = grid_renew_date(install)
    nodes = half_year_nodes(install)

    # Плановые детали: следующие per_cycle после «быстрой».
    for offset in range(1, per_cycle + 1):
        index = (fast_index + offset) % len(parts)
        if index == fast_index or not grid_date:
            continue
        db.update_equipment_part(parts[index][0], install_date=grid_date)

    if nodes:
        db.update_equipment_part(parts[fast_index][0], install_date=nodes[-1])
    return len(parts)


SCHEDULES = {
    'grid5': _schedule_grid5,
    'rotate': _schedule_rotate,
    'fast_one': _schedule_fast_one,
}


def apply_schedule(db, equipment_id: int, install: str, schedule: str,
                   fast: str = None) -> int:
    """Применить схему замены запчастей к единице оборудования."""
    handler = SCHEDULES.get(schedule or 'grid5', _schedule_grid5)
    if handler is _schedule_fast_one:
        return handler(db, equipment_id, install, fast)
    return handler(db, equipment_id, install)


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


def ensure_catalog(db, from_pdf: bool = True):
    """Гарантирует наличие каталога оборудования.

    На чистой машине после git clone база пуста: без каталога нечего
    привязывать к сценариям, и seed.py --demo молча создаёт ноль ГРП.
    Поэтому при пустом каталоге альбом из docs/ импортируется автоматически
    (парсинг 70-МБ PDF занимает несколько секунд).
    """
    templates = _catalog_templates(db)
    if templates or not from_pdf:
        return templates

    from core.config import PROJECT_ROOT
    pdf = os.path.join(PROJECT_ROOT, "docs", "Альбом запчастей по газу.pdf")
    if not os.path.isfile(pdf):
        print("[!] Каталог пуст, и нет docs/Альбом запчастей по газу.pdf —")
        print("    импортируйте альбом вручную: меню «Справочники» →")
        print("    «📂 Импорт из PDF-альбома»")
        return templates

    print("[*] Каталог оборудования пуст — импортирую альбом из docs/ …")
    from integration import pdf_parts_import
    units = pdf_parts_import.scan_pdf(pdf)
    if not units:
        print("[!] Не удалось прочитать альбом:", pdf)
        return templates
    pdf_parts_import.import_to_db(db, units, link_to_equipment=False)
    pdf_parts_import.create_catalog_equipment(db, units, CATALOG_GRP_NAME)
    pdf_parts_import.import_to_db(db, units, link_to_equipment=True)
    templates = _catalog_templates(db)
    print(f"[+] Каталог создан: единиц оборудования {len(units)}, "
          f"моделей с запчастями {len(templates)}")
    return templates


def _actual_life(install: str, today=None) -> float:
    """Фактический срок службы: от установки до сегодняшнего дня, лет."""
    if not install:
        return 0.0
    start = date.fromisoformat(install)
    today = today or date.today()
    return round((today - start).days / 365.25, 2)


def _is_demo_scenario(grp_type: str) -> bool:
    """Демо-сценарий — это ГРП, чей тип начинается с префикса сценариев.

    Проверка по названию нужна, чтобы удаление устаревших демо-данных НЕ задело
    реальные ГРП, заведённые пользователем через интерфейс: они сюда не попадут.
    """
    return grp_type.strip().lower().startswith(DEMO_PREFIX.lower())


def _find_demo_groups(db):
    """Существующие демо-сценарии: {полное название типа: grp_id}."""
    found = {}
    for grp in db.get_all_grp():
        if CATALOG_GRP_MARKER in grp[1].lower():
            continue
        if not _is_demo_scenario(grp[1]):
            continue
        found[grp[1].strip()] = grp[0]
    return found


def _drop_stale_groups(db, keep_types):
    """Удаляет устаревшие демо-сценарии — те, которых больше нет в EXAMPLES.

    Чистит за собой старые версии демо-данных: если сценарий переименован или
    удалён из EXAMPLES, его записи не копятся в базе. Каталог оборудования не
    трогаем, реальные ГРП пользователя — тоже.
    """
    dropped = 0
    for grp in db.get_all_grp():
        name = grp[1].strip()
        if CATALOG_GRP_MARKER in name.lower():
            continue
        if name in keep_types or not _is_demo_scenario(name):
            continue
        db.delete_grp(grp[0])
        dropped += 1
    if dropped:
        print(f"[~] Удалено устаревших демо-сценариев: {dropped}")
    return dropped


def seed_examples(reset: bool = False):
    """Готовит демонстрационные ГРП.

    Сценарии создаются ОДИН РАЗ и больше не пересоздаются: повторный запуск
    находит существующий ГРП по названию и ничего в нём не меняет — в том
    числе даты замен запчастей, которые пользователь мог отредактировать вручную.

    Удаляются только устаревшие демо-сценарии (их больше нет в EXAMPLES), а при
    reset=True — все демо-сценарии. Каталог оборудования и реальные ГРП
    пользователя не затрагиваются ни при каких условиях.

    Параметры:
        reset — пересоздать демо-сценарии заново, даже если они уже есть.
    """
    from db.database_pg import DatabasePG
    db = DatabasePG(DB_CONFIG)

    wanted = {ex["type"]: ex for ex in EXAMPLES}
    existing = _find_demo_groups(db)

    if reset:
        for grp_type, grp_id in existing.items():
            db.delete_grp(grp_id)
        print(f"[~] --reset-demo: удалено демо-сценариев — {len(existing)} "
              f"(каталог сохранён)")
        existing = {}
    else:
        # Убираем только те демо-сценарии, которых больше нет в списке.
        _drop_stale_groups(db, set(wanted))

    templates = ensure_catalog(db)
    if not templates:
        print("[!] Демо-сценарии не созданы: нет каталога оборудования")
        return

    created = kept = 0
    for ex in EXAMPLES:
        grp_type = ex["type"]
        install = ex.get("install")
        existing_id = existing.get(grp_type)

        if existing_id is not None:
            # Сценарий уже создан — не трогаем его содержимое.
            units = len(db.get_equipment_by_grp(existing_id))
            if units:
                print(f"[=] Сценарий уже есть, пропуск: «{grp_type}» "
                      f"(ID={existing_id}, единиц: {units})")
                kept += 1
                continue
            # ГРП есть, а оборудования нет — донаполняем (самопочинка).
            print(f"[~] Сценарий найден, но без оборудования — наполняю: «{grp_type}»")
            db.delete_grp(existing_id)

        grp_id = db.add_grp(grp_type, ex["lines_count"],
                            _actual_life(install), ex["design_life"])
        for item in ex["equipment"]:
            name = item["name"]
            eq_id = db.add_equipment(grp_id, name, install, None)
            linked = _link_full_parts(db, templates, eq_id, name)
            apply_schedule(db, eq_id, install, item.get("schedule"),
                           item.get("fast"))
            if not linked:
                print(f"    ⚠️ {name} — модели нет в каталоге, запчасти не привязаны")
        for rec in ex.get("journal") or []:
            db.add_replacement(grp_id, *rec)
        created += 1
        print(f"[+] Создан сценарий: «{grp_type}» (ID={grp_id}, "
              f"единиц: {len(ex['equipment'])}, "
              f"записей журнала: {len(ex.get('journal') or [])})")

    if created or kept:
        print(f"[ok] Сценарии: создано — {created}, уже было — {kept}")


def main():
    ensure_database()
    ensure_tables()
    seed_parts()
    align_part_norms()
    if "--demo" in sys.argv:
        seed_examples(reset="--reset-demo" in sys.argv)
    print("[ok] seed завершён")


if __name__ == "__main__":
    main()