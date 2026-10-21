@echo off
chcp 65001 >nul
cd /d %~dp0
call .venv\Scripts\activate
set /p FOLDER=테스트할 글 폴더 이름: 
python post.py "%FOLDER%" --test
pause
