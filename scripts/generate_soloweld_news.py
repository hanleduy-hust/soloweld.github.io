"""
Tự động tổng hợp và xuất bản bản tin công nghệ chuyên sâu hằng tuần (News & Insights)
cho cổng thông tin kỹ thuật SoloWeld (https://soloweld.github.io).

Lịch chạy định kỳ: 08:00 sáng Thứ Bảy hằng tuần (01:00 UTC) qua GitHub Actions.
"""

import datetime as dt
import html
import io
import json
import os
import random
import re
import sys
import time
import unicodedata
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from PIL import Image

# Cấu trúc thư mục chuẩn trên repository soloweld.github.io
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
NEWS_INDEX = DATA_DIR / "news_index.json"
USED_DOIS_FILE = DATA_DIR / "used_dois.json"
POSTS_DIR = ROOT / "news" / "posts"
IMG_DIR = ROOT / "images" / "news"
DRAFT_DIR = Path(os.environ.get("DRAFT_DIR", ROOT / ".draft"))

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
OPENALEX_API_KEY = os.environ.get("OPENALEX_API_KEY", "").strip()
CONTACT_EMAIL = os.environ.get("CONTACT_EMAIL", "contact@soloweld.github.io").strip()
TOPIC_ROTATION = os.environ.get("TOPIC_ROTATION", "auto").strip().lower()
MAX_PAPERS = int(os.environ.get("MAX_PAPERS", "16"))
MIN_PAPERS = int(os.environ.get("MIN_PAPERS", "4"))
LOOKBACK_DAYS = int(os.environ.get("LOOKBACK_DAYS", "60"))
MAX_FIGURES = int(os.environ.get("MAX_FIGURES", "8"))
COMPACT_TEST = os.environ.get("COMPACT_TEST") == "true"

VN_TZ = dt.timezone(dt.timedelta(hours=7))

SOLOWELD_TOPICS = [
    {
        "key": "ai_cv_welding",
        "vi": "AI & Thị giác máy tính trong Tự động hóa và Kiểm định Hàn",
        "en": "AI & Computer Vision in Welding Automation and Inspection",
        "zh": "焊接自动化与检测中的人工智能与计算机视觉",
        "ja": "溶接自動化・検査におけるAIとコンピュータビジョン",
        "queries": [
            'welding AND "computer vision"',
            'welding AND "deep learning" AND defect',
            'welding AND "machine learning" AND monitoring',
            '"seam tracking" AND (vision OR laser OR learning)',
            '"weld pool" AND ("neural network" OR vision)',
        ],
        "must": [
            r"\bweld|joining|seam\b|arc\b",
            r"artificial intelligence|machine learning|deep learning|neural network|computer vision|image processing|yolo|cnn|transformer",
        ],
        "outline": (
            "Thị giác máy tính (Computer Vision) dẫn đường mối hàn và theo dõi vũng hàn thời gian thực;"
            "Học sâu (Deep Learning) trong phát hiện khuyết tật mối hàn và kiểm tra không phá hủy (NDT/RT/UT);"
            "Tối ưu hóa thông số quy trình hàn và dự báo cơ tính mối hàn bằng Machine Learning;"
            "Khả năng tích hợp vào dây chuyền sản xuất theo tiêu chuẩn AWS D1.1, ASME và ISO"
        ),
    },
    {
        "key": "blockchain_cert_traceability",
        "vi": "Blockchain, Smart Contract & Chuyển đổi số Quản lý Chứng chỉ Hàn Quốc tế",
        "en": "Blockchain, Smart Contracts & Digital Traceability in Welding Certification",
        "zh": "区块链、智能合约与国际焊接认证数字化溯源",
        "ja": "ブロックチェーン・スマートコントラクトと国際溶接資格のデジタルトレーサビリティ",
        "queries": [
            'blockchain AND (manufacturing OR industrial) AND (certification OR traceability OR quality)',
            '"smart contract" AND (manufacturing OR supply chain OR inspection) AND quality',
            'welding AND ("digital twin" OR blockchain OR traceability OR "industry 4.0")',
            '"non-destructive testing" AND (blockchain OR "digital transformation" OR traceability)',
            'blockchain AND ("credential" OR "qualification" OR "certificate") AND engineering',
        ],
        "must": [
            r"blockchain|smart contract|distributed ledger|traceability|digital twin|industry 4\.0|cyber[- ]physical|verifiable credential",
            r"\bweld|manufactur|industrial|inspection|ndt|quality|certificat|qualificat|metallurg|fabricat",
        ],
        "outline": (
            "Kiến trúc Blockchain và Smart Contract trong chống giả mạo và xác thực chứng chỉ kỹ sư/thợ hàn (JWES, AWS, ASME, ISO 9606);"
            "Truy xuất nguồn gốc vật liệu (Kim loại cơ bản, Kim loại điền đầy) và nhật ký thông số hàn (WPS/PQR/WPQ) bất biến;"
            "Tự động hóa nghiệm thu chất lượng mối hàn và kiểm tra NDT thông qua hợp đồng thông minh (Smart Contracts);"
            "Lợi ích minh bạch hóa chuỗi cung ứng chế tạo cơ khí, bình áp lực và kết cấu thép quốc tế"
        ),
    },
    {
        "key": "welder_training_digital",
        "vi": "Công nghệ AI, VR/AR & Bản sao số trong Đào tạo Kỹ sư và Thợ hàn Quốc tế",
        "en": "AI, VR/AR & Digital Twins in International Welding Engineer and Welder Training",
        "zh": "国际焊接工程师与焊工培训中的AI、VR/AR与数字孪生技术",
        "ja": "国際溶接技術者・溶接工育成におけるAI・VR/AR・デジタルツイン技術",
        "queries": [
            'welding AND ("virtual reality" OR "augmented reality" OR simulator OR training)',
            'welding AND ("skill assessment" OR "welder training" OR "human-robot" OR ergonomics)',
            '"digital twin" AND welding AND (monitoring OR control OR training)',
            'welding AND ("knowledge graph" OR "large language model" OR "expert system")',
        ],
        "must": [
            r"\bweld|joining|arc\b",
            r"training|virtual reality|augmented reality|\bvr\b|\bar\b|simulat|skill|digital twin|knowledge graph|expert system|education|human[- ]robot",
        ],
        "outline": (
            "Hệ thống mô phỏng thực tế ảo (VR/AR) và cảm biến chuyển động trong huấn luyện kỹ năng thao tác mỏ hàn;"
            "Ứng dụng AI và phân tích dữ liệu đa phương thức để đánh giá tay nghề thợ hàn theo tiêu chuẩn ISO 9606 / AWS / JWES;"
            "Hệ chuyên gia (Expert Systems), đồ thị tri thức (Knowledge Graphs) và LLM hỗ trợ kỹ sư hàn lập quy trình WPS/PQR;"
            "Bản sao số (Digital Twin) kết nối giữa đào tạo thực hành và giám sát sản xuất thông minh"
        ),
    },
    {
        "key": "smart_robotic_waam",
        "vi": "Tự động hóa Hàn Robot Thông minh, Cảm biến Đa phương thức & In 3D Kim loại (WAAM)",
        "en": "Intelligent Robotic Welding, Multi-Sensor Fusion & Wire Arc Additive Manufacturing",
        "zh": "智能机器人焊接、多传感器融合与电弧增材制造 (WAAM)",
        "ja": "インテリジェントロボット溶接・マルチセンサ融合・ワイヤーアーク積層造形 (WAAM)",
        "queries": [
            '"robotic welding" AND ("machine learning" OR vision OR adaptive OR sensor)',
            '"wire arc additive manufacturing" AND ("machine learning" OR monitoring OR control)',
            '"laser welding" AND ("deep learning" OR "in-situ monitoring" OR photodiode OR acoustic)',
            '"friction stir welding" AND ("machine learning" OR optimization OR monitoring)',
        ],
        "must": [
            r"\bweld|\bwaam\b|wire arc additive",
            r"robot|sensor|adaptive|closed[- ]loop|monitoring|control|machine learning|deep learning|vision|acoustic|thermal",
        ],
        "outline": (
            "Robot hàn tự thích ứng (Adaptive Robotic Welding) và hợp nhất dữ liệu đa cảm biến (quang học, âm thanh, nhiệt, dòng hồ quang);"
            "Điều khiển vòng kín (Closed-loop Control) trong quá trình hàn hồ quang, hàn laser và in 3D kim loại (WAAM);"
            "Phân tích vi cấu trúc vùng ảnh hưởng nhiệt (HAZ), kiểm soát biến dạng và ứng suất dư bằng mô hình số kết hợp AI;"
            "Triển khai thực tế trong chế tạo đường ống năng lượng, bình áp lực ASME, đóng tàu và kết cấu thép"
        ),
    },
]

