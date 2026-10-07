"""Правило слабого звена: показывается один элемент, а не весь ГРП.

Тесты фиксируют, кого расчёт объявляет слабым звеном:

* слабое звено одно — элемент с наименьшим остаточным ресурсом;
* рядом с ним показываются только элементы, у которых ресурс исчерпывается
  в тот же день: по отдельности ни один из них срок не сдвигает;
* «в пределах полугода от минимума» звеном больше не считается — из-за этого
  допуска слабым звеном объявлялся почти весь ГРП.

Тесты не требуют базы: элементы собираются вручную.

Запуск: py -m unittest discover -s tests -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from logic.algorithms import (  # noqa: E402
    GRPResourceCalculator,
    AlgorithmResult,
    ElementResult,
    collect_weak_links,
    critical_title,
    weak_link_elements,
)

# Сутки в годах — та же мера, что и в расчёте (год = 365.25 дней).
DAY = 1.0 / 365.25


def _element(name, z, norm=5.0, age=1.0, install='2020-01-01'):
    """Элемент с заданным остаточным ресурсом и одной определяющей деталью."""
    return ElementResult(
        name=name,
        critical_key='regulator',
        install_date=install,
        age=age,
        norm=norm,
        z_element=z,
        details=[{'name': f'{name}: мембрана', 'norm': norm, 'age': age,
                  'z_base': z}],
    )


def _names(elements):
    return [e.name for e in elements]


class WeakLinkElementsTests(unittest.TestCase):
    """Состав слабых звеньев — минимум и совпавшие с ним по дате."""

    def test_single_minimum_is_the_only_link(self):
        used = [_element('А', 1.0), _element('Б', 3.0), _element('В', 2.0)]
        self.assertEqual(_names(weak_link_elements(used)), ['А'])

    def test_equal_remaining_resources_are_all_links(self):
        used = [_element('А', 1.5), _element('Б', 1.5), _element('В', 4.0)]
        self.assertEqual(_names(weak_link_elements(used)), ['А', 'Б'])

    def test_same_expiry_day_is_a_tie(self):
        """«Совпали по времени»: разница меньше суток — один и тот же день."""
        used = [_element('А', 4.0), _element('Б', 4.0 + 0.4 * DAY),
                _element('В', 9.0)]
        self.assertEqual(_names(weak_link_elements(used)), ['А', 'Б'])

    def test_next_day_is_not_a_tie(self):
        used = [_element('А', 4.0), _element('Б', 4.0 + 0.6 * DAY)]
        self.assertEqual(_names(weak_link_elements(used)), ['А'])

    def test_near_minimum_within_half_year_is_not_a_link(self):
        """Регрессия: раньше в звенья попадало всё в пределах полугода."""
        used = [_element('А', 2.0), _element('Б', 2.4), _element('В', 2.5)]
        self.assertEqual(_names(weak_link_elements(used)), ['А'])

    def test_overdue_minimum_wins(self):
        """Просроченный элемент — тоже слабое звено, а не «нет звеньев»."""
        used = [_element('А', -0.5), _element('Б', 2.0)]
        self.assertEqual(_names(weak_link_elements(used)), ['А'])

    def test_order_does_not_depend_on_input_order(self):
        first, second = _element('Б', 1.0), _element('А', 1.0)
        self.assertEqual(_names(weak_link_elements([second, first])),
                         _names(weak_link_elements([first, second])))

    def test_no_elements(self):
        self.assertEqual(weak_link_elements([]), [])
        self.assertEqual(weak_link_elements(None), [])


class CollectWeakLinksTests(unittest.TestCase):
    """Слабые звенья для отчёта: те же элементы плюс определяющая деталь."""

    @staticmethod
    def _result(elements):
        return AlgorithmResult('Скорректированная', 3, 1.0, elements=elements)

    def test_links_carry_the_driving_part(self):
        links = collect_weak_links(self._result([_element('Регулятор', 1.0)]))
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0].element, 'Регулятор')
        self.assertEqual(links[0].category, critical_title('regulator'))
        self.assertEqual(links[0].part, 'Регулятор: мембрана')
        self.assertAlmostEqual(links[0].z_element, 1.0)

    def test_unused_elements_are_ignored(self):
        idle = _element('Выведенный', 0.1)
        idle.used = False
        links = collect_weak_links(self._result([idle, _element('Рабочий', 2.0)]))
        self.assertEqual([link.element for link in links], ['Рабочий'])

    def test_only_coincident_elements_are_listed(self):
        links = collect_weak_links(self._result(
            [_element('А', 2.0), _element('Б', 2.4), _element('В', 2.0)]))
        self.assertEqual([link.element for link in links], ['А', 'В'])

    def test_missing_result_and_empty_result(self):
        self.assertEqual(collect_weak_links(None), [])
        self.assertEqual(collect_weak_links(self._result([])), [])


class SingleWeakElementTests(unittest.TestCase):
    """result.weak_element — первое из списка звеньев, то же, что в отчёте."""

    def test_same_element_as_first_link(self):
        used = [_element('Б', 1.0), _element('А', 1.0)]
        result = AlgorithmResult('Скорректированная', 3, 1.0, elements=used,
                                 weak_element=GRPResourceCalculator._weak_of(used).name)
        self.assertEqual(result.weak_element, collect_weak_links(result)[0].element)

    def test_no_elements(self):
        self.assertIsNone(GRPResourceCalculator._weak_of([]))


if __name__ == '__main__':
    unittest.main()
