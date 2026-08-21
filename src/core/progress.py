"""Alur langkah harian: Hitung Kalori -> Rekomendasi Menu -> Rekomendasi Latihan.

Aturannya: Langkah 2 dan 3 hanya terbuka kalau user sudah menghitung kalori
PADA HARI YANG SAMA. Begitu tanggal berganti, ketiganya kembali ke kondisi awal
(Langkah 1 terbuka, 2 & 3 terkunci).

Status SENGAJA tidak disimpan sebagai kolom/flag sendiri, melainkan diturunkan
dari `created_at` record yang memang sudah ditulis tiap fitur dipakai
(calorie_records, meal_recommendations, workout_recommendations). Konsekuensinya:

- reset harian terjadi dengan sendirinya, tanpa scheduler/cron dan tanpa perlu
  user membuka aplikasi di tengah malam;
- tidak ada state baru yang bisa "bohong" -- kalau kartu bilang selesai, berarti
  record-nya memang ada di database;
- tidak ada migrasi skema untuk fitur ini.

Modul ini sengaja hanya bergantung pada src.database (bukan streamlit atau view),
supaya bisa dipakai bareng oleh dashboard maupun gerbang akses di
core/state.ensure_nutrition_ready tanpa impor melingkar.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from src.database import CALORIE_STORE, MEAL_STORE, WORKOUT_STORE, load_records


CALORIE = "calorie"
MEAL = "meal"
WORKOUT = "workout"

STORE_PATHS = {
    CALORIE: CALORIE_STORE,
    MEAL: MEAL_STORE,
    WORKOUT: WORKOUT_STORE,
}

DONE = "done"
OPEN = "open"
LOCKED = "locked"

STATUS_LABELS = {DONE: "Selesai", OPEN: "Terbuka", LOCKED: "Terkunci"}


@dataclass(frozen=True)
class Step:
    """Satu kartu navigasi di dashboard."""

    number: int
    store: str
    title: str
    page: str
    icon: str
    status: str
    action_label: str
    hint: str

    @property
    def is_done(self) -> bool:
        """True bila langkah ini sudah diselesaikan hari ini."""
        return self.status == DONE

    @property
    def is_locked(self) -> bool:
        """True bila langkah ini masih terkunci karena Langkah 1 belum dikerjakan hari ini."""
        return self.status == LOCKED

    @property
    def status_label(self) -> str:
        """Label status berbahasa Indonesia: Selesai, Terbuka, atau Terkunci."""
        return STATUS_LABELS.get(self.status, "")


def parse_record_datetime(value) -> datetime | None:
    """Ubah `created_at` (string ISO dari JSON, atau datetime dari SQL) menjadi
    datetime naive. Naive dipilih supaya bisa dibandingkan dengan
    datetime.now() apa pun driver database yang dipakai."""
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return parsed.replace(tzinfo=None)


def record_date(record: dict) -> date | None:
    """Tanggal pembuatan satu record, atau None bila waktunya tidak terbaca."""
    parsed = parse_record_datetime(record.get("created_at"))
    return parsed.date() if parsed else None


def load_user_records(user_id: str | None) -> dict[str, list[dict]]:
    """Semua record milik satu user untuk ketiga store, terurut dari yang paling
    lama. Dipanggil SEKALI per render halaman lalu hasilnya dioper ke tiap kartu
    -- sebelumnya tiap kartu memuat ulang store-nya sendiri, dan di driver SQL
    itu berarti query berulang untuk data yang sama persis."""
    if not user_id:
        return {name: [] for name in STORE_PATHS}

    records: dict[str, list[dict]] = {}
    for name, path in STORE_PATHS.items():
        rows = [row for row in load_records(path) if row.get("user_id") == user_id]
        rows.sort(key=lambda row: parse_record_datetime(row.get("created_at")) or datetime.min)
        records[name] = rows
    return records


def records_on(records: list[dict], day: date) -> list[dict]:
    """Record yang dibuat pada tanggal tertentu."""
    return [record for record in records if record_date(record) == day]


def has_record_on(records: list[dict], day: date) -> bool:
    """True bila ada minimal satu record pada tanggal tertentu."""
    return any(record_date(record) == day for record in records)


def latest_per_day(records: list[dict], *, days: int = 3) -> list[dict]:
    """Record terakhir untuk tiap tanggal, maksimal `days` tanggal terbaru.

    Dipakai feed aktivitas. Perlu karena menu makan disimpan ulang SETIAP kali
    user mencentang "sudah dimakan" (lihat persist_meal_recommendation), jadi
    satu hari bisa punya belasan record yang isinya nyaris sama -- kalau semua
    ditampilkan, feed-nya penuh baris duplikat.
    """
    by_day: dict[date, dict] = {}
    for record in records:
        day = record_date(record)
        if day is None:
            continue
        current = by_day.get(day)
        if current is None or (parse_record_datetime(record.get("created_at")) or datetime.min) >= (
            parse_record_datetime(current.get("created_at")) or datetime.min
        ):
            by_day[day] = record

    latest_days = sorted(by_day, reverse=True)[:days]
    return [by_day[day] for day in latest_days]


def build_steps(records: dict[str, list[dict]], *, today: date | None = None) -> list[Step]:
    """Tiga kartu langkah beserta statusnya untuk hari `today`."""
    today = today or date.today()

    calorie_done = has_record_on(records.get(CALORIE, []), today)
    meal_done = has_record_on(records.get(MEAL, []), today)
    workout_done = has_record_on(records.get(WORKOUT, []), today)

    def gated(done: bool) -> str:
        """Status langkah 2 dan 3: terkunci selama Langkah 1 belum dikerjakan hari ini."""
        # Langkah 2 & 3 mengikuti Langkah 1: tanpa hitung kalori hari ini,
        # keduanya terkunci walaupun kemarin sudah pernah dikerjakan.
        if not calorie_done:
            return LOCKED
        return DONE if done else OPEN

    return [
        Step(
            number=1,
            store=CALORIE,
            title="Hitung Kalori",
            page="Calorie Calculator",
            icon="calculator",
            status=DONE if calorie_done else OPEN,
            action_label="Hitung Ulang" if calorie_done else "Mulai Sekarang",
            hint="Langkah pertama untuk target harian Anda",
        ),
        Step(
            number=2,
            store=MEAL,
            title="Rekomendasi Menu",
            page="Meal Recommendation",
            icon="utensils",
            status=gated(meal_done),
            action_label="Lihat Menu",
            hint="Menu harian sesuai target kalori",
        ),
        Step(
            number=3,
            store=WORKOUT,
            title="Rekomendasi Latihan",
            page="Workout Recommendation",
            icon="dumbbell",
            status=gated(workout_done),
            action_label="Mulai Latihan",
            hint="Program latihan sesuai tujuan Anda",
        ),
    ]


def latest_record_today(store, user_id: str | None, *, today: date | None = None) -> dict | None:
    """Record TERAKHIR milik user pada hari ini untuk satu store.

    Dipakai halaman Menu & Latihan untuk memulihkan hasil yang sudah dibuat
    hari itu setelah halaman di-refresh atau user login ulang -- tanpa ini,
    session state kosong dan user harus menekan "Buat ..." lagi, yang berarti
    menu/program hari itu tergantikan hasil acak baru.
    """
    if not user_id:
        return None
    today = today or date.today()

    latest = None
    latest_at = None
    for record in load_records(store):
        if record.get("user_id") != user_id:
            continue
        created_at = parse_record_datetime(record.get("created_at"))
        if created_at is None or created_at.date() != today:
            continue
        if latest_at is None or created_at >= latest_at:
            latest_at = created_at
            latest = record
    return latest


def calorie_done_today(user_id: str | None, *, today: date | None = None) -> bool:
    """Versi ringkas untuk gerbang akses halaman Menu & Latihan (satu query)."""
    if not user_id:
        return False
    today = today or date.today()
    return any(
        record.get("user_id") == user_id and record_date(record) == today
        for record in load_records(CALORIE_STORE)
    )
