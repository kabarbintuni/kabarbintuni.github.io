#!/usr/bin/env python3
"""
Mesin Radar & Bank Berita Kredibel — Kabar Bintuni (@kabarbintuni & @kabar.bintuni)
Menarik berita terupdate dari sumber resmi & media terverifikasi untuk wilayah:
  - Teluk Bintuni (target kuota 60%)
  - Papua Barat & Papua Barat Daya (target kuota 25%)
  - Papua Umum yang positif / berdampak luas (target kuota 15%)

Dilengkapi 3 Gerbang Redaksi Otomatis sesuai SOP Kabar Bintuni:
  1. Gerbang Anti-Sensitif (blokir konflik bersenjata, SARA, politik partisan, kekerasan grafis)
  2. Gerbang Dedup & Klaster Multi-Sumber (mengukur dampak + kredibilitas objektif)
  3. Gerbang Kuota Wilayah 60/25/15 + Auto-Draft gaya Pop-Vector Kaka Kabar & 5 Tagar SEO

Zero external dependencies (Python 3.10+ stdlib murni) agar cepat & stabil di GitHub Actions.
"""
from __future__ import annotations

import base64
import concurrent.futures
import email.utils
import hashlib
import html
import json
import os
import re
import ssl
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

WIT = timezone(timedelta(hours=9))
ROOT_DIR = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT_DIR / "bank-berita" / "data"
JSON_OUT = OUT_DIR / "bank-berita.json"
MD_OUT = OUT_DIR / "RINGKASAN-HARIAN.md"

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"

# ---------------------------------------------------------------------------
# 1. Konfigurasi Sumber Berita (RSS Resmi & Google News Terkurasi)
# ---------------------------------------------------------------------------
def _gnews_url(query: str) -> str:
    q = urllib.parse.quote(query, safe="")
    return f"https://news.google.com/rss/search?q={q}&hl=id&gl=ID&ceid=ID:id"


FEEDS: list[dict[str, str]] = [
    {
        "id": "bintuni_utama",
        "label": "Google News — Teluk Bintuni (14 hari)",
        "wilayah_hint": "bintuni",
        "url": _gnews_url('"Teluk Bintuni" OR Bintuni when:14d'),
    },
    {
        "id": "bintuni_layanan",
        "label": "Google News — Layanan, Loker, BPS & Ekonomi Bintuni (30 hari)",
        "wilayah_hint": "bintuni",
        "url": _gnews_url(
            '("Teluk Bintuni" OR Bintuni) (loker OR lowongan OR Disnaker OR DisTransnaker '
            'OR BPS OR PLN OR BMKG OR jalan OR kapal OR pasar OR UMKM OR beasiswa OR LNG OR Tangguh) when:30d'
        ),
    },
    {
        "id": "databoks_bps",
        "label": "Databoks / Data Statistik Teluk Bintuni & Papua Barat",
        "wilayah_hint": "bintuni",
        "url": _gnews_url('site:databoks.katadata.co.id ("Teluk Bintuni" OR "Papua Barat") when:45d'),
    },
    {
        "id": "papua_barat_pbd",
        "label": "Google News — Papua Barat & Papua Barat Daya (7 hari)",
        "wilayah_hint": "papua_barat",
        "url": _gnews_url('("Papua Barat" OR "Papua Barat Daya") when:7d'),
    },
    {
        "id": "rri_papua_barat",
        "label": "RRI — Papua Barat, PBD & Teluk Bintuni (7 hari)",
        "wilayah_hint": "papua_barat",
        "url": _gnews_url('site:rri.co.id (Bintuni OR "Papua Barat" OR "Papua Barat Daya") when:7d'),
    },
    {
        "id": "papua_positif",
        "label": "Google News — Papua (Ekonomi, Infrastruktur, Prestasi, Budaya, Wisata)",
        "wilayah_hint": "papua",
        "url": _gnews_url(
            'Papua (prestasi OR wisata OR budaya OR ekonomi OR infrastruktur OR beasiswa '
            'OR UMKM OR kuliner OR festival OR penerbangan OR pelayaran OR inovasi) when:5d'
        ),
    },
    {
        "id": "bmkg_nowcast",
        "label": "BMKG — Peringatan Dini Cuaca Resmi",
        "wilayah_hint": "bintuni",
        "url": "https://www.bmkg.go.id/alerts/nowcast/id/rss.xml",
    },
    {
        "id": "rss_mediaprorakyat",
        "label": "Media Pro Rakyat — RSS Langsung Teluk Bintuni",
        "wilayah_hint": "bintuni",
        "source_override": "Media Pro Rakyat",
        "url": "https://mediaprorakyat.com/feed/",
    },
    {
        "id": "rss_papuadalamberita",
        "label": "Papua Dalam Berita — RSS Langsung Papua Barat",
        "wilayah_hint": "papua_barat",
        "source_override": "Papua Dalam Berita",
        "url": "https://papuadalamberita.com/feed/",
    },
    {
        "id": "rss_taburapos",
        "label": "Tabura Pos — RSS Langsung Papua Barat",
        "wilayah_hint": "papua_barat",
        "source_override": "Tabura Pos",
        "url": "https://taburapos.co/feed/",
    },
]

# Akun IG & Facebook lokal prioritas pilihan redaksi (untuk Panel Pantau Cepat & Paste-Parser)
SOCIAL_WATCHLIST: list[dict[str, str]] = [
    {
        "id": "ig_explore_bintuni",
        "platform": "Instagram",
        "nama": "Explore Bintuni",
        "handle": "@explorebintuni",
        "url": "https://www.instagram.com/explorebintuni/",
        "fokus": "Wisata, budaya, sudut kota, dan agenda warga Teluk Bintuni",
        "default_cat": "EVENT & WARGA",
        "default_lokasi": "Teluk Bintuni, Papua Barat",
    },
    {
        "id": "ig_bps_bintuni",
        "platform": "Instagram",
        "nama": "BPS Teluk Bintuni",
        "handle": "@bps_telukbintuni",
        "url": "https://www.instagram.com/bps_telukbintuni/",
        "web_resmi": "https://telukbintunikab.bps.go.id/",
        "fokus": "Data resmi inflasi, harga bahan pokok, statistik penduduk & bahan Bedah Fakta",
        "default_cat": "BEDAH FAKTA",
        "default_lokasi": "Teluk Bintuni, Papua Barat",
    },
    {
        "id": "ig_info_pabar_pbd",
        "platform": "Instagram",
        "nama": "Info Pabar & PBD",
        "handle": "@info.pabar.pbd",
        "url": "https://www.instagram.com/info.pabar.pbd/",
        "fokus": "Kabar cepat & tren regional Papua Barat serta Papua Barat Daya",
        "default_cat": "KABAR TERKINI",
        "default_lokasi": "Papua Barat & PBD",
    },
    {
        "id": "fb_distransnaker",
        "platform": "Facebook",
        "nama": "DisTransnaker Kab. Teluk Bintuni",
        "handle": "DisTransnaker Kab. Teluk Bintuni",
        "url": "https://www.facebook.com/search/top?q=DisTransnaker%20Kab.%20Teluk%20Bintuni",
        "fokus": "Info resmi lowongan kerja (loker), pelatihan kerja, Kartu AK-1 & rekrutmen lokal",
        "default_cat": "KULINER & UMKM",
        "default_lokasi": "Bintuni Kota, Papua Barat",
    },
]

