"""처음 한 번 실행: 열린 브라우저에서 직접 네이버에 로그인하면 로그인 상태가 저장된다."""
import time

from playwright.sync_api import sync_playwright

from browser import open_browser
from common import load_config

WAIT_SECONDS = 600  # 추가 인증(문자, 새 기기 확인)까지 넉넉히 기다린다


def logged_in(ctx) -> bool:
    names = {c["name"] for c in ctx.cookies("https://naver.com")}
    return {"NID_AUT", "NID_SES"} <= names


def main() -> None:
    cfg = load_config()
    with sync_playwright() as pw:
        ctx = open_browser(pw, cfg, headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        if logged_in(ctx):
            print("[완료] 이미 로그인되어 있습니다.")
            ctx.close()
            return
        page.goto("https://nid.naver.com/nidlogin.login")
        print("브라우저에서 네이버에 로그인하세요. ('로그인 상태 유지'를 체크하면 오래 유지됩니다)")
        print("추가 인증 화면이 나오면 끝까지 진행하세요. 로그인이 끝나면 자동으로 알아챕니다.")
        deadline = time.time() + WAIT_SECONDS
        while time.time() < deadline:
            if logged_in(ctx):
                time.sleep(3)  # 로그인 직후 쿠키가 다 저장될 때까지 잠깐 기다림
                print("[완료] 로그인 정보가 저장됐습니다. 이 창을 닫아도 됩니다.")
                break
            time.sleep(2)
        else:
            print("[실패] 10분 안에 로그인이 끝나지 않았습니다. login.bat 을 다시 실행해 주세요.")
        ctx.close()


if __name__ == "__main__":
    main()
