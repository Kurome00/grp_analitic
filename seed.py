# -*- coding: utf-8 -*-
"""Подготовка БД: создание базы, таблиц и наполнение запчастями по умолчанию.

Запуск:
    python seed.py                       # создание таблиц + дефолтные запчасти
    python seed.py --demo                # + 4 демонстрационных ГРП (создаются
                                        #   один раз, повторно НЕ пересоздаются)
    python seed.py --demo --reset-demo   # пересоздать демо-ГРП заново

Логика демо-сценариев:
    Четыре сценария замены запчастей (см. EXAMPLES) — от просроченного ГРП
    к свежему:
      №1 — ГРП 2008 г., часть запчастей с истёкшим сроком;
      №2 — ГРП 2012 г., ресурс менее года;
      №3 — ГРП 2016 г., ресурс в норме;
      №4 — ГРП 2021 г., замены недавние.
    Оборудование получает ВСЕ заменяемые запчасти модели из каталога. Сами
    единицы стоят с даты установки и не меняются — различаются сценарии только
    датами замен запчастей, причём у каждой запчасти дата своя: раскладка идёт по
    всему ГРП и ни одна пара дат не совпадает. Иначе у нескольких запчастей был бы
    одинаковый остаточный ресурс, и слабых звеньев в расчёте оказалось бы
    несколько (см. logic.algorithms.weak_link_elements).
    Срок заменяемой запчасти — 5 лет (config.REPLACEABLE_NORM_YEARS), срок полной
    проверки оборудования — 20 лет (config.FULL_CHECK_TERM).
    Каталог оборудования при пересоздании демо-данных не удаляется.
"""
import os
import sys
from datetime import date, datetime, timedelta
from typing import List, Tuple

import psycopg2

from core.config import DB_CONFIG
from core.lifetimes import DAYS_IN_YEAR, years_between

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
    """Наполняет справочник заменяемыми запчастями (срок 5 лет)."""
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
            # Запчасть заведена старой версией seed: срок 5 лет, но признак
            # заменяемости не проставлен. Восстанавливаем признак, иначе
            # миграция ниже поднимет её норму до 20 лет.
            db.update_part_replaceable(row[0], True)
    print(f"[+] Запчасти добавлено: {added} / {len(DEFAULT_REPLACEABLE_PARTS)}")


def align_part_norms():
    """Приводит нормы запчастей к правилу: заменяемые — 5 лет, остальные — 20."""
    from db.database_pg import DatabasePG
    db = DatabasePG(DB_CONFIG)
    counters = db.align_norms_with_replaceable()
    print(f"[+] Нормы запчастей: поднято до 20 лет — {counters['raise_to']}, "
          f"оставлено 5 лет — {counters['lower_to']}, "
          f"задано вручную (не тронуто) — {counters['manual']}, "
          f"без изменений — {counters['ok']}")


# Каталог-справочник (в нём шаблоны моделей со всеми запчастями)
CATALOG_GRP_MARKER = 'каталог'
CATALOG_GRP_NAME = 'Каталог оборудования'

# Префикс типа ГРП у демо-сценариев. По нему seed находит свои сценарии и
# отличает их от реальных ГРП, заведённых пользователем.
DEMO_PREFIX = 'Сценарий №'


# Демонстрационные ГРП: четыре сценария замены запчастей.
# Сценарии НЕ пересоздаются при каждом запуске — они создаются один раз, а
# повторный запуск только проверяет, что они на месте (см. seed_examples).
# Пересоздать принудительно: seed.py --demo --reset-demo.
#
# Оборудование берёт ВСЕ заменяемые запчасти модели из каталога. Сами единицы
# стоят с даты установки и не меняются — различаются сценарии только датами
# замен запчастей. Внутри ГРП ни одна пара дат замены не совпадает: даты
# раскладываются по всем запчастям сразу (_spread_part_dates), иначе у нескольких
# запчастей вышел бы один и тот же остаточный ресурс, а значит несколько слабых
# звеньев вместо одного.
#
# Поля сценария:
#   type        — название ГРП (оно же — тип ГРП в базе);
#   install     — дата установки оборудования (YYYY-MM-DD);
#   spread      — раскладка дат замен: fresh_years — сколько лет назад заменена
#                 самая свежая запчасть, oldest_years — самая старая. Разница
#                 задаёт, каким получится остаточный ресурс: oldest_years
#                 больше 5 (нормы запчасти) — сценарий про просрочку;
#   equipment   — единицы ГРП: точные названия моделей из каталога. Слабым
#                 звеном расчёта становится ПОСЛЕДНЯЯ единица списка: её
#                 расходные запчасти получают самые старые даты (см.
#                 _parts_in_layout_order);
#   journal     — записи журнала замен (таблица replacements):
#                 (дата, обозначение, тип оборудования, модель, изготовитель,
#                  вид работ, причина, ответственный).
#
# Модели обязаны совпадать с названиями из каталога оборудования, иначе
# запчасти не привяжутся (seed сообщит об этом построчно).

