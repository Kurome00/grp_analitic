"""
Расчёт остаточного ресурса ГРП по алгоритмам 0-4.

Источники формул (методички лежат в папке docs/):
  * "docs/Алгоритм 3-без календаря-5+.pdf"  — скорректированная редакция Алгоритма 3
    (приоритет наработки, двойной учёт K_сост, учёт некратных замен, T_диагн).
  * "docs/Алг3-схема данных.pdf"             — соответствие шагов разделам цифрового
    паспорта ГРП, сквозной пример ГРП №26.
  * "docs/Алгоритм4.pdf"                    — Алгоритм 4. Из него используется только
    календарная база (срок полной проверки); взвешивание с фактической наработкой
    отключено, потому что данных телеметрии по элементам нет (см. calculate_algorithm_4).
  * "docs/Алгоритмы-(все до корректировки).pdf" — Алгоритмы 0-2 и сводные таблицы.

Каждый шаг расчёта фиксируется в трассировке (steps), чтобы результат можно
было проверить вручную: в трассировке хранятся формула, подставленные значения
и источник данных.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Callable, Dict, List, Optional, Tuple

from core.config import EQUIPMENT_NORMS, FULL_CHECK_TERM
from core.timefmt import years_to_text


# ---------------------------------------------------------------------------
# Критические элементы ГРП (Шаг 1 «Алгоритм 3»)
# ---------------------------------------------------------------------------

CRITICAL_ELEMENTS: Dict[str, Tuple[str, Tuple[str, ...]]] = {
    'regulator': ('Регулятор давления', ('регулятор', 'рдгпк', 'рдбк', 'редуктор', 'регуля')),
    'pzk': ('ПЗК (предохранительно-запорный клапан)',
            ('пзк', 'пкн', 'предохранительно-запорн', 'запорно-предохранительн', 'сбросно-запорн')),
    'psk': ('ПСК (предохранительно-сбросный клапан)',
            ('пск', 'предохранительно-сбросн', 'сбросно-предохранительн', 'сбросной клапан')),
    'filter': ('Фильтр', ('фильтр',)),
    'valve': ('Запорная арматура',
              ('кран', 'запорн', 'арматур', 'кш-', 'кшг', 'кшф', 'задвижк', 'вентил', '-ball', 'кранш')),
}

CRITICAL_ORDER = ('regulator', 'pzk', 'psk', 'filter', 'valve')

# Соответствие видов работ качеству ремонта (Шаг 5 «Алгоритм 3»)
REPAIR_QUALITY = {
    'new': 1.0,       # замена элемента на новый
    'quality': 1.0,   # качественный ремонт
    'poor': 0.9,      # некачественный ремонт
    'none': 1.0,      # ремонт не проводился
}

REPAIR_QUALITY_LABEL = {
    'new': 'замена на новое',
    'quality': 'качественный ремонт',
    'poor': 'некачественный ремонт (K_рем = 0,9)',
    'none': 'ремонт не проводился',
}

# Признаки аварийной работы в журнале замен (для N_отказов)
FAILURE_MARKERS = (
    'авар', 'отказ', 'сработ', 'разрыв', 'прорыв', 'аварийн',
)

# Признаки повреждения в журнале замен (для N_повреждений)
DAMAGE_MARKERS = (
    'повреж', 'корроз', 'трещин', 'износ', 'деформац', 'разруш', 'негермет',
)

# Признаки некачественного ремонта в журнале замен
POOR_REPAIR_MARKERS = (
    'некачеств', 'некач', 'плох', 'неудовлетв', 'брак', 'течь', 'негермет',
)


def _f(value) -> Optional[float]:
    """Мягкое приведение к float: None при нечисловом значении."""
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result:  # NaN
        return None
    return result


def num(value: Optional[float], digits: int = 3) -> str:
    """Форматирование числа в русской нотации (запятая как разделитель)."""
    number = _f(value)
    if number is None:
        return '—'
    return f"{number:.{digits}f}".replace('.', ',')


def signed_years(value: Optional[float]) -> str:
    """Ресурс в годах и месяцах с префиксом '+'/'−'."""
    text = years_to_text(value)
    if text == '—':
        return text
    return ('+' if (_f(value) or 0) > 0 else '') + text


def classify_critical(name: str) -> Optional[str]:
    """Определяет категорию критического элемента по наименованию."""
    low = (name or '').lower()
    for key in CRITICAL_ORDER:
        for marker in CRITICAL_ELEMENTS[key][1]:
            if marker in low:
                return key
    return None


def critical_title(key: str) -> str:
    return CRITICAL_ELEMENTS.get(key, (key, ()))[0]


# Короткие названия для плотных таблиц: «ПЗК (предохранительно-запорный
# клапан)» в графе шириной 150 px обрезается, хотя расшифровка всё равно видна
# на вкладке «Методика» и в полном названии элемента.
CRITICAL_SHORT = {
    'regulator': 'Регулятор',
    'pzk': 'ПЗК',
    'psk': 'ПСК',
    'filter': 'Фильтр',
    'valve': 'Арматура',
}


def critical_short_title(key: str) -> str:
    return CRITICAL_SHORT.get(key, critical_title(key))


# ---------------------------------------------------------------------------
# Структуры данных
# ---------------------------------------------------------------------------

@dataclass
class AlgorithmParams:
    """Весовые коэффициенты и ограничения алгоритмов.

    Значения по умолчанию — рекомендуемые из методики.
    """

    # Шаг 6 «Алгоритм 3»: k_повр = 1 − α·N_отказ − β·N_поврежд
    alpha_fail: float = 0.15
    beta_damage: float = 0.10
    # Шаг 4: K_эксл = 1 − θ·(1 − Усл_факт/Усл_норм)
    theta_conditions: float = 0.10
    # Шаг 5: K_рем = 1 − δ·(1 − Рем_факт/Рем_норм)
    delta_repair: float = 0.10
    # Шаг 11: T_диагн = min(Z_ГРП · K_запаса; T_макс)
    reserve: float = 0.50
    max_diag_interval: float = 5.0

    def as_rows(self) -> List[Tuple[str, str, str, str]]:
        """Строки (параметр, значение, диапазон, назначение) для вкладки исходных данных."""
        return [
            ('α — вес отказа', num(self.alpha_fail, 2), '0,05…0,25',
             f'k_повр = 1 − {num(self.alpha_fail, 2)}·N_отказ − {num(self.beta_damage, 2)}·N_поврежд'),
            ('β — вес повреждения', num(self.beta_damage, 2), '0,05…0,15',
             'повреждения слабее отказов (α > β)'),
            ('θ — вес условий эксплуатации', num(self.theta_conditions, 2), '0,05…0,20',
             'K_эксл = 1 − θ·(1 − Усл_факт/Усл_норм)'),
            ('δ — вес качества ремонта', num(self.delta_repair, 2), '0,05…0,20',
             'K_рем = 1 − δ·(1 − Рем_факт/Рем_норм)'),
            ('K_запаса', num(self.reserve, 2), '0,3…0,7',
             'запас на непредсказуемость отказа процесса'),
            ('T_макс — макс. междиагностический интервал', num(self.max_diag_interval, 1), '5 лет',
             'Правила МЧС Республики Беларусь'),
        ]


@dataclass
class Step:
    """Шаг трассировки расчёта."""

    level: str = 'info'   # title | formula | value | note | warn
    text: str = ''

    def as_dict(self) -> Dict:
        return {'level': self.level, 'text': self.text}


@dataclass
class ElementResult:
    """Результат расчёта по одному элементу ГРП."""

    name: str
    equipment_id: Optional[int] = None
    critical_key: Optional[str] = None
    install_date: Optional[str] = None
    removal_date: Optional[str] = None
    age: float = 0.0
    removed: bool = False
    norm: Optional[float] = None
    norm_source: str = ''

    # Шаг 2 — базовый ресурс
    z_base: Optional[float] = None
    z_base_variant: str = ''
    z_base_formula: str = ''
    z_base_note: str = ''
    details: List[Dict] = field(default_factory=list)

    # Шаг 2 (Алгоритм 4) — календарный и наработка
    z_calendar: Optional[float] = None
    z_workload: Optional[float] = None
    z_workload_source: str = ''

    # Шаг 3-6 — коэффициенты
    k_state: float = 1.0
    k_state_note: str = ''
    k_state_detail: List[Dict] = field(default_factory=list)
    k_cond: float = 1.0
    k_cond_note: str = ''
    k_repair: float = 1.0
    k_repair_note: str = ''
    k_fail: float = 1.0
    k_fail_note: str = ''
    n_fail: int = 0
    n_damage: int = 0

    # Шаг 7 — некратные замены
    replacement_sum: Optional[float] = None
    replacement_note: str = ''

    # Шаги 8-10 — итог
    z_element: float = 0.0
    z_element_formula: str = ''
    z_element_note: str = ''
    used: bool = True
    skip_reason: str = ''

    def as_dict(self) -> Dict:
        return {
            'name': self.name,
            'equipment_id': self.equipment_id,
            'critical_key': self.critical_key,
            'install_date': self.install_date,
            'age': self.age,
            'removed': self.removed,
            'norm': self.norm,
            'norm_source': self.norm_source,
            'z_base': self.z_base,
            'z_base_variant': self.z_base_variant,
            'z_base_formula': self.z_base_formula,
            'z_base_note': self.z_base_note,
            'details': self.details,
            'z_calendar': self.z_calendar,
            'z_workload': self.z_workload,
            'z_workload_source': self.z_workload_source,
            'k_state': self.k_state,
            'k_state_note': self.k_state_note,
            'k_state_detail': self.k_state_detail,
            'k_cond': self.k_cond,
            'k_cond_note': self.k_cond_note,
            'k_repair': self.k_repair,
            'k_repair_note': self.k_repair_note,
            'k_fail': self.k_fail,
            'k_fail_note': self.k_fail_note,
            'n_fail': self.n_fail,
            'n_damage': self.n_damage,
            'replacement_sum': self.replacement_sum,
            'replacement_note': self.replacement_note,
            'z_element': self.z_element,
            'z_element_formula': self.z_element_formula,
            'z_element_note': self.z_element_note,
            'used': self.used,
            'skip_reason': self.skip_reason,
        }


@dataclass
class AlgorithmResult:
    """Результат расчёта по одному алгоритму."""

    algorithm_name: str
    algorithm_number: int
    result: float
    weak_element: Optional[str] = None
    weak_element_key: Optional[str] = None
    next_diagnosis: Optional[float] = None
    elements: List[ElementResult] = field(default_factory=list)
    steps: List[Step] = field(default_factory=list)
    scalars: Dict = field(default_factory=dict)
    recommendation: str = ''
    error: Optional[str] = None

    @property
    def details(self) -> Dict:
        """Совместимость со старым потребителем (algorithms_view)."""
        data = {
            'elements': [e.as_dict() for e in self.elements],
            'steps': [s.as_dict() for s in self.steps],
        }
        data.update(self.scalars)
        if self.error:
            data['error'] = self.error
        return data

    @property
    def used_elements(self) -> List[ElementResult]:
        return [e for e in self.elements if e.used]

    def as_dict(self) -> Dict:
        return {
            'algorithm_name': self.algorithm_name,
            'algorithm_number': self.algorithm_number,
            'result': self.result,
            'weak_element': self.weak_element,
            'weak_element_key': self.weak_element_key,
            'next_diagnosis': self.next_diagnosis,
            'elements': [e.as_dict() for e in self.elements],
            'steps': [s.as_dict() for s in self.steps],
            'scalars': self.scalars,
            'recommendation': self.recommendation,
            'error': self.error,
        }


# ---------------------------------------------------------------------------
# Сроки по методикам и слабые звенья
# ---------------------------------------------------------------------------

# Методики, по которым показываются сроки. Раньше выводился один сводный
# («консервативный») срок — минимум по всем методикам; он смешивал разные
# редакции и не позволял увидеть, где именно расхождение. Теперь показываются
# два срока раздельно: по скорректированной методике (3) и по календарной (4).
DEADLINE_ALGORITHMS: Tuple[int, ...] = (3, 4)

# Слабым звеном считаем элементы, чей остаточный ресурс не превышает минимальный
# более чем на это число лет: в пределах года разные элементы дают один и тот же
# срок, и показывать надо их все, а не только первый попавшийся.
WEAK_LINK_TOLERANCE = 0.5


@dataclass
class Deadline:
    """Срок по одной методике: ресурс, дата диагностирования, слабые звенья."""
    algorithm_number: int
    algorithm_name: str
    result: float
    next_diagnosis: float
    weak_element: Optional[str]
    weak_links: List[Dict] = field(default_factory=list)
    recommendation: str = ''
    error: Optional[str] = None

    @property
    def is_valid(self) -> bool:
        return not self.error


@dataclass
class WeakLink:
    """Слабое звено: элемент ГРП и определяющая его заменяемая деталь."""
    element: str
    category: str
    z_element: float
    part: Optional[str] = None
    part_norm: Optional[float] = None
    part_age: Optional[float] = None

    def describe(self) -> str:
        base = f'{self.element} — {years_to_text(self.z_element)}'
        if self.part:
            return f'{base} (деталь «{self.part}»'
        return base

    def as_dict(self) -> Dict:
        return {
            'element': self.element,
            'category': self.category,
            'z_element': self.z_element,
            'part': self.part,
            'part_norm': self.part_norm,
            'part_age': self.part_age,
        }


def _driving_part(element: ElementResult) -> Optional[Dict]:
    """Заменяемая деталь с наименьшим остатком — она определяет элемент."""
    best, best_z = None, None
    for detail in element.details or []:
        z = _f(detail.get('z_base'))
        if z is None:
            z = (_f(detail.get('norm')) or 0.0) - (_f(detail.get('age')) or 0.0)
        if best_z is None or z < best_z:
            best, best_z = detail, z
    return best


def driving_part(element: ElementResult) -> Optional[Dict]:
    """Публичная обёртка: деталь с наименьшим остатком определяет элемент."""
    return _driving_part(element)


def collect_weak_links(result: AlgorithmResult,
                       tolerance: float = WEAK_LINK_TOLERANCE) -> List[WeakLink]:
    """Слабые звенья результата — все элементы с минимальным ресурсом.

    Возвращает список, а не одно имя: элементов-минимумов часто несколько
    (например, у нескольких единиц одновременно истёк срок), и каждый из них
    ограничивает ресурс ГРП.
    """
    used = result.used_elements if result else []
    if not used:
        return []
    z_min = min(e.z_element for e in used)
    limit = z_min + tolerance
    links = []
    for element in sorted(used, key=lambda e: (e.z_element, e.name)):
        if element.z_element > limit:
            break
        part = _driving_part(element)
        links.append(WeakLink(
            element=element.name,
            category=critical_title(element.critical_key) if element.critical_key else '—',
            z_element=element.z_element,
            part=part.get('name') if part else None,
            part_norm=_f(part.get('norm')) if part else None,
            part_age=_f(part.get('age')) if part else None,
        ))
    return links


def build_deadlines(results: Dict[int, AlgorithmResult],
                    numbers: Tuple[int, ...] = DEADLINE_ALGORITHMS
                    ) -> List[Deadline]:
    """Сроки по заданным методикам + слабые звенья каждого."""
    deadlines = []
    for number in numbers:
        result = results.get(number)
        if result is None:
            deadlines.append(Deadline(
                algorithm_number=number,
                algorithm_name=ALGORITHM_TITLES.get(number, algo_label(number)),
                result=0.0, next_diagnosis=0.0, weak_element=None,
                error='методика не рассчитана'))
            continue
        deadlines.append(Deadline(
            algorithm_number=number,
            algorithm_name=result.algorithm_name,
            result=result.result,
            next_diagnosis=result.next_diagnosis,
            weak_element=result.weak_element,
            weak_links=collect_weak_links(result),
            recommendation=result.recommendation,
            error=result.error,
        ))
    return deadlines


def algo_number(number: int) -> int:
    """Номер методики в нумерации, которую видит пользователь: 0-4 → 1-5.

    Внутри программы методики остаются с нуля: индексы нужны для обращения к
    calculate_algorithm_N и ключам словарей результатов. Пересчитывать всю
    нумерацию в коде незачем и опасно — достаточно сдвигать её на выходе.
    """
    return number + 1


def algo_label(number: int) -> str:
    """Подпись методики для интерфейса и отчётов: «Алгоритм 3»."""
    return f'Алгоритм {number + 1}'


ALGORITHM_TITLES = {
    0: 'Утверждённая методика',
    1: 'Среднее арифметическое',
    2: 'REGION-gaz (слабое звено)',
    3: 'Скорректированный (наработка + 4 коэффициента)',
    4: 'Календарный (срок полной проверки)',
}

ALGORITHM_SHORT = {
    0: 'Утверждённая методика',
    1: 'Среднее арифметическое',
    2: 'REGION-gaz',
    3: 'Скорректированный',
    4: 'Календарный',
}


# ---------------------------------------------------------------------------
# Калькулятор
# ---------------------------------------------------------------------------

class GRPResourceCalculator:
    """Калькулятор остаточного ресурса ГРП по алгоритмам 0-4.

    Входные данные по элементу (Dict):
        name, equipment_id, install_date, removal_date  — обязательные поля БД;
        norm            — прямое задание S_нач, лет;
        details         — детали элемента: [{name, norm_years, install_date,
                                             removal_date, is_replaceable}];
        telemetry       — наработка: {norm_hours, fact_hours} или
                         {norm_cycles, fact_cycles};
        state_params    — параметры диагностики: [{name, nominal, actual,
                         tol_min, tol_max}] → K_сост;
        condition       — условия эксплуатации: {fact, norm} → K_эксл;
        repair          — ремонт: {quality, fact, norm} → K_рем;
        failures, damages — N_отказов, N_повреждений.
    """

    def __init__(self,
                 norm_func: Optional[Callable[[Dict], Optional[float]]] = None,
                 params: Optional[AlgorithmParams] = None,
                 coefficients: Optional[Dict] = None):
        self.params = params or AlgorithmParams()
        self.norm_func = norm_func
        # A, B, C, K из журнала технической диагностики (используется в Алгоритме 1)
        self.coefficients = coefficients or {}

    # -- служебное ----------------------------------------------------------

    @staticmethod
    def _parse_date(value) -> Optional[date]:
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        if not value:
            return None
        for fmt in ('%Y-%m-%d', '%d.%m.%Y', '%Y-%m-%d %H:%M:%S'):
            try:
                return datetime.strptime(str(value)[:19].strip(), fmt).date()
            except ValueError:
                continue
        return None

    def _age(self, start, end=None) -> float:
        """Возраст в годах."""
        start_date = self._parse_date(start)
        if start_date is None:
            return 0.0
        end_date = self._parse_date(end) or date.today()
        return (end_date - start_date).days / 365.25

    @staticmethod
    def _to_iso(value) -> Optional[str]:
        parsed = GRPResourceCalculator._parse_date(value)
        return parsed.isoformat() if parsed else None

    # -- подготовка элементов ----------------------------------------------

    def get_norm_for_element(self, element: Dict,
                             details: Optional[List[Dict]] = None
                             ) -> Tuple[Optional[float], str]:
        """Нормативный ресурс S_нач элемента и источник нормы.

        Приоритет: задано вручную → справочник config → срок полной проверки.
        Срок заменяемых деталей (5 лет) на норму самого оборудования не влияет:
        он учитывается отдельно, как слабое звено по запчастям.
        """
        explicit = _f(element.get('norm'))
        if explicit is not None and explicit > 0:
            return explicit, 'задано вручную'

        name = element.get('name', '') or ''
        for key, years in EQUIPMENT_NORMS.items():
            if key in name or name in key:
                return float(years), 'справочник config'

        return FULL_CHECK_TERM, f'срок полной проверки ({FULL_CHECK_TERM:g} лет)'

    def _active_details(self, element: Dict) -> List[Dict]:
        """Активные ЗАМЕНЯЕМЫЕ детали элемента (для базового ресурса).

        В расчёт идут только детали с признаком is_replaceable: именно они
        имеют 5-летний срок службы и определяют остаточный ресурс.
        Незаменяемые детали (крепёж, корпусные элементы, прокладки каталога и
        т.п.) в сроке службы ГРП не участвуют.

        Возраст заменяемой детали без собственной даты установки считается от
        последней замены по элементу (replaced_on), а не от даты установки
        оборудования: иначе деталь с нормой 5 лет, монтированная вместе с
        ГРП 18 лет назад, получала остаток −13 лет, хотя её меняли при
        ремонтах. Если замен в журнале нет, остаётся дата установки
        оборудования — это честный просроченный срок службы.
        """
        details = []
        renewed_on = element.get('replaced_on')
        for item in element.get('details') or []:
            if not isinstance(item, dict):
                continue
            if item.get('removal_date') or item.get('removed'):
                continue
            if not item.get('is_replaceable'):
                continue
            norm = _f(item.get('norm_years'))
            if norm is None or norm <= 0:
                continue
            own_date = item.get('install_date')
            if own_date:
                source = 'дата установки детали'
            elif renewed_on:
                own_date, source = renewed_on, 'дата последней замены по журналу'
            else:
                source = 'дата установки оборудования'
            details.append({
                'name': item.get('name') or 'Деталь',
                'norm': norm,
                'install_date': own_date or element.get('install_date'),
                'age': self._age(own_date or element.get('install_date')),
                'install_source': source,
                'consumed_ratio': _f(item.get('consumed_ratio')),
                'norm_assumed': False,
            })
        return details

    def _build_element(self, equip: Dict) -> Optional[ElementResult]:
        """Готовит элемент к расчёту: норма, базовый ресурс, коэффициенты."""
        name = equip.get('name') or 'Без названия'
        install = self._to_iso(equip.get('install_date'))
        removed = bool(equip.get('removal_date'))
        details = self._active_details(equip)
        norm, norm_source = self.get_norm_for_element(equip, details)

        if norm is None and not details and _f(equip.get('z_base')) is None:
            return None
        if norm is None:
            norm = min(d['norm'] for d in details) if details else (
                _f(equip.get('z_base')) or 0.0)
            norm_source = 'минимальная норма деталей' if details else 'оценка остаточного ресурса'

        if install is None and details:
            earliest = min((d['install_date'] for d in details if d['install_date']),
                           default=None)
            if earliest:
                install = self._to_iso(earliest)

        element = ElementResult(
            name=name,
            equipment_id=equip.get('equipment_id'),
            critical_key=classify_critical(name),
            install_date=install,
            removal_date=self._to_iso(equip.get('removal_date')),
            age=self._age(install, equip.get('removal_date')),
            removed=removed,
            norm=norm,
            norm_source=norm_source,
        )

        self._calc_base_resource(element, equip, details)
        self._calc_coefficients(element, equip)
        self._calc_replacement_ratio(element)
        return element

    # -- Шаг 2: базовый ресурс --------------------------------------------

    def _calc_base_resource(self, element: ElementResult, equip: Dict,
                            details: List[Dict]) -> None:
        """Каскад вариантов: А (наработка) → Б1 (диагностика) → Б2 (экспертная)
        → В (календарный, резервный)."""
        telemetry = equip.get('telemetry') or {}
        norm = element.norm or 0.0
        element.details = details
        if norm:
            element.z_calendar = norm - element.age

        # Готовая оценка базового ресурса (протокол испытаний, документальная
        # оценка, экспертное заключение) — приоритет перед каскадом.
        explicit_z = _f(equip.get('z_base'))
        if explicit_z is not None:
            element.z_base = explicit_z
            element.z_base_variant = 'Б2'
            element.z_base_formula = f'Z_эц = {num(explicit_z, 2)}'
            element.z_base_note = (equip.get('z_base_source')
                                   or 'оценка остаточного ресурса принята документально')
            return

        # Вариант А — по наработке
        h_norm = _f(telemetry.get('norm_hours'))
        h_fact = _f(telemetry.get('fact_hours'))
        c_norm = _f(telemetry.get('norm_cycles'))
        c_fact = _f(telemetry.get('fact_cycles'))

        if h_norm and h_fact is not None and h_norm > 0:
            element.z_base = (h_norm - h_fact) / h_norm * norm
            element.z_base_variant = 'А'
            element.z_base_formula = (
                f'({num(h_norm, 0)} − {num(h_fact, 0)}) / {num(h_norm, 0)} × {num(norm, 2)}'
            )
            element.z_base_note = f'наработка {num(h_fact, 0)} из {num(h_norm, 0)} ч'
            element.z_workload = element.z_base
            element.z_workload_source = 'телеметрия (часы)'
            return

        if c_norm and c_fact is not None and c_norm > 0:
            element.z_base = (c_norm - c_fact) / c_norm * norm
            element.z_base_variant = 'А'
            element.z_base_formula = (
                f'({num(c_norm, 0)} − {num(c_fact, 0)}) / {num(c_norm, 0)} × {num(norm, 2)}'
            )
            element.z_base_note = f'наработка {num(c_fact, 0)} из {num(c_norm, 0)} циклов'
            element.z_workload = element.z_base
            element.z_workload_source = 'телеметрия (циклы)'
            return

        # Вариант Б1 — по диагностике (K_сост на уровне детали)
        detail_state = equip.get('detail_state') or {}
        if detail_state:
            for d in details:
                k_state = _f(detail_state.get(d['name']))
                d['z_est'] = k_state * d['norm'] if k_state is not None else None
            if any(_f(d.get('z_est')) is not None for d in details):
                self._finish_base(element, details, 'Б1',
                                  'K_сост,д × S_нач,д (коэффициент из протокола диагностики)')
                return

        # Вариант Б2 — экспертная (документальная) оценка остаточного ресурса деталей
        if details:
            for d in details:
                d['z_est'] = d['norm'] - d['age']
            self._finish_base(
                element, details, 'Б2',
                'Z_эц,д = S_нач,д − S_факт,д (назначенный ресурс детали минус её возраст)'
            )
            return

        # Вариант В — календарный, резервный
        element.z_base = norm - element.age
        element.z_base_variant = 'В'
        element.z_base_formula = f'{num(norm, 2)} − {num(element.age, 2)}'
        element.z_base_note = 'резервный вариант: данных по деталям нет'

    def _finish_base(self, element: ElementResult, details: List[Dict],
                     variant: str, note: str) -> None:
        """Z_база элемента = min по всем его деталям (принцип слабого звена)."""
        values = []
        for d in details:
            z_est = _f(d.get('z_est'))
            if z_est is None:
                continue
            d['z_base'] = z_est
            d['formula'] = f'{num(d["norm"], 2)} − {num(d["age"], 2)} = {num(z_est, 2)}'
            values.append((d['name'], z_est))

        if not values:
            element.z_base = element.norm - element.age
            element.z_base_variant = 'В'
            element.z_base_formula = f'{num(element.norm, 2)} − {num(element.age, 2)}'
            element.z_base_note = 'резервный вариант: детали без ресурса'
            return

        values.sort(key=lambda pair: pair[1])
        weak_detail, weak_value = values[0]
        element.z_base = weak_value
        element.z_base_variant = variant
        element.z_base_formula = 'min(' + '; '.join(
            f'{name} = {num(value, 2)}' for name, value in values
        ) + f') = {num(weak_value, 2)}'
        element.z_base_note = (f'слабейшая деталь «{weak_detail}»: {note}')

    # -- Шаги 3-6: коэффициенты -------------------------------------------

    def _calc_coefficients(self, element: ElementResult, equip: Dict) -> None:
        self._calc_k_state(element, equip)
        self._calc_k_cond(element, equip)
        self._calc_k_repair(element, equip)
        self._calc_k_fail(element, equip)

    def _calc_k_state(self, element: ElementResult, equip: Dict) -> None:
        """K_сост = 1 − (1/n)·Σ |Δij| / Допускij."""
        params = equip.get('state_params') or []
        rows = []
        for p in params:
            if not isinstance(p, dict):
                continue
            nominal = _f(p.get('nominal'))
            actual = _f(p.get('actual'))
            tol_max = _f(p.get('tol_max'))
            tol_min = _f(p.get('tol_min'))
            tolerance = None
            if nominal is not None and tol_max is not None:
                tolerance = abs(tol_max - nominal)
            if tolerance is None and nominal is not None and tol_min is not None:
                tolerance = abs(nominal - tol_min)
            if tolerance in (None, 0) or nominal is None or actual is None:
                rows.append({'name': p.get('name') or 'Параметр', 'skip': True})
                continue
            delta = abs(actual - nominal)
            ratio = delta / tolerance
            rows.append({
                'name': p.get('name') or 'Параметр',
                'nominal': nominal,
                'actual': actual,
                'tolerance': tolerance,
                'delta': delta,
                'ratio': ratio,
                'formula': f'|{num(actual, 4)} − {num(nominal, 4)}| / {num(tolerance, 4)}'
                           f' = {num(ratio, 3)}',
                'skip': False,
            })

        element.k_state_detail = rows
        valid = [r for r in rows if not r.get('skip')]
        if not valid:
            element.k_state = 1.0
            element.k_state_note = 'протокол диагностики отсутствует → K_сост = 1'
            return

        n = len(valid)
        total = sum(r['ratio'] for r in valid)
        element.k_state = max(0.0, 1.0 - total / n)
        element.k_state_note = (f'n = {n}, Σ|Δ|/Допуск = {num(total, 3)}, '
                                f'K = 1 − {num(total, 3)}/{n} = {num(element.k_state, 4)}')

    def _calc_k_cond(self, element: ElementResult, equip: Dict) -> None:
        """K_эксл = 1 − θ·(1 − Усл_факт/Усл_норм)."""
        condition = equip.get('condition') or {}
        fact = _f(condition.get('fact'))
        norm = _f(condition.get('norm'))
        theta = self.params.theta_conditions
        if fact is not None and norm and norm > 0:
            ratio = fact / norm
            element.k_cond = max(0.0, 1.0 - theta * (1.0 - ratio))
            element.k_cond_note = (f'1 − {num(theta, 2)}·(1 − {num(fact, 2)}/{num(norm, 2)})'
                                   f' = {num(element.k_cond, 4)}')
        else:
            element.k_cond = 1.0
            element.k_cond_note = 'режимная карта отсутствует → K_эксл = 1'

    def _calc_k_repair(self, element: ElementResult, equip: Dict) -> None:
        """K_рем: замена на новое / качественный / некачественный ремонт."""
        repair = equip.get('repair') or {}
        explicit = _f(repair.get('k'))
        if explicit is not None:
            element.k_repair = max(0.0, min(1.0, explicit))
            element.k_repair_note = f'задано вручную: K_рем = {num(element.k_repair, 4)}'
            return

        quality = (repair.get('quality') or 'none').lower()
        if quality in REPAIR_QUALITY:
            element.k_repair = REPAIR_QUALITY[quality]
            element.k_repair_note = REPAIR_QUALITY_LABEL[quality]
        else:
            element.k_repair = 1.0
            element.k_repair_note = 'неизвестный вид ремонта → K_рем = 1'

        fact = _f(repair.get('fact'))
        norm = _f(repair.get('norm'))
        delta = self.params.delta_repair
        if fact is not None and norm and norm > 0 and quality in ('quality', 'poor'):
            ratio = fact / norm
            calc = 1.0 - delta * (1.0 - ratio)
            element.k_repair = max(0.0, min(element.k_repair, calc))
            element.k_repair_note = (f'{REPAIR_QUALITY_LABEL[quality]}; '
                                    f'1 − {num(delta, 2)}·(1 − {num(fact, 2)}/{num(norm, 2)})'
                                    f' = {num(element.k_repair, 4)}')

    def _calc_k_fail(self, element: ElementResult, equip: Dict) -> None:
        """k_повр = 1 − α·N_отказ − β·N_поврежд, неотрицательное."""
        n_fail = int(_f(equip.get('failures')) or 0)
        n_damage = int(_f(equip.get('damages')) or 0)
        alpha = self.params.alpha_fail
        beta = self.params.beta_damage
        raw = 1.0 - alpha * n_fail - beta * n_damage
        element.n_fail = n_fail
        element.n_damage = n_damage
        element.k_fail = max(0.0, raw)
        element.k_fail_note = (f'1 − {num(alpha, 2)}·{n_fail} − {num(beta, 2)}·{n_damage}'
                               f' = {num(element.k_fail, 4)}')

    # -- Шаг 7: некратные замены -------------------------------------------

    def _calc_replacement_ratio(self, element: ElementResult) -> None:
        """Σ факт/нач по некратным заменам деталей < 1."""
        details = element.details
        if not details:
            element.replacement_sum = None
            element.replacement_note = 'деталей нет — шаг пропущен'
            return
        total = 0.0
        count = 0
        for d in details:
            ratio = _f(d.get('consumed_ratio'))
            if ratio is not None:
                total += ratio
                count += 1
        if count:
            element.replacement_sum = total
            element.replacement_note = (f'Σ факт/нач по {count} замен(ам) = {num(total, 3)}'
                                        f' → {"< 1, ресурс деталей не исчерпан" if total < 1 else "≥ 1, замены исчерпали ресурс"}')
        else:
            element.replacement_sum = None
            element.replacement_note = 'наработка по заменам не задана → шаг пропущен'

    # -- Шаг 8: ресурс элемента --------------------------------------------

    def _finalize_element(self, element: ElementResult,
                          full: bool = True) -> None:
        """Z_эл = Z_база × K_сост × K_эксл × K_рем × k_повр.

        full=False — только базовый ресурс и K_сост (Алгоритм 2, где
        остальные поправки не применяются по методике).
        """
        z_base = element.z_base if element.z_base is not None else 0.0
        factors = [('K_сост', element.k_state)]
        if full:
            factors += [('K_эксл', element.k_cond),
                        ('K_рем', element.k_repair),
                        ('k_повр', element.k_fail)]
        product = 1.0
        for _, value in factors:
            product *= value
        raw = z_base * product
        element.z_element = max(0.0, raw)
        # Формула идёт числом (чтобы сходилась с методикой), а следом —
        # человекочитаемый срок: «5,000 × … = 0,000 (0 дн)», а не «= 0,000 лет».
        element.z_element_formula = (
            f'{num(z_base, 3)} × ' +
            ' × '.join(f'{num(value, 3)}' for _, value in factors) +
            f' = {num(element.z_element, 3)} ({years_to_text(element.z_element)})'
        )
        element.z_element_note = ('полный набор поправок (Алгоритм 4/5)'
                                  if full else 'только K_сост (Алгоритм 2)')
        if raw < 0:
            element.z_element_note += '; отрицательный ресурс ограничен нулем'

    def _prepare(self, equipment_data: List[Dict], critical_only: bool = False,
                 full_factors: bool = True
                 ) -> Tuple[List[ElementResult], List[ElementResult]]:
        """Готовит элементы и считает итоговый ресурс каждого."""
        prepared: List[ElementResult] = []
        for equip in equipment_data or []:
            if not isinstance(equip, dict):
                continue
            element = self._build_element(equip)
            if element is None:
                continue
            if critical_only and not element.critical_key:
                element.used = False
                element.skip_reason = 'не является критическим элементом'
            elif not element.details:
                # Расчёт ведётся только по заменяемым деталям. Если у элемента
                # таких нет, включение его в расчёт дало бы ложные 20 лет
                # по сроку полной проверки — исключаем и объясняем причину.
                element.used = False
                element.skip_reason = 'нет заменяемых деталей'
            elif element.removed:
                # Оборудование снято с эксплуатации: его ресурс уже выработан,
                # в текущую оценку оно не входит. Полная замена оборудования
                # создаёт новую запись с новой датой установки, и уже она
                # участвует в расчёте на новый срок.
                element.used = False
                element.skip_reason = (
                    f'снято с эксплуатации {element.removal_date}'
                    if element.removal_date else 'снято с эксплуатации')
            self._finalize_element(element, full=full_factors)
            prepared.append(element)
        return prepared, [e for e in prepared if e.used]

    def _skip_elements(self, elements: List[ElementResult]) -> None:
        for element in elements:
            if element.used:
                continue
            element.z_element = 0.0

    # -- общие блоки трассировки ------------------------------------------

    def _header(self, result: AlgorithmResult) -> None:
        result.steps.append(Step('title', f'АЛГОРИТМ {result.algorithm_number}: '
                                          f'{result.algorithm_name}'))
        result.steps.append(Step('note', 'Исходные данные указаны в годах; '
                                         'результаты округлены для отображения.'))

    def _element_header(self, result: AlgorithmResult, index: int,
                        element: ElementResult) -> None:
        label = element.name
        if element.critical_key:
            label += f'   [критический: {critical_title(element.critical_key)}]'
        result.steps.append(Step('title', f'ЭЛЕМЕНТ {index}: {label}'))
        result.steps.append(Step('note', f'S_нач = {years_to_text(element.norm)} '
                                         f'({element.norm_source}); возраст = '
                                         f'{years_to_text(element.age)}'
                                         + (f'; демонтирован {element.removal_date or ""}'
                                            if element.removed else '')))
        if not element.used and element.skip_reason:
            result.steps.append(Step('warn', f'⚠ {element.skip_reason} — в расчёт не входит'))

    def _step_base(self, result: AlgorithmResult, element: ElementResult,
                   z_calendar: Optional[float] = None) -> None:
        """Шаг 2: базовый ресурс (в т.ч. вариант Алгоритма 4)."""
        result.steps.append(Step('formula', '  Шаг 2. Базовый ресурс Z_база'))
        norm = element.norm or 0.0

        if z_calendar is not None:
            result.steps.append(Step('value',
                                     f'    Z_календ = S_нач − S_факт = {num(norm, 2)}'
                                     f' − {num(element.age, 2)} = {years_to_text(z_calendar)}'))
            result.steps.append(Step('note',
                                     '    Основа — календарный срок полной проверки. '
                                     'Взвешивание с фактической наработкой не применяется: '
                                     'телеметрии по элементам нет.'))
            result.steps.append(Step('value',
                                     f'    Z_база = Z_календ = {years_to_text(z_calendar)}'))
            return

        result.steps.append(Step('note', f'    Вариант {element.z_base_variant}: '
                                         f'{element.z_base_note}'))
        for detail in element.details:
            if detail.get('z_base') is None:
                continue
            result.steps.append(Step('value',
                                     f'      деталь «{detail["name"]}»: S_нач = '
                                     f'{years_to_text(detail["norm"])}, возраст = '
                                     f'{years_to_text(detail["age"])} → '
                                     f'Z = {years_to_text(detail["z_base"])}'))
        result.steps.append(Step('formula',
                                 f'    Z_база = {element.z_base_formula}'))

    def _step_coefficients(self, result: AlgorithmResult, element: ElementResult) -> None:
        result.steps.append(Step('formula', '  Шаг 3. K_сост = 1 − (1/n)·Σ |Δij|/Допускij'))
        for row in element.k_state_detail:
            if row.get('skip'):
                continue
            result.steps.append(Step('value', f'    {row["name"]}: {row["formula"]}'))
        result.steps.append(Step('value', f'    → K_сост = {num(element.k_state, 4)}'
                                          f'   ({element.k_state_note})'))

        result.steps.append(Step('formula', '  Шаг 4. K_эксл = 1 − θ·(1 − Усл_факт/Усл_норм)'))
        result.steps.append(Step('value', f'    → K_эксл = {num(element.k_cond, 4)}'
                                          f'   ({element.k_cond_note})'))

        result.steps.append(Step('formula', '  Шаг 5. K_рем = 1 − δ·(1 − Рем_факт/Рем_норм)'))
        result.steps.append(Step('value', f'    → K_рем = {num(element.k_repair, 4)}'
                                          f'   ({element.k_repair_note})'))

        result.steps.append(Step('formula', '  Шаг 6. k_повр = 1 − α·N_отказ − β·N_поврежд'))
        result.steps.append(Step('value', f'    N_отказ = {element.n_fail},'
                                          f' N_поврежд = {element.n_damage}'
                                          f'   ({element.k_fail_note})'))

        if element.replacement_sum is not None:
            result.steps.append(Step('formula', '  Шаг 7. Учёт некратных замен: '
                                                'Σ факт/нач < 1'))
            result.steps.append(Step('value', f'    {element.replacement_note}'))

    def _step_element_total(self, result: AlgorithmResult, element: ElementResult) -> None:
        result.steps.append(Step('formula', '  Шаг 8. Ресурс элемента '
                                            'Z_эл = Z_база × K_сост × K_эксл × K_рем × k_повр'))
        result.steps.append(Step('value', f'    {element.z_element_formula}'))
        if element.z_element <= 0 and (element.z_base or 0) > 0:
            result.steps.append(Step('warn', '    ⚠ ресурс исчерпан: элемент требует замены'))

    # -- рекомендации -------------------------------------------------------

    def _rating(self, resource: float) -> str:
        if resource <= 0:
            return 'КРИТИЧЕСКИЙ (ресурс исчерпан)'
        if resource < 1:
            return 'КРИТИЧЕСКИЙ (менее 1 года)'
        if resource < 3:
            return 'НИЗКИЙ (1-3 года)'
        if resource < 5:
            return 'СРЕДНИЙ (3-5 лет)'
        return 'ВЫСОКИЙ (более 5 лет)'

    def _recommendation(self, resource: float, weak: Optional[ElementResult],
                        next_diagnosis: Optional[float]) -> str:
        weak_name = weak.name if weak else 'не определён'
        if resource <= 0:
            return (f'Ресурс исчерпан. Слабое звено: {weak_name}. '
                    f'Требуется немедленная замена или капитальный ремонт.')
        if resource < 1:
            return (f'Остаточный ресурс менее 1 года. Слабое звено: {weak_name}. '
                    f'Замена планируется в ближайшем квартале.')
        if resource < 3:
            return (f'Ресурс {years_to_text(resource)}. Слабое звено: {weak_name}. '
                    f'Замена в течение 1-2 лет.')
        if resource < 5:
            return (f'Ресурс {years_to_text(resource)}. Слабое звено: {weak_name}. '
                    f'Плановое диагностирование в ближайший год.')
        return (f'Ресурс {years_to_text(resource)}. Слабое звено: {weak_name}. '
                f'Состояние удовлетворительное, диагностирование по графику.')

    def _finalize(self, result: AlgorithmResult, used: List[ElementResult]) -> None:
        weak = min(used, key=lambda e: e.z_element) if used else None
        result.weak_element = weak.name if weak else None
        result.weak_element_key = weak.critical_key if weak else None

    def _empty(self, number: int, reason: str) -> AlgorithmResult:
        return AlgorithmResult(
            algorithm_name=ALGORITHM_TITLES[number],
            algorithm_number=number,
            result=0.0,
            steps=[Step('title', f'АЛГОРИТМ {number}: {ALGORITHM_TITLES[number]}'),
                   Step('warn', f'⚠ {reason}')],
            error=reason,
            recommendation=f'Расчёт не выполнен: {reason}',
        )

    # -- Алгоритм 0 ---------------------------------------------------------

    def calculate_algorithm_0(self, equipment_data: List[Dict]) -> AlgorithmResult:
        """Алгоритм 0 — утверждённая методика: Z = S_назн − S_факт, среднее."""
        result = AlgorithmResult('Утверждённая методика', 0, 0.0)
        self._header(result)
        prepared, used = self._prepare(equipment_data)

        if not used:
            return self._empty(0, 'нет элементов с известным нормативным ресурсом')

        result.steps.append(Step('formula', 'Методика: Z_элемент = S_назн − S_факт, '
                                            'Z_ГРП = Σ Z_элемент / m'))
        for i, element in enumerate(prepared, 1):
            self._element_header(result, i, element)
            if not element.used:
                continue
            element.z_element = max(0.0, element.z_base or 0.0)
            element.z_element_formula = (f'{num(element.z_base, 2)} '
                                         f'({years_to_text(element.z_base)})')
            element.z_element_note = 'утверждённая методика: ресурс без поправок'
            result.steps.append(Step('value',
                                     f'    Z_элемент = {num(element.norm, 2)}'
                                     f' − {num(element.age, 2)} = {years_to_text(element.z_base)}'))

        resources = [e.z_base if e.z_base is not None else 0.0 for e in used]
        m = len(used)
        total = sum(resources)
        avg = total / m if m else 0.0
        result.result = max(0.0, avg)
        result.elements = prepared
        result.scalars = {'sum_r': total, 'm': m, 'avg_resource': avg}
        result.next_diagnosis = min(result.result * self.params.reserve,
                                    self.params.max_diag_interval)

        self._finalize(result, used)
        result.steps.append(Step('title', 'ИТОГ'))
        result.steps.append(Step('value', f'  m = {m}'))
        result.steps.append(Step('value', f'  Σ Z_элемент = {num(total, 3)}'))
        result.steps.append(Step('value', f'  Z_ГРП = Σ Z / m = {num(total, 3)} / {m}'
                                          f' = {num(avg, 3)} ({years_to_text(avg)})'))
        result.recommendation = self._recommendation(result.result,
                                                     self._weak_of(used), result.next_diagnosis)
        return result

    @staticmethod
    def _weak_of(used: List[ElementResult]) -> Optional[ElementResult]:
        return min(used, key=lambda e: e.z_element) if used else None

    # -- Алгоритм 1 ---------------------------------------------------------

    def calculate_algorithm_1(self, equipment_data: List[Dict]) -> AlgorithmResult:
        """Алгоритм 1 — среднее арифметическое с общим коэффициентом
        K_общ = 1 − (A + B + C) из журнала технической диагностики."""
        result = AlgorithmResult('Среднее арифметическое', 1, 0.0)
        self._header(result)
        result.steps.append(Step('note', 'По методике к элементу применяется только '
                                         'K_сост; остальные коэффициенты не используются, '
                                         'их учёт — в Алгоритмах 2-4.'))
        prepared, used = self._prepare(equipment_data, full_factors=False)

        if not used:
            return self._empty(1, 'нет элементов с известным нормативным ресурсом')

        a = _f(self.coefficients.get('a'))
        b = _f(self.coefficients.get('b'))
        c = _f(self.coefficients.get('c'))
        k_common = _f(self.coefficients.get('k'))
        source = self.coefficients.get('source') or 'журнал технической диагностики'
        if k_common is None:
            k_common = 1.0 - sum(v for v in (a, b, c) if v is not None)
        k_common = max(0.0, min(1.0, k_common))

        result.steps.append(Step('formula', 'Z_ГРП = (Σ Z_элемент / m) × K_общ, '
                                            'где K_общ = 1 − (A + B + C)'))
        for i, element in enumerate(prepared, 1):
            self._element_header(result, i, element)
            if not element.used:
                continue
            result.steps.append(Step('value',
                                     f'    Z_элемент = Z_база × K_сост = '
                                     f'{num(element.z_base, 2)} × {num(element.k_state, 3)}'
                                     f' = {num(element.z_element, 2)} лет'))
        m = len(used)
        total = sum(e.z_element for e in used)
        avg = total / m if m else 0.0
        z_grp = max(0.0, avg * k_common)
        result.result = z_grp
        result.elements = prepared
        result.next_diagnosis = min(z_grp * self.params.reserve,
                                    self.params.max_diag_interval)
        result.scalars = {'avg_Z': avg, 'sum_z': total, 'm': m, 'K_common': k_common,
                          'coeff_a': a, 'coeff_b': b, 'coeff_c': c, 'coeff_k': k_common,
                          'coeff_source': source}

        self._finalize(result, used)
        result.steps.append(Step('title', 'ИТОГ'))
        result.steps.append(Step('value', f'  Среднее Z_элемент = Σ Z / m = {num(total, 3)}'
                                          f' / {m} = {num(avg, 3)}'))
        if all(v is None for v in (a, b, c)):
            result.steps.append(Step('note', '  В журнале диагностики нет коэффициентов A, B, C'
                                             ' → K_общ = 1,000 (снижает ресурс в 1 раз)'))
        else:
            result.steps.append(Step('value',
                                     f'  K_общ = 1 − ({num(a, 2)} + {num(b, 4)}'
                                     f' + {num(c, 4)}) = {num(k_common, 4)}  ({source})'))
        result.steps.append(Step('value', f'  Z_ГРП = {num(avg, 3)} × {num(k_common, 4)}'
                                          f' = {num(z_grp, 3)} ({years_to_text(z_grp)})'))
        result.steps.append(Step('value', f'  T_диагн = min({num(z_grp, 3)} × '
                                          f'{num(self.params.reserve, 2)}; '
                                          f'{num(self.params.max_diag_interval, 0)})'
                                          f' = {years_to_text(result.next_diagnosis)}'))
        result.recommendation = self._recommendation(result.result,
                                                     self._weak_of(used), result.next_diagnosis)
        return result

    # -- Алгоритм 2 ---------------------------------------------------------

    def calculate_algorithm_2(self, equipment_data: List[Dict]) -> AlgorithmResult:
        """Алгоритм 2 — REGION-gaz: принцип слабого звена по критическим элементам."""
        result = AlgorithmResult('REGION-gaz (слабое звено)', 2, 0.0)
        self._header(result)
        prepared, used = self._prepare(equipment_data, critical_only=True)

        if not used:
            return self._empty(2, 'нет критических элементов с известным нормативным ресурсом')

        result.steps.append(Step('formula', 'Z_ГРП = min (Z_рег; Z_пзк; Z_пск; '
                                            'Z_фильтр; Z_арматура)'))
        for i, element in enumerate(prepared, 1):
            self._element_header(result, i, element)
            if not element.used:
                continue
            self._step_base(result, element)
            self._step_coefficients(result, element)
            self._step_element_total(result, element)

        self._finalize(result, used)
        result.result = max(0.0, min(e.z_element for e in used))
        result.elements = prepared
        result.next_diagnosis = min(result.result * self.params.reserve,
                                    self.params.max_diag_interval)
        result.scalars = {'Z_weak': result.result,
                          'T_next_diagnosis': result.next_diagnosis}

        result.steps.append(Step('title', 'ИТОГ'))
        listing = '; '.join(f'Z_{e.critical_key} = {num(e.z_element, 2)}'
                            for e in used if e.critical_key)
        result.steps.append(Step('value', f'  {listing}'))
        result.steps.append(Step('value', f'  Слабое звено: {result.weak_element}'
                                          f' → Z_ГРП = {years_to_text(result.result)}'))
        result.steps.append(Step('value', f'  T_диагн = min({num(result.result, 3)} × '
                                          f'{num(self.params.reserve, 2)}; '
                                          f'{num(self.params.max_diag_interval, 0)})'
                                          f' = {years_to_text(result.next_diagnosis)}'))
        result.recommendation = self._recommendation(result.result,
                                                     self._weak_of(used), result.next_diagnosis)
        return result

    # -- Алгоритм 3 ---------------------------------------------------------

    def calculate_algorithm_3(self, equipment_data: List[Dict]) -> AlgorithmResult:
        """Алгоритм 3 — скорректированная редакция: приоритет фактической
        наработки, двойной учёт K_сост, некратные замены, T_диагн."""
        result = AlgorithmResult(ALGORITHM_TITLES[3], 3, 0.0)
        self._header(result)
        result.steps.append(Step('note', 'Базовая редакция: приоритет фактической наработки; '
                                         'обобщённый K_общ_тех исключён, K_сост применяется '
                                         'двойным учётом (в Z_база и в Z_эл).'))
        prepared, used = self._prepare(equipment_data, critical_only=True)

        if not used:
            return self._empty(3, 'нет критических элементов с известным нормативным ресурсом')

        for i, element in enumerate(prepared, 1):
            self._element_header(result, i, element)
            if not element.used:
                continue
            self._step_base(result, element)
            self._step_coefficients(result, element)
            self._step_element_total(result, element)

        weak = self._weak_of(used)
        result.elements = prepared
        result.weak_element = weak.name if weak else None
        result.weak_element_key = weak.critical_key if weak else None
        result.result = max(0.0, min(e.z_element for e in used))
        result.next_diagnosis = min(result.result * self.params.reserve,
                                    self.params.max_diag_interval)
        result.scalars = {'Z_weak': result.result, 'K_common_tech': None,
                          'T_next_diagnosis': result.next_diagnosis}

        result.steps.append(Step('title', 'ИТОГ'))
        result.steps.append(Step('formula', '  Шаг 9. Слабое звено: Z_слабое = '
                                            'min (Z_рег; Z_пзк; Z_пск; Z_фильтр; Z_арматура)'))
        listing = '; '.join(f'{critical_title(e.critical_key)} = {num(e.z_element, 2)}'
                            for e in used if e.critical_key)
        result.steps.append(Step('value', f'  {listing}'))
        result.steps.append(Step('value', f'  Слабое звено: {result.weak_element}'))
        result.steps.append(Step('formula', '  Шаг 10. Z_ГРП = Z_слабое'))
        result.steps.append(Step('value', f'  Z_ГРП = {years_to_text(result.result)}'))
        result.steps.append(Step('formula', '  Шаг 11. T_диагн = min(Z_ГРП × K_запаса; '
                                            'T_макс)'))
        result.steps.append(Step('value', f'  T_диагн = min({num(result.result, 3)} × '
                                          f'{num(self.params.reserve, 2)}; '
                                          f'{num(self.params.max_diag_interval, 0)})'
                                          f' = {years_to_text(result.next_diagnosis)}'))
        result.steps.append(Step('note', '  Шаг 12. Верификация — сравнить с протоколом '
                                         'испытаний и при расхождении > 20% пересчитать '
                                         'α, β, δ, θ по истории 5-10 объектов.'))
        result.recommendation = self._recommendation(result.result, weak,
                                                     result.next_diagnosis)
        return result

    # -- Алгоритм 4 ---------------------------------------------------------

    def calculate_algorithm_4(self, equipment_data: List[Dict]) -> AlgorithmResult:
        """Алгоритм 4 — календарный ресурс по сроку полной проверки.

        Отличается от скорректированной методики (Алгоритм 3) только базой:
        Z_база = Z_календ = S_нач − S_факт, где S_нач — срок полной проверки
        оборудования, а S_факт — его возраст. Дальше применяются те же
        коэффициенты K_сост, K_эксл, K_рем, k_повр и то же правило слабого звена.

        Взвешивание с фактической наработкой (Z_база = α·Z_календ +
        (1−α)·Z_наработка) из методики не применяется. Телеметрии по элементам
        в базе нет, а без неё Z_наработка подставляется равной Z_календ, и
        смешивание математически сокращалось до того же календарного срока —
        то есть α не влиял ни на что. Поэтому член Z_наработка и вес α убраны,
        а вместе с ними и порог переработки T_крит: он защищал именно то
        смешивание, которого больше нет.

        Внимание к шкале: Z_календ живёт в масштабе 20 лет и отвечает на
        вопрос «сколько прослужит оборудование», тогда как Алгоритм 3 считает
        по 5-летним заменяемым деталям и отвечает «когда истечёт расходник».
        Это разные величины, поэтому расхождение между методиками ожидаемо.
        """
        params = self.params
        result = AlgorithmResult(ALGORITHM_TITLES[4], 4, 0.0)
        self._header(result)
        result.steps.append(Step('note', 'Шаги 6-14 совпадают со скорректированным '
                                         'Алгоритмом 3: K_сост, K_эксл, K_рем, k_повр, '
                                         'учёт некратных замен и принцип слабого звена.'))
        result.steps.append(Step('note', 'База отличается: Z_база = Z_календ = '
                                         'S_нач − S_факт (срок полной проверки минус '
                                         'возраст оборудования). Взвешивание с фактической '
                                         'наработкой отключено — телеметрии нет.'))
        prepared, used = self._prepare(equipment_data, critical_only=True)

        if not used:
            return self._empty(4, 'нет критических элементов с известным нормативным ресурсом')

        for i, element in enumerate(prepared, 1):
            self._element_header(result, i, element)
            if not element.used:
                continue
            norm = element.norm or 0.0
            z_calendar = (element.z_calendar if element.z_calendar is not None
                          else norm - element.age)
            element.z_calendar = z_calendar
            element.z_base = z_calendar
            element.z_base_variant = 'В'
            element.z_base_formula = f'{num(norm, 2)} − {num(element.age, 2)}'
            element.z_base_note = ('календарный ресурс по сроку полной проверки; '
                                   'фактическая наработка не учитывается')
            self._finalize_element(element)

            self._step_base(result, element, z_calendar=z_calendar)
            self._step_coefficients(result, element)
            self._step_element_total(result, element)

        weak = self._weak_of(used)
        result.elements = prepared
        result.weak_element = weak.name if weak else None
        result.weak_element_key = weak.critical_key if weak else None
        result.result = max(0.0, min(e.z_element for e in used))
        result.next_diagnosis = min(result.result * params.reserve, params.max_diag_interval)
        result.scalars = {'Z_weak': result.result, 'K_common_tech': None,
                          'T_next_diagnosis': result.next_diagnosis}

        result.steps.append(Step('title', 'ИТОГ'))
        listing = '; '.join(f'{critical_title(e.critical_key)} = {num(e.z_element, 2)}'
                            for e in used if e.critical_key)
        result.steps.append(Step('value', f'  {listing}'))
        result.steps.append(Step('value', f'  Слабое звено: {result.weak_element}'))
        result.steps.append(Step('value', f'  Z_ГРП = {years_to_text(result.result)}'))
        result.steps.append(Step('value', f'  T_диагн = min({num(result.result, 3)} × '
                                          f'{num(params.reserve, 2)}; '
                                          f'{num(params.max_diag_interval, 0)})'
                                          f' = {years_to_text(result.next_diagnosis)}'))
        result.recommendation = self._recommendation(result.result, weak,
                                                     result.next_diagnosis)
        return result


def calculate_all_algorithms(equipment_data: List[Dict],
                             norm_func: Optional[Callable[[Dict], Optional[float]]] = None,
                             params: Optional[AlgorithmParams] = None,
                             coefficients: Optional[Dict] = None
                             ) -> Dict[int, AlgorithmResult]:
    """Расчёт по всем алгоритмам 0-4."""
    calculator = GRPResourceCalculator(norm_func, params, coefficients)
    return {
        0: calculator.calculate_algorithm_0(equipment_data),
        1: calculator.calculate_algorithm_1(equipment_data),
        2: calculator.calculate_algorithm_2(equipment_data),
        3: calculator.calculate_algorithm_3(equipment_data),
        4: calculator.calculate_algorithm_4(equipment_data),
    }
