"""Тесты единой арифметики сроков (core/lifetimes.py).

Задача тестов — не пересчитать формулы, а зафиксировать инварианты, на
которые опирается остальное приложение:

* год везде один и тот же (365.25), независимо от того, откуда пришла дата;
* неизвестная дата даёт 0.0 для возраста и None для остатка — вызывающий
  сам решает, как это показывать, но никогда не получает исключение;
* отрицательный остаток означает просрочку и не зажимается в ноль;
* детали без даты установки наследуют дату оборудования.

Запуск: py -m unittest discover -s tests -v
"""

import os
import sys
import unittest
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.lifetimes import (  # noqa: E402
    DAYS_IN_MONTH,
    DAYS_IN_YEAR,
    add_years,
    age_years,
    default_norm,
    driving_parts_remaining,
    is_replaceable,
    lifetime_months,
    norm_for_name,
    norm_source_for_name,
    parse_date,
    part_remaining,
    remaining_years,
    years_between,
)


class ParseDateTests(unittest.TestCase):
    def test_iso(self):
        self.assertEqual(parse_date('2020-03-05'), date(2020, 3, 5))

    def test_russian_format(self):
        self.assertEqual(parse_date('05.03.2020'), date(2020, 3, 5))

    def test_short_two_digit_year(self):
        self.assertEqual(parse_date('05.03.20'), date(2020, 3, 5))

    def test_datetime_with_time_is_truncated(self):
        self.assertEqual(parse_date('2020-03-05 14:30:00'), date(2020, 3, 5))

    def test_date_and_datetime_objects_pass_through(self):
        self.assertEqual(parse_date(date(2020, 3, 5)), date(2020, 3, 5))
        self.assertEqual(parse_date(datetime(2020, 3, 5, 14, 30)), date(2020, 3, 5))

    def test_garbage_returns_none(self):
        self.assertIsNone(parse_date('мусор'))
        self.assertIsNone(parse_date(''))
        self.assertIsNone(parse_date(None))
        self.assertIsNone(parse_date('   '))

    def test_every_ui_format_parses_identically(self):
        """Дата, введённая в UI и в БД, — одна и та же."""
        canonical = date(2021, 7, 14)
        for text in ('2021-07-14', '14.07.2021', '2021-07-14 00:00:00'):
            self.assertEqual(parse_date(text), canonical)


class YearsBetweenTests(unittest.TestCase):
    def test_uses_single_year_definition(self):
        delta = date(2020, 1, 1), date(2025, 1, 1)
        expected = (delta[1] - delta[0]).days / DAYS_IN_YEAR
        self.assertAlmostEqual(years_between(*delta), expected)

    def test_known_value(self):
        # 2020 — високосный, до 2021-01-01 проходит 366 дней.
        value = years_between('2020-01-01', '2021-01-01')
        self.assertAlmostEqual(value, 366 / DAYS_IN_YEAR, places=6)
        # год без 29 февраля — чуть меньше календарного года
        self.assertAlmostEqual(years_between('2021-01-01', '2022-01-01'),
                               365 / DAYS_IN_YEAR, places=6)

    def test_missing_start_returns_none(self):
        self.assertIsNone(years_between(None))
        self.assertIsNone(years_between(''))

    def test_end_defaults_to_today(self):
        expected = (date.today() - date(2020, 1, 1)).days / DAYS_IN_YEAR
        self.assertAlmostEqual(years_between('2020-01-01'), expected)

    def test_negative_span_is_negative(self):
        self.assertLess(years_between('2025-01-01', '2020-01-01'), 0)


class AgeYearsTests(unittest.TestCase):
    def test_missing_date_is_zero_not_exception(self):
        self.assertEqual(age_years(None), 0.0)
        self.assertEqual(age_years('мусор'), 0.0)

    def test_matches_years_between(self):
        self.assertEqual(age_years('2020-01-01', '2024-01-01'),
                         years_between('2020-01-01', '2024-01-01'))


class RemainingYearsTests(unittest.TestCase):
    def test_positive_remainder(self):
        # 2023-01-01 → 2024-01-01 = 365 дней, из нормы 5 лет остаётся ~4 года.
        value = remaining_years('2023-01-01', 5.0, today='2024-01-01')
        self.assertAlmostEqual(value, 5.0 - (365 / DAYS_IN_YEAR), places=6)

    def test_overdue_stays_negative(self):
        value = remaining_years('2015-01-01', 5.0, today='2024-01-01')
        self.assertLess(value, 0)

    def test_no_date_is_unknown_remainder(self):
        self.assertIsNone(remaining_years(None, 5.0))

    def test_bad_norm_is_unknown_remainder(self):
        self.assertIsNone(remaining_years('2020-01-01', None))
        self.assertIsNone(remaining_years('2020-01-01', 'не число'))


class ExpiryTests(unittest.TestCase):
    def test_add_years_lands_on_expected_day(self):
        # Срок считается в днях (год = 365.25), поэтому дата может уехать на
        # день: округление округляет дробь дней. Год — 5 лет ± 1 день.
        start = '2020-06-01'
        expiry = add_years(start, 5.0)
        self.assertAlmostEqual(years_between(start, expiry), 5.0, places=2)

    def test_missing_start_gives_no_expiry(self):
        self.assertIsNone(add_years(None, 5.0))


