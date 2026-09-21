"""角色规格表（plan §4）：每个角色 = 一份提示词 + 一份权限/输出声明。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RoleSpec:
    """一个角色的静态声明。权限由 `graph.permissions_for` 编译成 deepagents 规则。"""

    role: str
    describe: str
    outputs: tuple[str, ...]
    tools: tuple[str, ...] = ()
    read_deny: tuple[str, ...] = ()
    write_deny_all: bool = True
    prompt: str = ""


# 通用约束（plan §4 前言）：取证自由、每次调用落 EVIDENCE、禁读他人结论、输出禁仓位字段。
COMMON_RULES = """通用约束：
1. 取证自由但有配额：工具用完配额后只能基于已有信息作答，并在末尾打 LOW_INFO，不许编。
2. 每次工具调用由系统追加一行到 EVIDENCE-{role}.md，你不需要自己写。
3. 进入结论的每条证据必须写成 [source@YYYY-MM-DD] 形式，来源须在白名单内。
4. 输出严禁出现数量、手数、价格、限价、止损、仓位、敞口、金额、预算等任何字段——
   命中 SIG-001 即整份作废。你只产 stance 与理由，仓位由引擎算。
5. 只写属于你的档案文件，其余一律只读。
"""


def prompt_for(role: str, body: str) -> str:
    """拼装角色系统提示词。"""
    return f"你是 A股值班台的「{role}」角色。\n{body}\n{COMMON_RULES.replace('{role}', role)}"


@dataclass
class RoleRun:
    """一次角色运行的产出记录。"""

    role: str
    wrote: list[str] = field(default_factory=list)
    low_info: bool = False
    replies: list[str] = field(default_factory=list)
