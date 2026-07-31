from __future__ import annotations

from dataclasses import asdict
import os
from typing import Iterable

os.environ.setdefault("LOKY_MAX_CPU_COUNT", "4")

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import silhouette_score
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.preprocessing import MinMaxScaler

from .database import SQLStore, using_sql
from .nutrition import NutritionResult


MEAL_DISTRIBUTION = {
    "Breakfast": 0.25,
    "Lunch": 0.35,
    "Snack": 0.10,
    "Dinner": 0.30,
}

MEAL_TEMPLATE = {
    "Breakfast": ["A", "B"],
    "Lunch": ["A", "B", "B", "C"],
    "Snack": ["C"],
    "Dinner": ["B", "C"],
}

LEVEL_ALLOWLIST = {
    "Beginner": {"Beginner"},
    "Intermediate": {"Beginner", "Intermediate"},
    "Expert": {"Beginner", "Intermediate", "Expert"},
}

TRAINING_PARAMETERS = {
    ("Lose Weight", "Beginner"): {"sets": 3, "reps": 15, "rest_seconds": 60},
    ("Lose Weight", "Intermediate"): {"sets": 4, "reps": 15, "rest_seconds": 60},
    ("Lose Weight", "Expert"): {"sets": 4, "reps": 20, "rest_seconds": 45},
    ("Gain Weight", "Beginner"): {"sets": 3, "reps": 10, "rest_seconds": 90},
    ("Gain Weight", "Intermediate"): {"sets": 4, "reps": 10, "rest_seconds": 90},
    ("Gain Weight", "Expert"): {"sets": 4, "reps": 12, "rest_seconds": 90},
    ("Maintain Weight", "Beginner"): {"sets": 3, "reps": 12, "rest_seconds": 75},
    ("Maintain Weight", "Intermediate"): {"sets": 3, "reps": 12, "rest_seconds": 75},
    ("Maintain Weight", "Expert"): {"sets": 4, "reps": 12, "rest_seconds": 75},
}


def normalize_goal(goal: str) -> str:
    mapping = {
        "Weight Loss": "Lose Weight",
        "Lose Weight": "Lose Weight",
        "Weight Gain": "Gain Weight",
        "Gain Weight": "Gain Weight",
        "Weight Maintenance": "Maintain Weight",
        "Maintain Weight": "Maintain Weight",
    }
    return mapping.get(goal, goal)


def normalize_experience_level(level: str | int) -> str:
    mapping = {
        1: "Beginner",
        2: "Intermediate",
        3: "Expert",
        "1": "Beginner",
        "2": "Intermediate",
        "3": "Expert",
        "Beginner": "Beginner",
        "Intermediate": "Intermediate",
        "Expert": "Expert",
    }
    return mapping.get(level, "Beginner")


def load_datasets() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    members, foods, exercises = load_dataset_tables()
    return clean_members(members), prepare_foods(foods), prepare_exercises(exercises)


def load_dataset_tables() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if not using_sql():
        raise RuntimeError("Dataset source is database-only. Set MYSQL=true or POSTGRES=true in .env.")

    store = SQLStore()
    with store.connection() as connection:
        with connection.cursor() as cursor:
            members = fetch_dataframe(
                cursor,
                """
                SELECT
                    age AS `Age`,
                    gender AS `Gender`,
                    weight_kg AS `Weight (kg)`,
                    height_m AS `Height (m)`,
                    max_bpm AS `Max_BPM`,
                    avg_bpm AS `Avg_BPM`,
                    resting_bpm AS `Resting_BPM`,
                    session_duration_hours AS `Session_Duration (hours)`,
                    calories_burned AS `Calories_Burned`,
                    workout_type AS `Workout_Type`,
                    fat_percentage AS `Fat_Percentage`,
                    water_intake_liters AS `Water_Intake (liters)`,
                    workout_frequency_days_week AS `Workout_Frequency (days/week)`,
                    experience_level AS `Experience_Level`,
                    bmi AS `BMI`,
                    activity_level AS `Activity_Level`,
                    fitness_goal AS `Fitness_Goal`
                FROM gym_members
                ORDER BY member_id
                """,
                store.driver,
            )
            foods = fetch_dataframe(
                cursor,
                """
                SELECT id, calories, proteins, fat, carbohydrate, name, image
                FROM food_nutrition
                ORDER BY id
                """,
                store.driver,
            )
            exercises = fetch_dataframe(
                cursor,
                """
                SELECT
                    program_id AS `Unnamed: 0`,
                    title AS `Title`,
                    description AS `Desc`,
                    type AS `Type`,
                    body_part AS `BodyPart`,
                    equipment AS `Equipment`,
                    level AS `Level`,
                    rating AS `Rating`,
                    rating_desc AS `RatingDesc`
                FROM training_program
                ORDER BY program_id
                """,
                store.driver,
            )

    ensure_dataset_rows(members, foods, exercises)
    return members, foods, exercises


