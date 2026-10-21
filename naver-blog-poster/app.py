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
import fetch_reference
import generate
import login
import post
import settings_io
from common import (BLUR_DIR, DRAFT_FILE, IMAGE_LINE, POSTED_FILE, POSTS_DIR, TOPIC_FILE, IMAGE_EXTS,
                    list_images, load_config, needs_blur, read_draft, upload_image)

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


def gallery_items(folder: Path, cfg: dict) -> list[tuple[str, str]]:
    items = []
    for img in list_images(folder):
        shown = upload_image(cfg, folder, img.name) or img
        items.append((str(shown), img.name))
    return items


def blur_report(folder: Path) -> str:
    report = folder / BLUR_DIR / "가림_결과.txt"
    if not report.exists():
        return ""
    lines = report.read_text(encoding="utf-8").splitlines()
    missed = [l for l in lines if "못 찾음" in l or "실패" in l]
    head = f"번호판 가림: {len(lines)}장 처리"
    return head + (" — 아래 사진은 직접 확인하세요\n" + "\n".join(missed) if missed else " — 모든 사진에서 번호판을 찾았습니다")


def preview_md(folder: str, text: str) -> str:
    """미리보기: [사진: x] 자리에 실제 사진(가린 사본)을 보여주고 줄바꿈을 살린다."""
    if not text:
        return ""
    cfg = load_config()
    out = []
    for line in text.splitlines():
        m = IMAGE_LINE.match(line.strip())
        if m and folder:
            img = upload_image(cfg, Path(folder), m.group(1))
            out.append(f'<img src="/gradio_api/file={img.as_posix()}" width="420">' if img
                       else f"⚠️ 사진 없음: {m.group(1)}")
        elif line.startswith(("# ", "## ")):
            out.append(line)
        elif line.startswith("> "):
            out.append(f"> **{line[2:]}**")
        else:
            out.append(line + "  ")  # 마크다운에서 줄바꿈 유지
    return "\n".join(out)


def status_of(folder: Path) -> str:
    if (folder / POSTED_FILE).exists():
        first = (folder / POSTED_FILE).read_text(encoding="utf-8").splitlines()[1:2]
        return "발행됨" if first and first[0].startswith("http") else "임시저장됨"
    return "초안" if (folder / DRAFT_FILE).exists() else "작성 전"


# ── 글 쓰기 탭 ──

def make_post(kind, trim, ext_color, int_color, story, photos, plate_mode):
    if not trim:
        raise gr.Error("차량을 골라주세요.")
    if not photos:
        raise gr.Error("사진을 넣어주세요.")
    cfg = load_config()
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
    if plate_mode == "이미 가렸음":
        lines.append("번호판: 직접 가림")
    if story.strip():
        lines += ["고객 이야기:", story.strip()]
    (folder / TOPIC_FILE).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return write_draft(folder)


def write_draft(folder: Path):
    cfg = load_config()
    load_dotenv(ROOT / ".env", override=True)
    _, log = run_captured(generate.generate, cfg, folder)
    draft = folder / DRAFT_FILE
    text = draft.read_text(encoding="utf-8") if draft.exists() else ""
    if not text:
        gr.Warning("글을 만들지 못했습니다. 아래 진행 기록을 확인하세요.")
    note = blur_report(folder) if needs_blur(cfg, folder) else "번호판: 직접 가린 사진을 그대로 씁니다."
    return (str(folder), gallery_items(folder, cfg), note, text, preview_md(str(folder), text), log)


def rewrite(folder):
    if not folder:
        raise gr.Error("먼저 글을 만들어 주세요.")
    folder = Path(folder)
    (folder / DRAFT_FILE).unlink(missing_ok=True)
    return write_draft(folder)


def save_draft(folder, text):
    if not folder:
        raise gr.Error("먼저 글을 만들어 주세요.")
    (Path(folder) / DRAFT_FILE).write_text(text, encoding="utf-8")
    return preview_md(folder, text)


