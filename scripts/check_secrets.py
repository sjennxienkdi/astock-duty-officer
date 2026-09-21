"""脱敏终检（plan §16）：扫描全仓，命中密钥/真实 webhook/含用户名的绝对路径即失败。"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {
    ".git",
    ".venv",
    "__pycache__",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    "node_modules",
}
TEXT_SUFFIXES = {
    ".py",
    ".md",
    ".toml",
    ".yml",
    ".yaml",
    ".json",
    ".txt",
    ".cfg",
    ".ini",
    ".env",
    ".example",
}
PLACEHOLDER_HINTS = (
    "<",
    "REPLACE",
    "your-",
    "your_",
    "example",
    "changeme",
    "xxxx",
    "placeholder",
    "dummy",
)
USERNAME_PATH = re.compile(
    r"(?:[A-Za-z]:[\\/](?:Users|home)[\\/](?!<)[\w.\-]+|[\\/](?:Users|home)[\\/](?!<)[\w.\-]+)"
)
SECRET_ASSIGN = re.compile(
    r"""(?ix)
    \b [a-z0-9_]*(?:api[_-]?key|token|secret|password|webhook|access[_-]?key)[a-z0-9_]*
    \s* [=:]\s* ["']? (?!%|\$|\{)([A-Za-z0-9_\-]{16,})
    """
)
BARE_KEY = re.compile(r"\bsk-[A-Za-z0-9]{16,}\b")
WECOM_URL = re.compile(r"qyapi\.weixin\.qq\.com/cgi-bin/webhook/send\?key=([A-Za-z0-9\-]{8,})")


def _is_placeholder(value: str) -> bool:
    low = value.lower()
    return any(h in low for h in PLACEHOLDER_HINTS)


def _iter_files() -> list[Path]:
    out: list[Path] = []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        if set(path.relative_to(ROOT).parts) & SKIP_DIRS:
            continue
        out.append(path)
    return out


def check() -> list[str]:
    """返回违规项列表，空列表代表通过。"""
    problems: list[str] = []
    for path in _iter_files():
        rel = path.relative_to(ROOT).as_posix()
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            for match in BARE_KEY.finditer(line):
                problems.append(f"{rel}:{lineno}: 疑似密钥 {match.group(0)[:12]}…")
            for match in SECRET_ASSIGN.finditer(line):
                if not _is_placeholder(match.group(1)):
                    problems.append(f"{rel}:{lineno}: 疑似真实凭据赋值 {match.group(1)[:12]}…")
            for match in WECOM_URL.finditer(line):
                if not _is_placeholder(match.group(1)):
                    problems.append(f"{rel}:{lineno}: 疑似真实企业微信 webhook key")
            for match in USERNAME_PATH.finditer(line):
                problems.append(f"{rel}:{lineno}: 绝对路径含用户名 {match.group(0)}")
    return [p for p in problems if ".gitkeep" not in p]


def main() -> int:
    problems = check()
    if problems:
        print("脱敏检查未通过：")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print(f"脱敏检查通过：扫描 {len(_iter_files())} 个文本文件，无命中")
    return 0


if __name__ == "__main__":
    sys.exit(main())
