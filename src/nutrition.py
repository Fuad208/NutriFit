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


# --------------------------------------------------------------------------- #
# Pagar tujuan kebugaran
# --------------------------------------------------------------------------- #
# Rentang BMI yang masih tergolong "Normal" menurut classify_bmi(). Dipakai untuk
# menerjemahkan kalimat "sampai batas normal" jadi angka berat badan yang bisa
# ditunjukkan ke pengguna, bukan sekadar anjuran tanpa ukuran.
NORMAL_BMI_RANGE = (18.5, 23.0)

# Perlakuan tiap tujuan kebugaran pada tiap kategori IMT. Tingkatnya, dari longgar
# ke ketat: saran, boleh, syarat, warning, error, tetap, blokir.
# Ambangnya mengikuti classify_bmi() supaya layar dan aturan tidak berbeda
# pendapat. Alasan tiap penetapan: docs/catatan-desain.md bagian 13.
GOAL_GUARDRAILS = {
    "Kurus":       {"Lose Weight": "error",  "Maintain Weight": "boleh",   "Gain Weight": "saran"},
    "Normal":      {"Lose Weight": "syarat", "Maintain Weight": "saran",   "Gain Weight": "syarat"},
    "Gemuk":       {"Lose Weight": "saran",  "Maintain Weight": "warning", "Gain Weight": "error"},
    "Obesitas I":  {"Lose Weight": "tetap",  "Maintain Weight": "blokir",  "Gain Weight": "blokir"},
    "Obesitas II": {"Lose Weight": "tetap",  "Maintain Weight": "blokir",  "Gain Weight": "blokir"},
}

GOAL_ORDER = ("Lose Weight", "Maintain Weight", "Gain Weight")


@dataclass(frozen=True)
class GoalGuardrail:
    """Tujuan mana yang boleh dipilih seseorang, beserta alasan dan batas beratnya."""

    bmi: float
    bmi_status: str
    weight_min: float
    weight_max: float
    allowed: tuple[str, ...]
    fixed: str | None
    default: str
    levels: dict

    def level(self, fitness_goal: str) -> str:
        """Tingkat perlakuan satu tujuan: saran / boleh / syarat / warning / error / tetap / blokir."""
        return self.levels.get(fitness_goal, "blokir")

    def is_blocked(self, fitness_goal: str) -> bool:
        """True bila tujuan ini tidak boleh dipakai sama sekali pada kondisi BMI tersebut."""
        return self.level(fitness_goal) == "blokir"

    def needs_confirmation(self, fitness_goal: str) -> bool:
        """True bila tujuan ini hanya boleh dipakai setelah pengguna menyatakan mengerti risikonya."""
        return self.level(fitness_goal) == "error"


def goal_guardrail(weight_kg: float, height_cm: float) -> GoalGuardrail:
    """Tentukan tujuan yang boleh dipilih dari berat dan tinggi badan.

    Dipanggil SEBELUM pilihan tujuan dirender, bukan sesudahnya. Itulah sebabnya
    berat dan tinggi tidak lagi berada di dalam st.form di halaman kalori:
    Streamlit menahan nilai widget di dalam form sampai tombol kirim ditekan,
    sehingga BMI mustahil diketahui saat pilihan tujuan disusun -- dan pengguna
    obesitas bisa memilih "menaikkan berat" tanpa satu pun peringatan.
    """
    bmi = calculate_bmi(weight_kg, height_cm)
    status = classify_bmi(bmi)
    rules = GOAL_GUARDRAILS[status]

    height_m = height_cm / 100
    low, high = NORMAL_BMI_RANGE

    allowed = tuple(goal for goal in GOAL_ORDER if rules[goal] != "blokir")
    fixed = next((goal for goal in GOAL_ORDER if rules[goal] == "tetap"), None)
    default = fixed or next(goal for goal in GOAL_ORDER if rules[goal] == "saran")

    return GoalGuardrail(
        bmi=round(bmi, 1),
        bmi_status=status,
        weight_min=round(low * height_m**2, 1),
        weight_max=round(high * height_m**2, 1),
        allowed=allowed,
        fixed=fixed,
        default=default,
        levels=dict(rules),
    )