# ---------------------------------------------------------------------------
# 2. Sistem Kredibilitas Sumber (Tier 1 = Resmi, Tier 2 = Terverifikasi, Tier 3 = Cek Silang)
# ---------------------------------------------------------------------------
TIER1_PATTERNS = [
    "bmkg", "bps", "databoks", "antara", "rri.co.id", "lpp rri", "rri ",
    "ombudsman", "bpjs", "kementerian", "kemen", "pemerintah provinsi",
    "pemkab", "pemprov", "diskominfo", "kominfo", "basarnas", "bnpb",
    "bank indonesia", "ojk", "pertamina", "pln", "pelni", "go.id",
    "tribratanews",
]

TIER2_PATTERNS = [
    "kompas", "tempo", "detik", "cnn indonesia", "cnbc indonesia", "liputan6",
    "republika", "tribun", "bisnis.com", "kontan", "kumparan", "katadata",
    "mediaindonesia", "sindonews", "okezone", "suara.com", "merdeka.com",
    "idntimes", "viva.co.id", "metrotvnews", "inews", "tvonenews", "jpnn",
    "jubi", "tabura pos", "taburapos", "papua kini", "papuakini",
    "koreri", "kapabar", "media pro rakyat", "mediaprorakyat",
    "papuadalamberita", "papua dalam berita", "jagat papua", "topbnews",
    "cepos", "cenderawasih pos", "radarsorong", "kabarpapua", "pasificpos",
    "infopublik", "mongabay", "narasi", "tirto", "berita papua",
]

SPAM_SOURCE_PATTERNS = [
    "qoo10", "blogspot", "wordpress.com", "shopee", "tokopedia", "lazada",
]

# ---------------------------------------------------------------------------
# 3. Gerbang Anti-Sensitif (Red-Flag Gate — Wajib sesuai SOP Kabar Bintuni)
# ---------------------------------------------------------------------------
RED_FLAG_RULES: list[tuple[str, list[str]]] = [
    (
        "Konflik Bersenjata / Keamanan Papua",
        [
            r"\bkkb\b", r"\bopm\b", r"\btpnpb\b", r"\bseparatis\b", r"\bkontak tembak\b",
            r"\bbaku tembak\b", r"\bpenembakan\b", r"\bditembak\b", r"\bpenyerangan pos\b",
            r"\bteroris\b", r"\bsandera\b", r"\bdisandera\b", r"\bkelompok kriminal bersenjata\b",
            r"\bmerdeka papua\b", r"\bknpb\b", r"\bulmwp\b",
        ],
    ),
    (
        "Kekerasan Grafis / Kriminalitas Berat / Korban",
        [
            r"\bpembunuhan\b", r"\bdibunuh\b", r"\bmembunuh\b", r"\bdibacok\b", r"\bpenikaman\b",
            r"\bditikam\b", r"\bmutilasi\b", r"\bmayat\b", r"\bjenazah\b", r"\bbunuh diri\b",
            r"\bpemerkosaan\b", r"\bdiperkosa\b", r"\bpencabulan\b", r"\bdicabul", r"\basusila\b",
            r"\bberdarah\b", r"\btewas mengenaskan\b", r"\bkorban tewas\b", r"\bmeninggal dunia\b",
            r"\bdirudapaksa\b", r"\bnarkoba\b", r"\bsabu\b", r"\bganja\b",
        ],
    ),
    (
        "Politik Partisan / Partai / Konflik Pejabat",
        [
            r"\bppp\b", r"\bhanura\b", r"\bpdip\b", r"\bpdi-p\b", r"\bgolkar\b", r"\bgerindra\b",
            r"\bnasdem\b", r"\bpkb\b", r"\bpks\b", r"\bpartai\b", r"\bparpol\b", r"\bcaleg\b",
            r"\bpilkada\b", r"\bpemilu\b", r"\bkampanye\b", r"\bsengketa pilkada\b",
            r"\bkubu\b", r"\bdukungan politik\b", r"\bgabung hanura\b", r"\bkader partai\b",
            r"\bkorupsi\b", r"\btersangka korupsi\b", r"\bditahan kpk\b", r"\bkejati.*tahan\b",
        ],
    ),
    (
        "SARA / Kerusuhan / Demo Ricuh",
        [
            r"\bbentrok\b", r"\bkerusuhan\b", r"\bdemo ricuh\b", r"\banarkis\b", r"\bpenistaan\b",
            r"\bsara\b", r"\bbakar kantor\b", r"\bpalang jalan ricuh\b", r"\btawuran\b",
        ],
    ),
]

# Kata kunci sinyal positif (berdampak langsung ke warga usia 18-34)
HIGH_IMPACT_KEYWORDS = [
    "loker", "lowongan", "rekrutmen", "pelatihan", "kerja", "umkm", "kuliner", "pasar",
    "harga", "inflasi", "bbm", "solar", "listrik", "pln", "sinyal", "internet", "telkomsel",
    "jalan", "jembatan", "pelabuhan", "kapal", "pelni", "bandara", "pesawat", "penerbangan",
    "cuaca", "hujan lebat", "gelombang tinggi", "bmkg", "banjir", "longsor",
    "beasiswa", "kuliah", "sekolah", "prestasi", "juara", "olahraga", "turnamen", "festival",
    "wisata", "budaya", "mangrove", "pala", "kopi", "sagu", "bps", "databoks",
    "lng", "tangguh", "migas", "pupuk", "pelayanan publik", "kesehatan", "puskesmas", "rsud",
]

CEREMONIAL_PENALTY_KEYWORDS = [
    "rapat koordinasi", "rakor", "audiensi", "kunjungan kerja", "resmi dibuka",
    "sambutan", "hadiri rapat", "apel pagi", "silaturahmi", "studi banding",
    "kawal opini", "tinjau kesiapsiagaan", "serah terima jabatan", "sertijab",
]

STOPWORDS = {
    "yang", "dan", "di", "ke", "dari", "untuk", "pada", "dengan", "dalam", "ini", "itu",
    "oleh", "agar", "akan", "telah", "sudah", "saat", "bagi", "atas", "para", "juga",
    "bisa", "jadi", "kini", "baru", "tahun", "kabupaten", "provinsi", "papua", "barat",
    "teluk", "bintuni", "kota", "warga", "masyarakat", "pemerintah", "resmi", "daya",
}

