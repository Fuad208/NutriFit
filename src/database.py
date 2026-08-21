"""Akses data NutriFit ke PostgreSQL (Supabase).

SATU-SATUNYA penyimpanan aplikasi. Tidak ada driver alternatif dan tidak ada
penyimpanan berkas: seluruh akun, riwayat, dan dataset ada di sini.

ISOLASI PENGUJIAN. Skrip pengujian TIDAK boleh menulis ke data asli. Karena
penyimpanannya kini cuma satu, isolasinya pindah ke tingkat schema Postgres:
env `POSTGRES_SCHEMA` menentukan schema mana yang dipakai, dan tiap koneksi
membawa `search_path` sendiri. Aplikasi memakai `public`, pengujian memakai
schema sekali-pakai. Sengaja TANPA `,public` di belakang search_path -- kalau
ada, tabel yang belum terbentuk di schema uji akan diam-diam terbaca dari data
asli, dan isolasinya jadi bohong.

Variabel .env yang dibutuhkan:
    POSTGRES_HOST, POSTGRES_PORT, POSTGRES_USER, POSTGRES_PASSWORD,
    POSTGRES_DATABASE, dan (opsional) POSTGRES_SCHEMA.
"""

from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import threading
from typing import Any
from uuid import uuid4

import pandas as pd

from src.paths import ENV_PATH


# Koneksi dipakai ulang antar-query. Sebelumnya tiap pemanggilan connection()
# membuka koneksi baru ke Supabase lalu menutupnya; handshake TLS-nya sendiri
# makan ~3,8 detik, dan satu render halaman beranda memanggilnya 5-6 kali --
# jadi ~20 detik hanya untuk menarik ~100 baris. Lock dipakai karena Streamlit
# menjalankan tiap sesi di thread terpisah sementara koneksi DB tidak aman
# dipakai bersamaan; akses jadi bergiliran, tapi tiap query kini milidetik
# sehingga jauh lebih cepat daripada menyambung ulang terus-menerus.
_CONNECTION_LOCK = threading.RLock()
_CONNECTION_CACHE: dict[str, Any] = {}

# Penanda skema/migrasi sudah dijalankan untuk suatu target database.
_SCHEMA_READY: set[str] = set()


def _connection_is_alive(connection) -> bool:
    """Cek cepat apakah koneksi yang di-cache masih hidup sebelum dipakai ulang."""
    try:
        return getattr(connection, "closed", 1) == 0
    except Exception:
        return False


def reset_connection_cache() -> None:
    """Tutup & buang koneksi yang di-cache (dipakai di test / setelah gagal)."""
    with _CONNECTION_LOCK:
        for connection in _CONNECTION_CACHE.values():
            try:
                connection.close()
            except Exception:
                pass
        _CONNECTION_CACHE.clear()
        _SCHEMA_READY.clear()


# Identitas ketiga tabel riwayat, dipakai di seluruh aplikasi sebagai ganti
# menyebar nama tabelnya (lihat record_table).
CALORIE_STORE = "calorie"
MEAL_STORE = "meal"
WORKOUT_STORE = "workout"

RECORD_STORES = (CALORIE_STORE, MEAL_STORE, WORKOUT_STORE)

DEFAULT_SCHEMA = "public"

# Nama schema disisipkan ke DDL dan ke parameter koneksi, jadi tidak bisa
# di-parameterisasi seperti nilai biasa -- karena itu divalidasi ketat.
_SCHEMA_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def load_env(path: Path | None = None) -> None:
    """Muat pasangan KEY=VALUE dari berkas .env ke environment; nilai yang sudah ada tidak ditimpa."""
    path = ENV_PATH if path is None else path
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


load_env()


def getenv(name: str, default: str | None = None) -> str | None:
    """Ambil variabel environment; nama huruf besar dicoba dulu, lalu versi huruf kecilnya."""
    return os.getenv(name, os.getenv(name.lower(), default))


