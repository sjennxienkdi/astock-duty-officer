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
| 2026-09-21 | M3：展示模式用 cassette（`fixtures/agents/*.json`）驱动 `FakeChatModel`，图/权限/配额/EVIDENCE/引擎门禁全部真实执行，只有判断内容由录制回放提供 | §15.11 禁真实密钥 + §10 白名单无真实模型；等价于 VCR 回放，且是 `test_golden_day_*` 逐字节可重跑的前提 |
| 2026-09-21 | M3：禁互读落在 deepagents `FilesystemPermission`（deny read 他人结论），不是提示词约定 | §4 的「禁互读 / 复核禁读 DECISION」必须可被测试证伪；已在 `test_decision_no_cross_read` `test_review_cannot_read_decision` 断言工具返回 permission-denied |
| 2026-09-21 | M3：内置 `write_file` / `edit_file` / `delete` 同属 write 操作，整体 deny；交卷只能走 `submit_archive`（文件名白名单 + 只追加） | §15.7「不删档、不覆盖」在工具层成立，而不是靠约定；`delete` 属于写操作是 deepagents 的实现事实，顺势关掉 |
| 2026-09-21 | M3：`CANDIDATES.md` 只含标的与理由，edge gate 用的上市天数/成交额/ST 由引擎从数据源适配器取 | §15.2 禁 LLM 输出金额类字段；让判断层产数字会同时踩红线和产生第二个真相源 |
| 2026-09-21 | M3：SIG-001 的 `\b` 换成 `(?![0-9])`（`test_sig001_catches_cjk_without_word_boundary`） | `re` 下汉字与 `股`/`手` 同为 `\w`，「300股票」这类写法 `\b` 不成立会漏检；改后仍只匹配数字+单位 |
| 2026-09-21 | M3：硬雷浅筛加否定检测（关键词前 3 字出现 未/无/不 即未命中） | 「未触及爆仓线」曾被判成命中并误移池；浅筛是规则否决，假阳性等于替 LLM 说了不存在的结论 |
| 2026-09-21 | M3：cassette 每回合只放一个工具调用；档案追加加进程内写锁 | 并行工具调用让 `EVIDENCE-*.md` 行序不确定、Windows 上并发追加会掉行；回放型项目必须逐字节可重跑（`test_golden_day_is_byte_reproducible`） |
| 2026-09-21 | M3：`EVIDENCE-{role}.md` 只记白名单取证工具调用，档案内 `read_file` 导航不记 | §5.3 的门槛针对外部来源；`director` 不取证因此没有 EVIDENCE 档，不是漏写 |
| 2026-09-21 | M3：`Planner` 持 `VirtualClock` 并以 `stage(定时槽名)` 推进，代替固定「现在」 | EVIDENCE 与 ALERT 的时间戳要落回 §3.2 的真实节奏；agent 不挂钟（§15.5），推进动作本身仍由引擎时钟对象执行 |
| 2026-09-21 | M3：复核实例 tag 取 `deepseek`（`REVIEW-deepseek.md`） | §2.2 冻结的是 `REVIEW-{tag}.md` 模板，tag 本身未冻结；与决策三实例区分开以便 Replay 页展示 |
| 2026-09-21 | M3：`examples/replay-2026-09-16/` 的 27 份全天档案由代码跑出来的，并由 `test_examples_match_golden_day_replay` 钉住 | 手写示例档案必然与实现漂移；DoD 要求 Replay 页能完整回放，先保证它是真产物 |
