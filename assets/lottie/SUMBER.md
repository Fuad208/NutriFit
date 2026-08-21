# Sumber aset animasi

Berkas di folder ini TIDAK dibuat sendiri. Semuanya diunduh ulang oleh
`schema_data/fetch_lottie_assets.py`; jangan disunting manual, karena
suntingan akan hilang saat skrip itu dijalankan lagi.

## Animasi

Diambil dari koleksi **free animations** LottieFiles, yang berlisensi
[Lottie Simple License (FL 9.13.21)](https://lottiefiles.com/page/license):
bebas dipakai untuk keperluan pribadi maupun komersial, tanpa kewajiban
mencantumkan atribusi, dan tidak boleh dijual kembali sebagai animasi.
Atribusi di bawah dicantumkan atas kemauan sendiri, bukan karena
diwajibkan lisensi.

### `hero_login.json`

- halaman : https://lottiefiles.com/free-animation/t-plank-exercise-g5qVU6RPYY
- aset    : https://assets-v2.lottiefiles.com/a/dc68e41e-1189-11ee-a704-a3ee683b17ee/ygxWZwnPnw.lottie
- ukuran  : 985x885 px, 3 lapisan, 30 fps

### `hero_register.json`

- halaman : https://lottiefiles.com/free-animation/jumping-squats-9hzVV8Ohi6
- aset    : https://assets-v2.lottiefiles.com/a/d2a7325a-1170-11ee-b12a-1be3c918f379/IYB2y4zAOL.lottie
- ukuran  : 720x720 px, 1 lapisan, 25 fps

## Pemutar

`vendor/lottie_light.min.js` -- lottie-web 5.12.2 varian *light*,
diunduh dari https://cdnjs.cloudflare.com/ajax/libs/lottie-web/5.12.2/lottie_light.min.js
([MIT License](https://github.com/airbnb/lottie-web/blob/master/LICENSE.md)).

Disalin ke dalam proyek, bukan dipanggil dari CDN, supaya halaman login
tetap jalan tanpa internet dan tampilannya tidak bisa berubah diam-diam
saat CDN memperbarui versinya.
