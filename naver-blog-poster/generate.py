"""AI가 메모(topic.txt) + 사진 + 레퍼런스 글을 보고 draft.md 를 쓴다.

사용법:
  python generate.py             # 아직 draft.md 가 없는 모든 글 폴더
  python generate.py 글폴더이름    # 특정 폴더만 (기존 draft.md 덮어씀)
"""
import base64
import io
import sys
from pathlib import Path
from typing import Literal

import anthropic
from dotenv import load_dotenv
from PIL import Image
from pydantic import BaseModel

from common import (DRAFT_FILE, REFERENCE_FILE, REFERENCES_DIR, ROOT, TOPIC_FILE,
                    Block, Draft, list_images, load_config, post_folders,
                    resolve_folder, write_draft)

MAX_SIDE = 1568  # API로 보낼 때만 줄임. 블로그에는 원본이 올라감.
MAX_REFERENCES = 5


class AIBlock(BaseModel):
    kind: Literal["heading", "quote", "paragraph", "image"]
    text: str  # image 이면 사진 파일 이름


class AIDraft(BaseModel):
    title: str
    tags: list[str]
    blocks: list[AIBlock]


SYSTEM = """당신은 네이버 블로그 글을 쓰는 작가입니다.
사용자가 준 메모와 사진으로 블로그 글 한 편을 씁니다.

<reference> 안의 글은 반응이 좋았던 글입니다. 이 글들의 구조를 최대한 그대로 따라 쓰세요.
- 제목 형식(길이, 키워드 위치, 괄호/기호 사용)
- 도입부 방식, 소제목 개수와 순서, 각 소제목 아래 분량
- 사진이 들어가는 위치와 사진 사이 글의 길이 리듬
- 문단 길이, 줄바꿈 습관, 이모지/기호 사용, 말투와 어미
- 마무리 형식과 태그 개수
단, 레퍼런스의 문장을 그대로 옮기지 마세요. 네이버는 비슷한 문장이 많은 글을 유사문서로 판단해 노출을 낮춥니다.
구조와 말투만 가져오고, 내용과 문장은 메모와 사진으로 새로 쓰세요.

이 블로그의 목표는 네이버 검색 상위노출입니다. 메모에 "키워드:" 가 있으면:
- 제목 맨 앞쪽에 대표 키워드를 그대로 넣습니다. (레퍼런스 제목 형식 안에서)
- 첫 문단과 본문 중간, 마무리에 키워드를 자연스럽게 2~4번 씁니다. 억지로 반복하지 마세요. 과하면 오히려 어뷰징으로 판단됩니다.
- 태그에 대표 키워드와 연관 키워드(지역, 차종, 상황 등)를 넣습니다.
- 검색한 사람이 궁금해할 정보(사양, 가격, 차이점, 실제 경험)를 메모 범위 안에서 충실히 담습니다.

규칙:
- blocks 는 글 순서대로 나열합니다. kind 는 heading(굵은 소제목), quote(인용구 상자), paragraph(문단), image(사진) 중 하나입니다.
- 레퍼런스에서 "[인용] ..." 으로 표시된 곳은 인용구 상자입니다. 같은 자리에 quote 블록을 쓰세요. "## ..." 은 heading 입니다.
- 레퍼런스의 [스티커], [동영상], [지도], [링크] 는 넣을 수 없으니 건너뜁니다.
- 레퍼런스에 나온 가격, 사양, 이름 같은 사실은 다른 글의 정보이므로 절대 가져오지 마세요. 사실 정보는 메모에 있는 것만 씁니다.
- image 블록의 text 에는 주어진 사진 파일 이름을 정확히 그대로 씁니다. 모든 사진을 한 번씩만 사용하세요.
- 사진 내용과 어울리는 위치에 사진을 배치하세요.
- paragraph 안의 줄바꿈은 레퍼런스의 줄바꿈 습관을 따릅니다.
- tags 에는 # 없이 단어만 넣습니다."""


def encode_image(path: Path) -> tuple[str, str]:
    img = Image.open(path)
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return "image/jpeg", base64.standard_b64encode(buf.getvalue()).decode()


def reference_kind(folder: Path) -> str:
    """topic.txt 첫 줄이 '종류: 출고후기' 이면 references/출고후기/ 를 쓴다."""
    first = (folder / TOPIC_FILE).read_text(encoding="utf-8-sig").splitlines()[:1]
    if first and first[0].replace("：", ":").startswith("종류:"):
        return first[0].split(":", 1)[1].strip()
    return ""


