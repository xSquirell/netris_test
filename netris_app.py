import math
from dataclasses import dataclass
from typing import Tuple, List, Dict

import streamlit as st

st.set_page_config(
    page_title="Конфигуратор видеосервера",
    layout="wide",
)

# ----------------------------
# Константы из предоставленных таблиц
# ----------------------------

@dataclass
class Tier:
    cam_range: Tuple[int, int]
    cpu_class: str
    min_physical_cores: str  # как в ТЗ ("2-4", "4", ...)
    ram_gb: int

# ВАЖНО: значения ниже собраны по присланным скриншотам.
# Если ваши исходные таблицы отличаются, просто поправьте цифры здесь.
TIERS: List[Tier] = [
    Tier((2, 8),   "не хуже Intel i5 Gen8 (≥2.1 ГГц)",  "2-4",  8),
    Tier((9, 16),  "не хуже Intel i5 Gen8 (≥2.1 ГГц)",  "4",    16),
    Tier((17, 32), "не хуже Intel i5 Gen8 (≥2.1 ГГц)",  "4",    32),
    Tier((33, 64), "не хуже Intel i5 Gen8 (≥2.1 ГГц)",  "6",    64),
    Tier((65, 100),"не хуже Intel Xeon E5 (≥2.1 ГГц)",  "8",    96),
    Tier((101, 200),"не хуже Intel Xeon E5 (≥2.1 ГГц)", "10",   128),
    # Последние два значения RAM ориентировочные – уточните по вашему документу, если нужно
    Tier((201, 400),"не хуже Intel Xeon E5 (≥2.1 ГГц)", "12",   192),
    Tier((401, 500),"не хуже Intel Xeon E5 (≥2.1 ГГц)", "14",   256),
]

# Профили хранения из Табл. 10
# Ключ – краткое имя профиля, значение – требуемый объём видеоархива на 1 камеру, Тбайт
CAMERA_PROFILES_TB: Dict[str, float] = {
    "Стац. Тип 1/2/9 – 4096 кбит/с, 30 суток": 1.4,
    "Стац. Тип 3/4 – 2048 кбит/с, 30 суток": 0.7,
    "Мобильный ПАК – 2048 кбит/с, 30 суток": 0.7,
    "МКД Тип 1/2/9 – 4096 кбит/с, 30 суток": 1.4,
    "МКД Тип 3/4 – 2048 кбит/с, 10 суток": 0.3,
    "МКД Тип 3/5 – 2048 кбит/с, 10 суток (с метаданными)": 0.5,
}

FILL_FACTOR = 0.77  # Коэффициент заполнения массива не более 0.77 (из ТЗ)

# ----------------------------
# Вспомогательные функции
# ----------------------------

def pick_tier(num_cams: int) -> Tier:
    for t in TIERS:
        if t.cam_range[0] <= num_cams <= t.cam_range[1]:
            return t
    # Если камер меньше 2 или больше 500, подбираем ближайший допустимый диапазон
    if num_cams < TIERS[0].cam_range[0]:
        return TIERS[0]
    return TIERS[-1]


def aggregate_throughput(num_cams: int) -> Dict[str, float]:
    # По таблице: запись ≥8 Мбит/с с 1 ВК, чтение ≥16 Мбит/с с 1 ВК
    write_mbps = num_cams * 8
    read_mbps = num_cams * 16
    return {"write_mbps": write_mbps, "read_mbps": read_mbps}


def usable_capacity_tb(base_disks: int, disk_tb: float) -> Tuple[float, str]:
    """Возвращает (полезная ёмкость ТБ, строка с уровнем RAID) для массива без учёта hot-spare.
    Логика из ТЗ:
      - 2 диска  -> RAID1
      - 3..6     -> RAID5
      - 7..16    -> RAID6
      - >16      -> две группы RAID6, объединённые в RAID0 (RAID60)
    """
    if base_disks < 2:
        return 0.0, "-"
    if base_disks == 2:
        return 1 * disk_tb, "RAID1 (2 диска)"
    if 3 <= base_disks <= 6:
        return (base_disks - 1) * disk_tb, f"RAID5 ({base_disks} диска)"
    if 7 <= base_disks <= 16:
        return (base_disks - 2) * disk_tb, f"RAID6 ({base_disks} дисков)"

    # >16: разбиваем на 2 группы (как указано в ТЗ), каждая – RAID6, сверху – RAID0
    g1 = math.ceil(base_disks / 2)
    g2 = base_disks - g1
    # Минимальный размер группы для RAID6 обычно ≥4; проверок на нижний предел из ТЗ нет, но оставим здравый смысл
    u1 = (g1 - 2) * disk_tb if g1 >= 4 else 0
    u2 = (g2 - 2) * disk_tb if g2 >= 4 else 0
    return (u1 + u2), f"RAID60 (2×RAID6: {g1}+{g2} дисков)"


