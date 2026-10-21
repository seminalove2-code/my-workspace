@echo off
chcp 65001 >nul
cd /d %~dp0
call .venv\Scripts\activate
:loop
set URL=
set /p URL=레퍼런스 블로그 글 주소 (그냥 Enter 누르면 종료): 
if "%URL%"=="" exit /b
python fetch_reference.py "%URL%"
goto loop
