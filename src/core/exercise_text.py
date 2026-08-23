"""Penerjemahan nama, deskripsi, dan atribut latihan dari Inggris ke Indonesia.

Diterjemahkan per potongan istilah, bukan per kalimat utuh, supaya gerakan yang
belum pernah ditemui tetap terbaca sebagian.
"""

from __future__ import annotations

from functools import lru_cache
import json
import re

from src.paths import DATA_DIR


LEXICON_PATH = DATA_DIR / "exercise_id_lexicon.json"

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'-]*")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_PLACEHOLDER = "\x00{}\x00"
_PLACEHOLDER_RE = re.compile(r"\x00(\d+)\x00")


@lru_cache(maxsize=1)
def _lexicon() -> dict:
    """Muat kamus kata, frasa, dan kalimat dari berkas leksikon; dibaca sekali lalu di-cache."""
    try:
        raw = json.loads(LEXICON_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"words": {}, "phrases": {}, "sentences": {}, "phrase_re": None}
    if not isinstance(raw, dict):
        return {"words": {}, "phrases": {}, "sentences": {}, "phrase_re": None}

    words = {str(k).lower(): str(v) for k, v in (raw.get("words") or {}).items()}
    phrases = {str(k).lower(): str(v) for k, v in (raw.get("phrases") or {}).items()}
    sentences = {_sentence_key(k): str(v) for k, v in (raw.get("sentences") or {}).items()}

    # Satu regex alternasi untuk SEMUA frasa, diurutkan dari yang terpanjang.
    # Alternasi Python memilih cabang pertama yang cocok, bukan yang terpanjang,
    # jadi urutan inilah yang membuat "starting position" menang atas "starting".
    phrase_re = None
    if phrases:
        ordered = sorted(phrases, key=len, reverse=True)
        # Batas kiri/kanan ikut menolak tanda hubung supaya frasa tidak
        # menggigit separuh kata majemuk: tanpa itu frasa "arm ..." bisa cocok
        # di tengah "single-arm ..." dan merusak nama gerakannya.
        phrase_re = re.compile(
            r"(?<![A-Za-z-])(" + "|".join(re.escape(p) for p in ordered) + r")(?![A-Za-z-])",
            re.IGNORECASE,
        )
    return {"words": words, "phrases": phrases, "sentences": sentences, "phrase_re": phrase_re}


def lexicon_is_available() -> bool:
    """True bila berkas leksikon berhasil dimuat dan tidak kosong."""
    lexicon = _lexicon()
    return bool(lexicon["words"] or lexicon["phrases"] or lexicon["sentences"])


def _sentence_key(text) -> str:
    """Kunci pencocokan kalimat: huruf kecil, spasi dirapikan.

    Dinormalkan supaya perbedaan spasi ganda atau kapitalisasi di dataset tidak
    membuat kalimat yang sudah diterjemahkan manual jadi tidak terpakai.
    """
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def _apply_case(original: str, translated: str) -> str:
    """Samakan kapitalisasi huruf pertama dengan kata aslinya."""
    if not translated:
        return translated
    if original.isupper() and len(original) > 1:
        return translated.upper()
    if original[:1].isupper():
        return translated[:1].upper() + translated[1:]
    return translated


def id_kalimat(text: str) -> str:
    """Terjemahkan SATU kalimat (atau frasa pendek) ke bahasa Indonesia."""
    source = str(text or "").strip()
    if not source:
        return ""

    lexicon = _lexicon()
    exact = lexicon["sentences"].get(_sentence_key(source))
    if exact:
        return exact

    working = source
    captured: list[str] = []

    phrase_re = lexicon["phrase_re"]
    if phrase_re is not None:
        def _swap_phrase(match: re.Match) -> str:
            """Ganti satu frasa yang cocok dengan terjemahannya, disimpan sebagai placeholder agar tidak diproses ulang."""
            found = match.group(0)
            replacement = lexicon["phrases"].get(found.lower(), found)
            captured.append(_apply_case(found, replacement))
            return _PLACEHOLDER.format(len(captured) - 1)

        working = phrase_re.sub(_swap_phrase, working)

    def _swap_word(match: re.Match) -> str:
        """Ganti satu kata yang cocok dengan terjemahannya, kapitalisasi asli dipertahankan."""
        found = match.group(0)
        replacement = lexicon["words"].get(found.lower())
        if replacement is None:
            return found
        return _apply_case(found, replacement)

    working = _WORD_RE.sub(_swap_word, working)
    working = _PLACEHOLDER_RE.sub(lambda match: captured[int(match.group(1))], working)
    return _tidy(working)


def _tidy(text: str) -> str:
    """Rapikan hasil terjemahan: spasi ganda, spasi sebelum tanda baca, dan huruf awal kapital."""
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    return text[:1].upper() + text[1:] if text else text


