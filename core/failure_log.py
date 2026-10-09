"""Информация по отказам: графы таблицы, поля формы и чтение строки выборки.

Одно описание на трёх потребителей сразу — графы таблицы «Информация по
отказам», поля формы записи и чтение строки выборки из базы. Порядок граф
задан заказчиком: сначала номер записи и дата выявления, потом тип события
(например, «нарушение работы оборудования»), причина, критичность словами,
признак устранения, документ, куда отказ вносится, и примечания — в них
попадают и номер акта, и рекомендации, и приложенное фото.

Критичность и признак устранения хранятся словами («низкая», «да») и
проверяются при записи: в графе стоит одно из нескольких значений, поэтому
свободный текст там неотличимо похож на описку (см. parse_criticality и
parse_resolved).

Фото отказ хранит отдельной колонкой (failures.photo), а в графе «Примечания»
видно только отметку о нём: строка таблицы читается выборкой без самих
байтов, иначе список отказов тянул бы из базы всё содержимое снимков.
"""
import re
from typing import Dict, Optional, Sequence

EMPTY = '—'

# Документ по умолчанию: отказ сначала вносят в аварийный журнал, а уже
# оттуда он попадает в другие документы. Поле формы заполняется этим
# значением, но его можно заменить — в записи останется то, что вписали.
DEFAULT_DOCUMENT = 'Аварийный журнал'

PHOTO_MARK = '📷 фото'

# Критичность — словами, как в бумажном журнале. Порядок от меньшего к
# большему: в выпадающем списке он читается как шкала.
CRITICALITY_LEVELS = ('низкая', 'средняя', 'высокая')

# Признак устранения — «да» или «нет»; пусто означает «не указано».
YES_NO = ('да', 'нет')

# Типы событий для подсказки в форме. Список открытый: тип вписывается
# свободно, это только начало строки для выбора.
EVENT_TYPES = (
    'Нарушение работы оборудования',
    'Аварийная остановка',
    'Утечка газа',
    'Отказ запорной арматуры',
    'Отказ предохранительного клапана',
    'Отказ регулятора давления',
    'Загазованность помещения',
    'Отклонение выходного давления',
    'Отказ средств измерений',
    'Прекращение подачи электроэнергии',
    'Прочее',
)

# Графы таблицы отказов: (ключ, подпись, ширина). Первой графой идёт «№» —
# номер строки в списке, он нигде не хранится: это место записи в журнале.
TABLE_COLUMNS = (
    ('detected_date', 'Дата выявления', 105),
    ('event_type', 'Тип события', 210),
    ('reason', 'Причина', 210),
    ('criticality', 'Критичность', 105),
    ('resolved', 'Устранён', 90),
    ('document', 'Документ, куда вносится', 170),
    ('note', 'Примечания', 230),
)

# Поля формы записи: (ключ, подпись, вид, подсказка). Вид поля нужен форме,
# чтобы выбрать список или строку ввода: у критичности, признака устранения и
# типа события значения ограничены списком.
FORM_FIELDS = (
    ('detected_date', 'Дата выявления', 'date',
     '📝 12.01.2024 или 2024-01-12'),
    ('event_type', 'Тип события', 'choice',
     'например, нарушение работы оборудования'),
    ('reason', 'Причина', 'text', 'что привело к отказу'),
    ('criticality', 'Критичность', 'criticality',
     'низкая, средняя или высокая'),
    ('resolved', 'Устранён', 'yes_no', 'да или нет'),
    ('document', 'Документ, куда вносится', 'text',
     f'по умолчанию «{DEFAULT_DOCUMENT}»'),
    ('note', 'Примечания', 'text',
     'номер акта, рекомендации; фото прикладывается кнопкой'),
)

# Поля записи: ключи в порядке граф таблицы.
FIELDS = tuple(key for key, _label, _width in TABLE_COLUMNS)

# Графы, которые в базе NOT NULL DEFAULT '': пустое значение пишется пустой
# строкой, а не NULL.
NOT_NULL_FIELDS = ('criticality', 'resolved')

# Строка выборки get_failures_by_grp: поля записи, затем отметка о фото.
# Сами байты снимка в список не читаются — для показа хватает отметки, а
# фото берётся отдельной выборкой (get_failure_photo).
RECORD_COLUMNS = ('id',) + FIELDS + ('has_photo',)

# Дата отказов хранится так, как её ввели: ISO из формы или «12.01.2024».
# Для показа ISO приводится к общему виду.
_ISO_DATE = re.compile(r'^(\d{4})-(\d{2})-(\d{2})')


class FailureError(ValueError):
    """Некорректное значение графы отказа."""


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


