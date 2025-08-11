import math
from dataclasses import dataclass
from typing import Tuple, List, Dict, Union

import streamlit as st

st.set_page_config(page_title="Конфигуратор сервера «Безопасный регион»", layout="wide")

# ----------------------------
# Константы из упрощённого ТЗ
# ----------------------------

@dataclass
class Tier:
    cam_range: Tuple[int, int]
    cores_label: str  # строкой, как в ТЗ
    ram_gb: int
    cpu_model: str

TIERS: List[Tier] = [
    Tier((1, 8),   "2–4 ядра", 8,   "Intel Xeon E-2314"),
    Tier((9, 16),  "4 ядра",   8,   "Intel Xeon E-2314"),
    Tier((17, 32), "4 ядра",   16,  "Intel Xeon E-2314"),
    Tier((33, 64), "6 ядер",   32,  "Intel Xeon E-2336"),
    Tier((65, 100),"8 ядер",   64,  "Intel Xeon E-2378"),
    Tier((101, 200),"10 ядер", 64,  "Intel Xeon Silver 4310"),
    Tier((201, 400),"12 ядер", 96,  "Intel Xeon Silver 4310"),
    Tier((401, 500),"14 ядер", 128, "Intel Xeon Silver 4314"),
]

# Диски под ОС: всегда 2×240 ГБ SSD в RAID1 (фиксировано по ТЗ)
OS_STORAGE_STR = "2×240 ГБ SSD, RAID1"
OS_NAME = "РЕД ОС"

# Архив: 1,4 ТБ на 1 камеру (фиксировано)
ARCHIVE_TB_PER_CAMERA = 1.4
# Коэффициент заполнения массива (используем не более этого значения)
FILL_FACTOR = 0.77

# ----------------------------
# Вспомогательные функции
# ----------------------------

def cpu_family_code(cpu_model: str) -> str:
    """Код семейства CPU для имени: 5 – Xeon E, 7 – Xeon Silver."""
    if "Silver" in cpu_model:
        return "7"
    # по умолчанию считаем E‑серией
    return "5"


def chassis_code(total_disks: int) -> str:
    """Код корпуса по общему количеству дисков (включая hot‑spare).
    1–12 → '2'; 13–16 → '3'; 17–24 → '4'; ≥25 → возвращаем пустую строку (нет корпуса)."""
    if 1 <= total_disks <= 12:
        return "2"
    if 13 <= total_disks <= 16:
        return "3"
    if 17 <= total_disks <= 24:
        return "4"
    return ""  # нет подходящего корпуса


def raid_short_code(raid_str: str) -> str:
    if "RAID60" in raid_str:
        return "R60"
    if "RAID6" in raid_str:
        return "R6"
    if "RAID5" in raid_str:
        return "R5"
    if "RAID1" in raid_str:
        return "R1"
    return "R?"


def build_server_name(cams: int, plan: Dict[str, Union[int, float, str]], chosen: Tier) -> str:
    """Формирует имя по шаблону:
    'Сервер LTV SR{chassis}{cpu}0-{cams}N-{usable}-R6-IR.{RAM}G.WI.CSI' (R6 — всегда, признак аппаратного контроллера)
    Если дисков ≥25, возвращаем пустую строку — будем выводить предупреждение.
    """
    total_disks = int(plan.get("total_disks", 0))
    ch = chassis_code(total_disks)
    if not ch:
        return ""
    cpu_code = cpu_family_code(chosen.cpu_model)
    usable_int = int(round(float(plan.get("usable_tb", 0.0))))
    raid_code = "R6"  # всегда R6: признак аппаратного контроллера в имени
    ram = int(chosen.ram_gb)
    return f"Сервер LTV SR{ch}{cpu_code}0-{cams}N-{usable_int}-{raid_code}-IR.{ram}G.WI.CSI"

def pick_tier(num_cams: int) -> Tier:
    for t in TIERS:
        if t.cam_range[0] <= num_cams <= t.cam_range[1]:
            return t
    if num_cams < 1:
        return TIERS[0]
    return TIERS[-1]


