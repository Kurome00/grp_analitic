# -*- coding: utf-8 -*-
"""Формирование официального отчёта по ГРП в формате Word (.docx).

Документ оформлен по требованиям к инженерным отчётам:
титульный лист с рамкой, содержание (автособираемое оглавление),
автонумерация разделов, нумерованные таблицы с повторяющейся шапкой,
колонтитул с номером страницы, подписи исполнителей и приложения.

Сроки элементов определяются по заменяемым запчастям: срок равен
минимальному оставшемуся сроку службы среди них. Оборудование без
запчастей срока не имеет. Дополнительно выполняется расчёт остаточного
ресурса по алгоритмам 0-4 (см. модуль algorithms).
"""
from datetime import date, datetime

from docx import Document
from docx.enum.section import WD_ORIENT, WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

from core.config import FULL_CHECK_TERM
from core.models import Equipment
from core.timefmt import years_to_text
from logic.algorithms import (
    DAMAGE_MARKERS,
    FAILURE_MARKERS,
    POOR_REPAIR_MARKERS,
    AlgorithmParams,
    GRPResourceCalculator,
    calculate_all_algorithms,
    critical_title,
    num,
)

# ---------------------------------------------------------------------------
# Реквизиты документа (заполняются под конкретную организацию)
# ---------------------------------------------------------------------------

REPORT_META = {
    'organization': 'Гроднооблгаз',
    'department': 'Производственно-технический отдел',
    'city': 'г. Гродно',
    'doc_code': 'ГРО',
    'report_kind': 'ОТЧЁТ',
    'report_title': 'о результатах расчёта остаточного ресурса\n'
                    'оборудования газорегуляторного пункта',
}

# Срок полной проверки оборудования ГРП. По правилу отрасли срок службы
# элемента либо 5 лет, либо 20 лет: за пределами 20 лет эксплуатация не
# подтверждается, так как полная проверка проводится раз в 20 лет. Значение
# берётся из config, чтобы отчёт и расчёт пользовались одним значением, и
# выводится в отчёте явно с пометкой источника, а не подставляется молча.
FULL_INSPECTION_TERM = FULL_CHECK_TERM

# Цветовая схема
INK = (0, 0, 0)
GREY = (89, 89, 89)
RED = (176, 0, 0)
AMBER = (191, 143, 0)
GREEN = (0, 112, 60)

FILL_HEADER = 'D9E2F3'      # шапка таблицы
FILL_BAND = 'F2F5FA'        # чередование строк
FILL_RED = 'FBE4E4'
FILL_AMBER = 'FFF3DA'
FILL_GREEN = 'E4F2E6'
FILL_TOTAL = 'E8EDF5'

BODY_FONT = 'Times New Roman'
BODY_SIZE = 14
TABLE_SIZE = 9


def configure_report(organization=None, department=None, city=None,
                     doc_code=None, report_kind=None, report_title=None):
    """Задать реквизиты организации для титульного листа."""
    for key, value in (('organization', organization), ('department', department),
                       ('city', city), ('doc_code', doc_code),
                       ('report_kind', report_kind), ('report_title', report_title)):
        if value:
            REPORT_META[key] = value


# ---------------------------------------------------------------------------
# Низкоуровневые помощники OOXML
# ---------------------------------------------------------------------------

def _shade(cell, fill):
    """Заливка ячейки таблицы."""
    properties = cell._tc.get_or_add_tcPr()
    shading = OxmlElement('w:shd')
    shading.set(qn('w:val'), 'clear')
    shading.set(qn('w:color'), 'auto')
    shading.set(qn('w:fill'), fill)
    properties.append(shading)


def _field(paragraph, instruction, size=BODY_SIZE, bold=False):
    """Вставляет поле Word (PAGE, TOC, NUMPAGES)."""
    run = paragraph.add_run()
    run.font.name = BODY_FONT
    run.font.size = Pt(size)
    run.font.bold = bold
    begin = OxmlElement('w:fldChar')
    begin.set(qn('w:fldCharType'), 'begin')
    instr = OxmlElement('w:instrText')
    instr.set(qn('xml:space'), 'preserve')
    instr.text = instruction
    separate = OxmlElement('w:fldChar')
    separate.set(qn('w:fldCharType'), 'separate')
    placeholder = OxmlElement('w:t')
    placeholder.text = '1'
    end = OxmlElement('w:fldChar')
    end.set(qn('w:fldCharType'), 'end')
    for node in (begin, instr, separate, placeholder, end):
        run._r.append(node)
    return run


def _update_fields_on_open(doc):
    """Просит Word обновить оглавление при открытии файла."""
    settings = doc.settings.element
    flag = OxmlElement('w:updateFields')
    flag.set(qn('w:val'), 'true')
    settings.append(flag)


def _page_border(section, size='12', space='24'):
    """Рамка вокруг страницы — оформление титульного листа."""
    borders = OxmlElement('w:pgBorders')
    borders.set(qn('w:offsetFrom'), 'page')
    for edge in ('top', 'left', 'bottom', 'right'):
        element = OxmlElement(f'w:{edge}')
        element.set(qn('w:val'), 'single')
        element.set(qn('w:sz'), size)
        element.set(qn('w:space'), space)
        element.set(qn('w:color'), '000000')
        borders.append(element)
    section._sectPr.append(borders)


def _horizontal_rule(paragraph, size='8'):
    """Горизонтальная линия-разделитель (нижняя граница абзаца)."""
    properties = paragraph._p.get_or_add_pPr()
    borders = OxmlElement('w:pBdr')
    bottom = OxmlElement('w:bottom')
    bottom.set(qn('w:val'), 'single')
    bottom.set(qn('w:sz'), size)
    bottom.set(qn('w:space'), '1')
    bottom.set(qn('w:color'), '808080')
    borders.append(bottom)
    properties.append(borders)


# ---------------------------------------------------------------------------
# Разметка страницы и стили
# ---------------------------------------------------------------------------