TOPIC_BY_KEY = {t["key"]: t for t in SOLOWELD_TOPICS}
REUSABLE_LICENSES = {"cc-by", "cc-by-sa", "cc-by-nc", "cc-by-nc-sa", "cc0", "public-domain"}

UA = "Mozilla/5.0 (compatible; SoloWeld-NewsBot/1.0; +https://soloweld.github.io)"
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": UA})

WEB = requests.Session()
WEB.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/*,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
})

DIAG = []


def log(*a):
    print(*a, flush=True)


def diag(msg):
    log(msg)
    DIAG.append(msg.strip())


def slugify(text, maxlen=65):
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text[:maxlen].strip("-") or "soloweld-news"


def norm_doi(doi):
    if not doi:
        return ""
    return re.sub(r"^https?://(dx\.)?doi\.org/", "", doi.strip(), flags=re.I).lower()


def norm_license(lic):
    if not lic:
        return ""
    lic = lic.lower()
    if "creativecommons.org" in lic:
        if "publicdomain" in lic or "zero" in lic:
            return "cc0"
        m = re.search(r"licenses/([a-z\-]+)/", lic + "/")
        return ("cc-" + m.group(1)) if m else ""
    return lic.replace("_", "-")


def http_get(url, params=None, timeout=30, tries=3, **kw):
    last = None
    for i in range(tries):
        try:
            r = SESSION.get(url, params=params, timeout=timeout, **kw)
            if r.status_code in (429, 500, 502, 503, 504):
                last = f"HTTP {r.status_code}"
                time.sleep(2 + 3 * i)
                continue
            return r
        except requests.RequestException as e:
            last = str(e)
            time.sleep(2 + 3 * i)
    raise RuntimeError(f"GET {url} thất bại: {last}")


def abstract_from_inverted(inv):
    if not inv:
        return ""
    pos = []
    for word, idxs in inv.items():
        for i in idxs:
            pos.append((i, word))
    return " ".join(w for _, w in sorted(pos))


def clean_text(s, limit=None, strip_label=False):
    s = re.sub(r"</?[A-Za-z][A-Za-z0-9:_-]*(?:\s[^<>]*?)?\s*/?>", " ", s or "")
    s = html.unescape(re.sub(r"\s+", " ", s)).strip()
    if strip_label:
        s = re.sub(r"^(abstract|summary)[:.\s]+", "", s, flags=re.I)
    if limit and len(s) > limit:
        s = s[:limit].rsplit(" ", 1)[0] + "…"
    return s


def load_published_dois():
    seen = set()
    if USED_DOIS_FILE.exists():
        try:
            seen |= {norm_doi(d) for d in json.loads(USED_DOIS_FILE.read_text(encoding="utf-8"))}
        except Exception:
            pass
    if POSTS_DIR.exists():
        for f in POSTS_DIR.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                for ref in data.get("references", []):
                    if ref.get("doi"):
                        seen.add(norm_doi(ref["doi"]))
            except Exception:
                pass
    return seen


def save_published_dois(new_dois):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    seen = load_published_dois() | {norm_doi(d) for d in new_dois if d}
    USED_DOIS_FILE.write_text(json.dumps(sorted(seen), ensure_ascii=False, indent=2), encoding="utf-8")


def openalex_search(query, since, work_type="article", sort="publication_date:desc", per_page=20):
    params = {
        "search.title_and_abstract": query,
        "filter": f"from_publication_date:{since},is_oa:true,type:{work_type},has_doi:true",
        "sort": sort,
        "per-page": per_page,
        "select": (
            "id,doi,title,publication_date,authorships,primary_location,"
            "best_oa_location,abstract_inverted_index,language,has_content,cited_by_count"
        ),
    }
    if OPENALEX_API_KEY:
        params["api_key"] = OPENALEX_API_KEY
    if CONTACT_EMAIL:
        params["mailto"] = CONTACT_EMAIL
    r = http_get("https://api.openalex.org/works", params=params)
    r.raise_for_status()
    out = []
    for w in r.json().get("results", []):
        if w.get("language") not in (None, "en"):
            continue
        loc = w.get("best_oa_location") or {}
        src = ((w.get("primary_location") or {}).get("source") or {})
        authors = [a.get("author", {}).get("display_name", "") for a in w.get("authorships", [])]
        out.append({
            "doi": norm_doi(w.get("doi")),
            "title": clean_text(w.get("title")),
            "date": w.get("publication_date", ""),
            "journal": src.get("display_name") or "",
            "authors": [a for a in authors if a],
            "abstract": clean_text(abstract_from_inverted(w.get("abstract_inverted_index")), strip_label=True),
            "license": norm_license(loc.get("license")),
            "landing": loc.get("landing_page_url") or "",
            "pdf": loc.get("pdf_url") or "",
            "openalex_id": (w.get("id") or "").rsplit("/", 1)[-1],
            "has_pdf": bool((w.get("has_content") or {}).get("pdf")),
            "cited": w.get("cited_by_count") or 0,
            "kind": "review" if work_type == "review" else "article",
        })
    return out