def load_references(folder: Path) -> list[str]:
    own = folder / REFERENCE_FILE
    if own.exists():
        return [own.read_text(encoding="utf-8-sig")]
    kind = reference_kind(folder)
    base = REFERENCES_DIR / kind if kind else REFERENCES_DIR
    if kind and not base.is_dir():
        print(f"[주의] references/{kind} 폴더가 없어 references 의 글을 씁니다.")
        base = REFERENCES_DIR
    files = sorted(p for p in base.glob("*.txt") if p.name != "README.txt")
    if not files and not kind:  # 종류 없이 하위 폴더에만 있을 때
        files = sorted(p for p in base.rglob("*.txt") if p.name != "README.txt")
    return [p.read_text(encoding="utf-8-sig") for p in files[:MAX_REFERENCES]]


def build_content(folder: Path, images: list[Path], references: list[str], style: str) -> list[dict]:
    content: list[dict] = []
    for i, ref in enumerate(references, 1):
        content.append({"type": "text", "text": f'<reference index="{i}">\n{ref}\n</reference>'})
    for img in images:
        media_type, data = encode_image(img)
        content.append({"type": "text", "text": f"사진 파일 이름: {img.name}"})
        content.append({"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}})
    memo = (folder / TOPIC_FILE).read_text(encoding="utf-8-sig")
    content.append({"type": "text", "text": f"<style>\n{style}\n</style>\n\n<memo>\n{memo}\n</memo>\n\n"
                                            "위 메모와 사진으로 레퍼런스와 같은 구조의 블로그 글을 써주세요."})
    return content


def generate(client: anthropic.Anthropic, cfg: dict, folder: Path) -> None:
    if not (folder / TOPIC_FILE).exists():
        print(f"[건너뜀] {folder.name}: {TOPIC_FILE} 이 없습니다.")
        return
    images = list_images(folder)
    references = load_references(folder)
    if not references:
        print("[주의] 레퍼런스 글이 없습니다. references 폴더에 .txt 를 넣으면 그 구조를 따라 씁니다.")
    print(f"[작성 중] {folder.name} (사진 {len(images)}장, 레퍼런스 {len(references)}개)")

    response = client.beta.messages.parse(
        model=cfg.get("model", "claude-opus-5-5"),
        max_tokens=16000,
        output_config={"effort": cfg.get("effort", "medium")},
        # 안전 필터에 걸리면 다른 모델로 자동 재시도
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        system=SYSTEM,
        messages=[{"role": "user", "content": build_content(folder, images, references, cfg.get("style", ""))}],
        output_format=AIDraft,
    )
    if response.stop_reason == "refusal":
        print(f"[실패] {folder.name}: AI가 이 글 작성을 거절했습니다. 메모 내용을 확인해 주세요.")
        return
    ai = response.parsed_output
    if ai is None:
        print(f"[실패] {folder.name}: 응답을 읽지 못했습니다 (stop_reason={response.stop_reason}).")
        return

    # 없는 사진 이름은 빼고, 빠진 사진은 끝에 붙인다
    names = {p.name for p in images}
    blocks = [Block(b.kind, b.text.strip()) for b in ai.blocks
              if b.kind != "image" or b.text.strip() in names]
    used = {b.text for b in blocks if b.kind == "image"}
    blocks += [Block("image", n) for n in sorted(names - used)]

    write_draft(folder / DRAFT_FILE, Draft(ai.title.strip(), [t.strip().lstrip("#") for t in ai.tags], blocks))
    print(f"[완료] {folder / DRAFT_FILE}  ← 열어서 확인/수정하세요.")


def main() -> None:
    load_dotenv(ROOT / ".env")
    cfg = load_config()
    client = anthropic.Anthropic()
    if len(sys.argv) > 1:
        folders = [resolve_folder(sys.argv[1])]
    else:
        folders = [f for f in post_folders() if not (f / DRAFT_FILE).exists()]
        if not folders:
            print("새로 쓸 글이 없습니다. posts 폴더에 글 폴더(topic.txt + 사진)를 만들어 주세요.")
    for folder in folders:
        try:
            generate(client, cfg, folder)
        except anthropic.AuthenticationError:
            sys.exit("API 키가 잘못됐습니다. .env 파일의 ANTHROPIC_API_KEY 를 확인하세요.")
        except anthropic.APIError as e:
            print(f"[실패] {folder.name}: {e}")


if __name__ == "__main__":
    main()
