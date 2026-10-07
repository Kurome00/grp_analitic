"""Продление срока: шаг — замена запчастей, а не оборудования.

Карточка «Продление срока» показывает, что даст ползунок цели. Шаг там —
замена **запчасти** слабого звена: прирост в строке посчитан по замене ровно
названных запчастей (раньше шаг считался заменой всего узла, а называлась одна
запчасть — обещанное и посчитанное расходились). Тесты фиксируют:

* шаг называет запчасть и её оборудование, и прирост шага равен приросту от
  замены ровно этой запчасти — и меньше, чем от замены узла целиком;
* у одного узла может быть несколько шагов — по числу изношенных запчастей;
* просроченный элемент добирается несколькими запчастями за один шаг, поэтому
  строк «+0 лет» в лестнице нет;
* методика, считающая ресурс не по запчастям (заданный Z_база), и элемент без
  учитываемых запчастей дают шаг «менять нечего», а не пустую таблицу;
* предел шагов следует за числом запчастей и не обрезает лестницу раньше цели;
* пересчёт не портит payload: лестница строится по копии.

Тесты не требуют базы, Tkinter и записи файлов: payload собирается вручную и
считается настоящим GRPResourceCalculator — тем же движком, что и в окне.

Запуск: py -m unittest discover -s tests -v
"""

import copy
import os
import sys
import unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from logic.algorithms import (  # noqa: E402
    AlgorithmParams,
    AlgorithmResult,
    GRPResourceCalculator,
)
from ui.algorithms_view import (  # noqa: E402
    EXTENSION_STEPS,
    EXTENSION_STEPS_MAX,
    _parts_text,
    _step_head_text,
    build_extension_ladder,
    counted_part_keys,
    extension_step_limit,
    simulate_with_renewed,
)

PARAMS = AlgorithmParams()

# Внутренний номер методики: в окне расчёта он показан как «Алгоритм 4».
NUMBER = 3

REGULATOR = 'Регулятор РДБК-1М-50/35'
PZK = 'ПЗК КПН-50'

MEMBRANE = 'Мембрана регулятора'
GASKET = 'Прокладка корпуса'
SPRING = 'Пружина ПЗК'


def _ago(years):
    """Дата установки «years» лет назад — в тех же днях, что считает core.lifetimes."""
    return (date.today() - timedelta(days=round(years * 365.25))).isoformat()


def _part(name, norm, years_ago):
    """Заменяемая запчасть: норма срока и своя дата установки."""
    return {'name': name, 'norm_years': norm, 'install_date': _ago(years_ago),
            'is_replaceable': True}


def _unit(equipment_id, name, parts, **extra):
    """Единица оборудования с активными запчастями."""
    unit = {'equipment_id': equipment_id, 'name': name,
            'install_date': _ago(25), 'details': list(parts)}
    unit.update(extra)
    return unit


def _calc(payload, number=NUMBER):
    return getattr(GRPResourceCalculator(None, PARAMS),
                   f'calculate_algorithm_{number}')(payload)


def _term(payload, renewed=(), number=NUMBER):
    """Срок ГРП, если названные запчасти заменены сегодня."""
    if not renewed:
        return _calc(payload, number).result
    return simulate_with_renewed(number, payload, PARAMS, None, renewed).result


def _ladder(payload, number=NUMBER):
    return build_extension_ladder(number, payload, PARAMS, None,
                                  _calc(payload, number))


def _names(step):
    return [part['name'] for part in step['parts']]