def crossref_search(query, since):
    params = {
        "query.bibliographic": re.sub(r'["()]|\bAND\b|\bOR\b', " ", query),
        "filter": f"from-pub-date:{since},type:journal-article,has-license:true",
        "sort": "published",
        "order": "desc",
        "rows": 15,
    }
    if CONTACT_EMAIL:
        params["mailto"] = CONTACT_EMAIL
    r = http_get("https://api.crossref.org/works", params=params)
    r.raise_for_status()
    out = []
    for w in r.json().get("message", {}).get("items", []):
        lic = ""
        for l in w.get("license", []):
            n = norm_license(l.get("URL"))
            if n.startswith("cc"):
                lic = n
                break
        if not lic:
            continue
        dp = (w.get("published") or w.get("issued") or {}).get("date-parts", [[None]])[0]
        date = "-".join(f"{x:02d}" if i else str(x) for i, x in enumerate(dp) if x) if dp and dp[0] else ""
        authors = [f"{a.get('given', '')} {a.get('family', '')}".strip() for a in w.get("author", [])]
        out.append({
            "doi": norm_doi(w.get("DOI")),
            "title": clean_text((w.get("title") or [""])[0]),
            "date": date,
            "journal": (w.get("container-title") or [""])[0],
            "authors": [a for a in authors if a],
            "abstract": clean_text(w.get("abstract", ""), strip_label=True),
            "license": lic,
            "landing": w.get("URL") or "",
            "pdf": "",
            "openalex_id": "",
            "has_pdf": False,
            "cited": w.get("is-referenced-by-count") or 0,
            "kind": "article",
        })
    return out


def select_weekly_topic(now_vn):
    if TOPIC_ROTATION in TOPIC_BY_KEY:
        return TOPIC_BY_KEY[TOPIC_ROTATION], "feature"
    if TOPIC_ROTATION == "digest":
        return None, "digest"
    iso_week = now_vn.isocalendar()[1]
    selected = SOLOWELD_TOPICS[(iso_week - 1) % len(SOLOWELD_TOPICS)]
    return selected, "feature"


def relevant(paper, topic_obj):
    text = f"{paper['title']} {paper['abstract']}".lower()
    return all(re.search(pat, text, re.I) for pat in topic_obj["must"])


def collect_soloweld_papers(selected_topic, mode):
    today = dt.date.today()
    published = load_published_dois()
    topics_to_scan = [selected_topic] if (mode == "feature" and selected_topic) else SOLOWELD_TOPICS

    since_recent = (today - dt.timedelta(days=LOOKBACK_DAYS)).isoformat()
    since_fallback = (today - dt.timedelta(days=365)).isoformat()
    since_review = (today - dt.timedelta(days=3 * 365)).isoformat()

    key_fn = lambda x: (
        x["license"] in REUSABLE_LICENSES,
        bool(mdpi_pdf_urls(x["doi"]) or x.get("has_pdf") or x.get("pdf")),
        x.get("cited", 0),
        x.get("date", ""),
    )

    pools_article = []
    pools_review = []

    for t in topics_to_scan:
        for q in t["queries"]:
            try:
                items = openalex_search(q, since_recent, work_type="article", sort="publication_date:desc", per_page=25)
            except Exception as e:
                diag(f"  OpenAlex lỗi ({q}): {e} -> thử Crossref")
                try:
                    items = crossref_search(q, since_recent)
                except Exception as e2:
                    diag(f"  Crossref lỗi ({q}): {e2}")
                    items = []

            good = [
                it for it in items
                if it["doi"] and it["doi"] not in published and len(it["abstract"]) >= 180 and relevant(it, t)
            ]

            if sum(1 for g in good if g["license"] in REUSABLE_LICENSES) < 3:
                try:
                    more = openalex_search(q, since_fallback, work_type="article", sort="cited_by_count:desc", per_page=25)
                    existing = {g["doi"] for g in good}
                    good += [
                        it for it in more
                        if it["doi"] and it["doi"] not in published and it["doi"] not in existing
                        and len(it["abstract"]) >= 180 and relevant(it, t)
                    ]
                except Exception:
                    pass

            for it in good:
                it["topic"] = t["key"]
            good.sort(key=key_fn, reverse=True)
            pools_article.append(good)
            time.sleep(0.25)

            if mode == "feature":
                try:
                    rev_items = openalex_search(q, since_review, work_type="review", sort="cited_by_count:desc", per_page=15)
                    good_rev = [
                        it for it in rev_items
                        if it["doi"] and it["doi"] not in published and len(it["abstract"]) >= 180 and relevant(it, t)
                    ]
                    for it in good_rev:
                        it["topic"] = t["key"]
                    good_rev.sort(key=key_fn, reverse=True)
                    pools_review.append(good_rev)
                except Exception:
                    pass
                time.sleep(0.25)

    chosen, seen = [], set()

    def take_interleaved(lists, limit):
        added = 0
        while added < limit and any(lists):
            for lst in lists:
                while lst and lst[0]["doi"] in seen:
                    lst.pop(0)
                if lst and added < limit and len(chosen) < MAX_PAPERS:
                    it = lst.pop(0)
                    seen.add(it["doi"])
                    chosen.append(it)
                    added += 1
            if len(chosen) >= MAX_PAPERS:
                break

    if mode == "feature":
        take_interleaved(pools_article, max(0, MAX_PAPERS - 4))
        take_interleaved(pools_review, 4)
        take_interleaved(pools_article, MAX_PAPERS)
    else:
        take_interleaved(pools_article, MAX_PAPERS)

    log(f"Đã chọn {len(chosen)} bài báo khoa học ({sum(1 for c in chosen if c.get('kind') == 'review')} bài review).")
    return chosen


BAD_IMG = re.compile(
    r"(logo|cover|icon|banner|orcid|crossmark|badge|avatar|sprite|placeholder|journal[-_]?thumb|ads?/)",
    re.I,
)
FIG_CONTAINER = re.compile(r"(^|[-_\s])(fig|figure|html-fig|figure-container|figure-wrap)([-_\s\d]|$)", re.I)
FIG_LABEL = re.compile(r"^\s*((?:fig(?:ure)?|hình)\.?\s*\d+[a-z]?)[.:\s]*", re.I)

GOOD_FIG = re.compile(
    r"defect|weld|seam|architecture|network|blockchain|smart contract|accuracy|detection|recognition|"
    r"microstructur|sem\b|ebsd|morpholog|cross[- ]section|hardness|stress|strain|temperature field|"
    r"simulat|melt pool|bead|porosity|crack|comparison|result|system|monitoring|sensor|training",
    re.I,
)
BAD_FIG = re.compile(
    r"specimen|geometr|dimension|sampling|location of|graphical abstract",
    re.I,
)


def figure_score(caption, label):
    score = 2 * len(GOOD_FIG.findall(caption)) - 3 * len(BAD_FIG.findall(caption))
    m = re.search(r"\d+", label or "")
    if m and int(m.group()) == 1:
        score -= 1
    return score


