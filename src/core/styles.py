"""Injeksi CSS kustom untuk tampilan NutriFit."""

from __future__ import annotations

import streamlit as st


def inject_css() -> None:
    """Sisipkan seluruh CSS aplikasi ke halaman; dipanggil sekali di awal tiap render."""
    st.markdown(
        """
        <style>
        :root {
            /* Merah utama sistem. Namanya "green" adalah sisa masa ketika tema
               aplikasi ini masih hijau; nilainya sudah merah sejak lama, dan
               nama variabelnya dibiarkan supaya satu perubahan warna tidak
               menyeret ratusan suntingan di berkas ini. */
            --green: #FF4646;
            /* Versi lebih gelap dari hue yang sama, dipakai untuk TEKS (judul
               brand, tautan). #FF4646 sendiri terlalu terang untuk teks di atas
               putih -- rasio kontrasnya di bawah ambang WCAG AA untuk teks
               ukuran biasa, sedangkan yang di bawah ini lolos. */
            --green-dark: #D92A2A;
            --ink: #17202a;
            --muted: #64748b;
            --line: #e5e7eb;
            --panel: #ffffff;
            --soft: #fef2f2;
            --amber: #f59e0b;
            --rose: #e11d48;
            /* Jalur kosong pada bar makro & cincin kalori: langkah muda dari
               hue yang sama, bukan abu-abu, supaya terisi vs sisa terbaca
               sebagai satu skala. */
            --track: #fde8e8;
            --canvas: #f7f8fa;

            /* SKALA TIPOGRAFI -- modular ratio 1,2 (minor third) dengan basis
               teks 18px. Tiap tingkat adalah tingkat di bawahnya dikali 1,2,
               sehingga perbedaan antar-tingkat selalu terasa sama besar dan
               hierarkinya terbaca tanpa perlu menebak.
                 18 x1,2 = 21,6 (h6)   21,6 x1,2 = 25,92 (h5)
                 25,92 x1,2 = 31,1 (h4)  31,1 x1,2 = 37,32 (h3)
                 37,32 x1,2 = 44,79 (h2) 44,79 x1,2 = 53,75 (h1) */
            --fs-h1: 53.75px;
            --fs-h2: 44.79px;
            --fs-h3: 37.32px;
            --fs-h4: 31.1px;
            --fs-h5: 25.92px;
            --fs-h6: 21.6px;
            --fs-body: 18px;
            --fs-small: 16px;
            --fs-micro: 12.5px;

            /* SKALA JARAK -- kelipatan 4px, dipakai sebagai satu-satunya sumber
               nilai padding/margin antar-komponen. Sebelumnya tiap komponen
               memakai angka rem sendiri-sendiri (.6rem, .85rem, .9rem, 1.1rem),
               sehingga jarak antar-kartu tidak pernah konsisten dan hierarkinya
               kabur. */
            --sp-1: 4px;
            --sp-2: 8px;
            --sp-3: 12px;
            --sp-4: 16px;
            --sp-5: 24px;
            --sp-6: 32px;
            --sp-7: 48px;
        }

        /* --- Tipografi dasar -------------------------------------------- */
        .stApp, .stApp p, .stApp li, .stApp label,
        .stApp div[data-testid="stMarkdownContainer"] p {
            font-size: var(--fs-body);
            line-height: 1.55;
        }
        .stApp h1 { font-size: var(--fs-h1); line-height: 1.12; margin-bottom: var(--sp-4); }
        .stApp h2 { font-size: var(--fs-h2); line-height: 1.16; margin-bottom: var(--sp-4); }
        .stApp h3 { font-size: var(--fs-h3); line-height: 1.2;  margin-bottom: var(--sp-3); }
        .stApp h4 { font-size: var(--fs-h4); line-height: 1.24; margin-bottom: var(--sp-3); }
        .stApp h5 { font-size: var(--fs-h5); line-height: 1.28; margin-bottom: var(--sp-2); }
        .stApp h6 { font-size: var(--fs-h6); line-height: 1.32; margin-bottom: var(--sp-2); }
        .stApp small, .stApp .stCaption,
        .stApp div[data-testid="stCaptionContainer"] p {
            font-size: var(--fs-small);
            line-height: 1.45;
        }

        /* --- Hierarki jarak ---------------------------------------------- */
        /* Aturannya satu: makin besar unit yang dipisahkan, makin besar
           jaraknya. Antar-elemen di dalam satu kartu paling rapat, antar-kartu
           lebih renggang, antar-bagian halaman paling renggang. */
        .stApp div[data-testid="stVerticalBlock"] { gap: var(--sp-3); }
        .stApp div[data-testid="stVerticalBlockBorderWrapper"] {
            margin-bottom: var(--sp-5);
        }
        .stApp div[data-testid="stVerticalBlockBorderWrapper"] > div > div[data-testid="stVerticalBlock"] {
            gap: var(--sp-2);
        }
        .stApp div[data-testid="stHorizontalBlock"] { gap: var(--sp-4); }
        .stApp hr { margin: var(--sp-6) 0; }
        .stApp .stButton > button { padding: var(--sp-3) var(--sp-4); }
        .stApp div[data-testid="stExpander"] { margin-block: var(--sp-4); }
        .stApp div[data-testid="stDataFrame"],
        .stApp div[data-testid="stTable"] { margin-block: var(--sp-4); }
        /* Latar halaman sengaja abu-abu sangat muda supaya kartu putih di
           dashboard punya bidang pemisah. Kartu di halaman lain sudah
           mendeklarasikan background putihnya sendiri (.metric-card,
           .meal-card, .workout-program, form), jadi ikut terangkat. */
        .stApp {
            background: var(--canvas);
            color: var(--ink);
        }
        section[data-testid="stSidebar"] {
            background: #ffffff;
            border-right: 1px solid var(--line);
        }
        /* Item navigasi non-aktif: polos, tanpa border, biar yang menonjol
           cuma item yang sedang dibuka. Aturan .stButton global (border merah)
           sengaja ditimpa di sini supaya sidebar tetap bersih. */
        section[data-testid="stSidebar"] .stButton > button {
            display: flex;
            justify-content: flex-start !important;
            text-align: left !important;
            background: transparent;
            border: 0;
            border-radius: 8px;
            color: var(--ink);
            font-weight: 600;
            padding: .6rem .85rem;
        }
        /* Perataan dipaksa dengan !important dan menyasar SEMUA turunan tombol.
           Alasannya: properti lain di aturan atas (background, border, color)
           sudah terbukti diterapkan, jadi selectornya memang cocok -- yang
           kalah hanya perataan, karena Streamlit membungkus label dalam
           container sendiri yang meratakan teks ke tengah dengan aturan yang
           lebih menang. Memakai `*` dan bukan nama class internal Streamlit
           supaya tidak rusak saat versinya naik (nama class emotion berubah
           tiap rilis, sedangkan struktur "label ada di dalam tombol" tetap).
           Padding kiri disamakan .85rem dengan .sidebar-active supaya teks
           tombol non-aktif lurus satu garis dengan teks pil aktif. */
        section[data-testid="stSidebar"] .stButton > button * {
            text-align: left !important;
            justify-content: flex-start !important;
            margin-left: 0 !important;
            margin-right: auto !important;
        }
        section[data-testid="stSidebar"] .stButton > button:hover {
            background: #f3f4f6;
            color: var(--ink);
        }
        /* Item aktif: pil merah penuh dengan teks putih. */
        .sidebar-active {
            background: var(--green);
            border: 0;
            border-radius: 8px;
            color: #ffffff;
            font-weight: 700;
            padding: .6rem .85rem;
            margin-bottom: .25rem;
        }
        .sidebar-spacer {
            height: .25rem;
        }
        .sidebar-divider {
            border-top: 1px solid var(--line);
            margin: 1rem 0 .75rem;
        }
        /* Penanda lokasi untuk halaman yang tidak punya item sendiri di nav
           (mis. Lupa Password, Tutorial Latihan) supaya user tetap tahu
           sedang berada di mana. */
        .sidebar-subpage {
            background: var(--soft);
            border: 1px dashed var(--green);
            border-radius: 8px;
            color: var(--green-dark);
            font-size: .82rem;
            font-weight: 600;
            margin-top: .35rem;
            padding: .45rem .85rem;
        }
        /* Logout dipisah secara visual dari navigasi: abu-abu netral, bukan
           merah, supaya tidak bersaing perhatian dengan item aktif.
           Kelas st-key-* otomatis dibuat Streamlit dari `key=` widget. */
        section[data-testid="stSidebar"] .st-key-sidebar_logout button {
            background: #f3f4f6;
            border: 1px solid var(--line);
            color: var(--ink);
            font-weight: 600;
        }
        section[data-testid="stSidebar"] .st-key-sidebar_logout button:hover {
            background: #e5e7eb;
            color: var(--ink);
        }
        .sidebar-brand {
            font-size: 1.45rem;
            font-weight: 800;
            color: var(--green-dark);
            margin: .5rem 0 0;
        }
        .sidebar-subtitle {
            color: var(--muted);
            font-size: .86rem;
            margin-bottom: 1.25rem;
        }
        .hero {
            padding: 2rem 0 1.25rem;
        }
        /* Tinggi SENGAJA dipatok, bukan mengikuti rasio gambar.
           Kalau tingginya ikut lebar (perilaku default <img> / st.image
           use_container_width), halaman login bisa "bergetar": lebar menyempit
           -> gambar memendek -> halaman memendek -> scrollbar hilang -> lebar
           melebar lagi -> gambar meninggi -> scrollbar muncul -> berulang tanpa
           henti. Paling kelihatan saat sidebar terbuka karena area utama lebih
           sempit dan pas berada di ambang munculnya scrollbar. Dengan tinggi
           tetap, tinggi halaman tidak lagi bergantung pada lebar, jadi diam. */
        .hero-image {
            display: block;
            width: 100%;
            height: 340px;
            object-fit: cover;
            border-radius: 8px;
            background: var(--line);
        }
        /* Ilustrasi hero dirender lewat st.image, jadi tinggi <img>-nya dipatok
           dari sini. object-fit: contain, BUKAN cover seperti .hero-image di
           atas: isi ilustrasi menyentuh tepi kanvasnya, jadi pemotongan
           sedikit pun langsung memakan kepala atau alat yang digambar. */
        div[class*="st-key-hero_gambar"] img {
            display: block;
            width: 100%;
            height: 340px;
            object-fit: contain;
            border-radius: 8px;
        }

        /* ================================================================
           HALAMAN MASUK & DAFTAR
           Kolom kiri-kanan 50/50: satu sisi animasi, satu sisi formulir.
           ================================================================ */
        /* Animasi Lottie dirender lewat st.iframe, jadi selalu berada di dalam
           <iframe>. Iframe tidak mewarisi latar halaman, sehingga tanpa aturan
           ini akan muncul kotak putih di atas latar --canvas yang abu-abu muda.
           Aplikasi ini tidak memakai iframe untuk hal lain, jadi selektornya
           sengaja tidak dipersempit. */
        .stApp iframe {
            background: transparent;
            border: 0;
        }
        .auth-title {
            font-size: var(--fs-h4);
            font-weight: 800;
            line-height: 1.15;
            color: var(--ink);
            margin: 0 0 var(--sp-1);
        }
        .auth-sub {
            color: var(--muted);
            font-size: var(--fs-small);
            margin: 0 0 var(--sp-5);
        }
        /* Label halaman masuk ditulis sendiri sebagai HTML (widget-nya memakai
           label_visibility="collapsed") karena Streamlit tidak punya penanda
           "wajib diisi", sedangkan rancangannya meminta tanda bintang merah.
           Margin hanya di ATAS: label dan kotak isiannya harus terbaca sebagai
           satu unit, sedangkan antar-pasangan perlu jarak. */
        .auth-label {
            font-weight: 700;
            color: var(--ink);
            font-size: var(--fs-small);
            margin: var(--sp-3) 0 0;
        }
        .auth-label .wajib {
            color: var(--green);
            margin-left: 1px;
        }
        div[class*="st-key-kartu_masuk"] div[data-testid="stVerticalBlock"] {
            gap: var(--sp-1);
        }
        /* Warna & garis tepi kotak isian TIDAK diatur di sini.
           Sumbernya tema Streamlit di .streamlit/config.toml
           (secondaryBackgroundColor, showWidgetBorder, borderColor), bukan CSS.
           Percobaan mengoreksinya dari sini pernah gagal tanpa jejak: latar
           kotak isian dipasang pada [data-testid="stTextInputRootElement"],
           bukan pada [data-baseweb="input"] yang tampak sebagai pembungkus
           terluar -- jadi aturannya menempel di elemen yang salah dan tidak
           mengubah apa pun. Kalau warna kotak isian perlu diubah lagi, ubah
           config.toml, jangan menambah aturan di berkas ini. */
        .auth-footer-teks {
            text-align: right;
            color: var(--muted);
            font-size: var(--fs-small);
        }
        /* Halaman daftar berkartu, dengan garis tepi merah muda dan sudut lebih
           tumpul daripada kartu biasa. Halaman masuk sengaja TIDAK berkartu --
           di sana isiannya memang bukan st.form, jadi tidak ada yang perlu
           dimatikan. */
        div[class*="st-key-kartu_daftar"] div[data-testid="stForm"] {
            border: 1px solid #F8B9B9;
            border-radius: 14px;
            padding: var(--sp-6) var(--sp-5) var(--sp-5);
        }
        /* Tombol "Masuk": merah penuh, teks putih. Warnanya ditulis eksplisit,
           tidak menumpang perhitungan kontras otomatis Streamlit untuk tombol
           `type="primary"`, supaya tampilannya tidak ikut berubah kalau
           heuristik itu berubah di versi berikutnya. Elemen di DALAM tombol
           ikut disasar karena label tombol Streamlit dibungkus <p> yang punya
           warnanya sendiri. */
        div[class*="st-key-tombol_masuk"] button {
            background: var(--green) !important;
            border: 1px solid var(--green) !important;
            min-height: 52px;
            font-weight: 700;
            border-radius: 8px;
        }
        div[class*="st-key-tombol_masuk"] button,
        div[class*="st-key-tombol_masuk"] button * {
            color: #ffffff !important;
        }
        div[class*="st-key-tombol_masuk"] button:hover {
            background: var(--green-dark) !important;
            border-color: var(--green-dark) !important;
        }
        /* Tombol kirim st.form TIDAK dibungkus .stButton melainkan
           [data-testid="stFormSubmitButton"], jadi aturan .stButton di bawah
           tidak pernah mengenainya dan harus ditulis terpisah. */
        div[class*="st-key-kartu_daftar"] [data-testid="stFormSubmitButton"] button {
            background: #ffffff;
            border: 1px solid var(--green);
            color: var(--ink);
            min-height: 52px;
            font-weight: 700;
            border-radius: 8px;
        }
        div[class*="st-key-kartu_daftar"] [data-testid="stFormSubmitButton"] button:hover {
            background: var(--soft);
            border-color: var(--green);
            color: var(--ink);
        }
        /* "Lupa Password?", "Daftar", "Masuk" di bawah formulir: tombol biasa
           yang ditampilkan sebagai tautan teks. Dipakai tombol, BUKAN <a>,
           karena Streamlit memaksa target="_blank" pada setiap tautan non-#hash
           di dalam markdown -- sebuah <a href="?page=..."> akan membuka tab
           baru, bukan berpindah halaman di tab yang sama. */
        div[class*="st-key-ke_lupa_sandi"] button,
        div[class*="st-key-ke_daftar"] button,
        div[class*="st-key-ke_masuk"] button {
            background: transparent !important;
            border-color: transparent !important;
            color: var(--green-dark) !important;
            font-weight: 700 !important;
            padding-left: 0 !important;
            padding-right: 0 !important;
            justify-content: flex-start !important;
        }
        div[class*="st-key-ke_lupa_sandi"] button p,
        div[class*="st-key-ke_daftar"] button p,
        div[class*="st-key-ke_masuk"] button p {
            color: var(--green-dark) !important;
        }
        /* Padding tombol dinolkan. Tanpa ini tombol yang tampil sebagai tautan
           tetap membawa padding tombol (12px atas-bawah dari aturan .stButton),
           jadi "Lupa Password?" terapung jauh dari kotak sandi di atasnya dan
           dari tombol Masuk di bawahnya -- dan pada baris kaki, teks
           "Belum punya akun?" jadi tidak sebaris dengan tautannya. */
        div[class*="st-key-ke_lupa_sandi"] button,
        div[class*="st-key-ke_daftar"] button,
        div[class*="st-key-ke_masuk"] button {
            padding-top: 0 !important;
            padding-bottom: 0 !important;
            min-height: 0 !important;
        }
        div[class*="st-key-ke_lupa_sandi"] {
            margin: var(--sp-2) 0 var(--sp-5);
        }
        /* Baris kaki: dua kolom yang bertemu di garis tengah. Jarak antar-kolom
           dirapatkan dari --sp-4 bawaan ke --sp-2 supaya "Belum punya akun?"
           dan "Daftar" terbaca sebagai satu kalimat, bukan dua blok terpisah. */
        div[class*="st-key-baris_kaki_auth"] {
            margin-top: var(--sp-5);
        }
        div[class*="st-key-baris_kaki_auth"] div[data-testid="stHorizontalBlock"] {
            gap: var(--sp-2);
        }
        /* Label bawaan Streamlit di kartu daftar: 18px terlalu besar untuk
           label isian -- ia bersaing dengan judul halaman. Diturunkan satu
           tingkat pada skala tipografi, sejajar dengan .auth-label di halaman
           masuk supaya kedua halaman terasa satu keluarga. */
        div[class*="st-key-kartu_daftar"] div[data-testid="stForm"] label,
        div[class*="st-key-kartu_daftar"] div[data-testid="stForm"] label p {
            font-size: var(--fs-small) !important;
        }
        .brand {
            font-size: 2.6rem;
            line-height: 1;
            font-weight: 800;
            color: var(--green-dark);
            letter-spacing: 0;
        }
        .subtle {
            color: var(--muted);
            font-size: 1rem;
        }
        .metric-card {
            border: 1px solid var(--line);
            background: #ffffff;
            border-radius: 8px;
            padding: 1rem;
            min-height: 118px;
        }
        .home-header {
            display: flex;
            align-items: flex-end;
            justify-content: space-between;
            gap: 1rem;
            margin: .25rem 0 1.25rem;
        }
        .home-title {
            font-size: 1.75rem;
            line-height: 1.15;
            font-weight: 800;
            color: var(--ink);
            margin: 0;
        }
        .home-kicker {
            color: var(--muted);
            font-size: .95rem;
            margin-top: .25rem;
        }
        .home-row-gap {
            height: .55rem;
        }

        /* ================== Dashboard beranda ==================
           Kartu dashboard dibuat dengan st.container(border=True, key="..."),
           dan Streamlit menempelkan kelas `st-key-<key>` pada elemen kontainer
           tersebut. Selector memakai [class*="st-key-..."] supaya satu aturan
           mencakup semua kartu sekeluarga (card_trend, card_activity, dst.)
           tanpa perlu mengandalkan nama kelas acak (emotion) bawaan Streamlit
           yang berubah tiap rilis. Kalaupun suatu saat kelas ini hilang,
           kartunya tetap tampil sebagai container ber-border bawaan Streamlit,
           bukan berantakan. */
        /* CATATAN: kelas st-key-* juga menempel pada pembungkus WIDGET, bukan
           cuma container. Karena itu prefix di bawah harus spesifik ke nama
           container -- [class*="st-key-onboard_"] saja akan ikut mengenai
           tombol ber-key onboard_action_* dan membuat tiap tombol dibingkai
           kartu kedua di dalam kartunya sendiri. */
        div[class*="st-key-card_"],
        div[class*="st-key-step_card_"],
        div[class*="st-key-onboard_panel"],
        div[class*="st-key-onboard_card_"] {
            background: var(--panel) !important;
            border: 1px solid var(--line) !important;
            border-radius: 14px !important;
            padding: 1.05rem 1.15rem !important;
            gap: .4rem !important;
        }
        /* Tinggi minimum disamakan per baris supaya kartu bersebelahan rata.
           Sengaja min-height (bukan height): kalau isinya lebih panjang kartu
           ikut memanjang, jadi label sumbu grafik / baris aktivitas tidak
           pernah terpotong. */
        /* Angkanya dipilih supaya kartu bersebelahan hampir rata bawah pada
           isi yang wajar: 440px = tinggi kartu aktivitas berisi 5 baris + tombol
           "Lihat Semua", dan juga tinggi kartu tren berisi ringkasan + grafik
           230px + baris "Lihat data". Kolom Streamlit tidak punya tinggi pasti,
           jadi height:100% TIDAK berlaku di sini (jatuh ke auto) -- penyeragaman
           harus lewat min-height seperti ini. */
        div[class*="st-key-card_trend"],
        div[class*="st-key-card_activity"] {
            min-height: 440px;
        }
        div[class*="st-key-card_calorie"],
        div[class*="st-key-card_fact"] {
            min-height: 292px;
        }
        /* Kartu langkah SENGAJA tidak diberi min-height. Container Streamlit
           adalah flex column, dan saat tingginya dipatok, blok teks di dalamnya
           ikut menyusut (flex-shrink) sementara tombol di bawahnya memuai --
           akibatnya teks status "Terbuka" tertimpa tombol. Ketiga kartu toh
           sudah sama tinggi karena .step-title dipatok dua baris di bawah.
           flex-shrink:0 dipasang sebagai pengaman kalau isinya bertambah. */
        div[class*="st-key-step_card_"] .stElementContainer,
        div[class*="st-key-onboard_card_"] .stElementContainer,
        div[class*="st-key-card_"] .stElementContainer {
            flex-shrink: 0;
        }
        .card-head {
            display: flex;
            align-items: flex-start;
            justify-content: space-between;
            gap: .75rem;
        }
        .card-head-icon {
            color: var(--muted);
            flex-shrink: 0;
        }
        .card-title {
            font-size: 1.12rem;
            font-weight: 800;
            line-height: 1.25;
            color: var(--ink);
        }
        .card-caption {
            color: var(--muted);
            font-size: .84rem;
            margin-top: .15rem;
        }
        .nf-icon {
            display: block;
        }

        /* --- Banner umpan balik di atas kartu langkah --- */
        .step-banner {
            display: flex;
            align-items: flex-start;
            gap: .8rem;
            background: var(--panel);
            border: 1px solid var(--line);
            border-left: 4px solid var(--green);
            border-radius: 12px;
            padding: .9rem 1.05rem;
            margin: .35rem 0 .95rem;
        }
        .step-banner-icon {
            flex-shrink: 0;
            margin-top: .12rem;
            color: var(--green);
        }
        .step-banner-text {
            color: var(--ink);
            font-size: .95rem;
            line-height: 1.5;
        }
        .step-banner.is-success {
            border-left-color: #16a34a;
        }
        .step-banner.is-success .step-banner-icon {
            color: #16a34a;
        }
        .step-banner.is-info {
            border-left-color: #0ea5e9;
        }
        .step-banner.is-info .step-banner-icon {
            color: #0ea5e9;
        }

        /* --- Kartu langkah 1/2/3 --- */
        .step-top {
            display: flex;
            align-items: center;
            justify-content: space-between;
        }
        .step-kicker {
            color: var(--muted);
            font-size: .72rem;
            font-weight: 800;
            letter-spacing: .09em;
        }
        .step-badge.is-done {
            color: #16a34a;
        }
        .step-badge.is-open {
            color: var(--green);
        }
        .step-badge.is-locked {
            color: #cbd5e1;
        }
        /* Judul dipatok dua baris supaya "Rekomendasi Latihan" (yang membungkus)
           tidak membuat tombol kartu ketiga turun sendiri dan jadi tidak sejajar
           dengan dua kartu di sebelahnya. */
        .step-title {
            font-size: 1.3rem;
            font-weight: 800;
            line-height: 1.2;
            margin-top: .45rem;
            min-height: 2.4em;
        }
        .step-status {
            font-size: .88rem;
            font-weight: 700;
            margin-bottom: .35rem;
        }
        .step-status.is-done {
            color: #16a34a;
        }
        .step-status.is-open {
            color: var(--green);
        }
        .step-status.is-locked {
            color: var(--muted);
        }
        /* Selector keturunan (bukan anak langsung): tombol yang punya `help`
           dibungkus Streamlit dalam host tooltip, jadi `.stButton > button`
           tidak mengenainya dan tombol "Terkunci" jadi 4px lebih pendek. */
        div[class*="st-key-step_card_"] .stButton button,
        div[class*="st-key-onboard_card_"] .stButton button {
            border-radius: 10px;
            font-weight: 700;
            min-height: 44px;
        }
        /* Langkah yang sudah selesai tampil netral (abu-abu), bukan merah,
           supaya perhatian tetap jatuh ke langkah yang belum dikerjakan.
           Status ikut dimasukkan ke `key` widget-nya, jadi bisa disasar dari
           CSS tanpa bergantung pada atribut internal tombol Streamlit. */
        [class*="st-key-step_action_"][class*="_done"] button {
            background: #f1f3f5 !important;
            border-color: var(--line) !important;
            color: #495057 !important;
        }
        [class*="st-key-step_action_"][class*="_locked"] button,
        [class*="st-key-onboard_action_"][class*="_locked"] button {
            border-color: var(--line) !important;
            color: #adb5bd !important;
        }

        /* --- Panel onboarding (user yang belum pernah hitung kalori) --- */
        .onboard-title {
            font-size: 1.28rem;
            font-weight: 800;
        }
        .onboard-caption {
            color: var(--muted);
            font-size: .95rem;
            margin: .3rem 0 .9rem;
        }
        .onboard-card {
            text-align: center;
            padding: .3rem 0 .1rem;
        }
        .onboard-badge {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 46px;
            height: 46px;
            border-radius: 999px;
            background: #f1f3f5;
            color: var(--ink);
            margin-bottom: .55rem;
        }
        .onboard-name {
            font-weight: 800;
            font-size: 1.02rem;
        }
        .onboard-hint {
            color: var(--muted);
            font-size: .83rem;
            margin-top: .18rem;
            min-height: 2.5em;
        }
        .onboard-card.is-locked {
            opacity: .5;
        }
        /* Kartu pertama = satu-satunya aksi yang tersedia, jadi dipertegas. */
        div[class*="st-key-onboard_card_1"] {
            border: 2px solid #1f2937 !important;
        }
        [class*="st-key-onboard_action_1"] button {
            background: #1f2937 !important;
            border-color: #1f2937 !important;
            color: #ffffff !important;
        }

        /* --- Kartu tren berat badan --- */
        .trend-summary {
            display: flex;
            align-items: center;
            flex-wrap: wrap;
            gap: .55rem;
            margin: .1rem 0 .3rem;
        }
        .trend-value {
            font-size: 1.9rem;
            font-weight: 800;
            line-height: 1.1;
        }
        .trend-chip {
            background: #f1f3f5;
            color: #495057;
            border-radius: 999px;
            padding: .2rem .6rem;
            font-size: .8rem;
            font-weight: 600;
        }
        .trend-delta {
            display: inline-flex;
            align-items: center;
            gap: .28rem;
            font-size: .82rem;
            font-weight: 700;
        }
        .trend-delta.is-up,
        .trend-delta.is-down {
            color: var(--green-dark);
        }
        .trend-delta.is-flat {
            color: var(--muted);
        }

        /* --- Klaim harian (menu dimakan & latihan dikerjakan) --- */
        .claim-progress {
            display: flex;
            flex-wrap: wrap;
            gap: .25rem;
            margin: .35rem 0 .55rem;
        }
        .claim-group {
            font-size: .78rem;
            font-weight: 800;
            letter-spacing: .04em;
            text-transform: uppercase;
            color: var(--muted);
            margin: .65rem 0 .1rem;
        }

        /* --- Daftar aktivitas --- */
        .activity-list {
            margin-top: .3rem;
        }
        .activity-row {
            display: flex;
            align-items: flex-start;
            gap: .7rem;
            padding: .5rem 0;
            border-bottom: 1px solid #f1f5f9;
        }
        .activity-row:last-child {
            border-bottom: 0;
        }
        .activity-icon {
            flex-shrink: 0;
            width: 34px;
            height: 34px;
            border-radius: 999px;
            background: var(--soft);
            color: var(--green);
            display: inline-flex;
            align-items: center;
            justify-content: center;
        }
        .activity-body {
            display: flex;
            flex-direction: column;
            min-width: 0;
        }
        .activity-name {
            font-weight: 700;
            font-size: .93rem;
            line-height: 1.3;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .activity-time {
            color: var(--muted);
            font-size: .79rem;
        }
        .activity-note {
            color: #94a3b8;
            font-size: .77rem;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        /* --- Cincin kalori & bar makro --- */
        .ring-wrap {
            position: relative;
            width: 152px;
            height: 152px;
            margin: .2rem auto;
        }
        .ring-svg {
            display: block;
            width: 100%;
            height: 100%;
        }
        .ring-track {
            fill: none;
            stroke: var(--track);
            stroke-width: 13;
        }
        .ring-value {
            fill: none;
            stroke: var(--green);
            stroke-width: 13;
            stroke-linecap: round;
        }
        .ring-label {
            position: absolute;
            inset: 0;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
        }
        .ring-number {
            font-size: 2rem;
            font-weight: 800;
            line-height: 1;
        }
        .ring-caption {
            color: var(--muted);
            font-size: .78rem;
            margin-top: .25rem;
        }
        .macro-row {
            margin-bottom: .9rem;
        }
        .macro-row:last-child {
            margin-bottom: 0;
        }
        .macro-meta {
            display: flex;
            align-items: center;
            justify-content: space-between;
            color: var(--ink);
            font-size: .88rem;
            margin-bottom: .32rem;
        }
        .macro-name {
            display: inline-flex;
            align-items: center;
            gap: .45rem;
            font-weight: 600;
        }
        .macro-dot {
            width: 8px;
            height: 8px;
            border-radius: 999px;
            background: var(--green);
            display: inline-block;
        }
        .progress-track {
            height: 8px;
            background: var(--track);
            border-radius: 999px;
            overflow: hidden;
        }
        .progress-fill {
            height: 100%;
            background: var(--green);
            border-radius: 999px;
        }

        /* --- Fakta kesehatan & state kosong --- */
        .fact-quote {
            background: var(--soft);
            border-radius: 12px;
            padding: 1rem;
            color: #7f1d1d;
            font-size: .92rem;
            line-height: 1.55;
            text-align: center;
            margin: .45rem 0 .2rem;
        }
        .empty-state {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            text-align: center;
            padding: 1.5rem .5rem;
        }
        .empty-icon {
            color: #cbd5e1;
            margin-bottom: .55rem;
        }
        .empty-title {
            font-weight: 700;
            color: #475569;
            font-size: .92rem;
        }
        .empty-hint {
            font-size: .81rem;
            color: #94a3b8;
            margin-top: .2rem;
        }

        /* Tombol teks (Lihat Semua / Lihat Fakta Lainnya) dan tombol titik-tiga:
           tanpa border merah bawaan aturan .stButton di bawah. */
        [class*="st-key-activity_history"] button,
        [class*="st-key-fact_next"] button,
        [class*="st-key-calorie_menu"] button {
            background: transparent !important;
            border-color: transparent !important;
            color: var(--green-dark) !important;
            font-weight: 700 !important;
        }
        [class*="st-key-calorie_menu"] button {
            color: var(--muted) !important;
            min-height: 34px;
        }
        .metric-label {
            color: var(--muted);
            font-size: .86rem;
            margin-bottom: .35rem;
        }
        .metric-value {
            font-size: 1.7rem;
            font-weight: 800;
            line-height: 1.1;
        }
        .meal-card, .exercise-card {
            border: 1px solid var(--line);
            background: #ffffff;
            border-radius: 8px;
            padding: 1rem;
            height: 100%;
        }
        .exercise-card {
            height: 320px;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            overflow: hidden;
        }
        /* TIDAK ada tinggi yang dipesan di sini. Kartu-kartu sebaris disamakan
           tingginya oleh st.container(height="stretch") di views/workout.py,
           bukan dengan menambal tinggi tiap bagian isinya -- lihat komentar di
           sana. Menambal tinggi blok ini pernah dicoba (min-height: 76px) dan
           justru melahirkan ruang kosong ~26px antara takaran dan chip pada
           kartu yang namanya cukup satu baris. */
        .exercise-head {
            margin-top: var(--sp-1);
        }
        .exercise-title {
            font-size: 1rem;
            line-height: 1.25;
            display: -webkit-box;
            -webkit-line-clamp: 2;
            -webkit-box-orient: vertical;
            overflow: hidden;
        }
        /* Nama asli (Inggris) di bawah judul Indonesia: itulah nama yang
           dipakai di video tutorial dan pencarian, jadi tetap perlu terbaca --
           tapi sebagai keterangan, bukan sebagai judul. */
        .exercise-original {
            color: var(--muted);
            font-size: .8rem;
            line-height: 1.2;
            margin: -.15rem 0 .4rem;
            display: -webkit-box;
            -webkit-line-clamp: 1;
            -webkit-box-orient: vertical;
            overflow: hidden;
        }
        /* Isinya inti gerakan satu kalimat (lihat id_inti_latihan), bukan prosa
           panjang. Klem dua baris dipertahankan sebagai batas atas kalau nanti
           ada kalimat yang lebih panjang, tapi tingginya TIDAK dikunci: kalimat
           satu baris tidak boleh menyisakan baris kosong. Perataan tombol kini
           ditangani container "stretch", bukan tinggi tetap di sini. */
        .exercise-desc {
            color: var(--muted);
            font-size: .9rem;
            line-height: 1.45;
            margin-top: var(--sp-3);
            display: -webkit-box;
            -webkit-line-clamp: 2;
            -webkit-box-orient: vertical;
            overflow: hidden;
        }
        .workout-program {
            border: 1px solid var(--line);
            background: #ffffff;
            border-radius: 8px;
            padding: 1rem;
            margin-top: 1rem;
            margin-bottom: 1.25rem;
        }
        .workout-program-title {
            font-weight: 800;
            font-size: 1.15rem;
            margin-bottom: .15rem;
        }
        /* Nomor urut latihan: kotak merah PENUH dengan angka putih. Versi
           sebelumnya berlatar merah muda dengan angka merah, jadi kontrasnya
           setara chip di bawahnya dan urutan program tidak langsung terbaca --
           padahal nomor inilah satu-satunya penanda kartu mana yang dikerjakan
           lebih dulu. */
        .workout-number {
            width: 38px;
            height: 38px;
            border-radius: 8px;
            background: var(--green);
            color: #ffffff;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 800;
        }
        /* Takaran latihan sekarang satu baris teks biasa tepat di bawah nama
           gerakan, bukan kotak merah di dasar kartu. Sebagai kotak berwarna,
           takaran menarik perhatian lebih kuat daripada nama gerakannya sendiri
           dan mendorong keterangan menjauh dari judul yang diterangkannya. */
        .workout-dose {
            color: var(--ink);
            font-size: var(--fs-small);
            line-height: 1.4;
            margin-top: .1rem;
        }
        .workout-dose-sep {
            color: var(--line);
            margin: 0 .2rem;
        }
        .workout-card-row {
            margin-bottom: 1rem;
        }
        /* Kartu latihan. Latar putihnya WAJIB ditulis: st.container(border=True)
           hanya memberi garis tepi, tidak memberi warna isi, jadi tanpa aturan
           ini latar halaman (--canvas, abu-abu sangat muda) tembus ke dalam
           kartu dan kartunya tidak terbaca sebagai bidang terpisah.
           Kartu dashboard sudah lebih dulu menemui hal yang sama -- lihat blok
           st-key-card_ di bagian "Dashboard beranda" di atas, yang memakai
           `background: var(--panel) !important` untuk alasan yang sama.
           Prefix-nya "kartu_latihan_" (bukan "card_"), jadi aturan di sana
           tidak ikut mengenainya. */
        div[class*="st-key-kartu_latihan_"] {
            background: var(--panel) !important;
            border: 1px solid var(--line) !important;
            border-radius: 12px !important;
            padding: 1.05rem 1.15rem !important;
        }
        /* Tombol "Ganti Latihan": ringkas dan SATU BARIS. Sebelumnya dilebarkan
           sepenuh kolomnya (use_container_width), dan pada kolom sesempit itu
           labelnya pecah jadi "Ganti" / "Latihan" -- tinggi kepala kartu jadi
           dua kali lipat dan menekan seluruh isi di bawahnya. */
        div[class*="st-key-workout_switch_"] button {
            white-space: nowrap;
            padding: var(--sp-2) var(--sp-3) !important;
            min-height: 36px;
            font-size: var(--fs-small);
            font-weight: 600;
        }
        /* Jarak dari keterangan ke tombol "Lihat Panduan" di dasar kartu. */
        div[class*="st-key-workout_detail_"] {
            margin-top: var(--sp-3);
        }
        /* Chip pada kartu latihan berlatar PUTIH, bukan merah muda seperti chip
           di halaman lain: di rancangan, chip di sini adalah garis tepi saja.
           Disasar lewat .chip-row, yang hanya dipakai kartu latihan, supaya
           chip di halaman menu dan tutorial tidak ikut berubah. */
        .chip-row .chip {
            background: #ffffff;
            border-color: #FBC4C4;
            color: var(--green-dark);
        }
        /* Penanda latihan yang diambil dari level di atas level pengguna.
           Warnanya sengaja berbeda dari chip lain di baris yang sama: chip
           lainnya sekadar keterangan, yang ini peringatan. */
        .chip-row .chip.chip-warning {
            background: #FFF4E5;
            border-color: #F0B357;
            color: #8E5405;
            font-weight: 600;
        }
        .meal-row {
            border: 1px solid var(--line);
            background: #ffffff;
            border-radius: 8px;
            padding: .85rem;
            margin-bottom: .75rem;
        }
        /* Judul slot makan: nama slot + proporsi + kuota kalorinya. Kuota ikut
           ditulis di judul supaya angka porsi tiap menu di bawahnya punya
           konteks -- tanpa itu "250 kkal" terbaca sebagai angka lepas. */
        .slot-head {
            display: flex;
            align-items: center;
            flex-wrap: wrap;
            gap: .35rem;
            margin: 1.15rem 0 .5rem;
        }
        .slot-name {
            font-size: 1.25rem;
            font-weight: 800;
            margin-right: .35rem;
        }
        /* Kotak gambar menu. Ikon piring digambar sebagai LATAR kotaknya, dan
           foto aslinya ditumpuk di atas. Tautan gambar yang mati tidak
           menggambar apa pun, jadi yang tersisa adalah ikon ini -- bukan ikon
           "gambar rusak" bawaan browser. Menu tanpa gambar sama sekali memakai
           kotak yang sama, sehingga tinggi barisnya tetap seragam. */
        .meal-image {
            position: relative;
            width: 84px;
            height: 84px;
            border-radius: 8px;
            border: 1px solid var(--line);
            background-color: var(--soft);
            background-image: url("data:image/svg+xml;utf8,\
<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' \
stroke='%23e11d48' stroke-width='1.4' stroke-linecap='round' stroke-linejoin='round'>\
<path d='M3 11h18'/><path d='M12 11V7'/>\
<path d='M5 11a7 7 0 0 0 14 0'/><path d='M4 19h16'/></svg>");
            background-repeat: no-repeat;
            background-position: center;
            background-size: 38px 38px;
            overflow: hidden;
            flex-shrink: 0;
        }
        .meal-image img {
            position: absolute;
            inset: 0;
            width: 100%;
            height: 100%;
            object-fit: cover;
            border-radius: 7px;
        }
        .chip {
            display: inline-block;
            border: 1px solid #fecaca;
            background: #fef2f2;
            color: #991b1b;
            border-radius: 999px;
            padding: .18rem .55rem;
            font-size: .78rem;
            margin-right: .25rem;
            margin-bottom: .25rem;
        }
        .danger-chip {
            border-color: #fecdd3;
            background: #fff1f2;
            color: #9f1239;
        }
        .food-title {
            font-weight: 750;
            font-size: 1.02rem;
            margin-bottom: .35rem;
        }
        /* Jarak ke takaran di bawahnya sengaja rapat: keduanya menerangkan
           gerakan yang sama, jadi harus terbaca sebagai satu kesatuan. */
        .exercise-title {
            font-weight: 750;
            font-size: 1.02rem;
            margin-bottom: .1rem;
        }
        .section-title {
            font-size: 1.45rem;
            font-weight: 800;
            margin: 1rem 0 .35rem;
        }
        .form-section-title {
            color: var(--ink);
            font-size: 1rem;
            font-weight: 800;
            margin: .2rem 0 .15rem;
        }
        .form-section-caption {
            color: var(--muted);
            font-size: .88rem;
            margin: 0 0 .65rem;
        }
        div[data-testid="stForm"] {
            border: 1px solid var(--line);
            border-radius: 8px;
            background: #ffffff;
            padding: 1.1rem 1.15rem 1.25rem;
        }
        div[data-testid="stForm"] div[data-testid="stVerticalBlock"] {
            gap: .55rem;
        }
        div[data-testid="stForm"] label {
            color: var(--ink);
            font-weight: 750;
        }
        div[data-testid="stForm"] input,
        div[data-testid="stForm"] select {
            min-height: 42px;
        }
        div[data-testid="stForm"] [data-baseweb="input"],
        div[data-testid="stForm"] [data-baseweb="select"] > div,
        div[data-testid="stForm"] [data-baseweb="radio"] {
            border-radius: 8px;
        }
        div[data-testid="stForm"] [data-testid="stFormSubmitButton"] {
            margin-top: .35rem;
        }
        .stButton > button {
            border-radius: 8px;
            border: 1px solid var(--green);
        }

        /* ================================================================
           PEMETAAN KE SKALA TIPOGRAFI
           Ditaruh paling akhir supaya menang atas nilai lama tanpa harus
           menyunting puluhan deklarasi yang tersebar. Tiap kelas dipetakan ke
           TINGKAT pada skala, bukan ke angka lepas -- itu yang membuat
           hierarkinya konsisten di seluruh halaman.
           ================================================================ */
        .brand              { font-size: var(--fs-h3); line-height: 1.2; margin-bottom: var(--sp-2); }
        .sidebar-brand      { font-size: var(--fs-h6); line-height: 1.3; }
        .section-title      { font-size: var(--fs-h5); margin: var(--sp-6) 0 var(--sp-3); }
        .form-section-title { font-size: var(--fs-h6); margin: var(--sp-5) 0 var(--sp-1); }
        .card-title,
        .slot-name          { font-size: var(--fs-h6); line-height: 1.3; }
        .food-title,
        .exercise-title     { font-size: var(--fs-body); line-height: 1.4; font-weight: 700; }
        .claim-group        { font-size: var(--fs-small); margin: var(--sp-4) 0 var(--sp-2); }
        .ring-number        { font-size: var(--fs-h4); line-height: 1.1; }
        .card-caption,
        .form-section-caption,
        .subtle             { font-size: var(--fs-small); line-height: 1.45; }
        .chip               { font-size: var(--fs-micro); line-height: 1.6; }
        .chip-row           { font-size: var(--fs-small); margin-top: var(--sp-3); }

        /* Antar-blok utama halaman lebih renggang daripada antar-elemen di
           dalamnya, supaya mata bisa mengelompokkan isinya tanpa garis bantu. */
        .brand + div[data-testid="stCaptionContainer"] { margin-bottom: var(--sp-5); }
        .slot-head { margin: var(--sp-6) 0 var(--sp-3); }

        /* Kartu preferensi adalah blok BARU setelah baris ringkasan target,
           bukan lanjutannya. Aturan gap antar-kartu (--sp-5) terlalu rapat di
           sini karena yang dipisahkan bukan dua kartu sederajat, melainkan dua
           bagian halaman: "ini targetmu" lalu "sekarang pilih maumu". */
        div[class*="st-key-card_protein_pref"] {
            margin-top: var(--sp-6) !important;
        }
        /* Judul kartu menempel ke tepi atas kartunya; beri jarak sebelum
           deretan pilihan supaya keduanya tidak terbaca sebagai satu blok. */
        div[class*="st-key-card_protein_pref"] .card-title {
            margin-bottom: var(--sp-3);
        }
        /* Antar-baris pilihan lebih longgar sedikit daripada antar-kolom,
           supaya grid-nya terbaca baris demi baris. */
        div[class*="st-key-card_protein_pref"] div[data-testid="stHorizontalBlock"] {
            margin-bottom: var(--sp-2);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
