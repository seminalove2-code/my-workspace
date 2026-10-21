"""AI가 메모(topic.txt) + 사진 + 레퍼런스 글을 보고 draft.md 를 쓴다.

사용법:
  python generate.py             # 아직 draft.md 가 없는 모든 글 폴더
  python generate.py 글폴더이름    # 특정 폴더만 (기존 draft.md 덮어씀)
"""
import re
import sys
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv

import ai_providers
import blur
import card

from common import (DRAFT_FILE, REFERENCE_FILE, REFERENCES_DIR, ROOT, TOPIC_FILE,
                    Block, Draft, list_images, needs_blur, upload_image, CARD_FILE, THUMB_FILE, load_config, post_folders, post_kind,
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
- 가격은 <prices> 의 [판매가격]에 있는 것만, 옵션은 [트림별 주요 사양]에 있는 것만 씁니다.
- 제원(크기, 공차 중량, 출력, 토크, 0-100km/h, 연비 등)은 <specs> (Approach Book 제원표, 모델별 정확한 값)를 우선하고, 없으면 [제원]에 있는 것만 씁니다. <prices> 에 없는 트림의 가격은 쓰지 않습니다.
- [제원]의 모델 이름은 엔진 기준입니다. 메모의 트림 이름 앞부분과 맞는 줄의 값만 씁니다. (예: 트림 "X3 20 xDrive M Sport" → [제원]의 "X3 20" 줄). 맞는 줄이 없거나 애매하면 그 값은 쓰지 않습니다.
- 출고후기와 차량정보 글에는 "차량 주요 사양" 인용구 소제목과 사양 정리를 반드시 넣습니다.
- card 에는 스펙 카드 이미지에 들어갈 값을 넣습니다. 규칙은 본문과 같아서 <prices> 와 메모에 있는 값만 쓰고, 모르면 "" 로 둡니다.
  price 는 만원 단위 숫자만(예: 7,610), power/torque/zero100/top_speed 는 숫자만, options 는 고객이 체감하는 옵션 6~8개를 각 12자 안팎으로 씁니다.
  카드 이미지와 썸네일은 프로그램이 넣으므로 blocks 에는 넣지 마세요. 첫 블록은 사진이 아니라 인사말 문단으로 시작하세요.
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
- 독자는 대부분 휴대폰으로 봅니다. paragraph 의 한 줄은 공백 포함 18자 안팎(휴대폰 한 줄)으로 짧게 끊고, 한 문단은 2~4줄로 씁니다.
  긴 문장은 두 문장으로 나눕니다. 숫자·단위(예: 1,835kg)가 줄 끝에서 잘리지 않게 끊습니다.
- "자료에 안내되어 있어요", "제원이 확인되는", "참고하시면 됩니다"처럼 문서를 읽어주는 말투는 쓰지 않습니다. 딜러가 고객에게 직접 말하듯 씁니다.
  (예: "0-100km/h 7.3초라 고속도로 합류가 편해요")
- tags 에는 # 없이 단어만 넣습니다."""


def encode_image(path: Path) -> bytes:
    return blur.to_jpeg(blur.load_upright(path), MAX_SIDE)


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


def price_sections() -> tuple[str, dict[str, str]]:
    """가격표를 (머리말, {"THE 5": 차종 묶음 글, ...}) 로 나눈다."""
    header, *sections = re.split(r"(?m)^(?=## )", read_text(PRICE_FILE))
    return header.strip(), {sec.splitlines()[0][3:].strip(): sec.strip() for sec in sections}


def matching_series(memo: str) -> list[str]:
    """메모의 차종과 맞는 가격표 차종 이름들 (예: ["THE 5"])."""
    target = vehicle_line(memo)
    picked = []
    for name, sec in price_sections()[1].items():
        m = re.search(r"(?m)^검색어: (.*)$", sec)
        tokens = [t.strip() for t in m.group(1).split(",")] if m else []
        if any(re.search(rf"(?<![A-Za-z0-9]){re.escape(t)}(?![0-9])", target, re.I) for t in tokens if t):
            picked.append(name)
    return picked


def find_prices(memo: str) -> str:
    """가격표에서 메모의 차종과 맞는 차종 묶음(## ...)만 골라낸다."""
    if not PRICE_FILE.exists():
        return ""
    header, sections = price_sections()
    picked = [sections[n] for n in matching_series(memo)]
    return header + "\n\n" + "\n\n".join(picked) if picked else ""


def build_content(folder: Path, images: list[Path], references: list[str], cfg: dict) -> list[tuple[str, object]]:
    content: list[tuple[str, object]] = []
    for i, ref in enumerate(references, 1):
        content.append(("text", f'<reference index="{i}">\n{ref}\n</reference>'))
    for img in images:
        content.append(("text", f"사진 파일 이름: {img.name}"))
        shown = upload_image(cfg, folder, img.name) or img
        content.append(("image", encode_image(shown)))
    memo = read_text(folder / TOPIC_FILE)
    prices = find_prices(memo) or "(가격표에 이 차종이 없습니다. 가격은 쓰지 마세요.)"
    guide = read_text(GUIDE_DIR / f"{post_kind(folder)}.txt")
    import guide as guide_mod  # Approach Book 제원표 (PDF 에서 뽑아 둔 경우)
    specs = "\n".join(t for s in matching_series(memo) if (t := guide_mod.specs_text(guide_mod.assets(s))))
    content.append(("text",
        f"<style>\n{cfg.get('style', '')}\n</style>\n\n"
        f"<guide>\n{guide}\n</guide>\n\n"
        f"<keywords>\n{read_text(KEYWORD_FILE)}\n</keywords>\n\n"
        f"<prices>\n{prices}\n</prices>\n\n"
        f"<specs>\n{specs or '(제원표 없음)'}\n</specs>\n\n"
        f"<memo>\n{memo}\n</memo>\n\n"
        "위 메모와 사진으로 블로그 글을 써주세요."))
    return content


def generate(cfg: dict, folder: Path) -> None:
    if not (folder / TOPIC_FILE).exists():
        print(f"[건너뜀] {folder.name}: {TOPIC_FILE} 이 없습니다.")
        return
    images = list_images(folder)
    if needs_blur(cfg, folder) and images and not blur.blur_folder(cfg, folder):
        print(f"[중단] {folder.name}: 번호판 가리기에 실패한 사진이 있어 글을 쓰지 않았습니다. write.bat 을 다시 실행하세요.")
        return
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
    # 스펙 카드는 '차량 주요 사양' 소제목 바로 아래(없으면 마무리 앞), 썸네일은 맨 처음
    if post_kind(folder) in ("출고후기", "차량정보"):
        try:
            card.save_card_data(folder, {**ai.card.model_dump(), "kind": post_kind(folder)})
            if card.render(folder, cfg):
                at = next((i + 1 for i, b in enumerate(blocks) if b.kind == "quote" and "사양" in b.text), len(blocks))
                blocks.insert(at, Block("image", CARD_FILE))
                blocks.insert(0, Block("image", THUMB_FILE))  # 썸네일은 글 맨 처음 (네이버 검색 대표 사진)
        except Exception as e:  # 카드가 실패해도 글은 쓴다
            print(f"[주의] 스펙 카드를 만들지 못했습니다: {e}")
    # 이 차종 총정리 글이 발행돼 있으면 그 글로 가는 안내를 붙인다
    import guide  # guide 가 generate 를 쓰므로 여기서 불러온다
    guide.sync_urls(cfg)  # 그사이 발행된 총정리 글 주소 채우기
    if link := guide.link_for(read_text(folder / TOPIC_FILE), cfg):
        blocks.append(Block("paragraph", link))
    # 상담 안내는 AI가 아니라 설정 그대로 붙인다 (연락처 오타 방지)
    if cfg.get("closing"):
        blocks.append(Block("paragraph", cfg["closing"].strip()))

    if post_kind(folder) in ("출고후기", "차량정보") and not any(b.kind == "quote" and "사양" in b.text for b in blocks):
        print("[주의] 글에 '차량 주요 사양' 부분이 없습니다. 다시 쓰기를 누르거나 직접 넣어주세요.")
    tags = [t.strip().lstrip("#").replace(" ", "") for t in ai.tags]
    write_draft(folder / DRAFT_FILE, Draft(ai.title.strip(), [t for t in tags if t], blocks))
    print(f"[완료] {folder / DRAFT_FILE}  ← 열어서 확인/수정하세요.")


CARD_SYSTEM = """You fill in the values for a BMW spec card image from the given price list and memo.
Use only values that appear in <prices> (판매가격, 제원, 트림별 주요 사양) or <memo>. If a value is not there, use "".
Match the memo's trim to the price list: [제원] model names are engine names (e.g. trim "X3 20 xDrive M Sport" -> "X3 20").
price: 만원 number only (e.g. 7,610), the latest model year / latest production price when several are listed.
power, torque, zero100, top_speed: numbers only. options: 6-8 features a customer notices, each about 12 Korean characters.
Write all text in Korean except model names."""


def add_cards(cfg: dict, folder: Path, text: str) -> str:
    """본문은 그대로 두고 썸네일(맨 앞)과 스펙 카드('차량 주요 사양' 아래)만 넣은 글을 돌려준다."""
    memo = read_text(folder / TOPIC_FILE)
    prices = find_prices(memo) or "(가격표에 이 차종이 없습니다)"
    values = ai_providers.ask(cfg, CARD_SYSTEM, [("text", f"<prices>\n{prices}\n</prices>\n\n<memo>\n{memo}\n</memo>")],
                              ai_providers.SpecCard, max_tokens=4000)
    card.save_card_data(folder, {**values.model_dump(), "kind": post_kind(folder)})
    card.render(folder, cfg)
    lines = text.splitlines()
    if f"[사진: {CARD_FILE}]" not in text:
        at = next((i + 1 for i, l in enumerate(lines) if l.startswith("> ") and "사양" in l), None)
        if at is None:  # 사양 소제목이 없으면 상담 안내 앞에
            at = next((i for i, l in enumerate(lines) if l.startswith("━")), len(lines))
        lines[at:at] = ["", f"[사진: {CARD_FILE}]", ""]
    if f"[사진: {THUMB_FILE}]" not in text:
        at = next((i + 1 for i, l in enumerate(lines) if l.startswith("태그:")), 1)
        lines[at:at] = ["", f"[사진: {THUMB_FILE}]"]
    return "\n".join(lines)


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