def database_schema() -> str:
    """Schema Postgres yang sedang dipakai; pengujian mengalihkannya lewat POSTGRES_SCHEMA."""
    name = (getenv("POSTGRES_SCHEMA", DEFAULT_SCHEMA) or DEFAULT_SCHEMA).strip()
    if not _SCHEMA_PATTERN.match(name):
        raise ValueError(
            f"POSTGRES_SCHEMA tidak valid: {name!r}. "
            "Hanya huruf, angka, dan garis bawah, serta tidak diawali angka."
        )
    return name


def ensure_database() -> None:
    """Siapkan penyimpanan: buat schema beserta seluruh tabel bila belum ada."""
    SQLStore().ensure_schema()


def load_users() -> dict:
    """Ambil seluruh akun sebagai dict {email: data user}."""
    users = SQLStore().load_users()
    return users if isinstance(users, dict) else {}


def save_users(users: dict) -> None:
    """Simpan seluruh akun, menimpa isi lama."""
    SQLStore().save_users(users)


def load_records(store: str) -> list[dict]:
    """Ambil semua record pada store (calorie/meal/workout), terurut waktu pembuatan."""
    return SQLStore().load_records(normalize_store(store))


def save_records(store: str, records: list[dict]) -> None:
    """Timpa seluruh isi store dengan daftar record yang baru."""
    SQLStore().save_records(normalize_store(store), records)


def append_record(store: str, record: dict) -> None:
    """Tambahkan satu record ke store tanpa menulis ulang seluruh isinya."""
    SQLStore().append_record(normalize_store(store), record)


def delete_record(store: str, record_id: str) -> None:
    """Hapus satu record dari store berdasarkan id."""
    SQLStore().delete_record(normalize_store(store), record_id)


def delete_user_and_related_data(email: str) -> None:
    """Hapus akun beserta seluruh riwayat kalori, menu, dan latihan miliknya."""
    store = SQLStore()
    users = store.load_users()
    user = users.get(email)
    if not user:
        return
    # DELETE langsung berdasarkan user_id -- JANGAN diganti pola baca-saring-tulis
    # ulang: menulis ulang seluruh tabel demi membuang satu pengguna membuat
    # riwayat pengguna LAIN ikut terhapus dan disisipkan ulang, dan kalau
    # prosesnya putus di tengah, data merekalah yang hilang.
    store.delete_user(email, user.get("user_id"))


def latest_user_record(store: str, user_id: str | None) -> dict | None:
    """Record terbaru milik satu pengguna pada store tertentu, atau None bila belum ada."""
    if not user_id:
        return None
    records = [record for record in load_records(store) if record.get("user_id") == user_id]
    if not records:
        return None
    return sorted(records, key=lambda record: record.get("created_at", ""))[-1]


