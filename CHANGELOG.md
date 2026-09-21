# Changelog

本项目遵循 Keep a Changelog 格式。

## [Unreleased]

### Added
- M1：uv workspace 骨架（`app` + `engine` 两 member）、目录结构、ARCHITECTURE / SAFETY /
  DECISION-LOG / .env.example / LICENSE(MIT) / CHANGELOG.md、三个 GitHub Actions workflow、
  pre-commit 配置、`scripts/check_secrets.py` 脱敏守卫、`tests/test_smoke.py`。
- M2：确定性引擎 `duty_engine` 八个模块——storage（三表 + 只追加档案 + AlertLog 双写）、
  ledger（整数分 / 整数 bps）、orders（十态表驱动转移矩阵）、clock（§3.2 节奏表 + 虚拟时钟）、
  freeze（08:20 池锁定 / 08:45 计划锁定 + DECISION 解析 + MORNING 渲染）、aggregate（stance
  聚合与冲突回落）、monitor（盘中三判定 + 调频）、push_dispatcher（四类卡片限次与 outbox 回退）。
- M3：agent 层 `duty_agent`——graph（deepagents 装配、六个白名单工具、cassette 驱动的展示模型、
  文件级读取门禁）、planner（§3.2 编排、收卷与作废、盘中护栏、确认链）、config（配额/阈值/时刻）、
  七个角色模块、四个 guardrail 模块（sig001 / hard_red / source_adjudicator / intent_guard）。
  `examples/replay-2026-09-16/` 落地 27 份可逐字节重跑的全天档案与 fixtures。
- M4：研究记忆 KB——store（BM25 + sqlite-vec/numpy 双路 + RRF 融合）、ingest（`##` 分块、
  frontmatter、time-bound 排除、SUMMARY 只取结论段）、recall_tool（强制 `doc_type` 或 `code`
  过滤）、eval + 20 条金标集（recall@5 0.90 / MRR 0.663），决策实例当天真实召回并引用结题卡。
