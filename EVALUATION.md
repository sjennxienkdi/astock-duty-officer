# EVALUATION

本文件由 CI 与 `memory/eval.py` 输出填充（plan §6 / §12 M4、M6）。骨架阶段为占位。

| 指标 | 值 | 来源 |
|---|---|---|
| 测试数 | 待填 | `uv run pytest --collect-only -q` |
| 覆盖率 | 待填 | `uv run pytest --cov` |
| KB recall@5 | 待填（验收线 ≥ 0.8） | `uv run python -m duty_agent.memory.eval` |
| KB MRR | 待填 | 同上 |
| 已关闭实验轴 | 待填 | `examples/replay-2026-09-16/fixtures/quant-lab/` |
