@echo off
chcp 65001 >nul
cd /d %~dp0
call .venv\Scripts\activate
echo 글 주소를 넣으면 그 글 하나, 블로그 주소를 넣으면 최근 글 여러 개를 저장합니다.
:loop
echo.
set URL=
set KIND=
set COUNT=
set /p URL=블로그 또는 글 주소 (그냥 Enter 누르면 종료): 
if "%URL%"=="" exit /b
set /p KIND=글 종류 이름 (예: 출고후기, 차량정보 / 없으면 Enter): 
set /p COUNT=가져올 글 개수 (기본 5, Enter): 
if "%COUNT%"=="" set COUNT=5
python fetch_reference.py "%URL%" "%KIND%" %COUNT%
goto loop