EXAMPLES = [
    {
        "type": "Сценарий №1 — ГРП 2008 г.: часть запчастей с истёкшим сроком",
        "lines_count": 2,
        "design_life": 20,
        "install": "2008-05-10",
        "spread": {"fresh_years": 0.3, "oldest_years": 5.4},
        "equipment": [
            {"name": "Регулятор давления газа комбинированный КРОН-150"},
            {"name": "Клапан предохранительный запорный ПКН(В)-50А"},
            {"name": "Клапан предохранительный сбросной ПСК-25"},
            {"name": "Регулятор пилотный"},
            {"name": "Регулятор давления газа РДС-32"},
        ],
        "journal": [
            ("2013-05-12", "", "Регулятор", "КРОН-150", "ООО «Газпроммаш»",
             "Плановый ремонт", "Замена 3 запчастей: седло, пружина, прокладка",
             "Волков В.В."),
            ("2018-05-14", "", "Регулятор", "КРОН-150", "ООО «Газпроммаш»",
             "Плановый ремонт", "Замена 3 запчастей: седло, пружина, прокладка",
             "Волков В.В."),
            ("2023-05-10", "", "Регулятор", "КРОН-150", "ООО «Газпроммаш»",
             "Плановый ремонт", "Замена 3 запчастей: седло, пружина, прокладка",
             "Волков В.В."),
            ("2026-03-12", "", "Регулятор", "КРОН-150", "ООО «Газпроммаш»",
             "Текущий ремонт", "Замена мембраны — расходной запчасти, срок менее года",
             "Волков В.В."),
        ],
    },
    {
        "type": "Сценарий №2 — ГРП 2012 г.: ресурс запчастей менее года",
        "lines_count": 2,
        "design_life": 20,
        "install": "2012-03-15",
        "spread": {"fresh_years": 0.2, "oldest_years": 4.85},
        "equipment": [
            {"name": "Регулятор давления газа прямоточный комбинированный РГП-50"},
            {"name": "Клапан предохранительный запорный ПКН(В)-100А"},
            {"name": "Клапан предохранительный сбросной ПСК-50"},
            {"name": "Регулятор пилотный"},
            {"name": "Механизм настройки ПЗК"},
        ],
        "journal": [
            ("2022-12-20", "", "Регулятор", "РГП-50", "АО «Газмаш»",
             "Текущий ремонт", "Замена мембраны — расходная запчасть, меняется чаще остальных",
             "Волков В.В."),
            ("2023-06-15", "", "Клапан", "ПКН(В)-100А", "АО «Газмаш»",
             "Текущий ремонт", "Замена пружины и втулки", "Морозов М.М."),
            ("2024-03-10", "", "Клапан", "ПСК-50", "АО «Газмаш»",
             "Текущий ремонт", "Замена клапана и винта", "Морозов М.М."),
            ("2025-09-12", "", "Регулятор", "РГП-50", "АО «Газмаш»",
             "Текущий ремонт", "Замена седла и прокладки", "Волков В.В."),
        ],
    },
    {
        "type": "Сценарий №3 — ГРП 2016 г.: ресурс запчастей в норме",
        "lines_count": 2,
        "design_life": 20,
        "install": "2016-06-01",
        "spread": {"fresh_years": 0.15, "oldest_years": 3.6},
        "equipment": [
            {"name": "Регулятор давления комбинированный РДК-50"},
            {"name": "Регулятор давления газа комбинированный КРОН-50"},
            {"name": "Клапан предохранительный запорный прямоточный ПЗКП-32"},
            {"name": "Регулятор давления газа прямоточный РГП-32"},
            {"name": "Регулятор давления газа домовой РДГД-М"},
        ],
        "journal": [
            ("2021-06-08", "", "Регулятор", "РДК-50", "ООО «Газпроммаш»",
             "Плановый ремонт", "Замена мембраны, седла, прокладки", "Волков В.В."),
            ("2022-11-23", "", "Регулятор", "КРОН-50", "ООО «Газпроммаш»",
             "Текущий ремонт", "Замена пружины и втулки", "Морозов М.М."),
            ("2024-02-14", "", "Клапан", "ПЗКП-32", "ООО «Газпроммаш»",
             "Текущий ремонт", "Замена клапана, винта, колец", "Морозов М.М."),
            ("2025-08-19", "", "Регулятор", "РГП-32", "ООО «Газпроммаш»",
             "Текущий ремонт", "Замена мембраны и прокладки", "Волков В.В."),
        ],
    },
    {
        "type": "Сценарий №4 — ГРП 2021 г.: замены запчастей недавние",
        "lines_count": 2,
        "design_life": 20,
        "install": "2021-09-01",
        "spread": {"fresh_years": 0.1, "oldest_years": 1.8},
        "equipment": [
            {"name": "Регулятор давления газа с предохранительным клапаном РДГПК-50М"},
            {"name": "Регулятор давления газа комбинированный КРОН-200"},
            {"name": "Регулятор газа комбинированный РГК-100"},
            {"name": "Клапан предохранительный сбросной ПСК-50"},
            {"name": "Регулятор давления газа РДС-32"},
        ],
        "journal": [
            ("2022-10-05", "", "Регулятор", "КРОН-200", "ООО «Газпроммаш»",
             "Текущий ремонт", "Замена мембраны после пусконаладки", "Волков В.В."),
            ("2024-04-18", "", "Регулятор", "РГК-100", "ООО «Газпроммаш»",
             "Текущий ремонт", "Замена седла и прокладки", "Волков В.В."),
            ("2025-11-27", "", "Клапан", "ПСК-50", "ООО «Газпроммаш»",
             "Текущий ремонт", "Замена клапана и пружины", "Морозов М.М."),
            ("2026-07-14", "", "Регулятор", "РДГПК-50М", "ООО «Газпроммаш»",
             "Текущий ремонт", "Замена мембраны и фильтра", "Морозов М.М."),
        ],
    },
]


