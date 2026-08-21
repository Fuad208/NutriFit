"""Penerjemah teks latihan Inggris -> Indonesia, berbasis kamus & aturan.

Dataset latihan (`training_program`) dan dataset tutorial
(`dataProgramTraining/data/exercises.json`) seluruhnya berbahasa Inggris: nama
gerakan, deskripsi, dan langkah pelaksanaan. Dataset tutorial memang punya 10
bahasa, tapi Indonesia bukan salah satunya -- jadi tidak ada terjemahan siap
pakai yang bisa dibaca langsung.

Yang menyelamatkan keadaan: kosakatanya nyaris tertutup. Seluruh langkah
pelaksanaan hanya memakai ~900 kata unik, dan 400 kata teratas sudah menutup
98,7% kemunculan. Kalimatnya pun formulaik ("Repeat for the desired number of
repetitions." muncul 900 kali). Karena itu penerjemahan dilakukan OFFLINE dan
DETERMINISTIK -- tanpa layanan terjemahan, tanpa panggilan jaringan, dan hasil
yang sama persis di setiap mesin -- lewat tiga lapis pencocokan:

1. `sentences`  - kalimat utuh yang sering muncul, diterjemahkan manual. Lapis
                  paling akurat; dipakai lebih dulu.
2. `phrases`    - idiom & kolokasi multi-kata ("shoulder-width apart" ->
                  "selebar bahu"). Dicocokkan dari yang TERPANJANG supaya frasa
                  panjang menang atas potongannya.
3. `words`      - kata per kata untuk sisanya.

Kamusnya ada di data/exercise_id_lexicon.json supaya bisa ditambah tanpa
menyentuh kode. Kalau berkasnya hilang, modul ini mengembalikan teks aslinya
apa adanya -- aplikasi tetap jalan, hanya tidak diterjemahkan.
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
    """Nama gerakan ditampilkan APA ADANYA, tidak diterjemahkan.

    Ini keputusan sadar, bukan pekerjaan yang belum selesai. Dua alasannya:

    1. Praktisi gym Indonesia memang memakai nama Inggrisnya ("bench press",
       "lat pulldown", "deadlift"). Menerjemahkannya justru membuat gerakan
       lebih sulit dikenali, bukan lebih mudah.
    2. Nama latihan adalah frasa benda bertumpuk ("Weighted Donkey Calf Raise",
       "Half Bird Dog"). Penerjemah substitusi tidak mengubah urutan kata dan
       tidak tahu mana yang nama diri, jadi hasilnya salah pada nama-nama
       kiasan seperti "bird dog". Kalimat instruksi tidak punya masalah ini
       karena strukturnya perintah-lalu-objek.

    Yang DITERJEMAHKAN adalah keterangannya: deskripsi latihan dan langkah
    pelaksanaan (lihat id_deskripsi_latihan & id_langkah_latihan).

    Yang DIRAPIKAN hanya kapitalisasinya. Dataset menulis nama gerakan dengan
    gaya campur -- "Ab Crunch Machine" bersebelahan dengan "Incline bench
    press" dan "Machine triceps extension-" -- dan judul kartu yang kadang
    Title Case kadang huruf kecil terbaca seperti data yang belum selesai
    dibersihkan. `str.title()` bukan jawabannya karena ia merusak singkatan
    dan nama program ("FYR2" jadi "Fyr2", "MetaBurn" jadi "Metaburn"), jadi
    yang dinaikkan hanya kata yang SELURUHNYA huruf kecil; kata yang sudah
    memuat huruf besar dibiarkan sebagaimana penulis datanya menulisnya.
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
    """Keterangan latihan dalam bahasa Indonesia, DISUSUN dari metadata.

    Deskripsi asli di dataset berupa prosa pemasaran ("The banded plank jack is
    a variation on the plank that involves moving the legs in and out..."), dan
    prosa seperti itu tidak selamat lewat penerjemah substitusi: bahasa Inggris
    menaruh penjelas di DEPAN kata benda, bahasa Indonesia di belakang, jadi
    hasilnya jadi "berat badan urutan" alih-alih "rangkaian berat badan".
    Kalimat instruksi tidak kena masalah ini (strukturnya perintah-lalu-objek),
    karena itu langkah pelaksanaan tetap diterjemahkan.

    Untuk keterangan, menyusun kalimat sendiri dari metadata yang sudah
    terstruktur (jenis, bagian tubuh, alat, level, otot) memberi kalimat
    Indonesia yang benar dan selalu terbaca wajar. Teks aslinya tetap
    disediakan di halaman detail bagi yang ingin membandingkan.
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
# Inti gerakan (untuk kartu rekomendasi)
# --------------------------------------------------------------------------- #
# Kartu rekomendasi hanya punya ruang satu-dua baris, dan tiga keterangan yang
# paling sering dicari -- bagian tubuh, alat, level -- SUDAH tampil sebagai chip
# di atasnya. Mengulanginya sebagai kalimat panjang membuat kartu penuh tanpa
# menambah informasi. Yang belum terwakili chip justru yang paling menentukan:
# gerakannya seperti apa.
#
# Pola dicocokkan dari nama gerakan, diurutkan dari yang PALING SPESIFIK ke yang
# paling umum -- "lat pulldown" harus menang atas "pull", dan "push up" atas
# "push". Pencocokan berhenti di pola pertama yang kena.
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

    # Otot target dataset tutorial lebih spesifik daripada BodyPart ("dada
    # atas" vs "dada"), jadi dipakai kalau bisa. Tapi tutorial dicocokkan
    # dengan kemiripan nama (find_training_tutorial), bukan kunci yang pasti,
    # sehingga sesekali menempel ke gerakan lain -- "reverse-grip dumbbell
    # curl" pernah tersambung ke tutorial ber-target "lats". Target hanya
    # dipercaya kalau masih SATU KELUARGA dengan BodyPart baris itu sendiri;
    # kalau bertabrakan, BodyPart yang menang karena ia datang dari baris
    # latihannya sendiri dan tidak pernah salah sambung.
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
