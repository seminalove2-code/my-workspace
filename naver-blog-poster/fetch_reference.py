"""잘 되는 네이버 블로그 글을 구조(소제목/인용구/사진 위치/문단)를 살려 references/ 에 저장한다.

사용법:
  python fetch_reference.py <글 주소>                  # 글 하나
  python fetch_reference.py <블로그 주소> [종류] [개수]  # 그 블로그의 최근 글 여러 개 (기본 5개)
  python fetch_reference.py --list data/recommended_refs.txt  # 목록의 글을 종류별로 모두 (예전 것은 지움)
  예) python fetch_reference.py https://blog.naver.com/hth1890 출고후기 5
     → references/출고후기/ 에 저장
"""
import json
import re
import sys
import urllib.request

from playwright.sync_api import sync_playwright

from common import REFERENCES_DIR

# 모바일 페이지에는 iframe 이 없어 본문을 바로 읽을 수 있다.
EXTRACT_JS = """
() => {
  const title = (document.querySelector('.se-title-text')?.innerText || '').replace(/\\s+/g, ' ').trim();
  const out = [];
  for (const c of document.querySelectorAll('.se-main-container > .se-component')) {
    const cls = c.className;
    if (cls.includes('se-documentTitle')) continue;  // 제목/작성자 영역
    if (cls.includes('se-image') || cls.includes('se-imageStrip') || cls.includes('se-imageGroup')) {
      const n = Math.max(1, c.querySelectorAll('img').length);
      for (let i = 0; i < n; i++) out.push('[사진]');
    } else if (cls.includes('se-sticker')) out.push('[스티커]');
    else if (cls.includes('se-video') || cls.includes('se-oembed')) out.push('[동영상]');
    else if (cls.includes('se-placesMap') || cls.includes('se-map')) out.push('[지도]');
    else if (cls.includes('se-oglink')) out.push('[링크]');
    else if (cls.includes('se-horizontalLine')) out.push('---');
    else if (cls.includes('se-quotation')) out.push('[인용] ' + c.innerText.trim());
    else if (cls.includes('se-sectionTitle')) out.push('## ' + c.innerText.trim());
    else {
      const t = c.innerText.replace(/\\u200b/g, '').replace(/\\n{3,}/g, '\\n\\n').trim();
      if (t) out.push(t);
    }
  }
  const tags = [...document.querySelectorAll('.post_tag a, .tag_area a, a[class*="tag"]')]
      .map(a => a.innerText.trim()).filter(t => t.startsWith('#'));
  return {title, body: out.join('\\n\\n'), tags: [...new Set(tags)]};
}
"""


MIN_BODY = 800  # 이보다 짧은 글(사진만 있는 글 등)은 레퍼런스로 쓰지 않음


def parse_url(url: str) -> tuple[str, str]:
    m = re.search(r"blog\.naver\.com/(?:PostView\.naver\?blogId=)?([A-Za-z0-9_-]+)(?:/|&logNo=)?(\d+)?", url)
    if not m:
        sys.exit(f"네이버 블로그 주소가 아닙니다: {url}")
    return m.group(1), m.group(2) or ""


def recent_posts(blog_id: str, count: int) -> list[str]:
    api = f"https://m.blog.naver.com/api/blogs/{blog_id}/post-list?categoryNo=0&itemCount={count}&page=1"
    req = urllib.request.Request(api, headers={"Referer": f"https://m.blog.naver.com/{blog_id}",
                                               "User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        items = json.load(r)["result"]["items"]
    return [str(i["logNo"]) for i in items]


def save(data: dict, out_dir) -> None:
    text = f"# {data['title']}\n\n{data['body']}\n"
    if data["tags"]:
        text += f"\n태그: {' '.join(data['tags'])}\n"
    out_dir.mkdir(parents=True, exist_ok=True)
    name = re.sub(r'[\\/:*?"<>|]', "", data["title"])[:50].strip() or "reference"
    path = out_dir / f"{name}.txt"
    path.write_text(text, encoding="utf-8")
    print(f"[저장] {path.relative_to(REFERENCES_DIR.parent)}")


def fetch_list(list_file: str) -> None:
    jobs = []
    for line in open(list_file, encoding="utf-8-sig"):
        parts = line.split()
        if len(parts) == 2 and not line.startswith("#"):
            jobs.append((parts[0], parse_url(parts[1])))
    for kind in {k for k, _ in jobs}:  # 종류별 예전 레퍼런스 비우기
        for old in (REFERENCES_DIR / kind).glob("*.txt"):
            old.unlink()
    saved = 0
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(locale="ko-KR")
        for i, (kind, (blog_id, log_no)) in enumerate(jobs, 1):
            print(f"({i}/{len(jobs)}) {kind}: ", end="", flush=True)
            try:
                page.goto(f"https://m.blog.naver.com/{blog_id}/{log_no}")
                page.wait_for_selector(".se-main-container", timeout=20000)
                save(page.evaluate(EXTRACT_JS), REFERENCES_DIR / kind)
                saved += 1
            except Exception as e:
                print(f"[건너뜀] {blog_id}/{log_no}: {str(e)[:80]}")
        browser.close()
    print(f"\n완료: {len(jobs)}개 중 {saved}개 저장")


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    if sys.argv[1] == "--list":
        fetch_list(sys.argv[2])
        return
    blog_id, log_no = parse_url(sys.argv[1].strip())
    kind = sys.argv[2].strip() if len(sys.argv) > 2 else ""
    count = int(sys.argv[3]) if len(sys.argv) > 3 else 5
    out_dir = REFERENCES_DIR / kind if kind else REFERENCES_DIR

    # 블로그 주소만 주면 짧은 글을 건너뛰기 위해 넉넉히 가져온다
    log_nos = [log_no] if log_no else recent_posts(blog_id, count * 3)
    saved = 0
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(locale="ko-KR")
        for no in log_nos:
            if saved >= count:
                break
            page.goto(f"https://m.blog.naver.com/{blog_id}/{no}")
            try:
                page.wait_for_selector(".se-main-container", timeout=20000)
            except Exception:
                print(f"[건너뜀] {no}: 스마트에디터 ONE 글이 아닙니다.")
                continue
            data = page.evaluate(EXTRACT_JS)
            if not log_no and len(data["body"]) < MIN_BODY:
                print(f"[건너뜀] 글이 짧음: {data['title']}")
                continue
            save(data, out_dir)
            saved += 1
        browser.close()
    if not saved:
        print("저장한 글이 없습니다.")


if __name__ == "__main__":
    main()
