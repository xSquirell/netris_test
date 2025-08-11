import math
from dataclasses import dataclass
from typing import Tuple, List, Dict, Union

import streamlit as st

st.set_page_config(page_title="Конфигуратор видеосервера (упрощённое ТЗ)", layout="wide")

# ----------------------------
# Константы из упрощённого ТЗ
# ----------------------------

@dataclass
class Tier:
    cam_range: Tuple[int, int]
    cores_label: str  # строкой, как в ТЗ
    ram_gb: int

TIERS: List[Tier] = [
    Tier((1, 8),   "2–4 ядра", 8),
    Tier((9, 16),  "4 ядра", 8),
    Tier((17, 32), "4 ядра", 16),
    Tier((33, 64), "6 ядер", 32),
    Tier((65, 100),"8 ядер", 64),
    Tier((101, 200),"10 ядер", 64),
    Tier((201, 400),"12 ядер", 96),
    Tier((401, 500),"14 ядер", 128),
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
      • 7–16 → RAID6 ИЛИ 2×RAID5 в RAID0 (ёмкость идентична → (n-2)×disk)
      • >16 → две группы RAID6 в RAID0 → суммарно (n-4)×disk
    """
    if n < 2:
        return 0.0, "-"
    if n == 2:
        return 1 * disk_tb, "RAID1 (2 диска)"
    if 3 <= n <= 6:
        return (n - 1) * disk_tb, f"RAID5 ({n} диска)"
    if 7 <= n <= 16:
        return (n - 2) * disk_tb, f"RAID6 ({n} дисков) или 2×RAID5 в RAID0"

    # >16: две группы RAID6 в RAID0 (RAID60). Суммарные накладные расходы = 4 диска.
    return (n - 4) * disk_tb, f"RAID60 (2 группы RAID6, всего {n} дисков)"


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

st.title("Конфигуратор видеосервера по числу камер — упрощённое ТЗ")

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
st.subheader("Итоговая конфигурация")
col1, col2, col3 = st.columns(3)

with col1:
    st.markdown("**Сервер**")
    st.write(f"""CPU: {chosen.cores_label}

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
    st.write(f"""Диск: {disk_tb:.0f} ТБ

Базовых дисков (data+parity): {plan['base_disks']}

Hot‑spare (для >16 дисков, 1 на 18): {plan['spares']}

Всего физических дисков: {plan['total_disks']}

Схема: {plan['raid']}

Полезная ёмкость: {plan['usable_tb']:.2f} ТБ

Требуемая полезная ёмкость (с учётом коэффициента): {plan['required_usable_tb']:.2f} ТБ

Суммарная RAW-ёмкость: {plan['raw_tb']:.2f} ТБ""")

st.divider()

st.caption("""Правила подбора CPU/RAM, подсистемы ОС и массива под архив жёстко соответствуют упрощённому ТЗ из чата.
Для диапазона 7–16 дисков ёмкость RAID6 и 2×RAID5 в RAID0 одинаковая ((n−2)×диск), выбрана нейтральная подача.
Для >16 дисков используется RAID60 (две группы RAID6) и добавляются hot‑spare: 1 на каждые 18 дисков.""")

# Экспорт
import json
result = {
    "cameras": cams,
    "archive_tb_per_camera": ARCHIVE_TB_PER_CAMERA,
    "required_archive_tb": archive_effective_tb,
    "required_usable_tb": archive_effective_tb / FILL_FACTOR,
    "fill_factor": FILL_FACTOR,
    "disk_tb": disk_tb,
    "server": {"cpu": chosen.cores_label, "ram_gb": chosen.ram_gb, "os": OS_NAME, "os_storage": OS_STORAGE_STR},
    "storage_plan": plan,
}

st.download_button(
    label="Скачать конфигурацию (JSON)",
    data=json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8"),
    file_name="server_config.json",
    mime="application/json",
)

