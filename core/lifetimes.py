"""Единый расчёт возраста, нормы и остатка срока службы.

До появления этого модуля одна и та же арифметика была в четырёх местах
(`logic/algorithms.py`, `logic/documentary_analyzer.py`, `ui/views_pg.py`,
`integration/word_report_pg.py`, `core/models.py`), причём с разными
делителями: 365.25 дней/год в одних и 30.44 в других. Расхождение в
полгода-год проявлялось как «в интерфейсе срок один, в отчёте другой».

Правила, зафиксированные здесь:

* год = DAYS_IN_YEAR (365.25) дней — средний календарный год;
* месяц = DAYS_IN_MONTH (30.44) дней — средний месяц, только для перевода
  лет в месяцы (`Equipment.lifetime_months`), где точность до дней не нужна;
* год для расчёта сроков **всегда** получается делением на DAYS_IN_YEAR.

Менять эти константы в одном месте здесь и не дублировать их в прикладном
коде: иначе расхождения вернутся.
"""

from datetime import date, datetime
from typing import Optional, Union

from core.config import EQUIPMENT_NORMS, FULL_CHECK_TERM, part_norm

# Средний календарный год и средний месяц.
DAYS_IN_YEAR = 365.25
DAYS_IN_MONTH = 30.44
MONTHS_IN_YEAR = 12.0

DateLike = Union[str, date, datetime, None]

# Форматы дат, встречающиеся в БД, в журналах и при ручном вводе.
_DATE_FORMATS = ('%Y-%m-%d', '%d.%m.%Y', '%Y-%m-%d %H:%M:%S', '%d.%m.%y')


def parse_date(value: DateLike) -> Optional[date]:
    """Дата из БД, строки или объекта datetime. None — если разобрать нельзя.

    Раньше каждая копия этой функции знала свой набор форматов, из-за чего
    дата, принятая одной частью приложения, отвергалась другой.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    text = text.rstrip('гг').strip() if text.endswith('г') else text
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text[:19].strip(), fmt).date()
        except ValueError:
            continue
    return None


def years_between(start: DateLike, end: DateLike = None) -> Optional[float]:
    """Срок между двумя датами, в годах. None — если нет первой даты.

    Отсутствие второй даты означает «по сегодняшний день».
    """
    start_date = parse_date(start)
    if start_date is None:
        return None
    end_date = parse_date(end) or date.today()
    return (end_date - start_date).days / DAYS_IN_YEAR


def age_years(start: DateLike, end: DateLike = None) -> float:
    """Возраст в годах; при неизвестной дате — 0.0.

    Именно такой вариант нужен расчёту: элемент без даты установки получает
    нулевой возраст, а не падение. Отсутствие даты показывается отдельно
    (см. norm_source и skip_reason в logic/algorithms.py).
    """
    value = years_between(start, end)
    return 0.0 if value is None else value


def add_years(start: DateLike, years: float) -> Optional[date]:
    """Дата истечения срока: start + years лет."""
    start_date = parse_date(start)
    if start_date is None:
        return None
    return start_date + _days(years)


def _days(years: float) -> 'datetime.timedelta':
    from datetime import timedelta
    return timedelta(days=years * DAYS_IN_YEAR)


def remaining_years(start: DateLike, norm_years, today: DateLike = None) -> Optional[float]:
    """Остаток срока службы, лет: норма минус возраст.

    None — если нет даты отсчёта или норма не задана. Отрицательное значение
    означает просрочку и возвращается как есть: вызывающий сам решает, как
    её показывать.
    """
    try:
        norm = float(norm_years)
    except (TypeError, ValueError):
        return None
    age = years_between(start, today)
    if age is None:
        return None
    return norm - age


def lifetime_months(start: DateLike, end: DateLike = None) -> Optional[float]:
    """Время жизни в месяцах. None — если нет даты начала."""
    start_date = parse_date(start)
    if start_date is None:
        return None
    end_date = parse_date(end) or date.today()
    return (end_date - start_date).days / DAYS_IN_MONTH


def norm_for_name(name: str) -> Optional[float]:
    """Норма из справочника config по названию оборудования, лет.

    Сопоставление по вхождению: ищется и полное совпадение, и вхождение
    ключа в название, и наоборот — названия в базе пишут по-разному
    («Редукционная», «Редукционная (РСГ)», «Фильтр тонкой очистки»).
    """
    text = (name or '').strip()
    if not text:
        return None
    for key, years in EQUIPMENT_NORMS.items():
        if key in text or text in key:
            return float(years)
    return None


def norm_source_for_name(name: str) -> Optional[str]:
    """Человекочитаемый источник нормы по названию, для трассировки."""
    if norm_for_name(name) is None:
        return None
    return 'справочник config'


def default_norm() -> float:
    """Норма, когда в базе и справочнике ничего нет: срок полной проверки."""
    return FULL_CHECK_TERM


def part_remaining(part_install: DateLike, equip_install: DateLike,
                   norm_years, today: DateLike = None) -> Optional[float]:
    """Остаток ресурса одной детали, лет.

    Считается от даты установки самой детали (последней замены), а если она
    не задана — от даты установки оборудования. Если нет ни одной даты,
    остаток неизвестен и возвращается None.
    """
    start = parse_date(part_install) or parse_date(equip_install)
    if start is None:
        return None
    return remaining_years(start, norm_years, today)


def driving_parts_remaining(parts, today: DateLike = None):
    """Остатки по заменяемым деталям → минимум (слабое звено).

    parts — строки БД из get_equipment_parts_full: кортежи с полями
    (eq_part_id, part_id, name, norm, install_date, removal_date, part_number,
    is_replaceable). Список остатков активных заменяемых деталей; пустой
    список означает, что срока у оборудования нет.
    """
    remaining = []
    for row in parts or ():
        row = list(row) + [None] * 8
        _eq_part_id, _part_id, _name, norm, install, removal, _number, repl = row[:8]
        if removal or not repl:
            continue
        value = remaining_years(install, norm, today)
        if value is not None:
            remaining.append(value)
    return remaining


def is_replaceable(norm_years) -> bool:
    """Заменяемая ли деталь: норма ровно заменяемой (5 лет).

    Признак в базе мог потеряться, а норма остаться верной, поэтому деталь
    определяется и по тому, и по другому.
    """
    try:
        return abs(float(norm_years) - part_norm(True)) < 1e-9
    except (TypeError, ValueError):
        return False