"""draft.md 를 네이버 블로그 스마트에디터에 입력하고 발행한다.

사용법:
  python post.py                 # draft.md 는 있고 아직 안 올린 모든 글
  python post.py 글폴더이름        # 특정 폴더만
  python post.py 글폴더이름 --test  # 끝까지 입력만 하고 발행 버튼은 안 누름 (처음 테스트용)
"""
import html
import random
import sys
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import Error as PWError, FrameLocator, Page, TimeoutError as PWTimeout, sync_playwright

from browser import open_browser
from common import (CARD_DIR, DRAFT_FILE, with_fixed_tags, POSTED_FILE, ROOT, TOPIC_FILE, Draft, load_config, post_folders,
                    post_kind, read_draft, resolve_folder, upload_image)

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
    "quote_button": "button.se-insert-quotation-default-toolbar-button, button[data-name='quotation']",
    "quote_component": ".se-component.se-quotation",
    "table_component": ".se-component.se-table",
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
    cls = last.get_attribute("class") or ""
    if "se-image" in cls:
        last.click()
        page.keyboard.press("Enter")
    elif "se-table" in cls:  # 표 바로 아래 빈 줄로
        last.click(position={"x": 5, "y": max(1, (last.bounding_box() or {"height": 2})["height"] - 2)})
        page.keyboard.press("Control+End")
    elif "se-quotation" in cls:
        last.locator(".se-text-paragraph").last.click()
        page.keyboard.press("End")
        page.keyboard.press("ArrowDown")
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


def insert_quote(page: Page, ed: FrameLocator, text: str) -> None:
    btn = ed.locator(SEL["quote_button"]).first
    if not btn.count():  # 인용구 버튼을 못 찾으면 굵은 글씨로 대신
        insert_heading(page, text)
        return
    before = ed.locator(SEL["quote_component"]).count()
    btn.click()
    ed.locator(SEL["quote_component"]).nth(before).wait_for(timeout=5000)
    ed.locator(SEL["quote_component"]).nth(before).locator(".se-text-paragraph").first.click()
    page.keyboard.insert_text(text)
    pause()
    move_caret_below_last(page, ed)


def table_rows(text: str) -> list[list[str]]:
    return [[c.strip() for c in l.strip().strip("|").split("|")] for l in text.splitlines() if l.strip().startswith("|")]


def table_html(rows: list[list[str]]) -> str:
    """같은 값이 옆으로 이어지면 칸을 합친다 (전장 5,060 처럼 모든 모델이 같은 값)."""
    out = []
    for r, row in enumerate(rows):
        cells, i = [], 0
        while i < len(row):
            j = i
            while r > 0 and i > 0 and j + 1 < len(row) and row[j + 1] == row[i]:
                j += 1
            tag = "th" if r == 0 or i == 0 else "td"
            span = f' colspan="{j - i + 1}"' if j > i else ""
            cells.append(f"<{tag}{span}>{html.escape(row[i])}</{tag}>")
            i = j + 1
        out.append("<tr>" + "".join(cells) + "</tr>")
    return "<table><tbody>" + "".join(out) + "</tbody></table><p><br></p>"


TABLE_CSS = """*{box-sizing:border-box;margin:0}body{width:1080px;background:#fff;padding:28px 30px;
font-family:'Noto Sans KR','Malgun Gothic',sans-serif;color:#14213d}
table{border-collapse:collapse;width:100%;table-layout:fixed}th,td{border:1px solid #cfd6e0;padding:13px 6px;text-align:center;font-size:23px}
th{background:#e6eefb;color:#16418f;font-weight:700}tr th:first-child{background:#f3f5f8;color:#14213d;width:230px;font-size:21px}"""


def table_image(folder: Path, rows: list[list[str]], n: int) -> Path:
    """표를 그림으로 (네이버 표로 못 넣을 때 대신)"""
    import card
    out = folder / CARD_DIR / f"table_{n}.png"
    out.parent.mkdir(exist_ok=True)
    page_html = (f'<!doctype html><html lang="ko"><head><meta charset="utf-8">'
                 f'<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;700&display=swap" rel="stylesheet">'
                 f'<style>{TABLE_CSS}</style></head><body>{table_html(rows)}</body></html>')
    card._shot([(page_html, out, 200)])
    return out


def _paste(page: Page, html_text: str, plain: str) -> None:
    """진짜 클립보드에 표를 넣고 Ctrl+V (사람이 엑셀 표를 붙여넣는 것과 같은 방식)"""
    try:
        page.context.grant_permissions(["clipboard-read", "clipboard-write"], origin="https://blog.naver.com")
    except PWError:
        pass
    frame = page.frame(name="mainFrame") or page.main_frame
    frame.evaluate("""async ([h, t]) => {
        await navigator.clipboard.write([new ClipboardItem({
            'text/html': new Blob([h], {type: 'text/html'}), 'text/plain': new Blob([t], {type: 'text/plain'})})]);
    }""", [html_text, plain])
    page.keyboard.press("Control+V")