def candidate_images(page_url, soup):
    for junk in soup.find_all(["header", "nav", "footer", "aside"]):
        junk.decompose()
    containers = soup.find_all("figure")
    containers += [
        el for el in soup.find_all(["div", "section"])
        if FIG_CONTAINER.search(" ".join(el.get("class", [])) + " " + (el.get("id") or ""))
    ]
    cands, seen = [], set()
    for fig in containers:
        img = fig.find("img")
        if not img:
            continue
        src = None
        for attr in ("data-large", "data-lsrc", "data-src", "data-original", "data-lazy-src", "src"):
            if img.get(attr):
                src = img[attr]
                break
        if not src and img.get("srcset"):
            src = img["srcset"].split(",")[-1].strip().split(" ")[0]
        a = fig.find("a", href=re.compile(r"\.(jpe?g|png|webp)(\?|$)", re.I))
        if a:
            src = a["href"]
        if not src or src.startswith("data:"):
            continue
        url = urljoin(page_url, src)
        if url in seen or BAD_IMG.search(url):
            continue
        parts = []
        for el in [fig.find("figcaption")] + fig.find_all(class_=re.compile("caption|legend|fig.*desc|description", re.I)):
            t = clean_text(el.get_text(" ")) if el else ""
            if t and not any(t in q for q in parts):
                parts = [q for q in parts if q not in t] + [t]
        caption = clean_text(" ".join(parts), 450)
        if len(caption) < 20:
            continue
        m = FIG_LABEL.match(caption)
        label = m.group(1) if m else ""
        if m:
            caption = caption[m.end():].strip()
        seen.add(url)
        cands.append((url, caption, label))
        if len(cands) >= 8:
            break
    return sorted(cands, key=lambda c: figure_score(c[1], c[2]), reverse=True)


_USED_HASHES = None


def ahash(im):
    resampling = getattr(Image, "Resampling", Image).LANCZOS
    g = im.convert("L").resize((16, 16), resampling)
    px = list(g.getdata())
    avg = sum(px) / len(px)
    return int("".join("1" if v > avg else "0" for v in px), 2)


def used_hashes():
    global _USED_HASHES
    if _USED_HASHES is None:
        _USED_HASHES = []
        if IMG_DIR.exists():
            for f in IMG_DIR.glob("*/*.jpg"):
                try:
                    with Image.open(f) as im:
                        _USED_HASHES.append(ahash(im))
                except Exception:
                    pass
    return _USED_HASHES


def is_used_image(im):
    h = ahash(im)
    return any(bin(h ^ u).count("1") <= 12 for u in used_hashes())


def save_image(data, dest, min_w=400):
    if not data or len(data) > 12_000_000:
        return None
    try:
        im = Image.open(io.BytesIO(data))
        im.load()
    except Exception:
        return None
    w, h = im.size
    if w < min_w or h < 200 or w / h > 4 or h / w > 3:
        return None
    if is_used_image(im):
        diag(f"    Bỏ qua hình trùng lặp với bài trước ({dest.name})")
        return None
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bg = Image.new("RGB", im.size, "white")
        bg.paste(im, mask=im.split()[-1])
        im = bg
    im = im.convert("RGB")
    if w > 1200:
        resampling = getattr(Image, "Resampling", Image).LANCZOS
        im = im.resize((1200, int(h * 1200 / w)), resampling)
    dest.parent.mkdir(parents=True, exist_ok=True)
    im.save(dest, "JPEG", quality=85, optimize=True, progressive=True)
    used_hashes().append(ahash(im))
    return im.size


def download_image(url, referer, dest):
    r = WEB.get(url, timeout=30, headers={"Referer": referer})
    if r.status_code != 200 or "image" not in r.headers.get("Content-Type", "image"):
        return None
    return save_image(r.content, dest)


PDF_CAPTION = re.compile(r"^\s*(fig(?:ure)?\.?\s*\d+[a-z]?)[.:\s]", re.I)


def pdf_figures(pdf_bytes, max_n=8):
    try:
        import pymupdf as fitz
    except ImportError:
        import fitz
    out = []
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    for page in doc:
        if len(out) >= max_n:
            break
        blocks = [b for b in page.get_text("blocks") if b[6] == 0]
        caps = [b for b in blocks if PDF_CAPTION.match(b[4])]
        if not caps:
            continue
        rects = []
        for img in page.get_images(full=True):
            try:
                rects += [r for r in page.get_image_rects(img[0]) if r.width > 60 and r.height > 60]
            except Exception:
                pass
        for cap in caps:
            cap_top = cap[1]
            above = [r for r in rects if r.y1 <= cap_top + 8 and cap_top - r.y1 < 80]
            if not above:
                continue
            clip = above[0]
            for r in above[1:]:
                if r.y1 > clip.y0 - 120:
                    clip |= r
            clip = clip & page.rect
            if clip.width < 150 or clip.height < 100:
                continue
            pix = page.get_pixmap(clip=clip, dpi=170)
            text = clean_text(cap[4], 600)
            m = FIG_LABEL.match(text)
            label = m.group(1) if m else ""
            caption = text[m.end():].strip() if m else text
            if len(caption) >= 20:
                out.append((pix.tobytes("png"), caption[:450], label))
            if len(out) >= max_n:
                break
    return sorted(out, key=lambda f: figure_score(f[1], f[2]), reverse=True)


MDPI_JOURNALS = {
    "ma": "materials", "met": "metals", "cryst": "crystals", "mi": "micromachines", "fluids": "fluids",
    "app": "applsci", "coatings": "coatings", "jmmp": "jmmp", "polym": "polymers", "nano": "nanomaterials",
    "en": "energies", "electronics": "electronics", "machines": "machines", "sensors": "sensors",
    "lubricants": "lubricants", "designs": "designs", "processes": "processes", "jcs": "jcs",
    "alloys": "alloys", "eng": "eng", "technologies": "technologies", "inventions": "inventions",
    "sustainability": "sustainability", "info": "information", "fi": "futureinternet", "systems": "systems",
}


def mdpi_pdf_urls(doi):
    m = re.fullmatch(r"10\.3390/([a-z]+)(\d{2})(\d{2})(\d{4,5})", doi or "")
    if not m or m.group(1) not in MDPI_JOURNALS:
        return []
    j = MDPI_JOURNALS[m.group(1)]
    name = f"{j}-{int(m.group(2))}-{int(m.group(4)):05d}"
    return [
        f"https://mdpi-res.com/d_attachment/{j}/{name}/article_deploy/{name}.pdf",
        f"https://pub.mdpi-res.com/d_attachment/{j}/{name}/article_deploy/{name}.pdf",
    ]


def zenodo_pdf_urls(url):
    m = re.search(r"zenodo\.org/(?:records?|record)/(\d+)", url or "")
    if not m:
        return []
    try:
        r = SESSION.get(f"https://zenodo.org/api/records/{m.group(1)}", timeout=30)
        files = r.json().get("files", []) if r.status_code == 200 else []
        return [f["links"]["self"] for f in files if f.get("key", "").lower().endswith(".pdf")][:1]
    except Exception:
        return []


def get_pdf(p, page_url="", page_pdf=""):
    urls = []
    if p.get("has_pdf") and p.get("openalex_id") and OPENALEX_API_KEY:
        urls.append(f"https://content.openalex.org/works/{p['openalex_id']}.pdf?api_key={OPENALEX_API_KEY}")
    urls += [u for u in (page_pdf, p.get("pdf")) if u]
    urls += zenodo_pdf_urls(page_url or p.get("landing", ""))
    urls += mdpi_pdf_urls(p.get("doi"))
    seen = set()
    for u in urls:
        if u in seen:
            continue
        seen.add(u)
        try:
            r = WEB.get(u, timeout=60, allow_redirects=True, headers={"Accept": "application/pdf,*/*"})
            if r.status_code == 200 and r.content[:5] == b"%PDF-":
                return r.content, u.split("?")[0]
            diag(f"    PDF {u.split('?')[0][:80]} -> HTTP {r.status_code}")
        except Exception as e:
            diag(f"    PDF {u.split('?')[0][:60]} lỗi {type(e).__name__}")
    return None, ""


