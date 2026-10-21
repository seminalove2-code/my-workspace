"""바탕화면에 'BMW 블로그' 바로가기를 만든다. (setup.bat 이 실행)"""
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parent
target = root / "start_app.bat"
script = (
    "$d=[Environment]::GetFolderPath('Desktop');"
    "$s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d 'BMW 블로그.lnk'));"
    f"$s.TargetPath='{target}';$s.WorkingDirectory='{root}';$s.WindowStyle=7;"
    "$s.IconLocation='%SystemRoot%\\System32\\shell32.dll,13';$s.Save()"
)
r = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, text=True)
print("바탕화면에 'BMW 블로그' 아이콘을 만들었습니다." if r.returncode == 0 else f"바로가기를 만들지 못했습니다: {r.stderr.strip()}")