def _setup_section(section, landscape=False):
    """A4 с полями по ГОСТ: слева 30 мм, справа 15, сверху 20, снизу 20."""
    if landscape:
        section.orientation = WD_ORIENT.LANDSCAPE
        section.page_width, section.page_height = Cm(29.7), Cm(21.0)
        section.left_margin, section.right_margin = Cm(2.0), Cm(1.5)
        section.top_margin, section.bottom_margin = Cm(1.5), Cm(1.5)
    else:
        section.orientation = WD_ORIENT.PORTRAIT
        section.page_width, section.page_height = Cm(21.0), Cm(29.7)
        section.left_margin, section.right_margin = Cm(3.0), Cm(1.5)
        section.top_margin, section.bottom_margin = Cm(2.0), Cm(2.0)
    section.header_distance, section.footer_distance = Cm(1.0), Cm(1.0)


def _setup_styles(doc):
    """Единые стили документа."""
    normal = doc.styles['Normal']
    normal.font.name = BODY_FONT
    normal.font.size = Pt(BODY_SIZE)
    normal.font.color.rgb = RGBColor(*INK)
    paragraph_format = normal.paragraph_format
    paragraph_format.line_spacing = 1.5
    paragraph_format.space_after = Pt(0)
    paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY

    for level, size, align, before, after in (
            (1, BODY_SIZE, WD_ALIGN_PARAGRAPH.CENTER, 18, 12),
            (2, 13, WD_ALIGN_PARAGRAPH.LEFT, 14, 8),
            (3, BODY_SIZE, WD_ALIGN_PARAGRAPH.LEFT, 10, 6)):
        style = doc.styles[f'Heading {level}']
        style.font.name = BODY_FONT
        style.font.size = Pt(size)
        style.font.bold = True
        style.font.color.rgb = RGBColor(*INK)
        style.font.italic = False
        style.paragraph_format.alignment = align
        style.paragraph_format.space_before = Pt(before)
        style.paragraph_format.space_after = Pt(after)
        style.paragraph_format.keep_with_next = True
        style.paragraph_format.line_spacing = 1.15

    caption = doc.styles['Caption']
    caption.font.name = BODY_FONT
    caption.font.size = Pt(12)
    caption.font.bold = False
    caption.font.italic = True
    caption.font.color.rgb = RGBColor(*INK)
    caption.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT
    caption.paragraph_format.space_before = Pt(8)
    caption.paragraph_format.space_after = Pt(4)
    caption.paragraph_format.keep_with_next = True


# ---------------------------------------------------------------------------
# Текстовые блоки
# ---------------------------------------------------------------------------

def _body(doc, text, bold=False, color=INK, size=BODY_SIZE, align=None,
          indent=True, space_after=0, italic=False):
    paragraph = doc.add_paragraph()
    run = paragraph.add_run(text)
    run.font.name = BODY_FONT
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.italic = italic
    run.font.color.rgb = RGBColor(*color)
    if align is not None:
        paragraph.alignment = align
    if indent and align is None:
        paragraph.paragraph_format.first_line_indent = Cm(1.25)
    paragraph.paragraph_format.space_after = Pt(space_after)
    return paragraph


def _formula(doc, text):
    """Формула методики — по центру, без отступа первой строки."""
    return _body(doc, text, align=WD_ALIGN_PARAGRAPH.CENTER, indent=False,
                 size=BODY_SIZE, space_after=6)


def _note(doc, text, color=GREY):
    """Примечание меньшим кеглем."""
    return _body(doc, text, color=color, size=11, indent=False, italic=True,
                 space_after=6)


def _bullet(doc, text, color=INK, bold=False):
    paragraph = doc.add_paragraph(style='List Bullet')
    run = paragraph.add_run(text)
    run.font.name = BODY_FONT
    run.font.size = Pt(BODY_SIZE)
    run.font.bold = bold
    run.font.color.rgb = RGBColor(*color)
    paragraph.paragraph_format.space_after = Pt(4)
    return paragraph


def _section_title(doc, text):
    return doc.add_heading(text, level=1)


# ---------------------------------------------------------------------------
# Таблицы
# ---------------------------------------------------------------------------

def _cell_text(cell, text, bold=False, size=TABLE_SIZE, color=INK,
               align=WD_ALIGN_PARAGRAPH.CENTER, fill=None, italic=False):
    cell.text = ''
    paragraph = cell.paragraphs[0]
    paragraph.alignment = align
    paragraph.paragraph_format.space_before = Pt(2)
    paragraph.paragraph_format.space_after = Pt(2)
    paragraph.paragraph_format.line_spacing = 1.0
    run = paragraph.add_run(str(text) if text is not None else '—')
    run.font.name = BODY_FONT
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.italic = italic
    run.font.color.rgb = RGBColor(*color)
    if fill:
        _shade(cell, fill)


def _fix_widths(table, widths):
    """Фиксированная ширина колонок (иначе Word пересчитывает по содержимому)."""
    table.autofit = False
    layout = OxmlElement('w:tblLayout')
    layout.set(qn('w:type'), 'fixed')
    table._tbl.tblPr.append(layout)
    for row in table.rows:
        for index, width in enumerate(widths):
            if index < len(row.cells):
                row.cells[index].width = Cm(width)


def _repeat_header(row):
    """Повторять строку шапки на каждой странице."""
    properties = row._tr.get_or_add_trPr()
    header = OxmlElement('w:tblHeader')
    header.set(qn('w:val'), 'true')
    properties.append(header)


def _keep_together(row):
    """Запретить разрыв строки между страницами."""
    properties = row._tr.get_or_add_trPr()
    cant_split = OxmlElement('w:cantSplit')
    properties.append(cant_split)


def _table_caption(doc, number, title):
    paragraph = doc.add_paragraph(style='Caption')
    run = paragraph.add_run(f'Таблица {number} — {title}')
    run.font.name = BODY_FONT
    run.font.size = Pt(12)
    run.font.italic = True
    run.font.color.rgb = RGBColor(*INK)
    return paragraph


