"""config.yaml 에서 고른 AI 회사의 키로 쓸 수 있는 모델 이름을 보여준다."""
from dotenv import load_dotenv

import ai_providers
from common import ROOT, load_config

load_dotenv(ROOT / ".env")
cfg = load_config()
name = ai_providers.provider(cfg)
print(f"[{name}] 지금 설정된 모델: {ai_providers.model(cfg)}\n쓸 수 있는 모델:")
try:
    for m in ai_providers.list_models(cfg):
        print("  " + m)
except Exception as e:
    print(f"목록을 가져오지 못했습니다. .env 의 {ai_providers.KEY_NAMES[name]} 를 확인하세요.\n  ({e})")
