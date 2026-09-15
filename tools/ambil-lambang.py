#!/usr/bin/env python3
"""ambil-lambang: unduh jalur ikon merek untuk lambang sumber di UI.

Sumber: paket npm simple-icons lewat jsdelivr (CC0 1.0). Hasilnya ditulis ke
web/sumber.js sebagai peta nama -> jalur SVG, supaya halaman tidak perlu
meminta apa pun ke luar saat dipakai: lambang yang tidak ada di peta jatuh ke
inisial domain.

Jalankan sekali, lalu commit hasilnya:
  python3 tools/ambil-lambang.py
"""
from __future__ import annotations

import json
import pathlib
import re
import sys
import urllib.request

VERSI = "13.21.0"
CDN = f"https://cdn.jsdelivr.net/npm/simple-icons@{VERSI}/icons/{{slug}}.svg"
KELUAR = pathlib.Path(__file__).resolve().parent.parent / "web" / "sumber.js"

# Nama tampilan untuk merek yang ejaannya beda dari slug.
NAMA = {
    "openai": "OpenAI", "anthropic": "Anthropic", "github": "GitHub",
    "stackoverflow": "Stack Overflow", "stackexchange": "Stack Exchange",
    "wikipedia": "Wikipedia", "wikimediafoundation": "Wikimedia",
    "googlegemini": "Gemini", "googlescholar": "Google Scholar",
    "googledrive": "Google Drive", "googledocs": "Google Docs",
    "googlesheets": "Google Sheets", "googleslides": "Google Slides",
    "googlecalendar": "Google Calendar", "googlemaps": "Google Maps",
    "googleplay": "Google Play", "googlecloud": "Google Cloud",
    "youtube": "YouTube", "facebook": "Facebook", "instagram": "Instagram",
    "whatsapp": "WhatsApp", "telegram": "Telegram", "x": "X",
    "tiktok": "TikTok", "linkedin": "LinkedIn", "pinterest": "Pinterest",
    "snapchat": "Snapchat", "threads": "Threads", "discord": "Discord",
    "slack": "Slack", "medium": "Medium", "devdotto": "DEV Community",
    "hashnode": "Hashnode", "substack": "Substack", "ghost": "Ghost",
    "wordpress": "WordPress", "blogger": "Blogger", "tumblr": "Tumblr",
    "quora": "Quora", "ycombinator": "Hacker News", "producthunt": "Product Hunt",
    "npm": "npm", "pypi": "PyPI", "python": "Python", "javascript": "JavaScript",
    "typescript": "TypeScript", "nodedotjs": "Node.js", "react": "React",
    "vuedotjs": "Vue", "svelte": "Svelte", "angular": "Angular",
    "nextdotjs": "Next.js", "tailwindcss": "Tailwind CSS", "docker": "Docker",
    "kubernetes": "Kubernetes", "linux": "Linux", "ubuntu": "Ubuntu",
    "debian": "Debian", "android": "Android", "apple": "Apple",
    "windows": "Windows", "microsoft": "Microsoft", "microsoftazure": "Azure",
    "amazonwebservices": "AWS", "digitalocean": "DigitalOcean",
    "cloudflare": "Cloudflare", "vercel": "Vercel", "netlify": "Netlify",
    "heroku": "Heroku", "firebase": "Firebase", "supabase": "Supabase",
    "mongodb": "MongoDB", "postgresql": "PostgreSQL", "mysql": "MySQL",
    "redis": "Redis", "sqlite": "SQLite", "gitlab": "GitLab",
    "bitbucket": "Bitbucket", "jira": "Jira", "trello": "Trello",
    "notion": "Notion", "airtable": "Airtable", "figma": "Figma",
    "canva": "Canva", "dribbble": "Dribbble", "behance": "Behance",
    "adobephotoshop": "Photoshop", "sketch": "Sketch", "zoom": "Zoom",
    "spotify": "Spotify", "netflix": "Netflix", "twitch": "Twitch",
    "steam": "Steam", "ebay": "eBay", "amazon": "Amazon", "alibaba": "Alibaba",
    "bbc": "BBC", "cnn": "CNN", "nytimes": "The New York Times",
    "theguardian": "The Guardian", "reuters": "Reuters", "bloomberg": "Bloomberg",
    "forbes": "Forbes", "techcrunch": "TechCrunch", "theverge": "The Verge",
    "wired": "Wired", "arstechnica": "Ars Technica", "engadget": "Engadget",
    "zdnet": "ZDNET", "cnet": "CNET", "mashable": "Mashable",
    "gizmodo": "Gizmodo", "nature": "Nature", "sciencedirect": "ScienceDirect",
    "springer": "Springer", "ieee": "IEEE", "arxiv": "arXiv",
    "researchgate": "ResearchGate", "jstor": "JSTOR", "who": "WHO",
    "unitednations": "PBB", "worldbank": "World Bank", "imf": "IMF",
    "oecd": "OECD", "kaggle": "Kaggle", "huggingface": "Hugging Face",
    "openstreetmap": "OpenStreetMap", "mozilla": "Mozilla", "brave": "Brave",
    "opera": "Opera", "firefox": "Firefox", "googlechrome": "Chrome",
    "duckduckgo": "DuckDuckGo", "bing": "Bing", "yahoo": "Yahoo",
    "baidu": "Baidu", "yandex": "Yandex", "naver": "Naver", "line": "LINE",
    "wechat": "WeChat", "viber": "Viber", "signal": "Signal",
    "messenger": "Messenger", "gmail": "Gmail", "paypal": "PayPal",
    "visa": "Visa", "mastercard": "Mastercard", "stripe": "Stripe",
    "shopify": "Shopify", "woocommerce": "WooCommerce", "odoo": "Odoo",
    "sap": "SAP", "oracle": "Oracle", "ibm": "IBM", "intel": "Intel",
    "nvidia": "NVIDIA", "amd": "AMD", "qualcomm": "Qualcomm",
    "samsung": "Samsung", "xiaomi": "Xiaomi", "huawei": "Huawei",
    "oppo": "OPPO", "vivo": "vivo", "asus": "ASUS", "acer": "Acer",
    "dell": "Dell", "hp": "HP", "lenovo": "Lenovo", "toshiba": "Toshiba",
    "sony": "Sony", "lg": "LG", "philips": "Philips", "siemens": "Siemens",
    "bosch": "Bosch", "toyota": "Toyota", "honda": "Honda", "bmw": "BMW",
    "mercedes": "Mercedes-Benz", "tesla": "Tesla", "ford": "Ford",
    "hyundai": "Hyundai", "nissan": "Nissan", "suzuki": "Suzuki",
    "mcdonalds": "McDonald's", "starbucks": "Starbucks", "nike": "Nike",
    "adidas": "Adidas", "cocacola": "Coca-Cola", "pepsi": "Pepsi",
    "unilever": "Unilever", "nestle": "Nestle", "indomie": "Indomie",
    "telkomsel": "Telkomsel", "xl": "XL Axiata", "indosat": "Indosat",
    "grab": "Grab", "gojek": "Gojek", "traveloka": "Traveloka",
    "tokopedia": "Tokopedia", "shopee": "Shopee", "bukalapak": "Bukalapak",
    "lazada": "Lazada", "blibli": "Blibli", "bca": "BCA", "mandiri": "Mandiri",
    "bri": "BRI", "bni": "BNI", "dana": "DANA", "ovo": "OVO", "gopay": "GoPay",
    "wikidata": "Wikidata", "googletranslate": "Google Translate",
    "thehackernews": "The Hacker News", "bleepingcomputer": "BleepingComputer",
    "serverfault": "Server Fault", "superuser": "Super User",
    "askubuntu": "Ask Ubuntu", "geeksforgeeks": "GeeksforGeeks",
    "w3schools": "W3Schools", "mdnwebdocs": "MDN Web Docs",
    "digitalocean": "DigitalOcean", "heroku": "Heroku",
}

