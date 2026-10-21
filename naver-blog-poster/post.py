"""draft.md 를 네이버 블로그 스마트에디터에 입력하고 발행한다.

사용법:
  python post.py                 # draft.md 는 있고 아직 안 올린 모든 글
  python post.py 글폴더이름        # 특정 폴더만
  python post.py 글폴더이름 --test  # 끝까지 입력만 하고 발행 버튼은 안 누름 (처음 테스트용)
"""
import random
import sys
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import FrameLocator, Page, TimeoutError as PWTimeout, sync_playwright

from browser import open_browser
from common import (DRAFT_FILE, POSTED_FILE, ROOT, Draft, load_config, post_folders,
                    read_draft, resolve_folder)

# 네이버 에디터 화면이 바뀌면 여기만 고치면 된다.
SEL = {
    "editor_frame": "#mainFrame",
    "popup_cancel": ".se-popup-button-cancel",          # "작성 중인 글이 있습니다" → 취소
    "help_close": ".se-help-panel-close-button",        # 도움말 패널 닫기
    "title": ".se-documentTitle .se-text-paragraph",
    "body_text": ".se-component.se-text .se-text-paragraph",
    "components": ".se-components-wrap > .se-component",
    "image_component": ".se-component.se-image",
    "image_button": "button.se-image-toolbar-button",
    "publish_open": "button[class*='publish_btn']",     # 오른쪽 위 '발행'
    "save": "button[class*='save_btn']",                # '저장' (임시저장)
    "publish_layer": "div[class*='layer_publish']",
    "category_button": "button[class*='selectbox_button']",
    "tag_input": "input[placeholder*='태그']",
    "publish_confirm": "button[class*='confirm_btn']",  # 레이어 안 최종 '발행'
}


def pause(a: float = 0.3, b: float = 0.8) -> None:
    time.sleep(random.uniform(a, b))


def close_popups(ed: FrameLocator) -> None:
    for key in ("popup_cancel", "help_close"):
        btn = ed.locator(SEL[key])
        try:
            btn.first.click(timeout=2500)
            pause()
        except PWTimeout:
            pass


def type_lines(page: Page, text: str) -> None:
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if line:
            page.keyboard.insert_text(line)
        if i < len(lines) - 1:
            page.keyboard.press("Enter")
        pause(0.05, 0.2)


def move_caret_below_last(page: Page, ed: FrameLocator) -> None:
    """사진을 넣은 뒤, 사진 아래 새 줄로 커서를 옮긴다."""
    last = ed.locator(SEL["components"]).last
    if "se-image" in (last.get_attribute("class") or ""):
        last.click()
        page.keyboard.press("Enter")
    else:
        last.locator(".se-text-paragraph").last.click()
        page.keyboard.press("End")
    pause()


def insert_image(page: Page, ed: FrameLocator, path: Path) -> None:
    before = ed.locator(SEL["image_component"]).count()
    with page.expect_file_chooser() as fc:
        ed.locator(SEL["image_button"]).first.click()
    fc.value.set_files(str(path))
    # 업로드가 끝나 사진이 하나 늘어날 때까지 대기
    deadline = time.time() + 60
    while ed.locator(SEL["image_component"]).count() <= before:
        if time.time() > deadline:
            raise RuntimeError(f"사진 업로드가 끝나지 않았습니다: {path.name}")
        time.sleep(0.5)
    pause(1.0, 2.0)
    move_caret_below_last(page, ed)


def fill_editor(page: Page, ed: FrameLocator, folder: Path, draft: Draft) -> None:
    ed.locator(SEL["title"]).first.click()
    page.keyboard.insert_text(draft.title)
    pause()

    ed.locator(SEL["body_text"]).last.click()
    for i, block in enumerate(draft.blocks):
        if block.kind == "image":
            path = folder / block.text
            if not path.exists():
                print(f"  [주의] 사진 파일이 없어 건너뜀: {block.text}")
                continue
            insert_image(page, ed, path)
            continue
        if block.kind == "heading":
            page.keyboard.press("Control+B")
            page.keyboard.insert_text(block.text)
            page.keyboard.press("Control+B")
        else:
            type_lines(page, block.text)
        next_is_image = i + 1 < len(draft.blocks) and draft.blocks[i + 1].kind == "image"
        if not next_is_image:
            page.keyboard.press("Enter")
            page.keyboard.press("Enter")
        pause()


