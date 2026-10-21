"""윈도우 작업 스케줄러에 '매일 총정리 글 쓰기'를 켜고 끈다.

PC가 꺼져 있던 날은 다음에 켤 때 한 번 실행된다 (StartWhenAvailable).
"""
import subprocess
import sys

from common import ROOT

TASK = "BMW블로그_총정리"


def _ps(script: str) -> str:
    flags = 0x08000000 if sys.platform == "win32" else 0  # 검은 창 안 띄우기
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=flags)
    return (r.stdout + r.stderr).strip()


def enable(at: str = "08:30") -> str:
    pyw = ROOT / ".venv" / "Scripts" / "pythonw.exe"
    if not pyw.exists():
        pyw = sys.executable
    script = f"""
$a = New-ScheduledTaskAction -Execute '{pyw}' -Argument '"{ROOT / "auto_guide.py"}" --wait' -WorkingDirectory '{ROOT}'
$t = New-ScheduledTaskTrigger -Daily -At '{at}'
$s = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 3)
Register-ScheduledTask -TaskName '{TASK}' -Action $a -Trigger $t -Settings $s -Force | Out-Null
'ok'"""
    out = _ps(script)
    return f"매일 {at} 무렵(0~60분 사이 아무 때나) 총정리 글을 한 편씩 올립니다." if out.endswith("ok") else f"켜지 못했습니다: {out}"


def disable() -> str:
    _ps(f"Unregister-ScheduledTask -TaskName '{TASK}' -Confirm:$false")
    return "매일 자동 쓰기를 껐습니다."


def status() -> str:
    script = (f"$i = Get-ScheduledTaskInfo -TaskName '{TASK}' -ErrorAction SilentlyContinue; "
              "if ($i) { 'on|' + $i.NextRunTime.ToString('yyyy-MM-dd HH:mm') + '|' + $i.LastRunTime.ToString('yyyy-MM-dd HH:mm') } "
              "else { 'off' }")
    out = _ps(script)
    if out.startswith("on|"):
        _, nxt, last = out.split("|")
        return f"켜짐 · 다음 실행 {nxt}" + (f" · 지난 실행 {last}" if last[:4] > "2000" else "")
    return "꺼짐"


if __name__ == "__main__":
    print({"on": enable, "off": disable}.get(sys.argv[1] if len(sys.argv) > 1 else "", status)())