def _build_table(doc, headers, rows, widths, aligns=None, row_fills=None,
                 size=TABLE_SIZE, header_size=None):
    """Таблица с повторяющейся шапкой и чередованием строк."""
    table = doc.add_table(rows=1 + len(rows), cols=len(headers))
    table.style = 'Table Grid'
    table.alignment = WD_TABLE_ALIGNMENT.CENTER

    for index, header in enumerate(headers):
        _cell_text(table.rows[0].cells[index], header, bold=True,
                   size=header_size or size, fill=FILL_HEADER)
    _repeat_header(table.rows[0])
    _keep_together(table.rows[0])

    for row_index, row in enumerate(rows, start=1):
        fill = FILL_TOTAL if row_index % 2 == 0 else None
        if row_fills and row_fills[row_index - 1]:
            fill = row_fills[row_index - 1]
        for column, value in enumerate(row):
            align = (aligns[column] if aligns and column < len(aligns)
                     else WD_ALIGN_PARAGRAPH.CENTER)
            _cell_text(table.rows[row_index].cells[column], value, size=size,
                       align=align, fill=fill)
        _keep_together(table.rows[row_index])

    _fix_widths(table, widths)
    return table


# ---------------------------------------------------------------------------
# Титульный лист и содержание
# ---------------------------------------------------------------------------

def _title_page(doc, grp_name, grp_id, generated_at):
    """Титульный лист с рамкой и реквизитами."""
    section = doc.sections[0]
    _setup_section(section)
    _page_border(section)

    _body(doc, REPORT_META['organization'], bold=True, size=14,
          align=WD_ALIGN_PARAGRAPH.CENTER, indent=False)
    _body(doc, REPORT_META['department'], size=12,
          align=WD_ALIGN_PARAGRAPH.CENTER, indent=False, color=GREY)
    rule = doc.add_paragraph()
    rule.paragraph_format.space_before = Pt(6)
    rule.paragraph_format.space_after = Pt(6)
    _horizontal_rule(rule)

    _body(doc, REPORT_META['report_kind'], bold=True, size=26,
          align=WD_ALIGN_PARAGRAPH.CENTER, indent=False, space_after=10)
    for line in REPORT_META['report_title'].split('\n'):
        _body(doc, line, bold=True, size=16, align=WD_ALIGN_PARAGRAPH.CENTER,
              indent=False, space_after=2)

    for _ in range(4):
        doc.add_paragraph()

    details = [
        ('Объект оценки', f'ГРП «{grp_name}»'),
        ('Идентификатор объекта в системе', f'№ {grp_id}'),
        ('Шифр документа', REPORT_META['doc_code']),
        ('Редакция', '1.0'),
        ('Дата формирования', generated_at.strftime('%d.%m.%Y')),
        ('Режим доступа', 'Для служебного пользования'),
    ]
    table = doc.add_table(rows=len(details), cols=2)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    for index, (label, value) in enumerate(details):
        _cell_text(table.rows[index].cells[0], label, align=WD_ALIGN_PARAGRAPH.RIGHT,
                   size=12, color=GREY)
        _cell_text(table.rows[index].cells[1], value, align=WD_ALIGN_PARAGRAPH.LEFT,
                   size=12, bold=True)
    _fix_widths(table, [8.0, 7.5])

    for _ in range(5):
        doc.add_paragraph()

    rule = doc.add_paragraph()
    rule.paragraph_format.space_before = Pt(6)
    rule.paragraph_format.space_after = Pt(6)
    _horizontal_rule(rule)

    _body(doc, REPORT_META['city'], size=13, align=WD_ALIGN_PARAGRAPH.CENTER,
          indent=False, space_after=2)
    _body(doc, str(generated_at.year), size=13, bold=True,
          align=WD_ALIGN_PARAGRAPH.CENTER, indent=False)


def _page_footer(section):
    """Колонтитул с номером страницы по центру (без наследования)."""
    section.footer.is_linked_to_previous = False
    footer = section.footer
    for paragraph in footer.paragraphs[1:]:
        paragraph._p.getparent().remove(paragraph._p)
    paragraph = footer.paragraphs[0]
    for run in list(paragraph.runs):
        run._r.getparent().remove(run._r)
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = paragraph.add_run('— ')
    run.font.name = BODY_FONT
    run.font.size = Pt(11)
    _field(paragraph, 'PAGE', size=11)
    run = paragraph.add_run(' —')
    run.font.name = BODY_FONT
    run.font.size = Pt(11)


def _content_page(doc, section):
    """Содержание с автоматическим оглавлением."""
    _setup_section(section)
    _page_footer(section)
    _section_title(doc, 'СОДЕРЖАНИЕ')
    paragraph = doc.add_paragraph()
    paragraph.paragraph_format.first_line_indent = Cm(0)
    _field(paragraph, r'TOC \o "1-2" \h \z \u', size=BODY_SIZE)
    _note(doc, 'Оглавление обновляется автоматически при открытии документа '
               '(Word: «Ссылки» → «Обновить таблицу»).')


def _signatures(doc, generated_at):
    """Подписи исполнителей."""
    _body(doc, '', indent=False)
    table = doc.add_table(rows=4, cols=3)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    rows = [
        ('Исполнитель', '', '_____________________'),
        ('Проверил', '', '_____________________'),
        ('Утвердил', '', '_____________________'),
        ('Дата выдачи', generated_at.strftime('%d.%m.%Y'), ''),
    ]
    for index, (label, value, signature) in enumerate(rows):
        _cell_text(table.rows[index].cells[0], label, align=WD_ALIGN_PARAGRAPH.LEFT,
                   size=12, bold=True)
        _cell_text(table.rows[index].cells[1], value, align=WD_ALIGN_PARAGRAPH.LEFT,
                   size=12, color=GREY)
        _cell_text(table.rows[index].cells[2], signature,
                   align=WD_ALIGN_PARAGRAPH.LEFT, size=12)
    _fix_widths(table, [4.5, 6.0, 5.0])


# ---------------------------------------------------------------------------
# Подготовка данных
# ---------------------------------------------------------------------------