def id_teks(text: str) -> str:
    """Terjemahkan teks berisi beberapa kalimat (mis. deskripsi latihan)."""
    source = str(text or "").strip()
    if not source:
        return ""
    return " ".join(id_kalimat(part) for part in _SENTENCE_SPLIT_RE.split(source) if part.strip())


def id_nama_latihan(title: str) -> str:
    """Terjemahkan nama gerakan ke bahasa Indonesia, potongan demi potongan.

    Istilah yang tidak dikenali dibiarkan apa adanya.
    """
    return " ".join(_kapital_kata(kata) for kata in str(title or "").split())


def _kapital_kata(kata: str) -> str:
    """Naikkan huruf pertama tiap segmen yang seluruhnya huruf kecil.

    Dipotong di tanda hubung dan diperiksa PER SEGMEN, bukan per kata: tanda
    hubung di nama gerakan memisahkan dua kata setara, dan sebagian sudah
    setengah rapi di dataset. Pemeriksaan per kata membiarkan "Reverse-grip"
    apa adanya karena kata itu sudah memuat huruf besar, padahal yang perlu
    dinaikkan justru segmen keduanya.
    """
    return "-".join(
        bagian.capitalize() if bagian.islower() else bagian
        for bagian in kata.split("-")
    )


def id_deskripsi_latihan(exercise: dict, tutorial: dict | None = None) -> str:
    """Terjemahkan deskripsi gerakan kalimat demi kalimat.

    Kalimat yang tidak dikenali dibiarkan apa adanya, dan teks aslinya tetap bisa
    dibuka pengguna lewat halaman tutorial.
    """
    from .i18n import id_daftar, id_istilah  # lokal: hindari impor melingkar

    jenis = id_istilah(exercise.get("Type"))
    bagian = id_istilah(exercise.get("BodyPart"))
    alat = id_istilah(exercise.get("Equipment"))
    level = id_istilah(exercise.get("Level"))

    kalimat = []
    pokok = f"Latihan {jenis.lower()} untuk melatih {bagian.lower()}"
    if alat and alat not in {"-", "Tanpa Alat"}:
        pokok += f" menggunakan {alat.lower()}"
    elif alat == "Tanpa Alat":
        pokok += " tanpa alat bantu"
    kalimat.append(pokok + ".")

    if level and level != "-":
        kalimat.append(f"Ditujukan untuk level {level.lower()}.")

    if tutorial:
        target = id_istilah(tutorial.get("target"))
        if target and target != "-":
            kalimat.append(f"Otot utama: {target}.")
        secondary = tutorial.get("secondary_muscles") or []
        if secondary:
            kalimat.append(f"Otot pendukung: {id_daftar(secondary)}.")

    return " ".join(kalimat)


# --------------------------------------------------------------------------- #
# Penerjemahan nama dan deskripsi latihan
# --------------------------------------------------------------------------- #
# Diterjemahkan per potongan istilah, bukan per kalimat utuh, supaya nama gerakan
# yang belum pernah ditemui tetap terbaca sebagian.
POLA_GERAK: tuple[tuple[str, str], ...] = (
    # Peregangan diperiksa PALING AWAL: namanya kerap memuat pola gerak lain
    # sebagai keterangan posisi ("spider lunge stretch", "overhead squat
    # stretch"), padahal yang dikerjakan tetap meregangkan otot, bukan
    # mengangkat beban.
    (r"stretch|mobility|foam roll|\bsmr\b|myofascial", "Meregangkan otot"),
    (r"pull ?-? ?down", "Menarik beban ke bawah"),
    (r"pull ?-? ?up|chin ?-? ?up", "Menarik tubuh ke atas"),
    (r"push ?-? ?up", "Mendorong tubuh dari lantai"),
    (r"\bdip", "Menopang lalu menurunkan tubuh"),
    (r"deadlift", "Mengangkat beban dari lantai"),
    (r"clean|snatch|jerk", "Angkatan cepat ke atas kepala"),
    (r"hip thrust|bridge|thrust", "Mengangkat pinggul"),
    (r"shrug", "Mengangkat bahu"),
    (r"\bfly|flye", "Membuka dan menutup lengan"),
    (r"press|\bpush", "Mendorong beban"),
    (r"\brow\b|pull", "Menarik beban"),
    (r"squat", "Menekuk lutut menahan beban"),
    (r"lunge|step ?-? ?up", "Melangkah sambil menahan beban"),
    (r"crunch|sit ?-? ?up|leg raise|knee raise", "Menekuk badan melawan beban"),
    (r"plank|hold|isometric", "Menahan posisi statis"),
    (r"extension|skullcrusher|skull crusher", "Meluruskan sendi melawan beban"),
    (r"curl", "Menekuk sendi melawan beban"),
    (r"roll ?-? ?out", "Mengulur badan menahan beban"),
    (r"swing|juggle", "Mengayun beban"),
    (r"crawl", "Merangkak menahan berat tubuh"),
    (r"raise|lift|pullover", "Mengangkat beban"),
    (
        r"twist|rotation|rotate|russian|chop|woodchop|windmill",
        "Memutar badan",
    ),
    (r"kick", "Menendang melawan beban"),
    (r"carry|farmer|walk", "Berjalan sambil membawa beban"),
    (
        r"jump|hop|burpee|skip|sprint|run|jog|climb|high knee|sprawl",
        "Gerakan eksplosif berulang",
    ),
    # Paling belakang: "bend" & "hinge" muncul juga sebagai keterangan posisi
    # pada gerakan lain ("bent-over row"), jadi hanya dipakai kalau tidak ada
    # pola lain yang cocok.
    (r"good ?-? ?morning|\bbend\b|hinge", "Membungkuk menahan beban"),
)