def collect_figures(papers, post_id):
    figures = []
    for idx, p in enumerate(papers, start=1):
        if len(figures) >= MAX_FIGURES:
            break
        if p["license"] not in REUSABLE_LICENSES:
            continue
        n = len(figures) + 1
        dest = IMG_DIR / post_id / f"fig{n}.jpg"
        got = None
        page = p["landing"] or f"https://doi.org/{p['doi']}"
        page_url, page_pdf = page, ""
        try:
            r = WEB.get(page, timeout=30, allow_redirects=True)
            page_url = r.url
            if r.status_code == 200 and "html" in r.headers.get("Content-Type", ""):
                soup = BeautifulSoup(r.text, "html.parser")
                meta = soup.find("meta", attrs={"name": "citation_pdf_url"})
                page_pdf = urljoin(r.url, meta["content"]) if meta and meta.get("content") else ""
                cands = candidate_images(r.url, soup)
                for url, caption, label in cands:
                    try:
                        size = download_image(url, r.url, dest)
                    except Exception:
                        size = None
                    if size:
                        got = (caption, label, url, "html")
                        break
        except Exception as e:
            diag(f"  [{idx}] HTML lỗi {type(e).__name__}")

        if not got:
            data, src = get_pdf(p, page_url, page_pdf)
            if data:
                try:
                    for png, caption, label in pdf_figures(data):
                        size = save_image(png, dest, min_w=300)
                        if size:
                            got = (caption, label, src, "pdf")
                            break
                except Exception as e:
                    diag(f"  [{idx}] PDF lỗi tách hình: {type(e).__name__}")

        if got:
            caption, label, url, how = got
            figures.append({
                "n": n,
                "paper": idx,
                "src": f"images/news/{post_id}/fig{n}.jpg",
                "caption_original": caption,
                "orig_label": label,
                "source_url": url,
                "license": p["license"],
            })
            diag(f"  + Hình {n} ({how}) từ [{idx}] {p['doi']} {label}")
    return figures


PREFERRED_GEMINI_MODELS = [
    os.environ.get("GEMINI_MODEL", "").strip(),
    os.environ.get("GEMINI_MODEL", "").strip(),
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-1.5-flash",
]

BLOCKED_MODEL_PATTERNS = re.compile(
    r"omni|image|audio|tts|live|robot|vision|thinking|exp|preview|learnlm", re.I
)


def gemini_candidates():
    preferred = [m for m in dict.fromkeys(PREFERRED_GEMINI_MODELS) if m]
    metadata = {}
    try:
        response = SESSION.get(
            "https://generativelanguage.googleapis.com/v1beta/models",
            headers={"x-goog-api-key": GEMINI_API_KEY},
            params={"pageSize": 1000},
            timeout=30,
        )
        if response.status_code == 200:
            for model in response.json().get("models", []):
                name = model.get("name", "").removeprefix("models/")
                if (
                    "generateContent" in model.get("supportedGenerationMethods", [])
                    and "flash" in name
                    and name.startswith("gemini-")
                    and not BLOCKED_MODEL_PATTERNS.search(name)
                ):
                    metadata[name] = model
            ordered = [m for m in preferred if m in metadata]
            for m in sorted(metadata, reverse=True):
                if m not in ordered:
                    ordered.append(m)
            preferred = ordered
    except (requests.RequestException, ValueError):
        log("Không lấy được danh sách model động; dùng danh sách cấu hình mặc định.")
    names = list(dict.fromkeys(preferred))[:5]
    if not names:
        names = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]
    return [(name, metadata.get(name, {})) for name in names]


def gemini_json(prompt):
    errors = []
    started = time.monotonic()
    required = (
        "title_vi", "title_en", "title_zh", "title_ja",
        "summary_vi", "summary_en", "summary_zh", "summary_ja",
        "content_vi", "content_en",
    )
    for model, metadata in gemini_candidates():
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        body = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "maxOutputTokens": min(65536, metadata.get("outputTokenLimit") or 65536),
            },
        }
        for attempt in range(3):
            if time.monotonic() - started > 720:
                raise RuntimeError("Quá thời gian chờ Gemini API (12 phút).")
            retry_after = 0
            try:
                response = SESSION.post(
                    url,
                    headers={"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"},
                    json=body,
                    timeout=180,
                )
            except requests.RequestException as exc:
                reason = type(exc).__name__
            else:
                if response.status_code == 200:
                    try:
                        candidate = response.json()["candidates"][0]
                        if candidate.get("finishReason") != "STOP":
                            raise ValueError("Bài viết bị ngắt giữa chừng (finishReason != STOP)")
                        text = "".join(
                            p.get("text", "")
                            for p in candidate.get("content", {}).get("parts", [])
                            if not p.get("thought")
                        )
                        text = re.sub(r"^```(?:json)?|```$", "", text.strip()).strip()
                        data = json.loads(text)
                        if not isinstance(data, dict) or not all(
                            isinstance(data.get(k), str) and data[k].strip() for k in required
                        ):
                            raise ValueError("Thiếu trường JSON đa ngôn ngữ bắt buộc")
                        log(f"Biên tập thành công với model: {model}")
                        return data
                    except (KeyError, IndexError, TypeError, ValueError) as parse_err:
                        reason = f"Lỗi cấu trúc JSON ({parse_err})"
                else:
                    reason = f"HTTP {response.status_code}"
                    msg = ""
                    try:
                        msg = response.json().get("error", {}).get("message", "")
                        if msg:
                            reason += " - " + re.sub(r"\s+", " ", msg)[:160]
                    except ValueError:
                        pass
                    if response.status_code in (401, 402, 403):
                        raise RuntimeError(f"Gemini {reason}: Kiểm tra GEMINI_API_KEY.")
                    if response.status_code == 404 or (
                        response.status_code == 429 and ("quota" in msg.lower() or "billing" in msg.lower() or attempt >= 1)
                    ):
                        errors.append(f"{model}: {reason}")
                        log(f"Model {model} chạm giới hạn ({reason}) -> chuyển sang model dự phòng.")
                        time.sleep(2)
                        break
                    try:
                        retry_after = max(0, float(response.headers.get("Retry-After", 0)))
                    except (ValueError, TypeError):
                        pass
            errors.append(f"{model}: {reason}")
            log(f"Gemini {model}, lần thử {attempt + 1}/3: {reason}")
            if attempt < 2:
                delay = min(30, max(retry_after, 8 * (2 ** attempt) + random.uniform(0, 3)))
                time.sleep(delay)
    raise RuntimeError("Tất cả model Gemini đều thất bại: " + " | ".join(errors[-8:]))


