@echo off
chcp 65001 >nul
cd /d %~dp0
set PY=python
where python >nul 2>nul || set PY=py
echo [1/3] 가상환경 만드는 중...
%PY% -m venv .venv || (echo 파이썬이 없습니다. python.org 에서 설치할 때 "Add python.exe to PATH" 를 체크하세요. & pause & exit /b)
call .venv\Scripts\activate
echo [2/3] 필요한 프로그램 설치 중...
pip install -r requirements.txt
echo [3/3] 브라우저 설치 중...
python -m playwright install chromium
if not exist .env copy .env.example .env >nul
echo.
echo 설치 완료! .env 파일을 메모장으로 열어 API 키를 넣고, config.yaml 에 블로그 아이디를 넣으세요.
pause
