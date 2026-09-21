"""研究记忆 KB（plan §13 memory 条目）：强制过滤、time-bound 排除、验收线。"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pytest

from conftest import DAY as GOLDEN_DATE
from conftest import EXAMPLES, GoldenDay
from duty_agent.memory.eval import (
    RECALL_TARGET,
    Metrics,
    build_store,
    evaluate,
    load_golden,
    main,
    write_evaluation,
)
from duty_agent.memory.ingest import ingest, is_time_bound, parse_frontmatter, split_blocks
from duty_agent.memory.recall_tool import Filters, as_citations, recall
from duty_agent.memory.store import Chunk, KbStore, hash_embed, tokenize

DAY = "2026-09-16"


@pytest.fixture
def kb(tmp_path: Path) -> Iterator[KbStore]:
    with build_store(tmp_path / "kb.sqlite3", EXAMPLES, DAY) as store:
        yield store


def test_recall_requires_filter(kb: KbStore) -> None:
    with pytest.raises(ValueError):
        recall(kb, "缩量过滤", Filters())
    assert recall(kb, "缩量过滤", Filters(doc_type="experiment"))
    assert recall(kb, "立案调查", Filters(code="002456"))


def test_ingest_excludes_time_bound_docs(tmp_path: Path) -> None:
    """time-bound 档案即使躺在当天目录里也不能进索引，否则昨天会变成今天的事实。"""
    day = tmp_path / DAY
    (day / "DD" / "600519").mkdir(parents=True)
    (day / "DECISION-gpt.md").write_text("# DECISION\n\nstance: 建仓\n", encoding="utf-8")
    (day / "CANDIDATES.md").write_text("# CANDIDATES\n\n## 600519 贵州茅台\n", encoding="utf-8")
    (day / "PACK.md").write_text("# PACK\n", encoding="utf-8")
    (day / "EVENT-INDEX.md").write_text("# EVENT-INDEX\n", encoding="utf-8")
    (day / "SUMMARY.md").write_text(
        "# SUMMARY\n\n## 结论段\n持仓强制入池救回卖出通道。\n", encoding="utf-8"
    )
    (day / "DD" / "600519" / "2026-09-15.md").write_text("# DD\n\n- 质押: 无\n", encoding="utf-8")
    with KbStore(tmp_path / "kb.sqlite3") as store:
        store.reset()
        ingest(store, day, EXAMPLES / "fixtures" / "quant-lab", DAY)
        docs = {c.doc_id for c in store.chunks()}
        assert {"SUMMARY@2026-09-16", "DD/600519@2026-09-15"} <= docs
        assert not [
            d
            for d in docs
            if any(k in d for k in ("DECISION", "CANDIDATES", "PACK", "EVENT-INDEX"))
        ]
    assert all(
        is_time_bound(name)
        for name in ("DECISION-gpt.md", "CANDIDATES.md", "PACK.md", "EVENT-INDEX.md")
    )
    assert not is_time_bound("SUMMARY.md")


def test_recall_eval_threshold(kb: KbStore) -> None:
    metrics = evaluate(kb, load_golden())
    assert metrics.passed
    assert metrics.recall_at_5 >= RECALL_TARGET, metrics
    assert metrics.total == 20


def test_recall_falls_back_to_numpy_cosine(tmp_path: Path, kb: KbStore) -> None:
    """sqlite-vec 不可用时（§6 fallback）检索必须仍然可用。"""
    with build_store(tmp_path / "kb2.sqlite3", EXAMPLES, DAY) as mirror:
        mirror._vec_ready = False  # noqa: SLF001
        results = mirror.search("缩量过滤 回撤刹车", top_k=5)
        assert len(results) == 5
        assert {r.chunk.doc_id for r in results} & {
            r.chunk.doc_id for r in kb.search("缩量过滤 回撤刹车", top_k=5)
        }


def test_recall_is_filtered_by_metadata(kb: KbStore) -> None:
    results = recall(kb, "宁德时代 开庭 买卖合同纠纷", Filters(doc_type="diligence"))
    assert results and all(r.chunk.doc_type == "diligence" for r in results)
    experiments = recall(kb, "缩量过滤", Filters(doc_type="experiment"))
    assert experiments
    assert {r.chunk.doc_type for r in experiments} == {"experiment"}
    coded = recall(kb, "立案调查 质押", Filters(code="002456"))
    assert coded and {r.chunk.code for r in coded} == {"002456"}


def test_citations_carry_doc_and_as_of(kb: KbStore) -> None:
    lines = as_citations(recall(kb, "五日反转 为什么关闭", Filters(doc_type="experiment")))
    assert lines
    assert all(line.startswith("[qlab-") for line in lines)
    assert all("@2026-" in line.split("]")[0] for line in lines)


def test_split_blocks_and_frontmatter() -> None:
    text = (
        "---\ndoc_id: x-1\nas_of: 2026-01-02\n---\n"
        "\n# 标题\n\n## 结论\n内容一\n\n## 为什么\n内容二\n"
    )
    meta = parse_frontmatter(text)
    assert meta["doc_id"] == "x-1" and meta["as_of"] == "2026-01-02"
    blocks = split_blocks(text)
    assert [b.heading for b in blocks] == ["", "结论", "为什么"]
    assert blocks[1].body == "内容一"


def test_hash_embed_is_deterministic_and_normalized() -> None:
    first = hash_embed("缩量过滤 回撤刹车")
    assert first.shape == (256,)
    assert float(np.linalg.norm(first)) == pytest.approx(1.0)
    assert np.allclose(first, hash_embed("缩量过滤 回撤刹车"))
    assert not np.allclose(first, hash_embed("涨停炸板 次日反包"))


def test_tokenize_handles_mixed_scripts() -> None:
    tokens = tokenize("缩量过滤 edge gate 30%")
    assert "edge" in tokens and "gate" in tokens
    assert "缩" in tokens and "缩量" in tokens


def test_summary_only_conclusion_block_is_indexed(kb: KbStore) -> None:
    summary = [c for c in kb.chunks() if c.doc_id == f"SUMMARY@{DAY}"]
    assert len(summary) == 1
    assert "结论" in summary[0].text
    assert "盈亏与执行回顾" not in summary[0].text


def test_planner_ingests_at_close(golden_day: GoldenDay) -> None:
    assert golden_day.kb_added > 0
    with KbStore(golden_day.planner.settings.kb_index_path) as store:
        assert any(c.doc_id.startswith("CROSS_EXAM@") for c in store.chunks())


def test_golden_day_agent_actually_recalled(golden_day: GoldenDay) -> None:
    """记忆不是摆设：1 号实例当天确实召回过一次，并把 `[doc@as_of]` 写进了结论。"""
    archive = golden_day.planner.archive
    evidence = archive.read(GOLDEN_DATE, "EVIDENCE-decision-gpt.md")
    assert "recall" in evidence and "→ adopted" in evidence
    decision = archive.read(GOLDEN_DATE, "DECISION-gpt.md")
    assert "[qlab-0012@2026-08-29]" in decision


def test_chunk_ids_are_stable() -> None:
    text = "正文"
    first = Chunk("d-1", "600519", "summary", DAY, "结论性档案", text)
    assert first.chunk_id == Chunk("d-1", "600519", "summary", DAY, "结论性档案", text).chunk_id
    assert first.citation == f"[d-1@{DAY}]"


def test_eval_cli_reports_and_writes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    assert "recall@5" in capsys.readouterr().out
    doc = tmp_path / "EVALUATION.md"
    doc.write_text(
        "# EVALUATION\n\n| 指标 | 值 | 来源 |\n|---|---|---|\n"
        "| KB recall@5 | 待填 | x |\n| KB MRR | 待填 | x |\n",
        encoding="utf-8",
    )
    write_evaluation(Metrics(total=20, hits=18, recall_at_5=0.9, mrr=0.663), doc)
    text = doc.read_text(encoding="utf-8")
    assert "0.90" in text and "0.663" in text
    assert "待填" not in text
