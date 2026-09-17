from datetime import datetime, date
from typing import List, Dict, Tuple, Optional
from models import Equipment
from collections import defaultdict
from decimal import Decimal


class DocumentaryAnalyzer:
    """Анализатор соответствия оборудования документальным нормам"""
    
    def __init__(self, norms_db):
        self.norms_db = norms_db
    
    def _to_float(self, value):
        """Преобразование Decimal в float"""
        if isinstance(value, Decimal):
            return float(value)
        return value
    
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
            
            days = (end_date - install_date).days
            return days / 365.25
        except:
            return 0
    
    def get_norm_for_equipment(self, equipment_name: str) -> Optional[float]:
        """Получает нормативный срок для оборудования"""
        norm = self.norms_db.get_norm_by_name(equipment_name)
        if norm:
            return self._to_float(norm[2])
        return None
    
    def get_replacement_history(self, equipment_list: List[Equipment]) -> Dict:
        """Получает историю замен по каждому типу оборудования (только демонтированное)"""
        history = defaultdict(list)
        
        for equip in equipment_list:
            # Только демонтированное оборудование
            if not equip.removal_date:
                continue
                
            # Базовое имя (без номера)
            base_name = equip.name.split(' (')[0] if ' (' in equip.name else equip.name
            
            lifetime = equip.lifetime_months
            if lifetime:
                lifetime_years = lifetime / 12
                norm = self.get_norm_for_equipment(equip.name)
                
                # Статус замены
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
        
        # Сортируем по дате установки
        for key in history:
            history[key].sort(key=lambda x: x['install_date'])
        
        return dict(history)
    
    def get_exceeded_by_type(self, equipment_list: List[Equipment]) -> Dict:
        """Получает информацию о превышениях нормы по каждому типу оборудования"""
        exceeded_data = defaultdict(list)
        
        for equip in equipment_list:
            lifetime = equip.lifetime_months
            if not lifetime:
                continue
            
            lifetime_years = lifetime / 12
            norm = self.get_norm_for_equipment(equip.name)
            
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
        
        # Сортируем по величине превышения
        for key in exceeded_data:
            exceeded_data[key].sort(key=lambda x: x['exceeded'], reverse=True)
        
        return dict(exceeded_data)
    
    def get_current_problems(self, equipment_list: List[Equipment]) -> Dict:
        """Получает все проблемы текущего оборудования"""
        current_equipment = [e for e in equipment_list if not e.removal_date]
        
        problems = {
            'overdue': [],      # уже превысили норму
            'near_limit': [],   # скоро превысят (менее 1 года)
            'normal': [],       # в норме
            'no_data': []       # нет нормативных данных
        }
        
        for equip in current_equipment:
            age_years = self.get_equipment_age_years(equip.install_date, None)
            norm_years = self.get_norm_for_equipment(equip.name)
            
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
                    'exceeded': age_years - norm_years
                })
            elif age_years >= norm_years - 1:
                problems['near_limit'].append({
                    'name': equip.name,
                    'install_date': equip.install_date,
                    'age_years': age_years,
                    'norm_years': norm_years,
                    'left_years': norm_years - age_years
                })
            else:
                problems['normal'].append({
                    'name': equip.name,
                    'install_date': equip.install_date,
                    'age_years': age_years,
                    'norm_years': norm_years,
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
            norm_years = self.get_norm_for_equipment(equip.name)
            
            result = {
                'name': equip.name,
                'install_date': equip.install_date,
                'age_years': age_years,
                'norm_years': norm_years,
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
        
        # Анализ замен и превышений
        replacement_history = self.get_replacement_history(removed_equipment)
        exceeded_by_type = self.get_exceeded_by_type(equipment_list)
        
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
                'replacement_history': replacement_history,
                'exceeded_by_type': exceeded_by_type
            }
        }
    
    def generate_documentary_report(self, grp_id: int, grp_name: str, equipment_list: List[Equipment]) -> str:
        """Генерирует текстовый отчет по документальному анализу"""
        analysis = self.analyze_grp_equipment(equipment_list)
        
        report_lines = []
        report_lines.append("="*90)
        report_lines.append(f"ДОКУМЕНТАЛЬНЫЙ АНАЛИЗ ГРП")
        report_lines.append(f"ГРП: {grp_name} (ID: {grp_id})")
        report_lines.append(f"Дата анализа: {datetime.now().strftime('%d.%m.%Y %H:%M')}")
        report_lines.append("="*90)
        report_lines.append("")
        
        # ====== ТЕКУЩЕЕ ОБОРУДОВАНИЕ ======
        report_lines.append("📊 ТЕКУЩЕЕ ОБОРУДОВАНИЕ В ЭКСПЛУАТАЦИИ")
        report_lines.append("-"*90)
        
        stats = analysis['current']['statistics']
        report_lines.append(f"Всего в эксплуатации: {stats['total']} шт.")
        report_lines.append(f"  ❌ Превысили норму: {stats['exceeded_count']} шт.")
        report_lines.append(f"  ⚠️ Превысят в течение года: {stats['warning_count']} шт.")
        report_lines.append(f"  ✅ В пределах нормы: {stats['normal_count']} шт.")
        report_lines.append(f"  ❓ Без нормативных данных: {stats['no_norm_count']} шт.")
        report_lines.append("")
        
        # Превысившие норму
        if analysis['current']['exceeded']:
            report_lines.append("="*90)
            report_lines.append("❌ ОБОРУДОВАНИЕ, ПРЕВЫСИВШЕЕ НОРМАТИВНЫЙ СРОК (ТРЕБУЕТ ЗАМЕНЫ)")
            report_lines.append("="*90)
            for e in analysis['current']['exceeded']:
                report_lines.append(f"\n🔴 {e['name']}")
                report_lines.append(f"   📅 Установлено: {e['install_date']}")
                report_lines.append(f"   ⏱ Возраст: {e['age_years']:.1f} лет")
                report_lines.append(f"   📋 Норма: {e['norm_years']} лет")
                report_lines.append(f"   ⚠️ ПРЕВЫШЕНИЕ: {e['exceeded_years']:.1f} лет!")
            report_lines.append("")
        
        # Предупреждения (превысят в течение года)
        if analysis['current']['warning']:
            report_lines.append("="*90)
            report_lines.append("⚠️ ОБОРУДОВАНИЕ, КОТОРОЕ ПРЕВЫСИТ НОРМУ В ТЕЧЕНИЕ ГОДА")
            report_lines.append("="*90)
            for w in analysis['current']['warning']:
                report_lines.append(f"\n🟡 {w['name']}")
                report_lines.append(f"   📅 Установлено: {w['install_date']}")
                report_lines.append(f"   ⏱ Возраст: {w['age_years']:.1f} / {w['norm_years']} лет")
                report_lines.append(f"   ⏰ Осталось: {w['left_years']:.1f} лет ({w['left_years']*12:.0f} мес.)")
            report_lines.append("")
        
        # В норме
        if analysis['current']['normal']:
            report_lines.append("="*90)
            report_lines.append("✅ ОБОРУДОВАНИЕ В ПРЕДЕЛАХ НОРМЫ")
            report_lines.append("="*90)
            for n in analysis['current']['normal']:
                report_lines.append(f"\n🟢 {n['name']}")
                report_lines.append(f"   📅 Установлено: {n['install_date']}")
                report_lines.append(f"   ⏱ Возраст: {n['age_years']:.1f} / {n['norm_years']} лет")
                report_lines.append(f"   📆 Остаток ресурса: {n['left_years']:.1f} лет")
            report_lines.append("")
        
        # Без нормативных данных
        if analysis['current']['no_norm']:
            report_lines.append("="*90)
            report_lines.append("❓ ОБОРУДОВАНИЕ БЕЗ НОРМАТИВНЫХ ДАННЫХ")
            report_lines.append("="*90)
            for nn in analysis['current']['no_norm']:
                report_lines.append(f"\n❔ {nn['name']}")
                report_lines.append(f"   📅 Установлено: {nn['install_date']}")
                report_lines.append(f"   ⏱ Возраст: {nn['age_years']:.1f} лет")
                report_lines.append(f"   💡 Добавьте норму на вкладке 'Документальные нормы'")
            report_lines.append("")
        
        # ====== ИСТОРИЯ ЗАМЕН ======
        if analysis['history']['removed_count'] > 0:
            report_lines.append("="*90)
            report_lines.append(f"📜 ИСТОРИЯ ЗАМЕН ОБОРУДОВАНИЯ (всего {analysis['history']['removed_count']} замен)")
            report_lines.append("="*90)
            
            for equip_type, replacements in analysis['history']['replacement_history'].items():
                report_lines.append(f"\n📌 {equip_type}:")
                # Показываем последние 5 замен
                for r in replacements[-5:]:
                    report_lines.append(f"   • {r['install_date']} → {r['removal_date']}: {r['lifetime_years']:.1f} лет")
                    if r['norm'] and r['lifetime_years'] > r['norm']:
                        report_lines.append(f"     ПРЕВЫШЕНИЕ: {r['exceeded']:.1f} лет")
                if len(replacements) > 5:
                    report_lines.append(f"   ... и еще {len(replacements) - 5} записей")
                report_lines.append("")
        
        # ====== ПРЕВЫШЕНИЯ ПО ТИПАМ ОБОРУДОВАНИЯ ======
        if analysis['history']['exceeded_by_type']:
            report_lines.append("="*90)
            report_lines.append("📊 ПРЕВЫШЕНИЯ НОРМЫ ПО ТИПАМ ОБОРУДОВАНИЯ")
            report_lines.append("="*90)
            
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
            report_lines.append("="*90)
            report_lines.append("📈 ОБЩАЯ СТАТИСТИКА ПРЕВЫШЕНИЙ")
            report_lines.append("="*90)
            
            # Сортируем по количеству превышений
            type_exceeded_count = [(t, len(e)) for t, e in analysis['history']['exceeded_by_type'].items()]
            type_exceeded_count.sort(key=lambda x: x[1], reverse=True)
            
            report_lines.append("\n🔝 Типы оборудования с наибольшим количеством превышений:")
            for t, count in type_exceeded_count[:5]:
                report_lines.append(f"   • {t}: {count} шт.")
            
            # Считаем среднее превышение
            all_exceeds = []
            for exceeds in analysis['history']['exceeded_by_type'].values():
                for e in exceeds:
                    all_exceeds.append(e['exceeded'])
            
            if all_exceeds:
                avg_exceed = sum(all_exceeds) / len(all_exceeds)
                max_exceed = max(all_exceeds)
                report_lines.append(f"\n📊 Среднее превышение по всем случаям: {avg_exceed:.1f} лет")
                report_lines.append(f"📊 Максимальное превышение: {max_exceed:.1f} лет")
        
        # ====== РЕКОМЕНДАЦИИ ======
        report_lines.append("")
        report_lines.append("="*90)
        report_lines.append("💡 РЕКОМЕНДАЦИИ")
        report_lines.append("="*90)
        
        if stats['exceeded_count'] > 0:
            report_lines.append(f"⚠️ Требуется НЕМЕДЛЕННАЯ замена {stats['exceeded_count']} единиц оборудования!")
        if stats['warning_count'] > 0:
            report_lines.append(f"⚠️ Рекомендуется запланировать замену {stats['warning_count']} единиц оборудования в ближайший год.")
        if stats['exceeded_count'] == 0 and stats['warning_count'] == 0:
            report_lines.append("✅ Все оборудование в пределах нормативных сроков.")
        
        report_lines.append("")
        report_lines.append("="*90)
        report_lines.append("КОНЕЦ ОТЧЕТА")
        report_lines.append("="*90)
        
        return "\n".join(report_lines)
    
    def get_warnings_for_next_year(self, equipment_list: List[Equipment]) -> List[Dict]:
        """Получает текущее оборудование, которое превысит норму в следующем году"""
        warnings = []
        current_equipment = [e for e in equipment_list if not e.removal_date]
        
        for equip in current_equipment:
            age_years = self.get_equipment_age_years(equip.install_date, None)
            norm_years = self.get_norm_for_equipment(equip.name)
            
            if norm_years and age_years < norm_years <= age_years + 1:
                warnings.append({
                    'name': equip.name,
                    'install_date': equip.install_date,
                    'age_years': age_years,
                    'norm_years': norm_years,
                    'months_left': (norm_years - age_years) * 12
                })
        
        return warnings