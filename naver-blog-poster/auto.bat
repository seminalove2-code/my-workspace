@echo off
chcp 65001 >nul
cd /d %~dp0
call .venv\Scripts\activate
if not exist logs mkdir logs
echo ===== %date% %time% ===== >> logs\auto.log
python generate.py >> logs\auto.log 2>&1
python post.py >> logs\auto.log 2>&1