def replace_photo(folder, selected, new_file):
    if not folder or not selected:
        raise gr.Error("위 사진 목록에서 바꿀 사진을 먼저 클릭하세요.")
    if not new_file:
        raise gr.Error("바꿔 넣을 사진을 올려주세요.")
    folder, cfg = Path(folder), load_config()
    target = (folder / BLUR_DIR / selected) if needs_blur(cfg, folder) else (folder / selected)
    target.parent.mkdir(exist_ok=True)
    Image.open(new_file).convert("RGB").save(target, quality=92)
    gr.Info(f"{selected} 사진을 바꿨습니다.")
    return gallery_items(folder, cfg), None


def on_select(evt: gr.SelectData, folder):
    items = gallery_items(Path(folder), load_config()) if folder else []
    name = items[evt.index][1] if 0 <= evt.index < len(items) else ""
    return name, f"선택한 사진: {name}"


def upload_to_naver(folder, text):
    if not folder:
        raise gr.Error("먼저 글을 만들어 주세요.")
    folder = Path(folder)
    save_draft(str(folder), text)
    read_draft(folder / DRAFT_FILE)  # 제목 없는 글이면 여기서 알려준다
    cfg = load_config()
    done, log = run_captured(post.run_posts, cfg, [folder])
    if done:
        gr.Info("임시저장했습니다. 네이버 블로그에서 확인 후 발행하세요." if not cfg.get("publish")
                else "발행했습니다.")
    else:
        gr.Warning("올리지 못했습니다. 아래 기록을 확인하세요.")
    return log


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
    cfg = load_config()
    draft = folder / DRAFT_FILE
    text = draft.read_text(encoding="utf-8") if draft.exists() else ""
    return (str(folder), gallery_items(folder, cfg), blur_report(folder), text, preview_md(str(folder), text),
            f"불러옴: {name} ({status_of(folder)})", gr.Tabs(selected="write"))


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

