"""잘 되는 네이버 블로그 글 주소를 주면, 구조(소제목/사진 위치/문단)를 살려 references/ 에 저장한다.

사용법:
  python fetch_reference.py https://blog.naver.com/아이디/글번호
"""
import re
import sys

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


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit("사용법: python fetch_reference.py <네이버 블로그 글 주소>")
    url = sys.argv[1].strip().replace("://blog.naver.com", "://m.blog.naver.com")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(locale="ko-KR")
        page.goto(url)
        page.wait_for_selector(".se-main-container", timeout=20000)
        data = page.evaluate(EXTRACT_JS)
        browser.close()

    if not data["body"]:
        sys.exit("본문을 찾지 못했습니다. 스마트에디터 ONE 으로 쓴 글인지 확인하세요.")
    text = f"# {data['title']}\n\n{data['body']}\n"
    if data["tags"]:
        text += f"\n태그: {' '.join(data['tags'])}\n"

    REFERENCES_DIR.mkdir(exist_ok=True)
    name = re.sub(r'[\\/:*?"<>|]', "", data["title"])[:50].strip() or "reference"
    path = REFERENCES_DIR / f"{name}.txt"
    path.write_text(text, encoding="utf-8")
    print(f"[저장] {path}")


if __name__ == "__main__":
    main()
