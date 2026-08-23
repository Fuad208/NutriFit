"""Penandaan menu dan latihan yang benar-benar dikerjakan pengguna hari ini.

Menyimpan status klaim, menghitung gizi yang sudah dikonsumsi, dan menaksir
kalori yang terbakar dari program latihan yang ditandai selesai.
"""

from __future__ import annotations

import copy
from datetime import date, datetime
from uuid import uuid4

from src.database import MEAL_STORE, WORKOUT_STORE, append_record
from src.recommender import estimate_exercise_calories

from .progress import MEAL, WORKOUT, parse_record_datetime


def records_today(records: list[dict], *, today: date | None = None) -> list[dict]:
    """Record milik hari ini, terurut dari yang paling lama."""
    today = today or date.today()
    dated = [
        (parsed, record)
        for record in records or []
        if (parsed := parse_record_datetime(record.get("created_at"))) is not None
        and parsed.date() == today
    ]
    dated.sort(key=lambda pair: pair[0])
    return [record for _, record in dated]


# --------------------------------------------------------------------------- #
# Menu makan
# --------------------------------------------------------------------------- #
def _meal_item_key(slot: str, item: dict):
    """Kunci identitas satu item menu: pasangan slot makan dan id (atau nama bila id kosong)."""
    identity = item.get("id")
    if identity is None:
        identity = item.get("name")
    return slot, identity


def resolve_meal_states(meal_records: list[dict], *, today: date | None = None) -> dict:
    """Status terakhir yang diketahui untuk SETIAP item menu hari ini.

    Bukan sekadar isi record terakhir: membuat menu baru di sore hari tidak boleh
    menghapus item pagi yang sudah dimakan, sedangkan membatalkan centang harus
    tetap terbaca. Karena itu tiap item diambil dari record terakhir yang masih
    memuatnya.
    """
    states: dict = {}
    for record in records_today(meal_records, today=today):
        recommendations = record.get("recommendations") or {}
        if not isinstance(recommendations, dict):
            continue
        for slot, items in recommendations.items():
            for item in items or []:
                if isinstance(item, dict):
                    states[_meal_item_key(slot, item)] = item
    return states


def todays_meal_plan(meal_records: list[dict], *, today: date | None = None) -> dict[str, list[dict]]:
    """Susunan menu hari ini (dari record terakhir) dengan status klaim terkini."""
    todays = records_today(meal_records, today=today)
    if not todays:
        return {}

    latest = todays[-1].get("recommendations") or {}
    if not isinstance(latest, dict):
        return {}

    states = resolve_meal_states(meal_records, today=today)
    plan: dict[str, list[dict]] = {}
    for slot, items in latest.items():
        resolved = []
        for item in items or []:
            if not isinstance(item, dict):
                continue
            known = states.get(_meal_item_key(slot, item), item)
            merged = dict(item)
            merged["is_eaten"] = bool(known.get("is_eaten", False))
            resolved.append(merged)
        plan[slot] = resolved
    return plan


def set_meal_claim(
    user: dict,
    meal_records: list[dict],
    slot: str,
    item_id,
    claimed: bool,
    *,
    today: date | None = None,
) -> bool:
    """Tandai satu menu sudah/belum dimakan, lalu simpan sebagai record baru."""
    # Tanpa user_id, record akan tertulis tanpa pemilik dan tidak akan pernah
    # terbaca lagi oleh siapa pun (load_user_records menyaring per user_id) --
    # sekaligus mengotori tabel. Sesi yang tidak sinkron ditolak di sini.
    if not user or not user.get("user_id"):
        return False

    plan = todays_meal_plan(meal_records, today=today)
    if slot not in plan:
        return False

    updated = copy.deepcopy(plan)
    found = False
    for item in updated[slot]:
        identity = item.get("id") if item.get("id") is not None else item.get("name")
        if identity == item_id:
            item["is_eaten"] = bool(claimed)
            found = True
    if not found:
        return False

    latest = records_today(meal_records, today=today)[-1]
    append_record(
        MEAL_STORE,
        {
            "id": str(uuid4()),
            "user_id": user.get("user_id"),
            "email": user.get("email"),
            "preference": latest.get("preference") or [],
            "recommendations": updated,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        },
    )
    return True