def insert_table(page: Page, ed: FrameLocator, text: str, folder: Path, n: int = 1) -> None:
    """네이버 표로 넣는다 (클립보드 붙여넣기). 표가 안 생기면 같은 표를 그림으로 만들어 넣는다."""
    rows = table_rows(text)
    if not rows:
        return
    before = ed.locator(SEL["table_component"]).count()
    wrap = ed.locator(".se-components-wrap").first
    text_before = len(wrap.inner_text())
    try:
        _paste(page, table_html(rows), "\n".join("\t".join(r) for r in rows))
        deadline = time.time() + 6
        while ed.locator(SEL["table_component"]).count() <= before and time.time() < deadline:
            time.sleep(0.3)
    except PWError as e:
        print(f"  [주의] 표 붙여넣기 실패: {e}")
    if ed.locator(SEL["table_component"]).count() > before:
        pause(0.8, 1.2)
        move_caret_below_last(page, ed)
        return
    # 표가 안 생겼다: 붙여넣기로 글자만 들어갔으면 되돌리고 그림으로
    if len(wrap.inner_text()) > text_before:
        page.keyboard.press("Control+Z")
        pause()
    print("  [안내] 네이버 표가 안 만들어져서 표를 그림으로 넣었습니다.")
    insert_image(page, ed, table_image(folder, rows, n))


def insert_heading(page: Page, text: str) -> None:
    page.keyboard.press("Control+B")
    page.keyboard.insert_text(text)
    page.keyboard.press("Control+B")


def fill_editor(page: Page, ed: FrameLocator, cfg: dict, folder: Path, draft: Draft) -> None:
    ed.locator(SEL["title"]).first.click()
    page.keyboard.insert_text(draft.title)
    pause()

    ed.locator(SEL["body_text"]).last.click()
    for i, block in enumerate(draft.blocks):
        if block.kind == "image":
            path = upload_image(cfg, folder, block.text)
            if path is None:
                raise RuntimeError(f"올릴 사진이 없습니다: {block.text} "
                                   "(번호판 가린 사진이 없으면 write.bat 을 다시 실행하세요)")
            insert_image(page, ed, path)
            continue
        if block.kind == "quote":
            insert_quote(page, ed, block.text)
            continue
        if block.kind == "table":
            insert_table(page, ed, block.text, folder, i)
            continue
        if block.kind == "heading":
            insert_heading(page, block.text)
        else:
            type_lines(page, block.text)
        next_is_box = i + 1 < len(draft.blocks) and draft.blocks[i + 1].kind in ("image", "quote", "table")
        if not next_is_box:
            page.keyboard.press("Enter")
            page.keyboard.press("Enter")
        pause()
    # 글 맨 끝에 태그 한 줄 (#태그1 #태그2 ...). 임시저장할 때도 태그가 글에 남는다.
    if draft.tags and cfg.get("body_tags", True):
        type_lines(page, " ".join(f"#{t}" for t in with_fixed_tags(cfg, draft.tags)[:10]))


def open_publish_layer(ed: FrameLocator, category: str, tags: list[str]) -> None:
    ed.locator(SEL["publish_open"]).first.click()
    layer = ed.locator(SEL["publish_layer"]).first
    layer.wait_for(timeout=10000)
    pause()

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
    kind = post_kind(folder) if (folder / TOPIC_FILE).exists() else ""
    cats = cfg.get("categories") or {}
    category = (cats.get(kind) or (cats.get("차량정보") if kind == "총정리" else "") or cfg.get("category") or "").strip()
    if kind == "총정리":  # 총정리 글은 처음 몇 편만 임시저장하고 그 뒤로는 바로 발행 (guide.publish_now)
        import guide
        cfg = {**cfg, "publish": guide.publish_now(cfg)}
    elif kind == "출고후기":  # 출고후기는 최현정 대리가 확인하고 직접 발행하도록 언제나 임시저장
        cfg = {**cfg, "publish": False}
    print(f"[입력 중] {folder.name}: {draft.title}")

    try:
        page.goto(f"https://blog.naver.com/{cfg['blog_id']}?Redirect=Write&")
    except PWError:  # 로그인이 풀려 있으면 로그인 화면으로 넘어가며 이동이 끊긴다
        pass
    page.wait_for_load_state("domcontentloaded")
    if "nid.naver.com" in page.url:
        raise RuntimeError("네이버 로그인이 풀렸습니다. 다시 로그인해 주세요.")

    ed = page.frame_locator(SEL["editor_frame"])
    ed.locator(SEL["title"]).first.wait_for(timeout=30000)
    pause(1.5, 2.5)
    close_popups(ed)

    fill_editor(page, ed, cfg, folder, draft)

    if test:
        open_publish_layer(ed, category, with_fixed_tags(cfg, draft.tags))
        input("[테스트] 발행 직전까지 입력했습니다. 브라우저에서 확인 후 Enter 를 누르면 창을 닫습니다 (발행 안 함)...")
        return

    if cfg.get("publish", True):
        open_publish_layer(ed, category, with_fixed_tags(cfg, draft.tags))
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
    if kind == "총정리":
        guide.record(folder, result)


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

    run_posts(cfg, folders, test)


def run_posts(cfg: dict, folders: list[Path], test: bool = False) -> int:
    """글 폴더들을 차례로 올리고, 성공한 개수를 돌려준다."""
    done = 0
    with sync_playwright() as pw:
        ctx = open_browser(pw, cfg, headless=False if test else None)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        for i, folder in enumerate(folders):
            try:
                post_one(page, cfg, folder, test)
                done += 1
            except Exception as e:  # 한 글이 실패해도 다음 글은 계속
                shot = ROOT / "logs" / f"error_{datetime.now():%Y%m%d_%H%M%S}.png"
                shot.parent.mkdir(exist_ok=True)
                page.screenshot(path=str(shot), full_page=True)
                print(f"[실패] {folder.name}: {e}\n  화면 캡처: {shot}")
            if i < len(folders) - 1:
                pause(5, 10)
        ctx.close()
    return done


if __name__ == "__main__":
    main()