def open_publish_layer(ed: FrameLocator, cfg: dict, tags: list[str]) -> None:
    ed.locator(SEL["publish_open"]).first.click()
    layer = ed.locator(SEL["publish_layer"]).first
    layer.wait_for(timeout=10000)
    pause()

    category = (cfg.get("category") or "").strip()
    if category:
        try:
            layer.locator(SEL["category_button"]).first.click(timeout=3000)
            layer.get_by_text(category, exact=True).first.click(timeout=3000)
        except PWTimeout:
            print(f"  [주의] 카테고리 '{category}'를 찾지 못해 기본 카테고리로 둡니다.")
        pause()

    tag_input = layer.locator(SEL["tag_input"]).first
    for tag in tags[:30]:
        tag_input.click()
        tag_input.type(tag, delay=30)
        tag_input.press("Enter")
        pause(0.2, 0.4)


def post_one(page: Page, cfg: dict, folder: Path, test: bool) -> None:
    draft = read_draft(folder / DRAFT_FILE)
    print(f"[입력 중] {folder.name}: {draft.title}")

    page.goto(f"https://blog.naver.com/{cfg['blog_id']}?Redirect=Write&")
    page.wait_for_load_state("domcontentloaded")
    if "nid.naver.com" in page.url:
        sys.exit("로그인이 풀렸습니다. login.bat 을 다시 실행하세요.")

    ed = page.frame_locator(SEL["editor_frame"])
    ed.locator(SEL["title"]).first.wait_for(timeout=30000)
    pause(1.5, 2.5)
    close_popups(ed)

    fill_editor(page, ed, folder, draft)

    if test:
        open_publish_layer(ed, cfg, draft.tags)
        input("[테스트] 발행 직전까지 입력했습니다. 브라우저에서 확인 후 Enter 를 누르면 창을 닫습니다 (발행 안 함)...")
        return

    if cfg.get("publish", True):
        open_publish_layer(ed, cfg, draft.tags)
        ed.locator(SEL["publish_layer"]).first.locator(SEL["publish_confirm"]).first.click()
        page.wait_for_url(lambda url: "Redirect=Write" not in url, timeout=30000)
        result = page.url
        print(f"[발행 완료] {result}")
    else:
        ed.locator(SEL["save"]).first.click()
        pause(2.0, 3.0)
        result = "임시저장"
        print("[임시저장 완료] 네이버 블로그 글쓰기 → 임시저장 글에서 확인하세요.")

    (folder / POSTED_FILE).write_text(f"{datetime.now():%Y-%m-%d %H:%M}\n{result}\n", encoding="utf-8")


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    test = "--test" in sys.argv
    cfg = load_config()
    if cfg.get("blog_id") in (None, "", "my_blog_id"):
        sys.exit("config.yaml 의 blog_id 를 내 블로그 아이디로 바꿔주세요.")

    if args:
        folders = [resolve_folder(args[0])]
    else:
        folders = [f for f in post_folders()
                   if (f / DRAFT_FILE).exists() and not (f / POSTED_FILE).exists()]
    if not folders:
        print("올릴 글이 없습니다. (draft.md 가 있고 posted.txt 가 없는 폴더를 올립니다)")
        return

    with sync_playwright() as pw:
        ctx = open_browser(pw, cfg, headless=False if test else None)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        for folder in folders:
            try:
                post_one(page, cfg, folder, test)
            except Exception as e:  # 한 글이 실패해도 다음 글은 계속
                shot = ROOT / "logs" / f"error_{datetime.now():%Y%m%d_%H%M%S}.png"
                shot.parent.mkdir(exist_ok=True)
                page.screenshot(path=str(shot), full_page=True)
                print(f"[실패] {folder.name}: {e}\n  화면 캡처: {shot}")
            pause(5, 10)
        ctx.close()


if __name__ == "__main__":
    main()
