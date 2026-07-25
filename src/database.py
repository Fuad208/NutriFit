from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
from typing import Any
from uuid import uuid4

import pandas as pd


USER_DB_PATH = Path("database/user.json")
CALORIE_DB_PATH = Path("database/calorie.json")
MEAL_DB_PATH = Path("database/meal_recommendation.json")
WORKOUT_DB_PATH = Path("database/workout_recommendation.json")


RECORD_STORES = {
    "calorie": CALORIE_DB_PATH,
    "meal": MEAL_DB_PATH,
    "workout": WORKOUT_DB_PATH,
}


def load_env(path: Path = Path(".env")) -> None:
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


def env_bool(name: str, default: bool = False) -> bool:
    value = getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def getenv(name: str, default: str | None = None) -> str | None:
    return os.getenv(name, os.getenv(name.lower(), default))


def database_driver() -> str:
    if env_bool("MYSQL", env_bool("MYSQL_ENABLED", False)):
        return "mysql"
    if env_bool("POSTGRES", env_bool("POSTGRES_ENABLED", False)) or env_bool("POSTGRESQL", False):
        return "postgres"
    return (getenv("DATABASE_DRIVER", "json") or "json").strip().lower()


def using_sql() -> bool:
    return database_driver() in {"mysql", "postgres", "postgresql"}


def ensure_database() -> None:
    if using_sql():
        SQLStore().ensure_schema()
    else:
        ensure_json_files()


def load_users() -> dict:
    users = SQLStore().load_users() if using_sql() else load_json(USER_DB_PATH, {})
    if not isinstance(users, dict):
        return {}
    return users


def save_users(users: dict) -> None:
    if using_sql():
        SQLStore().save_users(users)
    else:
        save_json(USER_DB_PATH, users)


def load_records(store: str | Path) -> list[dict]:
    if using_sql():
        return SQLStore().load_records(normalize_store(store))
    records = load_json(json_path_for(store), [])
    return records if isinstance(records, list) else []


def save_records(store: str | Path, records: list[dict]) -> None:
    if using_sql():
        SQLStore().save_records(normalize_store(store), records)
    else:
        save_json(json_path_for(store), records)


def append_record(store: str | Path, record: dict) -> None:
    if using_sql():
        SQLStore().append_record(normalize_store(store), record)
    else:
        records = load_records(store)
        records.append(record)
        save_records(store, records)


def delete_record(store: str | Path, record_id: str) -> None:
    if using_sql():
        SQLStore().delete_record(normalize_store(store), record_id)
    else:
        records = [record for record in load_records(store) if record.get("id") != record_id]
        save_records(store, records)


def delete_user_and_related_data(email: str) -> None:
    users = load_users()
    user = users.get(email)
    if not user:
        return
    user_id = user.get("user_id")
    users.pop(email)
    save_users(users)
    for store in RECORD_STORES:
        records = [record for record in load_records(store) if record.get("user_id") != user_id]
        save_records(store, records)


def latest_user_record(store: str | Path, user_id: str | None) -> dict | None:
    if not user_id:
        return None
    records = [record for record in load_records(store) if record.get("user_id") == user_id]
    if not records:
        return None
    return sorted(records, key=lambda record: record.get("created_at", ""))[-1]


def to_jsonable(value: Any):
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


def ensure_json_files() -> None:
    USER_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    for path, default in [
        (USER_DB_PATH, {}),
        (CALORIE_DB_PATH, []),
        (MEAL_DB_PATH, []),
        (WORKOUT_DB_PATH, []),
    ]:
        if not path.exists():
            save_json(path, default)


def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except json.JSONDecodeError:
        return default
    return data


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(to_jsonable(data), file, indent=2)


def normalize_store(store: str | Path) -> str:
    if isinstance(store, Path):
        for name, path in RECORD_STORES.items():
            if path == store:
                return name
        raise ValueError(f"Unknown record store path: {store}")
    store_name = store.strip().lower()
    if store_name not in RECORD_STORES:
        raise ValueError(f"Unknown record store: {store}")
    return store_name