def _fmt(value, digits=1):
    """Число в русской нотации."""
    number = num(value, digits)
    return number if number != '—' else '—'


def _norm_cell(element):
    """Нормативный срок службы элемента.

    Если норма определена в базе — выводится она. Если данных о норме нет,
    принимается срок полной проверки оборудования (20 лет) с явной пометкой
    источника, чтобы принятое значение нельзя было спутать с нормативным.
    """
    if element.norm:
        return _fmt(element.norm, 1)
    return f'{_fmt(FULL_INSPECTION_TERM, 0)}*'


def _term_source_note(element):
    """Пометка о том, что срок принят по циклу полной проверки."""
    if element is not None and element.norm:
        return ''
    return (f'* — нормативный срок в базе отсутствует; принят срок полной '
            f'проверки оборудования — {_fmt(FULL_INSPECTION_TERM, 0)} лет. '
            f'По истечении этого срока эксплуатация не подтверждается и '
            f'требуется полная проверка.')


def _age_years(value):
    """Возраст оборудования в годах от даты установки."""
    parsed = GRPResourceCalculator._parse_date(value)
    if not parsed:
        return None
    return (date.today() - parsed).days / 365.25


def _match_journal(name, journal):
    """Записи журнала замен для типа оборудования."""
    low = str(name or '').strip().lower()
    for key, record in journal.items():
        if key and (key == low or key in low or low in key):
            return record
    return None


def _load_journal(db, grp_id):
    """Журнал замен, сгруппированный по типу оборудования."""
    journal = {}
    try:
        rows = db.get_replacements_by_grp(grp_id) or []
    except Exception:  # noqa: BLE001 — журнал не критичен для отчёта
        return journal
    for row in rows:
        row = list(row) + [None] * 9
        haystack = ' '.join(str(v or '') for v in
                            (row[6], row[7], row[4], row[2])).lower()
        key = str(row[3] or '').strip().lower()
        record = journal.setdefault(key, {'fail': 0, 'damage': 0, 'poor': 0, 'total': 0})
        record['total'] += 1
        if any(marker in haystack for marker in FAILURE_MARKERS):
            record['fail'] += 1
        if any(marker in haystack for marker in DAMAGE_MARKERS):
            record['damage'] += 1
        if any(marker in haystack for marker in POOR_REPAIR_MARKERS):
            record['poor'] += 1
    return journal


def _calc_inputs(db, grp_id, equipment_rows, journal):
    """Входные данные для расчёта остаточного ресурса по алгоритмам."""
    payload = []
    for row in equipment_rows:
        row = list(row) + [None] * 4
        equip = {'name': row[1] or '', 'equipment_id': row[0],
                 'install_date': row[2], 'removal_date': row[3]}

        details = []
        try:
            parts = db.get_equipment_parts_full(row[0]) or []
        except Exception:  # noqa: BLE001
            parts = []
        for part in parts:
            part = list(part) + [None] * 8
            norm_years, removal, replaceable = part[3], part[5], part[7]
            if removal or not norm_years or float(norm_years) <= 0:
                continue
            details.append({'name': part[2] or 'Деталь',
                            'norm_years': float(norm_years),
                            'install_date': part[4] or row[2],
                            'is_replaceable': bool(replaceable)})
        replaceable = [d for d in details if d['is_replaceable']]
        equip['details'] = replaceable or details

        record = _match_journal(equip['name'], journal)
        if record:
            equip['failures'] = record['fail']
            equip['damages'] = record['damage']
            if record['poor']:
                equip['repair'] = {'quality': 'poor'}
            elif record['total']:
                equip['repair'] = {'quality': 'new'}
        payload.append(equip)
    return payload


def _coefficients(db, grp_id):
    try:
        rows = db.get_technical_coefficients(grp_id) or []
    except Exception:  # noqa: BLE001
        return {}
    if not rows:
        return {}
    row = list(rows[0]) + [None] * 10
    return {'a': row[2], 'b': row[3], 'c': row[4], 'date': row[1]}


# ---------------------------------------------------------------------------
# Отчёт
# ---------------------------------------------------------------------------

