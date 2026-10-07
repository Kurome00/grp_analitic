"""Что предлагается менять: одна определяющая деталь, а не весь список.

Ресурс элемента держит только деталь с наименьшим остатком — остальные
истекают позже и общего срока не двигают. Поэтому и в шаге продления, и в
карточке «Скоро нужно менять» должна называться одна деталь: раньше туда
попадали все просроченные детали сразу, при разных датах замены.

Тесты не требуют ни базы, ни окна Tkinter: проверяется чистая функция отбора.

Запуск: py -m unittest discover -s tests -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ui.algorithms_view import _counted_parts, _pick_parts  # noqa: E402


class _Element:
    """Элемент расчёта в объёме, который нужен отбору деталей."""

    def __init__(self, details):
        self.details = details


def _part(name, residual, norm=5.0):
    """Деталь с заданным остатком (z_base — то же, что считает методика)."""
    return {'name': name, 'norm': norm, 'z_base': residual}


class PickPartsTests(unittest.TestCase):
    """Отбор детали к замене: ровно одна — с минимальным остатком."""

    def test_only_the_most_overdue_part_is_picked(self):
        element = _Element([_part('Пружина', -0.4), _part('Мембрана', -0.1),
                            _part('Втулка', -1.2)])
        picked = _pick_parts(element)
        self.assertEqual([p['name'] for p in picked], ['Втулка'])

    def test_parts_with_later_dates_do_not_come_along(self):
        """Несколько просроченных деталей — в замену идёт одна, самая изношенная."""
        element = _Element([_part('Прокладка', 0.0), _part('Шток', 0.9),
                            _part('Клапан', -0.2)])
        self.assertEqual(len(_pick_parts(element)), 1)

    def test_nearest_part_wins_when_nothing_is_overdue(self):
        element = _Element([_part('Тарелка', 3.0), _part('Седло', 1.5),
                            _part('Фильтр', 4.2)])
        self.assertEqual([p['name'] for p in _pick_parts(element)], ['Седло'])

    def test_parts_with_other_norms_are_ignored(self):
        element = _Element([_part('Корпус', 0.1, norm=20.0),
                            _part('Пружина', 2.0)])
        self.assertEqual([p['name'] for p in _pick_parts(element)], ['Пружина'])

    def test_no_counted_parts_gives_empty_list(self):
        self.assertEqual(_pick_parts(_Element([_part('Корпус', 1.0, norm=20.0)])), [])
        self.assertEqual(_pick_parts(_Element([])), [])


class CountedPartsTests(unittest.TestCase):
    """В расчёт идут только детали с нормой 5 лет."""

    def test_only_five_year_parts_are_counted(self):
        element = _Element([_part('Пружина', 1.0), _part('Корпус', 9.0, norm=20.0)])
        self.assertEqual([p['name'] for p in _counted_parts(element)], ['Пружина'])

    def test_norm_years_key_is_understood(self):
        """Вход расчёта приходит из базы с ключом norm_years."""
        element = _Element([{'name': 'Пружина', 'norm_years': 5.0, 'z_base': 2.0}])
        self.assertEqual([p['name'] for p in _counted_parts(element)], ['Пружина'])


if __name__ == '__main__':
    unittest.main()
