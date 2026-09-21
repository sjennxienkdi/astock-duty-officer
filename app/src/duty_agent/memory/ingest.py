"""KB 收录与分块（plan §6）：只收跨日有效的结论性档案，time-bound 一律不收。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from duty_agent.memory.store import Chunk, KbStore

# 只收这些（plan §6「收」列）；其余档案即使存在也不进索引
INCLUDE = ("SUMMARY.md", "CROSS_EXAM.md", "EVENTS-POSITIONS.md")
INCLUDE_DD = "DD"
QUANT_LAB = "quant-lab"

# 明令不收（plan §6「不收」列）：time-bound，收了就会跨日锚定
TIME_BOUND = ("DECISION-*.md", "CANDIDATES.md", "PACK.md", "EVENT-INDEX.md")

_DOC_TYPE = {
    "SUMMARY.md": "summary",
    "CROSS_EXAM.md": "cross_exam",
    "EVENTS-POSITIONS.md": "events",
}
_TIER = {
    "summary": "结论性档案",
    "cross_exam": "结论性档案",
    "events": "结论性档案",
    "diligence": "背调档",
    "experiment": "quant-lab",
}
_HEADING = re.compile(r"^##\s+(.*)$")
_FRONTMATTER = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)


@dataclass(frozen=True)
class Block:
    """一个 `##` 小节。"""

    heading: str
    body: str


def split_blocks(text: str) -> list[Block]:
    """markdown 按 `##` 分块；标题前的引言段算第 0 块。"""
    body = _FRONTMATTER.sub("", text)
    blocks: list[Block] = []
    lines: list[str] = []
    heading = ""
    for line in body.splitlines():
        if match := _HEADING.match(line):
            if "".join(lines).strip():
                blocks.append(Block(heading, "\n".join(lines).strip()))
            heading, lines = match.group(1).strip(), []
        else:
            lines.append(line)
    if "".join(lines).strip():
        blocks.append(Block(heading, "\n".join(lines).strip()))
    return blocks


def parse_frontmatter(text: str) -> dict[str, str]:
    """读 YAML 式单行 frontmatter（本仓库只需要 `key: value`）。"""
    match = _FRONTMATTER.match(text)
    if match is None:
        return {}
    fields: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            fields[key.strip()] = value.strip().strip('"')
    return fields


def is_time_bound(name: str) -> bool:
    """这个档案名属于 time-bound，禁止进 KB。"""
    return any(Path(name).match(pattern) for pattern in TIME_BOUND)


def ingest(store: KbStore, day_dir: Path, quant_lab_dir: Path, day: str) -> int:
    """把当天的结论性档案与 quant-lab 结题卡增量写入索引。"""
    chunks: list[Chunk] = []
    for name, doc_type in _DOC_TYPE.items():
        path = day_dir / name
        if not path.is_file():
            continue
        blocks = split_blocks(path.read_text(encoding="utf-8"))
        if doc_type == "summary":
            blocks = [b for b in blocks if "结论" in b.heading]
        chunks += _make(f"{name.rsplit('.', 1)[0]}@{day}", doc_type, day, "", blocks)
    for dd in sorted((day_dir / INCLUDE_DD).glob("*/*.md")):
        blocks = split_blocks(dd.read_text(encoding="utf-8"))
        code = dd.parent.name
        chunks += _make(f"DD/{code}@{dd.stem}", "diligence", dd.stem, code, blocks)
    for card in sorted(quant_lab_dir.glob("*.md")):
        text = card.read_text(encoding="utf-8")
        meta = parse_frontmatter(text)
        doc_id = meta.get("doc_id") or card.stem
        chunks += _make(
            doc_id,
            "experiment",
            meta.get("as_of", ""),
            meta.get("code", ""),
            split_blocks(text),
            tier=_TIER["experiment"],
        )
    store.upsert(chunks)
    return len(chunks)


def _make(
    doc_id: str, doc_type: str, as_of: str, code: str, blocks: list[Block], tier: str = ""
) -> list[Chunk]:
    return [
        Chunk(
            doc_id=doc_id,
            code=code,
            doc_type=doc_type,
            as_of=as_of,
            source_tier=tier or _TIER[doc_type],
            text=(f"## {block.heading}\n{block.body}" if block.heading else block.body),
        )
        for block in blocks
    ]
