"""Техническое диагностирование: порядок граф, числа в кПа и результат.

Тесты фиксируют:

* порядок граф таблицы — он задан заказчиком (дата, оборудование,
  проверяемый параметр, режим, допуск мин/макс, факт мин/макс, результат,
  примечание), поэтому перестановка граф ломает экран, а не только оформление;
* лишних граф в таблице нет: заказчик перечисляет их поимённо, а подписи
  граф с давлением остаются с единицей измерения;
* у каждой графы есть поле формы, иначе вводить было бы некуда;
* числа в кПа вписываются с запятой и с точкой, а описка в графе допуска не
  сохраняется: по этим числам выводится результат;
* результат — «норма» или «отклонение от нормы»: факт укладывается в допуск
  или выходит за его границу;
* чтение идёт по имени поля, а не по номеру: короткая строка (защитный
  кортеж) не роняет чтение и не сдвигает значения.

Тесты не требуют базы: строка выборки собирается вручную.

Запуск: py -m unittest discover -s tests -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import diagnostic_log  # noqa: E402

# Строка выборки get_diagnostic_checks в порядке RECORD_COLUMNS.
CHECK_ROW = (11, '2024-03-12', 'Регулятор давления РДБК1-50',
             'Давление на выходе', '1,3', '1,25', '1,35', '1,28', '1,32',
             'норма', 'Протокол №14')

# Та же проверка с выходом факта за верхнюю границу допуска.
DEVIATION_ROW = CHECK_ROW[:7] + ('1,28', '1,41', 'отклонение от нормы',
                                 'Акт №3; рекомендация: наладить регулятор')

# Порядок граф, заданный заказчиком. Первой идёт «№» — номер записи в списке.
REQUESTED_ORDER = ('check_date', 'equipment', 'parameter', 'mode',
                   'tolerance_min', 'tolerance_max', 'fact_min', 'fact_max',
                   'result', 'note')

# Подписи граф с давлением: единица измерения — часть подписи.
PRESSURE_LABELS = ('Режим, кПа', 'Допуск мин, кПа', 'Допуск макс, кПа',
                   'Факт мин, кПа', 'Факт макс, кПа')


def column(key: str) -> int:
    """Номер графы в table_cells (без ведущей «№»)."""
    return [name for name, _label, _width
            in diagnostic_log.TABLE_COLUMNS].index(key)


def row_with(key: str, value, base=CHECK_ROW):
    """Копия строки со значением одного поля."""
    cells = list(base)
    cells[diagnostic_log.RECORD_COLUMNS.index(key)] = value
    return tuple(cells)


class TestColumns(unittest.TestCase):
    def test_table_follows_the_requested_order(self):
        """Порядок граф — требование заказчика, а не оформление экрана."""
        keys = [key for key, _label, _width in diagnostic_log.TABLE_COLUMNS]
        self.assertEqual(keys, list(REQUESTED_ORDER))

    def test_nothing_follows_the_note(self):
        """В таблице ровно заказанные графы, — лишних быть не должно."""
        self.assertEqual(len(diagnostic_log.TABLE_COLUMNS),
                         len(REQUESTED_ORDER))

    def test_labels_keep_the_unit(self):
        """Давление подписано в кПа: без единицы числа не читаются."""
        labels = [label for _key, label, _width
                  in diagnostic_log.TABLE_COLUMNS]
        for label in PRESSURE_LABELS:
            self.assertIn(label, labels)

    def test_labels_and_keys_are_unique(self):
        keys = [key for key, _label, _width in diagnostic_log.TABLE_COLUMNS]
        labels = [label for _key, label, _width in diagnostic_log.TABLE_COLUMNS]
        self.assertEqual(len(set(keys)), len(keys))
        self.assertEqual(len(set(labels)), len(labels))

    def test_every_column_is_asked_in_the_form(self):
        """У каждой графы есть поле формы, и наоборот."""
        shown = {key for key, _label, _width in diagnostic_log.TABLE_COLUMNS}
        asked = {key for key, _label, _kind, _hint
                 in diagnostic_log.FORM_FIELDS}
        self.assertEqual(shown, asked)
        self.assertEqual(diagnostic_log.FIELDS, tuple(REQUESTED_ORDER))

    def test_form_field_kinds_are_known(self):
        """Вид поля выбирает форму: список или строку ввода."""
        kinds = {kind for _key, _label, kind, _hint
                 in diagnostic_log.FORM_FIELDS}
        self.assertEqual(kinds - {'date', 'equipment', 'choice', 'pressure',
                                  'result', 'text'}, set())

    def test_pressure_fields_are_the_columns_with_kpa(self):
        """С числами в кПа работают ровно пять граф — по подписям видно какие."""
        pressure = {key for key, _label, kind, _hint
                    in diagnostic_log.FORM_FIELDS if kind == 'pressure'}
        self.assertEqual(pressure, {'mode', 'tolerance_min', 'tolerance_max',
                                    'fact_min', 'fact_max'})
        self.assertEqual(set(diagnostic_log.PRESSURE_FIELDS), pressure)

    def test_result_is_chosen_from_a_list(self):
        """Результат — одно из двух слов, а не свободный текст."""
        kinds = {key: kind for key, _label, kind, _hint
                 in diagnostic_log.FORM_FIELDS}
        self.assertEqual(kinds['result'], 'result')
        self.assertEqual(diagnostic_log.RESULTS,
                         ('норма', 'отклонение от нормы'))

    def test_result_comes_from_the_tolerance_and_the_fact(self):
        """Результат выводят четыре графы; «режим» в сравнении не участвует."""
        self.assertEqual(set(diagnostic_log.RESULT_FIELDS),
                         {'tolerance_min', 'tolerance_max',
                          'fact_min', 'fact_max'})
        self.assertNotIn('mode', diagnostic_log.RESULT_FIELDS)
        self.assertEqual(set(diagnostic_log.RESULT_FIELDS)
                         - set(diagnostic_log.PRESSURE_FIELDS), set())

    def test_table_index_counts_the_number_column(self):
        """Первой графой идёт «№», поэтому индекс на единицу больше позиции."""
        self.assertEqual(diagnostic_log.table_index('check_date'), 1)
        self.assertEqual(diagnostic_log.table_index('note'), 1 + column('note'))

    def test_table_index_matches_table_cells(self):
        """Номер графы в строке таблицы — тот же список, что у table_cells."""
        cells = diagnostic_log.table_cells(CHECK_ROW)
        for key, _label, _width in diagnostic_log.TABLE_COLUMNS:
            self.assertEqual(diagnostic_log.table_index(key) - 1, column(key))
            self.assertTrue(cells[column(key)], key)


class TestReading(unittest.TestCase):
    def test_value_reads_by_field_name(self):
        self.assertEqual(diagnostic_log.value(CHECK_ROW, 'parameter'),
                         'Давление на выходе')
        self.assertEqual(diagnostic_log.value(CHECK_ROW, 'tolerance_max'), '1,35')

    def test_unknown_field_is_empty(self):
        self.assertEqual(diagnostic_log.value(CHECK_ROW, 'чего-нет'), '')

    def test_short_row_does_not_shift_values(self):
        """Строка без последних граф читается пустой, а не чужим значением."""
        short = CHECK_ROW[:9]
        self.assertEqual(diagnostic_log.value(short, 'parameter'),
                         'Давление на выходе')
        self.assertEqual(diagnostic_log.value(short, 'result'), '')
        self.assertEqual(diagnostic_log.value(short, 'note'), '')

    def test_dictionary_source_reads_the_same(self):
        """Запасная выборка приходит словарём по своему списку колонок."""
        source = dict(zip(diagnostic_log.RECORD_COLUMNS, CHECK_ROW))
        self.assertEqual(diagnostic_log.value(source, 'equipment'),
                         'Регулятор давления РДБК1-50')
        cells = diagnostic_log.table_cells(source)
        self.assertEqual(cells[column('result')], 'норма')
        self.assertEqual(len(cells), len(diagnostic_log.TABLE_COLUMNS))

    def test_none_and_spaces_become_a_dash(self):
        cells = diagnostic_log.table_cells(row_with('note', '   '))
        self.assertEqual(cells[column('note')], diagnostic_log.EMPTY)
        cells = diagnostic_log.table_cells(row_with('equipment', None))
        self.assertEqual(cells[column('equipment')], diagnostic_log.EMPTY)

    def test_numbers_are_shown_as_written(self):
        """Числа показываются так, как их перенесли из протокола."""
        cells = diagnostic_log.table_cells(CHECK_ROW)
        self.assertEqual(cells[column('mode')], '1,3')
        self.assertEqual(cells[column('fact_max')], '1,32')

    def test_date_is_shown_as_in_the_documents(self):
        """ISO из формы приводится к виду «ДД.ММ.ГГГГ»."""
        self.assertEqual(diagnostic_log.table_cells(CHECK_ROW)[0], '12.03.2024')

    def test_date_written_by_hand_is_shown_as_written(self):
        """Дату могли вписать словами — выдумывать её вид нельзя."""
        self.assertEqual(diagnostic_log.date_text('12.03.2024'), '12.03.2024')
        self.assertEqual(diagnostic_log.date_text('март 2024'), 'март 2024')
        self.assertEqual(diagnostic_log.date_text(''), '')

    def test_result_graph_is_read_as_written(self):
        self.assertEqual(diagnostic_log.result_text(CHECK_ROW), 'норма')
        self.assertEqual(diagnostic_log.result_text(DEVIATION_ROW),
                         'отклонение от нормы')

    def test_form_values_give_every_graph(self):
        values = diagnostic_log.form_values(CHECK_ROW)
        self.assertEqual(set(values), set(diagnostic_log.FIELDS))
        self.assertEqual(values['check_date'], '2024-03-12')
        self.assertEqual(values['tolerance_min'], '1,25')

    def test_form_values_of_a_short_record_are_empty(self):
        """Поля, которых в строке нет, — пустые, а не чужие значения."""
        values = diagnostic_log.form_values(CHECK_ROW[:1])
        self.assertEqual(set(values.values()), {''})


class TestNumbers(unittest.TestCase):
    """Числа в кПа: запятая и точка — одно и то же число."""

    def test_comma_and_dot_are_the_same(self):
        self.assertEqual(diagnostic_log.to_number('1,3'),
                         diagnostic_log.to_number('1.3'))
        self.assertEqual(diagnostic_log.to_number('1,3'), 1.3)

    def test_spaces_are_trimmed(self):
        self.assertEqual(diagnostic_log.to_number('  300  '), 300.0)

    def test_minus_signs_are_understood(self):
        """Минус бывает обычный и типографский — оба значат одно."""
        self.assertEqual(diagnostic_log.to_number('-0,5'), -0.5)
        self.assertEqual(diagnostic_log.to_number('−0,5'), -0.5)

    def test_other_text_is_not_a_number(self):
        for word in ('', None, '   ', 'около 1,3', '1,3,4', '1 3', '1,3 кПа',
                     'п/п'):
            self.assertIsNone(diagnostic_log.to_number(word), word)

    def test_pressure_graph_accepts_a_number_or_nothing(self):
        self.assertEqual(diagnostic_log.parse_pressure(' 1,25 ', 'Допуск мин, кПа'),
                         '1,25')
        self.assertEqual(diagnostic_log.parse_pressure('', 'Допуск мин, кПа'), '')
        self.assertEqual(diagnostic_log.parse_pressure(None, 'Режим, кПа'), '')

    def test_pressure_graph_rejects_other_text(self):
        """«примерно 1,3» в графе допуска неотличимо от описки."""
        with self.assertRaises(diagnostic_log.DiagnosticError) as caught:
            diagnostic_log.parse_pressure('примерно 1,3', 'Допуск макс, кПа')
        self.assertIn('Допуск макс, кПа', str(caught.exception))

    def test_parameter_is_required(self):
        """Проверка без параметра — запись, которую нельзя прочитать."""
        self.assertEqual(diagnostic_log.parse_parameter(' Давление на выходе '),
                         'Давление на выходе')
        with self.assertRaises(diagnostic_log.DiagnosticError):
            diagnostic_log.parse_parameter('   ')

    def test_parameter_suggestions_start_with_the_pressures(self):
        self.assertIn('Давление на выходе', diagnostic_log.PARAMETERS)


class TestResult(unittest.TestCase):
    """Результат проверки выводится из четырёх чисел в кПа."""

    def test_fact_inside_the_tolerance_is_the_norm(self):
        self.assertEqual(
            diagnostic_log.suggested_result('1,25', '1,35', '1,28', '1,32'),
            diagnostic_log.RESULT_OK)

    def test_fact_below_the_tolerance_is_a_deviation(self):
        self.assertEqual(
            diagnostic_log.suggested_result('1,25', '1,35', '1,10', '1,32'),
            diagnostic_log.RESULT_DEVIATION)

    def test_fact_above_the_tolerance_is_a_deviation(self):
        self.assertEqual(
            diagnostic_log.suggested_result('1,25', '1,35', '1,28', '1,41'),
            diagnostic_log.RESULT_DEVIATION)

    def test_touching_a_border_is_still_the_norm(self):
        """Совпадение с границей — ещё норма: граница входит в допуск."""
        self.assertEqual(
            diagnostic_log.suggested_result('1,25', '1,35', '1,25', '1,35'),
            diagnostic_log.RESULT_OK)

    def test_reversed_tolerance_is_understood(self):
        """Границы могли вписать наоборот — это те же границы."""
        self.assertEqual(
            diagnostic_log.suggested_result('1,35', '1,25', '1,28', '1,32'),
            diagnostic_log.RESULT_OK)

    def test_reversed_fact_is_understood(self):
        """Факт мин и макс тоже могли поменять местами."""
        self.assertEqual(
            diagnostic_log.suggested_result('1,25', '1,35', '1,32', '1,28'),
            diagnostic_log.RESULT_OK)

    def test_incomplete_numbers_give_no_result(self):
        """Пока вписаны не все четыре числа, судить не о чем."""
        cases = (('', '1,35', '1,28', '1,32'),
                 ('1,25', '', '1,28', '1,32'),
                 ('1,25', '1,35', '', '1,32'),
                 ('1,25', '1,35', '1,28', ''),
                 ('', '', '', ''))
        for numbers in cases:
            self.assertEqual(diagnostic_log.suggested_result(*numbers), '',
                             numbers)

    def test_result_can_be_chosen_by_hand(self):
        self.assertEqual(diagnostic_log.parse_result('Норма'), 'норма')
        self.assertEqual(diagnostic_log.parse_result(' ОТКЛОНЕНИЕ ОТ НОРМЫ '),
                         'отклонение от нормы')
        self.assertEqual(diagnostic_log.parse_result(''), '')

    def test_other_words_are_rejected(self):
        for word in ('удовлетворительно', 'норма (с замечанием)', 'да'):
            with self.assertRaises(diagnostic_log.DiagnosticError, msg=word):
                diagnostic_log.parse_result(word)


class TestValues(unittest.TestCase):
    """Значения граф для записи в базу."""

    def test_empty_lines_become_null(self):
        values = diagnostic_log.values({'equipment': '  ', 'note': None,
                                        'fact_max': ''})
        self.assertIsNone(values['equipment'])
        self.assertIsNone(values['note'])
        self.assertIsNone(values['fact_max'])

    def test_result_keeps_the_empty_string(self):
        """Результат в базе NOT NULL: пустая строка значит «не указан»."""
        self.assertEqual(diagnostic_log.values({'result': ''})['result'], '')
        self.assertEqual(diagnostic_log.values({'result': ' '})['result'], '')

    def test_values_are_stripped(self):
        self.assertEqual(
            diagnostic_log.values({'parameter': ' Давление на выходе '})['parameter'],
            'Давление на выходе')

    def test_values_round_trip_through_the_form(self):
        """Что форма показала, то и записывается: круговорот не теряет граф."""
        entered = diagnostic_log.form_values(CHECK_ROW)
        entered['check_date'] = '2024-03-12'
        saved = diagnostic_log.values(entered)
        self.assertEqual(saved['mode'], '1,3')
        self.assertEqual(saved['tolerance_max'], '1,35')
        self.assertEqual(saved['result'], 'норма')
        self.assertEqual(saved['note'], 'Протокол №14')
        self.assertEqual(set(saved), set(diagnostic_log.FIELDS))

    def test_empty_record_saves_nothing(self):
        """Пустая форма пишет NULL, а результат — только пустую строку."""
        values = diagnostic_log.values({})
        self.assertEqual(values['parameter'], None)
        self.assertEqual(values['fact_min'], None)
        self.assertEqual(values['result'], '')


if __name__ == '__main__':
    unittest.main()
