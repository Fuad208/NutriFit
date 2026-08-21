"""Hitung ulang `user_cluster` pada profil dan riwayat yang sudah tersimpan.

KENAPA PERLU. Nomor klaster hanya bermakna relatif terhadap model yang
membentuknya. Ketika jumlah klaster anggota berubah dari 7 menjadi 10, angka
"Klaster 5" yang tersimpan pada profil lama merujuk pembagian yang sudah tidak
ada lagi -- dua pengguna dengan tubuh identik bahkan bisa tercatat di klaster
berbeda hanya karena profilnya dihitung pada waktu yang berbeda.

Dampaknya kosmetik: `user_cluster` hanya ditampilkan sebagai keterangan
"Segmen pengguna" di halaman kalori dan tidak dipakai logika rekomendasi mana
pun. Tapi angka yang menunjuk ke sesuatu yang tidak ada tetap tidak pantas
dibiarkan, apalagi kalau riwayatnya ikut dibaca saat sidang.

CARA PAKAI.
    python schema_data/migrate_user_clusters.py            # hanya melihat (dry run)
    python schema_data/migrate_user_clusters.py --terapkan  # tulis perubahannya

Aman dijalankan berulang: setelah sekali berhasil, jalannya berikutnya tidak
menemukan apa-apa untuk diubah.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.database import (  # noqa: E402
    CALORIE_STORE,
    load_records,
    load_users,
    save_records,
    save_users,
)
from src.recommender import assign_user_cluster, clean_members, load_dataset_tables  # noqa: E402

# Kolom yang wajib ada sebelum sebuah profil bisa ditempatkan ulang. Profil yang
# tidak lengkap DILEWATI, bukan ditebak -- menebak berarti memindahkan pengguna
# ke segmen yang tidak pernah dihitung dari datanya sendiri.
WAJIB = ("age", "weight_kg", "height_cm", "bmi", "gender",
         "activity_level", "experience_level", "fitness_goal")


def cadangan_path() -> Path:
    """Path berkas cadangan berstempel waktu, ditulis sebelum data pengguna diubah."""
    stempel = datetime.now().strftime("%Y%m%d-%H%M%S")
    return ROOT / "data" / f"cadangan_user_cluster_{stempel}.json"


def klaster_baru(members, profil: dict) -> int | None:
    """Hitung ulang klaster satu profil; None bila datanya belum lengkap atau perhitungannya gagal."""
    if any(profil.get(kolom) in (None, "") for kolom in WAJIB):
        return None
    try:
        return int(assign_user_cluster(members, profil))
    except Exception:
        return None


def main() -> int:
    """Hitung ulang klaster seluruh pengguna terhadap model aktif; menulis hanya bila diberi --terapkan."""
    terapkan = "--terapkan" in sys.argv

    print("Penyimpanan : PostgreSQL (Supabase)")
    members = clean_members(load_dataset_tables()[0])
    jumlah_klaster = members["User_Cluster"].nunique()
    print(f"Model aktif : {jumlah_klaster} klaster anggota\n")

    users = load_users()
    records = load_records(CALORIE_STORE)

    cadangan = {
        "dibuat": datetime.now().isoformat(timespec="seconds"),
        "jumlah_klaster_model": int(jumlah_klaster),
        "users": {e: (u.get("profile") or {}).get("user_cluster") for e, u in users.items()},
        "calorie_records": [
            {"id": r.get("id"), "user_cluster": (r.get("profile") or {}).get("user_cluster")}
            for r in records if isinstance(r.get("profile"), dict)
        ],
    }

    # ---------------------------------------------------------------- profil --
    ubah_user, lewat_user = [], []
    for email, user in users.items():
        profil = user.get("profile")
        if not isinstance(profil, dict) or profil.get("user_cluster") is None:
            continue
        baru = klaster_baru(members, profil)
        if baru is None:
            lewat_user.append(email)
            continue
        lama = profil.get("user_cluster")
        if lama != baru:
            ubah_user.append((email, lama, baru))
            profil["user_cluster"] = baru

    print(f"PROFIL PENGGUNA ({len(users)} akun)")
    if ubah_user:
        for email, lama, baru in ubah_user:
            print(f"   {email:34s} klaster {lama} -> {baru}")
    else:
        print("   tidak ada yang perlu diubah")
    if lewat_user:
        print(f"   dilewati karena profil tidak lengkap: {', '.join(lewat_user)}")

    # -------------------------------------------------------------- riwayat --
    ubah_record, lewat_record = 0, 0
    for record in records:
        profil = record.get("profile")
        if not isinstance(profil, dict) or profil.get("user_cluster") is None:
            continue
        baru = klaster_baru(members, profil)
        if baru is None:
            lewat_record += 1
            continue
        if profil.get("user_cluster") != baru:
            profil["user_cluster"] = baru
            ubah_record += 1

    print(f"\nRIWAYAT KALORI ({len(records)} catatan)")
    print(f"   perlu diperbarui : {ubah_record}")
    if lewat_record:
        print(f"   dilewati (tidak lengkap) : {lewat_record}")

    total = len(ubah_user) + ubah_record
    if total == 0:
        print("\nSudah selaras dengan model aktif. Tidak ada yang ditulis.")
        return 0

    if not terapkan:
        print(f"\n{total} nilai akan berubah. Ini baru pratinjau.")
        print("Jalankan ulang dengan --terapkan untuk menuliskannya.")
        return 0

    berkas = cadangan_path()
    berkas.write_text(json.dumps(cadangan, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nCadangan nilai lama: {berkas}")

    save_users(users)
    save_records(CALORIE_STORE, records)
    print(f"{total} nilai diperbarui.")

    # Verifikasi ulang dari penyimpanan, bukan dari objek di memori.
    ulang_users = load_users()
    ulang_records = load_records(CALORIE_STORE)
    sisa = 0
    for user in ulang_users.values():
        profil = user.get("profile")
        if isinstance(profil, dict) and profil.get("user_cluster") is not None:
            baru = klaster_baru(members, profil)
            sisa += baru is not None and profil["user_cluster"] != baru
    for record in ulang_records:
        profil = record.get("profile")
        if isinstance(profil, dict) and profil.get("user_cluster") is not None:
            baru = klaster_baru(members, profil)
            sisa += baru is not None and profil["user_cluster"] != baru

    if sisa:
        print(f"PERINGATAN: {sisa} nilai masih tidak selaras setelah penulisan.")
        return 1
    print("Diverifikasi ulang dari penyimpanan: seluruh nilai selaras.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
