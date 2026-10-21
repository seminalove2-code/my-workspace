"""차량 스펙 카드 이미지(1080x1350)를 만든다. 글 폴더의 _card 폴더에 저장한다.

카드 값은 AI가 가격표·메모에서 뽑은 것(card.json)이고, 사진은 그 글의 사진 중 하나다.
"""
import html
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

from common import CARD_DIR, CARD_FILE, THUMB_FILE, list_images, load_config, upload_image

CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{width:1080px;height:1350px;display:flex;flex-direction:column;overflow:hidden;
 font-family:'Noto Sans KR','Malgun Gothic','Apple SD Gothic Neo',sans-serif;background:#f3f5f8;color:#14213d}
.top{background:#0b1d3a;color:#fff;padding:44px 64px 32px;position:relative}
.stripe{display:flex;gap:6px;margin-bottom:26px}.stripe i{width:46px;height:8px;border-radius:2px}
.s1{background:#7fb6ff}.s2{background:#1c4bb4}.s3{background:#e4242e}
.series{font-size:26px;letter-spacing:6px;color:#9fb6d9;font-weight:500}
h1{font-size:76px;font-weight:900;letter-spacing:-1px;margin-top:6px;line-height:1.1}
h1.long{font-size:58px}
.sub{font-size:26px;color:#c9d6ea;margin-top:10px}
.who{position:absolute;right:64px;top:62px;text-align:right;font-size:22px;color:#9fb6d9;line-height:1.5}
.photo{height:310px;flex:none;background:#c9d0da center/cover no-repeat}
.price{display:flex;justify-content:space-between;align-items:baseline;padding:22px 64px 4px}
.price span{font-size:28px;color:#5b6b82;font-weight:500}
.price b{font-size:62px;color:#1c69d4;font-weight:900}
.price small{font-size:24px;color:#5b6b82;margin-left:8px}
.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;padding:14px 64px}
.tile{background:#fff;border-radius:16px;padding:16px 22px;box-shadow:0 2px 0 #e3e8ef}
.tile p{font-size:21px;color:#6b7a90}
.tile b{display:block;font-size:32px;font-weight:700;margin-top:4px}
.tile b.txt{font-size:25px}
.tile b em{font-style:normal;font-size:22px;color:#6b7a90;font-weight:500;margin-left:4px}
.size{padding:6px 64px 0;font-size:22px;color:#5b6b82}
.opts{padding:20px 64px 0;display:flex;flex-wrap:wrap;gap:10px}
.opts span{background:#e6eefb;color:#16418f;border-radius:999px;padding:9px 18px;font-size:21px;font-weight:500}
.note{padding:14px 64px 16px;font-size:17px;color:#8a97aa}
.foot{margin-top:auto;background:#0b1d3a;color:#fff;padding:26px 64px;display:flex;justify-content:space-between;align-items:center}
.foot b{font-size:28px}.foot p{font-size:22px;color:#c9d6ea;margin-top:4px}
.tag{text-align:right;font-size:22px;color:#9fb6d9;line-height:1.5}
"""


THUMB_CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{width:1080px;height:1080px;overflow:hidden;position:relative;background:#222;
 font-family:'Noto Sans KR','Malgun Gothic','Apple SD Gothic Neo',sans-serif}
.bg{position:absolute;inset:0;background:#33455f no-repeat;background-size:cover}
.t{position:absolute;left:0;right:0;text-align:center;font-weight:900;font-style:italic;transform:skewX(-6deg);
 paint-order:stroke fill;letter-spacing:-2px;line-height:1.05;white-space:nowrap;
 filter:drop-shadow(0 6px 8px rgba(0,0,0,.45))}
.top1{top:40px;font-size:96px;color:#1c69d4;-webkit-text-stroke:16px #fff}
.top1 span{font-size:64px}
.top2{top:150px;font-size:112px;color:#fff;-webkit-text-stroke:18px #0b1d3a}
.bot1{bottom:118px;color:#fff;-webkit-text-stroke:18px #0b1d3a}
.bot2{bottom:40px;font-size:62px;color:#fff;-webkit-text-stroke:14px #1c69d4}
"""
# 아래 큰 줄 아래에 붙는 작은 줄 (출고후기는 색상, 나머지는 글 종류)
KIND_LABEL = {"차량정보": "실차 리뷰 · 가격 정리", "프로모션": "공식 금융 프로그램", "상담견적": "구매 상담"}


def _e(text: str) -> str:
    return html.escape(str(text or "").strip())


def build_html(card: dict, photo: Path | None, cfg: dict) -> str:
    tiles = [("최고출력", card.get("power"), "마력"), ("최대토크", card.get("torque"), "kg.m"),
             ("0-100km/h", card.get("zero100"), "초"), ("엔진", card.get("engine"), None),
             ("구동 · 변속기", card.get("drive"), None), ("최고속도", card.get("top_speed"), "km/h")]
    tile_html = "".join(
        f'<div class="tile"><p>{_e(k)}</p>' +
        (f'<b>{_e(v)}<em>{u}</em></b>' if u else f'<b class="txt">{_e(v)}</b>') + "</div>"
        for k, v, u in tiles if str(v or "").strip())
    opts = "".join(f"<span>{_e(o)}</span>" for o in (card.get("options") or [])[:8] if str(o).strip())
    phone = cfg.get("card_phone", "010-3228-3729")
    who = cfg.get("card_who", "BMW 한독모터스<br>용산전시장 최현정 대리")
    tag = cfg.get("card_tagline", "좋은 차는 기본, 좋은 담당자는 선택.<br>BMW는 최현정입니다 🩶")
    model = _e(card.get("model"))
    sub = " · ".join(x for x in (_e(card.get("year")), _e(card.get("colors"))) if x)
    photo_css = (f"background-image:url('{photo.resolve().as_uri()}');background-position:center {card.get('photo_pos', 65)}%"
                 if photo else "")
    price = (f'<div class="price"><span>판매가격</span><div><b>{_e(card["price"])}</b><small>만원</small></div></div>'
             if str(card.get("price") or "").strip() else "")
    size = f'<div class="size">크기 {_e(card["size"])}</div>' if str(card.get("size") or "").strip() else ""
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;700;900&display=swap" rel="stylesheet">
<style>{CSS}</style></head><body>
<div class="top"><div class="stripe"><i class="s1"></i><i class="s2"></i><i class="s3"></i></div>
<div class="series">{_e(card.get("series"))}</div>
<h1 class="{'long' if len(model) > 16 else ''}">{model}</h1><div class="sub">{sub}</div>
<div class="who">{who}</div></div>
<div class="photo" style="{photo_css}"></div>
{price}<div class="grid">{tile_html}</div>{size}<div class="opts">{opts}</div>
<div class="note">가격·제원은 2026년 10월 기준이며 변동될 수 있습니다.</div>
<div class="foot"><div><b>{_e(phone)}</b><p>문자 환영 · 관심 차종만 보내주셔도 됩니다</p></div>
<div class="tag">{tag}</div></div></body></html>"""


def build_thumb_html(card: dict, photo: Path | None, kind: str, cfg: dict) -> str:
    """출고후기 스타일: 위에 'BMW 한독모터스 / 용산 최현정대리', 아래에 차량과 색상 (사진은 밝게 그대로)."""
    big = _e(card.get("thumb_title") or card.get("model"))
    if kind == "출고후기" or not KIND_LABEL.get(kind):
        small = _e(card.get("colors"))
        small = f"({small})" if small else ""
    else:
        small = _e(KIND_LABEL[kind])
    size = 92 if len(big) <= 14 else max(56, int(92 * 14 / len(big)))
    pos = card.get("thumb_pos", 75)
    photo_css = f"background-image:url('{photo.resolve().as_uri()}');background-position:center {pos}%" if photo else ""
    top1 = cfg.get("thumb_top1", "BMW <span>한독모터스</span>")
    top2 = _e(cfg.get("thumb_top2", "용산 최현정대리"))
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@900&display=swap" rel="stylesheet">
<style>{THUMB_CSS}</style></head><body><div class="bg" style="{photo_css}"></div>
<div class="t top1">{top1}</div><div class="t top2">{top2}</div>
<div class="t bot1" style="font-size:{size}px">{big}</div><div class="t bot2">{small}</div></body></html>"""


def set_thumb_pos(folder: Path, pos: int) -> None:
    card = load_card_data(folder)
    card["thumb_pos"] = int(pos)
    (folder / CARD_DIR / "card.json").write_text(json.dumps(card, ensure_ascii=False, indent=1), encoding="utf-8")


def save_card_data(folder: Path, card: dict) -> None:
    d = folder / CARD_DIR
    d.mkdir(exist_ok=True)
    old = load_card_data(folder)
    card = {**card, "photo": old.get("photo", ""), "thumb_photo": old.get("thumb_photo", ""),
            "thumb_pos": old.get("thumb_pos", 75)}
    (d / "card.json").write_text(json.dumps(card, ensure_ascii=False, indent=1), encoding="utf-8")


def load_card_data(folder: Path) -> dict:
    p = folder / CARD_DIR / "card.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def set_card_photo(folder: Path, name: str, which: str = "photo") -> None:
    """which: 'photo' = 스펙 카드 사진, 'thumb_photo' = 썸네일 사진"""
    card = load_card_data(folder)
    card[which] = name
    (folder / CARD_DIR / "card.json").write_text(json.dumps(card, ensure_ascii=False, indent=1), encoding="utf-8")


def _shot(pages: list[tuple[str, Path, int]]) -> None:
    """(html, 저장할 png, 높이) 목록을 한 번에 사진으로 찍는다."""
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        for page_html, out, height in pages:
            src = out.with_suffix(".html")
            src.write_text(page_html, encoding="utf-8")
            page = browser.new_page(viewport={"width": 1080, "height": height})
            page.goto(src.resolve().as_uri())
            try:
                page.wait_for_load_state("networkidle", timeout=8000)  # 글꼴 받기 (인터넷 없으면 맑은 고딕)
            except Exception:
                pass
            page.screenshot(path=str(out))
            page.close()
        browser.close()


def _pick(folder: Path, cfg: dict, chosen: str) -> Path | None:
    names = [p.name for p in list_images(folder)]
    name = chosen if chosen in names else (names[0] if names else "")
    return upload_image(cfg, folder, name) if name else None


def render(folder: Path, cfg: dict | None = None, kind: str = "") -> Path | None:
    """card.json 으로 스펙 카드와 썸네일을 다시 그린다. 사진은 고른 것, 없으면 첫 사진(번호판 가린 사본)."""
    cfg = cfg or load_config()
    card = load_card_data(folder)
    if not card:
        return None
    kind = kind or card.get("kind", "")
    d = folder / CARD_DIR
    _shot([(build_html(card, _pick(folder, cfg, card.get("photo", "")), cfg), d / CARD_FILE, 1350),
           (build_thumb_html(card, _pick(folder, cfg, card.get("thumb_photo", "")), kind, cfg), d / THUMB_FILE, 1080)])
    return d / CARD_FILE
