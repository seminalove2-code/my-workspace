"""AI가 메모(topic.txt) + 사진 + 레퍼런스 글을 보고 draft.md 를 쓴다.

사용법:
  python generate.py             # 아직 draft.md 가 없는 모든 글 폴더
  python generate.py 글폴더이름    # 특정 폴더만 (기존 draft.md 덮어씀)
"""
import io
import re
import sys
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from PIL import Image

import ai_providers

from common import (DRAFT_FILE, REFERENCE_FILE, REFERENCES_DIR, ROOT, TOPIC_FILE,
                    Block, Draft, list_images, load_config, post_folders, post_kind,
                    resolve_folder, write_draft)

MAX_SIDE = 1568  # API로 보낼 때만 줄임. 블로그에는 원본이 올라감.
MAX_REFERENCES = 5
DATA_DIR = ROOT / "data"
PRICE_FILE = DATA_DIR / "가격표.txt"
KEYWORD_FILE = DATA_DIR / "키워드.txt"
GUIDE_DIR = DATA_DIR / "글종류"


SYSTEM = """당신은 네이버 블로그 글을 쓰는 작가입니다.
<style> 의 페르소나로, 메모와 사진을 바탕으로 블로그 글 한 편을 씁니다.

<reference> 안의 글은 반응이 좋았던 글입니다. 이 글들의 구조를 따라 쓰세요.
- 도입부 방식, 소제목 개수와 순서, 각 소제목 아래 분량
- 사진이 들어가는 위치와 사진 사이 글의 길이 리듬
- 문단 길이, 줄바꿈 습관, 이모지/기호 사용, 말투와 어미
단, 레퍼런스의 문장을 그대로 옮기지 마세요. 네이버는 비슷한 문장이 많은 글을 유사문서로 판단해 노출을 낮춥니다.
레퍼런스에 나온 가격, 사양, 이름, 고객 이야기는 다른 글의 정보이므로 절대 가져오지 마세요.
<guide> 에 이 글 종류의 제목 형식과 구조가 있으면 레퍼런스보다 <guide> 를 우선합니다.

이 블로그의 목표는 네이버 검색 상위노출과 문자·전화 문의입니다.
- 메모에 "키워드:" 가 있으면 그것을, 없으면 <keywords> 표에서 메모의 차종에 맞는 대표 키워드를 고릅니다.
- 제목 맨 앞쪽에 대표 키워드를 그대로 넣고, "｜" 뒤에 보조 내용이나 보조 키워드를 붙입니다.
- 첫 문단, 본문 중간, 마무리에 대표 키워드를 자연스럽게 2~4번 씁니다. 과하게 반복하지 마세요.
- 태그는 대표 키워드, 차종, 트림, "용산BMW" 같은 연관어로 10개 안팎이며, 띄어쓰기 없이 씁니다. (예: BMWX3가격)
- 분량은 2,000~3,000자, 인용구 소제목 4~6개를 기준으로 합니다.

사실 정보 규칙 (가장 중요):
- 가격은 <prices> 의 [판매가격]에 있는 것만, 사양은 [트림별 주요 사양]에 있는 것만 씁니다. <prices> 에 없는 트림의 가격은 쓰지 않습니다.
- 가격은 "판매가격 7,670만원 (26년식, 2026년 10월 기준)"처럼 연식과 기준 월을 붙입니다.
- 한 트림에 가격이 여러 개면 메모의 연식과 맞는 것을 쓰고, 메모에 없으면 가장 최근 연식의 가장 마지막 생산분(P 숫자가 큰 것) 가격을 씁니다. "P1", "P2" 같은 생산 차수 표기는 글에 쓰지 않습니다.
- 차량 모델, 색상, 출고 시기는 메모에 있는 것만 씁니다. 사진만 보고 트림이나 색상 이름을 추측하지 않습니다.
- 고객님의 구매 이유, 감정, 대화, 상황은 메모의 "고객 이야기"에 있는 것만 씁니다. 없으면 차량 중심으로 씁니다.
- 할인 금액, 현금 할인, 딜러 프로모션 조건은 절대 쓰지 않습니다. 메모에 BMW코리아 공식 홈페이지 금융 프로그램이 있을 때만 "공식 홈페이지 ○월 기준"으로 씁니다.
- 프로모션은 이런 말투로 한 번만 안내합니다: "솔직히 이번 달 조건 정말 좋아요! 공식 딜러라 블로그에는 자세히 못 적는 점~ 이해 부탁드려요. 문자 주시면 바로 알려드릴게요"
- 외부 링크, 카카오톡, 오픈채팅은 쓰지 않습니다. 연락 방법은 문자와 전화뿐입니다.
- 글 마지막의 상담 안내(연락처)는 프로그램이 자동으로 붙이므로 쓰지 마세요. 마무리 인사까지만 씁니다.

형식 규칙:
- blocks 는 글 순서대로 나열합니다. kind 는 heading(굵은 소제목), quote(인용구 상자), paragraph(문단), image(사진) 중 하나입니다.
- 소제목은 quote(인용구 상자)로 씁니다. 레퍼런스에서 "[인용] ..." 으로 표시된 곳과 같은 역할입니다.
- 레퍼런스의 [스티커], [동영상], [지도], [링크] 는 넣을 수 없으니 건너뜁니다.
- image 블록의 text 에는 주어진 사진 파일 이름을 정확히 그대로 씁니다. 모든 사진을 한 번씩만 사용하고, 내용과 어울리는 위치에 둡니다.
- paragraph 안의 줄바꿈은 레퍼런스의 줄바꿈 습관을 따릅니다.
- tags 에는 # 없이 단어만 넣습니다."""