def build_soloweld_prompt(papers, figures, selected_topic, mode, today, recent_titles):
    fig_of = {f["paper"]: f["n"] for f in figures}
    lines = []
    for i, p in enumerate(papers, 1):
        has = f"  [HAS FIGURE: FIG{fig_of[i]}]" if i in fig_of else ""
        kind = "REVIEW" if p.get("kind") == "review" else "RESEARCH"
        t_info = TOPIC_BY_KEY.get(p.get("topic"), {})
        lines.append(
            f"[{i}] {kind} ({t_info.get('en', 'Welding & AI')}){has}\n"
            f"Title: {p['title']}\n"
            f"Journal: {p['journal']} ({p['date']})\n"
            f"Abstract: {clean_text(p['abstract'], 1800)}\n"
        )
    figs = "\n".join(
        f"FIG{f['n']} – from paper [{f['paper']}]; original caption: {f['caption_original'] or '(none)'}"
        for f in figures
    ) or "(no figures)"

    topic_title = selected_topic["vi"] if selected_topic else "Tổng hợp AI, Thị giác máy tính & Blockchain trong Công nghệ Hàn Quốc tế"
    outline_str = selected_topic["outline"] if selected_topic else (
        "AI & Thị giác máy tính trong tự động hóa và kiểm tra mối hàn;"
        "Blockchain & Smart Contract trong minh bạch hóa chứng chỉ thợ hàn (JWES, AWS, ASME, ISO);"
        "Công nghệ VR/AR và Digital Twin trong đào tạo kỹ sư hàn quốc tế;"
        "Robot hàn thông minh và chế tạo bồi đắp hồ quang dây (WAAM)"
    )

    return f"""You are the Chief Technical Editor for SoloWeld (soloweld.github.io) — an international engineering portal specializing in AI-powered Welding Standards (AWS D1.1, ASME Section IX, ASME Section VIII, ISO, JWES), Welding Automation, and Digital Certification.

Write an IN-DEPTH weekly technical insight article for Saturday ({today}) on the theme:
"{topic_title}"
grounded strictly in the {len(papers)} peer-reviewed Open Access papers supplied below.

STRUCTURE (each section must use an <h3> heading):
1. Lead paragraph (<p class="lead">, 3–4 sentences) highlighting why these technological advances matter right now for welding manufacturing, quality assurance, and international certification.
2. "Bối cảnh Công nghiệp & Tiêu chuẩn Quốc tế" / "Industrial Context & International Standards": Current bottlenecks in welding automation, NDT inspection, and welder/WPS qualification management.
3. 4–5 thematic technical sections based on the papers (Suggested axes: {outline_str}). For each section: explain the architecture/algorithm (e.g., CNN, YOLO, Vision Transformer, Smart Contract, Digital Twin, Multi-sensor fusion), experimental setup, and exact quantitative metrics reported in the abstracts.
4. "Thách thức Triển khai Thực tế" / "Industrial Deployment Challenges": Data scarcity, harsh arc light/spatter environments, interoperability across AWS/ASME/ISO/JWES standards, and cybersecurity/blockchain latency.
5. "Ứng dụng trong Đào tạo Kỹ sư Hàn & Quản lý Chứng chỉ" / "Implications for Welding Engineer Training & Certification Management": Concrete recommendations for welding training centers, QA/QC inspectors, and digital certification ecosystems.

STRICT RULES:
- Cite sources using square brackets immediately after each claim, e.g. "... đạt độ chính xác phát hiện khuyết tật 98.4% [2]." Use ONLY numbers [1]..[{len(papers)}]. Do NOT write a reference list at the end (it is appended automatically).
- Do NOT invent metrics, datasets, or conclusions not present in the provided abstracts.
- VIETNAMESE TERMINOLOGY COMPLIANCE (TCVN 5017-1:2010 / ISO 857-1): Use standard Vietnamese welding engineering terms with English abbreviations in parentheses where helpful: "hàn kim loại (welding)", "hàn nóng chảy (fusion welding)", "hàn áp lực (pressure welding)", "kim loại cơ bản (base metal)", "kim loại điền đầy (filler metal)", "vùng ảnh hưởng nhiệt (HAZ)", "mối hàn (welded joint)", "quy trình hàn (WPS)", "hồ sơ phê duyệt quy trình hàn (PQR)", "chứng chỉ thợ hàn (WPQ)".
- VOICE: Objective, authoritative engineering tone. Never mention any individual blog owner, university, or generic "chuyên gia nhận định". Refer to cited researchers strictly as "nhóm tác giả [n]" / "the authors of [n]".
- FIGURES: Place each figure placeholder exactly once as its own paragraph right after the paragraph discussing its source paper: {{{{FIG1}}}}, {{{{FIG2}}}}... Never write figure numbers inside the prose text.
  Available figures:
{figs}
- Allowed HTML tags inside `content_vi` and `content_en`: <h3>, <h4>, <p>, <ul>, <ol>, <li>, <strong>, <em>, <sub>, <sup>. No inline styles, no <table>, no <img>, no <a>.
- MULTILINGUAL METADATA FOR SOLOWELD UI: Because soloweld.github.io supports 4 UI languages (EN, VI, ZH, JA), provide accurate translations of the article title, summary (2–3 sentences), and category label in ALL 4 languages (`vi`, `en`, `zh`, `ja`), plus full in-depth HTML body (`content_vi`, `content_en`, ~2000–2800 words per language) and concise summaries (`content_zh`, `content_ja`, ~400–600 words in HTML summarizing the core technical sections with [n] citations so ZH/JA readers also get structured technical insights).
- HEADLINE UNIQUENESS: Create a specific, compelling technical headline based on the actual breakthroughs in this week's papers. Avoid generic titles or repeating recent headlines: {json.dumps(recent_titles, ensure_ascii=False)}

Return ONLY a valid JSON object matching this exact schema:
{{
  "category_vi": "Chuyên đề AI & Hàn",
  "category_en": "AI & Welding Insight",
  "category_zh": "AI与焊接专题",
  "category_ja": "AI・溶接技術特集",
  "title_vi": "...",
  "title_en": "...",
  "title_zh": "...",
  "title_ja": "...",
  "summary_vi": "2–3 câu tóm tắt sắc gọn",
  "summary_en": "2–3 concise sentences",
  "summary_zh": "2–3句简明摘要",
  "summary_ja": "2〜3文の簡潔な要約",
  "tags": ["4-6 concise English keywords, e.g. Computer Vision, AWS D1.1, Blockchain, Smart Contract, WAAM"],
  "figure_captions_vi": {{"1": "bản dịch tiếng Việt chuẩn xác, ngắn gọn của chú thích gốc FIG1"}},
  "figure_captions_en": {{"1": "faithful, concise English version of the original FIG1 caption"}},
  "content_vi": "Full in-depth HTML in Vietnamese",
  "content_en": "Full in-depth HTML in English",
  "content_zh": "Structured HTML executive technical digest in Simplified Chinese with <h3> sections and [n] citations",
  "content_ja": "Structured HTML executive technical digest in Japanese with <h3> sections and [n] citations"
}}

PAPERS (Publication digest date: {today}):
{chr(10).join(lines)}"""


ALLOWED_TAGS = {"h3", "h4", "p", "ul", "ol", "li", "strong", "em", "b", "i", "sub", "sup", "br"}


