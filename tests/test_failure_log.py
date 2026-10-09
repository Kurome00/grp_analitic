"""Информация по отказам: порядок граф, чтение строки, слова и фото.

Тесты фиксируют:

* порядок граф таблицы — он задан заказчиком (дата выявления, тип события,
  причина, критичность, признак устранения, документ, примечания), поэтому
  перестановка граф ломает экран, а не только оформление;
* лишних граф в таблице нет: заказчик перечисляет их поимённо;
* у каждой графы есть поле формы, иначе вводить было бы некуда;
* критичность и признак устранения — слова из короткого списка, свободный
  текст там неотличим от описки;
* чтение идёт по имени поля, а не по номеру: короткая строка (защитный
  кортеж) не роняет чтение и не сдвигает значения;
* фото хранится отдельно от граф, поэтому список читается без байтов, а
  графа «Примечания» говорит о нём отметкой;
* документ по умолчанию — аварийный журнал.

Тесты не требуют базы: строка выборки собирается вручную.

Запуск: py -m unittest discover -s tests -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import failure_log  # noqa: E402

# Строка выборки get_failures_by_grp в порядке RECORD_COLUMNS.
FAILURE_ROW = (7, '2024-04-18', 'Нарушение работы оборудования',
               'Засорение фильтра', 'средняя', 'да', 'Аварийный журнал',
               'Акт №12; рекомендация: заменить фильтрующий элемент', False)

# Та же запись с приложенным фото и пустым примечанием.
PHOTO_ONLY_ROW = (8, '2024-05-02', 'Утечка газа', 'Ослабло соединение',
                  'высокая', 'нет', failure_log.DEFAULT_DOCUMENT, '', True)

# Порядок граф, заданный заказчиком. Первой идёт «№» — номер записи в списке.
REQUESTED_ORDER = ('detected_date', 'event_type', 'reason', 'criticality',
                   'resolved', 'document', 'note')


def column(key: str) -> int:
    """Номер графы в table_cells (без ведущей «№»)."""
    return [name for name, _label, _width
            in failure_log.TABLE_COLUMNS].index(key)


def row_with(key: str, value, base=FAILURE_ROW):
    """Копия строки со значением одного поля."""
    cells = list(base)
    cells[failure_log.RECORD_COLUMNS.index(key)] = value
    return tuple(cells)


class TestColumns(unittest.TestCase):
    def test_table_follows_the_requested_order(self):
        """Порядок граф — требование заказчика, а не оформление экрана."""
        keys = [key for key, _label, _width in failure_log.TABLE_COLUMNS]
        self.assertEqual(keys, list(REQUESTED_ORDER))

    def test_nothing_follows_the_notes(self):
        """В таблице ровно заказанные графы, — лишних быть не должно."""
        self.assertEqual(len(failure_log.TABLE_COLUMNS), len(REQUESTED_ORDER))

    def test_labels_and_keys_are_unique(self):
        keys = [key for key, _label, _width in failure_log.TABLE_COLUMNS]
        labels = [label for _key, label, _width in failure_log.TABLE_COLUMNS]
        self.assertEqual(len(set(keys)), len(keys))
        self.assertEqual(len(set(labels)), len(labels))

    def test_every_column_is_asked_in_the_form(self):
        """У каждой графы есть поле формы, и наоборот."""
        shown = {key for key, _label, _width in failure_log.TABLE_COLUMNS}
        asked = {key for key, _label, _kind, _hint in failure_log.FORM_FIELDS}
        self.assertEqual(shown, asked)
        self.assertEqual(failure_log.FIELDS, tuple(REQUESTED_ORDER))

    def test_form_field_kinds_are_known(self):
        """Вид поля выбирает форму: список или строку ввода."""
        kinds = {kind for _key, _label, kind, _hint in failure_log.FORM_FIELDS}
        self.assertEqual(kinds - {'date', 'text', 'choice', 'criticality',
                                  'yes_no'}, set())

    def test_form_labels_are_unique(self):
        labels = [label for _key, label, _kind, _hint in failure_log.FORM_FIELDS]
        self.assertEqual(len(set(labels)), len(labels))

    def test_criticality_and_resolved_are_lists(self):
        """Эти графы выбираются из списка, а не вписываются словами."""
        kinds = {key: kind for key, _label, kind, _hint
                 in failure_log.FORM_FIELDS}
        self.assertEqual(kinds['criticality'], 'criticality')
        self.assertEqual(kinds['resolved'], 'yes_no')

    def test_table_index_counts_the_number_column(self):
        """Первой графой идёт «№», поэтому индекс на единицу больше позиции."""
        self.assertEqual(failure_log.table_index('detected_date'), 1)
        self.assertEqual(failure_log.table_index('note'),
                         1 + column('note'))

    def test_table_index_matches_table_cells(self):
        """Номер графы в строке таблицы — тот же список, что у table_cells."""
        cells = failure_log.table_cells(FAILURE_ROW)
        for key, _label, _width in failure_log.TABLE_COLUMNS:
            self.assertEqual(failure_log.table_index(key) - 1, column(key))
            self.assertTrue(cells[column(key)], key)


class TestReading(unittest.TestCase):
    def test_value_reads_by_field_name(self):
        self.assertEqual(failure_log.value(FAILURE_ROW, 'criticality'),
                         'средняя')
        self.assertEqual(failure_log.value(FAILURE_ROW, 'document'),
                         'Аварийный журнал')

    def test_unknown_field_is_empty(self):
        self.assertEqual(failure_log.value(FAILURE_ROW, 'чего-нет'), '')

    def test_short_row_does_not_shift_values(self):
        """Строка без отметки о фото читается пустой, а не чужим значением."""
        short = FAILURE_ROW[:8]
        self.assertFalse(failure_log.has_photo(short))
        self.assertEqual(failure_log.value(short, 'event_type'),
                         'Нарушение работы оборудования')

    def test_dictionary_source_reads_the_same(self):
        """Запасная выборка приходит словарём по своему списку колонок."""
        source = dict(zip(failure_log.RECORD_COLUMNS, FAILURE_ROW))
        self.assertEqual(failure_log.value(source, 'reason'), 'Засорение фильтра')
        cells = failure_log.table_cells(source)
        self.assertEqual(cells[column('resolved')], 'да')
        self.assertEqual(len(cells), len(failure_log.TABLE_COLUMNS))

    def test_none_and_spaces_become_a_dash(self):
        cells = failure_log.table_cells(row_with('reason', '   '))
        self.assertEqual(cells[column('reason')], failure_log.EMPTY)
        cells = failure_log.table_cells(row_with('note', None))
        self.assertEqual(cells[column('note')], failure_log.EMPTY)

    def test_date_is_shown_as_in_the_documents(self):
        """ISO из формы приводится к виду «ДД.ММ.ГГГГ»."""
        self.assertEqual(failure_log.table_cells(FAILURE_ROW)[0], '18.04.2024')

    def test_date_written_by_hand_is_shown_as_written(self):
        """Дату могли вписать словами — выдумывать её вид нельзя."""
        self.assertEqual(failure_log.date_text('18.04.2024'), '18.04.2024')
        self.assertEqual(failure_log.date_text('апрель 2024'), 'апрель 2024')
        self.assertEqual(failure_log.date_text(''), '')

    def test_notes_tell_about_the_photo(self):
        """Фото в графах нет — о нём говорит отметка в примечаниях."""
        cells = failure_log.table_cells(row_with('has_photo', True))
        self.assertEqual(cells[column('note')],
                         'Акт №12; рекомендация: заменить фильтрующий элемент'
                         f' · {failure_log.PHOTO_MARK}')
        cells = failure_log.table_cells(
            row_with('note', '', base=row_with('has_photo', True)))
        self.assertEqual(cells[column('note')], failure_log.PHOTO_MARK)

    def test_notes_without_a_photo_stay_text(self):
        cells = failure_log.table_cells(FAILURE_ROW)
        self.assertNotIn(failure_log.PHOTO_MARK, cells[column('note')])

    def test_photo_mark_comes_from_the_choice(self):
        self.assertTrue(failure_log.has_photo(PHOTO_ONLY_ROW))
        self.assertFalse(failure_log.has_photo(FAILURE_ROW))
        self.assertFalse(failure_log.has_photo(row_with('has_photo', None)))

    def test_form_values_give_every_graph(self):
        values = failure_log.form_values(FAILURE_ROW)
        self.assertEqual(set(values), set(failure_log.FIELDS))
        self.assertEqual(values['event_type'], 'Нарушение работы оборудования')

    def test_form_values_of_a_short_record_are_empty(self):
        """Поля, которых в строке нет, — пустые, а не чужие значения."""
        values = failure_log.form_values(FAILURE_ROW[:1])
        self.assertEqual(set(values.values()), {''})


class TestWords(unittest.TestCase):
    """Критичность и признак устранения — слова из короткого списка."""

    def test_criticality_accepts_the_three_words(self):
        for word in failure_log.CRITICALITY_LEVELS:
            self.assertEqual(failure_log.parse_criticality(word), word)
        self.assertEqual(failure_log.parse_criticality('Средняя'), 'средняя')
        self.assertEqual(failure_log.parse_criticality(' ВЫСОКАЯ '), 'высокая')

    def test_criticality_is_empty_when_not_stated(self):
        self.assertEqual(failure_log.parse_criticality(''), '')
        self.assertEqual(failure_log.parse_criticality(None), '')

    def test_criticality_rejects_other_text(self):
        """«средняя (устранено)» в графе неотличимо от описки."""
        with self.assertRaises(failure_log.FailureError):
            failure_log.parse_criticality('средняя (устранено)')

    def test_resolved_accepts_yes_and_no(self):
        self.assertEqual(failure_log.parse_resolved('Да'), 'да')
        self.assertEqual(failure_log.parse_resolved('нет'), 'нет')
        self.assertEqual(failure_log.parse_resolved(''), '')

    def test_resolved_rejects_other_text(self):
        with self.assertRaises(failure_log.FailureError):
            failure_log.parse_resolved('частично')

    def test_event_type_is_required(self):
        """Отказ без типа события — запись, которую нельзя прочитать."""
        self.assertEqual(failure_log.parse_event(' Нарушение работы '),
                         'Нарушение работы')
        with self.assertRaises(failure_log.FailureError):
            failure_log.parse_event('   ')

    def test_suggested_event_types_start_with_the_example(self):
        self.assertIn('Нарушение работы оборудования', failure_log.EVENT_TYPES)


class TestValues(unittest.TestCase):
    """Значения граф для записи в базу."""

    def test_empty_lines_become_null(self):
        values = failure_log.values({'reason': '  ', 'note': None,
                                     'document': ''})
        self.assertIsNone(values['reason'])
        self.assertIsNone(values['note'])
        self.assertIsNone(values['document'])

    def test_list_columns_keep_the_empty_string(self):
        """Критичность и признак устранения в базе NOT NULL."""
        values = failure_log.values({'criticality': '', 'resolved': ' '})
        self.assertEqual(values['criticality'], '')
        self.assertEqual(values['resolved'], '')

    def test_values_are_stripped(self):
        self.assertEqual(
            failure_log.values({'document': ' Аварийный журнал '})['document'],
            'Аварийный журнал')

    def test_values_round_trip_through_the_form(self):
        """Что форма показала, то и записывается: круговорот не теряет граф."""
        entered = failure_log.form_values(FAILURE_ROW)
        self.assertEqual(failure_log.values(entered),
                         {'detected_date': '2024-04-18',
                          'event_type': 'Нарушение работы оборудования',
                          'reason': 'Засорение фильтра',
                          'criticality': 'средняя',
                          'resolved': 'да',
                          'document': 'Аварийный журнал',
                          'note': 'Акт №12; рекомендация: заменить '
                                  'фильтрующий элемент'})

    def test_empty_record_saves_nothing(self):
        """Пустая форма пишет NULL, а графы из списка — только пустую строку."""
        values = failure_log.values({})
        self.assertEqual(values['document'], None)
        self.assertEqual(values['reason'], None)
        self.assertEqual(values['criticality'], '')
        self.assertEqual(values['resolved'], '')


class TestPhotoFile(unittest.TestCase):
    """Приложенный файл: расширение определяется по содержимому."""

    def test_known_formats(self):
        self.assertEqual(failure_log.photo_extension(b'\x89PNG\r\n\x1a\n...'),
                         '.png')
        self.assertEqual(failure_log.photo_extension(b'\xff\xd8\xff\xe0...'),
                         '.jpg')
        self.assertEqual(failure_log.photo_extension(b'GIF89a...'), '.gif')
        self.assertEqual(failure_log.photo_extension(b'BM......'), '.bmp')
        self.assertEqual(failure_log.photo_extension(b'RIFF\x00\x00\x00\x00WEBPVP8 '),
                         '.webp')
        self.assertEqual(failure_log.photo_extension(b'%PDF-1.4'), '.pdf')

    def test_unknown_format_is_opened_as_a_picture(self):
        self.assertEqual(failure_log.photo_extension(b'\x00\x01\x02'), '.jpg')
        self.assertEqual(failure_log.photo_extension(None), '.jpg')

    def test_document_default_is_the_accident_log(self):
        self.assertEqual(failure_log.DEFAULT_DOCUMENT, 'Аварийный журнал')


if __name__ == '__main__':
    unittest.main()
