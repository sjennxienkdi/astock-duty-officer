# Changelog

本项目遵循 Keep a Changelog 与语义化版本。规格依据 `plan.md`，逐条决策见 `DECISION-LOG.md`。

## [0.1.0] - 2026-09-21

参考实现首次成型：M1–M6 全部落地，162 条测试、覆盖率 96%、ruff 与 mypy strict 零告警。

### Added

- **M1 骨架**：uv workspace（根 host + `duty-agent` / `duty-engine` 两 member）、目录结构、
  ARCHITECTURE / SAFETY / EVALUATION / DECISION-LOG / CHANGELOG / LICENSE(MIT) / .env.example、
  `ci` / `lint` / `docs` 三个 workflow、pre-commit 配置、`scripts/check_secrets.py` 脱敏守卫、
  `scripts/check_diagram.py` 主链图一致性守卫。
- **M2 确定性引擎**：storage（orders/ledger/alerts 三表 + 只追加档案 + AlertLog 双写）、
  ledger（整数分与整数 bps）、orders（十态表驱动转移矩阵）、clock（§3.2 节奏表 + 虚拟时钟）、
  freeze（08:20 池锁定 / 08:45 计划锁定 + DECISION 解析 + MORNING 渲染）、aggregate（stance 聚合
  与冲突回落）、monitor（盘中三判定 + 调频）、push_dispatcher（四类卡片限次与 outbox 回退）。
- **M3 agent 层**：graph（deepagents 装配、六个白名单工具、cassette 驱动的展示模型、
  文件级读取门禁）、planner（一天的编排、收卷与作废、盘中护栏、确认链）、config（配额与阈值）、
  七个角色模块、四个护栏模块（sig001 / hard_red / source_adjudicator / intent_guard）、
  `examples/replay-2026-09-16/` 的 27 份可逐字节重跑的全天档案与 fixtures。
- **M4 研究记忆**：store（BM25 + sqlite-vec/numpy 双路 + RRF 融合）、ingest（`##` 分块、
  frontmatter、time-bound 排除、SUMMARY 只取结论段）、recall_tool（强制 metadata filter）、
  eval + 20 条金标集（recall@5 0.90 / MRR 0.663）。
- **M5 输出面**：值班台五页（值班台 / 全天回放 / 人工确认 / 研究记忆 / 评测）、
  四类企业微信卡片模板与通道、卡片分发链与 §9 限次、`.streamlit/config.toml` 绑定本机回环。
- **M6 收尾**：README 三段叙事与徽章、`docs/demo-script.md` 三分钟动线、examples 回放校验、
  脱敏终检。

### Fixed

- 硬雷浅筛曾把「未触及爆仓线」判成命中并误移池（现按否定词判定）。
- cassette 一个回合内的并行工具调用导致取证日志行序不确定、Windows 上追加掉行
  （现单调用回合 + 进程内写锁）。
- 档案与 outbox 在 Windows 下写成 CRLF，与 git checkout 的 LF 不一致，
  使 examples 逐字节比对必然漂移（现统一强制 LF）。
- KB 哈希原先使用内置 `hash()`，受 PYTHONHASHSEED 随机化会让隔天索引失效（现用 crc32）。

### Security

- 不实跑、不接券商、不联网拉真实行情；LLM 走 `FakeChatModel` + cassette。
- 值班台默认只监听 `127.0.0.1`：确认页是唯一放行口且无鉴权。
- 全仓脱敏扫描在 CI 与本地 pre-commit 双跑。
