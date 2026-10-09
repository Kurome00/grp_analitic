"""Окно «Алгоритмы» — расчёт остаточного ресурса ГРП по методике.

Окно не показывает «магическое» число: рядом с результатом всегда видно,
из каких данных он получен, какая формула применена и какие данные отсутствовали
(с явной пометкой, что соответствующий коэффициент принят равным 1).
"""
import copy
import tkinter as tk
from datetime import date
from tkinter import messagebox, ttk

from core.config import FULL_CHECK_TERM
from core import diagnostic_log
from core.lifetimes import expiry_date
from core.timefmt import years_to_text
from ui.window_utils import fit_window
from ui.widgets_calc import (
    ACCENT,
    BAD,
    BG,
    CARD,
    F_BODY,
    F_HERO,
    F_TABLE_B,
    GOOD,
    LINE,
    SUB,
    TEXT,
    TINT_BAD,
    TINT_GOOD,
    TINT_MANUAL,
    TINT_PART,
    TINT_SKIP,
    TINT_WARN,
    WARN,
    Pane,
    calc_theme,
    card,
    card_title,
    fit_table,
    head_row,
    note,
    restore_theme,
    table,
)
from logic.algorithms import (
    ALGORITHM_SHORT,
    ALGORITHM_TITLES,
    DAMAGE_MARKERS,
    DEADLINE_ALGORITHMS,
    FAILURE_MARKERS,
    GRPResourceCalculator,
    POOR_REPAIR_MARKERS,
    PRIMARY_ALGORITHM,
    AlgorithmParams,
    algo_label,
    calculate_all_algorithms,
    classify_critical,
    critical_short_title,
    critical_title,
    driving_part,
    num,
    signed_years,
    weak_link_elements,
)

MUTED = SUB

# Ширина ленты методик. Плитка должна вмещать «Алгоритм N», короткое имя и
# остаток в одну строку каждое, иначе лента растёт в высоту и методики
# начинают уезжать за нижний край окна.
RAIL_W = 244

# Предел горизонта на ползунке «Срок замены»: пять лет — норма заменяемых
# запчастей, дальше смотреть бессмысленно, там всё равно всё просрочено.
HORIZON_MAX = 5.0
# Ползунок щёлкает по месяцам: подписанный срок всегда получается ровным
# («2 года 5 мес»), а не «2 года 5 мес 2 дн» из-за дробного шага мыши.
HORIZON_SNAP = 1.0 / 12.0
CONSERVATIVE_NOTE = (
    f'Сроки по {algo_label(DEADLINE_ALGORITHMS[0])} и {algo_label(DEADLINE_ALGORITHMS[1])} '
    'показываются раздельно: сводить их в одну величину '
    'нельзя — они считают разные величины (по заменяемым запчастям и по '
    'календарному сроку оборудования), поэтому расхождение между ними ожидаемо.'
)

def _btn(parent, text, command, color=ACCENT, font_size=10, padx=14):
    """Плоская кнопка с подсветкой при наведении."""
    palette = {
        'success': (GOOD, _darken(GOOD)),
        'danger': (BAD, _darken(BAD)),
        'muted': (SUB, _darken(SUB)),
    }
    bg, bg_hover = palette.get(color, (color, _darken(color)))
    btn = tk.Button(
        parent, text=text, command=command, bg=bg, fg='#ffffff',
        font=('Segoe UI', font_size), padx=padx, pady=6,
        bd=0, relief='flat', cursor='hand2', activebackground=bg_hover,
        activeforeground='#ffffff', highlightthickness=0,
    )
    btn.bind('<Enter>', lambda e, b=btn, c=bg_hover: b.config(bg=c))
    btn.bind('<Leave>', lambda e, b=btn, c=bg: b.config(bg=c))
    return btn


def _darken(hex_color, factor=0.85):
    """Затемняет цвет для эффекта наведения."""
    try:
        r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    except (ValueError, IndexError):
        return hex_color
    return '#%02x%02x%02x' % (int(r * factor), int(g * factor), int(b * factor))


def _bound_text(value):
    """Граница диапазона в сообщении: «0», «1», «0,05» — без лишних нулей."""
    return num(value, 0 if float(value).is_integer() else 2)


def _range_text(lo, hi):
    """Подпись диапазона рядом с полем: «0…1» или «больше 0»."""
    if hi is None:
        return f'больше {_bound_text(lo)}'
    return f'{_bound_text(lo)}…{_bound_text(hi)}'


def _manual_text(value):
    """Ручной K в поле: «0,85» вместо «0,850» — лишние нули только мешают."""
    if value is None:
        return ''
    return f'{float(value):.4f}'.rstrip('0').rstrip('.').replace('.', ',')


def parse_coefficient(raw, label, lo=0.0, hi=1.0, allow_empty=True):
    """Поле коэффициента → (значение, текст ошибки).

    Пустая строка — «считать по формуле»: (None, ''). Значение вне диапазона
    (или не число) не принимается: значение None и текст, по которому поле
    подсвечивается. Разбор вынесен из окна, чтобы проверялся тестами без Tk.

    hi=None — верхней границы нет, и нижняя берётся строго («больше 0»):
    так проверяется T_макс, он измеряется годами, а не долями единицы.
    """
    text = (raw or '').strip().replace(',', '.')
    if not text:
        return None, '' if allow_empty else f'{label}: укажите значение'
    limit = _range_text(lo, hi)
    try:
        value = float(text)
    except ValueError:
        return None, f'{label}: нужно число {limit}'
    if value < lo or (hi is None and value == lo) \
            or (hi is not None and value > hi):
        return None, f'{label}: допускается {limit}'
    return value, ''


# Поля панели «Коэффициенты методики»: (поле, подпись, разрядность, назначение,
# нижняя граница, верхняя граница). Все коэффициенты принимаются от 0 до 1;
# верхняя граница None означает «строго больше нижней» (T_макс — срок в годах).
WEIGHT_FIELDS = (
    ('alpha_fail', 'α · отказ', 2, 'k повр = 1 − α·N_отказ − β·N_повр',
     0.0, 1.0),
    ('beta_damage', 'β · повреждение', 2, 'повреждения слабее отказов (α > β)',
     0.0, 1.0),
    ('theta_conditions', 'θ · условия', 2, 'K эксл = 1 − θ·(1 − Усл/Усл.норм)',
     0.0, 1.0),
    ('delta_repair', 'δ · ремонт', 2, 'K рем = 1 − δ·(1 − Рем/Рем.норм)',
     0.0, 1.0),
    ('reserve', 'K запаса', 2, 'T диагн = min(Z_ГРП·K_запаса; T_макс)',
     0.0, 1.0),
    ('max_diag_interval', 'T_макс', 1,
     'верхняя граница междиагностического интервала', 0.0, None),
)

# Ручные поправки: пустое поле — считать по формуле методики.
MANUAL_FIELDS = (
    ('k_state_manual', 'K сост', 'вместо расчёта по протоколу диагностики'),
    ('k_cond_manual', 'K эксл (K усл)', 'вместо расчёта по режимной карте'),
    ('k_repair_manual', 'K рем', 'вместо оценки по виду ремонта'),
    ('k_fail_manual', 'k повр', 'вместо 1 − α·N_отказ − β·N_повр'),
)


def _part_residual(part):
    """Остаток заменяемой запчасти: заданный методикой, иначе норма минус возраст."""
    if not part:
        return None
    z = part.get('z_base')
    if z is None:
        z = (part.get('norm') or 0.0) - (part.get('age') or 0.0)
    return z


def _plural(count, one, few, many):
    """Русское склонение числительного: 1 год, 2 года, 5 лет."""
    tail = abs(count) % 100
    if 11 <= tail <= 14:
        return many
    tail %= 10
    if tail == 1:
        return one
    if 2 <= tail <= 4:
        return few
    return many


def _horizon_text(value):
    """Горизонт ползунка в виде срока.

    Ползунок щёлкает по месяцам, а years_to_text переводит в дни и печатает
    «6 мес 2 дн» вместо «6 мес». Здесь считаем целые месяцы сами, чтобы
    подпись всегда была ровной: «1 год 6 мес».
    """
    if not value or value <= 0:
        return '0 лет'
    months = int(round(value * 12))
    years, rest = divmod(months, 12)
    if not rest:
        return f'{years} {_plural(years, "год", "года", "лет")}'
    head = f'{years} {_plural(years, "год", "года", "лет")} ' if years else ''
    return f'{head}{rest} мес'


def _counted_parts(element):
    """Запчасти элемента, которые методика действительно учитывает (норма 5 лет)."""
    return [d for d in (element.details or []) if _is_counted_part(d)]


def _pick_parts(element):
    """Что менять у элемента: одна запчасть — та, что держит ресурс элемента.

    Это запчасть с наименьшим остатком (её же показывает отчёт как
    «определяющую»). Раньше сюда попадали все просроченные запчасти сразу, и шаг
    продления выглядел как требование менять пол-элемента, хотя срок двигает
    только самая изношенная: остальные истекают позже.
    """
    parts = _counted_parts(element)
    return sorted(parts, key=_part_residual)[:1]


def _parts_text(parts, limit=3):
    """Перечень запчастей для строки: первые несколько и сколько ещё."""
    names = [str(d.get('name')) for d in parts]
    if not names:
        return '—'
    shown = ', '.join(names[:limit])
    return shown if len(names) <= limit else f'{shown} и ещё {len(names) - limit}'


def counted_part_keys(payload):
    """Учитываемые запчасти ГРП парами (equipment_id, name).

    Имя запчасти — единственная связь между payload и element.details: в
    подробностях расчёта лежат те же имена (logic/algorithms.py, _active_details).
    """
    keys = set()
    for equipment in payload or []:
        equipment_id = equipment.get('equipment_id')
        for detail in equipment.get('details') or []:
            if _is_counted_part({'norm': detail.get('norm_years')}):
                keys.add((equipment_id, detail.get('name')))
    return keys


def simulate_with_renewed(number, payload, params, coefficients, renewed):
    """Пересчёт методики, если названные запчасти заменены сегодня.

    renewed — пары (equipment_id, name): меняется одна названная запчасть, а не
    весь узел. Иначе прирост в шаге продления обещал бы одно, а считался бы по
    замене всего оборудования.

    Идёт через настоящий движок, а не через копию формул: иначе лестница
    продления разошлась бы с расчётом при любой правке методики.
    """
    payload = copy.deepcopy(payload or [])
    today = date.today().isoformat()
    for equipment in payload:
        equipment_id = equipment.get('equipment_id')
        for detail in equipment.get('details') or []:
            if not _is_counted_part({'norm': detail.get('norm_years')}):
                continue
            if (equipment_id, detail.get('name')) in renewed:
                detail['install_date'] = today
    calculator = GRPResourceCalculator(None, params, coefficients)
    return getattr(calculator, f'calculate_algorithm_{number}')(payload)


def extension_step_limit(payload):
    """Сколько шагов замен считаем: по числу запчастей, но не больше предела.

    Шагов нужно не меньше, чем учитываемых запчастей в ГРП: пока срок держит
    запчасть за запчастью, лестница на двенадцати шагах обрывалась бы на
    середине и сообщала, что продлить больше нельзя, хотя менять осталось ещё.
    """
    return max(EXTENSION_STEPS,
               min(len(counted_part_keys(payload)) + 1, EXTENSION_STEPS_MAX))


