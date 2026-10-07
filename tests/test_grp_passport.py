"""Паспорт ГРП: описание полей, чтение из строки таблицы `grp`, строки отчёта.

Тесты фиксируют:

* описание полей (FIELDS) покрывает все колонки паспорта и не содержит
  повторов — иначе поле молча пропадало бы из формы или из отчёта;
* подписи и порядок полей совпадают с разделом 1 паспорта ГРП: наименование,
  адрес, регистрационный номер, даты, линии редуцирования, регулятор, материалы,
  покрытие, изготовитель, проектный срок, газопровод, «закольцован с»;
* чтение идёт по индексу, посчитанному от ROW_COLUMNS, поэтому короткая строка
  (защитный запасной кортеж в вызывающем коде) не роняет ни форму, ни отчёт;
* незаполненное поле в отчёте показывается прочерком, а срок — словами
  («20 лет»), а не десятичной дробью.

Тесты не требуют базы: строка таблицы собирается вручную.

Запуск: py -m unittest discover -s tests -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import grp_passport  # noqa: E402

# Значения из образца паспорта ГРП №26 (г. Гродно) — в порядке FIELDS.
SAMPLE = {
    'type': 'ГРП №26',
    'address': 'г. Гродно, ул. Лизы Чайкиной, 24',
    'reg_number': '29-53-0544 ГРП',
    'accept_date': '01.1981',
    'commission_date': '10.2007',
    'actual_life': 44.5,
    'lines_count': 1,
    'regulator_type': 'Регулятор давления РДБК-1М-50/35',
    'body_material': 'Алюминий',
    'pipe_material': 'Сталь',
    'has_coating': 'Да',
    'coating_type': 'Краска',
    'manufacturer': 'РУП "Белгазтехника"',
    'design_life': 20.0,
    'pipeline_type': 'Распределительный',
    'interlocked_with': 'ГРП-13,20,27; ШРП- 5,114,120,123',
}

# Подписи раздела 1 паспорта — в том же порядке, что и поля.
SAMPLE_LABELS = (
    'Наименование объекта',
    'Адрес',
    'Регистрационный номер',
    'Дата приёмки в эксплуатацию',
    'Дата ввода в эксплуатацию (или дата последней полной замены ГРП)',
    'Фактический срок службы',
    'Количество линий редуцирования',
    'Тип регулятора',
    'Материал корпуса',
    'Материал труб',
    'Наличие антикоррозионного покрытия',
    'Тип покрытия',
    'Завод-изготовитель',
    'Проектный срок службы',
    'Газопровод',
    'Закольцован с',
)


def _row(values):
    """Строка таблицы grp, как её отдаёт get_grp_by_id (порядок ROW_COLUMNS)."""
    return tuple(values.get(column, '') for column in grp_passport.ROW_COLUMNS)


class FieldsTests(unittest.TestCase):
    """Описание полей: полнота, порядок, подписи."""

    def test_fields_cover_all_columns(self):
        keys = [key for key, _label, _kind in grp_passport.FIELDS]
        self.assertEqual(sorted(keys), sorted(grp_passport.COLUMNS))

    def test_fields_have_no_duplicates(self):
        keys = [key for key, _label, _kind in grp_passport.FIELDS]
        self.assertEqual(len(keys), len(set(keys)))

    def test_labels_match_the_passport(self):
        self.assertEqual(tuple(label for _k, label, _kind in grp_passport.FIELDS),
                         SAMPLE_LABELS)

    def test_first_field_is_the_object_name(self):
        """Наименование объекта — поле `type`: оно уже было в базе."""
        self.assertEqual(grp_passport.FIELDS[0][0], 'type')

    def test_form_fields_are_the_new_passport_fields(self):
        keys = [key for key, _label, _kind in grp_passport.FORM_FIELDS]
        self.assertEqual(keys, list(grp_passport.PASSPORT_COLUMNS))

    def test_life_fields_are_marked_as_years(self):
        kinds = {key: kind for key, _label, kind in grp_passport.FIELDS}
        self.assertEqual(kinds['design_life'], 'years')
        self.assertEqual(kinds['actual_life'], 'years')

    def test_coating_is_a_choice(self):
        kinds = {key: kind for key, _label, kind in grp_passport.FIELDS}
        self.assertEqual(kinds['has_coating'], 'choice')
        self.assertIn('', grp_passport.COATING_CHOICES)
        self.assertIn('Да', grp_passport.COATING_CHOICES)

    def test_base_columns_keep_their_order(self):
        """grp[0..4] зашиты в интерфейсе и отчёте — паспорт идёт только в конец."""
        self.assertEqual(tuple(grp_passport.COLUMNS[:4]),
                         tuple(grp_passport.BASE_COLUMNS))
        self.assertEqual(grp_passport.ROW_COLUMNS[0], 'id')


class ReadingTests(unittest.TestCase):
    """Чтение значений из строки таблицы."""

    def test_value_reads_every_field(self):
        row = _row(SAMPLE)
        for key, _label, _kind in grp_passport.FIELDS:
            with self.subTest(key):
                self.assertEqual(grp_passport.value(row, key), SAMPLE[key])

    def test_fallback_row_has_no_passport_data(self):
        """Запасной кортеж отчёта: (grp_id, grp_name, 0, 0, 0).

        Базовые поля в нём есть — из них собирается заголовок, — а сведения
        паспорта пусты: отчёт про ГРП без карточки не должен падать.
        """
        fallback = (26, 'ГРП №26', 0, 0, 0)
        self.assertEqual(grp_passport.text(fallback, 'type'), 'ГРП №26')
        for key in grp_passport.PASSPORT_COLUMNS:
            with self.subTest(key):
                self.assertEqual(grp_passport.value(fallback, key), '')

    def test_truncated_row_does_not_raise(self):
        """Строка короче любого поля — чтение отдаёт пустое значение."""
        for key, _label, _kind in grp_passport.FIELDS:
            with self.subTest(key):
                self.assertEqual(grp_passport.value((26,), key), '')
        self.assertEqual(grp_passport.value((), 'type'), '')
        self.assertEqual(grp_passport.value(None, 'type'), '')

    def test_empty_and_none_are_the_same(self):
        row = _row({'type': 'ГРП №1', 'address': None})
        self.assertEqual(grp_passport.text(row, 'address'), '')

    def test_text_strips_spaces(self):
        row = _row({'address': '  г. Гродно  '})
        self.assertEqual(grp_passport.text(row, 'address'), 'г. Гродно')

    def test_unknown_key(self):
        row = _row(SAMPLE)
        self.assertEqual(grp_passport.value(row, 'нет такого поля'), '')

    def test_values_gives_strings_for_the_form(self):
        values = grp_passport.values(_row(SAMPLE))
        self.assertEqual(values['address'], SAMPLE['address'])
        self.assertEqual(values['lines_count'], '1')
        self.assertEqual(values['has_coating'], 'Да')

    def test_values_renders_life_as_text(self):
        """Срок возвращается в форму так, как его принимает parse_years."""
        values = grp_passport.values(_row(SAMPLE))
        self.assertEqual(values['design_life'], '20 лет')
        self.assertEqual(values['actual_life'], '44 года 6 мес')

    def test_values_of_empty_life_is_empty(self):
        values = grp_passport.values(_row({'type': 'ГРП №1'}))
        self.assertEqual(values['design_life'], '')


class ReportRowsTests(unittest.TestCase):
    """Строки таблицы «Сведения о ГРП» для Word-отчёта."""

    def test_rows_keep_the_passport_order(self):
        rows = grp_passport.report_rows(_row(SAMPLE))
        self.assertEqual(tuple(label for label, _value in rows), SAMPLE_LABELS)

    def test_rows_carry_the_entered_values(self):
        rows = dict(grp_passport.report_rows(_row(SAMPLE)))
        self.assertEqual(rows['Адрес'], SAMPLE['address'])
        self.assertEqual(rows['Дата приёмки в эксплуатацию'], '01.1981')
        self.assertEqual(rows['Закольцован с'], SAMPLE['interlocked_with'])

    def test_rows_show_life_in_words(self):
        rows = dict(grp_passport.report_rows(_row(SAMPLE)))
        self.assertEqual(rows['Проектный срок службы'], '20 лет')

    def test_empty_field_becomes_a_dash(self):
        rows = dict(grp_passport.report_rows(_row({'type': 'ГРП №1'})))
        self.assertEqual(rows['Адрес'], '—')
        self.assertEqual(rows['Тип покрытия'], '—')

    def test_empty_life_is_a_dash_not_zero_days(self):
        """«0 дн» на месте незаполненного срока читалось бы как «срок истёк»."""
        rows = dict(grp_passport.report_rows(_row({'type': 'ГРП №1'})))
        self.assertEqual(rows['Проектный срок службы'], '—')

    def test_all_fields_are_printed(self):
        """Ни одно введённое сведение не теряется по дороге в отчёт."""
        rows = grp_passport.report_rows(_row(SAMPLE))
        self.assertEqual(len(rows), len(grp_passport.FIELDS))
        self.assertEqual([label for label, _v in rows], list(SAMPLE_LABELS))


if __name__ == '__main__':
    unittest.main()
