"""Техническое диагностирование: графы таблицы, поля формы и результат проверки.

Одно описание на трёх потребителей сразу — графы таблицы «Техническое
диагностирование», поля формы записи и чтение строки выборки из базы. Порядок
граф задан заказчиком: сначала номер записи и дата проверки, потом что
проверяли (оборудование и параметр), режим проверки, границы допуска и
фактические значения в кПа, результат проверки и примечание.

Запись — это результат одной проверки одного параметра одного оборудования:
«режим» — значение параметра при проверке, «допуск мин/макс» — границы,
установленные документацией, «факт мин/макс» — что показала проверка.
Результат выводится из чисел: пока факт укладывается в допуск — «норма», как
только выходит за границу — «отклонение от нормы» (см. suggested_result).
В форме результат подставляется на виду и правится вручную: специалист
решает сам, бывает и так, что выход за допуск признан допустимым.

Числа в кПа хранятся текстом, как их вписали («1,3» или «300»): в журнале
важно то, что перенесено из протокола проверки, а не то, как это выглядит
после округления. Поэтому же оборудование хранится названием, а не ссылкой
на запись справочника: проверка — исторический документ, и она должна
читаться и после того, как единица оборудования снята и удалена.
"""
import re
from typing import Dict, Optional, Sequence

EMPTY = '—'

# Результат проверки — один из двух исходов, как в протоколе.
RESULT_OK = 'норма'
RESULT_DEVIATION = 'отклонение от нормы'
RESULTS = (RESULT_OK, RESULT_DEVIATION)

# Проверяемые параметры для подсказки в форме. Список открытый: параметр
# вписывается свободно, это только начало строки для выбора.
PARAMETERS = (
    'Давление на входе',
    'Давление на выходе',
    'Давление срабатывания ПЗК',
    'Давление срабатывания ПСК',
    'Перепад давления на фильтре',
    'Настройка регулятора давления',
    'Герметичность затвора',
)

# Графы таблицы: (ключ, подпись, ширина). Первой графой идёт «№» — номер
# строки в списке, он нигде не хранится: это место записи в журнале.
TABLE_COLUMNS = (
    ('check_date', 'Дата', 100),
    ('equipment', 'Оборудование', 180),
    ('parameter', 'Проверяемый параметр', 190),
    ('mode', 'Режим, кПа', 95),
    ('tolerance_min', 'Допуск мин, кПа', 110),
    ('tolerance_max', 'Допуск макс, кПа', 110),
    ('fact_min', 'Факт мин, кПа', 100),
    ('fact_max', 'Факт макс, кПа', 100),
    ('result', 'Результат', 150),
    ('note', 'Примечание', 180),
)

# Поля формы записи: (ключ, подпись, вид, подсказка). Вид поля нужен форме,
# чтобы выбрать строку ввода или список: параметр выбирается из подсказки,
# оборудование — из оборудования ГРП, результат — из двух исходов.
FORM_FIELDS = (
    ('check_date', 'Дата', 'date', '📝 12.01.2024 или 2024-01-12'),
    ('equipment', 'Оборудование', 'equipment',
     'из оборудования ГРП или своим названием'),
    ('parameter', 'Проверяемый параметр', 'choice',
     'например, давление срабатывания ПЗК'),
    ('mode', 'Режим, кПа', 'pressure', 'значение параметра при проверке'),
    ('tolerance_min', 'Допуск мин, кПа', 'pressure', 'нижняя граница допуска'),
    ('tolerance_max', 'Допуск макс, кПа', 'pressure', 'верхняя граница допуска'),
    ('fact_min', 'Факт мин, кПа', 'pressure', 'минимум по проверке'),
    ('fact_max', 'Факт макс, кПа', 'pressure', 'максимум по проверке'),
    ('result', 'Результат', 'result',
     'определяется по числам, можно выбрать самому'),
    ('note', 'Примечание', 'text', 'свободная строка'),
)

# Поля записи: ключи в порядке граф таблицы.
FIELDS = tuple(key for key, _label, _width in TABLE_COLUMNS)

# Графы с числами в кПа: проверяются при записи.
PRESSURE_FIELDS = tuple(key for key, _label, kind, _hint in FORM_FIELDS
                        if kind == 'pressure')

# Графы, по которым выводится результат: границы допуска и факт. «Режим» —
# значение параметра при проверке, в сравнении он не участвует.
RESULT_FIELDS = ('tolerance_min', 'tolerance_max', 'fact_min', 'fact_max')

# Результат в базе NOT NULL DEFAULT '': пустое значение значит «не указано».
NOT_NULL_FIELDS = ('result',)

# Строка выборки get_diagnostic_checks — поля записи по порядку граф.
RECORD_COLUMNS = ('id',) + FIELDS

# Дата хранится так, как её ввели: ISO из формы или «12.01.2024». Для показа
# ISO приводится к общему виду.
_ISO_DATE = re.compile(r'^(\d{4})-(\d{2})-(\d{2})')

# Число в кПа: целое или дробное, дробная часть — точкой или запятой.
_NUMBER = re.compile(r'^[-−+]?\d+(?:[.,]\d+)?$')