def _ladder_candidate(result, seen):
    """Ближайшая к замене запчасть среди слабых звеньев: (элемент, запчасть).

    Слабых звеньев обычно несколько: если у элементов срок истекает в один день,
    замена запчасти одного из них не двигает общий срок — минимум держит другой.
    Поэтому кандидат перебирается по всем слабым звеньям, а уже заменённые
    запчасти пропускаются: у одного узла изношенных запчастей может быть
    несколько, и каждая — отдельный шаг.
    """
    for element in weak_link_elements(result.used_elements):
        picked = _pick_parts(element)
        if not picked:
            continue
        part = picked[0]
        if (element.equipment_id, part.get('name')) not in seen:
            return element, part
    return None, None


def build_extension_ladder(number, payload, params, coefficients, result,
                           limit=None):
    """Лестница продления: замена каких запчастей что даёт, шаг за шагом.

    Шаг — замена запчастей текущего слабого звена. Оборудование здесь не
    меняется: замена узла целиком остаётся отдельной операцией в журнале замен
    (db/database_pg.py, replace_equipment_completely).

    Шаг набирает столько запчастей, сколько нужно, чтобы срок действительно
    сдвинулся: у просроченного элемента изношенных запчастей бывает несколько, а
    у совпавших по сроку слабых звеньев срок держит каждое — от замены одной
    запчасти результат не меняется. Обычный случай — одна запчасть за шаг.

    Если замена запчастей срок не двигает вовсе, лестница — один шаг с
    «parts_ineffective»: «no_parts» — учитываемых запчастей в ГРП нет,
    «weak_without_parts» — они есть, но слабое звено держит срок не по ним.
    """
    steps = []
    if result is None or result.error or not result.used_elements:
        return steps
    weak = weak_link_elements(result.used_elements)[0]
    all_parts = counted_part_keys(payload)
    if limit is None:
        limit = extension_step_limit(payload)
    probe = (simulate_with_renewed(number, payload, params, coefficients, all_parts)
             if all_parts else None)
    picked = _pick_parts(weak)
    if probe is None or abs(probe.result - result.result) <= 1e-9:
        # Либо учитываемых запчастей в ГРП нет, либо замена всех их срок не
        # изменила: методика считает ресурс по оборудованию, а не по износу
        # запчастей. Менять по расчёту нечего.
        return [{'element': weak, 'parts': picked,
                 'before': result.result, 'after': result.result, 'gain': 0.0,
                 'stuck': True, 'parts_ineffective': True,
                 'no_parts': not all_parts,
                 'weak_without_parts': bool(all_parts) and not picked}]

    renewed, seen = set(), set()
    sim = simulate_with_renewed(number, payload, params, coefficients, renewed)
    for _ in range(limit):
        if sim.error or not sim.used_elements:
            break
        element, part = _ladder_candidate(sim, seen)
        if part is None:
            # Все слабые звенья обойдены: менять у них больше нечего.
            steps.append({'element': weak_link_elements(sim.used_elements)[0],
                          'parts': [], 'before': sim.result, 'after': sim.result,
                          'gain': 0.0, 'stuck': True})
            break
        owner, parts, units = element, [], [element.name]
        after = sim
        while True:
            key = (element.equipment_id, part.get('name'))
            renewed.add(key)
            seen.add(key)
            parts.append(part)
            after = simulate_with_renewed(number, payload, params, coefficients,
                                          renewed)
            if after.result > sim.result + 1e-9:
                break
            element, part = _ladder_candidate(after, seen)
            if part is None:
                break
            if element.name not in units:
                units.append(element.name)
        gain = after.result - sim.result
        steps.append({'element': owner, 'units': units, 'parts': parts,
                      'before': sim.result, 'after': after.result, 'gain': gain,
                      'stuck': gain <= 0})
        sim = after
    return steps


def _step_head_text(step):
    """Что даёт шаг: «замена запчасти «X» в «РДБК-1М-50/35» даёт +1 год 2 мес»."""
    names = [str(part.get('name')) for part in step.get('parts') or []]
    if not names:
        return ''
    listed = ', '.join(f'«{name}»' for name in names[:2])
    if len(names) > 2:
        listed += f' и ещё {len(names) - 2}'
    units = [str(name) for name in (step.get('units') or [step['element'].name])]
    where = ', '.join(f'«{name[:40]}»' for name in units[:2])
    if len(units) > 2:
        where += f' и ещё {len(units) - 2}'
    what = 'запчасти' if len(names) == 1 else 'запчастей'
    return (f'замена {what} {listed} в {where} даёт '
            f'+{years_to_text(step["gain"])}')


def _last_replacement_on(journal):
    """Самая поздняя дата замены в журнале ('ГГГГ-ММ-ДД').

    Журнал замен ведётся по типам оборудования, а не по запчастям, поэтому дата
    последнего ремонта — единственный ориентир для запчастей без собственной даты
    установки. Допущение выносится в замечания к расчёту, чтобы пользователь
    видел, откуда взялась дата.
    """
    best = None
    for record in (journal or {}).values():
        for entry in record.get('entries') or []:
            value = entry.get('date')
            if not value:
                continue
            text = str(value).strip()[:10]
            if len(text) == 10 and (best is None or text > best):
                best = text
    return best


def _tree_hier(parent, columns, widths, height=8):
    """Дерево с раскрываемыми строками: оборудование → его запчасти."""
    return table(parent, columns, widths, height=height, expand=False,
                 tree=True, tree_width=300)


def _is_counted_part(detail):
    """Запчасть входит в методику: норма ровно 5 лет."""
    if not detail:
        return False
    norm = detail.get('norm', detail.get('norm_years'))
    try:
        return abs(float(norm) - PART_NORM_YEARS) < 0.01
    except (TypeError, ValueError):
        return False


def _due_date(years):
    """Дата истечения срока, отсчитанная от сегодняшней даты.

    Считается в core.lifetimes: по этой же дате ядро сравнивает сроки
    элементов, когда выбирает слабое звено. Своя арифметика здесь разошлась бы
    с ядром на сутки — и «одновременно истекающие» элементы перестали бы
    совпадать в отчёте и на экране.
    """
    return expiry_date(years).isoformat()


def _due_text(years):
    """Та же дата, но для фразы: «07.10.2029» — в предложении ISO читается плохо."""
    return expiry_date(years).strftime('%d.%m.%Y')


def _canvas_round_rect(canvas, x1, y1, x2, y2, radius, **kwargs):
    """Скруглённый прямоугольник на Canvas — у Tkinter нет create_round_rect."""
    radius = max(0.0, min(radius, (x2 - x1) / 2.0, (y2 - y1) / 2.0))
    points = [
        x1 + radius, y1, x2 - radius, y1,
        x2, y1, x2, y1 + radius,
        x2, y2 - radius, x2, y2,
        x2 - radius, y2, x1 + radius, y2,
        x1, y2, x1, y2 - radius,
        x1, y1 + radius, x1, y1,
    ]
    return canvas.create_polygon(points, smooth=True, splinesteps=16, **kwargs)


# Норма заменяемой запчасти, которую методика действительно учитывает. Запчасти
# с другой нормой в расчёт не попадают, поэтому и в списки на замену их
# показывать нельзя — иначе список будет врать про сроки.
PART_NORM_YEARS = 5.0
# «Скоро нужно менять»: остаток меньше года. Плюс всегда показывается
# слабое звено, даже если оно дальше года — иначе на календарной шкале
# (Алгоритм 4, где остаток измеряется годами до полной проверки) список был
# бы пустым и выглядел бы как ошибка.
SOON_HORIZON = 1.0
# Продление: ползунок задаёт нужный срок в годах от сегодня (до 20 лет — это
# предел полной проверки), и сколько шагов замен максимум считаем.
# Шагов нужно не меньше, чем учитываемых запчастей в ГРП: пока срок держит
# запчасть за запчастью, лестница на двенадцати шагах обрывалась бы на середине
# и сообщала, что продлить больше нельзя, хотя менять осталось ещё.
# Верхняя граница — чтобы очень большой ГРП не считался минутами.
EXTENSION_MAX = 20.0
EXTENSION_STEPS = 12
EXTENSION_STEPS_MAX = 60

CONSERVATIVE_SCALE = (
    'Это срок до полной проверки оборудования (норма элемента '
    f'{num(FULL_CHECK_TERM, 0)} лет), а не срок службы запчасти: поэтому '
    'здесь он и больше 5 лет.'
)

HORIZON_LEVELS = {
    'none': (GOOD, 'ничего не просрочено'),
    'some': (WARN, 'часть просрочена'),
    'all': (BAD, 'почти всё просрочено'),
}


