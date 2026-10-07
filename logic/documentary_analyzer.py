from typing import Dict, List, Optional, Tuple
from collections import defaultdict

from core.lifetimes import (
    add_years,
    age_years,
    driving_parts_remaining,
    parse_date,
    remaining_years,
    years_between,
)
from core.models import Equipment
from core.timefmt import years_to_text


class DocumentaryAnalyzer:
    """Анализатор сроков службы оборудования по заменяемым запчастям"""

    def __init__(self, norms_db):
        self.norms_db = norms_db

    _parse_date = staticmethod(parse_date)

    def get_equipment_age_years(self, install_date_str: str, removal_date_str: Optional[str] = None) -> float:
        """Возраст оборудования в годах (до снятия или до сегодняшнего дня)"""
        return age_years(install_date_str, removal_date_str)

    def get_norm_for_equipment(self, equipment_name: str,
                               equipment_id: Optional[int] = None,
                               install_date: Optional[str] = None) -> Optional[float]:
        """Эффективный срок службы оборудования по заменяемым запчастям.

        Оборудование не имеет собственного срока; срок равен минимальному
        сроку службы заменяемых запчастей. None — если заменяемых запчастей
        нет.
        """
        if equipment_id is not None:
            effective = self.get_effective_norm(equipment_id, install_date)
            if effective is not None:
                return float(effective)
        return None

    def get_effective_norm(self, equipment_id: int, install_date: str) -> Optional[float]:
        """Эффективный срок службы по запчастям (принцип 'слабого звена').

        Учитываются только заменяемые детали (со звездой в альбоме, срок
        службы которых 5 лет). Для каждой такой запчасти срок окончания =
        дата установки запчасти + норма запчасти. Дата установки запчасти
        по умолчанию = дата установки оборудования. Результат = срок
        окончания самой 'слабой' запчасти относительно даты установки
        оборудования. Может быть отрицательным (запчасть уже просрочена).
        None — если заменяемых запчастей нет.
        """
        parts = self.norms_db.get_equipment_parts_full(equipment_id)
        if not parts:
            return None

        equip_install = self._parse_date(install_date)
        active_norms = []
        for _ep_id, _part_id, _pname, pnorm, p_install, p_removal, _pnumb, is_repl in parts:
            if p_removal or not is_repl:
                continue
            try:
                active_norms.append(float(pnorm))
            except (TypeError, ValueError):
                continue

        if not active_norms:
            return None

        # Нет даты установки оборудования (например, в каталоге) —
        # срок службы полностью определяется запчастями.
        if equip_install is None:
            return min(active_norms)

        expiries = []
        for _ep_id, _part_id, _pname, pnorm, p_install, p_removal, _pnumb, is_repl in parts:
            if p_removal or not is_repl:
                continue
            expiry = add_years(self._parse_date(p_install) or equip_install, pnorm)
            if expiry is not None:
                expiries.append(expiry)

        if not expiries:
            return None
        return years_between(min(expiries), equip_install)

    def get_remaining_life(self, equipment_id: int, install_date: str) -> Optional[float]:
        """Оставшийся срок службы оборудования, лет.

        Оборудование не имеет собственного срока: его срок равен
        минимальному оставшемуся сроку службы среди заменяемых запчастей
        (со звездой в альбоме, срок службы 5 лет). None — если активных
        заменяемых запчастей нет.
        """
        parts = self.norms_db.get_equipment_parts_full(equipment_id)
        if not parts:
            return None

        remaining = driving_parts_remaining(parts)
        return min(remaining) if remaining else None

    def get_parts_status(self, equipment_id: int, install_date: str) -> List[Dict]:
        """Статус каждой заменяемой запчасти оборудования: имя, норма, дата
        установки, дата окончания, остаток ресурса (лет).

        В расчёт срока оборудования идут только заменяемые детали.
        """
        parts = self.norms_db.get_equipment_parts_full(equipment_id)
        equip_install = self._parse_date(install_date)
        if not parts or equip_install is None:
            return []

        status_list = []
        for _ep_id, _part_id, pname, pnorm, p_install, p_removal, pnumb, is_repl in parts:
            if not is_repl:
                continue
            part_start = self._parse_date(p_install) or equip_install
            expiry = add_years(part_start, pnorm)
            if expiry is None:
                continue
            status_list.append({
                'name': pname,
                'norm_years': float(pnorm),
                'install_date': part_start.isoformat(),
                'expiry_date': expiry.isoformat(),
                'remaining': remaining_years(part_start, pnorm) or 0.0,
                'removed': bool(p_removal),
            })
        return sorted(status_list, key=lambda s: (s['expiry_date'] if not s['removed'] else '9999'))

    def _resolve_norm(self, equip: Equipment) -> Tuple[Optional[float], Optional[str]]:
        """Норма и её источник: 'parts' — по запчастям, иначе None."""
        if getattr(equip, 'id', None):
            effective = self.get_effective_norm(equip.id, equip.install_date)
            if effective is not None:
                return effective, 'parts'
        return None, None

    def get_replacement_history(self, equipment_list: List[Equipment]) -> Dict:
        """История замен по каждому типу оборудования (только демонтированное)"""
        history = defaultdict(list)

        for equip in equipment_list:
            if not equip.removal_date:
                continue

            base_name = equip.name.split(' (')[0] if ' (' in equip.name else equip.name

            lifetime = equip.lifetime_months
            if lifetime:
                lifetime_years = lifetime / 12
                norm, _ = self._resolve_norm(equip)

                if norm and lifetime_years > norm:
                    excess = lifetime_years - norm
                    status = f"ЗАМЕНЕНО (превышение {years_to_text(excess)})"
                elif norm and lifetime_years < norm * 0.8:
                    status = "ЗАМЕНЕНО (досрочно)"
                else:
                    status = "ЗАМЕНЕНО"

                history[base_name].append({
                    'name': equip.name,
                    'install_date': equip.install_date,
                    'removal_date': equip.removal_date,
                    'lifetime_years': lifetime_years,
                    'norm': norm,
                    'status': status,
                    'exceeded': lifetime_years - norm if norm and lifetime_years > norm else 0
                })

        for key in history:
            history[key].sort(key=lambda x: x['install_date'])

        return dict(history)

    def get_exceeded_by_type(self, equipment_list: List[Equipment]) -> Dict:
        """Информация о превышениях нормы по каждому типу оборудования"""
        exceeded_data = defaultdict(list)

        for equip in equipment_list:
            lifetime = equip.lifetime_months
            if not lifetime:
                continue

            lifetime_years = lifetime / 12
            norm, _ = self._resolve_norm(equip)

            if norm and lifetime_years > norm:
                base_name = equip.name.split(' (')[0] if ' (' in equip.name else equip.name
                exceeded_data[base_name].append({
                    'name': equip.name,
                    'install_date': equip.install_date,
                    'removal_date': equip.removal_date if equip.removal_date else "в эксплуатации",
                    'lifetime_years': lifetime_years,
                    'norm': norm,
                    'exceeded': lifetime_years - norm,
                    'is_current': equip.removal_date is None
                })

        for key in exceeded_data:
            exceeded_data[key].sort(key=lambda x: x['exceeded'], reverse=True)

        return dict(exceeded_data)

    def get_current_problems(self, equipment_list: List[Equipment]) -> Dict:
        """Все проблемы текущего оборудования.

        Оборудование не имеет собственного срока: его срок равен
        минимальному оставшемуся сроку службы среди всех запчастей.
        Без запчастей срока нет (оборудование помечается как 'внесите оборудование').
        """
        problems = {
            'overdue': [],      # просрочены (мин. остаток < 0)
            'near_limit': [],   # мин. остаток менее 1 года
            'normal': [],       # мин. остаток >= 1 года
            'no_data': []       # запчастей нет — срока нет
        }

        for equip in equipment_list:
            if equip.removal_date:
                continue

            age_years = self.get_equipment_age_years(equip.install_date, None)
            remaining = self.get_remaining_life(equip.id, equip.install_date) if getattr(equip, 'id', None) else None

            base = {
                'name': equip.name,
                'install_date': equip.install_date,
                'age_years': age_years,
                'remaining': remaining,
                'norm_source': 'parts' if remaining is not None else None,
            }

            if remaining is None:
                problems['no_data'].append(base)
            elif remaining < 0:
                base['exceeded'] = -remaining
                problems['overdue'].append(base)
            elif remaining < 1:
                base['left_years'] = remaining
                problems['near_limit'].append(base)
            else:
                base['left_years'] = remaining
                problems['normal'].append(base)

        return problems

    def analyze_grp_equipment(self, equipment_list: List[Equipment]) -> Dict:
        """Полный анализ оборудования ГРП (только текущее оборудование)"""
        current_equipment = [e for e in equipment_list if not e.removal_date]
        removed_equipment = [e for e in equipment_list if e.removal_date]

        exceeded_current = []
        warning_current = []
        normal_current = []
        no_norm_current = []

        for equip in current_equipment:
            age_years = self.get_equipment_age_years(equip.install_date, None)
            remaining = self.get_remaining_life(equip.id, equip.install_date) if getattr(equip, 'id', None) else None
            parts_status = self.get_parts_status(equip.id, equip.install_date) if getattr(equip, 'id', None) else []

            result = {
                'name': equip.name,
                'install_date': equip.install_date,
                'age_years': age_years,
                'remaining': remaining,
                'norm_source': 'parts' if remaining is not None else None,
                'parts_status': parts_status,
            }

            if remaining is None:
                result['status'] = 'no_norm'
                no_norm_current.append(result)
            elif remaining < 0:
                result['status'] = 'exceeded'
                result['exceeded_years'] = -remaining
                exceeded_current.append(result)
            elif remaining < 1:
                result['status'] = 'warning'
                result['left_years'] = remaining
                warning_current.append(result)
            else:
                result['status'] = 'normal'
                result['left_years'] = remaining
                normal_current.append(result)

        return {
            'current': {
                'exceeded': exceeded_current,
                'warning': warning_current,
                'normal': normal_current,
                'no_norm': no_norm_current,
                'statistics': {
                    'total': len(current_equipment),
                    'exceeded_count': len(exceeded_current),
                    'warning_count': len(warning_current),
                    'normal_count': len(normal_current),
                    'no_norm_count': len(no_norm_current)
                }
            },
            'history': {
                'removed_count': len(removed_equipment),
                'replacement_history': self.get_replacement_history(removed_equipment),
                'exceeded_by_type': self.get_exceeded_by_type(equipment_list)
            }
        }
