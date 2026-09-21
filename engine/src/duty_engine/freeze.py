"""两道冻结墙（plan §5.1）：08:20 池锁定、08:45 计划锁定。墙之后无权加候选、定仓、改触发线。"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from duty_engine.aggregate import Aggregated, Stance, aggregate, parse_stance
from duty_engine.clock import ensure_shanghai
from duty_engine.orders import Order, OrderState
from duty_engine.storage import Alert, AlertLog, require_int

# plan §5.1 硬雷浅筛四类：标识符英文、展示走中文标签
HARD_RED_FLAGS = (
    "credit_default",
    "terminated_execution",
    "case_investigation",
    "pledge_margin_line",
)
HARD_RED_LABEL_ZH: Mapping[str, str] = {
    "credit_default": "失信被执行",
    "terminated_execution": "终本",
    "case_investigation": "立案调查",
    "pledge_margin_line": "质押爆仓线",
}

_CONFIDENCE_WORDS = ("high", "medium", "low")
_DECISION_HEADING = re.compile(r"^#\s+DECISION\s*·\s*(\S+)\s*·\s*(\S+)\s*$")
_SECTION_HEADING = re.compile(r"^##\s+(\d{6})\s+(\S+)\s*$")
_FIELD = re.compile(r"^([a-z_]+):\s*(.*)$")


class Confidence(StrEnum):
    """决策置信度三词。"""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class DecisionFormatError(ValueError):
    """DECISION 文件字段缺失或越词（plan §4.5.1：缺一即整份作废）。"""


@dataclass(frozen=True)
class EdgeGate:
    """池锁定的量化门槛（plan §5.1，配置项不是判断）。"""

    min_listed_days: int = 250
    min_avg_amount_cents: int = 8_000_000_000
    exclude_st: bool = True


@dataclass(frozen=True)
class Sizing:
    """引擎算仓参数（plan 未穷举，取保守小额）。"""

    single_name_max_bps: int = 1_000
    add_step_bps: int = 500
    trim_ratio_bps: int = 5_000
    stop_loss_bps: int = 300

    def __post_init__(self) -> None:
        require_int("single_name_max_bps", self.single_name_max_bps)
        require_int("stop_loss_bps", self.stop_loss_bps)


DEFAULT_EDGE_GATE = EdgeGate()
DEFAULT_SIZING = Sizing()


@dataclass(frozen=True)
class Candidate:
    """选股候选（`CANDIDATES.md` 解析结果的一行）。"""

    code: str
    name: str
    listed_days: int
    avg_amount_cents: int
    is_st: bool
    ref_price_cents: int
    hard_red_flags: frozenset[str] = frozenset()
    note: str = ""

    def __post_init__(self) -> None:
        unknown = set(self.hard_red_flags) - set(HARD_RED_FLAGS)
        if unknown:
            raise ValueError(f"未知硬雷标记: {sorted(unknown)}")


@dataclass(frozen=True)
class Holding:
    """现有持仓。"""

    code: str
    name: str
    qty_lots: int
    cost_cents: int


@dataclass(frozen=True)
class PoolItem:
    """锁池后的单只标的。"""

    code: str
    name: str
    ref_price_cents: int
    qty_lots: int
    cost_cents: int
    hard_red_flags: frozenset[str] = frozenset()

    @property
    def held(self) -> bool:
        return self.qty_lots > 0

    def market_value_cents(self) -> int:
        return self.qty_lots * 100 * self.ref_price_cents


@dataclass(frozen=True)
class Pool:
    """08:20 冻结后的标的池。frozen：墙后无人能改。"""

    pool_version: str
    locked_at: datetime
    items: tuple[PoolItem, ...]
    cash_cents: int
    dropped: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        require_int("cash_cents", self.cash_cents)

    @property
    def codes(self) -> tuple[str, ...]:
        return tuple(item.code for item in self.items)

    def item(self, code: str) -> PoolItem | None:
        return next((i for i in self.items if i.code == code), None)

    def portfolio_cents(self) -> int:
        """账户总值 = 现金 + 池内持仓市值。"""
        return self.cash_cents + sum((i.market_value_cents() for i in self.items), start=0)


@dataclass(frozen=True)
class DecisionEntry:
    """一条 per-code stance 判断，不含任何仓位字段。"""

    code: str
    name: str
    stance: Stance
    confidence: Confidence
    dd_ref: str
    evidence: tuple[str, ...]
    reasoning: str


@dataclass(frozen=True)
class DecisionFile:
    """一份 `DECISION-{tag}.md`。`voided` 为真则整份不计票。"""

    tag: str
    as_of: datetime
    pool_version: str
    entries: tuple[DecisionEntry, ...]
    voided: bool = False
    void_reason: str = ""
    text: str = field(default="", repr=False)


@dataclass(frozen=True)
class Target:
    """计划锁定后的一只标的：目标仓位与冻结触发线。"""

    code: str
    name: str
    stance: Stance
    target_bps: int
    current_bps: int
    protect_trigger_cents: int
    conflict: bool
    votes: int

    @property
    def rebalance(self) -> bool:
        return self.target_bps != self.current_bps


@dataclass(frozen=True)
class Plan:
    """08:45 冻结后的当日计划。frozen：墙后无人能改。"""

    pool_version: str
    locked_at: datetime
    targets: tuple[Target, ...]
    orders: tuple[Order, ...] = ()
    voided_tags: tuple[str, ...] = ()
    absent_tags: tuple[str, ...] = ()

    @property
    def zero_candidate(self) -> bool:
        return not self.targets


def lock_pool(
    candidates: list[Candidate],
    holdings: list[Holding],
    at: datetime,
    *,
    gate: EdgeGate = DEFAULT_EDGE_GATE,
    cash_cents: int = 0,
    alert_log: AlertLog | None = None,
) -> Pool:
    """08:20 池锁定：持仓强制入池 → edge gate → 硬雷浅筛（规则否决，非 LLM）。"""
    moment = ensure_shanghai(at)
    holding_by_code = {h.code: h for h in holdings}
    candidate_by_code = {c.code: c for c in candidates}
    dropped: list[tuple[str, str]] = []
    items: list[PoolItem] = []
    for code in sorted(set(candidate_by_code) | set(holding_by_code)):
        holding = holding_by_code.get(code)
        candidate = candidate_by_code.get(code)
        if holding is not None:
            ref_price = candidate.ref_price_cents if candidate else _cost_price(holding)
            items.append(
                PoolItem(
                    code=code,
                    name=candidate.name if candidate else holding.name,
                    ref_price_cents=ref_price,
                    qty_lots=holding.qty_lots,
                    cost_cents=holding.cost_cents,
                    hard_red_flags=candidate.hard_red_flags if candidate else frozenset(),
                )
            )
            continue
        assert candidate is not None
        if not _passes_gate(candidate, gate):
            dropped.append((code, "edge_gate"))
            continue
        if candidate.hard_red_flags:
            reasons = "+".join(HARD_RED_LABEL_ZH[f] for f in sorted(candidate.hard_red_flags))
            dropped.append((code, f"硬雷浅筛: {reasons}"))
            if alert_log is not None:
                alert_log.emit(Alert(moment, "hard_red", code, reasons))
            continue
        items.append(
            PoolItem(
                code=code,
                name=candidate.name,
                ref_price_cents=candidate.ref_price_cents,
                qty_lots=0,
                cost_cents=0,
            )
        )
    return Pool(
        pool_version=moment.strftime("%Y-%m-%d-%H%M"),
        locked_at=moment,
        items=tuple(items),
        cash_cents=cash_cents,
        dropped=tuple(dropped),
    )


def lock_plan(
    decisions: list[DecisionFile],
    pool: Pool,
    at: datetime,
    *,
    sizing: Sizing = DEFAULT_SIZING,
    alert_log: AlertLog | None = None,
    expected_tags: tuple[str, ...] = (),
) -> Plan:
    """08:45 计划锁定：作废件不计票 → 池外码不采纳 → 聚合 → 算仓 → 触发线 → 草稿单。"""
    moment = ensure_shanghai(at)
    pool_codes = {item.code for item in pool.items}
    stances: dict[str, list[Stance]] = {code: [] for code in pool_codes}
    voided_tags: list[str] = []
    for decision in decisions:
        if decision.voided:
            voided_tags.append(decision.tag)
            if alert_log is not None:
                reason = decision.void_reason or "整份作废，本轮不计票"
                alert_log.emit(Alert(moment, "sig001", decision.tag, reason))
            continue
        if decision.pool_version != pool.pool_version:
            voided_tags.append(decision.tag)
            if alert_log is not None:
                detail = f"池版本不符 {decision.pool_version}"
                alert_log.emit(Alert(moment, "sig001", decision.tag, detail))
            continue
        for entry in decision.entries:
            if entry.code in stances:
                stances[entry.code].append(entry.stance)
            elif alert_log is not None:
                alert_log.emit(
                    Alert(moment, "offpool", entry.code, "池外标的，计划锁定后无权加候选")
                )
    absent = tuple(sorted(set(expected_tags) - {d.tag for d in decisions if not d.voided}))
    if alert_log is not None:
        for tag in absent:
            alert_log.emit(Alert(moment, "absent", tag, "08:44 前未交卷，不重试不替补"))

    aggregated: Mapping[str, Aggregated] = aggregate(stances)
    if not any(stances.values()):
        return Plan(
            pool_version=pool.pool_version,
            locked_at=moment,
            targets=(),
            orders=(),
            voided_tags=tuple(voided_tags),
            absent_tags=absent,
        )
    portfolio = pool.portfolio_cents()
    targets: list[Target] = []
    orders: list[Order] = []
    for item in pool.items:
        agg = aggregated.get(item.code)
        stance = agg.stance if agg else Stance.HOLD
        current_bps = item.market_value_cents() * 10_000 // portfolio if portfolio else 0
        target_bps = _target_bps(stance, current_bps, sizing)
        targets.append(
            Target(
                code=item.code,
                name=item.name,
                stance=stance,
                target_bps=target_bps,
                current_bps=current_bps,
                protect_trigger_cents=_protect_line(item.ref_price_cents, sizing),
                conflict=agg.conflict if agg else False,
                votes=agg.votes if agg else 0,
            )
        )
        orders.extend(_build_orders(item, target_bps, portfolio, pool.cash_cents, moment, sizing))
    return Plan(
        pool_version=pool.pool_version,
        locked_at=moment,
        targets=tuple(targets),
        orders=tuple(orders),
        voided_tags=tuple(voided_tags),
        absent_tags=absent,
    )


def parse_decision(text: str) -> DecisionFile:
    """按 plan §4.5.1 解析 DECISION 文件，字段缺一即抛 `DecisionFormatError`。"""
    lines = [line.rstrip() for line in text.splitlines()]
    if not lines:
        raise DecisionFormatError("空文件")
    heading = _DECISION_HEADING.match(lines[0])
    if heading is None:
        raise DecisionFormatError("缺标题行 `# DECISION · {date} · {tag}`")
    fields: dict[str, str] = {}
    sections: list[tuple[str, str, dict[str, list[str]]]] = []
    for line in lines[1:]:
        if match := _SECTION_HEADING.match(line):
            sections.append((match.group(1), match.group(2), {}))
            continue
        if line.startswith("  - ") and sections:
            sections[-1][2].setdefault("evidence", []).append(line[4:].strip().strip('"'))
            continue
        if match := _FIELD.match(line):
            key, value = match.group(1), match.group(2)
            if sections:
                if not (value == "" and key == "evidence"):
                    sections[-1][2].setdefault(key, []).append(value)
            else:
                fields[key] = value
    for key in ("as_of", "pool_version"):
        if not fields.get(key):
            raise DecisionFormatError(f"缺字段 {key}")
    if not sections:
        raise DecisionFormatError("缺任何 `## {code} {name}` 段")
    entries: list[DecisionEntry] = []
    for code, name, body in sections:
        for key in ("stance", "confidence", "dd_ref", "reasoning"):
            if not body.get(key):
                raise DecisionFormatError(f"{code} 缺字段 {key}")
        confidence = body["confidence"][0]
        if confidence not in _CONFIDENCE_WORDS:
            raise DecisionFormatError(f"{code} confidence 越词 {confidence!r}")
        try:
            stance = parse_stance(body["stance"][0])
        except ValueError as exc:
            raise DecisionFormatError(f"{code} {exc}") from exc
        entries.append(
            DecisionEntry(
                code=code,
                name=name,
                stance=stance,
                confidence=Confidence(confidence),
                dd_ref=body["dd_ref"][0],
                evidence=tuple(body.get("evidence", [])),
                reasoning=body["reasoning"][0],
            )
        )
    return DecisionFile(
        tag=heading.group(2),
        as_of=ensure_shanghai(datetime.fromisoformat(fields["as_of"])),
        pool_version=fields["pool_version"],
        entries=tuple(entries),
        text=text,
    )


def render_morning(plan: Plan, pool: Pool) -> str:
    """产出 `MORNING.md` 机器原文，数字一律引擎算。"""
    lines = [
        f"# MORNING · {plan.locked_at.date().isoformat()}",
        f"pool_version: {plan.pool_version}",
        f"locked_at: {plan.locked_at.isoformat()}",
        f"portfolio_cents: {pool.portfolio_cents()}",
        f"voided_tags: {', '.join(plan.voided_tags) or '无'}",
        f"absent_tags: {', '.join(plan.absent_tags) or '无'}",
        "",
    ]
    for target in plan.targets:
        lines += [
            f"## {target.code} {target.name}",
            f"stance: {target.stance}",
            f"target_bps: {target.target_bps}",
            f"current_bps: {target.current_bps}",
            f"protect_trigger_cents: {target.protect_trigger_cents}",
            f"votes: {target.votes}",
            f"conflict: {'true' if target.conflict else 'false'}",
            "",
        ]
    return "\n".join(lines).rstrip() + "\n"


def _cost_price(holding: Holding) -> int:
    if not holding.qty_lots:
        raise ValueError(f"持仓 {holding.code} 无手数且无参考价")
    return holding.cost_cents // (holding.qty_lots * 100)


def _passes_gate(candidate: Candidate, gate: EdgeGate) -> bool:
    if candidate.is_st and gate.exclude_st:
        return False
    return (
        candidate.listed_days >= gate.min_listed_days
        and candidate.avg_amount_cents >= gate.min_avg_amount_cents
    )


def _target_bps(stance: Stance, current_bps: int, sizing: Sizing) -> int:
    if stance is Stance.CLEAR:
        return 0
    if stance is Stance.TRIM:
        return current_bps * sizing.trim_ratio_bps // 10_000
    if stance is Stance.HOLD:
        return current_bps
    if stance is Stance.ADD:
        return min(current_bps + sizing.add_step_bps, sizing.single_name_max_bps)
    return sizing.single_name_max_bps


def _protect_line(ref_price_cents: int, sizing: Sizing) -> int:
    return ref_price_cents * (10_000 - sizing.stop_loss_bps) // 10_000


def _build_orders(
    item: PoolItem,
    target_bps: int,
    portfolio_cents: int,
    cash_cents: int,
    at: datetime,
    sizing: Sizing,
) -> list[Order]:
    """目标与现仓之差换成草稿单；不足 1 手零订单，越风控线的单直接 rejected。"""
    current_bps = item.market_value_cents() * 10_000 // portfolio_cents if portfolio_cents else 0
    if target_bps == current_bps or portfolio_cents <= 0:
        return []
    delta_bps = target_bps - current_bps
    qty_lots = abs(delta_bps) * portfolio_cents // 10_000 // (item.ref_price_cents * 100)
    if delta_bps < 0:
        qty_lots = min(qty_lots, item.qty_lots)
        side = "sell"
    else:
        side = "buy"
    if qty_lots < 1:
        return []
    amount_cents = qty_lots * 100 * item.ref_price_cents
    within_cap = target_bps <= sizing.single_name_max_bps
    affordable = side == "sell" or amount_cents <= cash_cents
    return [
        Order(
            order_id=f"{item.code}-{at.strftime('%H%M')}-{side}",
            trade_date=at.date(),
            code=item.code,
            name=item.name,
            side=side,
            state=OrderState.APPROVED if within_cap and affordable else OrderState.REJECTED,
            qty_lots=qty_lots,
            limit_cents=item.ref_price_cents,
            amount_cents=amount_cents,
        )
    ]