def sanitize(html_text):
    soup = BeautifulSoup(html_text or "", "html.parser")
    for tag in soup.find_all(True):
        if tag.name in ("script", "style", "iframe", "img", "a", "figure"):
            tag.unwrap() if tag.name == "a" else tag.decompose()
        elif tag.name not in ALLOWED_TAGS:
            tag.unwrap()
        else:
            keep_class = tag.get("class") == ["lead"] and tag.name == "p"
            tag.attrs = {"class": "lead"} if keep_class else {}
    return str(soup)


LICENSE_URL = {
    "cc-by": "https://creativecommons.org/licenses/by/4.0/",
    "cc-by-sa": "https://creativecommons.org/licenses/by-sa/4.0/",
    "cc-by-nc": "https://creativecommons.org/licenses/by-nc/4.0/",
    "cc-by-nc-sa": "https://creativecommons.org/licenses/by-nc-sa/4.0/",
    "cc0": "https://creativecommons.org/publicdomain/zero/1.0/",
}


def short_cite(p):
    a = p["authors"]
    first = a[0].split()[-1] if a else "Anon."
    return f"{first}{' et al.' if len(a) > 1 else ''} ({p['date'][:4]})"


def figure_html(f, caption, lang, paper, number=None):
    vi = lang == "vi"
    lic = f["license"].upper().replace("CC-", "CC ")
    lic_html = (
        f'<a href="{LICENSE_URL[f["license"]]}" target="_blank" rel="noopener">{lic}</a>'
        if f["license"] in LICENSE_URL
        else lic
    )
    orig = f.get("orig_label") or ""
    if orig:
        orig = re.sub(r"(?i)^fig(ure)?\.?", "Hình" if vi else "Fig.", orig).strip()
        where = f"{orig} trong bài gốc" if vi else f"{orig} of the original article"
    else:
        where = "Hình trích từ bài gốc" if vi else "Figure reproduced from the original article"
    doi = html.escape(paper["doi"])
    credit = (
        f'{"Nguồn" if vi else "Source"}: {where} – {html.escape(short_cite(paper))}, '
        f'“{html.escape(paper["title"])}”, <em>{html.escape(paper["journal"])}</em>, '
        f'<a href="https://doi.org/{doi}" target="_blank" rel="noopener">doi:{doi}</a> '
        f'[<a href="#ref-{f["paper"]}">{f["paper"]}</a>]. '
        f'{"Giấy phép" if vi else "Licence"}: {lic_html}'
        f'{"; ảnh được thu nhỏ, giữ nguyên nội dung khoa học" if vi else "; resized, content unchanged"}.'
    )
    return (
        f'<figure class="post-figure my-6 rounded-xl overflow-hidden border border-slate-200 bg-slate-50 p-4">'
        f'<img src="{f["src"]}" alt="{html.escape(caption)}" loading="lazy" class="mx-auto rounded-lg max-h-[460px] object-contain">'
        f'<figcaption class="mt-3 text-sm text-slate-600 leading-relaxed">'
        f'<strong class="text-slate-900">{"Hình" if vi else "Figure"} {number or f["n"]}.</strong> {html.escape(caption)} '
        f'<span class="block mt-1 text-xs text-slate-500">{credit}</span></figcaption></figure>'
    )


CITE_RX = re.compile(r"\[(\d+(?:\s*[,;–-]\s*\d+)*)\]")


def cite_numbers(group):
    out = []
    for part in re.split(r"\s*[,;]\s*", group):
        m = re.fullmatch(r"(\d+)\s*[–-]\s*(\d+)", part.strip())
        if m and int(m.group(1)) <= int(m.group(2)) <= int(m.group(1)) + 30:
            out += list(range(int(m.group(1)), int(m.group(2)) + 1))
        elif part.strip().isdigit() and not part.strip().startswith("0"):
            out.append(int(part))
    return out


def renumber_citations(ai, papers, figures):
    n = len(papers)
    order = []
    for key in ("content_vi", "content_en", "content_zh", "content_ja"):
        text = ai.get(key, "") or ""
        for m in re.finditer(r"\{\{\s*FIG(\d+)\s*\}\}|" + CITE_RX.pattern, text):
            if m.group(1):
                f = next((f for f in figures if f["n"] == int(m.group(1))), None)
                nums = [f["paper"]] if f else []
            else:
                nums = cite_numbers(m.group(2))
            if not nums or any(not 1 <= x <= n for x in nums):
                continue
            for x in nums:
                if x not in order:
                    order.append(x)
    order += [x for x in range(1, n + 1) if x not in order]
    new = {old: i for i, old in enumerate(order, 1)}

    def sub(m):
        raw = cite_numbers(m.group(1))
        if not raw or any(x not in new for x in raw):
            return m.group(0)
        return "[" + ", ".join(map(str, sorted({new[x] for x in raw}))) + "]"

    for key in ("content_vi", "content_en", "content_zh", "content_ja"):
        if ai.get(key):
            ai[key] = CITE_RX.sub(sub, ai[key])
    for key in ("figure_captions_vi", "figure_captions_en"):
        caps = ai.get(key) or {}
        for k in list(caps):
            caps[k] = CITE_RX.sub(sub, caps[k] or "")
    for f in figures:
        f["paper"] = new[f["paper"]]
    return [papers[old - 1] for old in order]


def finalize_content(content, figures, captions, lang, papers):
    content = sanitize(content)
    n_ref = len(papers)

    def cite(m):
        nums = cite_numbers(m.group(1))
        if not nums or any(not 1 <= n <= n_ref for n in nums):
            return m.group(0)
        return '<sup class="cite font-semibold text-blue-600">[' + ", ".join(
            f'<a href="#ref-{n}" class="hover:underline">{n}</a>' for n in nums
        ) + "]</sup>"

    content = CITE_RX.sub(cite, content)
    by_n = {f["n"]: f for f in figures}
    token = re.compile(r"(?:<p>\s*)?\{\{\s*FIG(\d+)\s*\}\}(?:\s*</p>)?")

    placed = {int(n) for n in token.findall(content) if int(n) in by_n}
    unused = [f for f in figures if f["n"] not in placed]
    if unused and lang in ("vi", "en"):
        parts = re.split(r"(?=<h3>)", content)
        body = [i for i, part in enumerate(parts) if part.startswith("<h3>")][:-1] or [
            i for i, part in enumerate(parts) if part.startswith("<h3>")
        ]
        for i in body:
            if not unused:
                break
            if token.search(parts[i]):
                continue
            cited = {int(x) for x in re.findall(r'href="#ref-(\d+)"', parts[i])}
            pick = next((f for f in unused if f["paper"] in cited), unused[0])
            unused.remove(pick)
            parts[i] += f"{{{{FIG{pick['n']}}}}}"
        content = "".join(parts)
        for f in unused:
            content += f"{{{{FIG{f['n']}}}}}"

    counter, done = [0], set()

    def put(m):
        n = int(m.group(1))
        if n not in by_n or n in done:
            return ""
        done.add(n)
        counter[0] += 1
        f = by_n[n]
        cap = captions.get(str(n)) or f["caption_original"] or ""
        return figure_html(f, cap, "vi" if lang == "vi" else "en", papers[f["paper"] - 1], number=counter[0])

    content = token.sub(put, content)
    content = re.sub(r"<p>\s*</p>", "", content)
    return content


