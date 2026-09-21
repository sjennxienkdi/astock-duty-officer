# DECISION-LOG

规格未写的细节按「最简实现」落地并在此记一行一条。plan §0.10：规格内部矛盾取更保守一方。

| 日期 | 决策 | 理由 |
|---|---|---|
| 2026-09-21 | Python 3.11.15 由 uv 托管下载（`uv python install 3.11`），不使用系统 3.12 | plan §10 冻结 `==3.11.*`；本机无 3.11 |
| 2026-09-21 | `numpy` 计入 app 依赖 | §6 已规定 sqlite-vec「装不上则 numpy 余弦」，属该条既定回退项，非新增能力 |
| 2026-09-21 | 向量 embedding 用确定性 hash embedding（langchain-core FakeEmbeddings 语义 + numpy 余弦），不引入 embedding 服务依赖 | §10 白名单无 embedding 项，§15.11 禁真实密钥；展示模式可复现优先 |
| 2026-09-21 | `scripts/check_secrets.py` 从 M6 提前到 M1 实现 | 脱敏红线（§16）应在 M2–M6 写入 60+ 文件的过程中持续生效，而非终检才暴露 |
| 2026-09-21 | README.md / EVALUATION.md 在 M1 建立占位，README 首屏图按 §3.1 冻结原样写入 | 让 docs workflow 从 M1 起就能校验「首屏图一字不改」这条 DoD |
| 2026-09-21 | 订单十态的合法转移集按 §2.3 图示取保守最小集，`archived` 仅由终态进入 | §2.3 ASCII 图箭头错位未穷举；§0.10 取更少权限一方，矩阵在 M2 以表驱动显式钉死并被 `test_orders_full_transition_matrix` 覆盖 |
| 2026-09-21 | 仓库仅本地 `git init` + 每里程碑一次提交，不推远端；CI「绿」以本地等价命令验证 | 推远端属人工批准动作；plan §1 DoD 的 workflow 项待人工推送后由 GitHub 判定 |
| 2026-09-21 | 根 pyproject 设为 `package = false` 的 workspace host，web/tests/scripts 的依赖与工具配置集中在根 | app/engine 两 member 保持 §11 冻结结构不变 |
| 2026-09-21 | 金额单位 bps/分整数的常量与类型放在 engine，app 侧只做只读引用 | §7 引擎是唯一写库者；避免 app 侧出现第二个金额真相源 |
| 2026-09-21 | M2：`lock_pool` / `lock_plan` 保留 §7 的位置参数签名，配置与副作用出口改为关键字专用默认参数（`gate` / `cash_cents` / `alert_log` / `sizing` / `expected_tags`） | §7 冻结的是签名而非可选面；默认值 = 最少权限，调用方不传就没有告警落盘 |
| 2026-09-21 | M2：`ALERT_KINDS` 在 §4.1/§5.4/§5.5 的五类之外增加 `offpool` | §5.1「墙后无权加候选」需要可回放的落点，池外标的进票必须留痕而不是静默丢弃 |
| 2026-09-21 | M2：算仓参数 `Sizing`（单票上限 1000bps、加仓步长 500bps、减仓比例 50%、止损冻结线 300bps）作为配置常量 | §5.1 只写「聚合 → 目标仓位 bps → 触发线」未给数值；取小额保守值，且不改变任何门禁语义 |
| 2026-09-21 | M2：倍数一律用万分比表达，2.5 倍 = 25000（`MonitorConfig.volume_multiple_bps`） | §15.9 禁 float 参与运算，量能倍数也走整数轴，与 stance/仓位 bps 同一套单位 |
| 2026-09-21 | M2：`lock_plan` 在全体无有效票时短路返回空 `Plan` | §5.2「全体缺卷 → 零候选日（Plan 空）」，否则缺卷日会退化成全员持有 |
| 2026-09-21 | M2：订单 `side` 取 `buy` / `sell` 二词；卡片类型取 `morning_decision` / `intraday_proposal` / `daily_summary` / `alert` | §2 未冻结这两组标识符，按 §14「标识符用英文」命名 |
| 2026-09-21 | M2：十态中文标签表 `HUMAN_LABEL_ZH` 单源地放在 `engine/orders.py`，展示层只引用不复制 | §2.3 要求中文只出现在展示层，但五页 + 四类卡片需要同一份映射 |
| 2026-09-21 | M2：`ledger` 表不设 `position_bps` 列；仓位 bps 只存在于计划与目标里 | 账本记的是成交，bps 记的是计划，混在一列会出现第二个真相源 |
| 2026-09-21 | M2：outbox 文件名为 `{YYYYMMDDTHHMMSS}-{kind}.md` 而非 §9 的 `{ts}.md` | 同一秒内多类卡片会互相覆盖，档案只追加（§15.7）优先于字面命名 |
| 2026-09-21 | M2：`SIG-001` 命中由 app 侧置 `DecisionFile.voided`，`lock_plan` 见 voided 即整份跳过 | §11 把 sig001 放在 app、§5.1 把扫描放在计划锁定；引擎不反向依赖 app，用数据字段传门禁 |
