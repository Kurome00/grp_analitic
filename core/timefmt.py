"""Форматирование и разбор длительностей (годы ⇄ годы + месяцы + недели + дни).

Правило проекта: срок НИКОГДА не пишется десятичной дробью («7,30 лет»).
Длительность показывается словами: «7 лет 4 мес», «3 мес 2 нед», «5 дн».
В том же виде срок принимается обратно в поля ввода (см. parse_years).

Здесь же — название месяца для дат: в отчётности дату указывают месяцем
(«январь 2027»), а не числом.
"""

import re
from typing import Optional

MONTHS_IN_YEAR = 12.0
DAYS_IN_MONTH = 30.44
DAYS_IN_WEEK = 7.0

# Названия месяцев в именительном падеже: по номеру месяца 1…12.
MONTH_NAMES_RU = ('январь', 'февраль', 'март', 'апрель', 'май', 'июнь',
                  'июль', 'август', 'сентябрь', 'октябрь', 'ноябрь', 'декабрь')

# Слова месяцев в любом написании (год/года/лет, месяц/мес, неделя/нед, день/дн).
_UNIT_ALIASES = {
    'год': 'y', 'года': 'y', 'лет': 'y', 'г': 'y', 'л': 'y', 'годов': 'y',
    'месяц': 'm', 'месяца': 'm', 'мес': 'm', 'мес.': 'm', 'м': 'm',
    'неделя': 'w', 'недели': 'w', 'недель': 'w', 'нед': 'w', 'нед.': 'w', 'н': 'w',
    'день': 'd', 'дня': 'd', 'дней': 'd', 'дн': 'd', 'дн.': 'd', 'сут': 'd', 'д': 'd',
}

_UNIT_ORDER = {'y': 0, 'm': 1, 'w': 2, 'd': 3}

_TERM_RE = re.compile(
    r'(?P<value>[-−+]?\d+(?:[.,]\d+)?)\s*(?P<unit>[а-яa-z.]*)',
    re.IGNORECASE,
)


class DurationError(ValueError):
    """Некорректный ввод длительности."""


def _plural(n: int, one: str, few: str, many: str) -> str:
    n10 = n % 10
    n100 = n % 100
    if n10 == 1 and n100 != 11:
        return one
    if 2 <= n10 <= 4 and not (12 <= n100 <= 14):
        return few
    return many


def _to_float(value) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result:  # NaN
        return None
    return result


def years_to_text(years: Optional[float], months_abbr: str = "мес",
                  weeks_abbr: str = "нед", days_abbr: str = "дн",
                  zero_text: str = "0 дн") -> str:
    """Длительность в годах → текст «7 лет 4 мес», «5 мес 2 нед 3 дн», «2 дн».

    От года и выше выводятся годы и месяцы (месяц округляется от года).
    Если остаток меньше года, дробная часть года не теряется, а разворачивается
    в месяцы, недели и дни: остаток 0,09 года показывается как «1 мес 2 дн»,
    а не округляется до «1 мес» и не выглядит как «0,09».
    Нулевые компоненты не выводятся: «6 мес», а не «6 мес 0 дн».
    Отрицательные значения — со знаком «−».
    """
    value = _to_float(years)
    if value is None:
        return "—"

    sign = "−" if value < 0 else ""
    value = abs(value)

    if value == 0:
        return zero_text

    # От года и выше — годы и месяцы, как принято в отчётности.
    if value >= 1:
        total_months = int(value * MONTHS_IN_YEAR + 0.5)
        full_years, months = divmod(total_months, 12)
        parts = [f"{full_years} {_plural(full_years, 'год', 'года', 'лет')}"]
        if months:
            parts.append(f"{months} {months_abbr}")
        return sign + " ".join(parts)

    # Меньше года: месяцы + недели + дни, чтобы дробная часть года не терялась.
    total_days = value * 365.25
    months = int(total_days // DAYS_IN_MONTH)
    rest = total_days - months * DAYS_IN_MONTH
    weeks = int(rest // DAYS_IN_WEEK)
    days = int(rest - weeks * DAYS_IN_WEEK + 0.5)
    if days >= 7:          # округление могло выдать 7
        days = 0
        weeks += 1
    if weeks >= 4:         # месяц вместо ровно четырёх недель
        months += 1
        weeks = 0

    parts = []
    if months:
        parts.append(f"{months} {months_abbr}")
    if weeks:
        parts.append(f"{weeks} {weeks_abbr}")
    if days or not parts:
        parts.append(f"{days} {days_abbr}")
    return sign + " ".join(parts)


def month_year_text(day) -> str:
    """Дата → «январь 2027»; None → «—».

    Месяц и год, без числа: так указывают срок следующего диагностирования.
    Функция нарочно не разбирает строки — на вход идёт уже готовая дата
    (например, из core.lifetimes.expiry_date).
    """
    if day is None:
        return '—'
    return f'{MONTH_NAMES_RU[day.month - 1]} {day.year}'


def _normalize_unit(raw: str) -> Optional[str]:
    unit = (raw or '').strip().lower().replace('ё', 'е')
    if not unit:
        return 'y'          # «7» — семь лет
    unit = unit.rstrip('.')
    return _UNIT_ALIASES.get(unit)


def parse_years(text) -> Optional[float]:
    """Разбор длительности из строки ввода → годы (float) или None.

    Принимает:
      «7,30», «7.30», «7»            — десятичное число лет;
      «7 лет 4 мес», «7г4м», «7 лет» — словами;
      «84 мес», «2 нед 3 дн»          — единицами мельче года;
      «−2 года 3 мес», «-2 года»      — отрицательные значения.
    Пустая строка и None → None. Нераспознанный ввод → None.
    """
    if text is None:
        return None
    if isinstance(text, (int, float)) and not isinstance(text, bool):
        return _to_float(text)

    raw = str(text).strip().replace(' ', ' ').replace(',', '.')
    if not raw:
        return None
    raw = raw.replace('−', '-')

    match = _TERM_RE.search(raw)
    if not match:
        return None

    # Весь текст должен описывать длительность: «7 лет 4 мес», а не «7 лет 15 штук».
    leftovers = _TERM_RE.sub(' ', raw).strip(' .,+')
    if leftovers:
        return None

    years = 0.0
    found = False
    for term in _TERM_RE.finditer(raw):
        value = float(term.group('value'))
        unit = _normalize_unit(term.group('unit'))
        if unit is None:
            return None
        years += {'y': 1.0, 'm': 1.0 / MONTHS_IN_YEAR,
                  'w': 1.0 / (MONTHS_IN_YEAR * 4.3452381),
                  'd': 1.0 / 365.25}[unit] * value
        found = True
    return years if found else None


def parse_years_strict(text, field_name: str = "срок") -> float:
    """parse_years, но с понятной ошибкой вместо молчаливого None."""
    if text is None or not str(text).strip():
        raise DurationError(f"Не указан {field_name}.")
    value = parse_years(text)
    if value is None:
        raise DurationError(
            f"Не удалось разобрать {field_name}: «{str(text).strip()}».\n"
            "Правильно: «7,30» либо «7 лет 4 мес» (можно «7л4м», «84 мес»).")
    return value
