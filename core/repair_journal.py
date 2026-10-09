"""Ремонтный журнал: графы таблицы, поля формы и остаточный ресурс после ремонта.

Одно описание на трёх потребителей сразу — графы таблицы «Замены (ремонт)»,
поля формы записи и чтение строки выборки из базы. Порядок граф задан
заказчиком и повторяет бумажный ремонтный журнал: сначала номер записи и дата
ремонта, потом место работы (номер по схеме) и что именно заменено, причина,
наработка до ремонта, остаточный ресурс после ремонта, документ-основание,
ответственный, вид работ и примечание.

Записи журнала бывают двух видов. Запись из «Лида.xlsx» знает только дату,
обозначение, тип оборудования, модель, изготовителя, вид работ, причину и
ответственного: по этим полям заполняется файл «Замены.xlsx» и отчёт Word, и
они обязаны сохранить свои места в строке выборки. Новые графы (наработка до
ремонта, остаточный ресурс, документ-основание, примечание) добавлены в конец
записи, поэтому прежние поля не сдвинулись (см. EXTRA_COLUMNS).
"""
import re
from typing import Dict, Optional, Sequence

from core import equipment_card
from core.timefmt import DurationError, years_to_text

EMPTY = '—'

# Дата в базе хранится так, как её ввели: ISO из демо-данных и импорта или
# «15.03.2024» из формы. Для показа ISO приводится к общему виду.
_ISO_DATE = re.compile(r'^(\d{4})-(\d{2})-(\d{2})')

# Графы таблицы журнала: (ключ, подпись, ширина). Первой графой идёт «№» —
# номер строки в списке, он нигде не хранится: это место записи в журнале.
TABLE_COLUMNS = (
    ('replace_date', 'Дата замены/ремонта', 105),
    ('scheme_number', 'Номер по схеме', 100),
    ('part', 'Запчасть в этом оборудовании', 200),
    ('reason', 'Причина замены/ремонта', 180),
    ('hours_before', 'Наработка до замены/ремонта', 120),
    ('residual_after', 'Остаточный ресурс после ремонта, лет', 130),
    ('document', 'Документ-основание', 140),
    ('supervisor', 'ФИО ответственного', 130),
    ('work_type', 'Вид работ', 120),
    ('note', 'Примечание', 160),
)

# Графы, которых не было в образце «Лида.xlsx». Добавлены в конец колонок
# таблицы replacements, поэтому прежние поля строки выборки сохраняют свои
# индексы.
EXTRA_COLUMNS = ('hours_before', 'residual_after', 'document', 'note')

# Поля формы записи: (ключ, подпись, подсказка). Прежние поля («Лида.xlsx»)
# форма показывает как и раньше, здесь описаны только новые графы.
FORM_FIELDS = (
    ('hours_before', 'Наработка до замены/ремонта',
     'наработка оборудования к дате замены, в часах'),
    ('residual_after', 'Остаточный ресурс после ремонта, лет',
     'число лет либо «не нормируется»'),
    ('document', 'Документ-основание', 'акт, дефектная ведомость, наряд-заказ'),
    ('note', 'Примечание', 'свободная строка'),
)

# Строка выборки get_replacement: прежние поля записи, затем новые графы.
RECORD_COLUMNS = ('id', 'replace_date', 'part_number', 'equipment_type', 'model',
                  'manufacturer', 'work_type', 'reason', 'supervisor',
                  'equipment_id', 'part_id', 'effect',
                  'new_equipment_id') + EXTRA_COLUMNS

# Строка выборки get_replacements_by_grp: без привязки к оборудованию и эффекта.
BY_GRP_COLUMNS = ('id', 'replace_date', 'part_number', 'equipment_type', 'model',
                  'manufacturer', 'work_type', 'reason',
                  'supervisor') + EXTRA_COLUMNS

# Строка выборки get_replacements_detailed: запись целиком и названия объектов,
# к которым она привязана, — из них собирается графа «Номер по схеме».
DETAILED_COLUMNS = RECORD_COLUMNS + ('equipment_name', 'part_name',
                                     'scheme_number')


