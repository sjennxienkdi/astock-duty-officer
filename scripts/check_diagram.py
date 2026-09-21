"""校验 README / ARCHITECTURE 首屏主链图与 plan.md §3.1 逐字一致（plan §1 DoD）。"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FENCE = re.compile(r"```mermaid\n(.*?)```", re.DOTALL)


def first_diagram(path: Path) -> str:
    """取文件里第一个 mermaid 代码块正文。"""
    match = FENCE.search(path.read_text(encoding="utf-8"))
    if match is None:
        raise SystemExit(f"{path.name}: 未找到 mermaid 图")
    return match.group(1)


def main() -> int:
    canonical = first_diagram(ROOT / "plan.md")
    bad = [
        name for name in ("README.md", "ARCHITECTURE.md") if first_diagram(ROOT / name) != canonical
    ]
    if bad:
        print(f"主链图与 plan §3.1 不一致: {', '.join(bad)}")
        return 1
    print("主链图一致性检查通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
