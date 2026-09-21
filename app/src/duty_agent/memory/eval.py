"""KB 评测（plan §6）：recall@5 与 MRR，结果写进 EVALUATION.md。"""

from __future__ import annotations

import json
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from duty_agent.config import get_settings
from duty_agent.memory.ingest import ingest
from duty_agent.memory.store import KbStore

RECALL_TARGET = 0.8
GOLDEN_PATH = Path(__file__).with_name("eval_golden.json")


@dataclass(frozen=True)
class Golden:
    """一条金标问题。"""

    question: str
    expected_doc_ids: tuple[str, ...]


@dataclass(frozen=True)
class Metrics:
    """检索质量指标。"""

    total: int
    hits: int
    recall_at_5: float
    mrr: float

    @property
    def passed(self) -> bool:
        return self.recall_at_5 >= RECALL_TARGET


def load_golden(path: Path = GOLDEN_PATH) -> list[Golden]:
    """读金标集。"""
    rows = json.loads(path.read_text(encoding="utf-8"))
    return [Golden(row["question"], tuple(row["expected_doc_ids"])) for row in rows]


def build_store(db_path: Path, examples_dir: Path, day: str) -> KbStore:
    """从 examples 全量重建索引（评测不落增量状态，保证可重跑）。"""
    store = KbStore(db_path)
    store.reset()
    ingest(store, examples_dir, examples_dir / "fixtures" / "quant-lab", day)
    return store


def evaluate(store: KbStore, golden: list[Golden], *, top_k: int = 5) -> Metrics:
    """算 recall@5 与 MRR。评测度量的是检索质量，因此不加元数据过滤。"""
    hits, reciprocal = 0, 0.0
    for case in golden:
        ranked = [r.chunk.doc_id for r in store.search(case.question, top_k=top_k)]
        found = [rank + 1 for rank, doc in enumerate(ranked) if doc in case.expected_doc_ids]
        if found:
            hits += 1
            reciprocal += 1 / found[0]
    total = len(golden) or 1
    return Metrics(total=total, hits=hits, recall_at_5=hits / total, mrr=reciprocal / total)


def write_evaluation(metrics: Metrics, path: Path) -> None:
    """把结果写进 EVALUATION.md 的两行指标。"""
    pattern = {
        "| KB recall@5": f"| KB recall@5 | {metrics.recall_at_5:.2f}（验收线 ≥ {RECALL_TARGET}，"
        f"{metrics.hits}/{metrics.total} 命中） | `uv run python -m duty_agent.memory.eval` |",
        "| KB MRR": f"| KB MRR | {metrics.mrr:.3f} | `uv run python -m duty_agent.memory.eval` |",
    }
    lines = path.read_text(encoding="utf-8").splitlines()
    out = [
        next((row for prefix, row in pattern.items() if line.startswith(prefix)), line)
        for line in lines
    ]
    path.write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    """跑评测；`--write` 时同步更新 EVALUATION.md。"""
    args = argv if argv is not None else sys.argv[1:]
    settings = get_settings()
    examples, day = settings.examples_dir, settings.examples_dir.name.removeprefix("replay-")
    with tempfile.TemporaryDirectory() as tmp:
        with build_store(Path(tmp) / "kb.sqlite3", examples, day) as store:
            metrics = evaluate(store, load_golden())
    print(f"金标问题 {metrics.total} 条，命中 {metrics.hits} 条")
    print(f"recall@5 = {metrics.recall_at_5:.2f}（验收线 {RECALL_TARGET}）")
    print(f"MRR      = {metrics.mrr:.3f}")
    if "--write" in args:
        write_evaluation(metrics, settings.results_dir.parent / "EVALUATION.md")
        print("已写入 EVALUATION.md")
    if not metrics.passed:
        print("未达验收线：recall@5 低于 0.8")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
