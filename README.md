# A股值班台 · Deep Agents 多智能体参考实现

```mermaid
flowchart TD
    A["📰 资讯索引 + 📚 研究记忆 KB<br/>旁挂 · 可读可不用"]
    B["🔎 选股 Agent<br/>T-1 夜深研究 + T 晨修正<br/>持仓股强制入池"]
    C["🧨 背调 Agent<br/>新码触发 · 报告供参考 · 无否决权"]
    D{{"🧊 池锁定 08:20<br/>硬雷浅筛（规则否决）"}}
    E["📡 决策 Agents ×N<br/>08:44 交卷 · stance 五词 · 禁互读"]
    F{{"🧊 计划锁定 08:45<br/>SIG-001 · 引擎算仓"}}
    G["⚙️ 引擎 + 👁 盯盘<br/>盘中三判定 · 大波动反应环"]
    H{"👤 人工确认<br/>intent_id 真实轮次"}
    I["📁 当天档案 · 🖥 Web 值班台 · 💬 企业微信"]

    A -.-> B
    B --> D
    B -. 新码 .-> C
    C -. 参考 .-> E
    D --> E --> F --> G --> H --> I
```

> 研究在盘后、决策在盘前、执行保护在盘中、复盘在盘后。
> **LLM 只产判断不碰钱，每笔订单人工确认，全过程落档案、可回放、可检索。**

M1 骨架阶段：完整叙事、徽章与演示动线在 M6 收尾时补齐。
现在可读的文档：[ARCHITECTURE.md](ARCHITECTURE.md) · [SAFETY.md](SAFETY.md) ·
[DECISION-LOG.md](DECISION-LOG.md) · [规格原文 plan.md](plan.md)

## 免责声明

本项目是**架构参考实现**，不实跑、不接券商、不联网拉真实行情；数据源全部为脱敏 fixture，
LLM 走 `FakeChatModel`。文中任何标的、代码、数字均为示例，不构成投资建议。