class MonthsTests(unittest.TestCase):
    def test_calendar_month_year_is_close_to_twelve(self):
        value = lifetime_months('2020-01-01', '2021-01-01')
        self.assertAlmostEqual(value, 366 / DAYS_IN_MONTH, places=6)

    def test_missing_start_is_none(self):
        self.assertIsNone(lifetime_months(None))

    def test_end_defaults_to_today(self):
        expected = (date.today() - date(2020, 1, 1)).days / DAYS_IN_MONTH
        self.assertAlmostEqual(lifetime_months('2020-01-01'), expected)


class NormLookupTests(unittest.TestCase):
    def test_exact_name(self):
        self.assertEqual(norm_for_name('Редукционная'), 20.0)

    def test_name_with_suffix(self):
        self.assertEqual(norm_for_name('Редукционная (РСГ)'), norm_for_name('Редукционная'))

    def test_known_prefix_is_found(self):
        """'Фильтр тонкой очистки' не совпадает ни с одним ключом целиком."""
        self.assertIsNone(norm_for_name('Скважина №7'))
        self.assertEqual(norm_for_name('Фильтр тонкой очистки'), 20.0)

    def test_empty_name(self):
        self.assertIsNone(norm_for_name(''))
        self.assertIsNone(norm_for_name(None))

    def test_source_label(self):
        self.assertEqual(norm_source_for_name('Редукционная'), 'справочник config')
        self.assertIsNone(norm_source_for_name('Скважина №7'))

    def test_default_norm_is_positive(self):
        self.assertGreater(default_norm(), 0)


class ReplaceableTests(unittest.TestCase):
    def test_five_years_is_replaceable(self):
        self.assertTrue(is_replaceable(5.0))
        self.assertTrue(is_replaceable('5'))

    def test_other_norm_is_not_replaceable(self):
        self.assertFalse(is_replaceable(20.0))
        self.assertFalse(is_replaceable(None))


class PartRemainingTests(unittest.TestCase):
    """Деталь без своей даты установки наследует дату оборудования."""

    def test_part_date_wins(self):
        value = part_remaining('2023-01-01', '2010-01-01', 5.0, today='2024-01-01')
        expected = 5.0 - years_between('2023-01-01', '2024-01-01')
        self.assertAlmostEqual(value, expected)

    def test_falls_back_to_equipment_date(self):
        value = part_remaining(None, '2023-01-01', 5.0, today='2024-01-01')
        expected = 5.0 - years_between('2023-01-01', '2024-01-01')
        self.assertAlmostEqual(value, expected)

    def test_no_dates_at_all_is_unknown(self):
        self.assertIsNone(part_remaining(None, None, 5.0))


class DrivingPartsTests(unittest.TestCase):
    """Остаток оборудования = минимум по активным заменяемым деталям."""

    def _part(self, norm, install, removal=None, replaceable=True):
        return (1, 1, 'Деталь', norm, install, removal, 'PN-1', replaceable)

    def test_minimum_wins(self):
        parts = [self._part(5.0, '2023-01-01'), self._part(5.0, '2018-01-01')]
        self.assertAlmostEqual(min(driving_parts_remaining(parts)),
                               remaining_years('2018-01-01', 5.0))

    def test_removed_parts_are_ignored(self):
        parts = [self._part(5.0, '2018-01-01', removal='2020-01-01'),
                 self._part(5.0, '2023-01-01')]
        self.assertAlmostEqual(min(driving_parts_remaining(parts)),
                               remaining_years('2023-01-01', 5.0))

    def test_non_replaceable_parts_are_ignored(self):
        parts = [self._part(20.0, '2000-01-01', replaceable=False),
                 self._part(5.0, '2023-01-01')]
        self.assertAlmostEqual(min(driving_parts_remaining(parts)),
                               remaining_years('2023-01-01', 5.0))

    def test_short_rows_do_not_crash(self):
        """Неполная строка из БД не должна ронять расчёт."""
        self.assertEqual(driving_parts_remaining([(1, 1, 'Деталь', 5.0)]), [])

    def test_no_parts_is_empty(self):
        self.assertEqual(driving_parts_remaining([]), [])
        self.assertEqual(driving_parts_remaining(None), [])


class ConsistencyTests(unittest.TestCase):
    """Главная проверка: расчёт в ядре, UI и отчёте сходится."""

    def test_ui_and_calculator_agree_on_remainder(self):
        from logic.algorithms import GRPResourceCalculator

        start = '2023-06-01'
        calc = GRPResourceCalculator()
        self.assertAlmostEqual(calc._age(start), age_years(start))
        self.assertAlmostEqual(calc._age(start), years_between(start))

    def test_documentary_analyzer_shares_parse_date(self):
        from core.lifetimes import parse_date as canonical
        from logic.documentary_analyzer import DocumentaryAnalyzer

        self.assertIs(DocumentaryAnalyzer._parse_date, canonical)

    def test_equipment_model_uses_shared_months(self):
        from core.models import Equipment

        eq = Equipment(name='Редукционная', install_date='2020-01-01', removal_date='2021-01-01')
        self.assertAlmostEqual(eq.lifetime_months, lifetime_months('2020-01-01', '2021-01-01'))

    def test_equipment_model_tolerates_russian_date(self):
        from core.models import Equipment

        a = Equipment(name='X', install_date='2020-01-01', removal_date='2021-01-01')
        b = Equipment(name='X', install_date='01.01.2020', removal_date='01.01.2021')
        self.assertAlmostEqual(a.lifetime_months, b.lifetime_months)


if __name__ == '__main__':
    unittest.main()