_POLA_GERAK_RE = tuple(
    (re.compile(pola, re.IGNORECASE), teks) for pola, teks in POLA_GERAK
)

# Cadangan kalau nama gerakannya tidak memuat kata kerja sama sekali
# (mis. "Bulgarian Split", "Man Maker"): jenis latihan tetap memberi inti.
POLA_PER_JENIS: dict[str, str] = {
    "stretching": "Meregangkan otot",
    "plyometrics": "Gerakan eksplosif berulang",
    "cardio": "Latihan kardio berkelanjutan",
    "olympic weightlifting": "Angkatan cepat ke atas kepala",
    "powerlifting": "Angkatan beban maksimal",
    "strongman": "Memindahkan beban berat",
}

# Nama otot versi PENDEK khusus untuk kalimat inti. Berbeda dari ISTILAH_LATIHAN
# yang dipakai chip & halaman detail: di sana nama ilmiahnya berguna ("Dada
# (Pektoral)"), di kartu satu baris justru memakan ruang tanpa menambah makna.
OTOT_RINGKAS: dict[str, str] = {
    "abdominals": "perut",
    "abs": "perut",
    "abductors": "otot abduktor",
    "adductors": "otot adduktor",
    "biceps": "bisep",
    "calves": "betis",
    "cardiovascular system": "jantung dan paru",
    "chest": "dada",
    "delts": "bahu",
    "forearms": "lengan bawah",
    "glutes": "bokong",
    "hamstrings": "paha belakang",
    "lats": "sayap punggung",
    "levator scapulae": "leher",
    "lower back": "punggung bawah",
    "middle back": "punggung tengah",
    "pectorals": "dada",
    "quadriceps": "paha depan",
    "quads": "paha depan",
    "serratus anterior": "sisi tulang rusuk",
    "shoulders": "bahu",
    "spine": "tulang belakang",
    "traps": "trapezius",
    "triceps": "trisep",
    "upper back": "punggung atas",
    "upper chest": "dada atas",
}


def _otot_ringkas(value) -> str:
    """Nama otot sesingkat mungkin; istilah asing dikecilkan, bukan dibuang."""
    teks = str(value or "").strip().lower()
    if not teks or teks == "-":
        return ""
    return OTOT_RINGKAS.get(teks, teks)


def id_inti_latihan(exercise: dict, tutorial: dict | None = None) -> str:
    """Inti gerakan dalam satu kalimat pendek: pola gerak + otot yang dilatih.

    Dipakai kartu rekomendasi latihan. Halaman detail tetap memakai
    id_deskripsi_latihan yang lebih lengkap -- di sana ruangnya ada dan
    pembacanya memang sedang mencari keterangan.
    """
    judul = str(exercise.get("Title") or (tutorial or {}).get("name") or "")

    pola = ""
    for regex, teks in _POLA_GERAK_RE:
        if regex.search(judul):
            pola = teks
            break
    if not pola:
        jenis = str(exercise.get("Type") or "").strip().lower()
        pola = POLA_PER_JENIS.get(jenis, "Melatih kekuatan otot")

    # Otot target dataset tutorial lebih spesifik daripada BodyPart dataset utama,
    # jadi dipetakan ke istilah Indonesia yang dipakai di layar.
    target = _otot_ringkas((tutorial or {}).get("target"))
    bagian = _otot_ringkas(exercise.get("BodyPart"))
    if target and bagian and (target in bagian or bagian in target):
        otot = target
    else:
        otot = bagian or target

    if not otot:
        return f"{pola}."
    return f"{pola} untuk {otot}."


def id_langkah_latihan(steps) -> list[str]:
    """Langkah pelaksanaan dalam bahasa Indonesia."""
    if not steps:
        return []
    if not lexicon_is_available():
        return [str(step) for step in steps]
    return [id_teks(step) for step in steps if str(step).strip()]
