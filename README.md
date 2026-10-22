# my-workspace

유튜브 영상을 Claude에게 학습시키고, 정리한 내용을 쌓아 두는 저장소입니다.

## 사용법

claude.ai/code 에서 이 저장소로 세션을 열고 이렇게 말하면 됩니다.

- **영상 학습시키기**: "이 영상 학습해줘 https://www.youtube.com/watch?v=..."
  - 유튜브 접속이 막혀 있으면, 유튜브에서 `...더보기 → 스크립트 표시`로 자막을 복사해 함께 붙여넣으세요.
- **대본 분석하기**: "이 영상 대본 분석해줘 https://www.youtube.com/watch?v=..."
  - 자막을 뽑아 후킹·구조·시청 유지 장치·CTA를 분석하고, 내 콘텐츠용 대본 템플릿까지 만들어 줍니다.
- **배운 내용 활용하기**: "지금까지 학습한 내용 바탕으로 쇼츠 대본 아이디어 5개 줘"
- **목록 보기**: "학습한 영상 목록 보여줘"

## 폴더 구조

| 경로 | 내용 |
|------|------|
| `notes/youtube/` | 영상별 정리본 |
| `notes/youtube/analysis/` | 영상별 자막과 대본 분석 |
| `notes/youtube/INDEX.md` | 정리한 영상 목록 |
| `.claude/skills/youtube-script-analysis/` | 자막 추출·대본 분석 규칙과 자막 추출 스크립트 |
| `.claude/skills/youtube-study/SKILL.md` | 정리 형식과 규칙. 바꾸고 싶으면 Claude에게 "정리 형식에 ○○ 항목 추가해줘"라고 하면 됩니다. |