def consumed_nutrition(meal_records: list[dict], *, today: date | None = None) -> dict:
    """Total kalori & makro dari seluruh menu yang diklaim sudah dimakan hari ini."""
    totals = {"calories": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carbohydrate_g": 0.0}
    for item in resolve_meal_states(meal_records, today=today).values():
        if not item.get("is_eaten"):
            continue
        totals["calories"] += safe_float(item.get("target_calories"))
        # Makro dataset dinyatakan per 100 g, sedangkan yang dimakan adalah
        # porsi hasil konversi kalori. Tanpa penskalaan ini, menu 40 g dan menu
        # 400 g akan dihitung menyumbang protein yang sama persis.
        scale = safe_float(item.get("portion_gram")) / 100 or 1.0
        totals["protein_g"] += safe_float(item.get("proteins")) * scale
        totals["fat_g"] += safe_float(item.get("fat")) * scale
        totals["carbohydrate_g"] += safe_float(item.get("carbohydrate")) * scale
    return totals


# --------------------------------------------------------------------------- #
# Latihan
# --------------------------------------------------------------------------- #
def _exercise_key(exercise: dict) -> str:
    """Kunci identitas satu latihan: judulnya, atau Program_ID bila judul kosong."""
    return str(exercise.get("Title") or exercise.get("Program_ID") or "")


def resolve_workout_states(workout_records: list[dict], *, today: date | None = None) -> dict[str, dict]:
    """Status terakhir yang diketahui untuk setiap latihan hari ini, digabung dari seluruh record."""
    states: dict[str, dict] = {}
    for record in records_today(workout_records, today=today):
        rows = record.get("recommendations") or []
        if not isinstance(rows, list):
            continue
        for exercise in rows:
            if isinstance(exercise, dict) and _exercise_key(exercise):
                states[_exercise_key(exercise)] = exercise
    return states


def todays_workout_plan(workout_records: list[dict], *, today: date | None = None) -> list[dict]:
    """Program latihan hari ini (dari record terakhir) dengan status klaim terkini."""
    todays = records_today(workout_records, today=today)
    if not todays:
        return []

    latest = todays[-1].get("recommendations") or []
    if not isinstance(latest, list):
        return []

    states = resolve_workout_states(workout_records, today=today)
    plan = []
    for exercise in latest:
        if not isinstance(exercise, dict):
            continue
        merged = dict(exercise)
        known = states.get(_exercise_key(exercise), exercise)
        merged["is_done"] = bool(known.get("is_done", False))
        plan.append(merged)
    return plan


def set_workout_claim(
    user: dict,
    workout_records: list[dict],
    exercise_title: str,
    claimed: bool,
    *,
    today: date | None = None,
) -> bool:
    """Tandai satu latihan sudah/belum dikerjakan, lalu simpan sebagai record baru."""
    if not user or not user.get("user_id"):
        return False

    plan = todays_workout_plan(workout_records, today=today)
    if not plan:
        return False

    found = False
    for exercise in plan:
        if _exercise_key(exercise) == str(exercise_title):
            exercise["is_done"] = bool(claimed)
            found = True
    if not found:
        return False

    latest = records_today(workout_records, today=today)[-1]
    append_record(
        WORKOUT_STORE,
        {
            "id": str(uuid4()),
            "user_id": user.get("user_id"),
            "email": user.get("email"),
            "filters": latest.get("filters") or {},
            "recommendations": plan,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        },
    )
    return True


def burned_calories(
    workout_records: list[dict],
    weight_kg: float | None,
    *,
    today: date | None = None,
) -> float:
    """Perkiraan kalori terbakar dari latihan yang diklaim sudah dikerjakan hari ini."""
    return sum(
        estimate_exercise_calories(exercise, weight_kg)
        for exercise in resolve_workout_states(workout_records, today=today).values()
        if exercise.get("is_done")
    )


# --------------------------------------------------------------------------- #
# Ringkasan
# --------------------------------------------------------------------------- #
def claim_summary(records: dict[str, list[dict]], weight_kg: float | None, *, today: date | None = None) -> dict:
    """Satu panggilan untuk semua angka klaim yang dipakai dashboard."""
    meal_records = records.get(MEAL, [])
    workout_records = records.get(WORKOUT, [])
    meal_plan = todays_meal_plan(meal_records, today=today)
    workout_plan = todays_workout_plan(workout_records, today=today)
    meal_items = [item for items in meal_plan.values() for item in items]
    return {
        "meal_plan": meal_plan,
        "workout_plan": workout_plan,
        "meals_claimed": sum(1 for item in meal_items if item.get("is_eaten")),
        "meals_total": len(meal_items),
        "workouts_claimed": sum(1 for exercise in workout_plan if exercise.get("is_done")),
        "workouts_total": len(workout_plan),
        "consumed": consumed_nutrition(meal_records, today=today),
        "burned": burned_calories(workout_records, weight_kg, today=today),
    }


def safe_float(value) -> float:
    """Ubah nilai jadi float; balas 0.0 bila kosong atau tidak bisa dikonversi."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
