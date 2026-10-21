"""처음 한 번 실행: 열린 브라우저에서 직접 네이버에 로그인하면 로그인 상태가 저장된다."""
from playwright.sync_api import sync_playwright

from browser import open_browser
from common import load_config


def main() -> None:
    cfg = load_config()
    with sync_playwright() as pw:
        ctx = open_browser(pw, cfg, headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://nid.naver.com/nidlogin.login")
        print("브라우저에서 네이버에 로그인하세요. ('로그인 상태 유지'를 체크하면 오래 유지됩니다)")
        input("로그인을 마쳤으면 이 창에서 Enter 를 누르세요...")
        page.goto("https://blog.naver.com/MyBlog.naver")
        page.wait_for_load_state("domcontentloaded")
        if "nid.naver.com" in page.url:
            print("[실패] 아직 로그인되지 않았습니다. 다시 실행해 주세요.")
        else:
            print("[완료] 로그인 정보가 저장됐습니다.")
        ctx.close()


if __name__ == "__main__":
    main()
