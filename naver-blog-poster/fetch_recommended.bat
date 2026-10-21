@echo off
chcp 65001 >nul
cd /d %~dp0
call .venv\Scripts\activate
echo 추천 레퍼런스 글을 모두 저장합니다. (1~2분 걸려요)
python fetch_reference.py --list data\recommended_refs.txt
pause
