"""설정 화면에서 config.yaml 과 .env 를 고친다. config.yaml 의 설명(주석)은 그대로 둔다."""
import os
import re

from common import ROOT

CONFIG = ROOT / "config.yaml"
ENV = ROOT / ".env"


def _write(path, text: str) -> None:
    """다른 기능이 읽는 도중에 빈 파일을 보지 않도록 임시 파일에 쓰고 바꿔 끼운다."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _q(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def set_top(key: str, value: str | bool) -> None:
    """맨 앞에 있는 'key: 값' 한 줄을 바꾼다."""
    text = CONFIG.read_text(encoding="utf-8")
    v = ("true" if value else "false") if isinstance(value, bool) else _q(value)
    text, n = re.subn(rf'(?m)^{re.escape(key)}:.*$', f"{key}: {v}", text, count=1)
    if not n:
        text = text.rstrip() + f"\n{key}: {v}\n"
    _write(CONFIG, text)


def set_model(provider: str, model: str) -> None:
    """models: 아래의 '  provider: 값' 한 줄을 바꾼다."""
    text = CONFIG.read_text(encoding="utf-8")
    text = re.sub(rf'(?ms)^(models:\n(?:  .*\n)*?  {provider}:).*?$', rf'\1 {_q(model)}', text, count=1)
    _write(CONFIG, text)


def set_block(key: str, value: str) -> None:
    """'key: |' 로 시작하는 여러 줄 값(예: closing)을 바꾼다."""
    text = CONFIG.read_text(encoding="utf-8")
    body = "".join(f"  {line}\n" if line.strip() else "\n" for line in value.strip().splitlines())
    pattern = rf'(?ms)^{re.escape(key)}: \|\n(?:(?:  .*)?\n)*'
    if re.search(pattern, text):
        text = re.sub(pattern, lambda m: f"{key}: |\n{body}", text, count=1)
    else:
        text = text.rstrip() + f"\n\n{key}: |\n{body}"
    _write(CONFIG, text)


def set_env(name: str, value: str) -> None:
    lines = ENV.read_text(encoding="utf-8-sig").splitlines() if ENV.exists() else []
    out, found = [], False
    for line in lines:
        if line.split("=", 1)[0].strip() == name:
            out.append(f"{name}={value}")
            found = True
        else:
            out.append(line)
    if not found:
        out.append(f"{name}={value}")
    _write(ENV, "\n".join(out) + "\n")


def has_env(name: str) -> bool:
    if not ENV.exists():
        return False
    for line in ENV.read_text(encoding="utf-8-sig").splitlines():
        k, _, v = line.partition("=")
        if k.strip() == name and v.strip():
            return True
    return False
