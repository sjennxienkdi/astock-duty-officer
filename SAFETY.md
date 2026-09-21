# SAFETY

本系统的安全模型只有一句话：**模型负责提出，确定性代码负责允许，人负责放行。**
下面每条红线都有对应的代码落点和覆盖测试，不是承诺而是断言。

## 1. 红线（违反即返工）

1. 自动下单 / 接券商通道 / 实现任何跳过确认的 `execute_protective_path` 类接口
2. LLM 输出或推送卡片出现仓位字段（数量 / 价格 / 仓位 / 限价 / 止损 / 手数 / 金额）
3. RAG 检索行情或新闻
4. intraday 窗口引入新码
5. agent 挂钟（所有定时归 engine / cron）
6. 微信卡片内确认按钮
7. 删档案 / 覆盖历史档案（只追加；作废用 `.REJECTED` 后缀）
8. 依赖白名单（`plan.md` §10）之外加依赖
9. float 参与金额运算
10. 改 §2 任何冻结名（角色代号 / 档案文件名 / 状态机状态 / stance 词表）
11. 联网拉真实行情 / 使用真实密钥（展示模式全 fixture）
12. 为「看起来完整」而加规格外功能

## 2. 威胁模型

| # | 威胁 | 失效模式 | 防线 | 落点 | 覆盖测试 |
|---|---|---|---|---|---|
| T1 | 模型把「数字」说进判断里 | 幻觉出的仓位/限价被下游当成事实 | SIG-001 正则扫描，命中**整份文件作废**（改名 `.REJECTED` + `ALERT.md` + 本轮不计票），不是删行放行 | `guardrails/sig001.py` | `test_lock_plan_sig001_rejects_whole_file` |
| T2 | 多实例回声室 | 决策互相抄，N 个实例退化成 1 个观点 | 决策实例禁互读；复核**禁读** `DECISION-*.md`（防锚定） | `agents/decision.py` `agents/review.py` | `test_decision_no_cross_read` `test_review_cannot_read_decision` |
| T3 | 跨日锚定 | 把昨天的结论当今天的事实召回 | KB 不收 time-bound 档案（`DECISION-*` `CANDIDATES.md` `PACK.md` `EVENT-INDEX.md`） | `memory/ingest.py` | `test_ingest_excludes_time_bound_docs` |
| T4 | 证据污染 | 过期 / 无来源的说法进入结论 | 每条进结论的证据须带 `[source@time]`；资讯类证据超 3 个交易日判 rejected；配额耗尽只能打 `LOW_INFO`，不许编 | `guardrails/source_adjudicator.py` | `test_evidence_appended_per_tool_call` |
| T5 | 越权放行 | 定时任务 / 子代理 / 微信文本里的「请确认」被当成用户授权 | confirm 必须携带存在于**真实用户轮次**记录里的 `intent_id`；卡片只给链接不给按钮 | `guardrails/intent_guard.py` | `test_intent_guard_rejects_non_user_turn` `test_card_has_no_confirm_button` `test_confirm_page_creates_user_turn` |
| T6 | 竞态改单 | 截止后交卷、锁定后加候选 | 08:44 后不计票；08:20 / 08:45 两道墙之后 `Pool` / `Plan` 为 frozen dataclass，代码层无权改 | `engine/freeze.py` | `test_decision_late_submission_not_counted` |
| T7 | 盘中失控 | 大波动时 agent 自作主张买新码 | 规则触发（非 LLM 触发）才激活；intraday 仅限已持仓 / 已冻结未成交；同标的 ≤2 次/日、全局 ≤4 次/日，超限只写 ALERT | `engine/monitor.py` `agents/decision.py` | `test_intraday_forbids_new_code` `test_intraday_cooldown_limits` |
| T8 | 软否决变硬否决 | 背调越权直接踢掉候选 | `diligence` **无否决权**：只打 `hard_red=true` 标记，是否移池由引擎浅筛按规则在次日池锁定执行 | `guardrails/hard_red.py` `engine/freeze.py` | `test_lock_pool_hard_red_veto` |
| T9 | 静默丢持仓 | 串行漏斗把「卖出」吃掉——持仓股选股没选中就永远不被判断 | 持仓股**强制入池，不可剔除**，edge gate 与浅筛均不生效 | `engine/freeze.py` | `test_lock_pool_holdings_forced_in` `test_screener_holdings_forced_in` |
| T10 | 金额精度漂移 | float 累加造成分位误差 | 内部一律整数分（`amount_cents`）、仓位整数 bps（`position_bps`），mypy + 断言双拦 | `engine/ledger.py` | `test_ledger_cents_only` |
| T11 | 状态机被绕过 | 未确认直接 submitted、已成交回退 draft | 十态表驱动转移矩阵，非法转移抛 `IllegalTransition` | `engine/orders.py` | `test_orders_full_transition_matrix` `test_orders_illegal_transition_raises` |
| T12 | 盯盘事后归因 | 模型给波动编一个原因，污染复盘 | 零归因硬规则：只记现象不解释原因，不调用任何 LLM 取证工具 | `agents/watch.py` | `test_watch_zero_attribution` |
| T13 | 卡片数字与引擎不一致 | 展示层自己算了一遍数 | 数字一律 engine 出，agent 文字一律标「评论」 | `notify/cards.py` | `test_card_numbers_from_engine_only` |
| T14 | 密钥 / 真实账户泄露 | 仓库公开即泄露 | 全仓正则扫描（key / token / webhook / 含用户名的绝对路径），`.env` 不入库，示例值白名单 | `scripts/check_secrets.py` | `test_smoke` 调用 + CI |

