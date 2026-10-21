"""사진 속 번호판을 AI로 찾아 모자이크한 사본을 글 폴더의 '가림' 폴더에 만든다.

원본은 건드리지 않는다. 블로그에는 '가림' 폴더의 사진이 올라간다.
"""
import io
from pathlib import Path

from PIL import Image, ImageFilter, ImageOps

import ai_providers
from common import BLUR_DIR, list_images

DETECT_SIDE = 1568   # AI에게 보낼 때만 줄인 크기
MARGIN = 0.25        # 찾은 영역보다 사방으로 25% 넓게 가린다
REPORT_FILE = "가림_결과.txt"

SYSTEM = """You find vehicle license plates in a photo so they can be blurred for privacy.
Return every license plate you can see: Korean plates, temporary paper plates, plates on other cars in the background,
and plates that are partly hidden, small, or seen at an angle. Do not return BMW logos, badges, or model lettering.
Coordinates are on a 0-1000 scale of the image as given (x from left, y from top), as a box that covers the whole plate.
If there is no plate, return an empty list."""


def load_upright(path: Path) -> Image.Image:
    """휴대폰 사진의 회전 정보(EXIF)를 실제 픽셀에 반영해서 연다."""
    img = ImageOps.exif_transpose(Image.open(path))
    return img.convert("RGB") if img.mode not in ("RGB", "L") else img


def to_jpeg(img: Image.Image, max_side: int) -> bytes:
    small = img.copy()
    small.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    small.convert("RGB").save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def pixelate(img: Image.Image, box: tuple[int, int, int, int]) -> None:
    region = img.crop(box)
    w, h = region.size
    if w < 2 or h < 2:
        return
    block = max(6, min(w, h) // 6)
    small = region.resize((max(1, w // block), max(1, h // block)), Image.Resampling.BILINEAR)
    region = small.resize((w, h), Image.Resampling.NEAREST).filter(ImageFilter.GaussianBlur(block // 2))
    img.paste(region, box)


def blur_image(cfg: dict, src: Path, dst: Path) -> int:
    img = load_upright(src)
    found = ai_providers.ask(cfg, SYSTEM, [("text", "Find all license plates."),
                                           ("image", to_jpeg(img, DETECT_SIDE))],
                             ai_providers.Plates, max_tokens=4000)
    W, H = img.size
    for p in found.plates:
        x1, x2 = sorted((p.x1, p.x2))
        y1, y2 = sorted((p.y1, p.y2))
        mx, my = (x2 - x1) * MARGIN, (y2 - y1) * MARGIN
        box = (max(0, int((x1 - mx) * W / 1000)), max(0, int((y1 - my) * H / 1000)),
               min(W, int((x2 + mx) * W / 1000)), min(H, int((y2 + my) * H / 1000)))
        if box[2] > box[0] and box[3] > box[1]:
            pixelate(img, box)
    dst.parent.mkdir(exist_ok=True)
    img.save(dst, quality=92)
    return len(found.plates)


def blur_folder(cfg: dict, folder: Path) -> bool:
    """가림 사본이 없는 사진만 처리한다. 하나라도 실패하면 False."""
    out_dir = folder / BLUR_DIR
    todo = [p for p in list_images(folder) if not (out_dir / p.name).exists()]
    if not todo:
        return True
    print(f"  번호판 가리는 중... ({len(todo)}장)")
    report, ok = [], True
    for src in todo:
        try:
            n = blur_image(cfg, src, out_dir / src.name)
            report.append(f"{src.name}: 번호판 {n}개 가림" if n else f"{src.name}: 번호판 못 찾음 ← 직접 확인")
        except ai_providers.AIError as e:
            ok = False
            report.append(f"{src.name}: 실패 ({e})")
    with open(out_dir / REPORT_FILE, "a", encoding="utf-8") as f:
        f.write("\n".join(report) + "\n")
    missed = sum("못 찾음" in r for r in report)
    print(f"  번호판 가림 완료: {len(todo)}장 중 {len(todo) - missed}장에서 찾음. "
          f"'{BLUR_DIR}' 폴더와 {REPORT_FILE}를 꼭 확인하세요.")
    return ok