def _active_replaceable_parts(db, equipment_id: int):
    """Активные заменяемые запчасти единицы: [(equipment_part_id, название), ...]."""
    rows = []
    for ep in db.get_equipment_parts_full(equipment_id):
        ep_id, _pid, pname, _norm, _install, removal, _number, is_repl = ep
        if removal or not is_repl:
            continue
        rows.append((ep_id, pname))
    return rows


# Изношенные расходники: в раскладке дат они получают самые старые даты, чтобы
# слабым звеном расчёта оказался реальный износ (мембрана, пружина, седло), а не
# крепёж вроде шайбы или винта.
FAST_PART_PREFERENCES = ('мембран', 'пружин', 'седл', 'прокладк', 'фильтр',
                         'клапан', 'втулк', 'тарелк')


def _parts_in_layout_order(db, equipment_ids) -> List[Tuple[int, str]]:
    """Заменяемые запчасти всего ГРП в порядке раскладки дат.

    Порядок: единицы — как заданы в сценарии, внутри единицы расходники
    (FAST_PART_PREFERENCES) — в конец. Раскладка даёт последним в этом списке
    самые старые даты, поэтому слабым звеном становится расходник ПОСЛЕДНЕЙ
    единицы сценария.
    """
    rows = []
    for equipment_id in equipment_ids:
        parts = _active_replaceable_parts(db, equipment_id)
        rows.extend(sorted(parts, key=lambda ep: any(
            token in ep[1].lower() for token in FAST_PART_PREFERENCES)))
    return rows


