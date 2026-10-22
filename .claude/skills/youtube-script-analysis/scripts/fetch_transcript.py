"""유튜브 링크에서 영상 정보와 자막을 가져온다.

사용법: python3 fetch_transcript.py <유튜브 링크 또는 영상 ID> [출력 파일]

1차로 youtube-transcript-api, 실패하면 yt-dlp 자막으로 시도한다.
둘 다 실패하면 종료 코드 2와 함께 이유를 출력한다(자막을 지어내지 않는다).
필요 패키지: pip install yt-dlp youtube-transcript-api
"""
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

LANGS = ["ko", "en"]


def video_id(arg):
    m = re.search(r"(?:v=|youtu\.be/|/shorts/|/live/|/embed/)([\w-]{11})", arg)
    if m:
        return m.group(1)
    if re.fullmatch(r"[\w-]{11}", arg):
        return arg
    sys.exit(f"영상 ID를 찾을 수 없습니다: {arg}")


def ts(sec):
    sec = int(sec)
    return f"{sec // 3600}:{sec % 3600 // 60:02d}:{sec % 60:02d}" if sec >= 3600 else f"{sec // 60:02d}:{sec % 60:02d}"


def metadata(vid):
    try:
        out = subprocess.run(
            ["yt-dlp", "-J", "--skip-download", "--no-warnings", f"https://www.youtube.com/watch?v={vid}"],
            capture_output=True, text=True, timeout=120,
        )
        d = json.loads(out.stdout)
        return {k: d.get(k) for k in ("title", "channel", "upload_date", "duration", "view_count", "description")}
    except Exception as e:
        return {"error": str(e)}


def from_transcript_api(vid):
    from youtube_transcript_api import YouTubeTranscriptApi
    t = YouTubeTranscriptApi().fetch(vid, languages=LANGS)
    return [(s.start, s.text) for s in t.snippets]


def from_ytdlp(vid):
    with tempfile.TemporaryDirectory() as d:
        subprocess.run(
            ["yt-dlp", "-q", "--no-warnings", "--skip-download", "--write-subs", "--write-auto-subs",
             "--sub-langs", ",".join(LANGS), "--sub-format", "json3",
             "-o", f"{d}/%(id)s.%(ext)s", f"https://www.youtube.com/watch?v={vid}"],
            capture_output=True, text=True, timeout=180,
        )
        files = sorted(Path(d).glob("*.json3"), key=lambda p: next((i for i, l in enumerate(LANGS) if f".{l}" in p.name), 99))
        if not files:
            raise RuntimeError("yt-dlp가 자막 파일을 받지 못했습니다")
        events = json.loads(files[0].read_text()).get("events", [])
        lines = []
        for e in events:
            text = "".join(s.get("utf8", "") for s in e.get("segs", [])).strip()
            if text:
                lines.append((e.get("tStartMs", 0) / 1000, text))
        return lines


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    vid = video_id(sys.argv[1])
    meta = metadata(vid)
    lines, errors = None, []
    for fn in (from_transcript_api, from_ytdlp):
        try:
            lines = fn(vid)
            if lines:
                break
        except Exception as e:
            errors.append(f"{fn.__name__}: {type(e).__name__}: {str(e).splitlines()[0][:200] if str(e) else ''}")

    head = [f"# {meta.get('title') or vid}", f"- 링크: https://www.youtube.com/watch?v={vid}"]
    for k, label in (("channel", "채널"), ("upload_date", "업로드"), ("duration", "길이(초)"), ("view_count", "조회수")):
        if meta.get(k):
            head.append(f"- {label}: {meta[k]}")
    if not lines:
        print("\n".join(head))
        print("\n자막을 가져오지 못했습니다.\n" + "\n".join(f"- {e}" for e in errors))
        sys.exit(2)

    body = "\n".join(f"[{ts(s)}] {t}" for s, t in lines)
    text = "\n".join(head) + "\n\n## 설명\n" + (meta.get("description") or "") + "\n\n## 자막\n" + body + "\n"
    if len(sys.argv) > 2:
        Path(sys.argv[2]).write_text(text)
        print(f"저장: {sys.argv[2]} ({len(lines)}줄)")
    else:
        print(text)


if __name__ == "__main__":
    main()