def json_path_for(store: str | Path) -> Path:
    if isinstance(store, Path):
        return store
    return RECORD_STORES[normalize_store(store)]


class SQLStore:
    def __init__(self) -> None:
        driver = database_driver()
        self.driver = "postgres" if driver == "postgresql" else driver
        self.config = self._config()

    def _config(self) -> dict:
        if self.driver == "mysql":
            return {
                "host": getenv("MYSQL_HOST", "127.0.0.1"),
                "port": int(getenv("MYSQL_PORT", "3306") or "3306"),
                "user": getenv("MYSQL_USER", "root"),
                "password": getenv("MYSQL_PASSWORD", ""),
                "database": getenv("MYSQL_DATABASE", ""),
            }
        return {
            "host": getenv("POSTGRES_HOST", "127.0.0.1"),
            "port": int(getenv("POSTGRES_PORT", "5432") or "5432"),
            "user": getenv("POSTGRES_USER", "postgres"),
            "password": getenv("POSTGRES_PASSWORD", ""),
            "database": getenv("POSTGRES_DATABASE", getenv("POSTGRES_DB", "")),
        }

    @contextmanager
    def connection(self):
        if self.driver == "mysql":
            import pymysql

            if not self.config["database"]:
                raise ValueError("MYSQL_DATABASE must be set when MYSQL=true.")
            self.ensure_mysql_database(pymysql)
            connection = pymysql.connect(
                host=self.config["host"],
                port=self.config["port"],
                user=self.config["user"],
                password=self.config["password"],
                database=self.config["database"] or None,
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor,
                autocommit=False,
            )
        else:
            import psycopg
            from psycopg.rows import dict_row

            connection = psycopg.connect(
                host=self.config["host"],
                port=self.config["port"],
                user=self.config["user"],
                password=self.config["password"],
                dbname=self.config["database"] or None,
                row_factory=dict_row,
            )
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def ensure_mysql_database(self, pymysql_module) -> None:
        database = str(self.config["database"])
        if not re.match(r"^[A-Za-z0-9_]+$", database):
            raise ValueError("MYSQL_DATABASE may only contain letters, numbers, and underscores.")
        connection = pymysql_module.connect(
            host=self.config["host"],
            port=self.config["port"],
            user=self.config["user"],
            password=self.config["password"],
            charset="utf8mb4",
            cursorclass=pymysql_module.cursors.DictCursor,
            autocommit=True,
        )
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"CREATE DATABASE IF NOT EXISTS `{database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                )
        finally:
            connection.close()

    def placeholder(self) -> str:
        return "%s"

    def json_type(self) -> str:
        return "JSON" if self.driver == "mysql" else "JSONB"

    def ensure_schema(self) -> None:
        json_type = self.json_type()
        timestamp_type = "DATETIME" if self.driver == "mysql" else "TIMESTAMP"
        statements = [
            """
            CREATE TABLE IF NOT EXISTS app_metadata (
                meta_key VARCHAR(100) PRIMARY KEY,
                meta_value VARCHAR(255)
            )
            """,
            f"""
            CREATE TABLE IF NOT EXISTS users (
                user_id VARCHAR(64) PRIMARY KEY,
                email VARCHAR(255) NOT NULL UNIQUE,
                name VARCHAR(255),
                password VARCHAR(255),
                password_hash VARCHAR(255),
                role VARCHAR(50) NOT NULL DEFAULT 'user',
                birth_date VARCHAR(20),
                gender VARCHAR(20),
                profile {json_type},
                nutrition {json_type},
                created_at {timestamp_type} DEFAULT CURRENT_TIMESTAMP,
                updated_at {timestamp_type} DEFAULT CURRENT_TIMESTAMP
            )
            """,
            f"""
            CREATE TABLE IF NOT EXISTS calorie_records (
                id VARCHAR(64) PRIMARY KEY,
                user_id VARCHAR(64) NOT NULL,
                email VARCHAR(255) NOT NULL,
                profile {json_type},
                nutrition {json_type},
                created_at {timestamp_type}
            )
            """,
            f"""
            CREATE TABLE IF NOT EXISTS meal_recommendations (
                id VARCHAR(64) PRIMARY KEY,
                user_id VARCHAR(64) NOT NULL,
                email VARCHAR(255) NOT NULL,
                preference {json_type},
                recommendations {json_type},
                created_at {timestamp_type}
            )
            """,
            f"""
            CREATE TABLE IF NOT EXISTS workout_recommendations (
                id VARCHAR(64) PRIMARY KEY,
                user_id VARCHAR(64) NOT NULL,
                email VARCHAR(255) NOT NULL,
                filters {json_type},
                recommendations {json_type},
                created_at {timestamp_type}
            )
            """,
        ]
        with self.connection() as connection:
            with connection.cursor() as cursor:
                for statement in statements:
                    cursor.execute(statement)
        self.seed_from_json_if_empty()

    def seed_from_json_if_empty(self) -> None:
        with self.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT meta_value FROM app_metadata WHERE meta_key = {self.placeholder()}",
                    ("json_seeded",),
                )
                if cursor.fetchone():
                    return
                if not any(path.exists() for path in RECORD_STORES.values()) and not USER_DB_PATH.exists():
                    self.mark_seeded(cursor)
                    return

                cursor.execute("SELECT COUNT(*) AS total FROM users")
                users_total = count_result(cursor.fetchone())
                if users_total == 0:
                    users = load_json(USER_DB_PATH, {})
                    if isinstance(users, dict):
                        for email, user in users.items():
                            self.upsert_user(cursor, email, user)

                for store in RECORD_STORES:
                    table = record_table(store)
                    cursor.execute(f"SELECT COUNT(*) AS total FROM {table}")
                    if count_result(cursor.fetchone()) > 0:
                        continue
                    records = load_json(RECORD_STORES[store], [])
                    if isinstance(records, list):
                        for record in records:
                            self.insert_record(cursor, store, record)
                self.mark_seeded(cursor)

    def mark_seeded(self, cursor) -> None:
        if self.driver == "mysql":
            cursor.execute(
                """
                INSERT INTO app_metadata (meta_key, meta_value)
                VALUES (%s, %s)
                ON DUPLICATE KEY UPDATE meta_value = VALUES(meta_value)
                """,
                ("json_seeded", "true"),
            )
        else:
            cursor.execute(
                """
                INSERT INTO app_metadata (meta_key, meta_value)
                VALUES (%s, %s)
                ON CONFLICT (meta_key) DO UPDATE SET meta_value = EXCLUDED.meta_value
                """,
                ("json_seeded", "true"),
            )

    def load_users(self) -> dict:
        self.ensure_schema()
        with self.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT user_id, email, name, password, password_hash, role, birth_date, gender, profile, nutrition
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
            users[user["email"]] = user
        return users

    def save_users(self, users: dict) -> None:
        self.ensure_schema()
        existing = self.load_users()
        requested_emails = set(users)
        with self.connection() as connection:
            with connection.cursor() as cursor:
                for email in set(existing) - requested_emails:
                    cursor.execute(f"DELETE FROM users WHERE email = {self.placeholder()}", (email,))
                for email, user in users.items():
                    self.upsert_user(cursor, email, user)

    def upsert_user(self, cursor, email: str, user: dict) -> None:
        payload = {
            "user_id": user.get("user_id") or str(uuid4()),
            "email": user.get("email", email),
            "name": user.get("name"),
            "password": user.get("password"),
            "password_hash": user.get("password_hash"),
            "role": user.get("role", "user"),
            "birth_date": user.get("birth_date"),
            "gender": user.get("gender"),
            "profile": encode_json(user.get("profile"), self.driver),
            "nutrition": encode_json(user.get("nutrition"), self.driver),
        }
        columns = list(payload)
        placeholders = ", ".join([self.placeholder()] * len(columns))
        if self.driver == "mysql":
            updates = ", ".join([f"{column}=VALUES({column})" for column in columns if column != "user_id"])
            sql = f"""
                INSERT INTO users ({", ".join(columns)})
                VALUES ({placeholders})
                ON DUPLICATE KEY UPDATE {updates}, updated_at=CURRENT_TIMESTAMP
            """
        else:
            updates = ", ".join([f"{column}=EXCLUDED.{column}" for column in columns if column != "email"])
            sql = f"""
                INSERT INTO users ({", ".join(columns)})
                VALUES ({placeholders})
                ON CONFLICT (email) DO UPDATE SET {updates}, updated_at=CURRENT_TIMESTAMP
            """
        cursor.execute(sql, tuple(payload.values()))

    def load_records(self, store: str) -> list[dict]:
        self.ensure_schema()
        table = record_table(store)
        columns = record_columns(store)
        with self.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(f"SELECT {', '.join(columns)} FROM {table} ORDER BY created_at")
                rows = cursor.fetchall()
        return [decode_record(store, row) for row in rows]

    def save_records(self, store: str, records: list[dict]) -> None:
        self.ensure_schema()
        table = record_table(store)
        with self.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(f"DELETE FROM {table}")
                for record in records:
                    self.insert_record(cursor, store, record)

    def append_record(self, store: str, record: dict) -> None:
        self.ensure_schema()
        with self.connection() as connection:
            with connection.cursor() as cursor:
                self.insert_record(cursor, store, record)

    def delete_record(self, store: str, record_id: str) -> None:
        self.ensure_schema()
        table = record_table(store)
        with self.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(f"DELETE FROM {table} WHERE id = {self.placeholder()}", (record_id,))

    def insert_record(self, cursor, store: str, record: dict) -> None:
        table = record_table(store)
        columns = record_columns(store)
        payload = []
        for column in columns:
            value = record.get(column)
            if column in {"profile", "nutrition", "preference", "recommendations", "filters"}:
                value = encode_json(value, self.driver)
            elif column == "created_at":
                value = parse_datetime(value)
            payload.append(value)
        placeholders = ", ".join([self.placeholder()] * len(columns))
        cursor.execute(
            f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})",
            tuple(payload),
        )