class StepTests(unittest.TestCase):
    """Шаг продления — замена запчасти у слабого звена."""

    def setUp(self):
        # У регулятора изношена мембрана, прокладка ещё держится; ПЗК слабее
        # прокладки, но не мембраны — поэтому узлы меняются вперемешку.
        self.payload = [
            _unit(1, REGULATOR, [_part(MEMBRANE, 5.0, 4.0),
                                 _part(GASKET, 5.0, 0.5)]),
            _unit(2, PZK, [_part(SPRING, 5.0, 1.0)]),
        ]
        self.steps = _ladder(self.payload)
        self.first = self.steps[0]

    def test_step_replaces_a_part_not_the_unit(self):
        self.assertEqual(_names(self.first), [MEMBRANE])
        self.assertNotIn(GASKET, _names(self.first))

    def test_step_names_the_part_and_its_unit(self):
        self.assertEqual(self.first['element'].name, REGULATOR)
        text = _step_head_text(self.first)
        self.assertIn(MEMBRANE, text)
        self.assertIn('РДБК', text)
        self.assertTrue(text.startswith('замена запчасти '), text)

    def test_step_gain_is_the_gain_of_exactly_that_part(self):
        base = _term(self.payload)
        expected = _term(self.payload, {(1, MEMBRANE)}) - base
        self.assertAlmostEqual(self.first['gain'], expected, places=9)
        self.assertAlmostEqual(self.first['before'], base, places=9)
        self.assertAlmostEqual(self.first['after'], base + expected, places=9)

    def test_step_gain_is_less_than_replacing_the_whole_unit(self):
        """Замена узла целиком — не то же самое, что замена его запчасти."""
        payload = [
            _unit(1, REGULATOR, [_part(MEMBRANE, 5.0, 4.0),
                                 _part(GASKET, 5.0, 3.9)]),
            _unit(2, PZK, [_part(SPRING, 5.0, 0.1)]),
        ]
        base = _term(payload)
        one_part = _term(payload, {(1, MEMBRANE)}) - base
        whole_unit = _term(payload, {(1, MEMBRANE), (1, GASKET)}) - base
        self.assertGreater(whole_unit, one_part)
        self.assertAlmostEqual(_ladder(payload)[0]['gain'], one_part, places=9)

    def test_part_row_is_named_in_the_table(self):
        self.assertEqual(_parts_text(self.first['parts']), MEMBRANE)


class SeveralStepsTests(unittest.TestCase):
    """Запчастей у слабого звена несколько — каждый шаг отдельно."""

    def setUp(self):
        self.payload = [
            _unit(1, REGULATOR, [_part(MEMBRANE, 5.0, 4.0),
                                 _part(GASKET, 5.0, 0.5)]),
            _unit(2, PZK, [_part(SPRING, 5.0, 1.0)]),
        ]
        self.steps = _ladder(self.payload)

    def test_steps_go_from_one_worn_part_to_the_next(self):
        self.assertEqual([_names(step) for step in self.steps if step['parts']],
                         [[MEMBRANE], [SPRING], [GASKET]])

    def test_two_steps_happen_on_the_same_unit(self):
        """У одного узла две изношенные запчасти — и два шага по ним."""
        units = [step['element'].equipment_id for step in self.steps
                 if step['parts']]
        self.assertEqual(units.count(1), 2)

    def test_every_step_moves_the_term(self):
        for step in self.steps:
            if step['parts']:
                with self.subTest(_names(step)):
                    self.assertGreater(step['gain'], 0.0)

    def test_ladder_ends_when_nothing_is_left(self):
        last = self.steps[-1]
        self.assertTrue(last['stuck'])
        self.assertEqual(last['parts'], [])

    def test_steps_follow_each_other(self):
        for before, after in zip(self.steps, self.steps[1:]):
            self.assertAlmostEqual(after['before'], before['after'], places=9)


class OverdueUnitTests(unittest.TestCase):
    """Просроченный элемент: одна замена минимум не двигает."""

    def setUp(self):
        self.payload = [
            _unit(1, REGULATOR, [_part(MEMBRANE, 5.0, 6.0),
                                 _part(GASKET, 5.0, 6.1),
                                 _part('Седло клапана', 5.0, 6.2)]),
            _unit(2, PZK, [_part(SPRING, 5.0, 1.0)]),
        ]
        self.first = _ladder(self.payload)[0]

    def test_one_part_out_of_three_does_not_move_the_term(self):
        self.assertAlmostEqual(_term(self.payload, {(1, 'Седло клапана')}),
                               _term(self.payload), places=9)

    def test_step_collects_as_many_parts_as_needed(self):
        self.assertEqual(len(self.first['parts']), 3)
        self.assertGreater(self.first['gain'], 0.0)

    def test_no_zero_gain_rows_in_the_ladder(self):
        for step in _ladder(self.payload):
            if step['parts']:
                with self.subTest(_names(step)):
                    self.assertGreater(step['gain'], 0.0)


