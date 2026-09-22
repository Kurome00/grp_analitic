# -*- coding: utf-8 -*-
"""Парсер альбома запчастей PDF: оборудование -> список запчастей.

Использование:
    py pdf_parts_import.py --scan "<файл.pdf>"          # показать что найдено
    py pdf_parts_import.py --import "<файл.pdf>"          # наполнить справочник запчастей
    py pdf_parts_import.py --import "<файл.pdf>" --demo   # + привязать совпавшее оборудование
    py pdf_parts_import.py --import "<файл.pdf>" --norm 7 # срок по умолчанию для новых запчастей (лет)

Логика: каждая страница = единица оборудования с таблицей (Позиция/Обозначение/
Наименование/К-ВО). Все уникальные наименования запчастей добавляются в таблицу
parts (норма по умолчанию, правится вручную на вкладке 'Запчасти'). При --demo
оборудование из БД, чьё имя совпадает с названием единицы из альбома, автоматически
пополняется этими запчастями.
"""
import re
import sys

import pdfplumber

from config import DB_CONFIG
from database_pg import DatabasePG

DEFAULT_NORM_YEARS = 5.0

# Слова-мусор в заголовках страниц (заголовки таблиц, служебное)
_HEADER_WORDS = {'ПОЗИЦИЯ', 'ОБОЗНАЧЕНИЕ', 'НАИМЕНОВАНИЕ', 'К-ВО', 'ПРИМЕЧАНИЕ'}


def parse_toc(pdf) -> dict:
    """Из оглавления ('СОДЕРЖАНИЕ') получает карту страница -> название единицы."""
    toc = {}
    for page in pdf.pages:
        text = page.extract_text() or ''
        if 'СОДЕРЖАНИЕ' not in text:
            continue
        for line in text.splitlines():
            m = re.match(r'^(.*?)\.{3,}\s*(\d{1,2}(?:-\d{1,2})?)\s*$', line.strip())
            if not m:
                continue
            title = m.group(1).strip()
            rng = m.group(2)
            pages = range(int(rng), int(rng) + 1) if '-' not in rng else range(
                int(rng.split('-')[0]), int(rng.split('-')[1]) + 1)
            for p in pages:
                toc[p] = title
        break
    return toc


def _sanitize(value) -> str:
    if not value:
        return ''
    return value.replace('\n', ' ').strip()


def _clean_title(lines) -> str:
    """Собирает заголовок единицы оборудования до начала таблицы."""
    used = []
    for line in lines:
        stripped = line.strip()
        upper = stripped.upper()
        if not stripped or stripped.isdigit():
            continue
        # Начало таблицы: строка-заголовок колонок
        if 'ПОЗИЦИЯ' in upper and ('ОБОЗНАЧЕНИЕ' in upper or 'НАИМЕНОВАНИЕ' in upper):
            break
        # Строка только из служебных слов (например "ПОЗИЦИЯ ПОЗИЦИЯ")
        tokens = upper.split()
        if tokens and all(t in _HEADER_WORDS for t in tokens):
            continue
        used.append(stripped)

    # Убираем цифры-ссылки (номера позиций, "23*", номер страницы "8")
    words = used and ' '.join(used).split() or []
    cleaned = [w for w in words if not w.strip('*').strip().isdigit()]
    return ' '.join(cleaned)


def scan_pdf(pdf_path: str):
    """Читает PDF и возвращает список {unit: str, parts: [str,...]}."""
    units = []
    with pdfplumber.open(pdf_path) as pdf:
        toc = parse_toc(pdf)
        for idx, page in enumerate(pdf.pages):
            page_no = idx + 1
            title = toc.get(page_no, '')
            if not title:
                # Если страницы нет в оглавлении — пробуем заголовок с самого листа
                text = page.extract_text() or ''
                title = _clean_title(text.splitlines())
            table = page.extract_table()

            names = []
            if table and table[0] and 'Наименование' in [(c or '') for c in table[0]]:
                # Ищем все колонки 'Наименование' (страницы бывают двухколоночные)
                name_cols = [i for i, h in enumerate(table[0]) if (h or '').strip() == 'Наименование']
                for row in table[1:]:
                    found = set()
                    for i in name_cols:
                        if i < len(row):
                            cell = _sanitize(row[i])
                            if cell:
                                found.add(cell)
                    names.extend(sorted(found))
                # Убираем повторы с сохранением порядка
                seen = set()
                unique = []
                for _n in names:
                    if _n not in seen and _n.lower() not in seen:
                        seen.add(_n.lower())
                        unique.append(_n)
                names = unique

            if not names:
                continue
            units.append({'page': page_no, 'unit': title, 'parts': names})
    return units


