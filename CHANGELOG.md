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
