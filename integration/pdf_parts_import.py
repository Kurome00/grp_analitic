# -*- coding: utf-8 -*-
"""Парсер альбома запчастей PDF: оборудование -> список запчастей.

Использование (запускать из корня проекта):
    py -m integration.pdf_parts_import --scan "<файл.pdf>"          # показать что найдено
    py -m integration.pdf_parts_import --import "<файл.pdf>"        # наполнить справочник запчастей
    py -m integration.pdf_parts_import --import "<файл.pdf>" --demo # + привязать совпавшее оборудование
    py -m integration.pdf_parts_import --import "<файл.pdf>" --norm 7 # норма для новых запчастей (лет)

Логика: каждая страница = единица оборудования с таблицей (Позиция/Обозначение/
Наименование/К-ВО). Все уникальные наименования запчастей добавляются в таблицу
parts с нормой по умолчанию = срок полной проверки (20 лет), правится вручную
на вкладке 'Запчасти'. При --import-flags детали, помеченные в альбоме
заменяемыми, получают срок 5 лет. При --demo оборудование из БД, чьё имя
совпадает с названием единицы из альбома, автоматически пополняется этими
запчастями.
"""
import re
import sys

import pdfplumber

from core.config import DB_CONFIG, FULL_CHECK_TERM, part_norm
from db.database_pg import DatabasePG

# Норма по умолчанию для новых деталей: срок полной проверки оборудования.
# Детали, отмеченные заменяемыми, получают 5 лет (см. import_flags).
DEFAULT_NORM_YEARS = FULL_CHECK_TERM

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


def _norm(name: str) -> str:
    """Нормализация названия для сопоставления."""
    return re.sub(r'\s+', ' ', name or '').replace('ё', 'е').strip().lower()


def _designation(title: str) -> str:
    """Обозначение единицы альбома — последнее слово названия («РДС-32»)."""
    words = _norm(title).split()
    return words[-1] if words else ''


def is_breakdown_page(title: str, titles) -> bool:
    """Страница разборки узла, а не самостоятельное оборудование.

    В альбоме после модели идут страницы её узлов: за «Регулятором давления
    газа РДС-32» — «Корпус регулятора давления газа РДС-32» и «Мембрана
    регулятора давления газа РДС-32». Это запчасти модели: обозначение у них
    то же, а название длиннее. Отдельный узел со своим названием («Механизм
    настройки ПЗК») под правило не попадает — его обозначения нет ни у одной
    другой единицы, и оборудованием он быть не перестаёт.
    """
    own = _norm(title)
    key = _designation(title)
    if not own or not key:
        return False
    return any(_designation(other) == key and len(_norm(other)) < len(own)
               for other in titles)


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
    """Создаёт ГРП-каталог и добавляет в него оборудование по названиям из альбома.

    Единица альбома — это страница. Страницы разборки узлов («Корпус …»,
    «Мембрана …») оборудованием не считаются: их запчасти и так входят в
    состав модели (см. is_breakdown_page), и в каталоге они только мешали бы
    оборудованию с запчастями.
    """
    grp_id = None
    for g in db.get_all_grp():
        if g[1].lower() == grp_name.lower():
            grp_id = g[0]
            break
    if grp_id is None:
        grp_id = db.add_grp(grp_name, 1, 0.0, 0.0)
        print(f"[+] Создан ГРП: '{grp_name}'")

    titles = [u['unit'] for u in units if u['unit']]
    existing = {e[1].lower() for e in db.get_equipment_by_grp(grp_id)}
    created = 0
    skipped = []
    for u in units:
        if not u['unit'] or u['unit'].lower() in existing:
            continue
        if is_breakdown_page(u['unit'], titles):
            skipped.append(u['unit'])
            continue
        db.add_equipment(grp_id, u['unit'], None)
        existing.add(u['unit'].lower())
        created += 1
    print(f"[+] Оборудование добавлено в '{grp_name}': {created}")
    if skipped:
        print(f"    Пропущено страниц разборки узлов (это запчасти модели): "
              f"{len(skipped)}")
        for title in skipped:
            print(f"    - '{title}'")
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


# Расходные детали (срок службы 5 лет, подлежат замене по звёздочке в альбоме).
# Эвристика по умолчанию — список уточняется пользователем в интерфейсе.
REPLACEABLE_KEYWORDS = (
    'кольцо', 'прокладка', 'мембрана', 'пружина', 'клапан', 'седло', 'тарелка',
    'ролик', 'палец', 'сухарь', 'шток', 'диск', 'фильтр', 'манжета', 'сальник',
    'поршень', 'упор', 'хомут', 'дроссель', 'регулятор пилотный',
    'механизм настройки пзк',
)

# Исключения конструктивных деталей (не заменяемые), даже если слово попало выше
NON_REPLACEABLE_EXACT = {'клапан предохранительный', 'клапан перепускной'}


def _name_matches(row_name: str, part_name: str) -> bool:
    a, b = _norm(row_name), _norm(part_name)
    if not a or not b:
        return False
    a = a.split(' гост ')[0].strip()
    b = b.split(' гост ')[0].strip()
    return a == b or (len(a) >= 4 and len(b) >= 4 and (a in b or b in a))


def _part_replaceable(name: str) -> bool:
    n = _norm(name)
    if n in {_norm(x) for x in NON_REPLACEABLE_EXACT}:
        return False
    return any(k in n for k in REPLACEABLE_KEYWORDS)