def plan_storage(total_effective_tb: float, disk_tb: float) -> Dict[str, float | int | str]:
    """Подбираем минимальное число базовых дисков, чтобы полезная емкость ≥ требуемой,
    учитывая коэффициент заполнения 0.77 и горячие резервы 1 диск на каждые 18 дисков.
    Возвращаем словарь с планом.
    """
    # Требуемый usable с учетом FILL_FACTOR
    required_usable_tb = total_effective_tb / FILL_FACTOR

    best = None
    for base_disks in range(2, 200):  # разумный предел
        usable_tb, raid_str = usable_capacity_tb(base_disks, disk_tb)
        if usable_tb >= required_usable_tb:
            # hot-spare: 1 диск на каждые 18 физических. Считаем от base_disks.
            spares = math.ceil(base_disks / 18)
            total_physical = base_disks + spares
            best = {
                "base_disks": base_disks,
                "spares": spares,
                "total_disks": total_physical,
                "raid": raid_str,
                "usable_tb": usable_tb,
                "required_usable_tb": required_usable_tb,
                "raw_tb": total_physical * disk_tb,
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

st.title("Конфигуратор видеосервера по числу камер")

with st.sidebar:
    st.header("Входные данные")
    cams = st.number_input("Количество видеокамер", min_value=1, max_value=2000, value=32, step=1)

    profile_name = st.selectbox(
        "Профиль камеры (Табл. 10)",
        list(CAMERA_PROFILES_TB.keys()),
        index=1,
    )
    per_cam_tb = CAMERA_PROFILES_TB[profile_name]

    disk_tb = st.select_slider(
        "Ёмкость одного диска хранилища, ТБ",
        options=[4.0, 6.0, 8.0, 10.0, 12.0, 14.0, 16.0, 18.0, 20.0, 22.0],
        value=16.0,
    )

    st.caption("Коэффициент заполнения массива из ТЗ (не более 0.77)")
    fill = st.number_input("Коэффициент заполнения (0.01…1.0)", min_value=0.01, max_value=1.0, value=FILL_FACTOR, step=0.01)

# Расчёты
per_cam_storage_tb = per_cam_tb
storage_effective_tb = cams * per_cam_storage_tb
fill_factor_used = fill

# Подбор железа по диапазону камер
chosen_tier = pick_tier(cams)

# Сеть и пропускная способность
throughput = aggregate_throughput(cams)

# Планирование массива
plan = plan_storage(total_effective_tb=storage_effective_tb, disk_tb=disk_tb)

# ----------------------------
# Вывод
# ----------------------------

st.subheader("Итоговая конфигурация")

col1, col2, col3 = st.columns(3)
with col1:
    st.markdown("**Сервер**")
    st.write(
        f"CPU: {chosen_tier.cpu_class}\n\n"
        f"Мин. физ. ядра: {chosen_tier.min_physical_cores}\n\n"
        f"RAM: {chosen_tier.ram_gb} ГБ\n\n"
        f"ОС: РЕД ОС (не ниже 7.3)\n\n"
        f"Подсистема ОС: 2×SSD, RAID1 (по ТЗ; вместимость \u2265 120–240 ГБ в зависимости от комплектации)"
    )

with col2:
    st.markdown("**Хранилище (СХД) по Табл. 10**")
    st.write(
        f"Профиль: {profile_name}\n\n"
        f"Требуемый объём на 1 камеру: {per_cam_storage_tb:.2f} ТБ\n\n"
        f"Камер: {cams}\n\n"
        f"Итого требуемый видеоархив (effective): {storage_effective_tb:.2f} ТБ\n\n"
        f"Заложенный коэффициент заполнения: {fill_factor_used:.2f}"
    )

with col3:
    st.markdown("**Дисковый массив**")
    st.write(
        f"Подбор под диск {disk_tb:.0f} ТБ:\n\n"
        f"Базовых дисков (data+parity): {plan['base_disks']}\n\n"
        f"Hot-spare (1 на 18 дисков): {plan['spares']}\n\n"
        f"Всего физических дисков: {plan['total_disks']}\n\n"
        f"Схема: {plan['raid']}\n\n"
        f"Полезная ёмкость массива: {plan['usable_tb']:.2f} ТБ\n\n"
        f"Требуемая полезная ёмкость (с учётом заполнения): {plan['required_usable_tb']:.2f} ТБ\n\n"
        f"Суммарная RAW-ёмкость (все физ. диски): {plan['raw_tb']:.2f} ТБ"
    )

st.divider()

st.subheader("Сеть и потоки")
st.write(
    f"Суммарная запись ≥ {throughput['write_mbps']} Мбит/с, чтение ≥ {throughput['read_mbps']} Мбит/с (из расчёта 8/16 Мбит/с на камеру по ТЗ).\n\n"
    f"Сетевые интерфейсы: не менее 2× 1000BASE‑T/1000BASE‑TX (по ТЗ)."
)

st.info(
    "Примечания:\n"
    "• Правила выбора RAID и коэффициент заполнения 0.77 взяты из вашей Табл. 10.\n"
    "• Для массивов >16 дисков применяется схема RAID60 (две группы RAID6, объединённые в RAID0).\n"
    "• Горячий резерв: 1 диск на каждые 18 дисков.\n"
    "• Значения RAM для диапазонов 201–400 и 401–500 камер выставлены ориентировочно (192/256 ГБ). При необходимости скорректируйте в списке TIERS вверху файла.\n"
)

# Экспорт результатов
result = {
    "cameras": cams,
    "profile": profile_name,
    "per_camera_tb": per_cam_storage_tb,
    "effective_archive_tb": storage_effective_tb,
    "fill_factor": fill_factor_used,
    "disk_tb": disk_tb,
    "plan": plan,
    "server": {
        "cpu_class": chosen_tier.cpu_class,
        "min_physical_cores": chosen_tier.min_physical_cores,
        "ram_gb": chosen_tier.ram_gb,
        "os": "РЕД ОС (≥7.3)",
        "os_storage": "2×SSD, RAID1",
    },
    "throughput_mbps": aggregate_throughput(cams),
}

import json
st.download_button(
    label="Скачать конфигурацию (JSON)",
    data=json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8"),
    file_name="server_config.json",
    mime="application/json",
)

st.caption("Версия: начальный прототип. Отредактируйте блоки TIERS и CAMERA_PROFILES_TB при необходимости.")
