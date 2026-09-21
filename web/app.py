"""值班台入口（plan §8）：五个只读页面，唯一写路径是确认页调用引擎 API。

共享读取模型放这里，是为了守住 §11 的文件清单：`web/` 只有 app.py 与 pages/，
页面保持直筒脚本，不散落第二份读档逻辑。
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any

import streamlit as st

from duty_agent.config import Settings, get_settings
from duty_agent.memory.store import KbStore
from duty_agent.planner import Planner, build_planner
from duty_engine.clock import SCHEDULE
from duty_engine.storage import Archive


def settings() -> Settings:
    """当前运行配置。"""
    return get_settings()


def archive() -> Archive:
    """档案读取器。"""
    return Archive(settings().results_dir)


def known_days() -> list[str]:
    """可选日期：结果目录下的每一天，加上仓库自带的示例日。"""
    daily = settings().results_dir / "daily"
    days = {p.name for p in daily.glob("*") if p.is_dir()} if daily.is_dir() else set()
    example = settings().examples_dir
    if example.is_dir():
        days.add(example.name.removeprefix("replay-"))
    return sorted(days)


def day_dir(day: str) -> Path:
    """当天档案目录，示例日直接指向 examples。"""
    example = settings().examples_dir
    if day == example.name.removeprefix("replay-"):
        return example
    return settings().results_dir / "daily" / day


def planner(day: str) -> Planner:
    """当天的编排者（只用来读引擎状态与调确认 API）。"""
    return build_planner(settings(), date.fromisoformat(day))


def read(day: str, name: str) -> str:
    """读一份档案，不存在返回空串。"""
    path = day_dir(day) / name
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def read_root(name: str) -> str:
    """读仓库根目录下的文档（EVALUATION.md 等）。"""
    path = REPO_ROOT / name
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def morning_rows(day: str) -> list[dict[str, Any]]:
    """解析 `MORNING.md` 成表格行。数字全部来自引擎。"""
    rows: list[dict[str, Any]] = []
    code = ""
    for line in read(day, "MORNING.md").splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            code, _, name = stripped[3:].partition(" ")
            rows.append({"code": code, "name": name})
        elif stripped and code and ":" in stripped:
            key, _, value = stripped.partition(":")
            rows[-1][key.strip()] = value.strip()
    return rows


def order_rows(day: str) -> list[dict[str, Any]]:
    """引擎订单表（十态看板的数据源）。"""
    store = planner(day).store
    rows = store.conn.execute(
        "SELECT * FROM orders WHERE trade_date = ? ORDER BY order_id", (day,)
    ).fetchall()
    return [dict(row) for row in rows]


def alert_rows(day: str) -> list[dict[str, Any]]:
    """当天告警。"""
    return [dict(row) for row in planner(day).store.alerts()]


def evidence_files(day: str) -> list[str]:
    """各角色的取证链文件名。"""
    return sorted(p.name for p in day_dir(day).glob("EVIDENCE-*.md"))


def archive_files(day: str) -> list[str]:
    """当天全部档案（含 .REJECTED 作废件），按 §2.2 的节奏顺序排。"""
    order = [
        "POOL-DRAFT.md",
        "PACK.md",
        "EVENT-INDEX.md",
        "CANDIDATES.md",
        "MORNING.md",
        "PLAN.md",
        "NOON.md",
        "INTRADAY.md",
        "SUMMARY.md",
        "EVENTS-POSITIONS.md",
        "ALERT.md",
    ]

    def rank(name: str) -> int:
        head = name.split(".")[0].split("-")[0]
        return order.index(head + ".md") if head + ".md" in order else len(order)

    paths = [p for p in day_dir(day).rglob("*") if p.is_file() and p.suffix in {".md", ".REJECTED"}]
    return sorted(
        (p.relative_to(day_dir(day)).as_posix() for p in paths),
        key=lambda name: (rank(name.split("/")[-1]), name),
    )


_DONE_EVIDENCE = {
    "screener_deep_research": "POOL-DRAFT.md",
    "pack_collect": "PACK.md",
    "news_index": "EVENT-INDEX.md",
    "screener_revise": "CANDIDATES.md",
    "lock_plan": "MORNING.md",
    "plan_doc": "PLAN.md",
    "intraday_watch": "INTRADAY.md",
    "noon_report": "NOON.md",
    "daily_summary": "SUMMARY.md",
}


def schedule_state(day: str) -> list[dict[str, Any]]:
    """§3.2 节奏表的完成状态：以档案与库里的痕迹判定，不看挂钟。"""
    rows: list[dict[str, Any]] = []
    for entry in SCHEDULE:
        if entry.name == "service_start":
            done = True
        elif entry.name == "lock_pool":
            done = bool(morning_rows(day))
        elif entry.name in ("decision_window", "decision_deadline"):
            done = bool(list(day_dir(day).glob("DECISION-*.md")))
        elif entry.name in ("diligence_night", "diligence_morning"):
            done = (day_dir(day) / "DD").is_dir()
        elif entry.name == "review":
            done = bool(list(day_dir(day).glob("REVIEW-*.md")))
        elif entry.name == "backup_and_ingest":
            done = bool(read(day, "SUMMARY.md"))
        else:
            done = bool(read(day, _DONE_EVIDENCE.get(entry.name, "")))
        rows.append(
            {
                "时刻": f"{'T-1 ' if entry.day_offset else ''}{entry.at.strftime('%H:%M')}",
                "定时槽": entry.name,
                "执行者": entry.actor,
                "状态": "已完成" if done else "未执行",
            }
        )
    return rows


REPO_ROOT = Path(__file__).resolve().parents[1]
_FRONTMATTER = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)


@st.cache_resource(show_spinner=False)
def kb_store(db_path: str) -> KbStore:
    """KB 索引（只读用途）。按路径缓存，测试互不污染。"""
    return KbStore(Path(db_path))


def frontmatter(text: str) -> dict[str, str]:
    """读结题卡的 frontmatter。"""
    match = _FRONTMATTER.match(text)
    if match is None:
        return {}
    fields: dict[str, str] = {}
    for line in match.group(1).splitlines():
        key, sep, value = line.partition(":")
        if sep:
            fields[key.strip()] = value.strip().strip('"')
    return fields


def pick_day(key: str = "day") -> str | None:
    """侧栏选日期。所有页面共用同一个 key，切页不丢选择。"""
    days = known_days()
    if not days:
        st.warning("还没有任何一天的档案。先跑一次金日子回放。")
        return None
    return st.sidebar.selectbox("选择交易日", days, index=len(days) - 1, key=key)


if __name__ == "__main__":
    st.set_page_config(page_title="A股值班台", page_icon="📈", layout="wide")
    st.navigation(
        [
            st.Page(
                "pages/board.py", title="值班台", icon=":material/dashboard:", url_path="board"
            ),
            st.Page(
                "pages/replay.py", title="全天回放", icon=":material/history:", url_path="replay"
            ),
            st.Page(
                "pages/confirm.py", title="人工确认", icon=":material/verified:", url_path="confirm"
            ),
            st.Page(
                "pages/kb.py", title="研究记忆", icon=":material/library_books:", url_path="kb"
            ),
            st.Page("pages/evals.py", title="评测", icon=":material/speed:", url_path="evals"),
        ],
        position="top",
    ).run()