def create_catalog_equipment(db, units, grp_name: str) -> int:
    """Создаёт ГРП-каталог и добавляет в него оборудование по полным названиям из альбома."""
    grp_id = None
    for g in db.get_all_grp():
        if g[1].lower() == grp_name.lower():
            grp_id = g[0]
            break
    if grp_id is None:
        grp_id = db.add_grp(grp_name, 1, 0.0, 0.0)
        print(f"[+] Создан ГРП: '{grp_name}'")

    existing = {e[1].lower() for e in db.get_equipment_by_grp(grp_id)}
    created = 0
    for u in units:
        if not u['unit'] or u['unit'].lower() in existing:
            continue
        db.add_equipment(grp_id, u['unit'], None)
        existing.add(u['unit'].lower())
        created += 1
    print(f"[+] Оборудование добавлено в '{grp_name}': {created}")
    return grp_id


def import_to_db(db, units, link_to_equipment: bool = False, norm: float = DEFAULT_NORM_YEARS):
    """Добавляет запчасти в справочник и по желанию привязывает к оборудованию."""
    all_names = []
    for u in units:
        for _n in u['parts']:
            _n_l = _n.lower()
            if _n_l not in {x.lower() for x in all_names}:
                all_names.append(_n)

    existing = {r[1].lower(): r for r in db.get_all_parts()}
    created = 0
    part_ids = {}
    for name in all_names:
        found = existing.get(name.lower())
        if found:
            part_ids[name] = found[0]
        else:
            part_ids[name] = db.add_part(name, float(norm))
            created += 1

    print(f"[+] Запчастей в альбоме: {len(all_names)}, из них новых: {created}")
    if created:
        print(f"    Норма для новых задана: {norm} лет (правится на вкладке 'Запчасти')")

    if not link_to_equipment:
        return

    # Поиск совпадений названий единиц альбома с оборудованием в БД
    equipment = []
    for g in db.get_all_grp():
        equipment.extend(db.get_equipment_by_grp(g[0]))

    linked_units = 0
    for u in units:
        candidates = [e for e in equipment
                      if u['unit'] and (
                          u['unit'].lower() in e[1].lower() or e[1].lower() in u['unit'].lower()
                      )]
        # Точное совпадение названия приоритетнее совпадения подстроки
        exact = [e for e in candidates if e[1].lower() == u['unit'].lower()]
        eqs = exact or candidates
        had_links = False
        for e in eqs:
            existing = {r[2].lower() for r in db.get_equipment_parts(e[0])}
            if existing:
                had_links = True
            linked = 0
            for name in u['parts']:
                if name.lower() in existing:
                    continue
                src = e[3] if e[3] else None  # дата установки запчасти = дата снятия оборудования
                db.add_equipment_part(e[0], part_ids[name], src)
                existing.add(name.lower())
                linked += 1
            print(f"[+] '{e[1]}' <- [{u['unit']}]: добавлено {linked}")
        if had_links:
            linked_units += 1

    # Отчёт о единицах без совпадения в БД
    all_eq_names = {e[1] for e in equipment}
    unmatched = [u for u in units
                 if not any(u['unit'].lower() in n.lower() or n.lower() in u['unit'].lower()
                            for n in all_eq_names)]
    if unmatched:
        print(f"\n[=] Единиц без совпадения в БД ({len(unmatched)}):")
        for u in unmatched[:20]:
            print(f"    - '{u['unit']}' ({u['page']})")

    if not linked_units:
        print("[!] Совпадений с оборудованием БД нет. Создайте оборудование с названием из альбома\n"
              "    или добавьте запчасти вручную через окно 'Показать оборудование' -> 'Запчасти'.")


def main():
    args = sys.argv[1:]
    links = '--demo' in args
    norm = DEFAULT_NORM_YEARS
    if '--norm' in args:
        try:
            norm = float(args[args.index('--norm') + 1])
        except (ValueError, IndexError):
            print("--norm: нужно число (годы)")
            sys.exit(1)

    pdf = [a for a in args if a.lower().endswith('.pdf')]
    if not pdf:
        print("Не указан PDF. Пример: py pdf_parts_import.py --scan 'Альбом запчастей по газу.pdf'")
        sys.exit(1)
    pdf_path = pdf[0]

    grp_name = None
    if '--catalog' in args:
        if args.index('--catalog') + 1 >= len(args):
            print("--catalog: нужно указать имя ГРП-каталога")
            sys.exit(1)
        grp_name = args[args.index('--catalog') + 1]

    units = scan_pdf(pdf_path)
    print(f"Прочитано страниц: {len(units)}\n")
    if '--scan' in args:
        for u in units:
            print(f"[стр. {u['page']:>2}] {u['unit']}")
            for name in u['parts'][:12]:
                print(f"         - {name}")
            if len(u['parts']) > 12:
                print(f"         ... и ещё {len(u['parts']) - 12}")
            print()
        return

    db = DatabasePG(DB_CONFIG)
    import_to_db(db, units, link_to_equipment=links, norm=norm)

    if grp_name:
        catalog_id = create_catalog_equipment(db, units, grp_name)
        if '--reset' in args:
            db.remove_equipment_parts_by_grp(catalog_id)
            print("[~] Связи оборудования каталога очищены")
        import_to_db(db, units, link_to_equipment=True, norm=norm)


if __name__ == '__main__':
    main()