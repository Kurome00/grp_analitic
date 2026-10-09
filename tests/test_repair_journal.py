"""Ремонтный журнал: порядок граф, чтение строки, остаточный ресурс после ремонта.

Тесты фиксируют:

* порядок граф таблицы — он задан заказчиком и повторяет бумажный журнал
  (дата ремонта, место работы, что заменено, причина, наработка до ремонта,
  остаточный ресурс, документ-основание, ответственный, вид работ,
  примечание), поэтому перестановка граф ломает документ, а не только экран;
* прежние поля записи («Лида.xlsx»: дата, обозначение, тип, модель,
  изготовитель, вид работ, причина, ответственный) сохраняют свои индексы в
  строке выборки — по ним заполняются «Замены.xlsx», отчёт Word и расчёт;
* новые графы описаны одним списком: у каждой есть и колонка в базе, и поле
  формы, иначе вводить было бы некуда;
* чтение идёт по имени поля, а не по номеру: короткая строка (запасная
  выборка, защитный кортеж) не роняет чтение и не сдвигает значения;
* остаточный ресурс после ремонта приложение знает само: сброс срока запчасти
  возвращает ей нормативный срок, полная замена оборудования — назначенный
  срок службы новой единицы; при «не нормируется» остатка нет (прочерк).

Тесты не требуют базы: строка выборки собирается вручную.

Запуск: py -m unittest discover -s tests -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import equipment_card  # noqa: E402
from core import repair_journal  # noqa: E402
from core.timefmt import DurationError  # noqa: E402

# Строка выборки get_replacements_detailed в порядке DETAILED_COLUMNS.
DETAILED_ROW = (5, '2023-05-12', 'С-150', 'Регулятор', 'КРОН-150',
                'ООО «Газпроммаш»', 'Плановый ремонт', 'Износ седла',
                'Волков В.В.', 3, 7, 'part', 12,
                '12000', '5 лет', 'Акт №4 от 12.05.2023', 'плановый',
                'КРОН-150', 'Седло клапана', '3')

# Та же запись в порядке BY_GRP_COLUMNS: запасная выборка без привязки к
# оборудованию и без эффекта.
BY_GRP_ROW = (5, '2023-05-12', 'С-150', 'Регулятор', 'КРОН-150',
              'ООО «Газпроммаш»', 'Плановый ремонт', 'Износ седла',
              'Волков В.В.', '12000', '5 лет', 'Акт №4 от 12.05.2023',
              'плановый')

# Порядок граф, заданный заказчиком. Первой идёт «№» — номер записи в списке.
REQUESTED_ORDER = ('replace_date', 'scheme_number', 'part', 'reason',
                   'hours_before', 'residual_after', 'document', 'supervisor',
                   'work_type', 'note')


def column(key: str) -> int:
    """Номер графы в table_cells (без ведущей «№»)."""
    return [name for name, _label, _width
            in repair_journal.TABLE_COLUMNS].index(key)


def row_with(key: str, value, base=DETAILED_ROW):
    """Копия строки со значением одного поля."""
    cells = list(base)
    cells[repair_journal.DETAILED_COLUMNS.index(key)] = value
    return tuple(cells)


class TestColumns(unittest.TestCase):
    def test_table_follows_the_requested_order(self):
        """Порядок граф — требование к документу, а не оформление экрана."""
        keys = [key for key, _label, _width in repair_journal.TABLE_COLUMNS]
        self.assertEqual(keys[:len(REQUESTED_ORDER)], list(REQUESTED_ORDER))

    def test_note_is_the_last_document_column(self):
        """Примечание — последняя графа журнала."""
        keys = [key for key, _label, _width in repair_journal.TABLE_COLUMNS]
        self.assertEqual(keys.index('note'), len(REQUESTED_ORDER) - 1)

    def test_nothing_follows_the_note(self):
        """В журнале ровно те графы, что заказаны, — лишних быть не должно."""
        keys = [key for key, _label, _width in repair_journal.TABLE_COLUMNS]
        self.assertEqual(keys, list(REQUESTED_ORDER))
        self.assertEqual(len(repair_journal.TABLE_COLUMNS),
                         len(REQUESTED_ORDER))

    def test_labels_and_keys_are_unique(self):
        keys = [key for key, _label, _width in repair_journal.TABLE_COLUMNS]
        labels = [label for _key, label, _width in repair_journal.TABLE_COLUMNS]
        self.assertEqual(len(set(keys)), len(keys))
        self.assertEqual(len(set(labels)), len(labels))

    def test_every_extra_column_is_shown_and_asked(self):
        """У новой графы есть и колонка в таблице, и поле формы."""
        shown = {key for key, _label, _width in repair_journal.TABLE_COLUMNS}
        asked = {key for key, _label, _hint in repair_journal.FORM_FIELDS}
        self.assertEqual(set(repair_journal.EXTRA_COLUMNS) - shown, set())
        self.assertEqual(set(repair_journal.EXTRA_COLUMNS) - asked, set())

    def test_form_labels_are_unique(self):
        labels = [label for _key, label, _hint in repair_journal.FORM_FIELDS]
        self.assertEqual(len(set(labels)), len(labels))

    def test_old_record_fields_keep_their_places(self):
        """По первым девяти полям читают «Замены.xlsx», отчёт и расчёт."""
        self.assertEqual(
            repair_journal.BY_GRP_COLUMNS[:9],
            ('id', 'replace_date', 'part_number', 'equipment_type', 'model',
             'manufacturer', 'work_type', 'reason', 'supervisor'))

    def test_extra_columns_are_appended_at_the_end(self):
        """Новые графы дописаны в конец — прежние индексы не сдвинулись."""
        self.assertEqual(
            repair_journal.RECORD_COLUMNS[-len(repair_journal.EXTRA_COLUMNS):],
            repair_journal.EXTRA_COLUMNS)
        self.assertEqual(
            repair_journal.BY_GRP_COLUMNS[-len(repair_journal.EXTRA_COLUMNS):],
            repair_journal.EXTRA_COLUMNS)

    def test_table_index_counts_the_number_column(self):
        """Первой графой идёт «№», поэтому индекс на единицу больше позиции."""
        self.assertEqual(repair_journal.table_index('replace_date'), 1)
        self.assertEqual(repair_journal.table_index('part'),
                         1 + column('part'))

    def test_table_index_matches_table_cells(self):
        """Номер графы в строке таблицы — тот же список, что у table_cells."""
        cells = repair_journal.table_cells(DETAILED_ROW)
        for key, _label, _width in repair_journal.TABLE_COLUMNS:
            index = repair_journal.table_index(key) - 1
            self.assertEqual(index, column(key))
            self.assertTrue(cells[index], key)


class TestReading(unittest.TestCase):
    def test_value_reads_by_field_name(self):
        self.assertEqual(repair_journal.value(DETAILED_ROW, 'document'),
                         'Акт №4 от 12.05.2023')
        self.assertEqual(repair_journal.value(DETAILED_ROW, 'notes-нет'), '')
        self.assertEqual(repair_journal.value(DETAILED_ROW, 'scheme_number'), '3')

    def test_unknown_field_is_empty(self):
        self.assertEqual(repair_journal.value(DETAILED_ROW, 'чего-нет'), '')

    def test_short_row_does_not_shift_values(self):
        """Строка без новых колонок читается пустой, а не чужими значениями."""
        short = DETAILED_ROW[:13]
        self.assertEqual(repair_journal.value(short, 'hours_before'), '')
        self.assertEqual(repair_journal.value(short, 'replace_date'),
                         '2023-05-12')

    def test_dictionary_source_reads_the_same(self):
        """Запасная выборка приходит словарём по своему списку колонок."""
        source = dict(zip(repair_journal.BY_GRP_COLUMNS, BY_GRP_ROW))
        self.assertEqual(repair_journal.value(source, 'note'), 'плановый')
        cells = repair_journal.table_cells(source)
        self.assertEqual(cells[column('document')], 'Акт №4 от 12.05.2023')
        self.assertEqual(cells[column('note')], 'плановый')
        self.assertEqual(len(cells), len(repair_journal.TABLE_COLUMNS))

    def test_none_and_spaces_become_empty(self):
        cells = repair_journal.table_cells(row_with('note', '   '))
        self.assertEqual(cells[column('note')], repair_journal.EMPTY)
        cells = repair_journal.table_cells(row_with('document', None))
        self.assertEqual(cells[column('document')], repair_journal.EMPTY)

    def test_date_is_shown_as_in_the_documents(self):
        """ISO из демо-данных и импорта приводится к виду «ДД.ММ.ГГГГ»."""
        self.assertEqual(repair_journal.date_text('2023-05-12'), '12.05.2023')
        self.assertEqual(repair_journal.date_text('15.03.2024'), '15.03.2024')
        self.assertEqual(repair_journal.table_cells(DETAILED_ROW)[0], '12.05.2023')

    def test_date_without_a_day_is_shown_as_written(self):
        """День в такой записи неизвестен — выдумывать его нельзя."""
        self.assertEqual(repair_journal.date_text('05.2023'), '05.2023')
        self.assertEqual(repair_journal.date_text(''), '')

    def test_part_cell_shows_name_and_designation(self):
        cells = repair_journal.table_cells(DETAILED_ROW)
        self.assertEqual(cells[column('part')], 'Седло клапана · С-150')

    def test_part_cell_falls_back_to_the_designation(self):
        """У записи без привязки название взять негде — видно обозначение."""
        cells = repair_journal.table_cells(row_with('part_name', ''))
        self.assertEqual(cells[column('part')], 'С-150')

    def test_part_cell_of_empty_record_is_a_dash(self):
        row = row_with('part_name', '')
        row = list(row)
        row[repair_journal.DETAILED_COLUMNS.index('part_number')] = ''
        self.assertEqual(
            repair_journal.table_cells(tuple(row))[column('part')],
            repair_journal.EMPTY)

    def test_scheme_number_comes_from_the_equipment(self):
        cells = repair_journal.table_cells(row_with('scheme_number', '11'))
        self.assertEqual(cells[column('scheme_number')], '11')

    def test_effect_of_a_record_is_readable_from_the_record(self):
        """Влияние на срок в таблице не показывается, но о нём предупреждают
        при удалении — значение читается из самой записи."""
        self.assertEqual(
            repair_journal.value(DETAILED_ROW, 'effect',
                                 repair_journal.RECORD_COLUMNS), 'part')
        self.assertEqual(
            repair_journal.value(BY_GRP_ROW, 'effect',
                                 repair_journal.BY_GRP_COLUMNS), '')

    def test_form_values_carry_the_extra_columns(self):
        values = repair_journal.form_values(DETAILED_ROW)
        self.assertEqual(values['hours_before'], '12000')
        self.assertEqual(values['document'], 'Акт №4 от 12.05.2023')
        self.assertEqual(set(values), set(repair_journal.EXTRA_COLUMNS))

    def test_form_values_of_a_short_record_are_empty(self):
        values = repair_journal.form_values(DETAILED_ROW[:13])
        self.assertEqual(set(values.values()), {''})


class TestExtras(unittest.TestCase):
    """Значения новых граф для записи в базу."""

    def test_empty_lines_become_null(self):
        self.assertEqual(repair_journal.extras({'note': '  ', 'document': None}),
                         {'hours_before': None, 'residual_after': None,
                          'document': None, 'note': None})

    def test_values_are_stripped(self):
        self.assertEqual(repair_journal.extras({'document': ' Акт №4 '})['document'],
                         'Акт №4')

    def test_extras_round_trip_through_the_form(self):
        """Что форма показала, то и записывается: круговорот не теряет граф."""
        fields = repair_journal.form_values(DETAILED_ROW)
        self.assertEqual(repair_journal.extras(fields),
                         {'hours_before': '12000', 'residual_after': '5 лет',
                          'document': 'Акт №4 от 12.05.2023',
                          'note': 'плановый'})

    def test_empty_record_saves_nothing(self):
        self.assertEqual(
            set(repair_journal.extras({}).values()), {None})


class TestResidual(unittest.TestCase):
    """Остаточный ресурс после ремонта, лет."""

    def test_part_replacement_returns_the_norm(self):
        self.assertEqual(repair_journal.residual_after('part', 5.0), '5 лет')

    def test_part_replacement_without_a_part_is_empty(self):
        self.assertEqual(repair_journal.residual_after('part', None), '')

    def test_equipment_replacement_returns_the_passport_life(self):
        self.assertEqual(
            repair_journal.residual_after('equipment', assigned_life='20'), '20')

    def test_journal_only_record_has_no_residual(self):
        self.assertEqual(repair_journal.residual_after(''), '')

    def test_not_normed_life_leaves_the_cell_empty(self):
        """Ресурса нет, сравнивать не с чем — в таблице будет прочерк."""
        for text in ('не нормируется', 'НЕНОРМИРУЕТСЯ', 'не нормирован.'):
            self.assertEqual(
                repair_journal.residual_after('equipment', assigned_life=text),
                '', repr(text))

    def test_equipment_replacement_without_a_passport_is_empty(self):
        self.assertEqual(
            repair_journal.residual_after('equipment', assigned_life=''), '')

    def test_parse_residual_accepts_years_and_the_words(self):
        self.assertEqual(repair_journal.parse_residual('5'), '5')
        self.assertEqual(repair_journal.parse_residual(' 5 лет '), '5 лет')
        self.assertEqual(repair_journal.parse_residual(''), '')
        self.assertEqual(repair_journal.parse_residual('Не нормируется'),
                         equipment_card.NOT_NORMED)

    def test_parse_residual_rejects_other_text(self):
        """«5 лет, продлён» в графе ресурса неотличимо от описки."""
        with self.assertRaises(DurationError):
            repair_journal.parse_residual('5 лет, продлён')


if __name__ == '__main__':
    unittest.main()
