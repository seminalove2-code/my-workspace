"""Claude / OpenAI / Gemini 중 config.yaml 의 ai 설정으로 고른 AI에게 글을 쓰게 한다.

content 는 [("text", 문자열) | ("image", JPEG 바이트), ...] 순서 목록이다.
"""
import base64
from typing import Literal

from pydantic import BaseModel

KEY_NAMES = {"claude": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY", "gemini": "GEMINI_API_KEY"}
DEFAULT_MODELS = {"claude": "claude-opus-5-5", "openai": "gpt-5.5", "gemini": "gemini-3.5-flash"}


class AIBlock(BaseModel):
    kind: Literal["heading", "quote", "paragraph", "image"]
    text: str  # image 이면 사진 파일 이름


class SpecCard(BaseModel):
    # 스펙 카드에 들어갈 값. 모르는 값은 빈 문자열 "" (카드에서 그 칸을 뺀다)
    series: str      # 예: THE 5
    model: str       # 예: 520i M Sport
    year: str        # 예: 26년식
    colors: str      # 예: 브루클린 그레이 / 블랙
    price: str       # 만원 단위 숫자만, 예: 7,610
    power: str       # 마력 숫자만, 예: 190
    torque: str      # kg.m 숫자만, 예: 31.6
    zero100: str     # 초 숫자만, 예: 8.1
    engine: str      # 짧게, 예: 4기통 가솔린 MHEV
    drive: str       # 예: 후륜 · 자동 8단
    top_speed: str   # km/h 숫자만, 예: 230
    size: str        # 예: 5,060 × 1,900 × 1,515 mm · 휠베이스 2,995 mm
    options: list[str]  # 체감되는 옵션 6~8개, 각 12자 안팎


class AIDraft(BaseModel):
    title: str
    tags: list[str]
    blocks: list[AIBlock]
    card: SpecCard


class PlateBox(BaseModel):
    # 사진 크기를 0~1000으로 본 좌표 (왼쪽 위가 0,0)
    x1: int
    y1: int
    x2: int
    y2: int


class Plates(BaseModel):
    plates: list[PlateBox]


class AIError(Exception):
    pass


def provider(cfg: dict) -> str:
    name = str(cfg.get("ai", "claude")).strip().lower()
    if name not in KEY_NAMES:
        raise AIError(f"config.yaml 의 ai 는 claude / openai / gemini 중 하나여야 합니다. (지금: {name})")
    return name


def model(cfg: dict) -> str:
    name = provider(cfg)
    return (cfg.get("models") or {}).get(name) or DEFAULT_MODELS[name]


def write(cfg: dict, system: str, content: list[tuple[str, object]]) -> AIDraft:
    return ask(cfg, system, content, AIDraft)


def ask(cfg: dict, system: str, content: list[tuple[str, object]], schema: type[BaseModel],
        max_tokens: int = 16000):
    name = provider(cfg)
    try:
        return {"claude": _claude, "openai": _openai, "gemini": _gemini}[name](cfg, system, content, schema, max_tokens)
    except AIError:
        raise
    except Exception as e:  # 회사마다 오류 종류가 달라 메시지로 안내
        text = str(e)
        if any(w in text.lower() for w in ("api key", "api_key", "401", "unauthorized", "authentication", "permission")):
            raise AIError(f"API 키를 확인하세요: .env 파일의 {KEY_NAMES[name]} ({text[:200]})") from e
        if "model" in text.lower() and any(w in text.lower() for w in ("not found", "404", "does not exist")):
            raise AIError(f"모델 이름 '{model(cfg)}' 을 쓸 수 없습니다. models.bat 으로 쓸 수 있는 모델을 확인하세요.") from e
        raise AIError(text[:500]) from e


def _b64(data: bytes) -> str:
    return base64.standard_b64encode(data).decode()


def _claude(cfg: dict, system: str, content: list, schema, max_tokens: int):
    import anthropic

    parts = [{"type": "text", "text": v} if k == "text" else
             {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": _b64(v)}}
             for k, v in content]
    response = anthropic.Anthropic().beta.messages.parse(
        model=model(cfg),
        max_tokens=max_tokens,
        output_config={"effort": cfg.get("effort", "medium")},
        # 안전 필터에 걸리면 다른 모델로 자동 재시도
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        system=system,
        messages=[{"role": "user", "content": parts}],
        output_format=schema,
    )
    if response.stop_reason == "refusal":
        raise AIError("AI가 이 글 작성을 거절했습니다. 메모 내용을 확인해 주세요.")
    if response.parsed_output is None:
        raise AIError(f"응답을 읽지 못했습니다 (stop_reason={response.stop_reason}).")
    return response.parsed_output


def _openai(cfg: dict, system: str, content: list, schema, max_tokens: int):
    from openai import OpenAI

    parts = [{"type": "input_text", "text": v} if k == "text" else
             {"type": "input_image", "image_url": f"data:image/jpeg;base64,{_b64(v)}", "detail": "high"}
             for k, v in content]
    extra = {}
    if cfg.get("openai_reasoning"):  # 추론 모델일 때만 (예: medium)
        extra["reasoning"] = {"effort": cfg["openai_reasoning"]}
    response = OpenAI().responses.parse(
        model=model(cfg),
        instructions=system,
        input=[{"role": "user", "content": parts}],
        text_format=schema,
        max_output_tokens=max_tokens,
        **extra,
    )
    if response.output_parsed is None:
        raise AIError("응답을 읽지 못했습니다. (AI가 거절했거나 답이 잘렸을 수 있습니다)")
    return response.output_parsed


def _gemini(cfg: dict, system: str, content: list, schema, max_tokens: int):
    from google import genai
    from google.genai import types

    parts = [types.Part.from_text(text=v) if k == "text" else
             types.Part.from_bytes(data=v, mime_type="image/jpeg")
             for k, v in content]
    client = genai.Client()  # 변수에 담아야 요청 중에 닫히지 않는다
    response = client.models.generate_content(
        model=model(cfg),
        contents=[types.Content(role="user", parts=parts)],
        config=types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_schema=schema,
            max_output_tokens=max_tokens,
        ),
    )
    parsed = response.parsed
    if isinstance(parsed, schema):
        return parsed
    if response.text:
        return schema.model_validate_json(response.text)
    raise AIError("응답을 읽지 못했습니다. (AI가 거절했거나 답이 잘렸을 수 있습니다)")


def list_models(cfg: dict) -> list[str]:
    """지금 키로 쓸 수 있는 모델 이름 목록."""
    name = provider(cfg)
    if name == "claude":
        import anthropic
        return [m.id for m in anthropic.Anthropic().models.list()]
    if name == "openai":
        from openai import OpenAI
        return sorted(m.id for m in OpenAI().models.list() if m.id.startswith(("gpt", "o")))
    from google import genai
    client = genai.Client()
    return [m.name.removeprefix("models/") for m in client.models.list()
            if "generateContent" in (m.supported_actions or [])]