def generate_grp_docx(db, doc_analyzer, grp_id: int, grp_name: str,
                      filename: str = None) -> str:
    """Сформировать официальный Word-отчёт по конкретному ГРП.

    Возвращает путь к сохранённому файлу .docx.
    """
    generated_at = datetime.now()
    grp = db.get_grp_by_id(grp_id) or (grp_id, grp_name, 0, 0, 0)
    equipment_rows = db.get_equipment_by_grp(grp_id) or []
    equipment_list = [
        Equipment(name=e[1], install_date=e[2], removal_date=e[3], id=e[0])
        for e in equipment_rows
    ]
    analysis = doc_analyzer.analyze_grp_equipment(equipment_list)
    current = analysis['current']
    stats = current['statistics']
    replacements = db.get_replacements_by_grp(grp_id) or []

    journal = _load_journal(db, grp_id)
    coefficients = _coefficients(db, grp_id)
    params = AlgorithmParams()
    results = calculate_all_algorithms(_calc_inputs(db, grp_id, equipment_rows, journal),
                                       params=params, coefficients=coefficients)
    primary = results[3]
    usable = [r for r in results.values() if not r.error]

    doc = Document()
    _setup_styles(doc)
    _update_fields_on_open(doc)

    # --- Титульный лист ---------------------------------------------------
    _title_page(doc, grp_name, grp_id, generated_at)

    # Разрыв раздела сам начинает новую страницу — лишний разрыв страницы
    # здесь создавал бы пустой лист.
    content_section = doc.add_section(WD_SECTION.NEW_PAGE)
    _content_page(doc, content_section)
    doc.add_page_break()

    table_number = 0

    def caption(title):
        nonlocal table_number
        table_number += 1
        _table_caption(doc, table_number, title)

    # --- 1. Общие сведения ------------------------------------------------
    _section_title(doc, '1 ОБЩИЕ СВЕДЕНИЯ')
    _body(doc, 'Настоящий отчёт содержит результаты оценки остаточного ресурса '
               f'оборудования газорегуляторного пункта «{grp_name}» и предназначен '
               'для планирования технического обслуживания, диагностирования и '
               'замены оборудования.', space_after=8)

    caption('Параметры газорегуляторного пункта')
    _build_table(doc, ['Показатель', 'Значение'], [
        ['Тип газорегуляторного пункта', grp[1]],
        ['Количество ниток', _fmt(grp[2], 0)],
        ['Фактический срок службы, лет', _fmt(grp[3], 1)],
        ['Проектный срок службы, лет', _fmt(grp[4], 1)],
        ['Оборудования в эксплуатации, ед.', _fmt(stats['total'], 0)],
        ['Замен запчастей по журналу, ед.', _fmt(len(replacements), 0)],
    ], widths=[8.0, 7.5], aligns=[WD_ALIGN_PARAGRAPH.LEFT, WD_ALIGN_PARAGRAPH.CENTER],
        size=11)
    _body(doc, '', indent=False, space_after=6)

    # --- 2. Методика -------------------------------------------------------
    _section_title(doc, '2 МЕТОДИКА РАСЧЁТА')
    _body(doc, 'Расчёт выполнен по скорректированной редакции методики оценки '
               'остаточного ресурса элементов ГРП. Оценка производится в два этапа: '
               'определяется базовый ресурс элемента, затем применяются '
               'поправочные коэффициенты. Итог по ГРП определяется по принципу '
               'слабого звена — минимальному ресурсу среди критических элементов.',
          space_after=8)

    doc.add_heading('2.1 Базовый ресурс элемента', level=2)
    _body(doc, 'Базовый ресурс определяется каскадом оценок; применяется первый '
               'доступный вариант:', space_after=4)
    _bullet(doc, 'вариант А — по фактической наработке (телеметрия): '
                 'Z = (Sнач − Sфакт) / Sнач · Sнач;')
    _bullet(doc, 'вариант Б1 — по протоколу диагностики: Zд = Kсост,д · Sнач,д;')
    _bullet(doc, 'вариант Б2 — документальная (экспертная) оценка: '
                 'Zд = Sнач,д − Sфакт,д;')
    _bullet(doc, 'вариант В — календарный (резервный) при отсутствии сведений '
                 'о деталях: Z = Sнач − Sфакт.')
    _body(doc, 'Ресурс элемента принимается равным минимуму по его деталям, то есть '
               'определяется слабейшей деталью.', space_after=6)

    doc.add_heading('2.2 Поправочные коэффициенты', level=2)
    _formula(doc, 'Zэл = Zбаза · Kсост · Kэксл · Kрем · kповр')
    _formula(doc, 'Kсост = 1 − (1/n) · Σ |Δij| / Допускij')
    _formula(doc, 'Kэксл = 1 − θ · (1 − Услфакт / Услнорм)')
    _formula(doc, 'kповр = max(0; 1 − α · Nотказ − β · Nповрежд)')
    _body(doc, 'При отсутствии данных соответствующий коэффициент принимается равным '
               'единице; факт отсутствия данных фиксируется в отчёте.', space_after=8)

    doc.add_heading('2.3 Итог по ГРП и срок диагностирования', level=2)
    _formula(doc, 'ZГРП = min (Zрег; Zпзк; Zпск; Zфильтр; Zарматура)')
    _formula(doc, 'Tдиагн = min (ZГРП · Kзапаса ; Tмакс)')
    _body(doc, '', indent=False, space_after=4)

    caption('Принятые весовые коэффициенты')
    coefficient_rows = [list(row) for row in params.as_rows()]
    _build_table(doc, ['Параметр', 'Значение', 'Диапазон', 'Назначение'],
                 coefficient_rows, widths=[3.6, 1.8, 2.0, 8.1],
                 aligns=[WD_ALIGN_PARAGRAPH.LEFT, WD_ALIGN_PARAGRAPH.CENTER,
                         WD_ALIGN_PARAGRAPH.CENTER, WD_ALIGN_PARAGRAPH.LEFT],
                 size=10)
    _note(doc, 'Значения приведены по рекомендациям методики и подлежат уточнению '
               'по результатам эксплуатации конкретного объекта.')
    _body(doc, '', indent=False, space_after=6)

    # --- 3. Результаты расчёта --------------------------------------------
    _section_title(doc, '3 РЕЗУЛЬТАТЫ РАСЧЁТА ОСТАТОЧНОГО РЕСУРСА')
    if usable:
        _body(doc, f'Остаточный ресурс ГРП «{grp_name}» по основной методике '
                   f'(алгоритм 3) составляет {years_to_text(primary.result)} '
                   f'({_fmt(primary.result, 2)} года). Слабым звеном определён '
                   f'элемент «{primary.weak_element}».', bold=True, space_after=8)
    else:
        _body(doc, 'Расчёт остаточного ресурса не выполнен: '
                   f'{primary.error or "нет исходных данных"}.', bold=True,
              color=RED, space_after=8)

    caption('Сравнение результатов по методикам')
    comparison_rows, fills = [], []
    for number, result in sorted(results.items()):
        if result.error:
            comparison_rows.append([f'Алгоритм {number} — {result.algorithm_name}',
                                    '—', '—', result.error])
            fills.append(FILL_TOTAL)
            continue
        comparison_rows.append([
            f'Алгоритм {number} — {result.algorithm_name}'
            + (' (основная)' if number == 3 else ''),
            years_to_text(result.result),
            years_to_text(result.next_diagnosis),
            result.weak_element or '—',
        ])
        fills.append(FILL_TOTAL if number == 3 else None)
    _build_table(doc, ['Методика', 'Остаточный ресурс', 'Срок диагностирования',
                       'Слабое звено'],
                 comparison_rows, widths=[5.6, 3.2, 3.2, 3.5],
                 aligns=[WD_ALIGN_PARAGRAPH.LEFT, WD_ALIGN_PARAGRAPH.CENTER,
                         WD_ALIGN_PARAGRAPH.CENTER, WD_ALIGN_PARAGRAPH.LEFT],
                 row_fills=fills, size=10)
    _body(doc, '', indent=False, space_after=6)

    if usable:
        worst = min(usable, key=lambda r: r.result)
        _body(doc, f'Справочно: консервативная оценка (минимум по всем методикам) — '
                   f'{years_to_text(worst.result)}, методика «{worst.algorithm_name}». '
                   f'Рекомендация: {worst.recommendation}', size=12, space_after=8)

    # --- 4. Поэлементный расчёт -------------------------------------------
    _section_title(doc, '4 ПОЭЛЕМЕНТНЫЙ РАСЧЁТ')
    _body(doc, 'В расчёт включены критические элементы ГРП. Для каждого приведены '
               'нормативный ресурс, фактический возраст, базовый ресурс с указанием '
               'применённого варианта оценки и итоговые поправки.', space_after=8)

    element_rows, element_fills = [], []
    weak_name = primary.weak_element
    for element in primary.elements:
        if not element.used:
            # Элемент исключён из итога (например, не является критическим),
            # но его норма, возраст и базовый ресурс движок уже посчитал —
            # показываем их, чтобы данные не терялись. Поправочные
            # коэффициенты и итоговый ресурс не применяются.
            element_rows.append([
                element.name,
                'не входит в расчёт: ' + element.skip_reason,
                _norm_cell(element),
                _fmt(element.age, 1),
                f'{_fmt(element.z_base, 2)} ({element.z_base_variant or "—"})',
                '—', '—', '—', '—', '—'])
            element_fills.append(FILL_BAND)
            continue
        element_rows.append([
            element.name,
            critical_title(element.critical_key) if element.critical_key else '—',
            _norm_cell(element),
            _fmt(element.age, 1),
            f'{_fmt(element.z_base, 2)} ({element.z_base_variant or "—"})',
            _fmt(element.k_state, 3),
            _fmt(element.k_cond, 3),
            _fmt(element.k_repair, 3),
            _fmt(element.k_fail, 3),
            _fmt(element.z_element, 2),
        ])
        element_fills.append(FILL_RED if element.name == weak_name
                             else (FILL_AMBER if element.z_element <= 0 else None))
    if primary.elements:
        _build_table(doc, ['Элемент', 'Категория', 'S нач, лет', 'Возраст, лет',
                           'Z база, лет', 'K сост', 'K эксл', 'K рем', 'k повр',
                           'Z эл, лет'],
                     element_rows,
                     widths=[3.6, 2.6, 1.3, 1.3, 1.9, 1.1, 1.1, 1.1, 1.1, 1.4],
                     row_fills=element_fills, size=8)
        _note(doc, 'Выделенная строка — слабое звено, определяющее итог по ГРП. '
                   'Здесь и далее: Zбаза — базовый ресурс в варианте оценки '
                   'А/Б1/Б2/В, Zэл — ресурс с учётом всех поправок. Для элементов, '
                   'не вошедших в итог, показываются норма, возраст и базовый '
                   'ресурс; поправочные коэффициенты к ним не применяются, поэтому '
                   'Zэл по ним не рассчитывается.')
        if any(not element.norm for element in primary.elements):
            _note(doc, _term_source_note(next(
                element for element in primary.elements
                if not element.norm)), color=AMBER)
    else:
        # Нормативный срок не определён ни для одного элемента: расчёт
        # остаточного ресурса не выполняется. Чтобы отчёт не оставался
        # пустым, по каждой позиции показывается принятый срок полной
        # проверки оборудования, а незнание нормы отражается явно.
        _note(doc, f'Расчёт остаточного ресурса не выполнен: {primary.error}. '
                   f'Для контроля срока эксплуатации по перечисленным позициям '
                   f'принят срок полной проверки оборудования — '
                   f'{_fmt(FULL_INSPECTION_TERM, 0)} лет.', color=AMBER)
        fallback_rows, fallback_fills = [], []
        for row in equipment_rows:
            row = list(row) + [None] * 4
            if row[3]:
                continue
            fallback_rows.append([
                row[1] or 'Без названия', row[2] or '—',
                f'{_fmt(FULL_INSPECTION_TERM, 0)}*',
                _fmt(_age_years(row[2]), 1), '—', '—', '—', '—', '—', '—'])
            fallback_fills.append(FILL_AMBER)
        if fallback_rows:
            caption('Принятые сроки службы при отсутствии нормативов')
            _build_table(doc, ['Элемент', 'Дата установки', 'S нач, лет',
                               'Возраст, лет', 'Z база, лет', 'K сост',
                               'K эксл', 'K рем', 'k повр', 'Z эл, лет'],
                         fallback_rows,
                         widths=[3.6, 2.2, 1.3, 1.3, 1.9, 1.1, 1.1, 1.1, 1.1, 1.4],
                         row_fills=fallback_fills, size=8)
            _note(doc, _term_source_note(None), color=AMBER)
    _body(doc, '', indent=False, space_after=6)

    # --- 5. Сводка состояния ----------------------------------------------
    _section_title(doc, '5 СВОДКА СОСТОЯНИЯ ОБОРУДОВАНИЯ')
    caption('Распределение оборудования по остатку срока службы')
    summary_rows = [
        ['Всего в эксплуатации', _fmt(stats['total'], 0), FILL_TOTAL],
        ['Срок истёк — требуется замена', _fmt(stats['exceeded_count'], 0), FILL_RED],
        ['Осталось менее года', _fmt(stats['warning_count'], 0), FILL_AMBER],
        ['В пределах срока', _fmt(stats['normal_count'], 0), FILL_GREEN],
        ['Без сведений о запчастях', _fmt(stats['no_norm_count'], 0), None],
    ]
    _build_table(doc, ['Категория состояния', 'Количество, ед.'],
                 [[row[0], row[1]] for row in summary_rows],
                 widths=[11.0, 4.5],
                 aligns=[WD_ALIGN_PARAGRAPH.LEFT, WD_ALIGN_PARAGRAPH.CENTER],
                 row_fills=[row[2] for row in summary_rows], size=11)
    _body(doc, '', indent=False, space_after=6)

    # --- 6. Оборудование с истёкшим сроком --------------------------------
    _section_title(doc, '6 ОБОРУДОВАНИЕ С ИСТЁКШИМ СРОКОМ СЛУЖБЫ')
    if current['exceeded']:
        rows, fills = [], []
        for item in current['exceeded']:
            rows.append([item['name'], item['install_date'] or '—',
                         years_to_text(item['age_years']),
                         years_to_text(-item['remaining']),
                         years_to_text(item['exceeded_years'])])
            fills.append(FILL_RED)
        caption('Оборудование, срок службы которого истёк')
        _build_table(doc, ['Оборудование', 'Дата установки', 'Возраст',
                           'Остаток', 'Просрочено'],
                     rows, widths=[5.0, 2.4, 2.2, 2.2, 3.7],
                     aligns=[WD_ALIGN_PARAGRAPH.LEFT, WD_ALIGN_PARAGRAPH.CENTER,
                             WD_ALIGN_PARAGRAPH.CENTER, WD_ALIGN_PARAGRAPH.CENTER,
                             WD_ALIGN_PARAGRAPH.CENTER],
                     row_fills=fills, size=10)
        _body(doc, '', indent=False, space_after=6)
        _body(doc, 'По результатам оценки требуется замена перечисленного '
                   'оборудования. Наименее приоритетным является элемент с наибольшей '
                   'просрочкой.', space_after=6)
    else:
        _body(doc, 'Оборудования с истёкшим сроком службы не выявлено.',
              color=GREEN, space_after=6)

    # --- 7. Требующее внимания -------------------------------------------
    _section_title(doc, '7 ОБОРУДОВАНИЕ, ТРЕБУЮЩЕЕ ВНИМАНИЯ')
    if current['warning']:
        rows, fills = [], []
        for item in current['warning']:
            rows.append([item['name'], item['install_date'] or '—',
                         years_to_text(item['left_years'])])
            fills.append(FILL_AMBER)
        caption('Оборудование с остатком срока менее года')
        _build_table(doc, ['Оборудование', 'Дата установки', 'Остаточный срок'],
                     rows, widths=[6.4, 3.2, 3.9],
                     aligns=[WD_ALIGN_PARAGRAPH.LEFT, WD_ALIGN_PARAGRAPH.CENTER,
                             WD_ALIGN_PARAGRAPH.CENTER],
                     row_fills=fills, size=10)
        _body(doc, '', indent=False, space_after=6)
        _body(doc, 'Замену перечисленного оборудования следует запланировать '
                   'в пределах ближайшего года.', space_after=6)
    else:
        _body(doc, 'Оборудования с остатком срока менее года не выявлено.',
              color=GREEN, space_after=6)

    # --- 8. В пределах срока ----------------------------------------------
    _section_title(doc, '8 ОБОРУДОВАНИЕ В ПРЕДЕЛАХ СРОКА СЛУЖБЫ')
    if current['normal']:
        caption('Оборудование, эксплуатация которого продолжается')
        _build_table(doc, ['Оборудование', 'Дата установки', 'Остаточный срок'],
                     [[item['name'], item['install_date'] or '—',
                       years_to_text(item['left_years'])] for item in current['normal']],
                     widths=[7.0, 3.0, 3.5],
                     aligns=[WD_ALIGN_PARAGRAPH.LEFT, WD_ALIGN_PARAGRAPH.CENTER,
                             WD_ALIGN_PARAGRAPH.CENTER], size=10)
        _body(doc, '', indent=False, space_after=6)
    else:
        _body(doc, 'Оборудования в пределах срока нет.', color=GREEN, space_after=6)

    # --- 9. Без сведений о запчастях -------------------------------------
    _section_title(doc, '9 ОБОРУДОВАНИЕ БЕЗ СВЕДЕНИЙ О ЗАПЧАСТЯХ')
    if current['no_norm']:
        caption('Оборудование, для которого нормативный срок в базе отсутствует')
        _build_table(doc, ['Оборудование', 'Дата установки',
                           'Принятый срок', 'Мероприятие'],
                     [[item['name'], item['install_date'] or '—',
                       _fmt(FULL_INSPECTION_TERM, 0),
                       'Внести состав запчастей и нормы']
                      for item in current['no_norm']],
                     widths=[5.2, 2.4, 2.4, 5.5],
                     aligns=[WD_ALIGN_PARAGRAPH.LEFT, WD_ALIGN_PARAGRAPH.CENTER,
                             WD_ALIGN_PARAGRAPH.CENTER,
                             WD_ALIGN_PARAGRAPH.LEFT], row_fills=[FILL_AMBER] *
                      len(current['no_norm']), size=10)
        _body(doc, '', indent=False, space_after=6)
        _body(doc, f'Нормативные сроки по указанным позициям в базе отсутствуют, '
                   f'поэтому для контроля принят срок полной проверки оборудования '
                   f'— {_fmt(FULL_INSPECTION_TERM, 0)} лет. По истечении этого срока '
                   f'эксплуатация не подтверждается. Детальный расчёт остаточного '
                   f'ресурса выполняется после внесения состава запчастей и норм.',
              space_after=6)
    else:
        _body(doc, 'Оборудования без сведений о запчастях нет.', color=GREEN,
              space_after=6)

    # --- 10. История замен оборудования -----------------------------------
    section_number = 10
    if analysis['history']['removed_count'] > 0:
        _section_title(doc, f'{section_number} ИСТОРИЯ ЗАМЕН ОБОРУДОВАНИЯ')
        history_rows = []
        for equip_type, records in analysis['history']['replacement_history'].items():
            for record in records:
                history_rows.append([
                    equip_type, record['install_date'] or '—',
                    record['removal_date'] or '—',
                    years_to_text(record['lifetime_years'])])
        caption('Демонтированное и заменённое оборудование')
        _build_table(doc, ['Тип оборудования', 'Установлено', 'Демонтировано',
                           'Время жизни'],
                     history_rows, widths=[5.4, 3.0, 3.0, 4.1],
                     aligns=[WD_ALIGN_PARAGRAPH.LEFT, WD_ALIGN_PARAGRAPH.CENTER,
                             WD_ALIGN_PARAGRAPH.CENTER, WD_ALIGN_PARAGRAPH.CENTER],
                     size=10)
        _body(doc, '', indent=False, space_after=6)
        section_number += 1

    # --- Журнал замен запчастей (альбомная ориентация) --------------------
    # Разрыв раздела ставится до заголовка, иначе заголовок и таблица
    # оказались бы на разных страницах.
    if replacements:
        landscape = doc.add_section(WD_SECTION.NEW_PAGE)
        _setup_section(landscape, landscape=True)
        _page_footer(landscape)

    _section_title(doc, f'{section_number} ЖУРНАЛ ЗАМЕН ЗАПЧАСТЕЙ')
    section_number += 1
    if replacements:
        _body(doc, f'По ГРП «{grp_name}» зафиксировано записей: '
                   f'{len(replacements)}.', space_after=6)
    else:
        _body(doc, 'Замен запчастей по данному ГРП не зафиксировано.', space_after=6)

    if replacements:
        caption('Журнал замен запчастей')
        _build_table(doc,
                     ['№', 'Дата', 'Номер запчасти', 'Тип оборудования', 'Модель',
                      'Производитель', 'Вид работ', 'Причина', 'Ответственный'],
                     [[str(index), record[1] or '—', record[2] or '—',
                       record[3] or '—', record[4] or '—', record[5] or '—',
                       record[6] or '—', record[7] or '—', record[8] or '—']
                      for index, record in enumerate(replacements, start=1)],
                     widths=[0.9, 2.0, 2.6, 3.6, 2.4, 2.8, 2.6, 4.6, 3.5],
                     aligns=[WD_ALIGN_PARAGRAPH.CENTER, WD_ALIGN_PARAGRAPH.CENTER,
                             WD_ALIGN_PARAGRAPH.LEFT, WD_ALIGN_PARAGRAPH.LEFT,
                             WD_ALIGN_PARAGRAPH.LEFT, WD_ALIGN_PARAGRAPH.LEFT,
                             WD_ALIGN_PARAGRAPH.LEFT, WD_ALIGN_PARAGRAPH.LEFT,
                             WD_ALIGN_PARAGRAPH.LEFT], size=9)

    # Возврат в книжную ориентацию
    portrait = doc.add_section(WD_SECTION.NEW_PAGE)
    _setup_section(portrait)
    _page_footer(portrait)

    # --- Выводы ------------------------------------------------------------
    _section_title(doc, f'{section_number} ВЫВОДЫ И РЕКОМЕНДАЦИИ')
    section_number += 1

    conclusions = []
    if stats['exceeded_count'] > 0:
        conclusions.append(
            (RED, f'Требуется немедленная замена {stats["exceeded_count"]} ед. '
                  f'оборудования — срок службы установленных деталей истёк.'))
    if stats['warning_count'] > 0:
        conclusions.append(
            (AMBER, f'Замену {stats["warning_count"]} ед. оборудования следует '
                    f'запланировать в течение ближайшего года.'))
    if stats['no_norm_count'] > 0:
        conclusions.append(
            (GREY, f'По {stats["no_norm_count"]} ед. оборудования отсутствуют сведения '
                    f'о составе и нормах — необходимо их внести.'))
    if usable:
        conclusions.append(
            (INK, f'Плановый срок диагностирования по основной методике — '
                  f'{years_to_text(primary.next_diagnosis)} '
                  f'(не позднее {_fmt(params.max_diag_interval, 0)} лет).'))
    if not conclusions:
        conclusions.append((GREEN, 'Оборудование ГРП находится в пределах '
                                   'нормативного срока службы.'))

    for color, text in conclusions:
        _body(doc, text, bold=color != GREY, color=color, space_after=6)

    if usable:
        _body(doc, '', indent=False, space_after=6)
        _signatures(doc, generated_at)
        _body(doc, '', indent=False, space_after=6)
        _note(doc, f'Отчёт сформирован автоматически '
                   f'{generated_at.strftime("%d.%m.%Y в %H:%M")} '
                   f'по данным информационной системы учёта газорегуляторных пунктов. '
                   f'Идентификатор объекта: {grp_id}.')

    # --- Приложение А. Трассировка ----------------------------------------
    doc.add_page_break()
    doc.add_heading('ПРИЛОЖЕНИЕ А', level=1)
    _body(doc, '(справочное) Пошаговая трассировка расчёта остаточного ресурса '
               'по основной методике', bold=True, align=WD_ALIGN_PARAGRAPH.CENTER,
          indent=False, space_after=8)

    _table_caption(doc, table_number + 1, 'Последовательность вычислений')
    trace_table = doc.add_table(rows=1, cols=2)
    trace_table.style = 'Table Grid'
    _cell_text(trace_table.rows[0].cells[0], 'Шаг', bold=True, size=10,
               fill=FILL_HEADER)
    _cell_text(trace_table.rows[0].cells[1], 'Вычисление', bold=True, size=10,
               fill=FILL_HEADER)
    _repeat_header(trace_table.rows[0])
    for step in primary.steps:
        if not step.text.strip():
            continue
        row = trace_table.add_row()
        level = step.level
        _cell_text(row.cells[0], {'title': 'Заголовок', 'formula': 'Формула',
                                  'value': 'Значение', 'note': 'Примечание',
                                  'warn': 'Внимание'}.get(level, 'Значение'),
                   size=9, color=GREY)
        color = RED if level == 'warn' else INK
        _cell_text(row.cells[1], step.text.strip(), size=9,
                   align=WD_ALIGN_PARAGRAPH.LEFT,
                   bold=level in ('title', 'formula'), color=color)
    _fix_widths(trace_table, [3.0, 12.5])

    if not filename:
        filename = f'otchet_grp_{grp_id}_{generated_at.strftime("%Y%m%d")}.docx'
    doc.save(filename)
    return filename
