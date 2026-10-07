"""Форма 6.2 отчёта: состав строк и согласованность чисел с расчётом.

Форма заполняется по образцу паспорта ГРП (раздел 6.2) и печатается в отчёте
для методик «Алгоритм 3» и «Алгоритм 4». Тесты фиксируют:

* ровно 23 строки в порядке формы: базовые ресурсы, коэффициенты технического
  состояния, общие поправки, итоговые ресурсы, слабое звено, остаточный ресурс
  ГРП, срок следующего диагностирования (годы и месяцы), рекомендуемая дата;
* числа в форме те же, что в окне расчёта: минимум по категориям равен
  `result.result`, «Слабое звено» — категория `result.weak_element_key`;
* незаполненные случаи не роняют форму: пустая категория и нерассчитанная
  методика дают прочерки, а не исключение.

Тесты не требуют базы и Word: результат расчёта собирается вручную.

Запуск: py -m unittest discover -s tests -v
"""

import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from integration.word_report_pg import (  # noqa: E402
    FORM62_CATEGORIES,
    FORM62_HEADERS,
    form62_rows,
)
from logic.algorithms import AlgorithmParams, AlgorithmResult, ElementResult  # noqa: E402

# Числа образца паспорта ГРП №26: категория, Zбаза, Kсост, Z, есть ли детали.
SAMPLE = (
    ('regulator', 2.0, 0.694, 1.388, True),
    ('pzk', 2.0, 0.761, 1.522, True),
    ('psk', 10.0, 0.920, 9.198, False),
    ('filter', 10.0, 1.000, 10.0, True),
    ('valve', 10.0, 1.000, 10.0, True),
)

# Сегодняшний день образца: срок 0,694 года исчерпывается в январе 2027.
TODAY = date(2026, 5, 21)

WORDS = {
    'regulator': 'регулятор',
    'pzk': 'ПЗК',
    'psk': 'ПСК',
    'filter': 'фильтр',
    'valve': 'арматура',
}

ABBR = {
    'regulator': 'рег',
    'pzk': 'пзк',
    'psk': 'пск',
    'filter': 'фильтр',
    'valve': 'арматура',
}


def _element(key, z_base, k_state, z_element, has_details=True, name=None):
    """Результат по элементу категории: база, состояние и итоговый ресурс."""
    return ElementResult(
        name=name or f'{ABBR[key]}-1',
        critical_key=key,
        used=True,
        z_base=z_base,
        z_base_formula=('min(Zбаза d)' if has_details else 'ЭО по нормативу'),
        k_state=k_state,
        k_cond=1.0,
        k_repair=1.0,
        k_fail=1.0,
        z_element=z_element,
    )


def _sample_result():
    """Результат «Алгоритма 3» по числам образца."""
    elements = [_element(key, z_base, k_state, z_element, has_details)
                for key, z_base, k_state, z_element, has_details in SAMPLE]
    return AlgorithmResult(
        'Скорректированный', 3, 1.388,
        weak_element='рег-1', weak_element_key='regulator',
        next_diagnosis=0.694, elements=elements)


def _column(rows, index):
    return [row[index] for row in rows]


class ShapeTests(unittest.TestCase):
    """Состав формы: строки, подписи, обозначения."""

    def setUp(self):
        self.rows = form62_rows(_sample_result(), AlgorithmParams(), TODAY)

    def test_headers_match_the_form(self):
        self.assertEqual(FORM62_HEADERS,
                         ('Параметр', 'Обозначение', 'Значение', 'Ед. изм.',
                          'Примечание'))

    def test_every_row_has_five_cells(self):
        for row in self.rows:
            with self.subTest(row[0]):
                self.assertEqual(len(row), len(FORM62_HEADERS))

    def test_row_count_is_23(self):
        """Пять категорий в четырёх группах плюс три итоговые строки."""
        self.assertEqual(len(self.rows), 23)

    def test_parameters_are_in_the_form_order(self):
        expected = (
            [f'Базовый ресурс ({WORDS[key]})' for key, *_ in SAMPLE] +
            [f'Коэффициент тех. состояния ({WORDS[key]})' for key, *_ in SAMPLE] +
            ['Коэффициент условий эксплуатации',
             'Коэффициент качества ремонта',
             'Коэффициент повреждений и отказов'] +
            [f'Итоговый ресурс ({WORDS[key]})' for key, *_ in SAMPLE] +
            ['Слабое звено',
             'Остаточный ресурс ГРП',
             'Срок следующего диагностирования',
             'Срок следующего диагностирования',
             'Рекомендуемая дата следующего диагностирования'])
        self.assertEqual(_column(self.rows, 0), expected)

    def test_designations_are_in_the_form_order(self):
        keys = [key for key, *_ in SAMPLE]
        expected = ([f'Zбаза,{ABBR[key]}' for key in keys] +
                    [f'Kсост,{ABBR[key]}' for key in keys] +
                    ['Kусл', 'Kрем', 'kповр'] +
                    [f'Z{ABBR[key]}' for key in keys] +
                    ['Zслабое', 'ZГРП', 'Tслед_диагн', 'Tслед_диагн', '—'])
        self.assertEqual(_column(self.rows, 1), expected)

    def test_units_are_in_the_form_order(self):
        keys = [key for key, *_ in SAMPLE]
        expected = (['лет'] * 5 + ['—'] * 5 + ['—'] * 3 + ['лет'] * 5 +
                    ['—', 'лет', 'лет', 'мес.', '—'])
        self.assertEqual(_column(self.rows, 3), expected)