class DiagnosticError(ValueError):
    """Некорректное значение графы проверки."""


def value(source, key: str, columns: Sequence[str] = RECORD_COLUMNS) -> str:
    """Значение поля записи; '' — если поля нет в этой выборке.

    source — строка выборки (индекс считается по columns, а не пишется
    числом) либо словарь значений. Короткая строка не роняет чтение — поле
    пустое.
    """
    if isinstance(source, dict):
        raw = source.get(key)
    else:
        try:
            raw = source[list(columns).index(key)]
        except (ValueError, IndexError, TypeError):
            return ''
    return str(raw if raw is not None else '').strip()


def form_values(source, columns: Sequence[str] = RECORD_COLUMNS) -> Dict[str, str]:
    """Графы записи для формы: {ключ: значение}, незаполненное — ''."""
    return {key: value(source, key, columns) for key in FIELDS}


def values(fields: Dict) -> Dict[str, Optional[str]]:
    """Графы из словаря формы для записи в базу: пустая строка → NULL.

    Результат в базе NOT NULL (пустая строка — «не указано»), поэтому у него
    пустое значение остаётся пустой строкой.
    """
    result = {}
    for key in FIELDS:
        text = str(fields.get(key) or '').strip()
        result[key] = text or ('' if key in NOT_NULL_FIELDS else None)
    return result


def to_number(text) -> Optional[float]:
    """Число в кПа из строки; None — если это не число."""
    word = str(text or '').strip().replace('−', '-').replace(',', '.')
    if not _NUMBER.match(str(text or '').strip().replace('−', '-')):
        return None
    try:
        return float(word)
    except ValueError:
        return None


def parse_pressure(text, label: str) -> str:
    """Проверить графу с числом в кПа: число либо пусто.

    «1,3», «300», «−0,5» — значения параметра; всё прочее в этой графе
    неотличимо от описки, поэтому запись не сохраняется.
    """
    word = str(text or '').strip()
    if not word:
        return ''
    if to_number(word) is None:
        raise DiagnosticError(
            f'{label} — число в кПа (например, «1,3» или «300»).')
    return word


def parse_parameter(text) -> str:
    """Проверяемый параметр: свободная строка, но пустая смысла не имеет."""
    word = str(text or '').strip()
    if not word:
        raise DiagnosticError('Не указан проверяемый параметр.')
    return word


def parse_result(text) -> str:
    """Проверить графу «Результат»: «норма», «отклонение от нормы» или пусто."""
    word = str(text or '').strip().lower()
    if not word:
        return ''
    if word not in RESULTS:
        raise DiagnosticError('Результат — «норма» или «отклонение от нормы».')
    return word


def suggested_result(tolerance_min, tolerance_max,
                     fact_min, fact_max) -> str:
    """Результат проверки по числам: норма или отклонение от нормы.

    Факт укладывается в допуск, если его минимум не ниже допуска мин, а
    максимум не выше допуска макс. Пока вписаны не все четыре числа, судить
    не о чем — результат пуст, и его выбирают вручную.
    """
    tolerance = [to_number(tolerance_min), to_number(tolerance_max)]
    fact = [to_number(fact_min), to_number(fact_max)]
    if any(number is None for number in tolerance + fact):
        return ''
    low, high = sorted(tolerance)
    fact_low, fact_high = sorted(fact)
    if fact_low >= low and fact_high <= high:
        return RESULT_OK
    return RESULT_DEVIATION


def date_text(value) -> str:
    """Дата проверки для показа: «ДД.ММ.ГГГГ».

    В базе дата лежит так, как её ввели, поэтому ISO приводится к виду,
    принятому в документах. Любой другой текст показывается как записан.
    """
    text = str(value or '').strip()
    found = _ISO_DATE.match(text)
    if not found:
        return text
    year, month, day = found.groups()
    return f'{day}.{month}.{year}'


def result_text(source, columns: Sequence[str] = RECORD_COLUMNS) -> str:
    """Графа «Результат»: как записано в протоколе проверки."""
    return value(source, 'result', columns)


def table_cells(source, columns: Sequence[str] = RECORD_COLUMNS) -> list:
    """Значения граф проверки в порядке TABLE_COLUMNS (без ведущей «№»).

    Дата приводится к виду «ДД.ММ.ГГГГ», остальные графы показываются как
    записаны. Незаполненная графа — прочерк, а не пустая клетка.
    """
    shown = {}
    for key, _label, _width in TABLE_COLUMNS:
        if key == 'check_date':
            shown[key] = date_text(value(source, key, columns))
        else:
            shown[key] = value(source, key, columns)
    return [shown[key] or EMPTY for key, _label, _width in TABLE_COLUMNS]


def table_index(key: str) -> int:
    """Номер значения графы в строке таблицы.

    Первой графой идёт «№», поэтому к позиции в TABLE_COLUMNS прибавляется
    единица. Индекс считается, а не пишется числом: при перестановке граф
    чтение строки не сломается.
    """
    return 1 + [column for column, _label, _width in TABLE_COLUMNS].index(key)
