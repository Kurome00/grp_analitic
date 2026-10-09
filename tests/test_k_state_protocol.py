"""K сост элемента из строк технического диагностирования.

Вкладка «Техническое диагностирование» хранит строки протокола: оборудование,
проверяемый параметр, режим, границы допуска и факт (минимум и максимум).
Расчёт берёт K сост элемента именно оттуда: оборудование в протоколе
опознаётся тем же признаком, что и элемент (регулятор, ПЗК, ПСК, фильтр,
арматура), а каждое фактическое значение — отдельная проверка, потому что
протокол даёт и минимум, и максимум.

Отклонение считается от режима проверки и делится на полосу допуска
(допуск макс − допуск мин) — так же, как в расчётном файле паспорта ГРП-26:
строка регулятора «режим 2,3; допуск 2,185…2,415; факт 2,23416» даёт
|2,23416 − 2,3| / 0,23 = 0,28626, и K сост = 1 − 0,28626.

Тесты не требуют ни базы, ни окна Tkinter: проверяются разбор строк протокола
и расчёт коэффициента на датаклассах.

Запуск: py -m unittest discover -s tests -q
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import diagnostic_log  # noqa: E402
from logic.algorithms import (  # noqa: E402
    AlgorithmParams,
    ElementResult,
    GRPResourceCalculator,
)
from ui.algorithms_view import AlgorithmsWindow  # noqa: E402

REGULATOR = 'Регулятор давления газа РДБК-1М-50/35'


def check(**fields):
    """Строка проверки как из базы: незаполненные графы — пустые."""
    values = {key: '' for key in diagnostic_log.FIELDS}
    values.update(fields)
    return diagnostic_log.form_values(values)


def params_for(equipment, *checks):
    """Проверки элемента — так их готовит окно расчёта."""
    return AlgorithmsWindow._load_state_params(
        None, {'name': equipment}, [check(**fields) for fields in checks])


def k_state(state_params):
    """K сост по проверкам — тем же путём, что и в расчёте."""
    calculator = GRPResourceCalculator(None, AlgorithmParams())
    element = ElementResult(name=REGULATOR)
    calculator._calc_coefficients(element, {'state_params': state_params})
    return element


class StateParamTests(unittest.TestCase):
    """Строки протокола → проверки элемента."""

    def test_one_row_gives_two_checks(self):
        """Протокол даёт факт минимума и факт максимума — это две проверки."""
        params = params_for(REGULATOR, dict(
            check_date='2026-05-21', equipment='Регулятор',
            parameter='Точность регулирования при фактическом расходе',
            mode='2,3', tolerance_min='2,185', tolerance_max='2,415',
            fact_min='2,23416', fact_max='2,25895'))
        self.assertEqual(len(params), 2)
        self.assertEqual([p['actual'] for p in params], [2.23416, 2.25895])
        self.assertEqual([p['nominal'] for p in params], [2.3, 2.3])
        self.assertEqual([p['tol_min'] for p in params], [2.185, 2.185])
        self.assertEqual([p['tol_max'] for p in params], [2.415, 2.415])
        self.assertIn('21.05.2026', params[0]['name'])
        self.assertIn('(мин)', params[0]['name'])
        self.assertIn('(макс)', params[1]['name'])

    def test_equipment_is_matched_by_element_kind(self):
        """Регулятору — только его строки, ПЗК и ПСК не смешиваются."""
        common = dict(check_date='2025-11-25', mode='3,75',
                      tolerance_min='3,58125', tolerance_max='3,91875',
                      fact_min='3,73278')
        regulator = params_for(REGULATOR, dict(
            equipment='Регулятор', parameter='Точность регулирования',
            fact_max='2,4', **common))
        self.assertEqual(len(regulator), 2)

        pzk = params_for('Клапан предохранительный запорный ПКН-50', dict(
            equipment='ПЗК', parameter='Точность срабатывания', **common))
        self.assertEqual(len(pzk), 1)

        # ПСК ГП-50 — это сбросной клапан, строки ПЗК ему не подходят.
        psk = params_for('Клапан предохранительный сбросной ПСК ГП-50',
                         dict(equipment='ПЗК',
                              parameter='Точность срабатывания', **common))
        self.assertEqual(psk, [])

    def test_row_without_numbers_gives_nothing(self):
        """«Герметичность» проверяется словами — чисел для K сост нет."""
        params = params_for('Клапан предохранительный сбросной ПСК ГП-50',
                            dict(equipment='ПСК', parameter='Герметичность ПСК'))
        self.assertEqual(params, [])

    def test_element_without_critical_kind_is_skipped(self):
        """Газопровод не критический элемент — проверки ему не нужны."""
        params = params_for('Выходной газопровод Ду150', dict(
            equipment='Объект (выход)', parameter='Выходное давление',
            mode='2,3', tolerance_min='2,07', tolerance_max='2,53',
            fact_min='2,2011'))
        self.assertEqual(params, [])


class ProtocolKStateTests(unittest.TestCase):
    """K сост = 1 − (1/n)·Σ |факт − режим| / полоса допуска."""

    def test_passport_row_gives_the_passport_deviation(self):
        """Строка регулятора из протокола №143 — 0,28626, как в паспорте."""
        element = k_state(params_for(REGULATOR, dict(
            check_date='2024-05-27', equipment='Регулятор',
            parameter='Точность регулирования при фактическом расходе',
            mode='2,3', tolerance_min='2,185', tolerance_max='2,415',
            fact_min='2,23416')))
        self.assertEqual(len(element.k_state_detail), 1)
        self.assertAlmostEqual(element.k_state_detail[0]['ratio'], 0.28626,
                               places=5)
        self.assertAlmostEqual(element.k_state, 0.71374, places=5)

    def test_denominator_is_the_whole_tolerance_band(self):
        """Отклонение делится на полосу допуска, а не на её половину."""
        element = k_state([{'name': 'Режим', 'nominal': 2.3, 'actual': 2.4,
                            'tol_min': 2.2, 'tol_max': 2.4}])
        # |2,4 − 2,3| / 0,2 = 0,5, а не |2,4 − 2,3| / 0,1 = 1.
        self.assertAlmostEqual(element.k_state, 0.5)

    def test_checks_of_the_element_are_averaged(self):
        """Среднее по всем проверкам элемента, включая минимум и максимум."""
        element = k_state(params_for(REGULATOR, dict(
            check_date='2026-05-21', equipment='Регулятор',
            parameter='Точность регулирования при фактическом расходе',
            mode='2,3', tolerance_min='2,185', tolerance_max='2,415',
            fact_min='2,23416', fact_max='2,25895')))
        self.assertEqual(len(element.k_state_detail), 2)
        self.assertAlmostEqual(element.k_state,
                               1 - (0.2862609 + 0.1784783) / 2, places=5)
        self.assertIn('n = 2', element.k_state_note)

    def test_row_without_mode_is_marked_as_unfit(self):
        """Без режима отклонение не от чего считать — проверка пропущена."""
        element = k_state(params_for('Клапан предохранительный сбросной ПСК ГП-50',
                                     dict(
            check_date='2026-05-21', equipment='ПСК',
            parameter='Давление закрытия ПСК',
            tolerance_min='3,0855', fact_min='3,24804')))
        self.assertEqual(len(element.k_state_detail), 1)
        self.assertTrue(element.k_state_detail[0]['skip'])
        self.assertAlmostEqual(element.k_state, 1.0)
        self.assertIn('протокол диагностики отсутствует', element.k_state_note)

    def test_single_bound_keeps_the_distance_from_the_mode(self):
        """Задана одна граница допуска — делителем служит расстояние до неё."""
        element = k_state([{'name': 'Давление', 'nominal': 10.0,
                            'actual': 12.0, 'tol_max': 11.0}])
        self.assertAlmostEqual(element.k_state, 0.0)

    def test_no_checks_means_one(self):
        element = k_state([])
        self.assertAlmostEqual(element.k_state, 1.0)
        self.assertIn('протокол диагностики отсутствует', element.k_state_note)


if __name__ == '__main__':
    unittest.main()