def build() -> gr.Blocks:
    with gr.Blocks(title="BMW 블로그 글쓰기") as demo:
        folder = gr.State("")
        selected = gr.State("")
        gr.Markdown("## BMW 최현정 대리 블로그 글쓰기")
        with gr.Tabs() as tabs:
            with gr.Tab("글 쓰기", id="write"):
                with gr.Row():
                    with gr.Column():
                        kind = gr.Dropdown(KINDS, value="출고후기", label="글 종류")
                        trim = gr.Dropdown(vehicle_choices(), label="차량 (가격표에서 고르기, 검색 가능)",
                                           allow_custom_value=True, filterable=True)
                        price = gr.Markdown()
                        with gr.Row():
                            ext_color = gr.Textbox(label="외장 색상", placeholder="예: 브루클린 그레이")
                            int_color = gr.Textbox(label="시트 색상", placeholder="예: 블랙")
                        story = gr.Textbox(label="고객 이야기 (선택) — 카톡으로 받은 글을 그대로 붙여넣으세요",
                                           lines=8, placeholder="모르면 비워두세요. AI가 차량 중심으로 씁니다.")
                    with gr.Column():
                        photos = gr.File(label="사진 (여러 장을 한 번에 끌어다 놓으세요)",
                                         file_count="multiple", file_types=["image"], type="filepath")
                        plate_mode = gr.Radio(["자동으로 가리기", "이미 가렸음"], value="자동으로 가리기",
                                              label="번호판")
                        make_btn = gr.Button("✍️ 글 만들기", variant="primary", size="lg")
                gr.Markdown("### 미리보기")
                plate_note = gr.Textbox(label="번호판 확인", lines=2, interactive=False)
                gallery = gr.Gallery(label="블로그에 올라갈 사진 (사진을 클릭하면 바꿀 수 있어요)",
                                     columns=6, height=260, allow_preview=True)
                with gr.Row():
                    sel_note = gr.Markdown("")
                    new_photo = gr.File(label="바꿔 넣을 사진", file_types=["image"], type="filepath")
                    swap_btn = gr.Button("선택한 사진 바꾸기")
                with gr.Row():
                    editor = gr.Textbox(label="글 (여기서 바로 고칠 수 있어요)", lines=28)
                    preview = gr.Markdown(label="보이는 모양", height=640)
                with gr.Row():
                    save_btn = gr.Button("💾 고친 내용 저장")
                    redo_btn = gr.Button("🔄 다시 쓰기")
                    upload_btn = gr.Button("📤 네이버에 올리기", variant="primary")
                log = gr.Textbox(label="진행 기록", lines=6, interactive=False)

                trim.change(price_of, trim, price)
                outs = [folder, gallery, plate_note, editor, preview, log]
                make_btn.click(make_post, [kind, trim, ext_color, int_color, story, photos, plate_mode], outs)
                redo_btn.click(rewrite, folder, outs)
                editor.change(preview_md, [folder, editor], preview)
                save_btn.click(save_draft, [folder, editor], preview).then(lambda: gr.Info("저장했습니다."))
                gallery.select(on_select, folder, [selected, sel_note])
                swap_btn.click(replace_photo, [folder, selected, new_photo], [gallery, new_photo])
                upload_btn.click(upload_to_naver, [folder, editor], log)

            with gr.Tab("지난 글", id="history"):
                table = gr.Dataframe(headers=["폴더", "제목", "상태"], interactive=False)
                with gr.Row():
                    pick = gr.Dropdown(label="불러올 글")
                    load_btn = gr.Button("글 쓰기 화면으로 불러오기")
                    refresh_btn = gr.Button("새로고침")
                refresh_btn.click(history, None, [table, pick])
                load_btn.click(load_old, pick, [folder, gallery, plate_note, editor, preview, log, tabs])

            with gr.Tab("설정", id="settings"):
                gr.Markdown("#### AI")
                with gr.Row():
                    ai_name = gr.Radio(PROVIDERS, label="글을 쓸 AI")
                    ai_model = gr.Textbox(label="모델 이름")
                key_note = gr.Markdown()
                api_key = gr.Textbox(label="API 키 (바꿀 때만 붙여넣기)", type="password")
                with gr.Row():
                    save_ai_btn = gr.Button("AI 설정 저장", variant="primary")
                    models_btn = gr.Button("쓸 수 있는 모델 보기")
                models_out = gr.Textbox(label="모델 목록", lines=6, interactive=False)

                gr.Markdown("#### 네이버")
                with gr.Row():
                    login_btn = gr.Button("네이버 로그인 (창이 열리면 로그인하세요)")
                    publish = gr.Radio(["임시저장만", "바로 발행"], label="올리기 방식")
                login_out = gr.Textbox(label="로그인 결과", lines=2, interactive=False)

                gr.Markdown("#### 글 끝 상담 안내 (모든 글 마지막에 그대로 붙어요)")
                closing = gr.Textbox(lines=10, show_label=False)
                closing_btn = gr.Button("상담 안내 저장")

                gr.Markdown("#### 자료")
                with gr.Row():
                    price_file = gr.File(label="새 가격표.txt 올리기", file_types=[".txt"], type="filepath")
                    price_btn = gr.Button("가격표 바꾸기")
                refs_btn = gr.Button("추천 레퍼런스 다시 받기 (1~2분)")
                refs_out = gr.Textbox(label="레퍼런스 결과", lines=4, interactive=False)

                gr.Markdown("---")
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
        demo.load(history, None, [table, pick])
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
    port = free_port()
    url = f"http://127.0.0.1:{port}"
    if "--no-window" not in sys.argv:
        threading.Thread(target=open_window, args=(url,), daemon=True).start()
    build().launch(server_name="127.0.0.1", server_port=port, inbrowser=False, quiet=True,
                   allowed_paths=[str(POSTS_DIR)], footer_links=[])