def to_jsonable(value: Any):
    """Ubah nilai bersarang (dict/list/DataFrame/tipe NumPy) jadi bentuk yang aman di-JSON."""
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [to_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [to_jsonable(item) for item in value]
    if isinstance(value, pd.DataFrame):
        return to_jsonable(value.to_dict("records"))
    if hasattr(value, "item"):
        try:
            return value.item()
        except ValueError:
            pass
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def normalize_store(store: str) -> str:
    """Samakan penyebutan store jadi salah satu dari calorie/meal/workout."""
    store_name = str(store).strip().lower()
    if store_name not in RECORD_STORES:
        raise ValueError(f"Unknown record store: {store}")
    return store_name


class SQLStore:
    """Akses tabel PostgreSQL: koneksi, migrasi skema, serta CRUD user dan record."""

    def __init__(self) -> None:
        """Baca konfigurasi koneksi dan schema tujuan dari environment."""
        self.config = self._config()
        self.schema = database_schema()

    def _config(self) -> dict:
        """Konfigurasi host, port, user, password, dan nama database dari environment."""
        return {
            "host": getenv("POSTGRES_HOST", "127.0.0.1"),
            "port": int(getenv("POSTGRES_PORT", "5432") or "5432"),
            "user": getenv("POSTGRES_USER", "postgres"),
            "password": getenv("POSTGRES_PASSWORD", ""),
            "database": getenv("POSTGRES_DATABASE", getenv("POSTGRES_DB", "")),
        }

    def _connection_key(self) -> str:
        """Kunci cache koneksi; schema ikut masuk supaya koneksi uji tidak tertukar dengan koneksi aplikasi."""
        config = self.config
        return "|".join(
            str(part)
            for part in (config["host"], config["port"], config["user"], config["database"], self.schema)
        )

    def _open_connection(self):
        """Buka koneksi baru ke PostgreSQL dengan search_path dikunci ke schema tujuan."""
        import psycopg
        from psycopg.rows import dict_row

        return psycopg.connect(
            host=self.config["host"],
            port=self.config["port"],
            user=self.config["user"],
            password=self.config["password"],
            dbname=self.config["database"] or None,
            row_factory=dict_row,
            options=f"-c search_path={self.schema}",
        )

    @contextmanager
    def connection(self):
        """Context manager koneksi dari cache: commit bila sukses, rollback dan buang koneksi bila gagal."""
        key = self._connection_key()
        with _CONNECTION_LOCK:
            connection = _CONNECTION_CACHE.get(key)
            if connection is not None and not _connection_is_alive(connection):
                # Koneksi mati (idle timeout, restart server, jaringan putus).
                # Buang diam-diam lalu sambung ulang di bawah.
                try:
                    connection.close()
                except Exception:
                    pass
                _CONNECTION_CACHE.pop(key, None)
                connection = None
            if connection is None:
                connection = self._open_connection()
                _CONNECTION_CACHE[key] = connection

            try:
                yield connection
                connection.commit()
            except Exception:
                # Setelah error, koneksi bisa tertinggal di state transaksi yang
                # rusak. Rollback lalu buang dari cache supaya pemanggil
                # berikutnya dapat koneksi yang bersih, bukan warisan yang rusak.
                try:
                    connection.rollback()
                except Exception:
                    pass
                try:
                    connection.close()
                except Exception:
                    pass
                _CONNECTION_CACHE.pop(key, None)
                raise

    def placeholder(self) -> str:
        """Simbol placeholder parameter query."""
        return "%s"

    def ensure_schema(self) -> None:
        """Buat dan selaraskan schema beserta seluruh tabel serta kolom; hanya dijalankan sekali per proses."""
        # Cukup sekali per proses. Dulu seluruh DDL dijalankan ulang di SETIAP
        # query -- termasuk tiap baca data -- dan itu yang bikin satu query
        # sederhana makan ~1,8 detik. Ditandai selesai hanya kalau benar-benar
        # sukses, jadi kalau gagal akan dicoba lagi di pemanggilan berikutnya.
        key = self._connection_key()
        if key in _SCHEMA_READY:
            return

        statements = []
        if self.schema != DEFAULT_SCHEMA:
            # Harus lebih dulu: search_path koneksi ini menunjuk schema tersebut,
            # dan CREATE TABLE akan gagal ("no schema has been selected to create
            # in") selama schema-nya belum ada. CREATE SCHEMA sendiri tidak
            # bergantung pada search_path, jadi urutan ini aman.
            statements.append(f"CREATE SCHEMA IF NOT EXISTS {self.schema}")

        statements += [
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id VARCHAR(64) PRIMARY KEY,
                email VARCHAR(255) NOT NULL UNIQUE,
                name VARCHAR(255),
                password VARCHAR(255),
                password_hash VARCHAR(255),
                role VARCHAR(50) NOT NULL DEFAULT 'user',
                birth_date VARCHAR(20),
                gender VARCHAR(20),
                profile JSONB,
                nutrition JSONB,
                auth_provider VARCHAR(20) NOT NULL DEFAULT 'local',
                email_verified BOOLEAN NOT NULL DEFAULT FALSE,
                verification_token VARCHAR(128),
                verification_expires_at TIMESTAMP,
                reset_token VARCHAR(128),
                reset_token_expires_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS calorie_records (
                id VARCHAR(64) PRIMARY KEY,
                user_id VARCHAR(64) NOT NULL,
                email VARCHAR(255) NOT NULL,
                profile JSONB,
                nutrition JSONB,
                created_at TIMESTAMP
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS meal_recommendations (
                id VARCHAR(64) PRIMARY KEY,
                user_id VARCHAR(64) NOT NULL,
                email VARCHAR(255) NOT NULL,
                preference JSONB,
                recommendations JSONB,
                created_at TIMESTAMP
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS workout_recommendations (
                id VARCHAR(64) PRIMARY KEY,
                user_id VARCHAR(64) NOT NULL,
                email VARCHAR(255) NOT NULL,
                filters JSONB,
                recommendations JSONB,
                created_at TIMESTAMP
            )
            """,
        ]
        with self.connection() as connection:
            with connection.cursor() as cursor:
                for statement in statements:
                    cursor.execute(statement)
        _SCHEMA_READY.add(key)

    def load_users(self) -> dict:
        """Baca seluruh baris tabel users menjadi dict {email: data user}."""
        self.ensure_schema()
        with self.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT user_id, email, name, password, password_hash, role, birth_date, gender, profile, nutrition,
                           auth_provider, email_verified, verification_token, verification_expires_at,
                           reset_token, reset_token_expires_at
                    FROM users
                    ORDER BY email
                    """
                )
                rows = cursor.fetchall()
        users = {}
        for row in rows:
            user = dict(row)
            user["profile"] = decode_json(user.get("profile"))
            user["nutrition"] = decode_json(user.get("nutrition"))
            for ts_field in ("verification_expires_at", "reset_token_expires_at"):
                if user.get(ts_field) is not None and hasattr(user[ts_field], "isoformat"):
                    user[ts_field] = user[ts_field].isoformat(timespec="seconds")
            users[user["email"]] = user
        return users

    def save_users(self, users: dict) -> None:
        """Sinkronkan tabel users dengan dict yang diberikan: upsert yang ada, hapus yang tidak lagi terdaftar."""
        self.ensure_schema()
        existing = self.load_users()
        requested_emails = set(users)
        with self.connection() as connection:
            with connection.cursor() as cursor:
                for email in set(existing) - requested_emails:
                    cursor.execute(f"DELETE FROM users WHERE email = {self.placeholder()}", (email,))
                for email, user in users.items():
                    self.upsert_user(cursor, email, user)

    def delete_user(self, email: str, user_id: str | None) -> None:
        """Hapus satu akun beserta seluruh barisnya di ketiga tabel riwayat."""
        self.ensure_schema()
        with self.connection() as connection:
            with connection.cursor() as cursor:
                if user_id:
                    for store in RECORD_STORES:
                        cursor.execute(
                            f"DELETE FROM {record_table(store)} WHERE user_id = {self.placeholder()}",
                            (user_id,),
                        )
                cursor.execute(f"DELETE FROM users WHERE email = {self.placeholder()}", (email,))

    def upsert_user(self, cursor, email: str, user: dict) -> None:
        """Sisipkan atau perbarui satu baris user."""
        payload = {
            "user_id": user.get("user_id") or str(uuid4()),
            "email": user.get("email", email),
            "name": user.get("name"),
            "password": user.get("password"),
            "password_hash": user.get("password_hash"),
            "role": user.get("role", "user"),
            "birth_date": user.get("birth_date"),
            "gender": user.get("gender"),
            "profile": encode_json(user.get("profile")),
            "nutrition": encode_json(user.get("nutrition")),
            "auth_provider": user.get("auth_provider", "local"),
            "email_verified": bool(user.get("email_verified", False)),
            "verification_token": user.get("verification_token"),
            "verification_expires_at": parse_datetime(user.get("verification_expires_at")),
            "reset_token": user.get("reset_token"),
            "reset_token_expires_at": parse_datetime(user.get("reset_token_expires_at")),
        }
        columns = list(payload)
        placeholders = ", ".join([self.placeholder()] * len(columns))
        updates = ", ".join([f"{column}=EXCLUDED.{column}" for column in columns if column != "email"])
        sql = f"""
            INSERT INTO users ({", ".join(columns)})
            VALUES ({placeholders})
            ON CONFLICT (email) DO UPDATE SET {updates}, updated_at=CURRENT_TIMESTAMP
        """
        cursor.execute(sql, tuple(payload.values()))

    def load_records(self, store: str) -> list[dict]:
        """Baca seluruh baris tabel store lalu dekode kolom JSON dan timestamp-nya."""
        self.ensure_schema()
        table = record_table(store)
        columns = record_columns(store)
        with self.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(f"SELECT {', '.join(columns)} FROM {table} ORDER BY created_at")
                rows = cursor.fetchall()
        return [decode_record(store, row) for row in rows]

    def save_records(self, store: str, records: list[dict]) -> None:
        """Kosongkan tabel store lalu isi ulang dengan daftar record yang diberikan."""
        self.ensure_schema()
        table = record_table(store)
        with self.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(f"DELETE FROM {table}")
                for record in records:
                    self.insert_record(cursor, store, record)

    def append_record(self, store: str, record: dict) -> None:
        """Sisipkan satu record baru ke tabel store."""
        self.ensure_schema()
        with self.connection() as connection:
            with connection.cursor() as cursor:
                self.insert_record(cursor, store, record)

    def delete_record(self, store: str, record_id: str) -> None:
        """Hapus satu baris tabel store berdasarkan id."""
        self.ensure_schema()
        table = record_table(store)
        with self.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(f"DELETE FROM {table} WHERE id = {self.placeholder()}", (record_id,))

    def insert_record(self, cursor, store: str, record: dict) -> None:
        """Susun nilai tiap kolom (encode JSON dan timestamp) lalu INSERT satu record."""
        table = record_table(store)
        columns = record_columns(store)
        payload = []
        for column in columns:
            value = record.get(column)
            if column in {"profile", "nutrition", "preference", "recommendations", "filters"}:
                value = encode_json(value)
            elif column == "created_at":
                value = parse_datetime(value)
            payload.append(value)
        placeholders = ", ".join([self.placeholder()] * len(columns))
        cursor.execute(
            f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})",
            tuple(payload),
        )


def record_table(store: str) -> str:
    """Nama tabel SQL untuk sebuah store."""
    return {
        CALORIE_STORE: "calorie_records",
        MEAL_STORE: "meal_recommendations",
        WORKOUT_STORE: "workout_recommendations",
    }[store]


def record_columns(store: str) -> list[str]:
    """Urutan kolom yang dibaca dan ditulis untuk sebuah store."""
    return {
        CALORIE_STORE: ["id", "user_id", "email", "profile", "nutrition", "created_at"],
        MEAL_STORE: ["id", "user_id", "email", "preference", "recommendations", "created_at"],
        WORKOUT_STORE: ["id", "user_id", "email", "filters", "recommendations", "created_at"],
    }[store]


def encode_json(value):
    """Bungkus nilai jadi objek Jsonb siap simpan ke kolom JSONB."""
    data = to_jsonable(value)
    try:
        from psycopg.types.json import Jsonb
    except ImportError:
        return json.dumps(data)
    return Jsonb(data)


def decode_json(value):
    """Kembalikan isi kolom JSON sebagai objek Python, apa pun bentuk mentahnya."""
    if value is None or isinstance(value, (dict, list)):
        return value
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8")
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def decode_record(store: str, row: dict) -> dict:
    """Ubah satu baris hasil query jadi dict record: kolom JSON di-decode, waktu jadi teks ISO."""
    record = dict(row)
    for column in record_columns(store):
        if column in {"profile", "nutrition", "preference", "recommendations", "filters"}:
            record[column] = decode_json(record.get(column))
        elif column == "created_at" and record.get(column) is not None:
            record[column] = record[column].isoformat(timespec="seconds")
    return record


def parse_datetime(value):
    """Ubah teks ISO jadi objek datetime; nilai lain dikembalikan apa adanya."""
    if value is None or not isinstance(value, str):
        return value
    from datetime import datetime

    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return value