def scan_rows_with_flags(pdf_path: str):
    """Читает таблицы альбома: для каждого листа (модели) возвращает строки
    (обозначение, наименование, звёздочка рядом со строкой)."""
    units = []
    with pdfplumber.open(pdf_path) as pdf:
        toc = parse_toc(pdf)
        for idx, page in enumerate(pdf.pages):
            page_no = idx + 1
            title = toc.get(page_no, '')
            if not title:
                title = _clean_title((page.extract_text() or '').splitlines())
            stars = [w for w in page.extract_words(keep_blank_chars=False) if '*' in w['text']]

            # Выбираем таблицу с нужными колонками; координаты строк берём из
            # объекта Table (для привязки звёздочек к строкам по вертикали).
            found = []
            for t in page.find_tables():
                try:
                    tbl = t.extract()
                except Exception:
                    continue
                if not tbl:
                    continue
                hdr = tbl[0] if tbl else []
                if len(hdr) < 3:
                    continue
                hs = [str((c or '').strip()) for c in hdr]
                if 'Обозначение' in hs and 'Наименование' in hs:
                    found.append((t, tbl))
            if not found:
                # запасной вариант — как в scan_pdf
                tbl = page.extract_table()
                if tbl and tbl[0]:
                    found.append((None, tbl))

            for t, tbl in found:
                hdr = tbl[0]
                hs = [str((c or '').strip()) for c in hdr]
                des_i = hs.index('Обозначение') if 'Обозначение' in hs else 0
                nam_i = hs.index('Наименование') if 'Наименование' in hs else 0
                for nr, row in enumerate(tbl[1:], start=1):
                    if not row or not row[nam_i]:
                        continue
                    design = _sanitize(row[des_i]) if des_i < len(row) else ''
                    name = _sanitize(row[nam_i])
                    if not name or name == 'Наименование':
                        continue
                    starred = False
                    if t and nr < len(t.rows):
                        cells = t.rows[nr].cells
                        cell0 = cells[0] if cells else None
                        if cell0:
                            _x0, top, _x1, bottom = cell0
                            starred = any(top - 4 <= s['top'] <= bottom + 4 for s in stars)
                    units.append({
                        'page': page_no,
                        'unit': title,
                        'design': design,
                        'name': name,
                        'star': starred,
                    })
    return units


def import_flags(pdf_path: str):
    """Проставляет обозначения (part_number) на связях каталога и отмечает
    заменяемые детали в справочнике (эвристика, правится пользователем)."""
    db = DatabasePG(DB_CONFIG)
    rows = scan_rows_with_flags(pdf_path)
    print(f"[+] Строк таблиц альбома: {len(rows)}")

    catalog_id = None
    for g in db.get_all_grp():
        if 'каталог' in g[1].lower():
            catalog_id = g[0]
            break
    if catalog_id is None:
        print("[!] ГРП-каталог не найден")
        return
    equipment = db.get_equipment_by_grp(catalog_id)
    eq_by_name = {e[1].lower(): e for e in equipment}

    set_flags = {}
    filled = 0
    matched_rows = 0
    for row in rows:
        unit = row['unit']
        eq = eq_by_name.get(unit.lower())
        if not eq:
            eq = next((e for e in equipment
                       if unit.lower() in e[1].lower() or e[1].lower() in unit.lower()), None)
        if not eq:
            continue
        # наименование детали из таблицы альбома -> деталь в составе модели
        part = next((p for p in db.get_equipment_parts(eq[0])
                     if _name_matches(row['name'], p[2])), None)
        if not part:
            continue
        matched_rows += 1
        ep_id, part_id, part_name = part[0], part[1], part[2]
        # обозначение (каталожный номер), только если похож на номер
        if row['design'] and re.match(r'^[`]?\d{2,3}-|^[`]?АТ-|^[`]?ЕЛШУ\.', row['design'].strip()):
            with db.get_connection() as conn:
                cur = conn.cursor()
                cur.execute('UPDATE equipment_parts SET part_number = %s WHERE id = %s',
                            (row['design'].strip().lstrip('`'), ep_id))
            filled += 1
        already = set_flags.get(part_name)
        flag = _part_replaceable(row['name'])
        if already is not None:
            flag = flag or already
        set_flags[part_name] = flag

    print(f"[+] Из строк таблиц сопоставлено с каталогом: {matched_rows}")
    print(f"[+] Обозначений (part_number) проставлено: {filled}")

    replaceable = [n for n, f in set_flags.items() if f]
    with db.get_connection() as conn:
        cur = conn.cursor()
        cur.execute('UPDATE parts SET is_replaceable = FALSE')
    for name, flag in set_flags.items():
        part = db.get_part_by_name(name)
        if not part:
            continue
        db.update_part_replaceable(part[0], flag)
        if flag:
            # Заменяемая деталь живёт 5 лет; всё остальное — срок полной
            # проверки. Признак и норма хранятся согласованно.
            db.update_part_norm(part[0], part_norm(True))
    print(f"[+] Отмечено заменяемых деталей: {len(replaceable)}")
    print(f"\nЗаменяемые (срок {part_norm(True):g} лет):")
    for n in sorted(replaceable, key=str.lower):
        print(f"    - {n}")
    non = [n for n, f in set_flags.items() if not f]
    print(f"\nОстальные ({len(non)}) — срок {part_norm(False):g} лет. "
          f"Поправить можно на вкладке 'Запчасти'.")


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
        print("Не указан PDF. Пример: py -m integration.pdf_parts_import --scan "
              "'docs/Альбом запчастей по газу.pdf'")
        sys.exit(1)
    pdf_path = pdf[0]

    if '--flags' in args:
        import_flags(pdf_path)
        return

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