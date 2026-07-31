from __future__ import annotations

import argparse
from pathlib import Path
import sys


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.database import (  # noqa: E402
    RECORD_STORES,
    SQLStore,
    USER_DB_PATH,
    database_driver,
    encode_json,
    load_json,
    parse_datetime,
    record_columns,
    record_table,
    using_sql,
)


RECORD_LABELS = {
    "calorie": "calorie.json",
    "meal": "meal_recommendation.json",
    "workout": "workout_recommendation.json",
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Create app JSON tables and insert database/*.json rows.")
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Delete rows from JSON-backed app tables before importing.",
    )
    args = parser.parse_args()

    if not using_sql():
        raise SystemExit("Set MYSQL=true or POSTGRES=true in .env before running this script.")

    driver = database_driver()
    driver = "postgres" if driver == "postgresql" else driver
    if driver not in {"mysql", "postgres"}:
        raise SystemExit(f"Unsupported database driver: {driver}")

    store = SQLStore()
    store.ensure_schema()

    users = load_json(USER_DB_PATH, {})
    if not isinstance(users, dict):
        users = {}

    records_by_store = {}
    for store_name, path in RECORD_STORES.items():
        records = load_json(path, [])
        records_by_store[store_name] = records if isinstance(records, list) else []

    with store.connection() as connection:
        with connection.cursor() as cursor:
            if args.replace:
                clear_json_tables(cursor)

            import_users(cursor, store, users)
            print(f"users: upserted {len(users)} rows")

            for store_name, records in records_by_store.items():
                import_records(cursor, store, store_name, records)
                print(f"{RECORD_LABELS[store_name]}: upserted {len(records)} rows")


def clear_json_tables(cursor) -> None:
    for store_name in RECORD_STORES:
        cursor.execute(f"DELETE FROM {record_table(store_name)}")
    cursor.execute("DELETE FROM users")


def import_users(cursor, store: SQLStore, users: dict) -> None:
    for email, user in users.items():
        store.upsert_user(cursor, email, user)


def import_records(cursor, store: SQLStore, store_name: str, records: list[dict]) -> None:
    if not records:
        return

    table = record_table(store_name)
    columns = record_columns(store_name)
    placeholder = store.placeholder()
    column_sql = ", ".join(columns)
    placeholder_sql = ", ".join([placeholder] * len(columns))
    update_columns = [column for column in columns if column != "id"]

    if store.driver == "mysql":
        assignments = ", ".join([f"{column}=VALUES({column})" for column in update_columns])
        conflict_sql = f" ON DUPLICATE KEY UPDATE {assignments}"
    else:
        assignments = ", ".join([f"{column}=EXCLUDED.{column}" for column in update_columns])
        conflict_sql = f" ON CONFLICT (id) DO UPDATE SET {assignments}"

    rows = [record_payload(store, store_name, record) for record in records]
    cursor.executemany(
        f"INSERT INTO {table} ({column_sql}) VALUES ({placeholder_sql}){conflict_sql}",
        rows,
    )


def record_payload(store: SQLStore, store_name: str, record: dict) -> tuple:
    payload = []
    for column in record_columns(store_name):
        value = record.get(column)
        if column in {"profile", "nutrition", "preference", "recommendations", "filters"}:
            value = encode_json(value, store.driver)
        elif column == "created_at":
            value = parse_datetime(value)
        payload.append(value)
    return tuple(payload)


if __name__ == "__main__":
    main()
