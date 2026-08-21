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
    "Lose Weight": -500,
    "Maintain Weight": 0,
    "Gain Weight": 300,
}

GOAL_PROTEIN_GRAMS_PER_KG = {
    "Lose Weight": 2.2,
    "Maintain Weight": 1.8,
    "Gain Weight": 1.6,
}


@dataclass(frozen=True)
class NutritionResult:
    """Hasil perhitungan gizi satu pengguna: BMI, BMR, TDEE, target kalori, dan makro."""

    bmi: float
    bmi_status: str
    bmr: float
    tdee: float
    target_calories: float
    ideal_weight: float
    carbohydrate_g: float
    protein_g: float
    fat_g: float


def calculate_bmi(weight_kg: float, height_cm: float) -> float:
    """Hitung BMI dari berat (kg) dan tinggi (cm)."""
    height_m = height_cm / 100
    if height_m <= 0:
        raise ValueError("Height must be greater than zero.")
    return weight_kg / (height_m**2)


def classify_bmi(bmi: float) -> str:
    """Terjemahkan angka BMI ke kategori Asia-Pasifik (Kurus s.d. Obesitas II)."""
    if bmi < 18.5:
        return "Kurus"
    if bmi < 23:
        return "Normal"
    if bmi < 25:
        return "Gemuk"
    if bmi < 30:
        return "Obesitas I"
    return "Obesitas II"


def calculate_bmr(gender: str, weight_kg: float, height_cm: float, age: int) -> float:
    """Hitung BMR (kalori basal) dengan rumus Mifflin-St Jeor."""
    gender_key = gender.strip().lower()
    if gender_key == "male":
        return 10 * weight_kg + 6.25 * height_cm - 5 * age + 5
    return 10 * weight_kg + 6.25 * height_cm - 5 * age - 161


def calculate_ideal_weight(height_cm: float, gender: str) -> float:
    """Hitung berat badan ideal dengan rumus Broca (koreksi 10% pria, 15% wanita)."""
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
    """Rangkai BMI, BMR, TDEE, target kalori, dan pembagian makro jadi satu NutritionResult."""
    bmi = calculate_bmi(weight_kg, height_cm)
    bmr = calculate_bmr(gender, weight_kg, height_cm, age)
    activity_factor = ACTIVITY_FACTORS.get(activity_level, ACTIVITY_FACTORS["Medium"])
    tdee = bmr * activity_factor
    target_calories = max(1200, tdee + GOAL_CALORIE_ADJUSTMENTS.get(fitness_goal, 0))
    protein_g = weight_kg * GOAL_PROTEIN_GRAMS_PER_KG.get(fitness_goal, 1.8)
    fat_g = (target_calories * 0.25) / 9
    carbohydrate_calories = max(0, target_calories - (protein_g * 4) - (fat_g * 9))

    return NutritionResult(
        bmi=round(bmi, 1),
        bmi_status=classify_bmi(bmi),
        bmr=round(bmr),
        tdee=round(tdee),
        target_calories=round(target_calories),
        ideal_weight=round(calculate_ideal_weight(height_cm, gender), 1),
        carbohydrate_g=round(carbohydrate_calories / 4),
        protein_g=round(protein_g),
        fat_g=round(fat_g),
    )
