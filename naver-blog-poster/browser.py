"""로그인 정보가 저장되는 브라우저 실행."""
from playwright.sync_api import BrowserContext, Playwright

from common import PROFILE_DIR


def open_browser(pw: Playwright, cfg: dict, headless: bool | None = None) -> BrowserContext:
    opts = dict(
        user_data_dir=str(PROFILE_DIR),
        headless=cfg.get("headless", False) if headless is None else headless,
        viewport={"width": 1400, "height": 900},
        locale="ko-KR",
        args=["--disable-blink-features=AutomationControlled"],
    )
    if cfg.get("use_chrome", True):
        try:
            return pw.chromium.launch_persistent_context(channel="chrome", **opts)
        except Exception:
            print("[알림] 크롬을 찾지 못해 내장 브라우저로 실행합니다.")
    return pw.chromium.launch_persistent_context(**opts)
