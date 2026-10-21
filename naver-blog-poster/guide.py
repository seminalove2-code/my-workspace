"""차종 총정리 글 (색상·트림·가격). 출고후기를 보고 들어온 분이 차를 고르기 쉽게 한 페이지로 정리한다.

1) extract(): Approach Book PDF 의 색상 페이지에서 외장 색상·시트·휠 사진을 뽑아 data/차종사진 에 저장 (한 번만)
2) make(): 가격표 + 뽑은 사진으로 가격표·색상표·시트휠 카드를 만들고 AI가 본문을 쓴다
3) run_daily(): 하루 한 편씩, data/총정리_순서.txt 순서대로 아직 안 쓴 차종을 쓰고 올린다 (auto_guide.py)
"""
import html
import io
import json
import random
import re
import shutil
import time
from datetime import date, datetime
from pathlib import Path

from pydantic import BaseModel

import ai_providers
import card
from common import (CARD_DIR, DRAFT_FILE, POSTED_FILE, POSTS_DIR, THUMB_FILE, TOPIC_FILE, Block, Draft, write_draft)
from generate import DATA_DIR, GUIDE_DIR, KEYWORD_FILE, PRICE_FILE, matching_series, price_sections, read_text

ASSET_DIR = DATA_DIR / "차종사진"          # PDF 에서 뽑은 사진 (딜러 자료라 저장소에 올리지 않음)
THUMB_DIR = DATA_DIR / "총정리_썸네일"     # 차종별 썸네일로 쓸 실제 사진 (있으면 PDF 사진 대신)
ORDER_FILE = DATA_DIR / "총정리_순서.txt"
RECORD_FILE = DATA_DIR / "총정리_기록.json"
KIND = "총정리"
PRICE_CARD, COLOR_CARD, INTERIOR_CARD = "가격표.png", "색상표.png", "시트휠.png"

