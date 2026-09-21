# EVALUATION

指标由 `uv run pytest`、`uv run pytest --cov` 与 `uv run python -m duty_agent.memory.eval --write` 填出。

| 指标 | 值 | 来源 |
|---|---|---|
| 测试数 | 162 | `uv run pytest --collect-only -q` |
| 覆盖率 | 96%（engine 90–100%，agent 92–100%） | `uv run pytest --cov=duty_agent --cov=duty_engine` |
| KB recall@5 | 0.90（验收线 ≥ 0.8，18/20 命中） | `uv run python -m duty_agent.memory.eval` |
| KB MRR | 0.663 | `uv run python -m duty_agent.memory.eval` |
| 金标问题数 | 20 | `app/src/duty_agent/memory/eval_golden.json` |
| 已关闭实验轴 | 4 / 5 关闭（0008 五日反转、0012 动量五次确认、0018 TOM 复现、0024 涨停炸板） | `examples/replay-2026-09-16/fixtures/quant-lab/` |
| 保留实验轴 | 0021 缩量过滤（已落为池锁定 edge gate 的成交额门槛） | 同上 |
| 回放一致性 | `examples/replay-2026-09-16/` 27 份档案与重跑结果逐字节一致 | `test_examples_match_golden_day_replay` |

## KB 的两条未达标项说明

- 未命中的 2 条金标问题都指向 `SUMMARY@2026-09-16`：当天结论段只有一个块，
  与 `CROSS_EXAM` 的三个块在 bigram 空间里高度相似。这是语料太小造成的排序问题，
  不是索引缺陷；扩到多日语料后该现象会稀释。此处如实记录，不调金标问题来凑指标。
- 评测度量的是检索质量，因此不加元数据过滤；`filters` 强制只作用在 agent 侧的
  `recall_tool.recall`（见 `test_recall_requires_filter`）。