def _days_ago_series(count: int, fresh_years: float, oldest_years: float) -> List[int]:
    """Сроки давности замен в днях: от самой свежей запчасти к самой старой.

    Даты считаются по тому же году, что и весь расчёт (DAYS_IN_YEAR = 365.25),
    и все получаются разными — в этом смысл сценариев: при совпадающих датах у
    нескольких запчастей был бы один остаточный ресурс, а значит и слабых звеньев
    оказалось бы несколько (logic.algorithms.weak_link_elements).

    Если заданный разброс меньше суток на запчасть, раскладка расширяется: обещание
    «ни одна пара дат не совпадает» держится структурно, а не подобранными
    в сценарии числами.
    """
    fresh_days = max(0.0, fresh_years * DAYS_IN_YEAR)
    span_days = max(0.0, (oldest_years - fresh_years) * DAYS_IN_YEAR)
    if count <= 1:
        return [round(fresh_days + span_days)]
    span_days = max(span_days, float(count - 1))
    step = span_days / (count - 1)
    days = [round(fresh_days + i * step) for i in range(count)]
    if len(set(days)) != count:
        raise ValueError(
            f'не удалось разложить {count} запчастей по дням без совпадений')
    return days


def spread_part_dates(db, equipment_ids, install: str,
                      fresh_years: float, oldest_years: float) -> int:
    """Даёт каждой заменяемой запчасти ГРП свою дату замены.

    Единицы оборудования стоят с даты установки и не меняются — раскладываются
    только даты замен запчастей, от свежих к самым старым. Возвращает число
    запчастей, получивших дату.

    Даты задаются сценарием в годах: fresh_years — сколько лет назад заменена
    самая свежая запчасть, oldest_years — самая старая. Разница между ними и
    определяет остаточный ресурс: больше 5 лет (нормы запчасти) — сценарий про
    просрочку, меньше — ресурс в норме. Дата замены не может быть раньше
    установки оборудования: это уже ошибка в сценарии, а не данные.
    """
    parts = _parts_in_layout_order(db, equipment_ids)
    if not parts:
        return 0

    today = datetime.now().date()
    install_date = date.fromisoformat(install)
    days = _days_ago_series(len(parts), fresh_years, oldest_years)
    for (ep_id, name), days_ago in zip(parts, days):
        replaced = today - timedelta(days=days_ago)
        if replaced < install_date:
            raise ValueError(
                f'«{name}»: дата замены {replaced.isoformat()} раньше установки '
                f'оборудования {install} — поправьте spread сценария')
        db.update_equipment_part(ep_id, install_date=replaced.isoformat())
    return len(parts)


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
    запчасти отсчитывается от даты установки оборудования. Возвращает
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

    from core.config import docs_path
    pdf = docs_path("Альбом запчастей по газу.pdf")
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
    value = years_between(install, today)
    return 0.0 if value is None else round(value, 2)


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
            if units == len(ex["equipment"]):
                print(f"[=] Сценарий уже есть, пропуск: «{grp_type}» "
                      f"(ID={existing_id}, единиц: {units})")
                kept += 1
                continue
            # ГРП есть, но неполный (например, создание оборвалось после сбоя) —
            # пересоздаём целиком, чтобы сценарий был полным.
            print(f"[~] Сценарий неполный ({units} из {len(ex['equipment'])} единиц) "
                  f"— пересоздаю: «{grp_type}»")
            db.delete_grp(existing_id)

        grp_id = db.add_grp(grp_type, ex["lines_count"],
                            _actual_life(install), ex["design_life"])
        equipment_ids = []
        for item in ex["equipment"]:
            name = item["name"]
            eq_id = db.add_equipment(grp_id, name, install, None)
            if not _link_full_parts(db, templates, eq_id, name):
                print(f"    ⚠️ {name} — модели нет в каталоге, запчасти не привязаны")
            equipment_ids.append(eq_id)

        # Даты замен раскладываются сразу по всем запчастям ГРП: по одной на
        # запчасть, без совпадений (см. spread_part_dates).
        spread = ex.get("spread") or {}
        dated = spread_part_dates(db, equipment_ids, install,
                                  spread.get("fresh_years", 0.2),
                                  spread.get("oldest_years", 4.8))

        for rec in ex.get("journal") or []:
            db.add_replacement(grp_id, *rec)
        created += 1
        print(f"[+] Создан сценарий: «{grp_type}» (ID={grp_id}, "
              f"единиц: {len(ex['equipment'])}, дат замен: {dated}, "
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