class ValuesTests(unittest.TestCase):
    """Числа формы: те же, что в расчёте, и в той же записи, что в образце."""

    def setUp(self):
        self.result = _sample_result()
        self.rows = form62_rows(self.result, AlgorithmParams(), TODAY)
        self.values = _column(self.rows, 2)
        self.notes = _column(self.rows, 4)

    def test_base_resources(self):
        self.assertEqual(self.values[:5], ['2', '2', '10', '10', '10'])

    def test_state_coefficients(self):
        self.assertEqual(self.values[5:10],
                         ['0,694', '0,761', '0,920', '1,000', '1,000'])

    def test_common_corrections_use_one_decimal(self):
        self.assertEqual(self.values[10:13], ['1,0', '1,0', '1,0'])

    def test_total_resources_keep_one_decimal_at_least(self):
        """«10,0» рядом с «1,388»: целое не теряется среди дробных."""
        self.assertEqual(self.values[13:18],
                         ['1,388', '1,522', '9,198', '10,0', '10,0'])

    def test_residual_resource_is_the_weak_link(self):
        self.assertEqual(self.values[19], '1,388')

    def test_next_diagnosis_in_years_and_months(self):
        self.assertEqual(self.values[20], '0,694')
        self.assertEqual(self.values[21], '8,33')

    def test_recommended_date_is_a_month(self):
        self.assertEqual(self.values[22], 'январь 2027')

    def test_base_note_tells_whether_details_were_used(self):
        """«ЭО min(Zбаза d)» — база взята минимумом по заменяемым деталям."""
        self.assertEqual(self.notes[:5],
                         ['ЭО min(Zбаза d)', 'ЭО min(Zбаза d)', 'ЭО',
                          'ЭО min(Zбаза d)', 'ЭО min(Zбаза d)'])

    def test_state_note_points_at_the_calculation(self):
        self.assertEqual(self.notes[5:10], ['Из расчетов'] * 5)

    def test_corrections_apply_to_every_element(self):
        self.assertEqual(self.notes[10:13], ['Для всех элементов'] * 3)

    def test_total_resource_note_is_a_product(self):
        self.assertEqual(self.notes[13], '2 × 0,694 × 1,0 × 1,0 × 1,0')
        self.assertEqual(self.notes[15], '10 × 0,920 × 1,0 × 1,0 × 1,0')

    def test_weak_link_note_lists_the_category_resources(self):
        self.assertEqual(self.notes[18],
                         'min(1,388; 1,522; 9,198; 10,0; 10,0)')

    def test_residual_note_is_the_weak_link(self):
        self.assertEqual(self.notes[19], 'Ресурс слабого звена')

    def test_next_diagnosis_note_takes_numbers_from_params(self):
        self.assertEqual(self.notes[20], 'min(1,388 × 0,5; 5)')
        self.assertEqual(self.notes[21], '0,694 × 12')

    def test_date_note_counts_months_from_today(self):
        self.assertEqual(self.notes[22], '21.05.2026 + 8,33 мес.')


class ConsistencyTests(unittest.TestCase):
    """Форма не расходится с результатом расчёта."""

    def test_minimum_over_categories_is_the_result(self):
        """Ресурс ГРП — минимум по представителям: сумма строк формы сходится."""
        result = _sample_result()
        rows = form62_rows(result, AlgorithmParams(), TODAY)
        category_values = [float(value.replace(',', '.'))
                           for value in _column(rows, 2)[13:18]]
        self.assertAlmostEqual(min(category_values), result.result, places=3)

    def test_weak_link_word_matches_the_calculation(self):
        result = _sample_result()
        rows = form62_rows(result, AlgorithmParams(), TODAY)
        self.assertEqual(rows[18][2], WORDS['regulator'])

    def test_reserve_and_interval_come_from_params(self):
        params = AlgorithmParams(reserve=0.25, max_diag_interval=3.0)
        rows = form62_rows(_sample_result(), params, TODAY)
        self.assertEqual(rows[20][4], 'min(1,388 × 0,25; 3)')

    def test_next_diagnosis_row_follows_recomputed_value(self):
        result = _sample_result()
        result.next_diagnosis = 0.5
        rows = form62_rows(result, AlgorithmParams(), TODAY)
        self.assertEqual(rows[21][2], '6,00')
        self.assertEqual(rows[21][4], '0,500 × 12')