class HorizonSlider(tk.Frame):
    """Ползунок горизонта: рисуется сам, тянется мышью, щёлкает по месяцам.

    Стандартный ttk.Scale на этой теме выглядит серой полоской без ручки и без
    делений, а деления здесь несут смысл: по ним видно, где «через год» и
    «через три». Поэтому трек, заливка, ручка и деления рисуются на Canvas.
    """

    PADDING_X = 18
    TRACK_H = 8
    HANDLE_W = 22
    HANDLE_H = 30
    TICK_H = 7
    LABEL_H = 18
    HEIGHT = 78

    def __init__(self, parent, maximum: float, snap: float, command=None):
        super().__init__(parent, bg=CARD, height=self.HEIGHT)
        self.maximum = float(maximum)
        self.snap = float(snap) or 0.01
        self._command = command
        self._value = float(maximum)
        self._level = 'none'
        self._dragging = False
        self._hover = False

        self.canvas = tk.Canvas(self, bg=CARD, height=self.HEIGHT,
                                highlightthickness=0, bd=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.bind('<Configure>', lambda _e: self.redraw())
        self.canvas.bind('<Button-1>', self._on_press)
        self.canvas.bind('<B1-Motion>', self._on_drag)
        self.canvas.bind('<ButtonRelease-1>', self._on_release)
        self.canvas.bind('<Enter>', self._on_enter)
        self.canvas.bind('<Leave>', self._on_leave)
        self.canvas.bind('<Key>', self._on_key)
        self.canvas.configure(cursor='hand2', takefocus=True)

    # ------------------------------------------------------------- значения

    def get(self) -> float:
        return self._value

    def set(self, value: float, notify: bool = False):
        """Ставит значение с привязкой к шагу; notify=True — вызвать обработчик."""
        snapped = self._clamp(self._snap(float(value)))
        changed = abs(snapped - self._value) > 1e-9
        self._value = snapped
        self.redraw()
        if notify and changed and self._command:
            self._command(snapped)

    def step(self, months: int):
        self.set(self._value + months / 12.0, notify=True)

    def set_level(self, level: str):
        """Подсветка по срочности: никого / часть / всё."""
        if level not in HORIZON_LEVELS or level == self._level:
            return
        self._level = level
        self.redraw()

    def _snap(self, value: float) -> float:
        return round(value / self.snap) * self.snap

    def _clamp(self, value: float) -> float:
        return max(0.0, min(self.maximum, value))

    # -------------------------------------------------------------- события

    def _on_press(self, event):
        self._dragging = True
        self.canvas.focus_set()
        self._apply_x(event.x)

    def _on_drag(self, event):
        if self._dragging:
            self._apply_x(event.x)

    def _on_release(self, _event):
        self._dragging = False

    def _on_enter(self, _event):
        self._hover = True
        self.redraw()

    def _on_leave(self, _event):
        self._hover = False
        self._dragging = False
        self.redraw()

    def _on_key(self, event):
        if event.keysym in ('Left', 'Down'):
            self.step(-1)
            return 'break'
        if event.keysym in ('Right', 'Up'):
            self.step(1)
            return 'break'
        if event.keysym == 'Home':
            self.set(0.0, notify=True)
            return 'break'
        if event.keysym == 'End':
            self.set(self.maximum, notify=True)
            return 'break'
        return None

    def _apply_x(self, x: int):
        self.set(self._value_from_x(x), notify=True)

    # ------------------------------------------------------------ геометрия

    def _left(self) -> float:
        return float(self.PADDING_X + self.HANDLE_W / 2.0)

    def _right(self) -> float:
        return float(self.canvas.winfo_width() - self.PADDING_X - self.HANDLE_W / 2.0)

    def _value_from_x(self, x: float) -> float:
        left, right = self._left(), self._right()
        if right <= left:
            return 0.0
        return self._clamp((x - left) / (right - left) * self.maximum)

    def _x_from_value(self, value: float) -> float:
        left, right = self._left(), self._right()
        return left + (value / self.maximum) * (right - left) if self.maximum else left

    # --------------------------------------------------------------- отрисовка

    def redraw(self):
        canvas = self.canvas
        canvas.delete('all')
        width = canvas.winfo_width()
        if width <= 1:
            return

        left, right = self._left(), self._right()
        span = max(1.0, right - left)
        track_y = 22 + self.TRACK_H / 2.0
        color, _note = HORIZON_LEVELS.get(self._level, HORIZON_LEVELS['none'])
        handle_x = self._x_from_value(self._value)

        # Дорожка: серая «рельса» + заливка пройденного.
        canvas.create_line(left, track_y, right, track_y, fill='#dde3ec',
                           width=self.TRACK_H, capstyle=tk.ROUND)
        canvas.create_line(left, track_y, handle_x, track_y, fill=color,
                           width=self.TRACK_H, capstyle=tk.ROUND)

        # Деления по годам: мелкие — по месяцам, крупные — по годам.
        months = int(round(self.maximum * 12))
        for month in range(months + 1):
            x = left + span * (month / 12.0) / self.maximum
            if month % 12 == 0:
                canvas.create_line(x, track_y + self.TRACK_H / 2 + 3,
                                   x, track_y + self.TRACK_H / 2 + 3 + self.TICK_H,
                                   fill='#8e99a8', width=2)
                label = _horizon_text(float(month // 12))
                canvas.create_text(x, track_y + self.TRACK_H / 2 + 3 + self.TICK_H
                                   + self.LABEL_H / 2 + 1, text=label,
                                   fill=SUB, font=('Segoe UI', 9))
            elif month % 3 == 0:
                canvas.create_line(x, track_y + self.TRACK_H / 2 + 4,
                                   x, track_y + self.TRACK_H / 2 + 3 + self.TICK_H - 1,
                                   fill='#cfd6de', width=1)

        # Ручка: тень, корпус, белая полоска-метка.
        height = self.HANDLE_H + (4 if self._hover or self._dragging else 0)
        top = track_y - height / 2.0
        _canvas_round_rect(canvas, handle_x - self.HANDLE_W / 2 + 1, top + 2,
                           handle_x + self.HANDLE_W / 2 + 1, top + height + 2,
                           7, fill='#c7ced8', outline='')
        _canvas_round_rect(canvas, handle_x - self.HANDLE_W / 2, top,
                           handle_x + self.HANDLE_W / 2, top + height,
                           7, fill='#ffffff', outline=color, width=2)
        canvas.create_line(handle_x, top + height / 2 - 3,
                           handle_x, top + height / 2 + 3, fill=color, width=2)


class AlgorithmsWindow:
    """Расчёт и разбор остаточного ресурса ГРП по всем алгоритмам.

    Строится либо в отдельном окне (`container` не задан), либо прямо в экране
    главного окна — так расчёт открывается из меню, как и остальные разделы.
    `on_close` вызывается кнопкой «Закрыть»: встроенному расчёту нужно не
    уничтожить себя, а вернуть главное окно на рабочий экран.
    """

    def __init__(self, parent, db, grp_id, equipment_data, grp_name=None,
                 params: AlgorithmParams = None, on_params=None,
                 container=None, on_close=None):
        self.parent = parent
        self.db = db
        self.grp_id = grp_id
        self.grp_name = grp_name or f'ГРП №{grp_id}'
        self.equipment_data = equipment_data or []
        # on_params вызывается при каждом пересчёте с новыми коэффициентами:
        # главное окно запоминает их, чтобы Word-отчёт считался с теми же
        # значениями, что показаны здесь.
        self._on_params = on_params
        self._on_close = on_close
        self.params = copy.deepcopy(params) if params else AlgorithmParams()
        self.results = {}
        self.warnings = []
        self.journal = {}
        self._closed = False

        # Таблицы рисуются темой clam: тема Windows не даёт задать им цвет.
        # Тема в интерпретаторе общая, поэтому её нужно вернуть при выходе —
        # иначе главное окно останется в чужом оформлении.
        self._theme_saved = calc_theme()

        self._toplevel = container is None
        if self._toplevel:
            self.window = tk.Toplevel(parent)
            self.window.title(f'Остаточный ресурс · {self.grp_name}')
            self.window.configure(bg=BG)
            self.window.transient(parent)
            self.window.grab_set()
            self.window.bind('<Destroy>', self._on_destroy, add='+')
        else:
            self.window = container
            try:
                self.window.configure(bg=BG)
            except tk.TclError:
                # Контейнер ttk не знает опции -bg: фон задаёт сам экран.
                pass

        self._build_ui()
        self.calculate_and_display()
        if self._toplevel:
            # Окно по содержимому: широкие таблицы требуют места, но на ноутбуке
            # 1560x900 не влезало — размер считается от запроса виджетов и экрана.
            fit_window(self.window, min_width=900, min_height=560)

    def _on_destroy(self, event=None):
        # <Destroy> прилетает и от дочерних виджетов: реакция нужна только на
        # закрытие самого окна.
        if event is not None and event.widget is not self.window:
            return
        self.close()

    def close(self):
        """Вернуть тему ttk. Для отдельного окна — закрыть его."""
        if self._closed:
            return
        self._closed = True
        restore_theme(self._theme_saved)
        if self._toplevel:
            self.window.destroy()

    def _close_requested(self):
        """Кнопка «Закрыть»: встроенный расчёт уступает место рабочему экрану."""
        if self._on_close is not None:
            self._on_close()
        elif self._toplevel:
            self.window.destroy()

    # ------------------------------------------------------------------ UI

    def _build_ui(self):
        self._build_header()
        self.notebook = ttk.Notebook(self.window, style='Calc.TNotebook')
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=14, pady=(12, 14))
        self._build_algorithm_bar()

        # Методики переключаются вертикальной лентой слева, а не вкладками
        # ноутбука: их пять, они равноправны и должны быть видны одновременно,
        # чтобы можно было сравнивать остаток не переключаясь туда-сюда.
        self.tab_algorithms = tk.Frame(self.notebook, bg=BG)
        self.notebook.add(self.tab_algorithms, text='  Алгоритмы  ')

        self.tab_horizon = tk.Frame(self.notebook, bg=BG)
        self.notebook.add(self.tab_horizon, text='  Срок замены  ')

        self.tab_coefficients = tk.Frame(self.notebook, bg=BG)
        self.notebook.add(self.tab_coefficients, text='  Коэффициенты  ')

        self.tab_inputs = tk.Frame(self.notebook, bg=BG)
        self.notebook.add(self.tab_inputs, text='  Исходные данные  ')

        self._algo_var = tk.IntVar(value=PRIMARY_ALGORITHM)
        self._build_algorithms_tab()
        self._build_horizon_tab()
        self._build_coefficients_tab()
        self._build_inputs_tab()

    def _build_header(self):
        header = tk.Frame(self.window, bg='#ffffff', highlightbackground=LINE,
                          highlightthickness=1, bd=0)
        header.pack(fill=tk.X, side=tk.TOP)

        inner = tk.Frame(header, bg='#ffffff')
        inner.pack(fill=tk.X, padx=18, pady=12)

        left = tk.Frame(inner, bg=CARD)
        left.pack(side=tk.LEFT)
        tk.Label(left, text='Остаточный ресурс ГРП', bg=CARD, fg=TEXT,
                 font=('Segoe UI', 18, 'bold')).pack(anchor=tk.W)
        self.header_sub = tk.Label(left, text=self.grp_name, bg=CARD, fg=SUB,
                                   font=F_BODY)
        self.header_sub.pack(anchor=tk.W)

        right = tk.Frame(inner, bg=CARD)
        right.pack(side=tk.RIGHT)
        _btn(right, 'Пересчитать', self.calculate_and_display,
             color='success').pack(side=tk.RIGHT, padx=(8, 0))
        _btn(right, 'Закрыть', self._close_requested, color='muted').pack(side=tk.RIGHT)

    def _algo_choices(self):
        """Подписи методик для выпадающих списков: пять штук, номера 1-5."""
        return [f'{algo_label(i)} · {ALGORITHM_TITLES[i]}' for i in range(5)]

    def _build_algorithm_bar(self):
        """Переключатель методики для детальных вкладок."""
        bar = tk.Frame(self.window, bg=BG)
        bar.pack(fill=tk.X, padx=14, pady=(10, 0))

        left = tk.Frame(bar, bg=BG)
        left.pack(side=tk.LEFT)
        tk.Label(left, text='Методика', bg=BG, fg=TEXT,
                 font=F_TABLE_B).pack(side=tk.LEFT, padx=(0, 10))
        chooser = ttk.Combobox(left, state='readonly', width=52,
                               values=self._algo_choices(),
                               font=F_BODY, style='Calc.TCombobox')
        chooser.current(PRIMARY_ALGORITHM)
        chooser.bind('<<ComboboxSelected>>', self._on_algorithm_changed)
        chooser.pack(side=tk.LEFT)
        self._combo_algo = chooser

        self.algo_hint = tk.Label(bar, text='', bg=BG, fg=TEXT, font=F_BODY)
        self.algo_hint.pack(side=tk.LEFT, padx=14)

    def _on_algorithm_changed(self, _event=None):
        self._algo_var.set(self._combo_algo.current())
        self.render_coefficients()

    # ------------------------------------------------- Вертикальные вкладки

    def _build_algorithms_tab(self):
        """Лента методик слева и панель выбранной методики справа."""
        wrap = tk.Frame(self.tab_algorithms, bg=BG)
        wrap.pack(fill=tk.BOTH, expand=True, padx=14, pady=10)

        self.algo_values, self.algo_metas, self.algo_notes = {}, {}, {}
        self.algo_trees, self.algo_recommends = {}, {}
        self.soon_trees, self.soon_counts = {}, {}
        self.ext_sliders, self.ext_trees = {}, {}
        self.ext_head, self.ext_targets, self.ext_notes = {}, {}, {}
        self.algo_panes, self.algo_tabs = [], []
        self._selected_algorithm = PRIMARY_ALGORITHM
        self._payload = []
        self._coefficients_now = {}
        self._ladders = {}
        # Сколько шагов разрешено лестнице продления: у каждой методики своё
        # число элементов, и обрыв по лимиту надо отличать от «продлить нечем».
        self._ladder_limit = {}

        # Лента методик. Плитки компактные и не переносятся: пять методик
        # должны помещаться в ленту целиком при любой высоте окна, иначе
        # последняя методика просто уезжает за нижний край и её не видно.
        rail = tk.Frame(wrap, bg=BG, width=RAIL_W)
        rail.pack(side=tk.LEFT, fill=tk.Y)
        rail.pack_propagate(False)
        for number in range(5):
            self.algo_tabs.append(self._build_vertical_tab(rail, number))

        holder = tk.Frame(wrap, bg=BG)
        holder.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(12, 0))
        for number in range(5):
            pane = Pane(holder, pady=(0, 14))
            self.algo_panes.append(pane)
            self._build_algorithm_pane(pane, number)
        self._select_algorithm(PRIMARY_ALGORITHM)

    def _build_vertical_tab(self, parent, number):
        """Плитка методики в ленте: номер, короткое имя и остаток."""
        outer = tk.Frame(parent, bg=BG)
        outer.pack(fill=tk.X, pady=(0, 5))

        active = tk.Frame(outer, bg=BG, width=4)
        active.pack(side=tk.LEFT, fill=tk.Y)

        tile = tk.Frame(outer, bg=CARD, highlightbackground=LINE,
                        highlightthickness=1, bd=0, cursor='hand2')
        tile.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(4, 0))

        top = tk.Frame(tile, bg=CARD, cursor='hand2')
        top.pack(fill=tk.X, padx=12, pady=(8, 0))
        number_label = tk.Label(top, text=algo_label(number), bg=CARD, fg=ACCENT,
                                font=('Segoe UI', 11, 'bold'), cursor='hand2')
        number_label.pack(side=tk.LEFT)
        badge = tk.Label(top, text='—', bg=CARD, fg=SUB,
                         font=F_TABLE_B, cursor='hand2')
        badge.pack(side=tk.RIGHT)

        # Короткое имя методики: длинное не помещается в плитку в одну строку,
        # а перенос съедал бы высоту, которой ленте и так не хватает.
        title = tk.Label(tile, text=ALGORITHM_SHORT[number], bg=CARD, fg=SUB,
                         font=F_BODY, anchor=tk.W, justify=tk.LEFT,
                         cursor='hand2')
        title.pack(fill=tk.X, padx=12, pady=(1, 8))

        widgets = (outer, active, tile, top, number_label, badge, title)
        for widget in widgets:
            widget.bind('<Button-1>',
                        lambda _e, n=number: self._select_algorithm(n))
            widget.bind('<Enter>', lambda _e, n=number: self._hover_tab(n, True))
            widget.bind('<Leave>', lambda _e, n=number: self._hover_tab(n, False))
        return {'outer': outer, 'active': active, 'card': tile, 'head': top,
                'number': number_label, 'badge': badge, 'title': title}

    def _hover_tab(self, number, active):
        """Подсветка плитки под курсором, если она не выбрана."""
        if number == self._selected_algorithm:
            return
        self.algo_tabs[number]['card'].config(bg='#eaf0fd' if active else CARD)

    def _select_algorithm(self, number):
        """Показывает панель методики и перекрашивает ленту."""
        self._selected_algorithm = number
        self._algo_var.set(number)
        for pane in self.algo_panes:
            pane.pack_forget()
        self.algo_panes[number].pack(fill=tk.BOTH, expand=True)
        self.algo_panes[number].to_top()
        self._paint_algo_tabs()
        if self.results:
            self._render_extension(number)

    def _paint_algo_tabs(self):
        """Активная методика — белой плиткой с полосой, остальные приглушены."""
        for number, tab in enumerate(self.algo_tabs):
            selected = number == self._selected_algorithm
            tile, active = tab['card'], tab['active']
            bg = CARD if selected else '#f1f4f9'
            tile.config(bg=bg,
                        highlightbackground=ACCENT if selected else LINE)
            active.config(bg=ACCENT if selected else BG)
            tab['head'].config(bg=bg)
            tab['badge'].config(bg=bg)
            tab['number'].config(
                bg=bg,
                fg=ACCENT if selected else SUB,
                font=('Segoe UI', 11, 'bold') if selected else ('Segoe UI', 11))
            tab['title'].config(bg=bg, fg=TEXT if selected else SUB)

    def _build_algorithm_pane(self, tab, number):
        """Панель одной методики: остаток, список замен и продление срока."""
        body = tab.body

        top = card(body)
        top.pack(fill=tk.X)
        head_row(top).pack_forget()
        caption = tk.Frame(top, bg=CARD)
        caption.pack(fill=tk.X, padx=18, pady=(12, 0))
        card_title(caption, f'{algo_label(number)} · {ALGORITHM_TITLES[number]}').pack(
            side=tk.LEFT)

        row = tk.Frame(top, bg=CARD)
        row.pack(fill=tk.X, padx=18, pady=(4, 14))
        self.algo_values[number] = tk.Label(row, text='—', bg=CARD, fg=TEXT,
                                           font=F_HERO)
        self.algo_values[number].pack(side=tk.LEFT, anchor=tk.W)
        info = tk.Frame(row, bg=CARD)
        info.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(26, 0),
                  anchor=tk.W)
        self.algo_metas[number] = tk.Label(info, text='', bg=CARD, fg=TEXT,
                                          font=F_TABLE_B, justify=tk.LEFT,
                                          anchor=tk.W)
        self.algo_metas[number].pack(anchor=tk.W)
        self.algo_notes[number] = tk.Label(info, text='', bg=CARD, fg=SUB,
                                          font=F_BODY, justify=tk.LEFT,
                                          anchor=tk.W)
        self.algo_notes[number].pack(anchor=tk.W, pady=(6, 0))

        self._build_soon_card(body, number)
        self._build_extension_card(body, number)
        self._build_elements_card(body, number)

    # ------------------------------------------------- Скоро нужно менять

    def _build_soon_card(self, parent, number):
        """Список того, что скоро придётся менять, с запчастями внутри строки."""
        box = card(parent)
        box.pack(fill=tk.X, pady=(12, 0))
        head = head_row(box)
        card_title(head, 'Скоро нужно менять').pack(side=tk.LEFT)
        self.soon_counts[number] = tk.Label(head, text='', bg=CARD, fg=SUB,
                                            font=F_TABLE_B)
        self.soon_counts[number].pack(side=tk.RIGHT)

        self.soon_trees[number] = _tree_hier(
            box,
            columns=('Категория', 'Норма', 'Возраст', 'Осталось', 'Истекает'),
            widths={'Категория': 150, 'Норма': 85, 'Возраст': 95, 'Осталось': 115,
                    'Истекает': 110},
            height=5,
        )
        for tag, color in (('soon', TINT_WARN), ('over', TINT_BAD),
                           ('part', TINT_PART)):
            self.soon_trees[number].tag_configure(tag, background=color)

    def _render_soon_card(self, number):
        """Заполняет список замен: строка — элемент, вложенные — его запчасти."""
        tree = self.soon_trees[number]
        tree.delete(*tree.get_children())
        result = self.results.get(number)
        if result is None or result.error:
            self.soon_counts[number].config(text='', fg=SUB)
            fit_table(tree, 0)
            return

        used = result.used_elements
        if not used:
            self.soon_counts[number].config(text='нет элементов в расчёте', fg=BAD)
            fit_table(tree, 0)
            return
        # В списке — всё, что истекает в пределах горизонта, и слабое звено
        # целиком (минимум со всем, что совпало с ним по дате): на календарной
        # методике ресурс измеряется годами до полной проверки, и без минимума
        # список был бы пустым и выглядел бы как ошибка расчёта.
        weak = weak_link_elements(used)
        due = [e for e in used if e.z_element <= SOON_HORIZON or e in weak]

        rows = 0
        for element in sorted(due, key=lambda e: (e.z_element, e.name)):
            tag = 'over' if element.z_element <= 0 else 'soon'
            parent = tree.insert('', tk.END, open=True, tags=(tag,), text=(
                element.name[:80]), values=(
                critical_title(element.critical_key) if element.critical_key else '—',
                years_to_text(element.norm),
                years_to_text(element.age),
                years_to_text(element.z_element),
                _due_date(element.z_element),
            ))
            rows += 1
            # Внутри строки — только та запчасть, которая держит ресурс
            # элемента: остальные истекают позже и срока не двигают.
            parts = _pick_parts(element)
            if not parts:
                tree.insert(parent, tk.END, tags=('part',),
                            text='нет запчастей с нормой 5 лет в расчёте',
                            values=('', '—', '—', '—', ''))
                rows += 1
                continue
            for detail in parts:
                left = _part_residual(detail)
                tree.insert(parent, tk.END, tags=('part',), text=(
                    f'    {detail.get("name", "запчасть")}'), values=(
                    'запчасть', years_to_text(detail.get('norm')),
                    years_to_text(detail.get('age')), years_to_text(left),
                    _due_date(left),
                ))
                rows += 1

        self.soon_counts[number].config(
            text=f'{len(due)} из {len(used)} элементов', fg=BAD if due else GOOD)
        fit_table(tree, rows)

    # ------------------------------------------------------------ Продление

    def _build_extension_card(self, parent, number):
        """Ползунок цели продления и список того, что придётся заменить."""
        box = card(parent)
        box.pack(fill=tk.X, pady=(12, 0))

        head = head_row(box)
        card_title(head, 'Продление срока').pack(side=tk.LEFT)
        self.ext_head[number] = tk.Label(head, text='', bg=CARD, fg=SUB,
                                         font=F_BODY, justify=tk.LEFT)
        self.ext_head[number].pack(side=tk.LEFT, padx=14)

        self.ext_targets[number] = tk.Label(box, text='', bg=CARD, fg=TEXT,
                                            font=('Segoe UI', 13, 'bold'),
                                            justify=tk.LEFT, anchor=tk.W)
        self.ext_targets[number].pack(fill=tk.X, padx=18, pady=(6, 0))
        self.ext_notes[number] = tk.Label(box, text='', bg=CARD, fg=SUB,
                                          font=F_BODY, justify=tk.LEFT,
                                          anchor=tk.W)
        self.ext_notes[number].pack(fill=tk.X, padx=18, pady=(2, 0))

        self.ext_trees[number] = _tree_hier(
            box,
            columns=('Категория', 'Запчасть', 'Срок сейчас',
                     'Срок после замены', 'Прирост'),
            widths={'Категория': 130, 'Запчасть': 330, 'Срок сейчас': 130,
                    'Срок после замены': 150, 'Прирост': 115},
            height=3,
        )
        for tag, color in (('step', TINT_PART), ('last', TINT_GOOD),
                           ('stuck', TINT_WARN)):
            self.ext_trees[number].tag_configure(tag, background=color)

        slider_row = tk.Frame(box, bg=CARD)
        slider_row.pack(fill=tk.X, padx=18, pady=(10, 14))
        caption = tk.Frame(slider_row, bg=CARD)
        caption.pack(fill=tk.X, pady=(0, 2))
        tk.Label(caption, text='Хочу продлить', bg=CARD, fg=TEXT,
                 font=F_TABLE_B).pack(side=tk.LEFT)
        tk.Label(caption, text='— сколько лет должно остаться от сегодня',
                 bg=CARD, fg=SUB, font=F_BODY).pack(side=tk.LEFT, padx=(6, 0))
        self.ext_sliders[number] = HorizonSlider(
            slider_row, EXTENSION_MAX, HORIZON_SNAP,
            command=lambda _value, n=number: self._render_extension(n))
        self.ext_sliders[number].pack(fill=tk.X, expand=True)
        self.ext_sliders[number].set(0.0)

    def _simulate(self, number, renewed):
        """Пересчёт методики с условно заменёнными запчастями.

        renewed — пары (equipment_id, name): меняется названная запчасть, а не
        весь узел.
        """
        return simulate_with_renewed(number, self._payload, self.params,
                                     self._coefficients_now, renewed)

    def _extension_ladder(self, number):
        """Лестница: какая замена запчастей что даёт, шаг за шагом.

        Считается один раз на методику и кэшируется, иначе на каждое движение
        ползунка пришлось бы гонять пересчёт заново.
        """
        if number in self._ladders:
            return self._ladders[number]
        limit = extension_step_limit(self._payload)
        self._ladder_limit[number] = limit
        steps = build_extension_ladder(number, self._payload, self.params,
                                       self._coefficients_now,
                                       self.results.get(number), limit)
        self._ladders[number] = steps
        return steps

    def _render_extension(self, number):
        """Показывает шаги до цели ползунка и итог продления."""
        target = float(self.ext_sliders[number].get())
        tree = self.ext_trees[number]
        tree.delete(*tree.get_children())
        result = self.results.get(number)
        steps = self._extension_ladder(number)
        head, hint = self.ext_head[number], self.ext_notes[number]

        if result is None or result.error:
            head.config(text='')
            hint.config(text='', fg=SUB)
            self.ext_targets[number].config(text='', fg=TEXT)
            fit_table(tree, 0)
            return

        if not steps:
            head.config(text='')
            self.ext_targets[number].config(
                text='продлить нечем: в расчёт не вошёл ни один элемент', fg=BAD)
            hint.config(text='', fg=SUB)
            fit_table(tree, 0)
            return

        first = steps[0]
        if first.get('parts_ineffective'):
            if first.get('no_parts'):
                head.config(text=f'в расчёте нет запчастей с нормой '
                                 f'{num(PART_NORM_YEARS, 0)} лет — менять по '
                                 f'этой методике нечего')
            elif first.get('weak_without_parts'):
                head.config(text=f'срок держит «{first["element"].name[:40]}»: '
                                 f'заменяемых запчастей с нормой '
                                 f'{num(PART_NORM_YEARS, 0)} лет у него нет — '
                                 f'менять нечего')
            else:
                head.config(text='замена запчастей срок не двигает — его держит '
                                 'назначенный срок службы, а не износ запчастей')
        elif first['gain'] > 0:
            head.config(text=_step_head_text(first))
        else:
            reach = max(step['after'] for step in steps) - result.result
            if reach > 1e-9:
                head.config(text=f'слабых звеньев сразу несколько: меняем '
                                 f'запчасти по условию, всего '
                                 f'+{years_to_text(reach)}')
            else:
                head.config(text='замена запчастей срок не двигает — его держит '
                                 'назначенный срок службы, а не износ запчастей')

        # Ползунок задаёт нужный срок от сегодняшнего дня, а не прибавку к
        # текущему: «продлить на 3 года» — чтобы от сегодня оставалось 3 года.
        goal = target
        needed, reach = [], result.result
        for step in steps:
            if reach >= goal - 1e-9:
                break
            needed.append(step)
            reach = step['after']

        for index, step in enumerate(needed, 1):
            last = index == len(needed)
            tree.insert('', tk.END, text=f'{index}. {step["element"].name[:64]}',
                        tags=('stuck' if step['stuck']
                              else 'last' if last and reach >= goal - 1e-9
                              else 'step',),
                        values=(
                            critical_title(step['element'].critical_key)
                            if step['element'].critical_key else '—',
                            _parts_text(step['parts']),
                            years_to_text(step['before']),
                            years_to_text(step['after']),
                            f'+{years_to_text(step["gain"])}',
                        ))

        if target <= 0:
            self.ext_targets[number].config(
                text=f'Сейчас срок {years_to_text(result.result)} — сдвиньте '
                     f'ползунок, чтобы увидеть, что менять', fg=SUB)
            hint.config(text='Продление считается заменой запчастей слабого звена: '
                             'сначала самые изношенные, по одной за раз, пока не '
                             'наберётся срок.', fg=SUB)
            fit_table(tree, len(needed))
            return

        if result.result >= goal - 1e-9:
            # Срок и так больше заданного: продлевать нечего, замен не будет.
            self.ext_targets[number].config(
                text=f'Нужно {years_to_text(target)} от сегодня — срок уже '
                     f'{years_to_text(result.result)}: замен не нужно', fg=GOOD)
            hint.config(text=f'К {_due_text(goal)} срок ещё не истекает: '
                             f'ближайшая замена — '
                             f'{years_to_text(result.result)} от сегодня.', fg=SUB)
        elif reach >= goal - 1e-9:
            self.ext_targets[number].config(
                text=f'Нужно {years_to_text(target)} от сегодня '
                     f'(до {_due_text(goal)}): замен {len(needed)}', fg=GOOD)
            hint.config(text=f'Сейчас срок {years_to_text(result.result)}, '
                             f'после этих замен — {years_to_text(reach)}.', fg=SUB)
        else:
            gained = max(0.0, reach - result.result)
            self.ext_targets[number].config(
                text=f'Нужно {years_to_text(target)} от сегодня, но замены '
                     f'дают максимум {years_to_text(reach)} '
                     f'(+{years_to_text(gained)})', fg=WARN)
            # Собственного срока у оборудования нет, поэтому «менять
            # оборудование целиком» здесь предлагать нечего: предел задают
            # запчасти и срок полной проверки.
            limit = self._ladder_limit.get(number) or 0
            # Обрыв по лимиту — это когда шагов набралось ровно столько,
            # сколько разрешено, и последний из них ещё двигал срок. Шаг без
            # прироста означает, что лестница остановилась сама: заменять
            # больше нечего.
            capped = limit and len(steps) >= limit and not steps[-1].get('stuck')
            if steps[0].get('parts_ineffective'):
                if steps[0].get('no_parts'):
                    hint.config(
                        text=f'В расчёте нет заменяемых запчастей с нормой '
                             f'{num(PART_NORM_YEARS, 0)} лет — срок считается по '
                             f'оборудованию. Заведите запчасти во вкладке '
                             f'«Запчасти»: тогда продление будет считаться по '
                             f'ним.', fg=SUB)
                elif steps[0].get('weak_without_parts'):
                    hint.config(
                        text=f'Срок держит «{steps[0]["element"].name[:40]}»: '
                             f'заменяемых запчастей с нормой '
                             f'{num(PART_NORM_YEARS, 0)} лет у него нет, поэтому '
                             f'замена запчастей срок не поднимает. Дальше срок '
                             f'назначается диагностированием: T диагн. = '
                             f'{years_to_text(result.next_diagnosis)}.', fg=SUB)
                else:
                    hint.config(
                        text=f'Замена запчастей срок не двигает: он упирается в '
                             f'назначенный срок службы, а не в износ запчастей. '
                             f'Дальше срок назначается диагностированием: '
                             f'T диагн. = {years_to_text(result.next_diagnosis)}.',
                        fg=SUB)
            elif capped:
                # Лестницу оборвал не расчёт, а её собственный предел: замен
                # потребовалось больше, чем помещается в список.
                hint.config(
                    text=f'Показаны первые {len(steps)} замен — дальше список '
                         f'не считаем. Изношенных запчастей больше, и каждая '
                         f'следующая добавляет всё меньше.', fg=SUB)
            else:
                hint.config(
                    text=f'Больше продлить нельзя: слабыми оказались все '
                         f'элементы, последняя замена выводит срок на '
                         f'{years_to_text(reach)}. Дальше срок упирается не в '
                         f'износ элементов, а в назначенные сроки службы — '
                         f'замены запчастей его не поднимают.', fg=SUB)
        fit_table(tree, len(needed))

    # ----------------------------------------------- Элементы и коэффициенты

    def _build_elements_card(self, parent, number):
        """Разбор расчёта по элементам: база, коэффициенты, остаток."""
        box = card(parent)
        box.pack(fill=tk.X, pady=(12, 0))
        head_row(box).pack_forget()
        card_title(box, 'Как посчитано: элементы и коэффициенты').pack(
            anchor=tk.W, padx=18, pady=(12, 4))
        self.algo_trees[number] = table(
            box,
            columns=('Элемент', 'Категория', 'Норма', 'Возраст', 'Z база',
                     'K сост', 'K эксл', 'K рем', 'k повр', 'Осталось'),
            widths={'Элемент': 300, 'Категория': 135, 'Норма': 90, 'Возраст': 100,
                    'Z база': 90, 'K сост': 85, 'K эксл': 85, 'K рем': 85,
                    'k повр': 85, 'Осталось': 135},
            height=5,
            expand=False,
        )
        for tag, color in (('good', TINT_GOOD), ('warn', TINT_WARN),
                           ('bad', TINT_BAD), ('skip', TINT_SKIP)):
            self.algo_trees[number].tag_configure(tag, background=color)
        self.algo_recommends[number] = tk.Label(
            box, text='', bg=CARD, fg=ACCENT, font=('Segoe UI', 11, 'bold'),
justify=tk.LEFT, wraplength=1400)
        self.algo_recommends[number].pack(anchor=tk.W, padx=18, pady=(10, 14))

    def _render_algorithm_pane(self, number):
        """Заполняет панель методики по свежему результату расчёта."""
        result = self.results.get(number)
        value_label = self.algo_values[number]
        meta_label = self.algo_metas[number]
        note_label = self.algo_notes[number]
        tree = self.algo_trees[number]
        recommend = self.algo_recommends[number]

        tree.delete(*tree.get_children())
        badge = self.algo_tabs[number]['badge']

        if result is None:
            value_label.config(text='—', fg=BAD)
            meta_label.config(text='методика не рассчитана')
            note_label.config(text='')
            recommend.config(text='')
            badge.config(text='—', fg=SUB)
            fit_table(tree, 0)
            self._render_soon_card(number)
            return

        if result.error:
            value_label.config(text='—', fg=BAD)
            meta_label.config(text=result.error)
            note_label.config(text='')
            recommend.config(text='')
            badge.config(text='ошибка', fg=BAD)
            fit_table(tree, 0)
            self._render_soon_card(number)
            return

        value_label.config(text=years_to_text(result.result),
                           fg=self._color(result.result))
        meta_label.config(text=f'{self._rating(result.result)}\n'
                               f'T диагн. = {years_to_text(result.next_diagnosis)}\n'
                               f'элементов в расчёте: {len(result.used_elements)} '
                               f'из {len(result.elements)}')
        badge.config(text=years_to_text(result.result),
                     fg=self._color(result.result))

        skipped = [e for e in result.elements if not e.used]
        note = ''
        if number in (3, 4):
            note = CONSERVATIVE_NOTE + '  '
        note += (CONSERVATIVE_SCALE if number == 4 else '')
        if skipped:
            note += (f'не вошло в расчёт: {len(skipped)} '
                     f'({skipped[0].skip_reason})')
        note_label.config(text=note)

        for element in sorted(result.elements,
                              key=lambda e: (not e.used, e.z_element)):
            tag = ('skip' if not element.used
                   else 'bad' if element.z_element <= 0
                   else 'warn' if element.z_element < 1.0 else 'good')
            tree.insert('', tk.END, tags=(tag,), values=(
                element.name[:70],
                critical_short_title(element.critical_key) if element.critical_key else '—',
                years_to_text(element.norm),
                years_to_text(element.age),
                num(element.z_base, 2),
                num(element.k_state, 3),
                num(element.k_cond, 3),
                num(element.k_repair, 3),
                num(element.k_fail, 3),
                '—' if not element.used else years_to_text(element.z_element),
            ))
        recommend.config(text=result.recommendation or '')

        self._render_soon_card(number)
        self._render_extension(number)

    # ------------------------------------------------------- Срок замены

    def _build_horizon_tab(self):
        """Ползунок горизонта 0-5 лет и список того, что к нему истекает.

        Вкладка прокручивается целиком: на невысоком окне ползунок, подпись и
        таблица вместе выше экрана, и без прокрутки низ списка было не достать.
        """
        pane = Pane(self.tab_horizon)
        pane.pack(fill=tk.BOTH, expand=True)
        wrap = pane.body

        top = card(wrap)
        top.pack(fill=tk.X)

        head = head_row(top, padx=18)
        card_title(head, 'Что нужно заменить').pack(side=tk.LEFT)
        chooser = ttk.Combobox(head, state='readonly', width=48,
                               values=self._algo_choices(),
                               font=F_BODY, style='Calc.TCombobox')
        chooser.current(PRIMARY_ALGORITHM)
        chooser.bind('<<ComboboxSelected>>', self._on_horizon_algorithm)
        chooser.pack(side=tk.RIGHT)
        self._combo_horizon_algo = chooser

        slider_row = tk.Frame(top, bg=CARD)
        slider_row.pack(fill=tk.X, padx=18, pady=(10, 0))
        self.horizon_slider = HorizonSlider(slider_row, HORIZON_MAX,
                                            HORIZON_SNAP,
                                            command=self._on_horizon_changed)
        self.horizon_slider.pack(fill=tk.X, expand=True)

        readout = tk.Frame(top, bg=CARD)
        readout.pack(fill=tk.X, padx=18, pady=(2, 14))
        self.horizon_label = tk.Label(readout, text='', bg=CARD, fg=TEXT,
                                      font=('Segoe UI', 16, 'bold'))
        self.horizon_label.pack(side=tk.LEFT)
        self.horizon_count = tk.Label(readout, text='', bg=CARD, fg=TEXT,
                                      font=F_BODY, justify=tk.LEFT, anchor=tk.W)
        self.horizon_count.pack(side=tk.LEFT, padx=(20, 0))

        box = card(wrap)
        box.pack(fill=tk.X, pady=(12, 0))
        self.tree_horizon = table(
            box,
            columns=('Элемент', 'Тип', 'Запчасть', 'Норма запчасти', 'Возраст запчасти',
                     'Осталось запчасти', 'Осталось элемента'),
            widths={'Элемент': 290, 'Тип': 110, 'Запчасть': 300, 'Норма запчасти': 105,
                    'Возраст запчасти': 115, 'Осталось запчасти': 125,
                    'Осталось элемента': 140},
            height=12,
        )
        for tag, color in (('warn', TINT_WARN), ('bad', TINT_BAD)):
            self.tree_horizon.tag_configure(tag, background=color)

    def _on_horizon_algorithm(self, _event=None):
        index = self._combo_horizon_algo.current()
        if index < 0:
            return
        self._algo_var.set(index)
        self._combo_algo.current(index)
        self.render_horizon()

    def _on_horizon_changed(self, _value=None):
        self.render_horizon()

    def _horizon_number(self) -> int:
        index = self._combo_horizon_algo.current()
        return index if index >= 0 else PRIMARY_ALGORITHM

    def render_horizon(self):
        """Перерисовывает список замен под текущий горизонт и методику."""
        number = self._horizon_number()
        horizon = float(self.horizon_slider.get())
        result = self.results.get(number)
        tree = self.tree_horizon
        tree.delete(*tree.get_children())

        self.horizon_label.config(
            text=f'Горизонт {_horizon_text(horizon)}',
            fg=self._color(horizon) if horizon < 1.0 else TEXT)

        if result is None or result.error:
            self.horizon_count.config(
                text=result.error if result else 'методика не рассчитана', fg=BAD)
            self.horizon_slider.set_level('none')
            fit_table(tree, 0)
            return

        due, later = [], []
        for element in result.used_elements:
            part = driving_part(element)
            part_z = _part_residual(part)
            row = (
                element.name[:70],
                critical_title(element.critical_key) if element.critical_key else '—',
                (part.get('name') if part else '—'),
                years_to_text(part.get('norm')) if part else '—',
                years_to_text(part.get('age')) if part else '—',
                years_to_text(part_z) if part_z is not None else '—',
                years_to_text(element.z_element),
            )
            (due if element.z_element <= horizon else later).append(
                (element, part, part_z, row))

        due.sort(key=lambda item: (item[0].z_element, item[0].name))
        later.sort(key=lambda item: (item[0].z_element, item[0].name))
        # В таблице — только то, что истекает в пределах горизонта: элемент,
        # чей срок дальше, к намеченной дате менять не нужно, и в списке замен
        # он только мешает. Сколько таких осталось, сказано в подписи ниже.
        for element, _part, _z, row in due:
            tag = 'bad' if element.z_element <= 0 else 'warn'
            tree.insert('', tk.END, tags=(tag,), values=row)

        total = len(result.used_elements)
        if not due:
            self.horizon_slider.set_level('none')
            text = (f'к {_horizon_text(horizon)} не истекает ни один элемент: '
                    f'ближайший — '
                    f'{years_to_text(later[0][0].z_element) if later else "—"}')
            color = GOOD
        elif len(due) >= total:
            self.horizon_slider.set_level('all')
            text = (f'к {_horizon_text(horizon)} просрочено всё: {len(due)} из '
                    f'{total} элементов ({len({e.equipment_id for e, _, _, _ in due})}'
                    f' ед. оборудования)')
            color = BAD
        else:
            self.horizon_slider.set_level('some')
            text = (f'к {_horizon_text(horizon)} истекает: {len(due)} из {total} '
                    f'элементов ({len({e.equipment_id for e, _, _, _ in due})}'
                    f' ед. оборудования); остальные {len(later)} — позже')
            color = WARN
        self.horizon_count.config(text=text, fg=color)
        # Высота таблицы по числу строк: вкладка прокручивается целиком, и
        # длинный список должен быть доступен по прокрутке страницы.
        fit_table(tree, len(due), minimum=4, cap=24)

    # -------------------------------------------------------- Коэффициенты

    def _build_coefficients_tab(self):
        """Коэффициенты: редактируемые веса и как они превратились в K_..

        Вкладка прокручивается целиком: полей стало больше (веса, ручные K,
        кнопка и таблица по элементам), и на невысоком окне низ не помещался.
        """
        pane = Pane(self.tab_coefficients)
        pane.pack(fill=tk.BOTH, expand=True)
        wrap = pane.body

        editor = card(wrap)
        editor.pack(fill=tk.X, pady=(0, 12))
        self._build_params_panel(editor)

        box = card(wrap)
        box.pack(fill=tk.X)
        head = head_row(box, padx=18)
        card_title(head, 'Как получились коэффициенты по каждому элементу').pack(
            side=tk.LEFT)
        self._coeff_note = note(
            box, 'K сост, K эксл, K рем и k повр — поправки, на которые '
                 'умножается базовый ресурс. Где данных нет, коэффициент равен 1 '
                 'и ресурс не снижается.', padx=18, pady=(2, 6), fill=tk.X)

        self.tree_coefficients = table(
            box,
            columns=('Элемент', 'Категория', 'Норма, лет', 'Возраст, лет', 'База Z',
                     'Вариант базы', 'K сост', 'K эксл', 'K рем', 'k повр',
                     'Ресурс Z', 'Расчёт (формула)'),
            widths={'Элемент': 235, 'Категория': 140, 'Норма, лет': 82,
                    'Возраст, лет': 90, 'База Z': 78, 'Вариант базы': 68,
                    'K сост': 76, 'K эксл': 74, 'K рем': 70, 'k повр': 74,
                    'Ресурс Z': 82, 'Расчёт (формула)': 300},
            height=13,
        )
        self.tree_coefficients.tag_configure('weak', background=TINT_BAD)
        self.tree_coefficients.tag_configure('skip', background=TINT_SKIP,
                                             foreground=SUB)
        self.tree_coefficients.tag_configure('zero', background=TINT_WARN)
        self.tree_coefficients.tag_configure('manual', background=TINT_MANUAL)

    # ------------------------------------------------------- Исходные данные

    def _build_inputs_tab(self):
        wrap = tk.Frame(self.tab_inputs, bg=BG)
        wrap.pack(fill=tk.BOTH, expand=True, padx=14, pady=10)

        journal_card = card(wrap)
        journal_card.pack(fill=tk.X, pady=(0, 12))
        self._build_journal_panel(journal_card)

        box = card(wrap)
        box.pack(fill=tk.BOTH, expand=True)
        card_title(box, 'Что поступило в расчёт по каждому элементу').pack(
            anchor=tk.W, padx=18, pady=(12, 4))
        self.tree_inputs = table(
            box,
            columns=('Элемент', 'Категория', 'S_нач', 'Источник', 'Запчасти',
                     'Z_база', 'Отказы', 'Повреж.', 'Ремонт', 'В расчёте'),
            widths={'Элемент': 230, 'Категория': 165, 'S_нач': 85, 'Источник': 170,
                    'Запчасти': 70, 'Z_база': 80, 'Отказы': 65, 'Повреж.': 75,
                    'Ремонт': 140, 'В расчёте': 200},
            height=9,
        )
        self.tree_inputs.tag_configure('skip', background=TINT_SKIP,
                                       foreground=SUB)
        self.tree_inputs.tag_configure('weak', background=TINT_BAD)

    def _build_params_panel(self, parent):
        """Редактор весов методики и ручных поправок K."""
        head = head_row(parent, padx=18)
        card_title(head, 'Коэффициенты методики').pack(side=tk.LEFT)
        _btn(head, 'Вернуть методические', self._reset_params,
             color='muted').pack(side=tk.RIGHT)

        body = tk.Frame(parent, bg=CARD)
        body.pack(fill=tk.X, padx=18, pady=(8, 16))

        note(body, 'Веса управляют поправками K сост, K эксл, K рем и k повр: '
                   'изменение пересчитывает все методики сразу. Все '
                   'коэффициенты принимаются от 0 до 1.',
             fill=tk.X, pady=(0, 10))

        self._param_entries = {}
        self._param_specs = {}

        grid = self._param_grid(body)
        for row, (attr, label, digits, purpose, lo, hi) in enumerate(WEIGHT_FIELDS):
            self._add_param_cell(grid, row, attr, label, digits, purpose, lo, hi,
                                 getattr(self.params, attr), manual=False)

        note(body, 'Ручные поправки K (0…1). Пустое поле — коэффициент считается '
                   'по формуле методики; заполненное — берётся введённое '
                   'значение, и в расчёте оно помечается «задано вручную».',
             fill=tk.X, pady=(12, 6))

        manual_grid = self._param_grid(body)
        for row, (attr, label, purpose) in enumerate(MANUAL_FIELDS):
            self._add_param_cell(manual_grid, row, attr, label, 3, purpose,
                                 0.0, 1.0, getattr(self.params, attr),
                                 manual=True)

        self._params_message = tk.Label(body, text='', bg=CARD, fg=BAD,
                                        font=F_BODY, anchor=tk.W,
                                        justify=tk.LEFT)
        self._params_message.pack(fill=tk.X, pady=(10, 0))

        actions = tk.Frame(body, bg=CARD)
        actions.pack(fill=tk.X, pady=(8, 0))
        _btn(actions, 'Пересчитать с этими коэффициентами',
             self._apply_params, color='success').pack(side=tk.LEFT)

    @staticmethod
    def _param_grid(parent):
        """Сетка полей в две колонки — общая для весов и ручных поправок."""
        grid = tk.Frame(parent, bg=CARD)
        grid.pack(fill=tk.X)
        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(1, weight=1)
        return grid

    def _add_param_cell(self, grid, row, attr, label, digits, purpose, lo, hi,
                        value, manual):
        """Одно поле коэффициента: подпись, ввод, диапазон, назначение."""
        column = row % 2
        cell = tk.Frame(grid, bg=CARD)
        cell.grid(row=row // 2, column=column, sticky='ew',
                  padx=(0, 20) if column == 0 else (20, 0), pady=5)
        top = tk.Frame(cell, bg=CARD)
        top.pack(fill=tk.X)
        tk.Label(top, text=label, bg=CARD, fg=TEXT, font=F_TABLE_B,
                 width=16, anchor=tk.W).pack(side=tk.LEFT)
        entry = ttk.Entry(top, width=8, font=('Consolas', 11),
                          style='Calc.TEntry', justify=tk.RIGHT)
        initial = _manual_text(value) if manual else (
            num(value, digits) if value is not None else '')
        entry.insert(tk.END, initial)
        entry.pack(side=tk.LEFT, padx=(8, 0))
        tk.Label(top, text=_range_text(lo, hi), bg=CARD, fg=SUB,
                 font=F_BODY).pack(side=tk.LEFT, padx=(8, 0))
        tk.Label(cell, text=purpose, bg=CARD, fg=SUB, font=F_BODY,
                 anchor=tk.W).pack(fill=tk.X, pady=(2, 0))
        self._param_entries[attr] = entry
        self._param_specs[attr] = {'label': label, 'digits': digits, 'lo': lo,
                                   'hi': hi, 'manual': manual}

    def _build_journal_panel(self, parent):
        head = head_row(parent, padx=18)
        card_title(head, 'Журнал технической диагностики (A, B, C → K общ)').pack(
            side=tk.LEFT)

        body = tk.Frame(parent, bg=CARD)
        body.pack(fill=tk.X, padx=18, pady=(10, 16))
        self._journal_text = tk.Label(body, text='—', bg=CARD, fg=TEXT,
                                      font=F_BODY, justify=tk.LEFT,
                                      anchor=tk.W)
        self._journal_text.pack(fill=tk.X)

    def _read_params(self):
        """Читает коэффициенты из полей. Возвращает (params, ошибки, поля).

        В основу берётся текущий self.params, а не новый экземпляр: так
        незаполненное поле ручной поправки возвращает формулу методики, не
        сбрасывая остальные значения. Значение вне 0…1 не принимается —
        возвращается текст ошибки и само поле, чтобы его подсветить.
        """
        base = copy.deepcopy(self.params)
        errors, bad = [], []
        for attr, spec in self._param_specs.items():
            entry = self._param_entries[attr]
            value, error = parse_coefficient(entry.get(), spec['label'],
                                             spec['lo'], spec['hi'],
                                             allow_empty=spec['manual'])
            if error:
                errors.append(error)
                bad.append(entry)
                continue
            if value is None:
                if spec['manual']:
                    setattr(base, attr, None)
                continue
            setattr(base, attr, value)
        return base, errors, bad

    def _mark_bad_params(self, bad):
        """Подсвечивает поля с ошибкой и снимает подсветку с остальных."""
        for entry in self._param_entries.values():
            entry.configure(style='CalcBad.TEntry' if entry in bad
                            else 'Calc.TEntry')

    def _apply_params(self):
        params, errors, bad = self._read_params()
        if errors:
            # Пока в поле что-то неверное, расчёт не трогаем: иначе на экране
            # осталось бы старое число без объяснения, почему оно не изменилось.
            self._mark_bad_params(bad)
            self._params_message.config(
                text='Не принято — ' + '; '.join(errors) + '. Расчёт не изменён.')
            return
        self._mark_bad_params([])
        self._params_message.config(text='')
        self.params = params
        self.calculate_and_display()

    def _reset_params(self):
        self.params = AlgorithmParams()
        for attr, entry in self._param_entries.items():
            spec = self._param_specs[attr]
            value = getattr(self.params, attr)
            text = (_manual_text(value) if spec['manual']
                    else num(value, spec['digits']) if value is not None else '')
            entry.delete(0, tk.END)
            entry.insert(tk.END, text)
        self._mark_bad_params([])
        self._params_message.config(text='')
        self.calculate_and_display()

    # ------------------------------------------------------------- Расчёт

    def calculate_and_display(self):
        """Собирает данные из БД, считает все алгоритмы и обновляет вкладки."""
        try:
            coefficients = self._coefficients()
            payload, self.warnings, self.journal = self._collect_input(coefficients)
            self.results = calculate_all_algorithms(
                payload,
                params=self.params,
                coefficients=coefficients,
            )
            self._payload = payload
            self._coefficients_now = coefficients
            self._ladders, self._ladder_limit = {}, {}
        except Exception as exc:  # noqa: BLE001 — окно не должно падать
            messagebox.showerror('Ошибка расчёта', f'Не удалось выполнить расчёт:\n{exc}')
            return

        if self._on_params is not None:
            self._on_params(copy.deepcopy(self.params))

        self._audit_results()
        for number in range(5):
            self._render_algorithm_pane(number)
        self.render_horizon()
        self.render_coefficients()
        self._render_inputs()
        self._render_journal_card(coefficients)
        self._update_header()

    def _row_to_dict(self, row):
        """Кортеж БД → словарь элемента."""
        row = list(row) + [None] * 4
        return {
            'name': row[1] or '',
            'equipment_id': row[0],
            'install_date': row[2],
            'removal_date': row[3],
        }

    def _collect_input(self, coefficients):
        """Готовит вход для расчёта и список замечаний по данным."""
        journal = self._load_journal()
        checks = self._load_checks()
        grp_renewed = _last_replacement_on(journal)
        payload, warnings = [], []

        for row in self.equipment_data:
            equip = self._row_to_dict(row)
            equip['details'] = self._load_details(equip, warnings)
            equip['state_params'] = self._load_state_params(equip, checks)
            record = self._match_journal(equip, journal)
            if record:
                equip['failures'] = record['fail']
                equip['damages'] = record['damage']
                if record['poor']:
                    equip['repair'] = {'quality': 'poor'}
                elif record['total']:
                    equip['repair'] = {'quality': 'new'}
                # Дата последней замены по этому элементу: от неё считается
                # возраст заменяемых запчастей без собственной даты установки.
                equip['replaced_on'] = (_last_replacement_on({'x': record})
                                        or grp_renewed)
            else:
                equip['replaced_on'] = grp_renewed
            payload.append(equip)

        critical = [e for e in payload if classify_critical(e['name'])]
        if not critical:
            warnings.append(
                'Ни один элемент не распознан как критический (регулятор, ПЗК, ПСК, '
                'фильтр, запорная арматура) — проверьте наименования в справочнике.')
        if not any(e['details'] for e in payload):
            warnings.append(
                'Нет данных о запчастях и нормативных сроках службы. Заведите запчасти '
                'с нормами (вкладка «Запчасти») или укажите срок службы вручную — '
                'иначе используется упрощённый календарный вариант.')
        if not coefficients:
            warnings.append(
                f'Журнал технической диагностики пуст: в {algo_label(1)} общий '
                'коэффициент Kобщ = 1, оценка получается завышенной.')
        counted = [e for e in payload if e.get('state_params')]
        if not checks:
            warnings.append(
                'Проверок технического диагностирования нет: K_сост = 1 для всех '
                'элементов (вкладка «Техническое диагностирование»).')
        elif not counted:
            warnings.append(
                'Проверки технического диагностирования не сопоставлены ни с одним '
                'элементом: оборудование в протоколах должно называться так же, как '
                'в справочнике (регулятор, ПЗК, ПСК, фильтр, краны) — иначе K_сост = 1.')
        if not journal:
            warnings.append(
                'Журнал замен пуст: Nотказ = 0 и Nповрежд = 0, поэтому kповр = 1 для '
                'всех элементов.')
        else:
            covered = sum(1 for e in payload
                          if self._match_journal(e, journal))
            if covered < len(payload):
                warnings.append(
                    f'Записи журнала замен найдены только для {covered} из '
                    f'{len(payload)} элементов (сопоставление по типу оборудования).')
        dated = sum(1 for e in payload for d in (e.get('details') or [])
                    if d.get('is_replaceable') and not d.get('install_date'))
        if dated and grp_renewed:
            warnings.append(
                f'У {dated} заменяемых запчастей не указана дата установки — принята '
                f'дата последней замены по ГРП ({grp_renewed}). Укажите дату в '
                f'вкладке «Запчасти», если запчасть менялась отдельно.')
        return payload, warnings, journal

    def _load_checks(self):
        """Проверки технического диагностирования ГРП для K_сост."""
        try:
            rows = self.db.get_diagnostic_checks(self.grp_id) or []
        except Exception:  # noqa: BLE001 — без проверок K_сост = 1
            return []
        return [diagnostic_log.form_values(row) for row in rows]

    def _load_state_params(self, equip, checks):
        """Проверки этого элемента — вход K_сост (шаг 3 расчёта).

        Протокол называет оборудование коротко («Регулятор», «ПЗК», «Кран на
        входе»), а единица в базе — подробно («Клапан предохранительный
        запорный ПКН-50»), поэтому сопоставление идёт по отнесению к
        критическому элементу: тем же признаком элемент опознан и в расчёте.

        Каждая строка протокола даёт до двух проверок — по факту минимума и по
        факту максимума: в расчётном файле паспорта 10 строк регулятора
        считаются как 20 проверок. Строка без фактического значения (в
        протоколе — «герметичность», «норма» словами) проверок не даёт;
        отклонение считается от режима проверки, поэтому строка без режима
        отмечается как непригодная.
        """
        key = classify_critical(equip.get('name') or '')
        if not key:
            return []
        params = []
        for row in checks:
            if classify_critical(row.get('equipment') or '') != key:
                continue
            date = diagnostic_log.date_text(row.get('check_date'))
            parameter = row.get('parameter') or 'Параметр'
            for fact_key, side in (('fact_min', 'мин'), ('fact_max', 'макс')):
                actual = diagnostic_log.to_number(row.get(fact_key))
                if actual is None:
                    continue
                params.append({
                    'name': f'{date} {parameter} ({side})',
                    'nominal': diagnostic_log.to_number(row.get('mode')),
                    'actual': actual,
                    'tol_min': diagnostic_log.to_number(row.get('tolerance_min')),
                    'tol_max': diagnostic_log.to_number(row.get('tolerance_max')),
                })
        return params

    def _load_details(self, equip, warnings):
        """Активные запчасти элемента для варианта Б2 базового ресурса."""
        eq_id = equip.get('equipment_id')
        if eq_id is None:
            return []
        try:
            rows = self.db.get_equipment_parts_full(eq_id) or []
        except Exception as exc:  # noqa: BLE001
            warnings.append(f'Не удалось загрузить запчасти «{equip["name"]}»: {exc}')
            return []

        details = []
        for row in rows:
            row = list(row) + [None] * 8
            norm_years, install_date, removal_date, replaceable = row[3], row[4], row[5], row[7]
            if removal_date or not norm_years or float(norm_years) <= 0:
                continue
            details.append({
                'name': row[2] or 'Запчасть',
                'norm_years': float(norm_years),
                # Своя дата установки запчасти: если её нет, расчёт берёт дату
                # последней замены из журнала, а подставлять сюда дату
                # оборудования нельзя — запчасть с 5-летней нормой выглядела бы
                # просроченной на все годы эксплуатации ГРП.
                'install_date': install_date,
                'equip_install_date': equip.get('install_date'),
                'is_replaceable': bool(replaceable),
            })
        replaceable = [d for d in details if d['is_replaceable']]
        return replaceable or details

    def _load_journal(self):
        """Журнал замен, сгруппированный по типу оборудования."""
        index = {}
        try:
            rows = self.db.get_replacements_by_grp(self.grp_id) or []
        except Exception:  # noqa: BLE001 — журнал не критичен для расчёта
            return {}
        for row in rows:
            row = list(row) + [None] * 9
            replace_date, part_number, equipment_type = row[1], row[2], row[3]
            model, work_type, reason = row[4], row[6], row[7]
            haystack = ' '.join(str(v or '') for v in
                                (work_type, reason, model, part_number)).lower()
            key = str(equipment_type or '').strip().lower()
            record = index.setdefault(key, {'fail': 0, 'damage': 0, 'poor': 0,
                                            'total': 0, 'entries': []})
            record['total'] += 1
            record['entries'].append({'date': replace_date, 'part': part_number,
                                      'work': work_type, 'reason': reason})
            if any(marker in haystack for marker in FAILURE_MARKERS):
                record['fail'] += 1
            if any(marker in haystack for marker in DAMAGE_MARKERS):
                record['damage'] += 1
            if any(marker in haystack for marker in POOR_REPAIR_MARKERS):
                record['poor'] += 1
        return index

    @staticmethod
    def _match_journal(equip, journal):
        """Находит записи журнала для элемента по типу оборудования."""
        name = str(equip.get('name') or '').strip().lower()
        for key, record in journal.items():
            if not key:
                continue
            if key == name or key in name or name in key:
                return record
        return None

    def _coefficients(self):
        """Актуальная запись журнала диагностики: A, B, C → Kобщ."""
        try:
            rows = self.db.get_technical_coefficients(self.grp_id) or []
        except Exception:  # noqa: BLE001
            return {}
        if not rows:
            return {}
        row = list(rows[0]) + [None] * 10
        return {'a': row[2], 'b': row[3], 'c': row[4],
                'source': f'журнал диагностики от {row[1]}',
                'k_db': row[5], 'date': row[1]}

    def _audit_results(self):
        """Добавляет замечания, которые видны только после самого расчёта."""
        result = self._result(PRIMARY_ALGORITHM)
        if result is None or result.error:
            return

        overdue, exhausted, no_data, skipped = [], [], [], []
        for element in result.elements:
            if element is None:
                continue
            if not element.used:
                skipped.append(element.name)
                continue
            if (element.z_base or 0) > 0 and element.z_element <= 0:
                exhausted.append(element.name)
            for detail in element.details:
                if (detail.get('z_base') is not None
                        and detail['z_base'] <= 0 < detail['age']):
                    overdue.append(f'{detail["name"]} ({element.name})')

        if overdue:
            self.warnings.append(
                f'Нормативный срок отработан запчастями ({len(overdue)}): '
                + ', '.join(overdue[:4])
                + ('…' if len(overdue) > 4 else '')
                + ' — их ресурс принят равным нулю.')
        if exhausted:
            self.warnings.append(
                f'Ресурс исчерпан поправками у элементов: {", ".join(exhausted)}.')
        if skipped:
            self.warnings.append(
                f'Не вошли в расчёт как некритические: {len(skipped)} элементов '
                f'(учитываются только в {algo_label(0)} и {algo_label(1)}).')

    def _render_journal_card(self, coefficients):
        if not coefficients:
            self._journal_text.config(text=f'Записей нет — Kобщ = 1,000 ({algo_label(1)} '
                                           'не снижает оценку)')
            return
        a, b, c = coefficients.get('a'), coefficients.get('b'), coefficients.get('c')
        computed = 1 - sum(float(v) for v in (a, b, c) if v is not None) \
            if any(v is not None for v in (a, b, c)) else None
        text = (f"дата: {coefficients.get('date')}\n"
                f"A = {num(a, 4)}    B = {num(b, 4)}    C = {num(c, 4)}"
                f"    →    Kобщ = 1 − (A + B + C) = {num(computed, 4)}")
        if coefficients.get('k_db') is not None and computed is not None:
            if abs(float(coefficients['k_db']) - computed) > 0.0001:
                text += f"\nв базе хранится K = {num(coefficients['k_db'], 4)} — " \
                        f'расхождение с формулой, в расчёте используется формула'
        self._journal_text.config(text=text)

    # ---------------------------------------------------------- Рендеринг

    def _result(self, number):
        return self.results.get(number)

    def _rating(self, value):
        if value <= 0:
            return 'РЕСУРС ИСЧЕРПАН'
        if value < 1:
            return 'КРИТИЧЕСКИЙ · менее 1 года'
        if value < 3:
            return 'НИЗКИЙ · 1-3 года'
        if value < 5:
            return 'СРЕДНИЙ · 3-5 лет'
        return 'ВЫСОКИЙ · более 5 лет'

    def _color(self, value):
        if value <= 0:
            return BAD
        if value < 1:
            return BAD
        if value < 3:
            return WARN
        if value < 5:
            return '#b8860b'
        return GOOD

    def _tag(self, value):
        if value <= 0:
            return 'bad'
        if value < 3:
            return 'warn'
        return 'good'

    def _update_header(self):
        result = self._result(PRIMARY_ALGORITHM)
        used = len(result.used_elements) if result else 0
        self.header_sub.config(
            text=f'{self.grp_name}  ·  элементов в расчёте: {used}'
                 f'  ·  методика: {algo_label(PRIMARY_ALGORITHM)}')

    def _manual_summary(self):
        """Подпись под таблицей коэффициентов: посчитаны они или заданы."""
        values = self.params.manual_values()
        if not values:
            return ('K сост, K эксл, K рем и k повр — поправки, на которые '
                    'умножается базовый ресурс. Где данных нет, коэффициент равен 1 '
                    'и ресурс не снижается.')
        listed = ', '.join(f'{name} = {num(value, 3)}'
                           for name, _label, value in values)
        return (f'Задано вручную — {listed}: формулы методики для этих поправок '
                f'не применяются. Остальные K считаются по методике, и где данных '
                f'нет, коэффициент равен 1.')

    def render_coefficients(self):
        """Таблица коэффициентов по элементам выбранного алгоритма."""
        tree = self.tree_coefficients
        tree.delete(*tree.get_children())
        self._coeff_note.config(text=self._manual_summary())
        result = self._result(self._algo_var.get())
        if result is None:
            self.algo_hint.config(text='')
            fit_table(tree, 0)
            return
        if result.error:
            tree.insert('', tk.END, values=(result.error,) + ('',) * 11)
            self.algo_hint.config(text=result.error)
            fit_table(tree, 0)
            return

        weak = result.weak_element
        for element in result.elements:
            if not element.used:
                tree.insert('', tk.END, tags=('skip',), values=(
                    element.name, element.skip_reason, '—', '—', '—', '—',
                    '—', '—', '—', '—', '—', 'не входит в расчёт'))
                continue
            tag = 'weak' if element.name == weak else ('zero' if element.z_element <= 0 else '')
            # Голубым помечаем строки с ручными K — но только там, где нет
            # цветовой метки по ресурсу: она важнее и не должна перекрываться.
            tags = (tag,) if tag else (('manual',) if element.k_manual else ())
            tree.insert('', tk.END, tags=tags, values=(
                element.name,
                critical_title(element.critical_key) if element.critical_key else '—',
                years_to_text(element.norm),
                years_to_text(element.age),
                signed_years(element.z_base),
                element.z_base_variant or '—',
                num(element.k_state, 3),
                num(element.k_cond, 3),
                num(element.k_repair, 3),
                num(element.k_fail, 3),
                signed_years(element.z_element),
                element.z_element_formula,
            ))

        # Подсказка у выбора методики: она же была в трассировке, которую убрали.
        self.algo_hint.config(
            text=f'в расчёте {len(result.used_elements)} элементов'
                 + (f', слабое звено — {result.weak_element}'
                    if result.weak_element else ''))
        fit_table(tree, len(result.elements), minimum=4, cap=24)

    def _render_inputs(self):
        """Что именно поступило в расчёт и чего не хватило."""
        tree = self.tree_inputs
        tree.delete(*tree.get_children())
        result = self._result(PRIMARY_ALGORITHM)
        if result is None:
            return

        by_id = {element.equipment_id: element for element in result.elements}
        journal = self.journal

        for row in self.equipment_data:
            equip = self._row_to_dict(row)
            element = by_id.get(equip['equipment_id'])
            name = equip['name']
            record = None
            for key, value in journal.items():
                if key and (key == name.lower() or key in name.lower()
                            or name.lower() in key):
                    record = value
                    break

            repair = '—'
            if record:
                if record['poor']:
                    repair = f'некачественный ({record["poor"]})'
                elif record['total']:
                    repair = f'замена ({record["total"]})'

            in_calc = 'да'
            if element is None:
                in_calc = 'нет: нет нормы и запчастей'
            elif not element.used:
                in_calc = f'нет: {element.skip_reason}'

            tag = 'weak' if element and element.name == result.weak_element else (
                'skip' if element is None or not element.used else '')

            tree.insert('', tk.END, tags=(tag,) if tag else (), values=(
                name,
                critical_title(element.critical_key) if element and element.critical_key else '—',
                years_to_text(element.norm) if element else '—',
                (element.norm_source if element and element.norm_source else '—'),
                (len(element.details) if element else 0),
                signed_years(element.z_base) if element and element.z_base is not None else '—',
                (record['fail'] if record else 0),
                (record['damage'] if record else 0),
                repair,
                in_calc,
            ))