# Slug yang diunduh. Nama domain dipetakan ke salah satu dari ini di sumber.js.
SLUG = sorted(set(NAMA))


def unduh(slug: str) -> str | None:
    try:
        with urllib.request.urlopen(CDN.format(slug=slug), timeout=20) as r:
            teks = r.read().decode("utf-8", "replace")
    except Exception:
        return None
    m = re.search(r'<path[^>]*\sd="([^"]+)"', teks)
    if not m:
        return None
    jalur = m.group(1).strip()
    # Ikon berlapis (beberapa path) tidak dipakai: satu jalur saja sudah cukup
    # dan menjaga berkasnya tetap kecil.
    return jalur if len(jalur) > 20 else None


def main() -> int:
    peta: dict[str, dict[str, str]] = {}
    gagal: list[str] = []
    for slug in SLUG:
        jalur = unduh(slug)
        if jalur:
            peta[slug] = {"nama": NAMA.get(slug, slug.title()), "d": jalur}
        else:
            gagal.append(slug)
    isi = json.dumps(peta, ensure_ascii=False, separators=(",", ":"))
    KELUAR.write_text(
        "/* Lambang sumber. Dibuat oleh tools/ambil-lambang.py, jangan diubah tangan.\n"
        f"   Sumber: simple-icons {VERSI} (CC0 1.0), diunduh sekali lalu disimpan\n"
        "   sebagai jalur SVG. Tidak ada permintaan ke luar saat halaman dipakai. */\n"
        f"const LAMBANG_MEREK = {isi};\n",
        encoding="utf-8",
    )
    print(f"{len(peta)} lambang ditulis ke {KELUAR} ({KELUAR.stat().st_size // 1024} KB)")
    if gagal:
        print("tidak ada di simple-icons:", ", ".join(gagal))
    return 0


if __name__ == "__main__":
    sys.exit(main())
