"""Ручные поправки K: ввод от 0 до 1 и приоритет над формулой методики.

K сост методика считает по строкам технического диагностирования
(`tests/test_k_state_protocol.py`), а K эксл посчитать нечем: режимной карты
в базе нет, поэтому он всегда 1. Оба коэффициента можно ввести в окне
«Алгоритмы» — введённое значение должно попасть в расчёт вместо формулы и
быть помечено как ручное, а значение вне 0…1 приниматься не должно.

Тесты не требуют ни базы, ни окна Tkinter: проверяются чистая функция разбора
и расчёт коэффициентов на датаклассах.

Запуск: py -m unittest discover -s tests -q
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from logic.algorithms import (  # noqa: E402
    AlgorithmParams,
    ElementResult,
    GRPResourceCalculator,
)
from ui.algorithms_view import parse_coefficient  # noqa: E402


class ParseCoefficientTests(unittest.TestCase):
    """Поле коэффициента: 0…1, пусто — считать по формуле."""

    def test_empty_means_formula(self):
        self.assertEqual(parse_coefficient('', 'K эксл'), (None, ''))
        self.assertEqual(parse_coefficient('   ', 'K эксл'), (None, ''))

    def test_comma_and_dot_are_both_understood(self):
        self.assertEqual(parse_coefficient('0,85', 'K эксл'), (0.85, ''))
        self.assertEqual(parse_coefficient('0.85', 'K эксл'), (0.85, ''))

    def test_bounds_are_inclusive(self):
        self.assertEqual(parse_coefficient('0', 'K эксл'), (0.0, ''))
        self.assertEqual(parse_coefficient('1', 'K эксл'), (1.0, ''))

    def test_value_above_range_is_rejected(self):
        value, error = parse_coefficient('1,4', 'K эксл')
        self.assertIsNone(value)
        self.assertIn('0…1', error)

    def test_negative_value_is_rejected(self):
        value, error = parse_coefficient('-0,1', 'K сост')
        self.assertIsNone(value)
        self.assertIn('0…1', error)

    def test_not_a_number_is_rejected(self):
        value, error = parse_coefficient('abc', 'K рем')
        self.assertIsNone(value)
        self.assertIn('K рем', error)

    def test_empty_weight_is_an_error(self):
        """У веса пустое поле — ошибка: иначе прежнее значение осталось бы молча."""
        value, error = parse_coefficient('', 'θ · условия', allow_empty=False)
        self.assertIsNone(value)
        self.assertIn('θ · условия', error)

    def test_upper_bound_none_means_strictly_greater(self):
        """T макс измеряется годами, а не долями: ноль недопустим."""
        self.assertEqual(parse_coefficient('5', 'T_макс', lo=0.0, hi=None),
                         (5.0, ''))
        value, error = parse_coefficient('0', 'T_макс', lo=0.0, hi=None)
        self.assertIsNone(value)
        self.assertIn('больше 0', error)


class ManualCoefficientTests(unittest.TestCase):
    """Заполненный K идёт в расчёт вместо формулы и помечается ручным."""

    def _calculate(self, params, equip=None):
        calculator = GRPResourceCalculator(None, params)
        element = ElementResult(name='Регулятор давления')
        calculator._calc_coefficients(element, equip or {})
        return element

    def test_manual_k_cond_replaces_formula(self):
        element = self._calculate(AlgorithmParams(k_cond_manual=0.42))
        self.assertAlmostEqual(element.k_cond, 0.42)
        self.assertIn('вручную', element.k_cond_note)
        self.assertIn('K_эксл', element.k_manual)

    def test_formula_is_used_when_the_field_is_empty(self):
        element = self._calculate(AlgorithmParams())
        self.assertAlmostEqual(element.k_cond, 1.0)
        self.assertIn('режимная карта отсутствует', element.k_cond_note)
        self.assertEqual(element.k_manual, [])

    def test_manual_values_are_clamped_to_the_range(self):
        """Защита на случай параметров, пришедших не из окна расчёта."""
        element = self._calculate(AlgorithmParams(k_state_manual=1.7,
                                                 k_fail_manual=-0.5))
        self.assertAlmostEqual(element.k_state, 1.0)
        self.assertAlmostEqual(element.k_fail, 0.0)

    def test_manual_k_state_keeps_the_protocol_details(self):
        """Ручной K заменяет число, но разбор протокола остаётся видимым."""
        equip = {'state_params': [{'name': 'Давление', 'nominal': 10.0,
                                   'actual': 12.0, 'tol_max': 11.0}]}
        element = self._calculate(AlgorithmParams(k_state_manual=0.5), equip)
        self.assertAlmostEqual(element.k_state, 0.5)
        self.assertEqual(len(element.k_state_detail), 1)
        self.assertFalse(element.k_state_detail[0].get('skip'))

    def test_all_four_corrections_can_be_set_at_once(self):
        params = AlgorithmParams(k_state_manual=0.9, k_cond_manual=0.8,
                                 k_repair_manual=0.7, k_fail_manual=0.6)
        element = self._calculate(params)
        self.assertEqual(element.k_manual,
                         ['K_сост', 'K_эксл', 'K_рем', 'k_повр'])
        self.assertAlmostEqual(element.k_repair, 0.7)
        self.assertAlmostEqual(element.k_fail, 0.6)

    def test_manual_values_are_listed_for_the_report(self):
        listed = AlgorithmParams(k_cond_manual=0.85).manual_values()
        self.assertEqual(listed, [('K_эксл', 'K эксл (K усл)', 0.85)])


class AsRowsTests(unittest.TestCase):
    """Таблица принятых коэффициентов: ручные K видны только когда заданы."""

    def test_no_manual_rows_by_default(self):
        rows = AlgorithmParams().as_rows()
        self.assertEqual(len(rows), 6)
        self.assertFalse(any('вручную' in row[0] for row in rows))

    def test_weight_ranges_are_zero_to_one(self):
        for row in AlgorithmParams().as_rows():
            expected = 'больше 0' if row[0].startswith('T_макс') else '0…1'
            self.assertEqual(row[2], expected, row[0])

    def test_manual_rows_carry_the_value_and_range(self):
        rows = AlgorithmParams(k_cond_manual=0.85, k_fail_manual=0.9).as_rows()
        manual = [row for row in rows if 'вручную' in row[0]]
        self.assertEqual(len(manual), 2)
        self.assertEqual([row[2] for row in manual], ['0…1', '0…1'])
        self.assertTrue(any('K_эксл' in row[0] and '0,850' in row[1]
                            for row in manual))


if __name__ == '__main__':
    unittest.main()