def write_output(**kv):
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            for k, v in kv.items():
                v = str(v)
                if "\n" in v:
                    f.write(f"{k}<<__EOF__\n{v}\n__EOF__\n")
                else:
                    f.write(f"{k}={v}\n")


def main():
    if not GEMINI_API_KEY:
        sys.exit("Thiếu biến môi trường GEMINI_API_KEY")

    now_vn = dt.datetime.now(VN_TZ)
    today = now_vn.date().isoformat()
    selected_topic, mode = select_weekly_topic(now_vn)

    log(f"=== Bắt đầu tạo bản tin SoloWeld ({today}) ===")
    if selected_topic:
        log(f"Chuyên đề tuần này: {selected_topic['vi']} ({selected_topic['key']})")

    papers = collect_soloweld_papers(selected_topic, mode)
    if len(papers) < MIN_PAPERS:
        log(f"Chỉ tìm thấy {len(papers)} bài báo mới (< {MIN_PAPERS}) -> tạm hoãn xuất bản tuần này.")
        write_output(skipped="true")
        return

    topic_slug = slugify(selected_topic["key"] if selected_topic else "weekly-digest", 40)
    post_id = f"{today}-soloweld-{topic_slug}"

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    POSTS_DIR.mkdir(parents=True, exist_ok=True)
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    (IMG_DIR / ".gitkeep").touch()
    (POSTS_DIR / ".gitkeep").touch()

    if (POSTS_DIR / f"{post_id}.json").exists():
        post_id += "-" + now_vn.strftime("%H%M")

    figures = collect_figures(papers, post_id)
    log(f"Thu thập được {len(figures)} hình minh họa giấy phép mở (CC).")

    recent_titles = []
    if NEWS_INDEX.exists():
        try:
            published_index = json.loads(NEWS_INDEX.read_text(encoding="utf-8"))
            recent_titles = [
                {"vi": item.get("title_vi", ""), "en": item.get("title_en", "")}
                for item in published_index[:25]
            ]
        except Exception:
            pass

    prompt = build_soloweld_prompt(papers, figures, selected_topic, mode, today, recent_titles)

    DRAFT_DIR.mkdir(parents=True, exist_ok=True)
    (DRAFT_DIR / "sources.json").write_text(
        json.dumps(
            {"papers": papers, "figures": figures, "prompt": prompt, "post_id": post_id, "today": today},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    if COMPACT_TEST:
        prompt = prompt.replace("~2000–2800 words", "~450–650 words")
        prompt = prompt.replace("~400–600 words", "~120–180 words")
    ai = gemini_json(prompt)
    papers = renumber_citations(ai, papers, figures)

    refs = [
        {
            "n": i,
            "authors": p["authors"][:6],
            "more_authors": len(p["authors"]) > 6,
            "title": p["title"],
            "journal": p["journal"],
            "date": p["date"],
            "doi": p["doi"],
            "url": f"https://doi.org/{p['doi']}",
            "license": p["license"],
            "topic": p.get("topic", ""),
        }
        for i, p in enumerate(papers, 1)
    ]

    caps_vi = ai.get("figure_captions_vi", {}) or {}
    caps_en = ai.get("figure_captions_en", {}) or {}

    content_vi_final = finalize_content(ai["content_vi"], figures, caps_vi, "vi", papers)
    content_en_final = finalize_content(ai["content_en"], figures, caps_en, "en", papers)
    content_zh_final = finalize_content(ai.get("content_zh") or ai["content_en"], figures, caps_en, "zh", papers)
    content_ja_final = finalize_content(ai.get("content_ja") or ai["content_en"], figures, caps_en, "ja", papers)

    m_cover = re.search(r'<img src="([^"]+)"', content_vi_final)
    cover_img = m_cover.group(1) if m_cover else ""

    post = {
        "id": post_id,
        "date": today,
        "topic_key": selected_topic["key"] if selected_topic else "digest",
        "type": mode,
        "category_vi": clean_text(ai.get("category_vi") or (selected_topic["vi"] if selected_topic else "Điểm tin Công nghệ")),
        "category_en": clean_text(ai.get("category_en") or (selected_topic["en"] if selected_topic else "Tech Digest")),
        "category_zh": clean_text(ai.get("category_zh") or (selected_topic["zh"] if selected_topic else "技术动态")),
        "category_ja": clean_text(ai.get("category_ja") or (selected_topic["ja"] if selected_topic else "技術ダイジェスト")),
        "title_vi": clean_text(ai["title_vi"]),
        "title_en": clean_text(ai["title_en"]),
        "title_zh": clean_text(ai["title_zh"]),
        "title_ja": clean_text(ai["title_ja"]),
        "summary_vi": clean_text(ai["summary_vi"]),
        "summary_en": clean_text(ai["summary_en"]),
        "summary_zh": clean_text(ai["summary_zh"]),
        "summary_ja": clean_text(ai["summary_ja"]),
        "tags": [clean_text(t) for t in ai.get("tags", [])][:6],
        "cover": cover_img,
        "paper_count": len(papers),
        "figure_count": len(figures),
        "content_vi": content_vi_final,
        "content_en": content_en_final,
        "content_zh": content_zh_final,
        "content_ja": content_ja_final,
        "references": refs,
        "generated_by": "SoloWeld AI Editorial Engine (Gemini)",
    }

    post_file = POSTS_DIR / f"{post_id}.json"
    post_file.write_text(json.dumps(post, ensure_ascii=False, indent=2), encoding="utf-8")

    index_data = []
    if NEWS_INDEX.exists():
        try:
            index_data = json.loads(NEWS_INDEX.read_text(encoding="utf-8"))
        except Exception:
            index_data = []

    index_data = [item for item in index_data if item.get("id") != post_id]
    summary_entry = {
        k: post[k]
        for k in (
            "id", "date", "topic_key", "type",
            "category_vi", "category_en", "category_zh", "category_ja",
            "title_vi", "title_en", "title_zh", "title_ja",
            "summary_vi", "summary_en", "summary_zh", "summary_ja",
            "tags", "cover", "paper_count", "figure_count",
        )
    }
    summary_entry["file"] = f"news/posts/{post_id}.json"
    index_data.insert(0, summary_entry)
    NEWS_INDEX.write_text(json.dumps(index_data, ensure_ascii=False, indent=2), encoding="utf-8")

    save_published_dois([p["doi"] for p in papers])

    log(f"Đã xuất bản thành công bài viết: {post['title_vi']} ({post_file})")
    write_output(
        skipped="false",
        post_id=post_id,
        title_vi=post["title_vi"],
        title_en=post["title_en"],
        diag="\n".join(DIAG[-50:]) or "(không có ghi chú)",
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        traceback.print_exc()
        msg = f"{type(e).__name__}: {e}".replace("%", "%25").replace("\r", " ").replace("\n", " ")
        print(f"::error title=SoloWeld Auto News Error::{msg[:900]}")
        sys.exit(1)
