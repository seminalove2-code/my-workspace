"""여러 스크립트가 같이 쓰는 경로, 설정, 초안(draft.md) 읽기/쓰기."""
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
POSTS_DIR = ROOT / "posts"
REFERENCES_DIR = ROOT / "references"
PROFILE_DIR = ROOT / "browser_profile"

TOPIC_FILE = "topic.txt"
REFERENCE_FILE = "reference.txt"
DRAFT_FILE = "draft.md"
POSTED_FILE = "posted.txt"
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}

# Windows 콘솔에서 한글이 깨지지 않게
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def load_config() -> dict:
    with open(ROOT / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def list_images(folder: Path) -> list[Path]:
    return sorted(p for p in folder.iterdir() if p.suffix.lower() in IMAGE_EXTS)


def post_folders() -> list[Path]:
    if not POSTS_DIR.exists():
        return []
    return sorted(p for p in POSTS_DIR.iterdir() if p.is_dir())


def resolve_folder(arg: str) -> Path:
    """'posts/글이름' 또는 '글이름' 둘 다 받는다."""
    p = Path(arg)
    if not p.is_absolute() and not p.exists():
        p = POSTS_DIR / arg
    if not p.is_dir():
        sys.exit(f"폴더를 찾을 수 없습니다: {arg}")
    return p.resolve()


# ── draft.md 형식 ──
# # 제목
# 태그: 태그1, 태그2
#
# ## 소제목          → 굵은 글씨 한 줄
# > 인용구           → 인용구 상자
# 일반 문단          → 그대로
# [사진: 파일이름.jpg] → 폴더 안의 사진 업로드

@dataclass
class Block:
    kind: str  # "heading" | "quote" | "paragraph" | "image"
    text: str


@dataclass
class Draft:
    title: str
    tags: list[str]
    blocks: list[Block]


IMAGE_LINE = re.compile(r"^\[사진:\s*(.+?)\s*\]$")


def write_draft(path: Path, draft: Draft) -> None:
    lines = [f"# {draft.title}", f"태그: {', '.join(draft.tags)}", ""]
    for b in draft.blocks:
        if b.kind == "heading":
            lines.append(f"## {b.text}")
        elif b.kind == "quote":
            lines.append(f"> {b.text}")
        elif b.kind == "image":
            lines.append(f"[사진: {b.text}]")
        else:
            lines.append(b.text)
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def read_draft(path: Path) -> Draft:
    text = path.read_text(encoding="utf-8-sig")
    title, tags = "", []
    blocks: list[Block] = []
    paragraph: list[str] = []

    def flush():
        if paragraph:
            blocks.append(Block("paragraph", "\n".join(paragraph)))
            paragraph.clear()

    for raw in text.splitlines():
        line = raw.rstrip()
        if not title and line.startswith("# "):
            title = line[2:].strip()
        elif not blocks and not paragraph and line.startswith("태그:"):
            tags = [t.strip().lstrip("#") for t in line[3:].split(",") if t.strip()]
        elif not line.strip():
            flush()
        elif line.startswith("## "):
            flush()
            blocks.append(Block("heading", line[3:].strip()))
        elif line.startswith("> "):
            flush()
            blocks.append(Block("quote", line[2:].strip()))
        elif m := IMAGE_LINE.match(line.strip()):
            flush()
            blocks.append(Block("image", m.group(1)))
        else:
            paragraph.append(line)
    flush()

    if not title:
        sys.exit(f"{path} 첫 줄에 '# 제목'이 없습니다.")
    return Draft(title, tags, blocks)
