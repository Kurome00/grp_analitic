"""Паспорт ГРП: поля раздела 1 паспорта и чтение их из строки таблицы `grp`.

Одно описание на три потребителя сразу — раскладку колонок в базе, поля формы
ввода и таблицу «Сведения о ГРП» в Word-отчёте. Иначе подписи и порядок полей
разъезжаются: поле добавили в форму, а в отчёт оно не попало.

Сведения паспорта хранятся текстом. Даты приёмки и ввода в эксплуатацию в
паспорте указаны с точностью до месяца («01.1981», «10.2007») и несут
оговорку («замена с трубами или нет?»), а «Закольцован с» — свободный список
объектов; ни к DATE, ни к числу это не приводится.
"""
from typing import Dict, List, Sequence, Tuple

from core.timefmt import years_to_text

EMPTY = '—'

# Колонки, которые были в grp до паспорта. Порядок менять нельзя: grp[0..4]
# (id, type, lines_count, actual_life, design_life) читается по индексам в
# интерфейсе, отчёте и seed.py.
BASE_COLUMNS = ('type', 'lines_count', 'actual_life', 'design_life')

# Колонки паспорта — добавляются только в конец таблицы.
PASSPORT_COLUMNS = (
    'address', 'reg_number', 'accept_date', 'commission_date',
    'regulator_type', 'body_material', 'pipe_material', 'has_coating',
    'coating_type', 'manufacturer', 'pipeline_type', 'interlocked_with',
)

COLUMNS = BASE_COLUMNS + PASSPORT_COLUMNS

# Колонки строки выборки: id идёт первым, дальше COLUMNS.
ROW_COLUMNS = ('id',) + COLUMNS

# Поля формы и таблицы отчёта: (ключ, подпись, вид поля). Подписи — как в
# разделе 1 паспорта. Вид поля: 'text' — строка, 'int' — целое,
# 'years' — срок (показывается словами «20 лет»), 'choice' — выбор из списка.
FIELDS: Tuple[Tuple[str, str, str], ...] = (
    ('type', 'Наименование объекта', 'text'),
    ('address', 'Адрес', 'text'),
    ('reg_number', 'Регистрационный номер', 'text'),
    ('accept_date', 'Дата приёмки в эксплуатацию', 'text'),
    ('commission_date', 'Дата ввода в эксплуатацию (или дата последней '
                        'полной замены ГРП)', 'text'),
    ('actual_life', 'Фактический срок службы', 'years'),
    ('lines_count', 'Количество линий редуцирования', 'int'),
    ('regulator_type', 'Тип регулятора', 'text'),
    ('body_material', 'Материал корпуса', 'text'),
    ('pipe_material', 'Материал труб', 'text'),
    ('has_coating', 'Наличие антикоррозионного покрытия', 'choice'),
    ('coating_type', 'Тип покрытия', 'text'),
    ('manufacturer', 'Завод-изготовитель', 'text'),
    ('design_life', 'Проектный срок службы', 'years'),
    ('pipeline_type', 'Газопровод', 'text'),
    ('interlocked_with', 'Закольцован с', 'text'),
)

# Поля, которые форма ввода добавляет к уже существующим («Тип ГРП»,
# «Количество линий», сроки): сами базовые поля форма показывает отдельно,
# своими подписями и проверками.
FORM_FIELDS = tuple(item for item in FIELDS if item[0] in PASSPORT_COLUMNS)

# Варианты поля «Наличие антикоррозионного покрытия»: пустое значение —
# сведения не заполнены.
COATING_CHOICES = ('', 'Да', 'Нет')

# Поля-сроки пишутся словами, а не десятичной дробью.
_LIFE_KEYS = frozenset(key for key, _label, kind in FIELDS if kind == 'years')


def value(grp: Sequence, key: str):
    """Значение поля из строки grp (кортеж get_grp_by_id). '' — если поля нет.

    Индекс считается по ROW_COLUMNS, а не пишется числом: при добавлении
    колонки в конец здесь ничего менять не нужно. Короткая строка (защитный
    запасной кортеж в вызывающем коде) не роняет чтение — поле пустое.
    """
    try:
        index = ROW_COLUMNS.index(key)
    except ValueError:
        return ''
    if not grp or index >= len(grp):
        return ''
    raw = grp[index]
    return '' if raw is None else raw


def text(grp: Sequence, key: str) -> str:
    """Значение поля строкой, без пробелов по краям."""
    raw = value(grp, key)
    return '' if raw == '' else str(raw).strip()


def values(grp: Sequence) -> Dict[str, str]:
    """{ключ: значение} по всем полям — для заполнения формы ввода.

    Поля-сроки отдаются так, как их принимает обратный разбор
    (core.timefmt.parse_years): «20 лет», а не «20.00» из базы — иначе
    значение не прочлось бы назад в поле при редактировании.
    """
    result = {}
    for key, _label, kind in FIELDS:
        raw = value(grp, key)
        if kind == 'years':
            result[key] = years_to_text(raw) if raw != '' else ''
        else:
            result[key] = text(grp, key)
    return result


def cell(grp: Sequence, key: str) -> str:
    """Значение для таблицы отчёта: пустое поле показывается прочерком."""
    if key in _LIFE_KEYS:
        return years_to_text(value(grp, key))
    return text(grp, key) or EMPTY


def report_rows(grp: Sequence) -> List[Tuple[str, str]]:
    """Строки таблицы «Сведения о ГРП»: (подпись, значение)."""
    return [(label, cell(grp, key)) for key, label, _kind in FIELDS]