def usable_and_level(n: int, disk_tb: float) -> Tuple[float, str]:
    """Возвращает (полезная ёмкость ТБ, строка с уровнем RAID) для массива из n БАЗОВЫХ дисков
    (не включая hot-spare).

    Правила из упрощённого ТЗ:
      • 2 шт → RAID1
      • 3–6 → RAID5
      • 7–16 → RAID6
      • >16 → две группы RAID6 в RAID0 → суммарно (n-4)×disk
    """
    if n < 2:
        return 0.0, "-"
    if n == 2:
        return 1 * disk_tb, "RAID1 (2 диска)"
    if 3 <= n <= 6:
        return (n - 1) * disk_tb, f"RAID5 ({n} диска)"
    if 7 <= n <= 16:
        return (n - 2) * disk_tb, f"RAID6 ({n} дисков)"

    # >16: две группы RAID6 в RAID0 (RAID60). Разбиваем массив на две максимально равные группы.
    g1 = math.ceil(n / 2)
    g2 = n - g1
    # Страхуемся: обе группы должны быть валидными для RAID6 (минимум 4 диска на группу)
    if g2 < 4:
        g2 = 4
        g1 = n - g2
    usable = max(g1 - 2, 0) + max(g2 - 2, 0)
    return usable * disk_tb, f"RAID60 (RAID6 {g1} дисков, RAID6 {g2} дисков)"


def plan_storage(required_effective_tb: float, disk_tb: float, fill_factor: float) -> Dict[str, Union[float, int, str]]:
    """Подбираем минимальное число базовых дисков (без hot-spare),
    чтобы полезная ёмкость ≥ требуемой. Для n>16 добавляются hot-spare: 1 на каждые 18 дисков."""
    best = None
    required_usable_tb = required_effective_tb / fill_factor
    for n in range(2, 240):
        usable_tb, level = usable_and_level(n, disk_tb)
        if usable_tb >= required_usable_tb:
            spares = math.ceil(n / 18) if n > 16 else 0
            total = n + spares
            best = {
                "base_disks": n,
                "spares": spares,
                "total_disks": total,
                "raid": level,
                "usable_tb": usable_tb,
                "required_usable_tb": required_usable_tb,
                "raw_tb": total * disk_tb,
            }
            break

    if best is None:
        return {
            "base_disks": 0,
            "spares": 0,
            "total_disks": 0,
            "raid": "Невозможно подобрать (увеличьте размер диска)",
            "usable_tb": 0.0,
            "required_usable_tb": required_usable_tb,
            "raw_tb": 0.0,
        }

    return best

# ----------------------------
# UI
# ----------------------------

st.title("Конфигуратор сервера «Безопасный регион»")

with st.sidebar:
    st.header("Ввод")
    cams = st.number_input("Количество видеокамер", min_value=1, max_value=2000, value=32, step=1)
    disk_tb = st.select_slider(
        "Ёмкость одного диска архива, ТБ",
        options=[4.0, 6.0, 8.0, 10.0, 12.0, 14.0, 16.0, 18.0, 20.0, 22.0],
        value=16.0,
    )

# Расчёты
archive_effective_tb = cams * ARCHIVE_TB_PER_CAMERA
chosen = pick_tier(cams)
plan = plan_storage(archive_effective_tb, disk_tb, FILL_FACTOR)

# Вывод
st.subheader("Параметры:")
col1, col2, col3 = st.columns(3)

with col1:
    st.markdown("**Сервер**")
    st.write(f"""CPU: {chosen.cpu_model}

Ядра (по ТЗ): {chosen.cores_label}

RAM: {chosen.ram_gb} ГБ

ОС: {OS_NAME}

Подсистема ОС: {OS_STORAGE_STR}""")

with col2:
    st.markdown("**Хранилище видеоархива**")
    st.write(f"""Требуемый объём на 1 камеру: {ARCHIVE_TB_PER_CAMERA:.1f} ТБ

Камер: {cams}

Итого требуемо: {archive_effective_tb:.2f} ТБ

Коэффициент заполнения массива (не более): {FILL_FACTOR:.2f}

Требуемая полезная ёмкость с учётом коэффициента: {archive_effective_tb / FILL_FACTOR:.2f} ТБ""")

with col3:
    st.markdown("**Дисковый массив (под архив)**")
    st.write(f"""Диски: {disk_tb:.0f} ТБ × {plan['total_disks']} шт

Hot‑spare: {plan['spares']} шт

Схема RAID: {plan['raid']}

Эффективная ёмкость (usable): {plan['usable_tb']:.2f} ТБ

RAW-ёмкость: {plan['raw_tb']:.2f} ТБ""")

st.divider()

# Имя сервера по правилам пользователя
server_name = build_server_name(cams, plan, chosen)
if server_name:
    st.subheader("Наименование сервера")
    st.code(server_name)
else:
    st.error("Невозможно сформировать имя: требуется корпус на более чем 24 диска.")



