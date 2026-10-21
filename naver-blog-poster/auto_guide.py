"""작업 스케줄러가 매일 실행: 오늘 아직 안 썼으면 다음 차종 총정리 글 한 편을 쓰고 올린다.

  python auto_guide.py          # 바로 실행
  python auto_guide.py --wait   # 0~60분 쉬었다가 실행 (스케줄러용)
"""
import sys
from datetime import datetime

from dotenv import load_dotenv

from common import ROOT, load_config

(ROOT / "logs").mkdir(exist_ok=True)
log = open(ROOT / "logs" / "총정리.log", "a", encoding="utf-8", buffering=1)
sys.stdout = sys.stderr = log  # 창 없이(pythonw) 돌기 때문에 기록은 파일로

import guide  # noqa: E402

if __name__ == "__main__":
    print(f"===== {datetime.now():%Y-%m-%d %H:%M} =====")
    load_dotenv(ROOT / ".env", override=True)
    try:
        guide.run_daily(load_config(), wait="--wait" in sys.argv)
    except Exception as e:
        print(f"[오류] {e}")
