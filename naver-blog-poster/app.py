"""BMW 블로그 글쓰기 화면. 'BMW블로그.bat' 으로 실행하면 프로그램 창이 열린다."""
import contextlib
import io
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import datetime
from pathlib import Path

from common import ROOT

# 창 없이 실행(pythonw)되면 출력할 곳이 없으므로 로그 파일로 보낸다
(ROOT / "logs").mkdir(exist_ok=True)
if sys.stdout is None or sys.stderr is None:
    _log = open(ROOT / "logs" / "app.log", "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stdout or _log
    sys.stderr = sys.stderr or _log

import gradio as gr
from dotenv import load_dotenv
from PIL import Image

import ai_providers
import card
import fetch_reference
import generate
import guide
import login
import post
import task_schedule
import settings_io
from common import (BLUR_DIR, CARD_DIR, CARD_FILE, DRAFT_FILE, POSTED_FILE, POSTS_DIR, THUMB_FILE, TOPIC_FILE, IMAGE_EXTS,
                    Block, Draft, list_images, load_config, needs_blur, read_draft, upload_image)
from common import write_draft as save_draft_file

PRICE_FILE = ROOT / "data" / "가격표.txt"
KINDS = ["출고후기", "차량정보", "프로모션", "일상기록", "상담견적"]
PROVIDERS = ["openai", "claude", "gemini"]


# ── 공통 ──

def run_captured(fn, *args) -> tuple[object, str]:
    """기존 기능이 화면에 찍던 안내 문구를 모아서 돌려준다."""
    buf = io.StringIO()
    result = None
    with contextlib.redirect_stdout(buf):
        try:
            result = fn(*args)
        except BaseException as e:  # sys.exit 도 화면에 보여준다
            print(f"[오류] {e}")
    return result, buf.getvalue().strip()


def vehicle_choices() -> list[tuple[str, str]]:
    if not PRICE_FILE.exists():
        return []
    out = []
    for line in PRICE_FILE.read_text(encoding="utf-8-sig").splitlines():
        m = re.match(r"- (.+?): (.*만원.*)$", line)
        if m:
            out.append((f"{m.group(1)}  —  {m.group(2)}", m.group(1)))
    return out


def price_of(trim: str) -> str:
    for label, value in vehicle_choices():
        if value == trim:
            return "판매가격: " + label.split("—", 1)[1].strip()
    return "가격표에 없는 차량입니다. 글에 가격이 들어가지 않습니다." if trim else ""


def safe_name(text: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "", text).strip()[:40] or "글"


def blur_report(folder: Path) -> str:
    report = folder / BLUR_DIR / "가림_결과.txt"
    if not report.exists():
        return ""
    lines = report.read_text(encoding="utf-8").splitlines()
    missed = [l for l in lines if "못 찾음" in l or "실패" in l]
    head = f"🔒 번호판 가림: {len(lines)}장 처리"
    return head + (" — ⚠️ 아래 사진은 직접 확인하세요  \n" + "  \n".join(missed) if missed else " — 모든 사진에서 번호판을 찾았어요")


def status_of(folder: Path) -> str:
    if (folder / POSTED_FILE).exists():
        first = (folder / POSTED_FILE).read_text(encoding="utf-8").splitlines()[1:2]
        return "발행됨" if first and first[0].startswith("http") else "임시저장됨"
    if (folder / guide.QUEUE_FILE).exists():
        return "아침에 올리기 예약"
    return "초안" if (folder / DRAFT_FILE).exists() else "작성 전"


# ── 글 편집기 ──
# 글은 [[종류, 내용], ...] 목록으로 다룬다. 종류: paragraph / quote / heading / image
# 블록을 고칠 때마다 draft.md 에 바로 저장한다 (저장 버튼 없음).

def load_post(folder: Path) -> tuple[str, str, list[list[str]]]:
    if not (folder / DRAFT_FILE).exists():
        return "", "", []
    d = read_draft(folder / DRAFT_FILE)
    return d.title, ", ".join(d.tags), [[b.kind, b.text] for b in d.blocks]


def store(folder, title, tags, blocks) -> None:
    if not folder:
        raise gr.Error("먼저 글을 만들어 주세요.")
    tag_list = [t.strip().lstrip("#").replace(" ", "") for t in (tags or "").split(",") if t.strip()]
    save_draft_file(Path(folder) / DRAFT_FILE, Draft((title or "").strip() or "제목 없음", tag_list,
                                                     [Block(k, t) for k, t in blocks]))


def unused(folder, blocks) -> list[str]:
    """글 폴더에 있지만 글에 안 들어간 사진 (다시 넣을 수 있게)"""
    if not folder:
        return []
    folder = Path(folder)
    names = [p.name for p in list_images(folder)]
    names += [n for n in (THUMB_FILE, CARD_FILE) if (folder / CARD_DIR / n).exists()]
    used = {t for k, t in blocks if k == "image"}
    return [n for n in names if n not in used]


def opened(folder: Path, log: str = "", note: str | None = None):
    """글 폴더를 편집 화면에 띄운다. OPEN 출력과 순서가 같다."""
    cfg = load_config()
    title, tags, blocks = load_post(folder)
    if note is None:
        note = blur_report(folder) if needs_blur(cfg, folder) else ""
    return (str(folder), note, title, tags, blocks, time.time(), log,
            gr.Dropdown(choices=unused(folder, blocks), value=None))


def changed(folder, title, tags, blocks):
    """순서·사진이 바뀐 뒤: 저장하고 화면을 다시 그린다."""
    store(folder, title, tags, blocks)
    return blocks, time.time(), gr.Dropdown(choices=unused(folder, blocks), value=None)


def move_block(folder, title, tags, blocks, i, step):
    j = i + step
    if 0 <= j < len(blocks):
        blocks[i], blocks[j] = blocks[j], blocks[i]
    return changed(folder, title, tags, blocks)


def remove_block(folder, title, tags, blocks, i):
    blocks.pop(i)
    return changed(folder, title, tags, blocks)


def add_text_below(folder, title, tags, blocks, i):
    blocks.insert(i + 1, ["paragraph", ""])
    return changed(folder, title, tags, blocks)


def set_text(folder, title, tags, blocks, i, value):
    if i < len(blocks) and blocks[i][1] != value:
        blocks[i][1] = value
        store(folder, title, tags, blocks)
    return blocks


def add_photo(folder, title, tags, blocks, name):
    if not name:
        raise gr.Error("넣을 사진을 고르세요.")
    blocks.append(["image", name])
    gr.Info("글 맨 아래에 넣었어요. ⬆ 버튼으로 원하는 자리까지 올리세요.")
    return changed(folder, title, tags, blocks)


def replace_photo(folder, blocks, i, new_file):
    folder, cfg, name = Path(folder), load_config(), blocks[i][1]
    if name in (CARD_FILE, THUMB_FILE):
        raise gr.Error("썸네일·스펙 카드는 바꿀 수 없어요. 썸네일은 다른 사진의 [썸네일로] 버튼을 누르세요.")
    target = (folder / BLUR_DIR / name) if needs_blur(cfg, folder) else (folder / name)
    target.parent.mkdir(exist_ok=True)
    Image.open(new_file).convert("RGB").save(target, quality=92)
    if card.load_card_data(folder):  # 썸네일에 들어간 사진일 수 있으니 다시 그린다
        card.render(folder, cfg)
    gr.Info(f"{name} 사진을 바꿨어요.")
    return time.time()


def use_for_thumb(folder, blocks, i):
    folder = Path(folder)
    if not card.load_card_data(folder):
        raise gr.Error("이 글에는 썸네일이 없어요. (출고후기·차량정보 글에만 만들어요)")
    card.set_card_photo(folder, blocks[i][1], "thumb_photo")
    card.render(folder)
    gr.Info("썸네일 사진을 바꿨어요.")
    return time.time()


def move_thumb(folder, pos):
    if not folder or not card.load_card_data(Path(folder)):
        raise gr.Error("이 글에는 썸네일이 없어요.")
    card.set_thumb_pos(Path(folder), pos)
    card.render(Path(folder))
    return time.time()


PREVIEW_CSS = """<style>
.pv{max-width:560px;margin:0 auto;font-family:'Noto Sans KR','Malgun Gothic',sans-serif;color:#222;text-align:center;line-height:1.85;font-size:15px}
.pv h1{font-size:21px;line-height:1.45;text-align:left;margin:4px 0 6px}.pv .tg{font-size:12px;color:#1c69d4;text-align:left;margin-bottom:14px}
.pv img{width:100%;display:block;margin:12px 0;border-radius:4px}.pv p{margin:0 0 14px;white-space:pre-wrap}
.pv blockquote{margin:26px 0 14px;border-left:4px solid #1c69d4;padding:4px 12px;font-size:17px;font-weight:700;text-align:left}
.pv b.hd{display:block;margin:14px 0;font-size:16px}
.pv table{border-collapse:collapse;width:100%;margin:12px 0;font-size:12.5px;line-height:1.45}.pv th,.pv td{border:1px solid #d5dbe3;padding:6px 4px}
.pv th{background:#f3f5f8}.pv .miss{color:#c00}
</style>"""


def preview_html(folder, title, tags, blocks) -> str:
    """네이버 블로그(휴대폰)에서 보이는 모양에 가깝게 글을 보여준다."""
    if not blocks:
        return ('<div class="pv" style="color:#888;padding:40px 0">왼쪽에 정보를 넣고 <b>✍️ 글 만들기</b>를 누르면 '
                '여기에 완성된 글이 나와요.<br>예전 글은 [📂 지난 글]에서 불러올 수 있어요.</div>')
    import html as h
    cfg = load_config()
    out = [f"<h1>{h.escape(title or '')}</h1>"]
    tag_list = [t.strip() for t in (tags or "").split(",") if t.strip()]
    for k, text in blocks:
        if k == "image":
            img = upload_image(cfg, Path(folder), text) if folder else None
            out.append(f'<img src="/gradio_api/file={img.as_posix()}?t={int(img.stat().st_mtime)}">' if img
                       else f'<p class="miss">⚠️ 사진 없음: {h.escape(text)}</p>')
        elif k == "quote":
            out.append(f"<blockquote>{h.escape(text)}</blockquote>")
        elif k == "heading":
            out.append(f'<b class="hd">{h.escape(text)}</b>')
        elif k == "table":
            out.append(post.table_html(post.table_rows(text)).replace("<p><br></p>", ""))
        else:
            out.append(f"<p>{h.escape(text)}</p>")
    if tag_list and cfg.get("body_tags", True):
        out.append(f'<p class="tg" style="text-align:center">{" ".join("#" + h.escape(t) for t in tag_list[:10])}</p>')
    return PREVIEW_CSS + '<div class="pv">' + "".join(out) + "</div>"


# ── 글 쓰기 ──

def make_post(kind, trim, ext_color, int_color, story, photos, already_blurred):
    if not trim:
        raise gr.Error("차량을 골라주세요.")
    if not photos:
        raise gr.Error("사진을 넣어주세요.")
    folder = POSTS_DIR / f"{datetime.now():%Y%m%d_%H%M}_{safe_name(trim)}"
    folder.mkdir(parents=True, exist_ok=True)
    bad = []
    for i, src in enumerate(photos, 1):
        src = Path(src)
        if src.suffix.lower() not in IMAGE_EXTS:
            bad.append(src.name)
            continue
        shutil.copy(src, folder / f"{i:02d}{src.suffix.lower()}")
    if bad:
        gr.Warning(f"이 파일은 사진 형식이 아니라 뺐습니다: {', '.join(bad)} (아이폰 HEIC는 jpg로 바꿔주세요)")
    vehicle = " / ".join(x for x in (trim, ext_color.strip(), int_color.strip()) if x)
    lines = [f"종류: {kind}", f"차량: {vehicle}", f"출고: {datetime.now():%Y년 %m월}"]
    if already_blurred:
        lines.append("번호판: 직접 가림")
    if story.strip():
        lines += ["고객 이야기:", story.strip()]
    (folder / TOPIC_FILE).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return ai_write(folder)


def ai_write(folder: Path):
    load_dotenv(ROOT / ".env", override=True)
    _, log = run_captured(generate.generate, load_config(), folder)
    if not (folder / DRAFT_FILE).exists():
        gr.Warning("글을 만들지 못했습니다. 아래 [진행 기록]을 확인하세요.")
    return opened(folder, log)


def rewrite(folder):
    if not folder:
        raise gr.Error("먼저 글을 만들어 주세요.")
    folder = Path(folder)
    (folder / DRAFT_FILE).unlink(missing_ok=True)
    return ai_write(folder)


def add_cards_only(folder, title, tags, blocks):
    if not folder:
        raise gr.Error("먼저 글을 만들거나 [지난 글]에서 불러오세요.")
    folder = Path(folder)
    if generate.post_kind(folder) not in ("출고후기", "차량정보"):
        raise gr.Error("썸네일·스펙 카드는 출고후기와 차량정보 글에만 넣어요.")
    store(folder, title, tags, blocks)
    load_dotenv(ROOT / ".env", override=True)
    try:
        text = generate.add_cards(load_config(), folder, (folder / DRAFT_FILE).read_text(encoding="utf-8"))
    except ai_providers.AIError as e:
        raise gr.Error(f"카드 값을 받지 못했습니다: {e}")
    (folder / DRAFT_FILE).write_text(text, encoding="utf-8")
    gr.Info("본문은 그대로 두고 썸네일과 스펙 카드를 넣었어요.")
    return opened(folder)


def new_tables(folder, title, tags, blocks):
    if not folder or generate.post_kind(Path(folder)) != guide.KIND:
        raise gr.Error("총정리 글에서만 쓸 수 있어요.")
    store(folder, title, tags, blocks)
    n = guide.refresh_tables(Path(folder))
    gr.Info(f"제원표 {n}개를 새로 넣었어요. 본문은 그대로예요." if n else "뽑아 둔 제원표가 없어요. [총정리 글] 탭에서 PDF로 다시 뽑아주세요.")
    return opened(Path(folder))


def add_guide_link(folder, title, tags, blocks):
    """이미 만든 글 끝(상담 안내 앞)에 그 차종 총정리 글 링크를 넣는다."""
    if not folder:
        raise gr.Error("먼저 글을 만들거나 [지난 글]에서 불러오세요.")
    cfg = load_config()
    guide.sync_urls(cfg)
    link = guide.link_for((Path(folder) / TOPIC_FILE).read_text(encoding="utf-8-sig"), cfg)
    if not link:
        raise gr.Error("이 차종의 발행된 총정리 글 주소가 없어요. [📚 총정리 글] 탭에서 주소를 넣어주세요.")
    url = link.splitlines()[3]  # 넷째 줄이 총정리 글 주소
    if any(url in t for _, t in blocks):
        raise gr.Error("이미 링크가 들어가 있어요.")
    at = next((i for i, (k, t) in enumerate(blocks) if k == "paragraph" and t.startswith("━")), len(blocks))
    blocks.insert(at, ["paragraph", link])
    gr.Info("상담 안내 바로 위에 총정리 글 링크를 넣었어요.")
    return changed(folder, title, tags, blocks)


def upload_to_naver(folder, title, tags, blocks):
    store(folder, title, tags, blocks)
    folder = Path(folder)
    cfg = load_config()
    kind = generate.post_kind(folder)
    published = guide.publish_now(cfg) if kind == guide.KIND else False if kind == "출고후기" else cfg.get("publish")
    done, log = run_captured(post.run_posts, cfg, [folder])
    if done:
        (folder / guide.QUEUE_FILE).unlink(missing_ok=True)
        gr.Info("발행했어요." if published else "임시저장했어요. 네이버 블로그에서 확인 후 발행하세요.")
    else:
        gr.Warning("올리지 못했습니다. [진행 기록]을 확인하세요.")
    return log


def queue_post(folder, title, tags, blocks):
    store(folder, title, tags, blocks)
    (Path(folder) / guide.QUEUE_FILE).write_text(f"{datetime.now():%Y-%m-%d %H:%M} 예약\n", encoding="utf-8")
    gr.Info("다음 아침 8:30~9:30 사이에 자동으로 올려요. ([총정리 글] 탭에서 매일 자동이 켜져 있어야 해요)")


# ── 총정리 글 탭 ──

def guide_view(series=None):
    rows = guide.status_rows()
    names = [r[1] for r in rows]
    series = series if series in names else (guide.next_series() or (names[0] if names else None))
    return (rows, gr.Dropdown(choices=names, value=series), guide.review_items(series) if series else [],
            task_schedule.status() if sys.platform == "win32" else "윈도우에서만 켤 수 있어요",
            gr.Dropdown(choices=[(guide.kname(n), n) for n in names]), url_note())


def guide_extract(pdf):
    if not pdf:
        if not guide.BOOK_FILE.exists():
            raise gr.Error("Approach Book PDF 파일을 올려주세요.")
        pdf = guide.BOOK_FILE  # 예전에 올린 PDF 로 다시 뽑기
    _, log = run_captured(guide.extract, pdf)
    return (log, *guide_view())


def book_note() -> str:
    if guide.BOOK_FILE.exists():
        t = datetime.fromtimestamp(guide.BOOK_FILE.stat().st_mtime)
        return f"✅ 보관 중인 Approach Book: {t:%Y-%m-%d} 에 올린 파일. **새 달 Approach Book 이 나왔을 때만** 다시 올리세요."
    return "아직 PDF가 없어요. 한 번만 올리면 프로그램이 보관해 두고 계속 씁니다."


def guide_make(series):
    if not series:
        raise gr.Error("차종을 고르세요.")
    if not guide.assets(series):
        raise gr.Error("이 차종은 색상 사진이 없습니다. 먼저 PDF에서 사진을 뽑아주세요.")
    load_dotenv(ROOT / ".env", override=True)
    folder, log = run_captured(guide.make, load_config(), series)
    if not folder:
        raise gr.Error(f"글을 만들지 못했습니다.\n{log}")
    cfg = load_config()
    note = ("이 총정리 글은 바로 발행돼요." if guide.publish_now(cfg)
            else f"처음 {cfg.get('guide_review_count', 3)}편은 임시저장돼요. 네이버에서 확인 후 직접 발행하고, [총정리 글] 탭에 주소를 넣어주세요.")
    return (*opened(folder, log, note), gr.Tabs(selected="write"))


def guide_thumb(series, photo):
    if not series or not photo:
        raise gr.Error("차종을 고르고 사진을 올려주세요.")
    guide.THUMB_DIR.mkdir(parents=True, exist_ok=True)
    for old in guide.THUMB_DIR.glob(f"{guide.safe(series)}.*"):
        old.unlink()
    Image.open(photo).convert("RGB").save(guide.THUMB_DIR / f"{guide.safe(series)}.jpg", quality=92)
    gr.Info(f"{guide.kname(series)} 총정리 썸네일에 이 사진을 씁니다. (번호판은 미리 가려주세요)")
    return None


def guide_url(series, url):
    url = url.strip().split("?")[0]
    if not series:
        raise gr.Error("차종을 고르세요.")
    if not re.match(r"https?://(m\.)?blog\.naver\.com/", url):
        raise gr.Error("네이버 블로그 글 주소(https://blog.naver.com/...)를 붙여넣으세요.")
    guide.set_url(series, url)
    gr.Info(f"이제 {guide.kname(series)} 출고후기 끝에 총정리 글 링크가 붙어요.")
    return guide.status_rows(), "", url_note()


def url_note() -> str:
    rec = guide.load_records()
    done = [f"{guide.kname(s)} ✅" for s in guide.order() if str(rec.get(s, {}).get("url", "")).startswith("http")]
    return "주소가 있는 차종: " + (", ".join(done) if done else "아직 없음")


def find_urls():
    found, log = run_captured(guide.sync_urls, load_config())
    gr.Info(f"{len(found)}개 차종의 글 주소를 찾았어요." if found else "새로 찾은 글이 없어요. 발행 직후라면 몇 분 뒤 다시 눌러보세요.")
    return guide.status_rows(), url_note()


def guide_schedule(on, at):
    if sys.platform != "win32":
        raise gr.Error("윈도우에서만 켤 수 있어요.")
    if on and not re.fullmatch(r"\d{1,2}:\d{2}", at.strip()):
        raise gr.Error("시간은 08:30 처럼 적어주세요.")
    msg = task_schedule.enable(at.strip()) if on else task_schedule.disable()
    gr.Info(msg)
    return task_schedule.status()


def save_category_url(url):
    if url.strip() and not url.strip().startswith("http"):
        raise gr.Error("블로그에서 BMW차량정보 카테고리를 누른 뒤 주소창의 주소(https://...)를 붙여넣으세요.")
    settings_io.set_top("guide_category_url", url.strip())
    gr.Info("저장했어요. 다음 출고후기부터 전 차종 모아보기 링크가 붙어요." if url.strip() else "카테고리 링크를 뺐어요.")


# ── 지난 글 탭 ──

def history():
    rows = []
    if POSTS_DIR.exists():
        for f in sorted((p for p in POSTS_DIR.iterdir() if p.is_dir()), reverse=True):
            title = ""
            if (f / DRAFT_FILE).exists():
                first = (f / DRAFT_FILE).read_text(encoding="utf-8").splitlines()[:1]
                title = first[0].lstrip("# ").strip() if first else ""
            rows.append([f.name, title, status_of(f)])
    return rows, gr.Dropdown(choices=[r[0] for r in rows], value=None)


def load_old(name):
    if not name:
        raise gr.Error("불러올 글을 고르세요.")
    folder = POSTS_DIR / name
    return (*opened(folder, f"불러옴: {name} ({status_of(folder)})"), gr.Tabs(selected="write"))



# ── 설정 탭 ──

def settings_values():
    cfg = load_config()
    name = cfg.get("ai", "openai")
    key_name = ai_providers.KEY_NAMES.get(name, "")
    key_note = "저장된 키 있음" if settings_io.has_env(key_name) else "키가 없습니다. 아래에 붙여넣으세요."
    return (name, ai_providers.model(cfg), key_note,
            "바로 발행" if cfg.get("publish") else "임시저장만", (cfg.get("closing") or "").strip())


def save_ai(name, model_name, key):
    settings_io.set_top("ai", name)
    if model_name.strip():
        settings_io.set_model(name, model_name.strip())
    if key.strip():
        env = ai_providers.KEY_NAMES[name]
        settings_io.set_env(env, key.strip())
        os.environ[env] = key.strip()
    gr.Info("AI 설정을 저장했습니다.")
    return settings_values()[2], ""


def provider_changed(name):
    cfg = load_config()
    cfg["ai"] = name
    key_name = ai_providers.KEY_NAMES[name]
    return ai_providers.model(cfg), ("저장된 키 있음" if settings_io.has_env(key_name)
                                     else "키가 없습니다. 아래에 붙여넣으세요.")


def show_models(name):
    load_dotenv(ROOT / ".env", override=True)
    cfg = load_config()
    cfg["ai"] = name
    try:
        return "\n".join(ai_providers.list_models(cfg))
    except Exception as e:
        return f"목록을 가져오지 못했습니다. API 키를 확인하세요.\n({e})"


def do_login():
    _, log = run_captured(login.main)
    return log or "로그인 창을 닫았습니다."


def save_publish(mode):
    settings_io.set_top("publish", mode == "바로 발행")
    gr.Info(f"올리기 방식: {mode}")


def save_closing(text):
    settings_io.set_block("closing", text)
    gr.Info("글 끝 상담 안내를 저장했습니다.")


def replace_prices(file):
    if not file:
        raise gr.Error("가격표.txt 파일을 올려주세요.")
    PRICE_FILE.parent.mkdir(exist_ok=True)
    shutil.copy(file, PRICE_FILE)
    gr.Info(f"가격표를 바꿨습니다. 차량 {len(vehicle_choices())}개")
    return gr.Dropdown(choices=vehicle_choices())


def update_refs():
    _, log = run_captured(fetch_reference.fetch_list, str(ROOT / "data" / "recommended_refs.txt"))
    return log


def quit_app():
    threading.Timer(0.5, lambda: os._exit(0)).start()
    return "프로그램을 종료했습니다. 이 창을 닫으세요."


# ── 화면 ──

THEME = gr.themes.Soft(primary_hue="blue", neutral_hue="slate",
                       font=[gr.themes.GoogleFont("Noto Sans KR"), "Malgun Gothic", "sans-serif"])
CSS = """
footer {display:none !important}
.gradio-container {max-width: 1320px !important}
.panel {background: var(--block-background-fill); border:1px solid var(--border-color-primary); border-radius:16px; padding:18px !important}
.blk {border:1px solid var(--border-color-primary); border-radius:12px; padding:6px 8px !important; gap:6px !important}
.blk-img img {max-height:300px; object-fit:contain}
.tools {gap:4px !important; flex-wrap:nowrap !important}
.tools button {min-width:0 !important; padding:4px 8px !important; font-size:13px !important}
.quote textarea {font-weight:700; border-left:4px solid #1c69d4 !important}
.hint {color: var(--body-text-color-subdued); font-size:13px}
#make-btn, #queue-btn {font-size:17px !important; min-height:52px}
"""
KIND_LABEL = {"quote": "인용구 소제목", "heading": "굵은 글씨 한 줄", "paragraph": "문단",
              "table": "📊 표 (네이버 표로 들어가요 · 칸을 눌러 바로 고칠 수 있어요)"}


def table_text(df) -> str:
    """편집한 표(Dataframe) → draft.md 의 '| 칸 | 칸 |' 글"""
    rows = [list(df.columns)] + df.astype(str).values.tolist()
    return "\n".join("| " + " | ".join(str(c).replace("|", "/") for c in r) + " |" for r in rows)


def build() -> gr.Blocks:
    with gr.Blocks(title="BMW 블로그 글쓰기") as demo:
        folder = gr.State("")
        blocks = gr.State([])
        ver = gr.State(0.0)  # 바뀌면 글 블록을 다시 그린다
        gr.Markdown("## 🩶 BMW 최현정 대리 블로그")
        with gr.Tabs() as tabs:
            with gr.Tab("✍️ 글 쓰기", id="write"):
                with gr.Row(equal_height=False):
                    # ① 왼쪽: 정보 넣기
                    with gr.Column(scale=4, min_width=360, elem_classes="panel"):
                        gr.Markdown("### ① 정보 넣기")
                        kind = gr.Radio(KINDS, value="출고후기", label="글 종류")
                        trim = gr.Dropdown(vehicle_choices(), value=None, label="차량 (검색 가능)", allow_custom_value=True, filterable=True)
                        price = gr.Markdown(elem_classes="hint")
                        with gr.Row():
                            ext_color = gr.Textbox(label="외장 색상", placeholder="예: 브루클린 그레이", min_width=120)
                            int_color = gr.Textbox(label="시트 색상", placeholder="예: 블랙", min_width=120)
                        photos = gr.File(label="출고 사진 (여러 장을 한 번에 끌어다 놓기)", file_count="multiple",
                                         file_types=["image"], type="filepath", height=150)
                        already = gr.Checkbox(label="번호판을 이미 가렸어요 (체크 안 하면 자동으로 가려요)", value=False)
                        story = gr.Textbox(label="고객 이야기 (카톡으로 받은 글 그대로 붙여넣기)", lines=6,
                                           placeholder="모르면 비워두세요. 차량 중심으로 씁니다.")
                        make_btn = gr.Button("✍️ 글 만들기", variant="primary", elem_id="make-btn")
                        gr.Markdown("1~2분 걸려요. 다 되면 오른쪽에 글이 나와요.", elem_classes="hint")

                    # ② 오른쪽: 확인하고 고치기
                    with gr.Column(scale=6, min_width=520, elem_classes="panel"):
                        gr.Markdown("### ② 확인하고 고치기")
                        plate_note = gr.Markdown()
                        with gr.Tabs(selected="preview") as view_tabs:
                            with gr.Tab("👀 미리보기", id="preview"):
                                prev = gr.HTML()
                            with gr.Tab("✏️ 고치기", id="edit"):
                                gr.Markdown("고친 내용은 바로 저장돼요. 사진은 ⬆⬇로 옮기고 🗑로 빼요.", elem_classes="hint")
                                title = gr.Textbox(label="제목")
                                tags = gr.Textbox(label="태그 (쉼표로 구분)")

                                @gr.render(inputs=[folder, blocks], triggers=[ver.change])
                                def draw(folder_v, blocks_v):
                                    if not blocks_v:
                                        gr.Markdown("왼쪽에 정보를 넣고 **✍️ 글 만들기**를 누르면 여기에 글이 나와요.  \n"
                                                    "예전 글은 [📂 지난 글]에서 불러올 수 있어요.", elem_classes="hint")
                                        return
                                    cfg = load_config()
                                    common_in = [folder, title, tags, blocks]
                                    common_out = [blocks, ver, unused_dd]
                                    for i, (k, text) in enumerate(blocks_v):
                                        with gr.Group(elem_classes="blk"):
                                            if k == "image":
                                                path = upload_image(cfg, Path(folder_v), text) if folder_v else None
                                                label = {THUMB_FILE: "썸네일 (글 맨 처음 · 검색 대표 사진)", CARD_FILE: "스펙 카드"}.get(text, text)
                                                if path:
                                                    gr.Image(str(path), label=f"📷 {label}", interactive=False, height=300,
                                                             elem_classes="blk-img")
                                                else:
                                                    gr.Markdown(f"⚠️ 사진 없음: {text}")
                                            elif k == "table":
                                                rows = post.table_rows(text)
                                                df = gr.Dataframe(value=rows[1:], headers=rows[0] if rows else None, interactive=True, wrap=True,
                                                                  label=KIND_LABEL["table"], max_height=900,
                                                                  column_widths=["26%"] + [f"{74 / max(1, len(rows[0]) - 1):.0f}%"] * (len(rows[0]) - 1) if rows else None)
                                                df.input(lambda f, t, g, b, v, i=i: set_text(f, t, g, b, i, table_text(v)), [*common_in, df], blocks)
                                            else:
                                                tb = gr.Textbox(text, label=KIND_LABEL.get(k, "문단"), lines={"paragraph": 3, "table": 8}.get(k, 1),
                                                                max_lines=30, elem_classes="quote" if k == "quote" else "")
                                                tb.blur(lambda f, t, g, b, v, i=i: set_text(f, t, g, b, i, v), [*common_in, tb], blocks)
                                            with gr.Row(elem_classes="tools"):
                                                up = gr.Button("⬆", size="sm")
                                                down = gr.Button("⬇", size="sm")
                                                rm = gr.Button("🗑 빼기", size="sm", variant="stop")
                                                add = gr.Button("＋ 아래에 문단", size="sm")
                                                if k == "image" and text not in (THUMB_FILE, CARD_FILE):
                                                    thumb = gr.Button("🖼 썸네일로", size="sm")
                                                    swap = gr.UploadButton("🔁 사진 바꾸기", size="sm", file_types=["image"], type="filepath")
                                                    thumb.click(lambda f, b, i=i: use_for_thumb(f, b, i), [folder, blocks], ver)
                                                    swap.upload(lambda f, b, file, i=i: replace_photo(f, b, i, file), [folder, blocks, swap], ver)
                                            up.click(lambda f, t, g, b, i=i: move_block(f, t, g, b, i, -1), common_in, common_out)
                                            down.click(lambda f, t, g, b, i=i: move_block(f, t, g, b, i, 1), common_in, common_out)
                                            rm.click(lambda f, t, g, b, i=i: remove_block(f, t, g, b, i), common_in, common_out)
                                            add.click(lambda f, t, g, b, i=i: add_text_below(f, t, g, b, i), common_in, common_out)

                                with gr.Row():
                                    unused_dd = gr.Dropdown(label="뺐던 사진 다시 넣기", scale=3)
                                    add_btn = gr.Button("＋ 넣기", scale=1)
                        with gr.Row():
                            queue_btn = gr.Button("⏰ 아침 8:30~9:30에 올리기", variant="primary", elem_id="queue-btn", scale=2)
                            upload_btn = gr.Button("📤 지금 바로 올리기", scale=1)
                        gr.Markdown("출고후기는 언제나 임시저장으로 올라가요. 네이버에서 확인하고 발행하세요.", elem_classes="hint")
                        with gr.Accordion("더 보기 (다시 쓰기 · 썸네일 위치 · 진행 기록)", open=False):
                            with gr.Row():
                                redo_btn = gr.Button("🔄 AI가 처음부터 다시 쓰기")
                                cards_btn = gr.Button("🖼 썸네일·스펙 카드만 넣기")
                                tables_btn = gr.Button("📊 제원표만 새로 넣기 (총정리)")
                                link_btn = gr.Button("🔗 총정리 글 링크 넣기 (출고후기)")
                            thumb_pos = gr.Slider(0, 100, value=75, step=5, label="썸네일 사진 위치 (작게: 위쪽 · 크게: 아래쪽)")
                            log = gr.Textbox(label="진행 기록", lines=6, interactive=False)

                OPEN = [folder, plate_note, title, tags, blocks, ver, log, unused_dd]
                ver.change(preview_html, [folder, title, tags, blocks], prev)
                blocks.change(preview_html, [folder, title, tags, blocks], prev)
                trim.change(price_of, trim, price)
                make_btn.click(make_post, [kind, trim, ext_color, int_color, story, photos, already], OPEN)
                redo_btn.click(rewrite, folder, OPEN)
                cards_btn.click(add_cards_only, [folder, title, tags, blocks], OPEN)
                tables_btn.click(new_tables, [folder, title, tags, blocks], OPEN)
                link_btn.click(add_guide_link, [folder, title, tags, blocks], [blocks, ver, unused_dd])
                for box in (title, tags):
                    box.blur(lambda f, t, g, b: store(f, t, g, b) if f else None, [folder, title, tags, blocks], None).then(
                        preview_html, [folder, title, tags, blocks], prev)
                add_btn.click(add_photo, [folder, title, tags, blocks, unused_dd], [blocks, ver, unused_dd])
                thumb_pos.release(move_thumb, [folder, thumb_pos], ver)
                upload_btn.click(upload_to_naver, [folder, title, tags, blocks], log)
                queue_btn.click(queue_post, [folder, title, tags, blocks], None)

            with gr.Tab("📚 총정리 글", id="guide"):
                gr.Markdown("차종별 **색상·트림·가격 총정리** 글을 하루 한 편씩 써요. "
                            "출고후기 끝에 그 차종 총정리 글 링크가 자동으로 붙어요.")
                with gr.Column(elem_classes="panel"):
                    gr.Markdown("### 🔗 발행한 총정리 글 주소 (출고후기 링크에 쓰여요)")
                    gr.Markdown("직접 발행하거나 예약 발행한 글은 프로그램을 켤 때 블로그에서 **저절로 찾아요.** "
                                "안 찾아지면 아래에 직접 넣으세요.", elem_classes="hint")
                    with gr.Row():
                        g_url_series = gr.Dropdown(label="차종", filterable=True, scale=2)
                        g_url = gr.Textbox(label="글 주소 (https://blog.naver.com/hotpickconnect/...)", scale=4)
                    with gr.Row():
                        g_url_btn = gr.Button("💾 주소 저장", variant="primary")
                        g_find_btn = gr.Button("🔍 블로그에서 지금 찾기")
                    g_url_note = gr.Markdown()
                with gr.Row(equal_height=False):
                    with gr.Column(scale=1, elem_classes="panel"):
                        gr.Markdown("### ① 처음 한 번: 사진 뽑기")
                        g_book = gr.Markdown(book_note)
                        g_pdf = gr.File(label="Approach Book PDF (전체 파일)", file_types=[".pdf"], type="filepath", height=130)
                        g_extract_btn = gr.Button("📥 색상·시트·휠 사진 뽑기 (1~2분)", variant="primary")
                        g_log = gr.Textbox(label="뽑은 결과", lines=4, interactive=False)
                    with gr.Column(scale=1, elem_classes="panel"):
                        gr.Markdown("### ③ 매일 자동으로 쓰기")
                        g_time = gr.Textbox(value="08:30", label="시작 시각 (이 시각부터 1시간 안에 올라가요)")
                        with gr.Row():
                            g_on = gr.Button("▶ 매일 자동 켜기", variant="primary")
                            g_off = gr.Button("■ 끄기")
                        g_sched = gr.Markdown()
                        gr.Markdown("PC가 켜져 있어야 해요. 꺼져 있던 날은 다음에 켤 때 한 편 써요. "
                                    "[⏰ 아침에 올리기]로 예약한 글도 이때 같이 올라가요.", elem_classes="hint")
                with gr.Column(elem_classes="panel"):
                    gr.Markdown("### ② 차종별 확인 — 사진과 이름이 맞는지 훑어보세요")
                    with gr.Row():
                        g_series = gr.Dropdown(label="차종", filterable=True, scale=2)
                        g_make_btn = gr.Button("✍️ 이 차종 총정리 글 지금 만들기", scale=2)
                    g_gallery = gr.Gallery(label="뽑은 사진", columns=7, height=300)
                    with gr.Accordion("썸네일을 실제 사진으로 바꾸기 (선택)", open=False):
                        with gr.Row():
                            g_thumb = gr.File(label="번호판 가린 사진", file_types=["image"], type="filepath", height=120)
                            g_thumb_btn = gr.Button("이 사진을 썸네일로")
                with gr.Column(elem_classes="panel"):
                    gr.Markdown("### 진행 상황")
                    g_table = gr.Dataframe(headers=["순서", "차종", "이름", "상태", "글 주소"], interactive=False)
                    g_refresh = gr.Button("새로고침")
                    with gr.Row():
                        g_cat = gr.Textbox(label="블로그 'BMW차량정보' 카테고리 주소 (넣으면 출고후기에 '다른 차종도 전부 정리해 뒀어요' 링크도 붙어요)",
                                           value=lambda: load_config().get("guide_category_url", ""), scale=4)
                        g_cat_btn = gr.Button("카테고리 주소 저장", scale=1)

                g_view = [g_table, g_series, g_gallery, g_sched, g_url_series, g_url_note]
                g_extract_btn.click(guide_extract, g_pdf, [g_log, *g_view]).then(book_note, None, g_book)
                g_series.input(lambda s: guide.review_items(s), g_series, g_gallery)
                g_thumb_btn.click(guide_thumb, [g_series, g_thumb], g_thumb)
                g_make_btn.click(guide_make, g_series, [*OPEN, tabs])
                g_on.click(lambda t: guide_schedule(True, t), g_time, g_sched)
                g_off.click(lambda t: guide_schedule(False, t), g_time, g_sched)
                g_url_btn.click(guide_url, [g_url_series, g_url], [g_table, g_url, g_url_note])
                g_url_series.input(lambda s: str(guide.load_records().get(s, {}).get("url", "")) if s else "", g_url_series, g_url)
                g_find_btn.click(find_urls, None, [g_table, g_url_note])
                g_refresh.click(guide_view, g_series, g_view)
                g_cat_btn.click(save_category_url, g_cat, None)

            with gr.Tab("📂 지난 글", id="history"):
                with gr.Column(elem_classes="panel"):
                    with gr.Row():
                        pick = gr.Dropdown(label="불러올 글", scale=3)
                        load_btn = gr.Button("✏️ 불러와서 고치기", variant="primary", scale=1)
                        refresh_btn = gr.Button("새로고침", scale=1)
                    table = gr.Dataframe(headers=["폴더", "제목", "상태"], interactive=False)
                refresh_btn.click(history, None, [table, pick])
                load_btn.click(load_old, pick, [*OPEN, tabs])

            with gr.Tab("⚙️ 설정", id="settings"):
                with gr.Row(equal_height=False):
                    with gr.Column(elem_classes="panel"):
                        gr.Markdown("### AI")
                        ai_name = gr.Radio(PROVIDERS, label="글을 쓸 AI")
                        ai_model = gr.Textbox(label="모델 이름")
                        key_note = gr.Markdown()
                        api_key = gr.Textbox(label="API 키 (바꿀 때만 붙여넣기)", type="password")
                        with gr.Row():
                            save_ai_btn = gr.Button("AI 설정 저장", variant="primary")
                            models_btn = gr.Button("쓸 수 있는 모델 보기")
                        models_out = gr.Textbox(label="모델 목록", lines=4, interactive=False)
                    with gr.Column(elem_classes="panel"):
                        gr.Markdown("### 네이버")
                        login_btn = gr.Button("네이버 로그인 (창이 열리면 로그인하세요)")
                        login_out = gr.Textbox(label="로그인 결과", lines=2, interactive=False)
                        publish = gr.Radio(["임시저장만", "바로 발행"], label="올리기 방식 (출고후기는 언제나 임시저장)")
                        gr.Markdown("### 자료")
                        price_file = gr.File(label="새 가격표.txt", file_types=[".txt"], type="filepath", height=110)
                        price_btn = gr.Button("가격표 바꾸기")
                        refs_btn = gr.Button("추천 레퍼런스 다시 받기 (1~2분)")
                        refs_out = gr.Textbox(label="레퍼런스 결과", lines=3, interactive=False)
                with gr.Column(elem_classes="panel"):
                    gr.Markdown("### 글 끝 상담 안내 (모든 글 마지막에 그대로 붙어요)")
                    closing = gr.Textbox(lines=10, show_label=False)
                    closing_btn = gr.Button("상담 안내 저장")
                with gr.Row():
                    quit_btn = gr.Button("프로그램 종료", variant="stop")
                    quit_out = gr.Markdown()

                ai_name.input(provider_changed, ai_name, [ai_model, key_note])
                save_ai_btn.click(save_ai, [ai_name, ai_model, api_key], [key_note, api_key])
                models_btn.click(show_models, ai_name, models_out)
                login_btn.click(do_login, None, login_out)
                publish.input(save_publish, publish, None)
                closing_btn.click(save_closing, closing, None)
                price_btn.click(replace_prices, price_file, trim)
                refs_btn.click(update_refs, None, refs_out)
                quit_btn.click(quit_app, None, quit_out)

        demo.load(settings_values, None, [ai_name, ai_model, key_note, publish, closing])
        demo.load(guide_view, None, g_view)
        demo.load(history, None, [table, pick])
        demo.load(lambda: time.time(), None, ver)  # 처음 화면에 안내 문구 그리기
    return demo



def free_port(start: int = 7860) -> int:
    for port in range(start, start + 50):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    return start


def open_window(url: str) -> None:
    """주소창 없는 프로그램 창(크롬 앱 모드)으로 연다. 크롬이 없으면 기본 브라우저."""
    time.sleep(2)
    for chrome in (Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Google/Chrome/Application/chrome.exe",
                   Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Google/Chrome/Application/chrome.exe",
                   Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe"):
        if chrome.exists():
            subprocess.Popen([str(chrome), f"--app={url}", "--window-size=1400,950"])
            return
    webbrowser.open(url)


if __name__ == "__main__":
    load_dotenv(ROOT / ".env")
    threading.Thread(target=lambda: (guide.refresh_if_needed(), guide.sync_urls(load_config())), daemon=True).start()
    port = free_port()
    url = f"http://127.0.0.1:{port}"
    if "--no-window" not in sys.argv:
        threading.Thread(target=open_window, args=(url,), daemon=True).start()
    build().launch(server_name="127.0.0.1", server_port=port, inbrowser=False, quiet=True,
                   allowed_paths=[str(POSTS_DIR), str(guide.ASSET_DIR), str(guide.THUMB_DIR)], footer_links=[],
                   theme=THEME, css=CSS)
