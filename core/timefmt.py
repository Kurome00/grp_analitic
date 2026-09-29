"""Форматирование длительностей (лет ⇄ годы + месяцы + недели + дни)."""

from typing import Optional


def _plural(n: int, one: str, few: str, many: str) -> str:
    n10 = n % 10
    n100 = n % 100
    if n10 == 1 and n100 != 11:
        return one
    if 2 <= n10 <= 4 and not (12 <= n100 <= 14):
        return few
    return many


def years_to_text(years: Optional[float], months_abbr: str = "мес",
                  weeks_abbr: str = "нед", days_abbr: str = "дн") -> str:
    """Длительность в годах → текст «1 год 9 мес», «5 мес 4 нед 2 дн», «3 дн».

    От года и выше выводятся годы и месяцы. Если остаток меньше года, дробная
    часть года не теряется, а разворачивается в месяцы, недели и дни: остаток
    0.09 года показывается как «1 мес 2 дн», а не округляется до «1 мес» и не
    выглядит как «0.1».
    Отрицательные значения — со знаком «−».
    """
    if years is None:
        return "—"
    try:
        years = float(years)
    except (TypeError, ValueError):
        return "—"

    if years != years:  # NaN
        return "—"

    sign = "−" if years < 0 else ""

    # От года и выше — годы и месяцы, как раньше: месяц округляется от года.
    if abs(years) >= 1:
        total_months = round(abs(years) * 12)
        full_years, months = divmod(total_months, 12)
        parts = [f"{full_years} {_plural(full_years, 'год', 'года', 'лет')}"]
        if months:
            parts.append(f"{months} {months_abbr}")
        return sign + " ".join(parts)

    # Меньше года: месяцы + недели + дни, чтобы дробная часть года не терялась.
    total_days = abs(years) * 365.25
    months = int(total_days // 30.44)
    rest = total_days - months * 30.44
    weeks = int(rest // 7)
    days = int(round(rest - weeks * 7))
    if days >= 7:  # округление могло выдать 7
        days = 0
        weeks += 1

    parts = []
    if months:
        parts.append(f"{months} {months_abbr}")
    if weeks:
        parts.append(f"{weeks} {weeks_abbr}")
    parts.append(f"{days} {days_abbr}")
    return sign + " ".join(parts)