def fetch_dataframe(cursor, query: str, driver: str) -> pd.DataFrame:
    if driver == "postgres":
        query = query.replace("`", '"')
    try:
        cursor.execute(query)
    except Exception as exc:
        raise RuntimeError("Dataset tables are not ready. Run python3 schema_data/import_csv_to_db.py first.") from exc
    return pd.DataFrame(cursor.fetchall())


def ensure_dataset_rows(members: pd.DataFrame, foods: pd.DataFrame, exercises: pd.DataFrame) -> None:
    empty_tables = []
    if members.empty:
        empty_tables.append("gym_members")
    if foods.empty:
        empty_tables.append("food_nutrition")
    if exercises.empty:
        empty_tables.append("training_program")
    if empty_tables:
        tables = ", ".join(empty_tables)
        raise RuntimeError(f"Dataset table(s) empty: {tables}. Run python3 schema_data/import_csv_to_db.py first.")


def clean_members(df: pd.DataFrame) -> pd.DataFrame:
    cleaned = df.copy()
    cleaned["Experience_Label"] = cleaned["Experience_Level"].apply(normalize_experience_level)
    cleaned["Fitness_Goal"] = cleaned["Fitness_Goal"].apply(normalize_goal)
    cleaned = cleaned.dropna(subset=["Age", "Gender", "Weight (kg)", "Height (m)", "BMI"])
    cleaned["User_Cluster"] = assign_member_clusters(cleaned)
    return cleaned


def assign_member_clusters(members: pd.DataFrame, n_clusters: int = 5) -> pd.Series:
    numeric_columns = ["Age", "Weight (kg)", "Height (m)", "BMI"]
    categorical_columns = ["Gender", "Activity_Level", "Experience_Label", "Fitness_Goal"]
    numeric, categorical, scaler = member_feature_matrices(members, numeric_columns, categorical_columns)
    labels, _, _ = fit_kprototypes(numeric, categorical, n_clusters=min(n_clusters, len(members)))
    return pd.Series(labels + 1, index=members.index)


def prepare_foods(df: pd.DataFrame) -> pd.DataFrame:
    foods = df.copy()
    foods = foods.dropna(subset=["name", "calories", "proteins", "fat", "carbohydrate"])
    for column in ["calories", "proteins", "fat", "carbohydrate"]:
        foods[column] = pd.to_numeric(foods[column], errors="coerce").fillna(0)
    foods = foods[foods["calories"] > 0].reset_index(drop=True)
    foods["Food_Cluster"] = assign_food_clusters(foods)
    foods["CBF_Text"] = (
        foods["name"].fillna("")
        + " calories "
        + foods["calories"].round().astype(str)
        + " protein "
        + foods["proteins"].round().astype(str)
        + " fat "
        + foods["fat"].round().astype(str)
        + " carbohydrate "
        + foods["carbohydrate"].round().astype(str)
        + " cluster "
        + foods["Food_Cluster"]
    )
    return foods


def assign_food_clusters(foods: pd.DataFrame) -> pd.Series:
    features = foods[["calories", "proteins", "fat", "carbohydrate"]]
    scaled = MinMaxScaler().fit_transform(features)
    labels = KMeans(n_clusters=3, random_state=42, n_init=10).fit_predict(scaled)
    clustered = foods.assign(_cluster=labels)
    summaries = clustered.groupby("_cluster")[["calories", "proteins", "fat", "carbohydrate"]].mean()

    low_cal_cluster = summaries["calories"].idxmin()
    remaining_for_carb = [cluster for cluster in summaries.index if cluster != low_cal_cluster]
    carb_cluster = summaries.loc[remaining_for_carb, "carbohydrate"].idxmax() if remaining_for_carb else low_cal_cluster
    remaining = [cluster for cluster in summaries.index if cluster not in {carb_cluster, low_cal_cluster}]
    protein_cluster = summaries.loc[remaining, "proteins"].idxmax() if remaining else carb_cluster

    cluster_map = {
        carb_cluster: "A",
        protein_cluster: "B",
        low_cal_cluster: "C",
    }
    return pd.Series(labels).map(cluster_map).fillna("B")


