# running
# python3 schema_data/import_csv_to_db.py --append

from __future__ import annotations

import argparse
from pathlib import Path
import sys

import pandas as pd


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.database import SQLStore, database_driver, using_sql  # noqa: E402


DATA_DIR = ROOT_DIR / "data"
FOOD_NUTRITION_CSV = DATA_DIR / "nutrition.csv"
if not FOOD_NUTRITION_CSV.exists():
    FOOD_NUTRITION_CSV = DATA_DIR / "food_nutrition.csv"


TABLES = {
    "food_nutrition": {
        "csv": FOOD_NUTRITION_CSV,
        "columns": ["id", "calories", "proteins", "fat", "carbohydrate", "name", "image"],
        "primary_key": "id",
        "create": {
            "mysql": """
                CREATE TABLE IF NOT EXISTS food_nutrition (
                    id INT PRIMARY KEY,
                    calories DOUBLE,
                    proteins DOUBLE,
                    fat DOUBLE,
                    carbohydrate DOUBLE,
                    name VARCHAR(255),
                    image TEXT
                )
            """,
            "postgres": """
                CREATE TABLE IF NOT EXISTS food_nutrition (
                    id INTEGER PRIMARY KEY,
                    calories DOUBLE PRECISION,
                    proteins DOUBLE PRECISION,
                    fat DOUBLE PRECISION,
                    carbohydrate DOUBLE PRECISION,
                    name VARCHAR(255),
                    image TEXT
                )
            """,
        },
    },
    "gym_members": {
        "csv": DATA_DIR / "gym_members.csv",
        "index_column": "member_id",
        "primary_key": "member_id",
        "columns": [
            "member_id",
            "age",
            "gender",
            "weight_kg",
            "height_m",
            "max_bpm",
            "avg_bpm",
            "resting_bpm",
            "session_duration_hours",
            "calories_burned",
            "workout_type",
            "fat_percentage",
            "water_intake_liters",
            "workout_frequency_days_week",
            "experience_level",
            "bmi",
            "activity_level",
            "fitness_goal",
        ],
        "rename": {
            "Age": "age",
            "Gender": "gender",
            "Weight (kg)": "weight_kg",
            "Height (m)": "height_m",
            "Max_BPM": "max_bpm",
            "Avg_BPM": "avg_bpm",
            "Resting_BPM": "resting_bpm",
            "Session_Duration (hours)": "session_duration_hours",
            "Calories_Burned": "calories_burned",
            "Workout_Type": "workout_type",
            "Fat_Percentage": "fat_percentage",
            "Water_Intake (liters)": "water_intake_liters",
            "Workout_Frequency (days/week)": "workout_frequency_days_week",
            "Experience_Level": "experience_level",
            "BMI": "bmi",
            "Activity_Level": "activity_level",
            "Fitness_Goal": "fitness_goal",
        },
        "create": {
            "mysql": """
                CREATE TABLE IF NOT EXISTS gym_members (
                    member_id INT AUTO_INCREMENT PRIMARY KEY,
                    age INT,
                    gender VARCHAR(20),
                    weight_kg DOUBLE,
                    height_m DOUBLE,
                    max_bpm INT,
                    avg_bpm INT,
                    resting_bpm INT,
                    session_duration_hours DOUBLE,
                    calories_burned DOUBLE,
                    workout_type VARCHAR(100),
                    fat_percentage DOUBLE,
                    water_intake_liters DOUBLE,
                    workout_frequency_days_week INT,
                    experience_level INT,
                    bmi DOUBLE,
                    activity_level VARCHAR(50),
                    fitness_goal VARCHAR(50)
                )
            """,
            "postgres": """
                CREATE TABLE IF NOT EXISTS gym_members (
                    member_id SERIAL PRIMARY KEY,
                    age INTEGER,
                    gender VARCHAR(20),
                    weight_kg DOUBLE PRECISION,
                    height_m DOUBLE PRECISION,
                    max_bpm INTEGER,
                    avg_bpm INTEGER,
                    resting_bpm INTEGER,
                    session_duration_hours DOUBLE PRECISION,
                    calories_burned DOUBLE PRECISION,
                    workout_type VARCHAR(100),
                    fat_percentage DOUBLE PRECISION,
                    water_intake_liters DOUBLE PRECISION,
                    workout_frequency_days_week INTEGER,
                    experience_level INTEGER,
                    bmi DOUBLE PRECISION,
                    activity_level VARCHAR(50),
                    fitness_goal VARCHAR(50)
                )
            """,
        },
    },
    "training_program": {
        "csv": DATA_DIR / "training_program.csv",
        "primary_key": "program_id",
        "columns": [
            "program_id",
            "title",
            "description",
            "type",
            "body_part",
            "equipment",
            "level",
            "rating",
            "rating_desc",
        ],
        "rename": {
            "Unnamed: 0": "program_id",
            "Title": "title",
            "Desc": "description",
            "Type": "type",
            "BodyPart": "body_part",
            "Equipment": "equipment",
            "Level": "level",
            "Rating": "rating",
            "RatingDesc": "rating_desc",
        },
        "create": {
            "mysql": """
                CREATE TABLE IF NOT EXISTS training_program (
                    program_id INT PRIMARY KEY,
                    title VARCHAR(255),
                    description TEXT,
                    type VARCHAR(100),
                    body_part VARCHAR(100),
                    equipment VARCHAR(100),
                    level VARCHAR(50),
                    rating DOUBLE,
                    rating_desc TEXT
                )
            """,
            "postgres": """
                CREATE TABLE IF NOT EXISTS training_program (
                    program_id INTEGER PRIMARY KEY,
                    title VARCHAR(255),
                    description TEXT,
                    type VARCHAR(100),
                    body_part VARCHAR(100),
                    equipment VARCHAR(100),
                    level VARCHAR(50),
                    rating DOUBLE PRECISION,
                    rating_desc TEXT
                )
            """,
        },
    },
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Create dataset tables and insert CSV rows.")
    parser.add_argument(
        "--append",
        action="store_true",
        help="Append rows instead of truncating each dataset table before insert.",
    )
    args = parser.parse_args()

    if not using_sql():
        raise SystemExit("Set MYSQL=true or POSTGRES=true in .env before running this script.")

    driver = database_driver()
    driver = "postgres" if driver == "postgresql" else driver
    if driver not in {"mysql", "postgres"}:
        raise SystemExit(f"Unsupported database driver: {driver}")

    store = SQLStore()
    with store.connection() as connection:
        with connection.cursor() as cursor:
            for table_name, spec in TABLES.items():
                create_table(cursor, spec, driver)
                if not args.append:
                    truncate_table(cursor, table_name, driver)
                rows = load_csv_rows(spec)
                insert_rows(cursor, table_name, spec, rows, store.placeholder(), driver)
                action = "upserted/appended" if args.append else "inserted"
                print(f"{table_name}: {action} {len(rows)} rows")


def create_table(cursor, spec: dict, driver: str) -> None:
    cursor.execute(spec["create"][driver])


def truncate_table(cursor, table_name: str, driver: str) -> None:
    if driver == "postgres":
        cursor.execute(f"TRUNCATE TABLE {table_name} RESTART IDENTITY")
    else:
        cursor.execute(f"TRUNCATE TABLE {table_name}")


def load_csv_rows(spec: dict) -> list[tuple]:
    df = pd.read_csv(spec["csv"])
    if "rename" in spec:
        df = df.rename(columns=spec["rename"])
    if "index_column" in spec:
        df.insert(0, spec["index_column"], range(1, len(df) + 1))
    df = df[spec["columns"]]
    df = df.astype(object).where(pd.notna(df), None)
    return [tuple(row) for row in df.itertuples(index=False, name=None)]


def insert_rows(cursor, table_name: str, spec: dict, rows: list[tuple], placeholder: str, driver: str) -> None:
    if not rows:
        return
    columns = spec["columns"]
    column_sql = ", ".join(columns)
    placeholder_sql = ", ".join([placeholder] * len(columns))
    primary_key = spec.get("primary_key")
    conflict_sql = ""

    if primary_key:
        update_columns = [column for column in columns if column != primary_key]
        if driver == "mysql":
            assignments = ", ".join([f"{column}=VALUES({column})" for column in update_columns])
            conflict_sql = f" ON DUPLICATE KEY UPDATE {assignments}"
        else:
            assignments = ", ".join([f"{column}=EXCLUDED.{column}" for column in update_columns])
            conflict_sql = f" ON CONFLICT ({primary_key}) DO UPDATE SET {assignments}"

    cursor.executemany(
        f"INSERT INTO {table_name} ({column_sql}) VALUES ({placeholder_sql}){conflict_sql}",
        rows,
    )


if __name__ == "__main__":
    main()