## 3. 为什么 RAG 不用于行情与新闻

结论：**KB 只做「跨日结论与方法论」的检索，实时事实一律走单源 snapshot。** 三个理由：

1. **两个真相源问题。** 价格必须单源、可审计、可复现。一旦允许从向量库召回价格，就存在
   「索引里的价格」和「快照里的价格」两个版本，而对账只认后者。
2. **语义相似 ≠ 时间正确。** 向量检索对「同一标的、不同交易日」几乎没有区分度——问「600519 现在
   能不能加」，最容易召回的恰恰是上周那条相似结论。这是幻觉里最危险的一类：它读起来像证据。
3. **召回集不可复现。** top-k 依赖索引状态，而下单路径要求逐字节可回放。

所以 RAG 用在哪：**背调档案（`DD/**`）、日报结论段、对垒复盘、已关闭的实验轴**——这些本来就是
跨日语义，且下游可不用。行情走 `quote_snapshot`（fixture 腾讯源），新闻走 `EVENT-INDEX.md`，
两者都在主链旁挂，都不进 KB。

## 4. 人工确认链

```
engine 算出订单(draft) → 风控通过(approved) → 微信决策卡【只含链接】
   → 人在 Web Confirm 页提交 → 产生一条真实用户轮次(intent_id)
   → intent_guard.verify(intent_id) 通过 → queued → 人工提交 → submitted → 回填
```

`approved` 在人看的界面写「风控通过，待人工确认」，`queued` 写「已确认，待提交」。
两个状态之间必须有一次真实用户轮次，这是代码断言而不是流程约定。

## 5. 失败处理原则

- **不重试、不替补**：某角色 08:44 未交卷 → 记 `ALERT.md` kind=absent，缺卷实例不计票；全体缺卷
  → 零候选日（Plan 为空），系统安静地什么都不做。
- **降级要留痕**：配额耗尽 / 信息不足 → 打 `LOW_INFO`，而不是给一个看起来完整的答案。
- **作废要响亮**：SIG-001 命中、硬雷命中、冷却超限 → 全部落 `ALERT.md` 并可被 Replay 页回放。