def has_photo(source, columns: Sequence[str] = RECORD_COLUMNS) -> bool:
    """Приложено ли к записи фото (отметка в выборке списка)."""
    if isinstance(source, dict):
        raw = source.get('has_photo')
    else:
        try:
            raw = source[list(columns).index('has_photo')]
        except (ValueError, IndexError, TypeError):
            return False
    return bool(raw) and str(raw) not in ('0', 'False', 'false')


def form_values(source, columns: Sequence[str] = RECORD_COLUMNS) -> Dict[str, str]:
    """Графы записи для формы: {ключ: значение}, незаполненное — ''."""
    return {key: value(source, key, columns) for key in FIELDS}


def values(fields: Dict) -> Dict[str, Optional[str]]:
    """Графы из словаря формы для записи в базу: пустая строка → NULL.

    Критичность и признак устранения в базе NOT NULL (пустая строка — «не
    указано»), поэтому у них пустое значение остаётся пустой строкой.
    """
    result = {}
    for key in FIELDS:
        text = str(fields.get(key) or '').strip()
        result[key] = text or ('' if key in NOT_NULL_FIELDS else None)
    return result


def parse_criticality(text) -> str:
    """Проверить графу «Критичность».

    Принимает слова «низкая», «средняя», «высокая» в любом регистре и пустое
    значение («не указано»). Всё прочее — FailureError: «средняя (со
    временным устранением)» в графе неотличимо от описки.
    """
    word = str(text or '').strip().lower()
    if not word:
        return ''
    if word not in CRITICALITY_LEVELS:
        raise FailureError(
            'Критичность — одно из слов: '
            + ', '.join(CRITICALITY_LEVELS) + '.')
    return word


def parse_resolved(text) -> str:
    """Проверить графу «Устранён»: «да», «нет» или пусто."""
    word = str(text or '').strip().lower()
    if not word:
        return ''
    if word not in YES_NO:
        raise FailureError('Устранён — «да» или «нет».')
    return word


def parse_event(text) -> str:
    """Тип события: свободная строка, но пустая графа смысла не имеет."""
    word = str(text or '').strip()
    if not word:
        raise FailureError('Не указан тип события (например, «нарушение работы '
                           'оборудования»).')
    return word


def date_text(value) -> str:
    """Дата выявления для показа: «ДД.ММ.ГГГГ».

    В базе дата лежит так, как её ввели, поэтому ISO приводится к виду,
    принятому в документах. Любой другой текст показывается как записан.
    """
    text = str(value or '').strip()
    found = _ISO_DATE.match(text)
    if not found:
        return text
    year, month, day = found.groups()
    return f'{day}.{month}.{year}'


def note_cell(source, columns: Sequence[str] = RECORD_COLUMNS) -> str:
    """Графа «Примечания»: текст и отметка о приложенном фото.

    Примечание хранит и номер акта, и рекомендации, и фото. Сам снимок лежит
    отдельно, поэтому о нём говорит отметка.
    """
    text = value(source, 'note', columns)
    if not has_photo(source, columns):
        return text
    return f'{text} · {PHOTO_MARK}' if text else PHOTO_MARK


def table_cells(source, columns: Sequence[str] = RECORD_COLUMNS) -> list:
    """Значения граф отказов в порядке TABLE_COLUMNS (без ведущей «№»).

    Дата приводится к виду «ДД.ММ.ГГГГ», в примечаниях видна отметка о фото;
    остальные графы показываются как записаны. Незаполненная графа — прочерк,
    а не пустая клетка.
    """
    shown = {}
    for key, _label, _width in TABLE_COLUMNS:
        if key == 'detected_date':
            shown[key] = date_text(value(source, key, columns))
        elif key == 'note':
            shown[key] = note_cell(source, columns)
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


def photo_extension(data: bytes) -> str:
    """Расширение файла снимка по его содержимому.

    Имя файла при приложении не сохраняется: фото живёт в базе, а на диск
    пишется только на время просмотра. Чтобы система открыла снимок нужной
    программой, расширение определяется по «магии» в начале файла.
    """
    head = bytes(data or b'')[:12]
    if head.startswith(b'\x89PNG\r\n\x1a\n'):
        return '.png'
    if head.startswith(b'\xff\xd8\xff'):
        return '.jpg'
    if head.startswith((b'GIF87a', b'GIF89a')):
        return '.gif'
    if head.startswith(b'BM'):
        return '.bmp'
    if head.startswith(b'RIFF') and head[8:12] == b'WEBP':
        return '.webp'
    if head.startswith(b'%PDF'):
        return '.pdf'
    return '.jpg'