class CategoryChoiceTests(unittest.TestCase):
    """Представитель категории: минимальный ресурс, при равенстве — по имени."""

    @staticmethod
    def _result(elements, weak_key='regulator', result=1.0, next_diagnosis=0.5):
        return AlgorithmResult('REGION-gaz', 2, result, weak_element_key=weak_key,
                               next_diagnosis=next_diagnosis, elements=elements)

    def test_lowest_resource_represents_the_category(self):
        elements = [_element('filter', 10.0, 1.0, 9.0, name='фильтр-1'),
                    _element('filter', 10.0, 0.5, 4.5, name='фильтр-2')]
        rows = form62_rows(self._result(elements, 'filter', 4.5, 2.25),
                           AlgorithmParams(), TODAY)
        self.assertEqual(rows[16][2], '4,5')
        self.assertEqual(rows[16][4], '10 × 0,500 × 1,0 × 1,0 × 1,0')

    def test_equal_resources_are_broken_by_name(self):
        """При равном ресурсе берётся первый по имени — как у слабого звена."""
        first = _element('valve', 8.0, 1.0, 5.0, name='арматура-А')
        second = _element('valve', 5.0, 1.0, 5.0, name='арматура-Б')
        straight = form62_rows(self._result([first, second], 'valve', 5.0, 2.5),
                               AlgorithmParams(), TODAY)
        reverse = form62_rows(self._result([second, first], 'valve', 5.0, 2.5),
                              AlgorithmParams(), TODAY)
        self.assertEqual(straight[17][4], '8 × 1,000 × 1,0 × 1,0 × 1,0')
        self.assertEqual(reverse[17][4], straight[17][4])

    def test_unused_elements_are_ignored(self):
        idle = _element('filter', 10.0, 0.1, 1.0, name='фильтр-списанный')
        idle.used = False
        working = _element('filter', 10.0, 0.9, 9.0, name='фильтр-рабочий')
        rows = form62_rows(self._result([idle, working], 'filter', 9.0, 4.5),
                           AlgorithmParams(), TODAY)
        self.assertEqual(rows[16][2], '9,0')

    def test_missing_category_is_a_dash(self):
        """ПСК в ГРП нет — его строки пусты, остальные заполнены."""
        elements = [_element(key, z_base, k_state, z_element)
                    for key, z_base, k_state, z_element, _d in SAMPLE
                    if key != 'psk']
        rows = form62_rows(self._result(elements), AlgorithmParams(), TODAY)
        self.assertEqual(rows[2][2], '—')
        self.assertEqual(rows[2][4], '—')
        self.assertEqual(rows[7][2], '—')
        self.assertEqual(rows[15][2], '—')
        self.assertEqual(rows[15][4], '—')
        self.assertEqual(rows[18][4], 'min(1,388; 1,522; 10,0; 10,0)')

    def test_element_without_category_is_ignored(self):
        other = _element('regulator', 2.0, 0.5, 1.0, name='прочее')
        other.critical_key = None
        rows = form62_rows(self._result([other]), AlgorithmParams(), TODAY)
        self.assertEqual(rows[0][2], '—')


class DegenerateTests(unittest.TestCase):
    """Нерассчитанная методика: форма не пропадает, значения пусты."""

    @staticmethod
    def _failed(error='Нет оборудования для расчёта'):
        return AlgorithmResult('REGION-gaz', 2, 0.0, error=error)

    def test_error_result_prints_dashes(self):
        rows = form62_rows(self._failed(), AlgorithmParams(), TODAY)
        self.assertEqual(len(rows), 23)
        self.assertEqual(set(_column(rows, 2)[:20]), {'—'})
        self.assertEqual(rows[22][2], '—')

    def test_error_result_has_no_notes(self):
        rows = form62_rows(self._failed(), AlgorithmParams(), TODAY)
        self.assertEqual(set(_column(rows, 4)), {'—'})

    def test_missing_result_prints_the_same_form(self):
        self.assertEqual(form62_rows(None, AlgorithmParams(), TODAY),
                         form62_rows(self._failed(), AlgorithmParams(), TODAY))

    def test_parameters_are_optional(self):
        rows = form62_rows(_sample_result(), None, TODAY)
        self.assertEqual(rows[20][4], 'min(1,388 × 0,5; 5)')

    def test_today_is_optional(self):
        """Без даты берётся сегодняшний день — форма всё равно заполнена."""
        rows = form62_rows(_sample_result(), AlgorithmParams())
        self.assertNotEqual(rows[22][2], '—')

    def test_categories_constant_has_five_form_rows(self):
        self.assertEqual(len(FORM62_CATEGORIES), 5)
        self.assertEqual([key for key, _w, _a in FORM62_CATEGORIES],
                         ['regulator', 'pzk', 'psk', 'filter', 'valve'])


if __name__ == '__main__':
    unittest.main()
