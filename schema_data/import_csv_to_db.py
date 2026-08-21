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

from src.database import SQLStore  # noqa: E402


DATA_DIR = ROOT_DIR / "data"
# Dulu `nutrition.csv` dicoba dulu lalu jatuh ke `food_nutrition.csv`. Keduanya
# berisi data yang sama persis (1.346 x 7), dan punya dua berkas kembar membuat
# "dataset penelitian yang mana?" jadi pertanyaan yang tidak perlu ada. Salinan
# gandanya dihapus; tinggal satu sumber.
FOOD_NUTRITION_CSV = DATA_DIR / "food_nutrition.csv"


TABLES = {
    "food_nutrition": {
        "csv": FOOD_NUTRITION_CSV,
        "columns": ["id", "calories", "proteins", "fat", "carbohydrate", "name", "image"],
        "primary_key": "id",
        "create": """
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
        "create": """
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
        "create": """
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
}


def main() -> None:
    """Buat tabel dataset lalu isi dari berkas CSV; secara bawaan tabel dikosongkan dulu."""
    parser = argparse.ArgumentParser(description="Create dataset tables and insert CSV rows.")
    parser.add_argument(
        "--append",
        action="store_true",
        help="Append rows instead of truncating each dataset table before insert.",
    )
    args = parser.parse_args()

    store = SQLStore()
    with store.connection() as connection:
        with connection.cursor() as cursor:
            for table_name, spec in TABLES.items():
                create_table(cursor, spec)
                if not args.append:
                    truncate_table(cursor, table_name)
                rows = load_csv_rows(spec)
                insert_rows(cursor, table_name, spec, rows, store.placeholder())
                action = "upserted/appended" if args.append else "inserted"
                print(f"{table_name}: {action} {len(rows)} rows")


def create_table(cursor, spec: dict) -> None:
    """Jalankan DDL CREATE TABLE untuk satu tabel dataset."""
    cursor.execute(spec["create"])


def truncate_table(cursor, table_name: str) -> None:
    """Kosongkan satu tabel sebelum diisi ulang, sekaligus mereset urutan id-nya."""
    cursor.execute(f"TRUNCATE TABLE {table_name} RESTART IDENTITY")


def load_csv_rows(spec: dict) -> list[tuple]:
    """Baca CSV satu tabel, samakan nama kolom dan urutannya, lalu ubah jadi daftar tuple."""
    df = pd.read_csv(spec["csv"])
    if "rename" in spec:
        df = df.rename(columns=spec["rename"])
    if "index_column" in spec:
        df.insert(0, spec["index_column"], range(1, len(df) + 1))
    df = df[spec["columns"]]
    df = df.astype(object).where(pd.notna(df), None)
    return [tuple(row) for row in df.itertuples(index=False, name=None)]


def insert_rows(cursor, table_name: str, spec: dict, rows: list[tuple], placeholder: str) -> None:
    """Sisipkan seluruh baris sekaligus; bila ada kunci primer, baris lama diperbarui bukan digandakan."""
    if not rows:
        return
    columns = spec["columns"]
    column_sql = ", ".join(columns)
    placeholder_sql = ", ".join([placeholder] * len(columns))
    primary_key = spec.get("primary_key")
    conflict_sql = ""

    if primary_key:
        update_columns = [column for column in columns if column != primary_key]
        assignments = ", ".join([f"{column}=EXCLUDED.{column}" for column in update_columns])
        conflict_sql = f" ON CONFLICT ({primary_key}) DO UPDATE SET {assignments}"

    cursor.executemany(
        f"INSERT INTO {table_name} ({column_sql}) VALUES ({placeholder_sql}){conflict_sql}",
        rows,
    )


if __name__ == "__main__":
    main()