BULAN_ID = [
    "", "Jan", "Feb", "Mar", "Apr", "Mei", "Jun",
    "Jul", "Agu", "Sep", "Okt", "Nov", "Des",
]

# ---------------------------------------------------------------------------
# 4. Utilitas Pembersihan, Wilayah, Kategori & Auto-Draft
# ---------------------------------------------------------------------------
def clean_html_text(raw: str) -> str:
    if not raw:
        return ""
    text = html.unescape(raw)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def strip_source_suffix(title: str, source_name: str) -> str:
    t = clean_html_text(title)
    if source_name:
        esc = re.escape(source_name.strip())
        t = re.sub(rf"\s*[-–—|]\s*{esc}\s*$", "", t, flags=re.I)
    # Bersihkan akhiran portal umum (" - Kompas.com", " | RRI.co.id")
    t = re.sub(r"\s*[-–—|]\s*[A-Za-z0-9.\s]{2,35}(?:\.com|\.co\.id|\.id|\.net|News|Pos|TV|RI)\s*$", "", t, flags=re.I)
    return t.strip(" -–—|")


def parse_pub_date(raw: str) -> datetime:
    if raw:
        try:
            dt = email.utils.parsedate_to_datetime(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(WIT)
        except Exception:
            pass
    return datetime.now(WIT)


def format_tanggal_wit(dt: datetime) -> str:
    return f"{dt.day} {BULAN_ID[dt.month]} {dt.year}"


def classify_source_tier(source_name: str, link: str) -> tuple[int, str]:
    blob = f"{source_name} {link}".lower()
    if any(p in blob for p in TIER1_PATTERNS):
        return 1, "Resmi / Instansi"
    if any(p in blob for p in TIER2_PATTERNS):
        return 2, "Media Terverifikasi"
    return 3, "Perlu Cek Silang"


def detect_red_flag(title: str, summary: str) -> str | None:
    text = f"{title} {summary}".lower()
    for reason, patterns in RED_FLAG_RULES:
        for pat in patterns:
            if re.search(pat, text, flags=re.I):
                return reason
    return None


def detect_wilayah(title: str, summary: str, hint: str) -> str:
    text = f"{title} {summary}".lower()
    bintuni_terms = [
        "bintuni", "sumuri", "babo", "aranday", "wamesa", "merdey", "moskona",
        "manimeri", "tuhiba", "dataran beimes", "tandia", "kaitaro", "kuri",
        "tembuni", "fafuwar", "aroy", "tomu", "kamundan", "weryagar", "yakora",
        "tangguh", "sp1", "sp2", "sp3", "sp4", "sp5", "argosigemerai", "wesiri",
    ]
    if any(w in text for w in bintuni_terms):
        return "bintuni"
    pabar_terms = [
        "papua barat", "manokwari", "fakfak", "kaimana", "teluk wondama", "wondama",
        "pegunungan arfak", "pegaf", "mansel", "manokwari selatan",
        "papua barat daya", "sorong", "raja ampat", "maybrat", "tambrauw",
    ]
    if any(w in text for w in pabar_terms):
        return "papua_barat"
    if "papua" in text:
        return "papua"
    return hint


def is_relevant_to_papua(title: str, summary: str) -> bool:
    text = f"{title} {summary}".lower()
    geo_words = [
        "bintuni", "papua", "manokwari", "sorong", "fakfak", "kaimana", "wondama",
        "raja ampat", "jayapura", "merauke", "timika", "mimika", "nabire", "biak",
        "tangguh", "sumuri", "babo", "cenderawasih", "pabar", "pbd",
    ]
    return any(g in text for g in geo_words)


def detect_lokasi_label(title: str, summary: str, wilayah: str) -> str:
    text = f"{title} {summary}".lower()
    spots = [
        ("sp5", "SP5, Teluk Bintuni"),
        ("sp4", "SP4, Teluk Bintuni"),
        ("sp3", "SP3, Teluk Bintuni"),
        ("sp2", "SP2, Teluk Bintuni"),
        ("sp1", "SP1, Teluk Bintuni"),
        ("sumuri", "Distrik Sumuri, Teluk Bintuni"),
        ("babo", "Distrik Babo, Teluk Bintuni"),
        ("tangguh", "Teluk Bintuni, Papua Barat"),
        ("manimeri", "Manimeri, Teluk Bintuni"),
        ("argosigemerai", "Argosigemerai, Teluk Bintuni"),
        ("moskona", "Moskona, Teluk Bintuni"),
        ("merdey", "Merdey, Teluk Bintuni"),
        ("bintuni", "Teluk Bintuni, Papua Barat"),
        ("manokwari", "Manokwari, Papua Barat"),
        ("fakfak", "Fakfak, Papua Barat"),
        ("kaimana", "Kaimana, Papua Barat"),
        ("wondama", "Teluk Wondama, Papua Barat"),
        ("papua barat daya", "Papua Barat Daya"),
        ("sorong", "Sorong, Papua Barat Daya"),
        ("raja ampat", "Raja Ampat, Papua Barat Daya"),
        ("papua barat", "Papua Barat"),
        ("jayapura", "Jayapura, Papua"),
        ("mimika", "Mimika, Papua Tengah"),
        ("timika", "Timika, Papua Tengah"),
        ("merauke", "Merauke, Papua Selatan"),
    ]
    for kw, label in spots:
        if kw in text:
            return label
    if wilayah == "bintuni":
        return "Teluk Bintuni, Papua Barat"
    if wilayah == "papua_barat":
        return "Papua Barat"
    return "Tanah Papua"


# Indeks kategori cocok 100% dengan CATEGORIES di editor/index.html:
# 0 = KABAR TERKINI | 1 = BREAKING NEWS | 2 = KULINER & UMKM | 3 = BEDAH FAKTA | 4 = EVENT & WARGA
def _has_any_word(text: str, words: list[str]) -> bool:
    return any(re.search(rf"\b{re.escape(w)}\b", text) for w in words)


def detect_category(title: str, summary: str, source_name: str) -> tuple[int, str, str]:
    title_l = title.lower()
    text = f"{title} {summary} {source_name}".lower()
    if _has_any_word(text, ["bmkg", "peringatan dini", "hujan lebat", "gelombang tinggi", "gempa", "banjir", "longsor", "putus total", "darurat", "evakuasi", "cuaca ekstrem"]):
        return 1, "BREAKING NEWS", "#cuacabintuni"
    if _has_any_word(text, ["databoks", "bps", "perkapita", "statistik", "inflasi", "ekonomi papua", "triwulan", "indeks", "survei", "mangrove", "sejarah", "harga pangan"]):
        return 3, "BEDAH FAKTA", "#bedahfaktabintuni"
    if _has_any_word(title_l, ["umkm", "kuliner", "loker", "lowongan", "rekrutmen", "disnaker", "distransnaker", "pelatihan kerja", "wirausaha", "kopi", "pala", "produk lokal", "ekraf", "ekonomi kreatif"]):
        return 2, "KULINER & UMKM", "#umkmbintuni"
    if _has_any_word(title_l, ["festival", "turnamen", "lomba", "event", "konser", "pameran", "komunitas", "seni", "olahraga", "futsal", "sepak bola", "biliar", "wisata", "literasi", "beasiswa", "prestasi", "juara"]):
        return 4, "EVENT & WARGA", "#eventbintuni"
    return 0, "KABAR TERKINI", "#infobintuni"


def highlight_headline_for_card(clean_title: str) -> str:
    """Bungkus 1-3 kata kunci penting dengan *...* untuk sorotan Pop-Vector di editor."""
    t = re.sub(r"\*", "", clean_title).strip()
    # Prioritas kata kunci geografis atau topik utama
    targets = [
        r"Teluk Bintuni", r"Papua Barat Daya", r"Papua Barat", r"Bintuni",
        r"LNG Tangguh", r"BMKG", r"BPS", r"UMKM", r"DisTransnaker", r"Disnaker",
        r"Papua",
    ]
    for pat in targets:
        m = re.search(rf"\b({pat})\b", t, flags=re.I)
        if m:
            return t[:m.start()] + "*" + m.group(1) + "*" + t[m.end():]
    # Fallback: sorot 2 kata pertama bila belum ada yang tersorot
    words = t.split()
    if len(words) >= 4:
        return "*" + " ".join(words[:2]) + "* " + " ".join(words[2:])
    return t


def build_subline(summary: str, clean_title: str, wilayah: str, source_name: str) -> str:
    s = clean_html_text(summary)
    # Google News description sering hanya mengulang judul + nama sumber
    sim = SequenceMatcher(None, s.lower()[:80], clean_title.lower()[:80]).ratio() if s else 1.0
    if not s or len(s) < 25 or sim > 0.65:
        if wilayah == "bintuni":
            return f"Pantauan redaksi dari {source_name} untuk warga Kabupaten Teluk Bintuni."
        if wilayah == "papua_barat":
            return f"Perkembangan regional Papua Barat & PBD yang berdampak ke wilayah Teluk Bintuni."
        return f"Kabar pilihan Tanah Papua yang relevan dan inspiratif untuk warga Bintuni."
    # Potong rapi maks 115 karakter
    if len(s) > 115:
        s = s[:112].rsplit(" ", 1)[0].rstrip(".,;:") + "…"
    return s


def recommend_format(wilayah: str, cat_idx: int, tier: int, sumber_count: int, score: int) -> dict[str, str]:
    if cat_idx == 3:
        return {
            "kode": "bedah_fakta",
            "label": "Feed 4:5 / Bahan Bedah Fakta",
            "editor_mode": "4x5",
            "catatan": "Kaya data resmi — bisa langsung jadi Kartu 4:5 atau stok video Bedah Fakta akhir pekan.",
        }
    if cat_idx == 1:
        return {
            "kode": "feed_reels",
            "label": "Story + Video Cepat 9:16",
            "editor_mode": "story",
            "catatan": "Info cepat & penting — prioritaskan IG Story segera + Video Cepat 9:16.",
        }
    if wilayah == "bintuni" and (score >= 62 or sumber_count >= 2 or tier == 1):
        return {
            "kode": "feed_reels",
            "label": "Feed 4:5 + Video Cepat 9:16",
            "editor_mode": "4x5",
            "catatan": "Relevansi Bintuni tinggi — layak naik Feed IG 4:5 dan Reels/TikTok 9:16.",
        }
    if wilayah == "papua_barat" and (score >= 65 or sumber_count >= 2):
        return {
            "kode": "feed_reels",
            "label": "Feed 4:5 + Story",
            "editor_mode": "4x5",
            "catatan": "Berdampak ke Papua Barat — naikkan dengan sudut pandang warga Bintuni.",
        }
    return {
        "kode": "story",
        "label": "IG Story (Cepat)",
        "editor_mode": "story",
        "catatan": "Sesuai SOP Bagian 3: berita portal luar cukup diolah ringkas untuk IG Story + kredit sumber.",
    }


def build_seo_caption(
    clean_title: str,
    poin_resume: list[str],
    lokasi: str,
    sumber_display: str,
    tanggal_wit: str,
    tagar_topik: str,
    wilayah: str,
    kredit_foto: str = "Ilustrasi / Dok. Instansi",
) -> str:
    """Format caption bergaya jurnalisme ringkas ala Tempo + SEO baku Kabar Bintuni."""
    body_blocks = [p.strip() for p in poin_resume if p and p.strip()]
    if not body_blocks:
        body_blocks = [clean_title]
    body_text = "\n\n".join(body_blocks[:3])
    cta_map = {
        "bintuni": "Bagaimana menurut kaka dan ade di Bintuni? Tulis pendapat kam di komentar.",
        "papua_barat": "Bagaimana dampaknya ke Teluk Bintuni menurut kam? Bagikan ke teman atau keluarga.",
        "papua": "Kabar pilihan dari Tanah Papua. Simpan dan bagikan info ini agar makin banyak warga tahu.",
    }
    cta = cta_map.get(wilayah, cta_map["bintuni"])
    return (
        f"{body_text}\n\n"
        f"📍 Lokasi: {lokasi}\n"
        f"📰 Sumber: {sumber_display} ({tanggal_wit})\n"
        f"📷 Foto: {kredit_foto}\n"
        f"💬 {cta}\n\n"
        f"#kabarbintuni #telukbintuni #bintuni #papuabarat {tagar_topik}"
    )


def strip_news_dateline(text: str) -> str:
    """Buang dateline koran di awal paragraf agar gaya baca bersih seperti Tempo."""
    t = text.strip()
    # Contoh: "TELUK BINTUNI, Mediaprorakyat.com — Pendidikan..." atau "MANOKWARI, KOMPAS.com - ..."
    t = re.sub(
        r"^(?:[A-Z][A-Za-z.\s,]{2,48}?(?:com|co\.id|id|net|Pos|News|RRI|Antara)?)\s*(?:[-–—]{1,2}|:)\s+",
        "",
        t,
    )
    # Juga buang awalan nama kota huruf kapital penuh: "BINTUNI, " atau "MANOKWARI — "
    t = re.sub(r"^[A-Z\s]{4,28}\s*[-–—,]\s+", "", t)
    return t.strip()


BOILERPLATE_PHRASES = [
    "baca juga", "simak juga", "berita terkait", "artikel terkait", "the post ",
    "appeared first on", "copyright", "all rights reserved", "hak cipta",
    "cookie", "subscribe", "berlangganan", "silakan login", "masuk atau daftar",
    "download aplikasi", "unduh aplikasi", "ikuti kami", "follow instagram",
    "gabung saluran", "halaman selanjutnya", "halaman:", "pewarta:", "editor:",
    "penulis:", "reporter:", "foto:", "ilustrasi:", "sumber:", "advertisement",
    "scroll untuk melanjutkan", "dapatkan update", "whatsapp channel",
    "link copied", "lihat foto", "laporan reporter", "laporan wartawan",
    "bagikan artikel", "komentar anda",
]


def clean_article_paragraphs(raw_paragraphs: list[str], title: str) -> list[str]:
    """Saring paragraf isi artikel menjadi daftar kalimat/paragraf bersih bernilai berita."""
    cleaned: list[str] = []
    seen_norm: set[str] = set()
    title_l = title.lower()

    for raw in raw_paragraphs:
        p = clean_html_text(raw)
        p = strip_news_dateline(p)
        p = re.sub(r"\s+", " ", p).strip()
        if len(p) < 55 or len(p) > 480:
            continue
        pl = p.lower()
        if any(bp in pl for bp in BOILERPLATE_PHRASES):
            continue
        if pl.startswith(("http://", "https://", "www.", "@", "#")):
            continue
        # Hindari paragraf yang hanya mengulang persis judul
        if SequenceMatcher(None, pl[:90], title_l[:90]).ratio() > 0.86:
            continue
        norm = re.sub(r"[^a-z0-9]", "", pl[:70])
        if norm in seen_norm:
            continue
        seen_norm.add(norm)
        # Pastikan diakhiri tanda baca rapi
        if p[-1] not in ".!?…\"”":
            p += "."
        cleaned.append(p)
    return cleaned


def score_paragraph_value(p: str, idx: int) -> int:
    """Nilai bobot informasi paragraf: angka, rupiah, persen, tujuan/dampak, kutipan."""
    score = 0
    if idx == 0:
        score += 30
    if re.search(r"\b\d[\d.,]*\s*(?:%|persen|ribu|juta|miliar|triliun|hektare|ha|orang|unit|formasi|rupiah|rp|km|jam|hari|tahun)\b", p, flags=re.I):
        score += 22
    elif re.search(r"\b(?:rp\s?\d|\d{2,})", p, flags=re.I):
        score += 12
    if any(w in p.lower() for w in ["bertujuan", "untuk memperkuat", "berdampak", "menargetkan", "sehingga", "upaya", "resmi", "meliputi", "melibatkan", "diharapkan", "mendorong", "meningkatkan", "mengimbau"]):
        score += 10
    if '"' in p or "“" in p or "mengatakan" in p.lower() or "mengungkapkan" in p.lower() or "menjelaskan" in p.lower():
        score += 8
    if 95 <= len(p) <= 260:
        score += 10
    return score


def select_tempo_resume(
    title: str,
    raw_paragraphs: list[str],
    meta_desc: str,
    fallback_summary: str,
    wilayah: str,
    source_name: str,
) -> tuple[list[str], str, bool]:
    """Pilih 2-3 paragraf ringkasan faktual bergaya Tempo (Lead + Konteks/Dampak)."""
    paras = clean_article_paragraphs(raw_paragraphs, title)

    if not paras and meta_desc:
        md_clean = clean_article_paragraphs([meta_desc], title)
        paras.extend(md_clean)

    if paras:
        chosen: list[str] = [paras[0]]
        rest = [(score_paragraph_value(p, i + 1), i + 1, p) for i, p in enumerate(paras[1:10])]
        rest.sort(key=lambda x: (-x[0], x[1]))

        total_len = len(chosen[0])
        for _, _, cand in rest:
            if len(chosen) >= 3:
                break
            # Hindari tumpang tindih dengan paragraf yang sudah dipilih
            if any(SequenceMatcher(None, cand.lower()[:90], c.lower()[:90]).ratio() > 0.55 for c in chosen):
                continue
            if total_len + len(cand) > 680 and len(chosen) >= 2:
                continue
            chosen.append(cand)
            total_len += len(cand)

        # Ringkasan 1 kalimat singkat untuk subline kartu berita (maks 118 karakter)
        first_sent = re.split(r"(?<=[.!?])\s+", chosen[0])[0].strip()
        subline = first_sent if len(first_sent) <= 118 else first_sent[:114].rsplit(" ", 1)[0].rstrip(".,;:") + "…"
        return chosen, subline, True

    # Fallback aman bila portal memblokir bot (mis. Cloudflare 403) atau RSS BMKG alert
    raw_clean = clean_html_text(fallback_summary)
    if raw_clean and len(raw_clean) > 45 and SequenceMatcher(None, raw_clean.lower()[:80], title.lower()[:80]).ratio() < 0.72:
        long_fb = raw_clean if len(raw_clean) <= 360 else raw_clean[:356].rsplit(" ", 1)[0].rstrip(".,;:") + "…"
        short_fb = build_subline(raw_clean, title, wilayah, source_name)
        return [long_fb], short_fb, True
    fb = build_subline(fallback_summary, title, wilayah, source_name)
    return [f"{title}.", fb], fb, False


def decode_gnews_url(gurl: str) -> str:
    """Resolve tautan redirect Google News RSS ke URL artikel berita aslinya."""
    if "news.google.com" not in gurl:
        return gurl
    m = re.search(r"/articles/([^?]+)", gurl)
    if not m:
        return gurl
    token = m.group(1)

    # Cara 1: format base64 lama
    try:
        padded = token + "=" * (-len(token) % 4)
        raw = base64.urlsafe_b64decode(padded)
        s = raw.decode("latin1")
        hm = re.search(r"(https?://[^\x00-\x1f\x7f-\xff\"'<> ]+)", s)
        if hm and "news.google.com" not in hm.group(1) and is_safe_http_url(hm.group(1)):
            return hm.group(1)
    except Exception:
        pass

    # Cara 2: ambil signature & timestamp dari halaman artikel Google News lalu decode via batchexecute
    try:
        ctx = ssl.create_default_context()
        req = urllib.request.Request(gurl, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=10, context=ctx) as r:
            html_page = r.read(1_200_000).decode("utf-8", errors="ignore")
        sg = re.search(r'data-n-a-sg="([^"]+)"', html_page)
        ts = re.search(r'data-n-a-ts="([^"]+)"', html_page)
        if sg and ts:
            payload = [
                "Fbv4je",
                f'["garturlreq",[["X","X",["X","X"],null,null,1,1,"ID:id",null,1,null,null,null,null,null,0,1],"X","X",1,[1,1,1],1,1,null,0,0,null,0],"{token}",{ts.group(1)},"{sg.group(1)}"]',
            ]
            body = urllib.parse.urlencode({"f.req": json.dumps([[payload]])}).encode("utf-8")
            req2 = urllib.request.Request(
                "https://news.google.com/_/DotsSplashUi/data/batchexecute",
                data=body,
                headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8", "User-Agent": USER_AGENT},
            )
            with urllib.request.urlopen(req2, timeout=10, context=ctx) as r2:
                txt = r2.read(200_000).decode("utf-8", errors="ignore")
            m2 = re.search(r'garturlres\\",\\"(https?://[^\\"]+)', txt)
            if m2:
                decoded = m2.group(1).replace("\\u003d", "=").replace("\\u0026", "&")
                if is_safe_http_url(decoded):
                    return decoded
    except Exception:
        pass
    return gurl


def fetch_article_content(url: str) -> tuple[list[str], str]:
    """Ambil paragraf isi artikel + meta description secara aman (maks 500 KB, timeout 8 dtk)."""
    if not is_safe_http_url(url) or "news.google.com" in url:
        return [], ""
    try:
        ctx = ssl.create_default_context()
        req = urllib.request.Request(url, headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "id-ID,id;q=0.9,en;q=0.5",
        })
        with urllib.request.urlopen(req, timeout=8, context=ctx) as resp:
            ctype = (resp.headers.get("Content-Type") or "").lower()
            if "html" not in ctype and "xml" not in ctype:
                return [], ""
            page = resp.read(500_000).decode("utf-8", errors="ignore")

        # Ambil og:description / meta description sebagai cadangan kuat
        meta_desc = ""
        for pat in [
            r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)["\']',
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:description["\']',
            r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']',
        ]:
            mm = re.search(pat, page, flags=re.I)
            if mm and len(mm.group(1).strip()) > 45:
                meta_desc = clean_html_text(mm.group(1))
                break

        # Hapus script, style, nav, footer, aside agar hanya tersisa isi utama
        clean_page = re.sub(r"<(script|style|noscript|nav|footer|aside|header)[^>]*>.*?</\1>", " ", page, flags=re.S | re.I)
        # Prioritaskan isi di dalam <article> jika ada
        art = re.search(r"<article[^>]*>(.*?)</article>", clean_page, flags=re.S | re.I)
        scope = art.group(1) if art else clean_page
        paras = re.findall(r"<p[^>]*>(.*?)</p>", scope, flags=re.S | re.I)
        if len(paras) < 2 and art:
            paras = re.findall(r"<p[^>]*>(.*?)</p>", clean_page, flags=re.S | re.I)
        return paras[:20], meta_desc
    except Exception:
        return [], ""


def title_tokens(title: str) -> set[str]:
    words = re.findall(r"[a-z0-9]{3,}", title.lower())
    return {w for w in words if w not in STOPWORDS}


def is_similar_story(a_title: str, b_title: str) -> bool:
    ta, tb = title_tokens(a_title), title_tokens(b_title)
    if ta and tb:
        jaccard = len(ta & tb) / max(1, len(ta | tb))
        if jaccard >= 0.45:
            return True
    ratio = SequenceMatcher(None, a_title.lower(), b_title.lower()).ratio()
    return ratio >= 0.62


# ---------------------------------------------------------------------------
# 5. Fetcher RSS & BMKG
# ---------------------------------------------------------------------------
def fetch_xml(url: str, timeout: int = 15, max_bytes: int = 2_500_000) -> bytes:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("https", "http"):
        raise ValueError(f"Skema URL tidak diizinkan: {parsed.scheme}")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        data = resp.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError("Ukuran respons RSS melebihi batas aman 2,5 MB")
    # Tolak DOCTYPE/ENTITY untuk perlindungan ekstra terhadap serangan XML
    head_l = data[:4096].lower()
    if b"<!doctype" in head_l or b"<!entity" in head_l:
        raise ValueError("Payload XML mengandung DOCTYPE/ENTITY yang ditolak demi keamanan")
    return data


def is_safe_http_url(url: str) -> bool:
    try:
        p = urllib.parse.urlparse(url.strip())
        if p.scheme not in ("https", "http") or not p.netloc:
            return False
        host = (p.hostname or "").lower()
        # Tolak host lokal / privat (anti-SSRF)
        if host in ("localhost", "127.0.0.1", "0.0.0.0", "::1") or host.startswith(("10.", "192.168.", "169.254.", "172.16.", "172.17.", "172.18.", "172.19.")):
            return False
        return True
    except Exception:
        return False


def collect_raw_items() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    collected: list[dict[str, Any]] = []
    feed_stats: list[dict[str, Any]] = []

    for feed in FEEDS:
        st = {"id": feed["id"], "label": feed["label"], "ok": False, "count": 0, "error": ""}
        try:
            raw = fetch_xml(feed["url"])
            root = ET.fromstring(raw)
            items = root.findall(".//item")
            st["ok"] = True
            for it in items:
                raw_title = it.findtext("title", "")
                link = (it.findtext("link", "") or "").strip()
                pub_raw = it.findtext("pubDate", "")
                desc_raw = it.findtext("description", "")
                content_el = it.find("{http://purl.org/rss/1.0/modules/content/}encoded")
                content_html = (content_el.text or "") if content_el is not None else ""
                src_el = it.find("source")
                source_name = (src_el.text or "").strip() if src_el is not None else ""
                if feed.get("source_override"):
                    source_name = feed["source_override"]
                elif feed["id"] == "bmkg_nowcast":
                    source_name = "BMKG Resmi"

                if not raw_title or not link or not is_safe_http_url(link):
                    continue
                if any(sp in f"{source_name} {link}".lower() for sp in SPAM_SOURCE_PATTERNS):
                    continue

                clean_t = strip_source_suffix(raw_title, source_name)
                summary = clean_html_text(desc_raw)
                rss_paras = re.findall(r"<p[^>]*>(.*?)</p>", content_html or desc_raw, flags=re.S | re.I)

                # Khusus BMKG Nowcast: hanya ambil jika menyangkut Papua Barat / Teluk Bintuni / PBD
                if feed["id"] == "bmkg_nowcast":
                    blob = f"{clean_t} {summary}".lower()
                    if not any(k in blob for k in ["papua barat", "bintuni", "manokwari", "papua barat daya"]):
                        continue

                if not is_relevant_to_papua(clean_t, summary):
                    continue

                pub_dt = parse_pub_date(pub_raw)
                wilayah = detect_wilayah(clean_t, summary, feed["wilayah_hint"])
                tier, tier_label = classify_source_tier(source_name, link)

                collected.append({
                    "raw_title": raw_title,
                    "title": clean_t,
                    "summary": summary,
                    "rss_paras": rss_paras[:15],
                    "link": link,
                    "source": source_name or "Portal Berita",
                    "tier": tier,
                    "tier_label": tier_label,
                    "pub_dt": pub_dt,
                    "wilayah": wilayah,
                    "feed_id": feed["id"],
                })
                st["count"] += 1
        except Exception as exc:
            st["error"] = str(exc)[:140]
        feed_stats.append(st)

    return collected, feed_stats


# ---------------------------------------------------------------------------
# 6. Pipeline 3 Gerbang: Anti-Sensitif -> Dedup/Klaster -> Skor & Kuota 60/25/15
# ---------------------------------------------------------------------------
def build_bank_berita() -> dict[str, Any]:
    now_wit = datetime.now(WIT)
    raw_items, feed_stats = collect_raw_items()

    blocked_items: list[dict[str, Any]] = []
    safe_items: list[dict[str, Any]] = []
    seen_links: set[str] = set()

    # Urutkan terbaru dulu sebelum dedup
    raw_items.sort(key=lambda x: x["pub_dt"], reverse=True)

    for item in raw_items:
        if item["link"] in seen_links:
            continue
        seen_links.add(item["link"])

        flag = detect_red_flag(item["title"], item["summary"])
        if flag:
            blocked_items.append({
                "title": item["title"],
                "source": item["source"],
                "wilayah": item["wilayah"],
                "tanggal_wit": format_tanggal_wit(item["pub_dt"]),
                "alasan_blokir": flag,
                "link": item["link"],
            })
            continue
        safe_items.append(item)

    # Gerbang 2: Dedup & Klaster Multi-Sumber (Kredibilitas + Dampak Viral)
    clusters: list[dict[str, Any]] = []
    for item in safe_items:
        matched = None
        for cl in clusters:
            if is_similar_story(item["title"], cl["title"]):
                matched = cl
                break
        if matched is None:
            clusters.append({
                "primary": item,
                "title": item["title"],
                "sources": [{
                    "nama": item["source"],
                    "tier": item["tier"],
                    "link": item["link"],
                    "tanggal_wit": format_tanggal_wit(item["pub_dt"]),
                }],
                "latest_dt": item["pub_dt"],
            })
        else:
            # Jangan duplikat nama media sama dalam 1 klaster
            existing_names = {s["nama"].lower() for s in matched["sources"]}
            if item["source"].lower() not in existing_names:
                matched["sources"].append({
                    "nama": item["source"],
                    "tier": item["tier"],
                    "link": item["link"],
                    "tanggal_wit": format_tanggal_wit(item["pub_dt"]),
                })
            # Promosikan primary jika sumber baru punya tier lebih tinggi (angka lebih kecil)
            if item["tier"] < matched["primary"]["tier"]:
                matched["primary"] = item
                matched["title"] = item["title"]
            if item["pub_dt"] > matched["latest_dt"]:
                matched["latest_dt"] = item["pub_dt"]

    # Hitung skor kelayakan & susun objek bank konten siap pakai
    scored: list[dict[str, Any]] = []
    for cl in clusters:
        p = cl["primary"]
        dt = cl["latest_dt"]
        age_hours = max(0.0, (now_wit - dt).total_seconds() / 3600.0)

        # Skor dasar: Kredibilitas sumber
        best_tier = min(s["tier"] for s in cl["sources"])
        tier_score = {1: 35, 2: 26, 3: 12}.get(best_tier, 12)

        # Skor kebaharuan
        if age_hours <= 24:
            fresh_score = 26
        elif age_hours <= 72:
            fresh_score = 20
        elif age_hours <= 168:
            fresh_score = 13
        elif age_hours <= 336:
            fresh_score = 7
        else:
            fresh_score = 3

        # Skor dampak multi-sumber ("viral + terkonfirmasi")
        src_count = len(cl["sources"])
        multi_score = min(24, (src_count - 1) * 12)

        # Skor dampak langsung ke warga vs penalti seremonial
        blob = f"{p['title']} {p['summary']}".lower()
        impact_hits = sum(1 for kw in HIGH_IMPACT_KEYWORDS if kw in blob)
        impact_score = min(22, impact_hits * 7)
        cerem_penalty = -14 if any(kw in blob for kw in CEREMONIAL_PENALTY_KEYWORDS) else 0
        geo_bonus = 8 if p["wilayah"] == "bintuni" else (3 if p["wilayah"] == "papua_barat" else 0)

        total_score = max(10, min(100, tier_score + fresh_score + multi_score + impact_score + cerem_penalty + geo_bonus))

        cat_idx, cat_label, tagar_topik = detect_category(p["title"], p["summary"], p["source"])
        lokasi = detect_lokasi_label(p["title"], p["summary"], p["wilayah"])
        card_headline = highlight_headline_for_card(p["title"])
        subline = build_subline(p["summary"], p["title"], p["wilayah"], p["source"])
        sumber_names = [s["nama"] for s in cl["sources"]]
        sumber_display = sumber_names[0] if len(sumber_names) == 1 else f"{sumber_names[0]} (+{len(sumber_names)-1} media)"
        rec = recommend_format(p["wilayah"], cat_idx, best_tier, src_count, total_score)
        kredit_foto_saran = (
            f"Dok. {p['source']}" if best_tier == 1
            else "Ilustrasi: Kabar Bintuni (atau ganti kredit resmi/izin)"
        )
        poin_awal = [p["title"] + ".", subline]
        tanggal_str = format_tanggal_wit(dt)
        caption_seo = build_seo_caption(
            p["title"], poin_awal, lokasi, sumber_display, tanggal_str, tagar_topik, p["wilayah"], kredit_foto_saran
        )

        item_id = "kb-" + hashlib.md5(f"{p['title']}|{p['source']}".encode("utf-8")).hexdigest()[:10]
        verifikasi_label = (
            "Terverifikasi Multi-Sumber" if src_count >= 2
            else ("Sumber Resmi / Primer" if best_tier == 1 else ("Media Terverifikasi" if best_tier == 2 else "Perlu Cek Silang"))
        )

        scored.append({
            "id": item_id,
            "wilayah": p["wilayah"],  # bintuni | papua_barat | papua
            "wilayah_label": {"bintuni": "Teluk Bintuni", "papua_barat": "Papua Barat & PBD", "papua": "Papua Umum"}[p["wilayah"]],
            "score": total_score,
            "cat_idx": cat_idx,
            "cat_label": cat_label,
            "title": p["title"],
            "card_headline": card_headline,
            "subline": subline,
            "poin_resume": poin_awal,
            "resume_dari_artikel": False,
            "lokasi": lokasi,
            "sumber_utama": p["source"],
            "sumber_display": sumber_display,
            "sumber_count": src_count,
            "sumber_list": cl["sources"],
            "tier": best_tier,
            "verifikasi_label": verifikasi_label,
            "tanggal_wit": tanggal_str,
            "published_iso": dt.isoformat(timespec="minutes"),
            "umur_jam": round(age_hours, 1),
            "link": p["link"],
            "rekomendasi_format": rec,
            "tagar_topik": tagar_topik,
            "kredit_foto_saran": kredit_foto_saran,
            "caption_seo": caption_seo,
            "peringatan_visual": "Utamakan Mode Grafis Kaka Kabar, foto rilis instansi resmi, atau dokumentasi sendiri. Jangan pakai foto ber-watermark media lain tanpa izin.",
            "_rss_paras": p.get("rss_paras") or [],
            "_raw_summary": p["summary"],
        })

    # Gerbang 3: Terapkan Kuota Wilayah 60% Bintuni (18) / 25% Papua Barat & PBD (8) / 15% Papua (4)
    by_wilayah: dict[str, list[dict[str, Any]]] = {"bintuni": [], "papua_barat": [], "papua": []}
    for it in scored:
        by_wilayah[it["wilayah"]].append(it)
    for w in by_wilayah:
        by_wilayah[w].sort(key=lambda x: (x["score"], x["published_iso"]), reverse=True)

    quota = {"bintuni": 18, "papua_barat": 8, "papua": 4}
    selected: list[dict[str, Any]] = []
    for w in ("bintuni", "papua_barat", "papua"):
        selected.extend(by_wilayah[w][: quota[w]])

    # Urutkan tampilan akhir: prioritaskan Bintuni skor tinggi + berita segar
    wilayah_order = {"bintuni": 0, "papua_barat": 1, "papua": 2}
    selected.sort(key=lambda x: (wilayah_order[x["wilayah"]], -x["score"], x["umur_jam"]))

    # Gerbang 4: Perkaya 30 berita terpilih dengan isi artikel asli -> Resume otomatis ala Tempo
    def _enrich_one(it: dict[str, Any]) -> None:
        rss_paras = it.pop("_rss_paras", [])
        raw_summary = it.pop("_raw_summary", "")
        real_url = decode_gnews_url(it["link"])
        if is_safe_http_url(real_url):
            it["link"] = real_url

        paras: list[str] = list(rss_paras)
        meta_desc = ""
        # Jika paragraf dari RSS belum cukup (kurang dari 2 paragraf substansial), baca halaman artikel aslinya
        if len(clean_article_paragraphs(paras, it["title"])) < 2:
            fetched_paras, meta_desc = fetch_article_content(it["link"])
            if fetched_paras:
                paras = fetched_paras

        poin, new_sub, from_article = select_tempo_resume(
            it["title"], paras, meta_desc, raw_summary, it["wilayah"], it["sumber_utama"]
        )
        it["poin_resume"] = poin
        it["resume_dari_artikel"] = from_article
        if from_article and new_sub:
            it["subline"] = new_sub
        it["caption_seo"] = build_seo_caption(
            it["title"],
            poin,
            it["lokasi"],
            it["sumber_display"],
            it["tanggal_wit"],
            it["tagar_topik"],
            it["wilayah"],
            it["kredit_foto_saran"],
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(_enrich_one, selected))

    # Pastikan semua item ter-clean dari field internal bila ada
    for it in selected:
        it.pop("_rss_paras", None)
        it.pop("_raw_summary", None)

    counts = {
        "bintuni": sum(1 for x in selected if x["wilayah"] == "bintuni"),
        "papua_barat": sum(1 for x in selected if x["wilayah"] == "papua_barat"),
        "papua": sum(1 for x in selected if x["wilayah"] == "papua"),
        "total_terpilih": len(selected),
        "total_mentah": len(raw_items),
        "total_terklaster": len(clusters),
        "total_diblokir_sensitif": len(blocked_items),
    }

    return {
        "schema_version": 1,
        "generated_at_wit": now_wit.strftime("%d %b %Y, %H:%M WIT"),
        "generated_at_iso": now_wit.isoformat(timespec="minutes"),
        "jadwal_otomatis": "2× sehari otomatis (06.00 WIT & 17.30 WIT) via GitHub Actions",
        "kuota_target": {"bintuni": "60%", "papua_barat": "25%", "papua": "15%"},
        "stats": counts,
        "feed_health": feed_stats,
        "social_watchlist": SOCIAL_WATCHLIST,
        "items": selected,
        "blocked_audit": blocked_items[:25],
    }


def write_markdown_summary(data: dict[str, Any]) -> str:
    st = data["stats"]
    lines = [
        "# Bank Berita Harian — Kabar Bintuni",
        "",
        f"- **Diperbarui:** {data['generated_at_wit']}",
        f"- **Hasil kurasi:** **{st['total_terpilih']} berita layak** "
        f"(Teluk Bintuni: {st['bintuni']} · Papua Barat & PBD: {st['papua_barat']} · Papua: {st['papua']})",
        f"- **Audit keamanan redaksi:** {st['total_diblokir_sensitif']} berita sensitif/politik otomatis ditahan dari total {st['total_mentah']} berita mentah.",
        "",
        "## Daftar Berita Terpilih",
        "",
        "| # | Wilayah | Skor | Kategori | Judul | Sumber | Format |",
        "|---|---|---|---|---|---|---|",
    ]
    for i, it in enumerate(data["items"], 1):
        title_esc = it["title"].replace("|", "–")
        lines.append(
            f"| {i} | {it['wilayah_label']} | **{it['score']}** | {it['cat_label']} | "
            f"[{title_esc}]({it['link']}) | {it['sumber_display']} ({it['tanggal_wit']}) | {it['rekomendasi_format']['label']} |"
        )
    lines.append("")
    lines.append("## Pantau Cepat Akun IG & Facebook Lokal")
    for sw in data["social_watchlist"]:
        lines.append(f"- **{sw['platform']} — {sw['nama']}** (`{sw['handle']}`): {sw['fokus']} → {sw['url']}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    data = build_bank_berita()

    # Tulis JSON secara atomik
    tmp_json = JSON_OUT.with_suffix(".json.tmp")
    tmp_json.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp_json, JSON_OUT)

    md_text = write_markdown_summary(data)
    MD_OUT.write_text(md_text, encoding="utf-8")

    st = data["stats"]
    print(
        f"[OK] Bank Berita diperbarui ({data['generated_at_wit']}): "
        f"{st['total_terpilih']} layak (Bintuni={st['bintuni']}, Pabar/PBD={st['papua_barat']}, Papua={st['papua']}), "
        f"{st['total_diblokir_sensitif']} diblokir Red-Flag."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
