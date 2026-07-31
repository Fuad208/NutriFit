from __future__ import annotations

from dataclasses import dataclass


ACTIVITY_FACTORS = {
    "Low": 1.2,
    "Medium": 1.375,
    "Moderate": 1.375,
    "High": 1.55,
    "Very High": 1.725,
}

GOAL_CALORIE_ADJUSTMENTS = {
    "Lose Weight": -400,
    "Maintain Weight": 0,
    "Gain Weight": 350,
}


@dataclass(frozen=True)
class NutritionResult:
    bmi: float
    bmi_status: str
    bmr: float
    tdee: float
    target_calories: float
    ideal_weight: float
    carbohydrate_g: float
    protein_g: float
    fat_g: float


def calculate_age(current_year: int, birth_year: int) -> int:
    return max(13, current_year - birth_year)


def calculate_bmi(weight_kg: float, height_cm: float) -> float:
    height_m = height_cm / 100
    if height_m <= 0:
        raise ValueError("Height must be greater than zero.")
    return weight_kg / (height_m**2)


def classify_bmi(bmi: float) -> str:
    if bmi < 18.5:
        return "Underweight"
    if bmi < 25:
        return "Normal"
    if bmi < 30:
        return "Overweight"
    return "Obese"


def calculate_bmr(gender: str, weight_kg: float, height_cm: float, age: int) -> float:
    gender_key = gender.strip().lower()
    if gender_key == "male":
        return 10 * weight_kg + 6.25 * height_cm - 5 * age + 5
    return 10 * weight_kg + 6.25 * height_cm - 5 * age - 161


def calculate_ideal_weight(height_cm: float, gender: str) -> float:
    base = height_cm - 100
    correction = 0.1 if gender.strip().lower() == "male" else 0.15
    return base - (base * correction)


def calculate_nutrition_targets(
    *,
    gender: str,
    weight_kg: float,
    height_cm: float,
    age: int,
    activity_level: str,
    fitness_goal: str,
) -> NutritionResult:
    bmi = calculate_bmi(weight_kg, height_cm)
    bmr = calculate_bmr(gender, weight_kg, height_cm, age)
    activity_factor = ACTIVITY_FACTORS.get(activity_level, ACTIVITY_FACTORS["Medium"])
    tdee = bmr * activity_factor
    target_calories = max(1200, tdee + GOAL_CALORIE_ADJUSTMENTS.get(fitness_goal, 0))

    return NutritionResult(
        bmi=round(bmi, 1),
        bmi_status=classify_bmi(bmi),
        bmr=round(bmr),
        tdee=round(tdee),
        target_calories=round(target_calories),
        ideal_weight=round(calculate_ideal_weight(height_cm, gender), 1),
        carbohydrate_g=round((target_calories * 0.50) / 4),
        protein_g=round((target_calories * 0.25) / 4),
        fat_g=round((target_calories * 0.25) / 9),
    )