def value(source, key: str, columns: Sequence[str] = DETAILED_COLUMNS) -> str:
    """Значение поля записи журнала; '' — если поля нет в этой выборке.

    source — строка выборки (индекс считается по columns, а не пишется числом:
    при добавлении колонки в конец здесь ничего менять не нужно) либо словарь
    значений. Короткая строка не роняет чтение — поле пустое.
    """
    if isinstance(source, dict):
        raw = source.get(key)
    else:
        try:
            raw = source[list(columns).index(key)]
        except (ValueError, IndexError, TypeError):
            return ''
    return str(raw if raw is not None else '').strip()


def form_values(source, columns: Sequence[str] = RECORD_COLUMNS) -> Dict[str, str]:
    """Новые графы записи для формы: {ключ: значение}, незаполненное — ''."""
    return {key: value(source, key, columns) for key, _label, _hint in FORM_FIELDS}


def extras(fields: Dict) -> Dict[str, Optional[str]]:
    """Новые графы из словаря формы для записи в базу: пустая строка → NULL."""
    return {key: (str(fields.get(key) or '').strip() or None)
            for key, _label, _hint in FORM_FIELDS}


def parse_residual(text) -> str:
    """Проверить графу «Остаточный ресурс после ремонта, лет».

    Как и назначенный срок службы в паспорте единицы, это либо число лет, либо
    слова «не нормируется» (ресурс документацией не назначен), либо пусто.
    Всё прочее — DurationError: «5 лет, продлён» в графе неотличимо от описки.
    """
    try:
        return equipment_card.parse_life(text)
    except DurationError:
        raise DurationError(
            'Остаточный ресурс после ремонта — число лет (например, «5») '
            'либо «не нормируется».')


def residual_after(effect: str, norm_years: float = None,
                   assigned_life: str = '') -> str:
    """Остаточный ресурс после ремонта — предзаполнение формы.

    Сброс срока запчасти возвращает ей нормативный срок заново (norm_years),
    полная замена оборудования — назначенный срок службы новой единицы: при
    полной замене паспорт переносится, поэтому он тот же. Если документация
    срок не назначила («не нормируется»), сравнивать не с чем — графа пуста, в
    таблице у неё будет прочерк.

    Значение подставляется в форму на виду и правится вручную — в журнал
    попадает то, что в нём осталось.
    """
    if effect == 'part' and norm_years:
        return years_to_text(norm_years)
    if effect == 'equipment':
        life = equipment_card.norm_life(assigned_life)
        return '' if equipment_card.is_not_normed(life) else life
    return ''


def date_text(value) -> str:
    """Дата замены/ремонта для показа: «ДД.ММ.ГГГГ».

    В базе дата лежит так, как её ввели, поэтому в журнале ISO приводится к
    виду, принятому в документах. Запись без дня («05.2023») и любой другой
    текст показываются как записаны — выдумывать день нельзя.
    """
    text = str(value or '').strip()
    found = _ISO_DATE.match(text)
    if not found:
        return text
    year, month, day = found.groups()
    return f'{day}.{month}.{year}'


def part_cell(source, columns: Sequence[str] = DETAILED_COLUMNS) -> str:
    """Что заменено: название запчасти и её обозначение.

    Название берётся из справочника запчастей (привязка part_id), обозначение —
    из самой записи журнала: у записи без привязки название взять негде, и
    тогда видно только обозначение.
    """
    name = value(source, 'part_name', columns)
    number = value(source, 'part_number', columns)
    if name and number and name != number:
        return f'{name} · {number}'
    return name or number


def table_cells(source, columns: Sequence[str] = DETAILED_COLUMNS) -> list:
    """Значения граф журнала в порядке TABLE_COLUMNS (без ведущей «№»).

    Графа «Запчасть» собирается из названия и обозначения, дата приводится к
    виду «ДД.ММ.ГГГГ»; остальные показываются как записаны. Незаполненная
    графа — прочерк, а не пустая клетка.
    """
    shown = {}
    for key, _label, _width in TABLE_COLUMNS:
        if key == 'part':
            shown[key] = part_cell(source, columns)
        elif key == 'replace_date':
            shown[key] = date_text(value(source, key, columns))
        else:
            shown[key] = value(source, key, columns)
    return [shown[key] or EMPTY for key, _label, _width in TABLE_COLUMNS]


def table_index(key: str) -> int:
    """Номер значения графы в строке таблицы.

    Первой графой идёт «№», поэтому к позиции в TABLE_COLUMNS прибавляется
    единица. Индекс считается, а не пишется числом: при перестановке граф
    чтение строки не сломается.
    """
    return 1 + [column for column, _label, _width in TABLE_COLUMNS].index(key)