FONT = '<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;700;900&display=swap" rel="stylesheet">'
CARD_CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{width:1080px;min-height:1080px;font-family:'Noto Sans KR','Malgun Gothic',sans-serif;background:#f3f5f8;color:#14213d;display:flex;flex-direction:column}
.top{background:#0b1d3a;color:#fff;padding:44px 64px 32px}.stripe{display:flex;gap:6px;margin-bottom:20px}.stripe i{width:46px;height:8px;border-radius:2px}
.s1{background:#7fb6ff}.s2{background:#1c4bb4}.s3{background:#e4242e}h1{font-size:60px;font-weight:900}.sub{font-size:25px;color:#c9d6ea;margin-top:6px}
.foot{margin-top:auto;background:#0b1d3a;color:#fff;padding:24px 64px;display:flex;justify-content:space-between;align-items:center;font-size:24px}.foot b{font-size:28px}
table{margin:30px 64px 0;border-collapse:separate;border-spacing:0 12px;width:952px}
th{font-size:24px;color:#6b7a90;text-align:right;padding:0 24px;font-weight:500}th:first-child{text-align:left}
td{background:#fff;font-size:38px;font-weight:700;text-align:right;padding:22px 24px}td:first-child{text-align:left;border-radius:14px 0 0 14px}
td:last-child{border-radius:0 14px 14px 0}td.ms{color:#1c69d4}td.name{font-size:36px}
.note{padding:6px 64px 24px;font-size:19px;color:#8a97aa}
.white{background:#fff}.g{display:grid;grid-template-columns:repeat(3,1fr);gap:10px 18px;padding:24px 40px}.c{text-align:center}
.img{height:150px;background:center/contain no-repeat}.sq .img{height:230px}
.c b{display:block;font-size:24px;margin-top:4px}.c em{font-style:normal;color:#8a97aa;font-size:19px;font-weight:500}.c small{display:block;font-size:19px;color:#6b7a90}
.t{display:inline-block;margin-top:6px;padding:3px 14px;border-radius:999px;font-size:18px;font-weight:700}
.a{background:#e6eefb;color:#16418f}.m{background:#16418f;color:#fff}.b{background:#eef0f3;color:#5b6b82}
h2{font-size:32px;padding:28px 64px 0;font-weight:900}h2 span{font-size:22px;color:#6b7a90;font-weight:500;margin-left:10px}
"""

SYSTEM = """당신은 네이버 블로그 글을 쓰는 작가입니다. <style> 의 페르소나로 BMW 한 차종의 '색상·트림·가격 총정리' 글을 씁니다.

이 글의 목적: 출고후기를 보고 들어온 분이 3분 안에 "내 차"(트림·외장 색상·시트)를 고르고, 문자로 문의하게 만드는 것.
네이버 검색 노출도 노리므로 <keywords> 에서 이 차종의 대표 키워드를 제목 맨 앞에 넣고, 본문에 자연스럽게 2~4번 씁니다.
<guide> 의 제목 형식과 구조를 그대로 따릅니다.

사실 정보 규칙 (가장 중요):
- 가격, 제원, 옵션은 <prices> 에 있는 것만, 색상·시트·휠은 <colors> 에 있는 것만 씁니다. 숫자를 추측하지 않습니다.
- "가장 많이 출고", "고객님들이 많이 고르는", "인기 1위" 처럼 확인할 수 없는 말은 쓰지 않습니다.
- <colors> 에 색상 자료가 없는 트림은 색상을 단정하지 말고 "문자 주시면 바로 알려드릴게요"로 안내합니다.
- 할인 금액과 딜러 프로모션 조건은 절대 쓰지 않습니다. 프로모션은 이 말투로 한 번만: "공식 딜러라 블로그에는 할인 조건을 적을 수 없는 점~ 너그럽게 이해 부탁드려요 🙏 문자 주시면 이번 달 조건 바로 알려드릴게요!"
- 외부 링크, 카카오톡은 쓰지 않습니다. 연락 방법은 문자와 전화뿐입니다.
- 글 마지막 상담 안내(연락처)는 프로그램이 붙이므로 쓰지 않습니다.

형식 규칙:
- blocks 는 글 순서대로. kind 는 quote(인용구 소제목), paragraph(문단), image(사진), heading(굵은 한 줄) 중 하나.
- image 블록의 text 는 <images> 의 파일 이름을 정확히 그대로 씁니다. 카드 3장(가격표·색상표·시트휠)은 꼭 한 번씩 넣고, 색상 사진은 2~3장만 고릅니다.
- 썸네일은 프로그램이 맨 앞에 넣으므로 blocks 에 넣지 않습니다. 첫 블록은 인사말 문단입니다.
- 네이버 모바일에서 읽기 좋게 한 줄을 짧게 끊고 가운데 정렬에 어울리게 씁니다. 분량은 1,500~2,500자.
- tags 는 # 없이 띄어쓰기 없는 단어 10개 안팎."""


class GuideDraft(BaseModel):
    title: str
    tags: list[str]
    blocks: list[ai_providers.AIBlock]


# ── 이름 ──

def safe(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "_", name).strip()


def key(name: str) -> str:
    """'The 5' / 'THE 5' → '5' 처럼 비교용으로 줄인다."""
    return re.sub(r"[^0-9a-z가-힣]", "", re.sub(r"(?i)^\s*the\s*", "", name).lower())


SUFFIX = [("Gran Coupe", "그란쿠페"), ("ACTIVE TOURER", "액티브 투어러"), ("TOURING", "투어링"),
          ("Convertible", "컨버터블"), ("Coupe", "쿠페")]


def kname(series: str) -> str:
    """'THE 5' → '5시리즈', 'THE 2 Gran Coupe' → '2시리즈 그란쿠페', 'THE X5' → 'X5'"""
    s = re.sub(r"(?i)^the\s+", "", series).strip()
    m = re.match(r"^(\d)\b\s*(.*)$", s)
    if not m:
        return s
    rest = m.group(2)
    for en, ko in SUFFIX:
        rest = re.sub(rf"(?i)\b{en}\b", ko, rest)
    return f"{m.group(1)}시리즈" + (f" {rest.strip()}" if rest.strip() else "")


# ── 1) PDF 에서 사진 뽑기 ──

def _png(doc, xref: int, smask: int):
    import pymupdf
    from PIL import Image
    pix = pymupdf.Pixmap(doc, xref)
    if smask:  # 투명 배경을 살려서 흰 바탕에 얹는다 (안 하면 검은 배경)
        pix = pymupdf.Pixmap(pix, pymupdf.Pixmap(doc, smask))
    if pix.colorspace and pix.colorspace.n > 3:
        pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
    im = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGBA")
    bg = Image.new("RGBA", im.size, "white")
    bg.alpha_composite(im)
    return bg.convert("RGB")


def _overlap(a, b) -> bool:
    return a.x0 < b.x1 and a.x1 > b.x0


def extract(pdf: str | Path, log=print) -> dict[str, int]:
    """색상 페이지('참고를 위한 이미지' 문구가 있는 페이지)마다 사진 아래 '(코드)' 글자를 이름으로 붙여 저장한다."""
    import pymupdf
    doc = pymupdf.open(str(pdf))
    names = list(price_sections()[1])
    if ASSET_DIR.exists():
        shutil.rmtree(ASSET_DIR)
    data: dict[str, dict] = {}
    for pno, page in enumerate(doc):
        if "참고를 위한 이미지" not in page.get_text():
            continue
        lines = [(pymupdf.Rect(l["bbox"]), "".join(s["text"] for s in l["spans"]).strip())
                 for b in page.get_text("dict")["blocks"] for l in b.get("lines", [])]
        lines = [(r, t) for r, t in lines if t]
        heads = [t for _, t in lines if re.match(r"(?i)^the\s+\S", t)]
        m = re.match(r"(?i)^the\s+(.+?)\.\s*(.*)$", max(heads, key=len)) if heads else None
        if not m:
            log(f"  [건너뜀] {pno + 1}쪽: 차종 이름을 못 찾음")
            continue
        series = next((n for n in names if key(m.group(1)) in [key(p) for p in n.split("/")]), "THE " + m.group(1).strip())
        group = {"title": m.group(2).strip() or kname(series), "page": pno + 1, "exterior": [], "seats": [], "wheels": []}
        folder = ASSET_DIR / safe(series)
        folder.mkdir(parents=True, exist_ok=True)
        for im in page.get_images(full=True):
            xref, smask = im[0], im[1]
            for r in page.get_image_rects(xref):
                cx = (r.x0 + r.x1) / 2
                below = [(abs(lr.y0 - r.y1) + abs((lr.x0 + lr.x1) / 2 - cx) * .3, lr, t) for lr, t in lines
                         if "(" in t and r.y1 - 5 <= lr.y0 < r.y1 + 45 and _overlap(lr, r)]
                if not below:
                    continue
                _, lr, label = min(below, key=lambda c: c[0])
                lm = re.match(r"^(.*?)\s*\((.*)\)\s*$", label)
                if not lm:
                    continue
                name, inside = lm.group(1).strip(), lm.group(2).strip()
                parts = [p.strip() for p in inside.split("/")]
                if re.fullmatch(r"[A-Z0-9]{4}", inside) and name:
                    kind, item = "seats", {"name": name, "code": inside}
                elif re.fullmatch(r"[A-Z0-9]{3}", parts[0]) and name:
                    q = " ".join(parts[1:]).lower()
                    avail = "M Sport" if ("msp" in q or "m sport" in q) else "기본형" if "base" in q else "전 트림"
                    kind, item = "exterior", {"name": name, "code": parts[0], "avail": avail}
                else:  # 휠: 사진 아래 "936M" 줄, 그 아래 "(520i & 523d M Sport)" 줄
                    above = [(lr.y0 - ar.y1, t) for ar, t in lines
                             if ar.y0 >= r.y1 - 5 and ar.y1 <= lr.y0 + 3 and _overlap(ar, lr) and "(" not in t]
                    wheel = name or (min(above)[1] if above else "")
                    if not wheel:
                        continue
                    kind, item = "wheels", {"name": wheel, "note": inside}
                file = f"{pno + 1}_{kind}_{len(group[kind]) + 1}.png"
                _png(doc, xref, smask).save(folder / file)
                group[kind].append({**item, "file": file})
        if any(group[k] for k in ("exterior", "seats", "wheels")):
            data.setdefault(series, {"series": series, "groups": []})["groups"].append(group)
            g = group
            log(f"  {pno + 1}쪽 {series} ({g['title']}): 외장 {len(g['exterior'])} · 시트 {len(g['seats'])} · 휠 {len(g['wheels'])}")
    for series, d in data.items():
        (ASSET_DIR / safe(series) / "data.json").write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    missing = [n for n in names if n not in data]
    log(f"[완료] {len(data)}개 차종 사진을 뽑았습니다." + (f"\n  색상 페이지를 못 찾은 차종: {', '.join(missing)}" if missing else ""))
    return {s: sum(len(g["exterior"]) for g in d["groups"]) for s, d in data.items()}


def assets(series: str) -> dict:
    p = ASSET_DIR / safe(series) / "data.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def review_items(series: str) -> list[tuple[str, str]]:
    """확인 화면용 (사진, 설명) 목록"""
    d, out = assets(series), []
    for g in d.get("groups", []):
        for kind, label in (("exterior", "외장"), ("seats", "시트"), ("wheels", "휠")):
            for it in g[kind]:
                extra = it.get("avail") or it.get("code") or it.get("note") or ""
                out.append((str(ASSET_DIR / safe(series) / it["file"]), f"[{g['title']}] {label} · {it['name']} ({extra})"))
    return out


# ── 2) 카드 만들기 ──

def price_rows(section: str) -> list[list[str]]:
    """[판매가격] 에서 트림별 최신 가격. [기본 이름, 기본형 가격, M Sport 가격]"""
    block = section.split("[판매가격]", 1)[1].split("\n[", 1)[0] if "[판매가격]" in section else ""
    rows: dict[str, list[str]] = {}
    for line in block.splitlines():
        m = re.match(r"- (.+?): (.*)$", line.strip())
        if not m or re.search(r"-\d+$", m.group(1)):  # '530e M Sport-1' 같은 중복 표기는 뺀다
            continue
        best = None
        for seg in m.group(2).split(" / "):
            pm = re.search(r"([\d,]+)만원", seg)
            if not pm:
                continue
            y, p = re.search(r"(\d{2})년식", seg), re.search(r"P(\d)", seg)
            rank = (int(y.group(1)) if y else 0, int(p.group(1)) if p else 0)
            if best is None or rank > best[0]:
                best = (rank, pm.group(1))
        if not best:
            continue
        name = m.group(1).strip()
        if re.search(r"M Sport(?! Pro)", name):
            base, col = " ".join(re.sub(r"M Sport", " ", name).split()), 2
        else:
            base, col = name, 1
        rows.setdefault(base, [base, "", ""])[col] = best[1]
    return list(rows.values())


def price_month() -> str:
    m = re.search(r"(\d{4})년\s*(\d{1,2})월", read_text(PRICE_FILE))
    return f"{m.group(1)}년 {int(m.group(2))}월 기준" if m else ""


def _page(title: str, sub: str, inner: str, cfg: dict, cls: str = "") -> str:
    phone = cfg.get("card_phone", "010-3228-3729")
    return (f'<!doctype html><html lang="ko"><head><meta charset="utf-8">{FONT}<style>{CARD_CSS}</style></head>'
            f'<body class="{cls}"><div class="top"><div class="stripe"><i class="s1"></i><i class="s2"></i><i class="s3"></i></div>'
            f'<h1>{html.escape(title)}</h1><div class="sub">{html.escape(sub)}</div></div>{inner}'
            f'<div class="foot"><b>{html.escape(phone)}</b><span>용산 BMW 최현정 대리</span></div></body></html>')


def price_html(series: str, rows: list[list[str]], cfg: dict) -> str:
    two = any(r[2] for r in rows)
    e = html.escape
    if two:
        body = "".join(f'<tr><td class="name">{e(n)}</td><td>{e(b) or "-"}</td><td class="ms">{e(s) or "-"}</td></tr>' for n, b, s in rows)
        head = "<tr><th>모델</th><th>기본형</th><th>M Sport</th></tr>"
    else:
        body = "".join(f'<tr><td class="name">{e(n)}</td><td>{e(b)}</td></tr>' for n, b, _ in rows)
        head = "<tr><th>모델</th><th>판매가격</th></tr>"
    sub = " · ".join(x for x in ("판매가격", "만원", price_month()) if x)
    inner = (f"<table>{head}{body}</table>"
             '<div class="note">가격은 변동될 수 있습니다. 이번 달 조건은 문자로 물어보세요.</div>')
    return _page(f"{kname(series)} 트림별 가격", sub, inner, cfg)


def _uri(series: str, file: str) -> str:
    return (ASSET_DIR / safe(series) / file).resolve().as_uri()


def _sig(items: list[dict], *fields) -> tuple:
    return tuple(tuple(it.get(f, "") for f in fields) for it in items)


def color_html(series: str, d: dict, cfg: dict) -> str:
    groups = [g for g in d["groups"] if g["exterior"]]
    same = len({_sig(g["exterior"], "name", "avail") for g in groups}) == 1
    sections = []
    for g in groups[:1] if same else groups:
        cells = "".join(
            f'<div class="c"><div class="img" style="background-image:url(\'{_uri(series, it["file"])}\')"></div>'
            f'<b>{html.escape(it["name"])} <em>{html.escape(it["code"])}</em></b>'
            f'<span class="t {"m" if it["avail"] == "M Sport" else "b" if it["avail"] == "기본형" else "a"}">{it["avail"]}</span></div>'
            for it in g["exterior"])
        title = "" if same else f"<h2>{html.escape(g['title'])}</h2>"
        sections.append(f'{title}<div class="g">{cells}</div>')
    sub = (" · ".join(g["title"] for g in groups) + " 공통") if same and len(groups) > 1 else "트림에 따라 고를 수 있는 색이 달라요"
    if same and len(groups) == 1:
        sub = f"{groups[0]['title']} 기준 · 트림에 따라 고를 수 있는 색이 달라요"
    return _page(f"{kname(series)} 외장 색상", sub, "".join(sections), cfg, "white")


def interior_html(series: str, d: dict, cfg: dict) -> str:
    seen, sections = set(), []
    for g in d["groups"]:
        sig = (_sig(g["seats"], "name"), _sig(g["wheels"], "name", "note"))
        if sig in seen or not (g["seats"] or g["wheels"]):
            continue
        seen.add(sig)
        cells = "".join(f'<div class="c"><div class="img" style="background-image:url(\'{_uri(series, it["file"])}\')"></div>'
                        f'<b>{html.escape(it["name"])}</b><small>{html.escape(it["code"])}</small></div>' for it in g["seats"])
        wheels = "".join(f'<div class="c"><div class="img" style="background-image:url(\'{_uri(series, it["file"])}\')"></div>'
                         f'<b>{html.escape(it["name"])}</b><small>{html.escape(it["note"])}</small></div>' for it in g["wheels"])
        sections.append(f'<h2>{html.escape(g["title"])}<span>시트 · 휠</span></h2>'
                        f'<div class="g">{cells}</div><div class="g sq">{wheels}</div>')
    return _page(f"{kname(series)} 시트 · 휠", "트림마다 들어가는 시트와 휠이 달라요", "".join(sections), cfg, "white")


def colors_text(d: dict) -> str:
    """AI에게 줄 색상·시트·휠 정리"""
    out = []
    for g in d.get("groups", []):
        out.append(f"[{g['title']}] (Approach Book {g['page']}쪽)")
        out.append("- 외장: " + ", ".join(f"{x['name']}({x['code']}, {x['avail']})" for x in g["exterior"]))
        out.append("- 시트: " + ", ".join(f"{x['name']}({x['code']})" for x in g["seats"]))
        out.append("- 휠: " + ", ".join(f"{x['name']}({x['note']})" for x in g["wheels"]))
    return "\n".join(out) or "(색상 자료 없음)"


def render_cards(cfg: dict, series: str, folder: Path, section: str, d: dict) -> list[tuple[str, str]]:
    """글 폴더에 카드와 색상 사진을 만들고 (파일 이름, 설명) 목록을 돌려준다."""
    pages, images = [], []
    rows = price_rows(section)
    if rows:
        pages.append((price_html(series, rows, cfg), folder / PRICE_CARD, 1080))
        images.append((PRICE_CARD, "트림별 가격표 카드 (모든 트림의 판매가격)"))
    if any(g["exterior"] for g in d.get("groups", [])):
        pages.append((color_html(series, d, cfg), folder / COLOR_CARD, 1080))
        images.append((COLOR_CARD, "외장 색상 한눈에 보기 카드 (색 이름·코드·고를 수 있는 트림)"))
    if any(g["seats"] or g["wheels"] for g in d.get("groups", [])):
        pages.append((interior_html(series, d, cfg), folder / INTERIOR_CARD, 1080))
        images.append((INTERIOR_CARD, "시트 색상과 휠 카드"))
    # 썸네일: 실제 사진이 있으면 그걸, 없으면 PDF 의 첫 외장 색상 사진
    real = next((p for p in THUMB_DIR.glob(f"{safe(series)}.*")), None) if THUMB_DIR.exists() else None
    first = next((g["exterior"][0] for g in d.get("groups", []) if g["exterior"]), None)
    photo = real or (ASSET_DIR / safe(series) / first["file"] if first else None)
    thumb = {"thumb_title": f"BMW {kname(series)} 총정리", "colors": "색상 · 트림 · 가격", "thumb_pos": 75,
             "thumb_fit": "" if real else "contain"}
    (folder / CARD_DIR).mkdir(exist_ok=True)
    pages.append((card.build_thumb_html(thumb, photo, "출고후기", cfg), folder / CARD_DIR / THUMB_FILE, 1080))
    card._shot(pages)
    # 색상 사진 낱장 (AI가 2~3장 골라 넣는다)
    seen = set()
    for g in d.get("groups", []):
        for it in g["exterior"]:
            if it["name"] in seen:
                continue
            seen.add(it["name"])
            name = f"색상_{safe(it['name']).replace(' ', '')}.png"
            shutil.copy(ASSET_DIR / safe(series) / it["file"], folder / name)
            images.append((name, f"외장 색상 사진: {it['name']} ({it['avail']})"))
    return images


# ── 글 쓰기 ──

def folder_for(series: str) -> Path:
    """아직 안 올린 이 차종 글 폴더가 있으면 다시 쓰고, 없으면 새로 만든다."""
    for f in sorted(POSTS_DIR.glob(f"*_총정리_{safe(series)}"), reverse=True):
        if not (f / POSTED_FILE).exists():
            return f
    return POSTS_DIR / f"{datetime.now():%Y%m%d_%H%M}_총정리_{safe(series)}"


def make(cfg: dict, series: str, log=print) -> Path | None:
    header, sections = price_sections()
    if series not in sections:
        log(f"[건너뜀] 가격표에 {series} 가 없습니다.")
        return None
    d = assets(series)
    folder = folder_for(series)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / TOPIC_FILE).write_text(f"종류: {KIND}\n번호판: 없음\n차량: {series} ({kname(series)})\n", encoding="utf-8")
    images = render_cards(cfg, series, folder, sections[series], d)
    content = [("text",
        f"<style>\n{cfg.get('style', '')}\n</style>\n\n"
        f"<guide>\n{read_text(GUIDE_DIR / f'{KIND}.txt')}\n</guide>\n\n"
        f"<keywords>\n{read_text(KEYWORD_FILE)}\n</keywords>\n\n"
        f"<prices>\n{header}\n\n{sections[series]}\n</prices>\n\n"
        f"<colors>\n{colors_text(d)}\n</colors>\n\n"
        "<images>\n" + "\n".join(f"{n}: {desc}" for n, desc in images) + "\n</images>\n\n"
        f"차종: {series} ({kname(series)}). 이 차종의 색상·트림·가격 총정리 글을 써주세요.")]
    log(f"[작성 중] {kname(series)} 총정리 ({ai_providers.provider(cfg)} {ai_providers.model(cfg)})")
    try:
        ai = ai_providers.ask(cfg, SYSTEM, content, GuideDraft)
    except ai_providers.AIError as e:
        log(f"[실패] {series}: {e}")
        return None

    names = {n for n, _ in images}
    blocks, used = [], set()
    for b in ai.blocks:
        text = b.text.strip()
        if b.kind == "image" and (text not in names or text in used):
            continue
        used.add(text)
        blocks.append(Block(b.kind, text))
    # 카드가 빠졌으면 어울리는 소제목 아래에 넣는다
    for name, word in ((PRICE_CARD, "트림"), (COLOR_CARD, "색상"), (INTERIOR_CARD, "시트")):
        if name in names and name not in used:
            at = next((i + 1 for i, b in enumerate(blocks) if b.kind == "quote" and word in b.text), len(blocks))
            blocks.insert(at, Block("image", name))
    blocks.insert(0, Block("image", THUMB_FILE))
    if cfg.get("closing"):
        blocks.append(Block("paragraph", cfg["closing"].strip()))
    tags = [t.strip().lstrip("#").replace(" ", "") for t in ai.tags]
    write_draft(folder / DRAFT_FILE, Draft(ai.title.strip(), [t for t in tags if t], blocks))
    log(f"[완료] {folder / DRAFT_FILE}")
    return folder


# ── 3) 순서와 기록 ──

def load_records() -> dict:
    return json.loads(RECORD_FILE.read_text(encoding="utf-8")) if RECORD_FILE.exists() else {}


def save_records(rec: dict) -> None:
    RECORD_FILE.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")


def series_of(folder: Path) -> str:
    for line in read_text(folder / TOPIC_FILE).splitlines():
        if line.startswith("차량:"):
            return line.split(":", 1)[1].split("(")[0].strip()
    return ""


def record(folder: Path, result: str) -> None:
    """올린 뒤 부른다. result 는 글 주소 또는 '임시저장'."""
    rec = load_records()
    rec[series_of(folder)] = {"date": f"{date.today()}", "url": result, "folder": folder.name}
    save_records(rec)


def set_url(series: str, url: str) -> None:
    """임시저장 글을 직접 발행한 뒤 주소를 넣어두면 출고후기에 링크가 붙는다."""
    rec = load_records()
    rec.setdefault(series, {"date": f"{date.today()}", "folder": ""})["url"] = url.strip()
    save_records(rec)


def publish_now(cfg: dict) -> bool:
    """처음 guide_review_count 편(기본 3편)은 임시저장, 그 뒤로는 바로 발행."""
    if not cfg.get("guide_publish", True):
        return False
    return len(load_records()) >= int(cfg.get("guide_review_count", 3))


def order() -> list[str]:
    names = list(price_sections()[1])
    wanted = [l.strip() for l in read_text(ORDER_FILE).splitlines() if l.strip() and not l.startswith("#")]
    first = [n for n in wanted if n in names]
    return first + [n for n in names if n not in first]


def status_rows() -> list[list[str]]:
    rec = load_records()
    rows, nxt = [], next_series()
    for i, s in enumerate(order(), 1):
        r = rec.get(s)
        if r:
            state = f"완료 {r['date']}" + (" (발행)" if str(r.get("url", "")).startswith("http") else " (임시저장)")
        elif not assets(s):
            state = "사진 없음 (건너뜀)"
        else:
            state = "다음 차례" if s == nxt else "대기"
        rows.append([str(i), s, kname(s), state, (r or {}).get("url", "")])
    return rows


def next_series() -> str | None:
    rec = load_records()
    return next((s for s in order() if s not in rec and assets(s)), None)


def link_for(memo: str) -> str:
    """출고후기 끝에 붙일 총정리 글 안내. 발행된 총정리 글이 없으면 빈 문자열."""
    rec = load_records()
    for s in matching_series(memo):
        url = str(rec.get(s, {}).get("url", ""))
        if url.startswith("http"):
            return f"🔎 {kname(s)} 색상·트림·가격 한눈에 보기 →\n{url}"
    return ""


def run_daily(cfg: dict, wait: bool = False, log=print) -> None:
    """오늘 아직 안 썼으면 다음 차종 한 편을 쓰고 올린다."""
    import post
    today = f"{date.today()}"
    if any(r.get("date") == today for r in load_records().values()):
        log("[건너뜀] 오늘은 이미 총정리 글을 올렸습니다.")
        return
    series = next_series()
    if not series:
        log("[끝] 사진이 있는 모든 차종의 총정리 글을 다 썼습니다.")
        return
    if wait:  # 매일 같은 시각에 올라가지 않게 0~60분 쉬었다가 시작 (08:30 에 켜지면 9:30 전에 끝)
        time.sleep(random.randint(0, 60 * 60))
    folder = make(cfg, series, log)
    if folder and (folder / DRAFT_FILE).exists():
        post.run_posts(cfg, [folder])
