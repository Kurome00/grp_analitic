"""Паспортные сведения единицы оборудования: поля, порядок граф, чтение строки.

Тесты фиксируют:

* DETAIL_COLUMNS покрывает все колонки, которые база добавляет в таблицу
  `equipment`, и не содержит повторов — иначе поле молча пропадало бы из
  формы или из таблицы оборудования;
* ROW_COLUMNS начинается с id, name, install_date, removal_date: по этим
  четырём позициям читают расчёт, отчёт и интерфейс, и сдвиг сломал бы их;
* в таблице и в форме одна и та же единица описана одними полями — графа,
  которую нельзя заполнить, или поле, которого не видно, — это ошибка;
* чтение идёт по индексу, посчитанному от ROW_COLUMNS, поэтому короткая
  строка (защитный запасной кортеж в вызывающем коде) не роняет чтение;
* номер графы в строке таблицы считается вместе с ведущей графой «№»;
* назначенный срок службы может быть не назначен документацией — тогда в
  графе стоит «не нормируется» (в любом написании), а фактическая наработка
  показывается прочерком: сравнивать её не с чем;
* наименование узнаётся по написанию, а не по буквам: по этой проверке
  каталог не даёт завести одну модель дважды.

Тесты не требуют базы: строка таблицы собирается вручную.

Запуск: py -m unittest discover -s tests -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import equipment_card  # noqa: E402
from core.timefmt import DurationError  # noqa: E402

# Значения в порядке ROW_COLUMNS: id, name, install_date, removal_date,
# затем DETAIL_COLUMNS.
ROW = (17, 'Регулятор давления газа комбинированный КРОН-150', '2016-06-01',
       None, 'КРОН-150', 'ООО «Газпроммаш»', '150', '1', '3', '20',
       '100000', '48000', 'слабое звено расчёта')

# Единица, которой документация срок службы не назначила. Наработка в паспорте
# при этом может быть записана — в таблице её всё равно заменяет прочерк.
ROW_NOT_NORMED = (18, 'Газопровод обвязки ГРП', '2011-05-04', None,
                  '', 'ООО «Газпроммаш»', '50', '1', '4',
                  'не нормируется', '', '41000', '')

# Позиция графы в строке таблицы: table_view отдаёт значения без ведущей «№».
def column(key: str) -> int:
    """Номер графы в table_view (без ведущей «№»)."""
    return [name for name, _label, _width
            in equipment_card.TABLE_COLUMNS].index(key)


def row_with(key: str, value, base=ROW_NOT_NORMED):
    """Копия строки со значением одной графы."""
    cells = list(base)
    cells[equipment_card.ROW_COLUMNS.index(key)] = value
    return tuple(cells)


class TestColumns(unittest.TestCase):
    def test_details_have_no_repeats(self):
        self.assertEqual(len(set(equipment_card.DETAIL_COLUMNS)),
                         len(equipment_card.DETAIL_COLUMNS))

    def test_row_columns_start_with_the_four_old_ones(self):
        self.assertEqual(equipment_card.ROW_COLUMNS[:4],
                         ('id', 'name', 'install_date', 'removal_date'))

    def test_row_columns_are_the_old_ones_plus_details(self):
        self.assertEqual(equipment_card.ROW_COLUMNS[4:],
                         equipment_card.DETAIL_COLUMNS)

    def test_every_detail_column_has_a_table_column(self):
        """У каждого паспортного поля есть графа — иначе вводить некуда."""
        shown = {key for key, _label, _width in equipment_card.TABLE_COLUMNS}
        self.assertEqual(set(equipment_card.DETAIL_COLUMNS) - shown, set())

    def test_every_detail_column_has_a_form_field(self):
        """У каждого паспортного поля есть поле формы — иначе не заполнить."""
        asked = {key for key, _label, _hint in equipment_card.FORM_FIELDS}
        self.assertEqual(set(equipment_card.DETAIL_COLUMNS) - asked, set())

    def test_equipment_table_shows_the_install_date(self):
        """Дата монтажа — паспортная графа, а не служебное поле."""
        shown = [key for key, _label, _width in equipment_card.TABLE_COLUMNS]
        self.assertIn('install_date', shown)

    def test_removal_date_is_neither_shown_nor_asked(self):
        """Дату снятия пользователь не видит и не вводит: её ставит замена
        оборудования целиком, а не паспорт единицы."""
        shown = [key for key, _label, _width in equipment_card.TABLE_COLUMNS]
        asked = [key for key, _label, _hint in equipment_card.FORM_FIELDS]
        self.assertNotIn('removal_date', shown)
        self.assertNotIn('removal_date', asked)

    def test_removal_date_stays_in_the_row(self):
        """По этой колонке строки выборки расчёт отличает снятое оборудование."""
        self.assertIn('removal_date', equipment_card.ROW_COLUMNS)
        self.assertEqual(equipment_card.value(ROW, 'removal_date'), '')
        self.assertEqual(equipment_card.form_item(ROW)['removal_date'], '')

    def test_table_has_no_id_column(self):
        """Пользователь не должен видеть идентификатор записи."""
        self.assertNotIn('id', [key for key, _l, _w
                                in equipment_card.TABLE_COLUMNS])

    def test_table_labels_are_unique(self):
        labels = [label for _key, label, _width in equipment_card.TABLE_COLUMNS]
        self.assertEqual(len(set(labels)), len(labels))

    def test_form_labels_are_unique(self):
        labels = [label for _key, label, _hint in equipment_card.FORM_FIELDS]
        self.assertEqual(len(set(labels)), len(labels))


class TestReading(unittest.TestCase):
    def test_value_reads_by_column_name(self):
        self.assertEqual(equipment_card.value(ROW, 'model'), 'КРОН-150')
        self.assertEqual(equipment_card.value(ROW, 'scheme_number'), '3')

    def test_value_of_unknown_field_is_empty(self):
        self.assertEqual(equipment_card.value(ROW, 'нет-такого-поля'), '')

    def test_short_row_does_not_break_reading(self):
        """Строка без паспортных колонок (запасной кортеж) читается как пустая."""
        short = ROW[:4]
        self.assertEqual(equipment_card.value(short, 'model'), '')
        self.assertEqual(equipment_card.value(short, 'name'), ROW[1])

    def test_none_and_spaces_become_empty(self):
        row = tuple([''] * 4) + ('', None, '  ',) + ('',) * 6
        self.assertEqual(equipment_card.values(row)['model'], '')
        self.assertEqual(equipment_card.values(row)['dn'], '')

    def test_values_returns_all_detail_fields(self):
        self.assertEqual(set(equipment_card.values(ROW)),
                         set(equipment_card.DETAIL_COLUMNS))

    def test_values_are_stripped(self):
        """Форма сохраняет значения обрезанными — сравнение «до/после» точное."""
        row = tuple([''] * 4) + ('  КРОН-50  ',) + ('',) * 8
        self.assertEqual(equipment_card.values(row)['model'], 'КРОН-50')

    def test_table_view_follows_column_order(self):
        view = equipment_card.table_view(ROW)
        self.assertEqual(len(view), len(equipment_card.TABLE_COLUMNS))
        self.assertEqual(view[0], ROW[1])                 # наименование
        self.assertEqual(view[1], 'КРОН-150')             # тип (модель)
        self.assertEqual(view[2], 'ООО «Газпроммаш»')     # изготовитель
        self.assertEqual(view[6], '2016-06-01')           # дата монтажа

    def test_table_view_shows_dash_for_empty(self):
        """Незаполненная графа показывается прочерком, а не пустой клеткой."""
        self.assertEqual(
            equipment_card.table_view(row_with('dn', '', ROW))[column('dn')],
            equipment_card.EMPTY)

    def test_table_index_counts_the_number_column(self):
        """Первой графой идёт «№», поэтому индекс на единицу больше позиции."""
        self.assertEqual(equipment_card.table_index('name'), 1)
        self.assertEqual(
            equipment_card.table_index('install_date'),
            1 + [key for key, _l, _w
                 in equipment_card.TABLE_COLUMNS].index('install_date'))

    def test_table_index_matches_table_view(self):
        """table_view отдаёт графы без «№»: её значение стоит на месте 0."""
        for key in equipment_card.DETAIL_COLUMNS:
            index = equipment_card.table_index(key) - 1
            self.assertEqual(equipment_card.table_view(ROW)[index],
                             equipment_card.value(ROW, key) or equipment_card.EMPTY)


class TestFormItem(unittest.TestCase):
    def test_form_item_carries_every_field(self):
        item = equipment_card.form_item(ROW)
        self.assertEqual(item['id'], 17)
        self.assertEqual(item['name'], ROW[1])
        self.assertEqual(item['install_date'], '2016-06-01')
        self.assertEqual(item['removal_date'], '')
        self.assertEqual(item['model'], 'КРОН-150')

    def test_details_of_form_item_round_trip(self):
        """Что форма отдала, то и записывается: круговорот не теряет полей."""
        item = equipment_card.form_item(ROW)
        self.assertEqual(equipment_card.details(item),
                         equipment_card.values(ROW))

    def test_details_of_empty_mapping_are_empty_strings(self):
        self.assertEqual(set(equipment_card.details({}).values()), {''})

    def test_details_ignores_unknown_keys(self):
        self.assertEqual(equipment_card.details({'модель': 'КРОН-150'}),
                         {key: '' for key in equipment_card.DETAIL_COLUMNS})


class TestNotNormed(unittest.TestCase):
    """Срок службы не назначен: «не нормируется» вместо числа лет."""

    def test_written_forms_are_the_same_value(self):
        for text in ('не нормируется', 'Не нормируется.', 'НЕ НОРМИРУЕТСЯ',
                     'ненормируется', 'не нормирован', 'не нормировано',
                     '  не  нормируется  '):
            self.assertTrue(equipment_card.is_not_normed(text), repr(text))

    def test_numbers_and_other_text_are_not_that_value(self):
        for text in ('', None, '20', '20 лет', 'не нормируется по документации'):
            self.assertFalse(equipment_card.is_not_normed(text), repr(text))

    def test_written_form_is_brought_to_one_spelling(self):
        """Иначе в таблице стояли бы разные записи одного и того же значения."""
        self.assertEqual(
            equipment_card.values(row_with('assigned_life', 'Не нормирован.'))['assigned_life'],
            equipment_card.NOT_NORMED)
        self.assertEqual(
            equipment_card.details({'assigned_life': ' НЕНОРМИРУЕТСЯ '})['assigned_life'],
            equipment_card.NOT_NORMED)

    def test_life_is_shown_as_written(self):
        self.assertEqual(
            equipment_card.table_view(ROW_NOT_NORMED)[column('assigned_life')],
            equipment_card.NOT_NORMED)

    def test_actual_hours_is_dash_when_life_is_not_normed(self):
        """Срок не нормирован — фактическую наработку показывать не с чем."""
        self.assertEqual(
            equipment_card.table_view(ROW_NOT_NORMED)[column('actual_hours')],
            equipment_card.EMPTY)

    def test_same_rule_in_the_form_list(self):
        """Список оборудования в форме ГРП показывает единицу так же."""
        self.assertEqual(
            equipment_card.table_cells(
                equipment_card.form_item(ROW_NOT_NORMED))[column('actual_hours')],
            equipment_card.EMPTY)

    def test_actual_hours_is_shown_when_life_is_a_number_of_years(self):
        self.assertEqual(equipment_card.table_view(ROW)[column('actual_hours')],
                         '48000')

    def test_empty_life_shows_actual_hours(self):
        """Прочерк — признак «не нормируется», а не незаполненного срока."""
        self.assertEqual(
            equipment_card.table_view(
                row_with('assigned_life', ''))[column('actual_hours')], '41000')

    def test_parse_life_accepts_years_and_the_words(self):
        self.assertEqual(equipment_card.parse_life('20'), '20')
        self.assertEqual(equipment_card.parse_life(' 20 лет '), '20 лет')
        self.assertEqual(equipment_card.parse_life(''), '')
        self.assertEqual(equipment_card.parse_life('Не нормируется'),
                         equipment_card.NOT_NORMED)

    def test_parse_life_rejects_other_text(self):
        """«20 лет, продлён» в графе срока неотличимо от описки."""
        with self.assertRaises(DurationError):
            equipment_card.parse_life('20 лет, продлён')
        with self.assertRaises(DurationError):
            equipment_card.parse_life('не нармируется')


class TestNames(unittest.TestCase):
    """Одно и то же оборудование узнаётся по наименованию.

    По этой проверке каталог не даёт завести модель второй раз: разными
    записями «РДС-32» и «рдс-32» разошлись бы и запчасти, и сроки.
    """

    def test_writing_differences_are_the_same_name(self):
        self.assertTrue(equipment_card.same_name('РДС-32', 'рдс-32'))
        self.assertTrue(equipment_card.same_name(' РДС-32 ', 'РДС  -  32'))
        self.assertTrue(equipment_card.same_name('Мембрана', 'Мембрана'))

    def test_yo_letter_is_the_same_letter(self):
        self.assertTrue(equipment_card.same_name('Фильтр ФЭЁ', 'фильтр фэе'))

    def test_other_names_are_different(self):
        self.assertFalse(equipment_card.same_name('РДС-32', 'РДС-50'))
        self.assertFalse(equipment_card.same_name('РДС-32', 'РДБК1-50'))

    def test_empty_name_matches_nothing(self):
        """Иначе пустая строка «совпала» бы с каждой незаполненной записью."""
        self.assertFalse(equipment_card.same_name('', ''))
        self.assertFalse(equipment_card.same_name('   ', None))
        self.assertFalse(equipment_card.same_name('РДС-32', ''))

    def test_find_by_name_returns_the_row(self):
        rows = [ROW, row_with('name', 'РДС-32', base=ROW_NOT_NORMED)]
        self.assertIs(equipment_card.find_by_name(rows, 'рдс-32'), rows[1])
        self.assertIs(equipment_card.find_by_name(rows, ROW[1]), rows[0])

    def test_find_by_name_returns_nothing_for_a_new_name(self):
        """Новой модели в каталоге нет — значит, её можно завести."""
        self.assertIsNone(equipment_card.find_by_name([ROW], 'РДС-32'))
        self.assertIsNone(equipment_card.find_by_name([ROW], ''))
        self.assertIsNone(equipment_card.find_by_name([], 'РДС-32'))

    def test_find_by_name_reads_the_name_column(self):
        """Наименование читается по ROW_COLUMNS: сдвиг колонок его не сломает."""
        shifted = (19,) + ROW[1:]
        self.assertIs(equipment_card.find_by_name([shifted], ROW[1]), shifted)


if __name__ == '__main__':
    unittest.main()