class NoPartsTests(unittest.TestCase):
    """Менять нечего: объясняется, а не показывается пустой таблицей."""

    def test_element_without_counted_parts(self):
        """Срок держит запчасть с нормой 20 лет — менять по расчёту нечего."""
        payload = [
            _unit(1, REGULATOR, [_part(MEMBRANE, 20.0, 19.0)]),
            _unit(2, PZK, [_part(SPRING, 5.0, 1.0)]),
        ]
        steps = _ladder(payload)
        self.assertEqual(len(steps), 1)
        first = steps[0]
        self.assertTrue(first['parts_ineffective'])
        self.assertTrue(first['weak_without_parts'])
        self.assertFalse(first['no_parts'])
        self.assertEqual(first['parts'], [])
        self.assertTrue(first['stuck'])
        self.assertEqual(first['element'].name, REGULATOR)

    def test_grp_without_counted_parts_at_all(self):
        payload = [_unit(1, REGULATOR, [_part(MEMBRANE, 20.0, 19.0)])]
        first = _ladder(payload)[0]
        self.assertTrue(first['no_parts'])
        self.assertFalse(first['weak_without_parts'])
        self.assertEqual(first['parts'], [])

    def test_explicit_base_resource_ignores_parts(self):
        """Готовый Z_база (вариант Б2): запчасть есть, но срок держит не она."""
        payload = [
            _unit(1, REGULATOR, [_part(MEMBRANE, 5.0, 4.0)],
                  z_base=1.0, z_base_source='экспертное заключение'),
            _unit(2, PZK, [_part(SPRING, 5.0, 1.0)]),
        ]
        first = _ladder(payload)[0]
        self.assertTrue(first['parts_ineffective'])
        self.assertFalse(first['weak_without_parts'])
        self.assertFalse(first['no_parts'])
        self.assertEqual(_names(first), [MEMBRANE])


class HelperTests(unittest.TestCase):
    """Предел шагов, отбор запчастей и неприкосновенность payload."""

    def test_counts_only_five_year_parts(self):
        payload = [_unit(1, REGULATOR, [_part(MEMBRANE, 5.0, 1.0),
                                        _part('Корпус', 20.0, 1.0),
                                        _part('Крепёж', None, 1.0)])]
        self.assertEqual(counted_part_keys(payload), {(1, MEMBRANE)})

    def test_limit_follows_the_number_of_parts(self):
        payload = [_unit(1, REGULATOR, [_part(f'Запчасть {i}', 5.0, 1.0)
                                        for i in range(3)])]
        self.assertGreaterEqual(extension_step_limit(payload),
                                len(counted_part_keys(payload)))
        self.assertGreaterEqual(extension_step_limit(payload), EXTENSION_STEPS)

    def test_limit_is_capped(self):
        many = EXTENSION_STEPS_MAX + 5
        payload = [_unit(1, REGULATOR, [_part(f'Запчасть {i}', 5.0, 1.0)
                                        for i in range(many)])]
        self.assertEqual(extension_step_limit(payload), EXTENSION_STEPS_MAX)

    def test_simulation_leaves_the_payload_alone(self):
        payload = [_unit(1, REGULATOR, [_part(MEMBRANE, 5.0, 4.0),
                                        _part(GASKET, 5.0, 0.5)])]
        before = copy.deepcopy(payload)
        simulate_with_renewed(NUMBER, payload, PARAMS, None, {(1, MEMBRANE)})
        self.assertEqual(payload, before)

    def test_renewal_touches_only_the_named_part(self):
        payload = [_unit(1, REGULATOR, [_part(MEMBRANE, 5.0, 4.0),
                                        _part(GASKET, 5.0, 0.5)])]
        base = _term(payload)
        renewed = _term(payload, {(1, MEMBRANE)})
        self.assertAlmostEqual(renewed - base, 4.5 - 1.0, places=1)
        self.assertLess(renewed, _term(payload, {(1, MEMBRANE), (1, GASKET)}))


class DegenerateTests(unittest.TestCase):
    """Неполный расчёт: лестница пуста, а не падает."""

    def setUp(self):
        self.payload = [_unit(1, REGULATOR, [_part(MEMBRANE, 5.0, 4.0)])]

    def test_missing_result_gives_no_steps(self):
        self.assertEqual(build_extension_ladder(NUMBER, self.payload, PARAMS,
                                                None, None), [])

    def test_failed_calculation_gives_no_steps(self):
        empty = _calc([])
        self.assertTrue(empty.error)
        self.assertEqual(build_extension_ladder(NUMBER, [], PARAMS, None,
                                                empty), [])

    def test_result_without_used_elements_gives_no_steps(self):
        result = AlgorithmResult('Скорректированный', NUMBER, 0.0, elements=[])
        self.assertEqual(build_extension_ladder(NUMBER, self.payload, PARAMS,
                                                None, result), [])

    def test_non_critical_element_is_not_lengthened(self):
        """Некритический элемент в расчёт не входит — продлевать нечего."""
        payload = [_unit(1, 'Труба подводящая', [_part(GASKET, 5.0, 4.0)])]
        result = _calc(payload)
        self.assertTrue(result.error)
        self.assertEqual(_ladder(payload), [])


if __name__ == '__main__':
    unittest.main()