def encode_image(path: Path) -> bytes:
    img = Image.open(path)
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def load_references(folder: Path) -> list[str]:
    own = folder / REFERENCE_FILE
    if own.exists():
        return [own.read_text(encoding="utf-8-sig")]
    kind = post_kind(folder)
    base = REFERENCES_DIR / kind if kind else REFERENCES_DIR
    if kind and not base.is_dir():
        print(f"[주의] references/{kind} 폴더가 없어 references 의 글을 씁니다.")
        base = REFERENCES_DIR
    files = sorted(p for p in base.glob("*.txt") if p.name != "README.txt")
    if not files and not kind:  # 종류 없이 하위 폴더에만 있을 때
        files = sorted(p for p in base.rglob("*.txt") if p.name != "README.txt")
    return [p.read_text(encoding="utf-8-sig") for p in files[:MAX_REFERENCES]]


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig") if path.exists() else ""


def vehicle_line(memo: str) -> str:
    """메모의 '차량:' 줄. 없으면 메모 전체에서 차종을 찾는다."""
    for line in memo.splitlines():
        if line.replace("：", ":").strip().startswith("차량:"):
            return line.split(":", 1)[1]
    return memo


def find_prices(memo: str) -> str:
    """가격표에서 메모의 차종과 맞는 차종 묶음(## ...)만 골라낸다."""
    text = read_text(PRICE_FILE)
    if not text:
        return ""
    target = vehicle_line(memo)
    header, *sections = re.split(r"(?m)^(?=## )", text)
    picked = []
    for sec in sections:
        m = re.search(r"(?m)^검색어: (.*)$", sec)
        tokens = [t.strip() for t in m.group(1).split(",")] if m else []
        if any(re.search(rf"(?<![A-Za-z0-9]){re.escape(t)}(?![0-9])", target, re.I) for t in tokens if t):
            picked.append(sec.strip())
    return header.strip() + "\n\n" + "\n\n".join(picked) if picked else ""


def build_content(folder: Path, images: list[Path], references: list[str], cfg: dict) -> list[tuple[str, object]]:
    content: list[tuple[str, object]] = []
    for i, ref in enumerate(references, 1):
        content.append(("text", f'<reference index="{i}">\n{ref}\n</reference>'))
    for img in images:
        content.append(("text", f"사진 파일 이름: {img.name}"))
        content.append(("image", encode_image(img)))
    memo = read_text(folder / TOPIC_FILE)
    prices = find_prices(memo) or "(가격표에 이 차종이 없습니다. 가격은 쓰지 마세요.)"
    guide = read_text(GUIDE_DIR / f"{post_kind(folder)}.txt")
    content.append(("text",
        f"<style>\n{cfg.get('style', '')}\n</style>\n\n"
        f"<guide>\n{guide}\n</guide>\n\n"
        f"<keywords>\n{read_text(KEYWORD_FILE)}\n</keywords>\n\n"
        f"<prices>\n{prices}\n</prices>\n\n"
        f"<memo>\n{memo}\n</memo>\n\n"
        "위 메모와 사진으로 블로그 글을 써주세요."))
    return content


def generate(cfg: dict, folder: Path) -> None:
    if not (folder / TOPIC_FILE).exists():
        print(f"[건너뜀] {folder.name}: {TOPIC_FILE} 이 없습니다.")
        return
    images = list_images(folder)
    references = load_references(folder)
    if not PRICE_FILE.exists():
        print(f"[주의] {PRICE_FILE.relative_to(ROOT)} 가 없어 가격 없이 씁니다.")
    if not references:
        print("[주의] 레퍼런스 글이 없습니다. references 폴더에 .txt 를 넣으면 그 구조를 따라 씁니다.")
    print(f"[작성 중] {folder.name} ({ai_providers.provider(cfg)} {ai_providers.model(cfg)}, 사진 {len(images)}장, 레퍼런스 {len(references)}개)")

    try:
        ai = ai_providers.write(cfg, SYSTEM, build_content(folder, images, references, cfg))
    except ai_providers.AIError as e:
        print(f"[실패] {folder.name}: {e}")
        return

    # 없는 사진 이름은 빼고, 빠진 사진은 끝에 붙인다
    names = {p.name for p in images}
    blocks = [Block(b.kind, b.text.strip()) for b in ai.blocks
              if b.kind != "image" or b.text.strip() in names]
    used = {b.text for b in blocks if b.kind == "image"}
    blocks += [Block("image", n) for n in sorted(names - used)]
    # 상담 안내는 AI가 아니라 설정 그대로 붙인다 (연락처 오타 방지)
    if cfg.get("closing"):
        blocks.append(Block("paragraph", cfg["closing"].strip()))

    tags = [t.strip().lstrip("#").replace(" ", "") for t in ai.tags]
    write_draft(folder / DRAFT_FILE, Draft(ai.title.strip(), [t for t in tags if t], blocks))
    print(f"[완료] {folder / DRAFT_FILE}  ← 열어서 확인/수정하세요.")


def main() -> None:
    load_dotenv(ROOT / ".env")
    cfg = load_config()
    if len(sys.argv) > 1:
        folders = [resolve_folder(sys.argv[1])]
    else:
        folders = [f for f in post_folders() if not (f / DRAFT_FILE).exists()]
        if not folders:
            print("새로 쓸 글이 없습니다. posts 폴더에 글 폴더(topic.txt + 사진)를 만들어 주세요.")
    for folder in folders:
        generate(cfg, folder)


if __name__ == "__main__":
    main()