def record_table(store: str) -> str:
    return {
        "calorie": "calorie_records",
        "meal": "meal_recommendations",
        "workout": "workout_recommendations",
    }[store]


def record_columns(store: str) -> list[str]:
    return {
        "calorie": ["id", "user_id", "email", "profile", "nutrition", "created_at"],
        "meal": ["id", "user_id", "email", "preference", "recommendations", "created_at"],
        "workout": ["id", "user_id", "email", "filters", "recommendations", "created_at"],
    }[store]


def encode_json(value, driver: str):
    data = to_jsonable(value)
    if driver == "postgres":
        try:
            from psycopg.types.json import Jsonb
        except ImportError:
            return json.dumps(data)
        return Jsonb(data)
    return json.dumps(data)


def decode_json(value):
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
    record = dict(row)
    for column in record_columns(store):
        if column in {"profile", "nutrition", "preference", "recommendations", "filters"}:
            record[column] = decode_json(record.get(column))
        elif column == "created_at" and record.get(column) is not None:
            record[column] = record[column].isoformat(timespec="seconds")
    return record


def count_result(row: dict | tuple | None) -> int:
    if not row:
        return 0
    if isinstance(row, dict):
        return int(row.get("total", 0))
    return int(row[0])


def parse_datetime(value):
    if value is None or not isinstance(value, str):
        return value
    from datetime import datetime

    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return value