def prepare_exercises(df: pd.DataFrame) -> pd.DataFrame:
    exercises = df.copy()
    if "Unnamed: 0" in exercises.columns:
        exercises = exercises.rename(columns={"Unnamed: 0": "Program_ID"})
    required = ["Title", "Desc", "Type", "BodyPart", "Equipment", "Level"]
    exercises = exercises.dropna(subset=required).reset_index(drop=True)
    for column in required:
        exercises[column] = exercises[column].astype(str)
    exercises["Exercise_Cluster"] = assign_exercise_clusters(exercises)
    exercises["CBF_Text"] = (
        exercises["Title"]
        + " "
        + exercises["Desc"]
        + " "
        + exercises["Type"]
        + " "
        + exercises["BodyPart"]
        + " "
        + exercises["Equipment"]
        + " "
        + exercises["Level"]
        + " cluster "
        + exercises["Exercise_Cluster"].astype(str)
    )
    return exercises


def assign_exercise_clusters(exercises: pd.DataFrame) -> pd.Series:
    categorical = exercises[["Type", "BodyPart", "Equipment", "Level"]].fillna("Unknown")
    n_clusters = min(8, max(3, len(exercises) // 250))
    labels, _ = fit_kmodes(categorical, n_clusters=n_clusters)
    return pd.Series(labels, index=exercises.index)


def assign_user_cluster(members: pd.DataFrame, profile: dict) -> int:
    numeric_columns = ["Age", "Weight (kg)", "Height (m)", "BMI"]
    categorical_columns = ["Gender", "Activity_Level", "Experience_Label", "Fitness_Goal"]

    work = members.copy()
    work["Height (m)"] = work["Height (m)"].where(work["Height (m)"] < 3, work["Height (m)"] / 100)
    numeric_matrix, categorical_matrix, scaler = member_feature_matrices(work, numeric_columns, categorical_columns)
    _, numeric_modes, categorical_modes = fit_kprototypes(numeric_matrix, categorical_matrix, n_clusters=5)

    profile_numeric = pd.DataFrame(
        [[profile["age"], profile["weight_kg"], profile["height_cm"] / 100, profile["bmi"]]],
        columns=numeric_columns,
    )
    profile_numeric_scaled = scaler.transform(profile_numeric)[0]
    profile_categories = np.array(
        [
            str(profile["gender"]),
            str(profile["activity_level"]),
            str(profile["experience_level"]),
            str(normalize_goal(profile["fitness_goal"])),
        ]
    )
    numeric_distance = np.linalg.norm(numeric_modes - profile_numeric_scaled, axis=1)
    categorical_distance = (categorical_modes != profile_categories).sum(axis=1)

    combined_distance = numeric_distance + (categorical_distance / len(categorical_columns))
    return int(combined_distance.argmin()) + 1


def member_feature_matrices(
    members: pd.DataFrame,
    numeric_columns: list[str],
    categorical_columns: list[str],
) -> tuple[np.ndarray, np.ndarray, MinMaxScaler]:
    work = members.copy()
    work["Height (m)"] = work["Height (m)"].where(work["Height (m)"] < 3, work["Height (m)"] / 100)
    scaler = MinMaxScaler()
    numeric = scaler.fit_transform(work[numeric_columns])
    categorical = work[categorical_columns].fillna("Unknown").astype(str).to_numpy()
    return numeric, categorical, scaler


def fit_kprototypes(
    numeric: np.ndarray,
    categorical: np.ndarray,
    n_clusters: int,
    *,
    max_iter: int = 30,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    n_clusters = max(1, min(n_clusters, len(numeric)))
    init_indices = np.linspace(0, len(numeric) - 1, n_clusters, dtype=int)
    numeric_modes = numeric[init_indices].copy()
    categorical_modes = categorical[init_indices].copy()
    labels = np.zeros(len(numeric), dtype=int)

    for _ in range(max_iter):
        distances = kprototypes_distances(numeric, categorical, numeric_modes, categorical_modes)
        new_labels = distances.argmin(axis=1)
        if np.array_equal(labels, new_labels):
            break
        labels = new_labels

        for cluster in range(n_clusters):
            mask = labels == cluster
            if not mask.any():
                continue
            numeric_modes[cluster] = numeric[mask].mean(axis=0)
            categorical_modes[cluster] = categorical_mode_rows(categorical[mask])

    return labels, numeric_modes, categorical_modes


def kprototypes_distances(
    numeric: np.ndarray,
    categorical: np.ndarray,
    numeric_modes: np.ndarray,
    categorical_modes: np.ndarray,
) -> np.ndarray:
    numeric_distance = ((numeric[:, None, :] - numeric_modes[None, :, :]) ** 2).sum(axis=2)
    categorical_distance = (categorical[:, None, :] != categorical_modes[None, :, :]).sum(axis=2)
    return numeric_distance + categorical_distance


def fit_kmodes(
    categorical: pd.DataFrame,
    *,
    n_clusters: int,
    max_iter: int = 30,
) -> tuple[np.ndarray, np.ndarray]:
    values = categorical.astype(str).to_numpy()
    n_clusters = max(1, min(n_clusters, len(values)))
    init_indices = np.linspace(0, len(values) - 1, n_clusters, dtype=int)
    modes = values[init_indices].copy()
    labels = np.zeros(len(values), dtype=int)

    for _ in range(max_iter):
        distances = (values[:, None, :] != modes[None, :, :]).sum(axis=2)
        new_labels = distances.argmin(axis=1)
        if np.array_equal(labels, new_labels):
            break
        labels = new_labels

        for cluster in range(n_clusters):
            mask = labels == cluster
            if mask.any():
                modes[cluster] = categorical_mode_rows(values[mask])

    return labels, modes


def categorical_mode_rows(values: np.ndarray) -> np.ndarray:
    modes = []
    for column_index in range(values.shape[1]):
        values_in_column, counts = np.unique(values[:, column_index], return_counts=True)
        modes.append(values_in_column[counts.argmax()])
    return np.array(modes)


def clustering_performance_report(
    members: pd.DataFrame,
    foods: pd.DataFrame,
    exercises: pd.DataFrame,
) -> dict[str, dict]:
    return {
        "K-Prototypes Profil Anggota": kprototypes_performance(members),
        "K-Means Menu Makanan": kmeans_food_performance(foods),
        "K-Modes Latihan": kmodes_exercise_performance(exercises),
    }


def kprototypes_performance(members: pd.DataFrame) -> dict:
    numeric_columns = ["Age", "Weight (kg)", "Height (m)", "BMI"]
    categorical_columns = ["Gender", "Activity_Level", "Experience_Label", "Fitness_Goal"]
    numeric, categorical, _ = member_feature_matrices(members, numeric_columns, categorical_columns)
    labels, numeric_modes, categorical_modes = fit_kprototypes(numeric, categorical, n_clusters=5)
    distances_to_modes = kprototypes_distances(numeric, categorical, numeric_modes, categorical_modes)
    distance_matrix = kprototypes_pairwise_distances(numeric, categorical)
    return performance_payload(
        algorithm="K-Prototypes",
        data_type="Campuran numerik + kategorikal",
        rows=len(members),
        n_clusters=len(np.unique(labels)),
        cost=float(distances_to_modes[np.arange(len(labels)), labels].sum()),
        score=safe_silhouette(distance_matrix, labels, metric="precomputed"),
        counts=cluster_counts(labels + 1),
        cost_label="Combined Cost",
    )


def kmeans_food_performance(foods: pd.DataFrame) -> dict:
    features = foods[["calories", "proteins", "fat", "carbohydrate"]]
    scaled = MinMaxScaler().fit_transform(features)
    model = KMeans(n_clusters=3, random_state=42, n_init=10)
    labels = model.fit_predict(scaled)
    return performance_payload(
        algorithm="K-Means",
        data_type="Numerik",
        rows=len(foods),
        n_clusters=len(np.unique(labels)),
        cost=float(model.inertia_),
        score=safe_silhouette(scaled, labels),
        counts=cluster_counts(assign_food_clusters(foods)),
        cost_label="Inertia",
    )


def kmodes_exercise_performance(exercises: pd.DataFrame) -> dict:
    categorical = exercises[["Type", "BodyPart", "Equipment", "Level"]].fillna("Unknown")
    n_clusters = min(8, max(3, len(exercises) // 250))
    labels, modes = fit_kmodes(categorical, n_clusters=n_clusters)
    values = categorical.astype(str).to_numpy()
    distances_to_modes = (values[:, None, :] != modes[None, :, :]).sum(axis=2)
    distance_matrix = categorical_pairwise_distances(values)
    return performance_payload(
        algorithm="K-Modes",
        data_type="Kategorikal",
        rows=len(exercises),
        n_clusters=len(np.unique(labels)),
        cost=float(distances_to_modes[np.arange(len(labels)), labels].sum()),
        score=safe_silhouette(distance_matrix, labels, metric="precomputed"),
        counts=cluster_counts(labels),
        cost_label="Hamming Cost",
    )


def performance_payload(
    *,
    algorithm: str,
    data_type: str,
    rows: int,
    n_clusters: int,
    cost: float,
    score: float | None,
    counts: pd.DataFrame,
    cost_label: str,
) -> dict:
    return {
        "algorithm": algorithm,
        "data_type": data_type,
        "rows": rows,
        "n_clusters": n_clusters,
        "cost": round(cost, 3),
        "cost_label": cost_label,
        "silhouette_score": round(score, 3) if score is not None else None,
        "counts": counts,
    }


def cluster_counts(labels) -> pd.DataFrame:
    counts = pd.Series(labels, name="Cluster").value_counts().sort_index()
    return counts.rename_axis("Cluster").reset_index(name="Jumlah Data")


def safe_silhouette(data, labels, metric: str = "euclidean") -> float | None:
    unique_labels = np.unique(labels)
    if len(unique_labels) < 2 or len(unique_labels) >= len(labels):
        return None
    return float(silhouette_score(data, labels, metric=metric))


def kprototypes_pairwise_distances(numeric: np.ndarray, categorical: np.ndarray) -> np.ndarray:
    numeric_distance = ((numeric[:, None, :] - numeric[None, :, :]) ** 2).sum(axis=2)
    categorical_distance = (categorical[:, None, :] != categorical[None, :, :]).sum(axis=2)
    return numeric_distance + categorical_distance


def categorical_pairwise_distances(values: np.ndarray) -> np.ndarray:
    return (values[:, None, :] != values[None, :, :]).sum(axis=2).astype(float)


def recommend_foods(
    foods: pd.DataFrame,
    nutrition: NutritionResult,
    preference: str,
    excluded_food_ids: Iterable[int] | None = None,
) -> dict[str, list[dict]]:
    excluded = set(excluded_food_ids or [])
    vectorizer = TfidfVectorizer(stop_words="english")
    tfidf = vectorizer.fit_transform(foods["CBF_Text"])
    query = preference.strip() or "balanced protein carbohydrate"
    query_vector = vectorizer.transform([query])
    scores = cosine_similarity(query_vector, tfidf).ravel()
    ranked = foods.assign(_score=scores).sort_values("_score", ascending=False)

    recommendations: dict[str, list[dict]] = {}
    for meal_slot, clusters in MEAL_TEMPLATE.items():
        slot_calories = nutrition.target_calories * MEAL_DISTRIBUTION[meal_slot]
        item_target = slot_calories / len(clusters)
        recommendations[meal_slot] = []
        used_ids = set(excluded)

        for cluster in clusters:
            candidates = ranked[(ranked["Food_Cluster"] == cluster) & (~ranked["id"].isin(used_ids))]
            chosen = _pick_food_candidate(candidates, item_target)
            if chosen is None:
                candidates = ranked[~ranked["id"].isin(used_ids)]
                chosen = _pick_food_candidate(candidates, item_target)
            if chosen is None:
                continue

            used_ids.add(int(chosen["id"]))
            recommendations[meal_slot].append(chosen)

    return recommendations


def _pick_food_candidate(candidates: pd.DataFrame, target_calories: float) -> dict | None:
    for _, row in candidates.iterrows():
        calories = float(row["calories"])
        if calories <= 0:
            continue
        portion = (target_calories / calories) * 100
        if 50 <= portion <= 450:
            result = row.to_dict()
            result["portion_gram"] = round(portion)
            result["target_calories"] = round(target_calories)
            result["similarity_score"] = round(float(row["_score"]), 3)
            return result
    return None


def swap_food(
    foods: pd.DataFrame,
    current_food: dict,
    target_calories: float,
    preference: str,
) -> dict | None:
    candidates = foods[
        (foods["Food_Cluster"] == current_food["Food_Cluster"]) & (foods["id"] != current_food["id"])
    ].copy()
    if candidates.empty:
        return None
    candidates["_score"] = candidates["name"].str.contains(preference, case=False, na=False).astype(float)
    return _pick_food_candidate(candidates.sort_values("_score", ascending=False), target_calories)


def recommend_exercises(
    exercises: pd.DataFrame,
    *,
    body_part: str,
    workout_type: str,
    equipment_preference: str,
    experience_level: str,
    fitness_goal: str,
    limit: int = 5,
) -> pd.DataFrame:
    allowed_levels = LEVEL_ALLOWLIST[experience_level]
    filtered = exercises[exercises["Level"].isin(allowed_levels)].copy()
    if body_part != "Any":
        filtered = filtered[filtered["BodyPart"] == body_part]
    if workout_type != "Any":
        filtered = filtered[filtered["Type"] == workout_type]
    if filtered.empty:
        filtered = exercises[exercises["Level"].isin(allowed_levels)].copy()

    query = f"{body_part} {workout_type} {equipment_preference} {experience_level}"
    vectorizer = TfidfVectorizer(stop_words="english")
    tfidf = vectorizer.fit_transform(filtered["CBF_Text"])
    scores = cosine_similarity(vectorizer.transform([query]), tfidf).ravel()
    ranked = filtered.assign(Similarity=scores).sort_values("Similarity", ascending=False)

    selected = _enforce_equipment_diversity(ranked, limit)
    params = TRAINING_PARAMETERS[(normalize_goal(fitness_goal), experience_level)]
    for key, value in params.items():
        selected[key] = value
    selected["Similarity"] = selected["Similarity"].round(3)
    return selected


def switch_exercise(
    exercises: pd.DataFrame,
    current_exercise: dict,
    current_recommendations: pd.DataFrame,
    filters: dict,
) -> dict | None:
    experience_level = filters.get("experience_level", "Beginner")
    fitness_goal = filters.get("fitness_goal", "Maintain Weight")
    body_part = filters.get("body_part", "Any")
    workout_type = filters.get("workout_type", "Any")
    equipment_preference = filters.get("equipment_preference", "Any")

    allowed_levels = LEVEL_ALLOWLIST[experience_level]
    candidates = exercises[exercises["Level"].isin(allowed_levels)].copy()
    if body_part != "Any":
        candidates = candidates[candidates["BodyPart"] == body_part]
    if workout_type != "Any":
        candidates = candidates[candidates["Type"] == workout_type]

    current_title = str(current_exercise.get("Title", ""))
    selected_titles = {
        str(title)
        for title in current_recommendations.get("Title", pd.Series(dtype=str)).tolist()
    }
    excluded_titles = {str(title) for title in filters.get("excluded_titles", [])}
    candidates = candidates[~candidates["Title"].astype(str).isin(selected_titles | excluded_titles | {current_title})]
    if candidates.empty:
        return None

    query = f"{body_part} {workout_type} {equipment_preference} {experience_level}"
    vectorizer = TfidfVectorizer(stop_words="english")
    tfidf = vectorizer.fit_transform(candidates["CBF_Text"])
    scores = cosine_similarity(vectorizer.transform([query]), tfidf).ravel()
    ranked = candidates.assign(Similarity=scores)
    if equipment_preference != "Any":
        ranked["_equipment_match"] = (ranked["Equipment"] == equipment_preference).astype(int)
        ranked = ranked.sort_values(["_equipment_match", "Similarity"], ascending=False)
    else:
        ranked = ranked.sort_values("Similarity", ascending=False)

    replacement = ranked.iloc[0].drop(labels=["_equipment_match"], errors="ignore").to_dict()
    params = TRAINING_PARAMETERS[(normalize_goal(fitness_goal), experience_level)]
    replacement.update(params)
    replacement["Similarity"] = round(float(replacement.get("Similarity", 0)), 3)
    return replacement


def _enforce_equipment_diversity(ranked: pd.DataFrame, limit: int) -> pd.DataFrame:
    selected_indices = []
    used_equipment = set()

    for index, row in ranked.iterrows():
        if row["Equipment"] in used_equipment:
            continue
        selected_indices.append(index)
        used_equipment.add(row["Equipment"])
        if len(selected_indices) >= min(limit, 3):
            break

    for index in ranked.index:
        if len(selected_indices) >= limit:
            break
        if index not in selected_indices:
            selected_indices.append(index)

    return ranked.loc[selected_indices].copy()


def profile_payload(nutrition: NutritionResult, **profile) -> dict:
    payload = dict(profile)
    payload.update(asdict(nutrition))
    return payload
