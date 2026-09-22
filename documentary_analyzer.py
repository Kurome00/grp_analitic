from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

from config import EQUIPMENT_NORMS
from models import Equipment


class DocumentaryAnalyzer:
    """Анализатор соответствия оборудования документальным нормам"""

    def __init__(self, norms_db):
        self.norms_db = norms_db

    @staticmethod
    def _parse_date(value) -> Optional[date]:
        try:
            if isinstance(value, date):
                return value
            if isinstance(value, datetime):
                return value.date()
            return datetime.strptime(value, '%Y-%m-%d').date()
        except Exception:
            return None

    def get_equipment_age_years(self, install_date_str: str, removal_date_str: Optional[str] = None) -> float:
        """Рассчитывает возраст оборудования в годах"""
        try:
            if isinstance(install_date_str, date):
                install_date = install_date_str
            else:
                install_date = datetime.strptime(install_date_str, '%Y-%m-%d').date()

            if removal_date_str:
                if isinstance(removal_date_str, date):
                    end_date = removal_date_str
                else:
                    end_date = datetime.strptime(removal_date_str, '%Y-%m-%d').date()
            else:
                end_date = date.today()

            return (end_date - install_date).days / 365.25
        except Exception:
            return 0.0

    def get_norm_for_equipment(self, equipment_name: str,
                               equipment_id: Optional[int] = None,
                               install_date: Optional[str] = None) -> Optional[float]:
        """Нормативный срок для оборудования.

        Если известно оборудование с запчастями — срок определяется по запчастям
        (слабое звено). Иначе ищем в БД (точное или подстрочное совпадение),
        затем в базовых нормах config.EQUIPMENT_NORMS.
        Возвращает None, если норма не найдена.
        """
        if equipment_id is not None:
            effective = self.get_effective_norm(equipment_id, install_date)
            if effective is not None:
                return float(effective)

        for _, norm_name, max_years, _ in self.norms_db.get_all_norms():
            if norm_name and (equipment_name == norm_name or norm_name in equipment_name):
                return float(max_years)

        for key, years in EQUIPMENT_NORMS.items():
            if key in equipment_name:
                return float(years)
        return None

    def get_effective_norm(self, equipment_id: int, install_date: str) -> Optional[float]:
        """Эффективный срок службы по запчастям (принцип 'слабого звена').

        Для каждой запчасти срок окончания = дата установки запчасти +
        норма запчасти. Дата установки запчасти по умолчанию = дата установки
        оборудования. Результат = срок окончания самой 'слабой' запчасти
        относительно даты установки оборудования. Может быть отрицательным
        (запчасть уже просрочена). None — если запчастей нет.
        """
        parts = self.norms_db.get_equipment_parts(equipment_id)
        if not parts:
            return None

        equip_install = self._parse_date(install_date)
        active_norms = []
        for _ep_id, _part_id, _pname, pnorm, p_install, p_removal in parts:
            if p_removal:
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
        for _ep_id, _part_id, _pname, pnorm, p_install, p_removal in parts:
            if p_removal:
                continue
            part_start = self._parse_date(p_install) or equip_install
            try:
                norm_years = float(pnorm)
            except (TypeError, ValueError):
                continue
            expiries.append(part_start + timedelta(days=norm_years * 365.25))

        if not expiries:
            return None
        return (min(expiries) - equip_install).days / 365.25

    def get_parts_status(self, equipment_id: int, install_date: str) -> List[Dict]:
        """Статус каждой запчасти оборудования: имя, норма, дата установки,
        дата окончания, остаток ресурса (лет)."""
        parts = self.norms_db.get_equipment_parts(equipment_id)
        equip_install = self._parse_date(install_date)
        if not parts or equip_install is None:
            return []

        status_list = []
        for _ep_id, _part_id, pname, pnorm, p_install, p_removal in parts:
            part_start = self._parse_date(p_install) or equip_install
            try:
                norm_years = float(pnorm)
            except (TypeError, ValueError):
                continue
            expiry = part_start + timedelta(days=norm_years * 365.25)
            status_list.append({
                'name': pname,
                'norm_years': norm_years,
                'install_date': part_start.isoformat(),
                'expiry_date': expiry.isoformat(),
                'remaining': (expiry - date.today()).days / 365.25,
                'removed': bool(p_removal),
            })
        return sorted(status_list, key=lambda s: (s['expiry_date'] if not s['removed'] else '9999'))

    def _resolve_norm(self, equip: Equipment) -> Tuple[Optional[float], str]:
        """Норма и её источник: 'parts' — по запчастям, иначе 'document'."""
        if getattr(equip, 'id', None):
            effective = self.get_effective_norm(equip.id, equip.install_date)
            if effective is not None:
                return effective, 'parts'
        return self.get_norm_for_equipment(equip.name), 'document'

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
                    status = f"ЗАМЕНЕНО (превышение {excess:.1f} лет)"
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
        """Все проблемы текущего оборудования"""
        problems = {
            'overdue': [],      # уже превысили норму
            'near_limit': [],   # скоро превысят (менее 1 года)
            'normal': [],       # в норме
            'no_data': []       # нет нормативных данных
        }

        for equip in equipment_list:
            if equip.removal_date:
                continue

            age_years = self.get_equipment_age_years(equip.install_date, None)
            norm_years, norm_source = self._resolve_norm(equip)

            if norm_years is None:
                problems['no_data'].append({
                    'name': equip.name,
                    'install_date': equip.install_date,
                    'age_years': age_years
                })
            elif age_years > norm_years:
                problems['overdue'].append({
                    'name': equip.name,
                    'install_date': equip.install_date,
                    'age_years': age_years,
                    'norm_years': norm_years,
                    'norm_source': norm_source,
                    'exceeded': age_years - norm_years
                })
            elif age_years >= norm_years - 1:
                problems['near_limit'].append({
                    'name': equip.name,
                    'install_date': equip.install_date,
                    'age_years': age_years,
                    'norm_years': norm_years,
                    'norm_source': norm_source,
                    'left_years': norm_years - age_years
                })
            else:
                problems['normal'].append({
                    'name': equip.name,
                    'install_date': equip.install_date,
                    'age_years': age_years,
                    'norm_years': norm_years,
                    'norm_source': norm_source,
                    'left_years': norm_years - age_years
                })

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
            norm_years, norm_source = self._resolve_norm(equip)
            parts_status = self.get_parts_status(equip.id, equip.install_date) if getattr(equip, 'id', None) else []

            result = {
                'name': equip.name,
                'install_date': equip.install_date,
                'age_years': age_years,
                'norm_years': norm_years,
                'norm_source': norm_source,
                'parts_status': parts_status,
            }

            if norm_years is None:
                result['status'] = 'no_norm'
                no_norm_current.append(result)
            elif age_years > norm_years:
                result['status'] = 'exceeded'
                result['exceeded_years'] = age_years - norm_years
                exceeded_current.append(result)
            elif age_years >= norm_years - 1:
                result['status'] = 'warning'
                result['left_years'] = norm_years - age_years
                warning_current.append(result)
            else:
                result['status'] = 'normal'
                result['left_years'] = norm_years - age_years
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

    def _format_parts_notes(self, result: Dict) -> List[str]:
        """Строки отчёта с детализацией по запчастям."""
        if result.get('norm_source') != 'parts':
            return []
        notes = [f"   📋 Норма: {result['norm_years']:.1f} лет (по запчастям)"]
        for p in result.get('parts_status', []):
            if p['removed']:
                continue
            if p['remaining'] < 0:
                mark = "⚠️"
            elif p['remaining'] < 1:
                mark = "🟡"
            else:
                mark = "🟢"
            notes.append(f"      {mark} {p['name']} — оконч. {p['expiry_date']}, остаток {p['remaining']:.1f} лет")
        return notes

    def generate_documentary_report(self, grp_id: int, grp_name: str, equipment_list: List[Equipment]) -> str:
        """Генерирует текстовый отчет по документальному анализу"""
        analysis = self.analyze_grp_equipment(equipment_list)

        report_lines = []
        report_lines.append("=" * 90)
        report_lines.append("ДОКУМЕНТАЛЬНЫЙ АНАЛИЗ ГРП")
        report_lines.append(f"ГРП: {grp_name} (ID: {grp_id})")
        report_lines.append(f"Дата анализа: {datetime.now().strftime('%d.%m.%Y %H:%M')}")
        report_lines.append("=" * 90)
        report_lines.append("")

        # ====== ТЕКУЩЕЕ ОБОРУДОВАНИЕ ======
        report_lines.append("📊 ТЕКУЩЕЕ ОБОРУДОВАНИЕ В ЭКСПЛУАТАЦИИ")
        report_lines.append("-" * 90)

        stats = analysis['current']['statistics']
        report_lines.append(f"Всего в эксплуатации: {stats['total']} шт.")
        report_lines.append(f"  ❌ Превысили норму: {stats['exceeded_count']} шт.")
        report_lines.append(f"  ⚠️ Превысят в течение года: {stats['warning_count']} шт.")
        report_lines.append(f"  ✅ В пределах нормы: {stats['normal_count']} шт.")
        report_lines.append(f"  ❓ Без нормативных данных: {stats['no_norm_count']} шт.")
        report_lines.append("")

        def section(title):
            report_lines.append("=" * 90)
            report_lines.append(title)
            report_lines.append("=" * 90)

        # Превысившие норму
        if analysis['current']['exceeded']:
            section("❌ ОБОРУДОВАНИЕ, ПРЕВЫСИВШЕЕ НОРМАТИВНЫЙ СРОК (ТРЕБУЕТ ЗАМЕНЫ)")
            for e in analysis['current']['exceeded']:
                report_lines.append(f"\n🔴 {e['name']}")
                report_lines.append(f"   📅 Установлено: {e['install_date']}")
                report_lines.append(f"   ⏱ Возраст: {e['age_years']:.1f} лет")
                if e.get('norm_source') == 'parts':
                    report_lines.extend(self._format_parts_notes(e))
                else:
                    report_lines.append(f"   📋 Норма: {e['norm_years']} лет")
                report_lines.append(f"   ⚠️ ПРЕВЫШЕНИЕ: {e['exceeded_years']:.1f} лет!")
            report_lines.append("")

        # Предупреждения (превысят в течение года)
        if analysis['current']['warning']:
            section("⚠️ ОБОРУДОВАНИЕ, КОТОРОЕ ПРЕВЫСИТ НОРМУ В ТЕЧЕНИЕ ГОДА")
            for w in analysis['current']['warning']:
                report_lines.append(f"\n🟡 {w['name']}")
                report_lines.append(f"   📅 Установлено: {w['install_date']}")
                report_lines.append(f"   ⏱ Возраст: {w['age_years']:.1f} / {w['norm_years']:.1f} лет")
                if w.get('norm_source') == 'parts':
                    report_lines.extend(self._format_parts_notes(w))
                report_lines.append(f"   ⏰ Осталось: {w['left_years']:.1f} лет ({w['left_years']*12:.0f} мес.)")
            report_lines.append("")

        # В норме
        if analysis['current']['normal']:
            section("✅ ОБОРУДОВАНИЕ В ПРЕДЕЛАХ НОРМЫ")
            for n in analysis['current']['normal']:
                report_lines.append(f"\n🟢 {n['name']}")
                report_lines.append(f"   📅 Установлено: {n['install_date']}")
                report_lines.append(f"   ⏱ Возраст: {n['age_years']:.1f} / {n['norm_years']:.1f} лет")
                if n.get('norm_source') == 'parts':
                    report_lines.extend(self._format_parts_notes(n))
                report_lines.append(f"   📆 Остаток ресурса: {n['left_years']:.1f} лет")
            report_lines.append("")

        # Без нормативных данных
        if analysis['current']['no_norm']:
            section("❓ ОБОРУДОВАНИЕ БЕЗ НОРМАТИВНЫХ ДАННЫХ")
            for nn in analysis['current']['no_norm']:
                report_lines.append(f"\n❔ {nn['name']}")
                report_lines.append(f"   📅 Установлено: {nn['install_date']}")
                report_lines.append(f"   ⏱ Возраст: {nn['age_years']:.1f} лет")
                report_lines.append(f"   💡 Добавьте норму на вкладке 'Документальные нормы'")
            report_lines.append("")

        # ====== ИСТОРИЯ ЗАМЕН ======
        if analysis['history']['removed_count'] > 0:
            section(f"📜 ИСТОРИЯ ЗАМЕН ОБОРУДОВАНИЯ (всего {analysis['history']['removed_count']} замен)")

            for equip_type, replacements in analysis['history']['replacement_history'].items():
                report_lines.append(f"\n📌 {equip_type}:")
                for r in replacements[-5:]:
                    report_lines.append(f"   • {r['install_date']} → {r['removal_date']}: {r['lifetime_years']:.1f} лет")
                    if r['norm'] and r['lifetime_years'] > r['norm']:
                        report_lines.append(f"     ПРЕВЫШЕНИЕ: {r['exceeded']:.1f} лет")
                if len(replacements) > 5:
                    report_lines.append(f"   ... и еще {len(replacements) - 5} записей")
                report_lines.append("")

        # ====== ПРЕВЫШЕНИЯ ПО ТИПАМ ОБОРУДОВАНИЯ ======
        if analysis['history']['exceeded_by_type']:
            section("📊 ПРЕВЫШЕНИЯ НОРМЫ ПО ТИПАМ ОБОРУДОВАНИЯ")

            for equip_type, exceeds in analysis['history']['exceeded_by_type'].items():
                report_lines.append(f"\n📌 {equip_type}: {len(exceeds)} случаев превышения")
                for e in exceeds[:3]:
                    current_mark = " (В ЭКСПЛУАТАЦИИ!)" if e['is_current'] else ""
                    report_lines.append(f"   • {e['name']}{current_mark}")
                    report_lines.append(f"     Период: {e['install_date']} → {e['removal_date']}")
                    report_lines.append(f"     Факт: {e['lifetime_years']:.1f} лет / Норма: {e['norm']} лет")
                    report_lines.append(f"     ПРЕВЫШЕНИЕ: {e['exceeded']:.1f} лет")
                if len(exceeds) > 3:
                    report_lines.append(f"     ... и еще {len(exceeds) - 3} записей")
                report_lines.append("")

        # ====== ОБЩАЯ СТАТИСТИКА ПРЕВЫШЕНИЙ ======
        total_exceeded = sum(len(exceeds) for exceeds in analysis['history']['exceeded_by_type'].values())
        if total_exceeded > 0:
            section("📈 ОБЩАЯ СТАТИСТИКА ПРЕВЫШЕНИЙ")

            type_exceeded_count = [(t, len(e)) for t, e in analysis['history']['exceeded_by_type'].items()]
            type_exceeded_count.sort(key=lambda x: x[1], reverse=True)

            report_lines.append("\n🔝 Типы оборудования с наибольшим количеством превышений:")
            for t, count in type_exceeded_count[:5]:
                report_lines.append(f"   • {t}: {count} шт.")

            all_exceeds = [e['exceeded'] for exceeds in analysis['history']['exceeded_by_type'].values() for e in exceeds]
            if all_exceeds:
                report_lines.append(f"\n📊 Среднее превышение по всем случаям: {sum(all_exceeds)/len(all_exceeds):.1f} лет")
                report_lines.append(f"📊 Максимальное превышение: {max(all_exceeds):.1f} лет")

        # ====== РЕКОМЕНДАЦИИ ======
        report_lines.append("")
        section("💡 РЕКОМЕНДАЦИИ")

        if stats['exceeded_count'] > 0:
            report_lines.append(f"⚠️ Требуется НЕМЕДЛЕННАЯ замена {stats['exceeded_count']} единиц оборудования!")
        if stats['warning_count'] > 0:
            report_lines.append(f"⚠️ Рекомендуется запланировать замену {stats['warning_count']} единиц оборудования в ближайший год.")
        if stats['exceeded_count'] == 0 and stats['warning_count'] == 0:
            report_lines.append("✅ Все оборудование в пределах нормативных сроков.")

        report_lines.append("")
        section("КОНЕЦ ОТЧЕТА")

        return "\n".join(report_lines)