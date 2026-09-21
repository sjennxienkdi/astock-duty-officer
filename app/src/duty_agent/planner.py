"""派活顺序（plan §3.2）：角色只产档案，引擎负责门禁与算仓。"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from typing import Any

from duty_agent.agents import RoleRun, RoleSpec
from duty_agent.config import Settings
from duty_agent.graph import RecallFn, RunContext, run_role
from duty_agent.guardrails.hard_red import scan_dd
from duty_agent.guardrails.intent_guard import TurnLedger, verify
from duty_agent.guardrails.sig001 import hits, scan
from duty_agent.guardrails.source_adjudicator import QuotaMeter
from duty_agent.memory.ingest import ingest
from duty_agent.memory.store import KbStore
from duty_agent.notify.cards import CardRenderer
from duty_engine.aggregate import Stance
from duty_engine.clock import SCHEDULE, TZ_SHANGHAI, VirtualClock
from duty_engine.freeze import (
    Candidate,
    DecisionFile,
    Holding,
    Plan,
    Pool,
    parse_decision,
    render_morning,
)
from duty_engine.freeze import lock_plan as engine_lock_plan
from duty_engine.freeze import lock_pool as engine_lock_pool
from duty_engine.monitor import MonitorConfig, Snapshot, judge
from duty_engine.orders import (
    IllegalTransition,
    Order,
    OrderState,
    can_transition,
    save,
    transition,
)
from duty_engine.push_dispatcher import (
    ALERT_CARD,
    DAILY_SUMMARY,
    INTRADAY_PROPOSAL,
    MORNING_DECISION,
    DispatchResult,
    PushDispatcher,
    PushEvent,
)
from duty_engine.storage import Alert, AlertLog, Archive, Store

_PICKED = re.compile(r"^##\s+(\d{6})\s+(\S+)\s*$")
_PICK_FIELD = re.compile(r"^(held|dd_ref|note|low_info)\s*[:：]\s*(.*)$")
_DEADLINE = next(entry for entry in SCHEDULE if entry.name == "decision_deadline")


@dataclass(frozen=True)
class Picked:
    """`CANDIDATES.md` 里的一行——只有判断，没有数字。"""

    code: str
    name: str
    held: bool
    dd_ref: str
    note: str
    low_info: bool


def parse_candidates(text: str) -> tuple[Picked, ...]:
    """解析选股终稿。edge gate 用的事实不在这儿，由引擎从数据源取。"""
    rows: list[Picked] = []
    code = name = ""
    fields: dict[str, str] = {}

    def flush() -> None:
        if code:
            rows.append(
                Picked(
                    code=code,
                    name=name,
                    held=fields.get("held", "false") == "true",
                    dd_ref=fields.get("dd_ref", "无背调"),
                    note=fields.get("note", ""),
                    low_info=fields.get("low_info", "false") == "true",
                )
            )

    for line in text.splitlines():
        stripped = line.strip()
        if match := _PICKED.match(stripped):
            flush()
            code, name = match.group(1), match.group(2)
            fields = {}
        elif match := _PICK_FIELD.match(stripped):
            fields[match.group(1)] = match.group(2)
    flush()
    return tuple(rows)


def deadline_of(day: date) -> datetime:
    """决策截止时刻（08:44）。"""
    return _DEADLINE.occurs_on(day)


@dataclass
class IntradayBudget:
    """盘中提案冷却（plan §4.5）。"""

    per_code: int
    global_max: int
    used_per_code: dict[str, int] = field(default_factory=dict)
    used_global: int = 0

    def take(self, code: str) -> tuple[bool, str]:
        if self.used_global >= self.global_max:
            return False, f"全局冷却：已达 {self.global_max} 次/日"
        if self.used_per_code.get(code, 0) >= self.per_code:
            return False, f"同标的冷却：{code} 已达 {self.per_code} 次/日"
        self.used_per_code[code] = self.used_per_code.get(code, 0) + 1
        self.used_global += 1
        return True, "ok"


@dataclass
class Planner:
    """一天的编排者：自己不判断，只按时刻表把角色与引擎串起来。"""

    settings: Settings
    store: Store
    archive: Archive
    clock: VirtualClock
    alert_log: AlertLog
    dispatcher: PushDispatcher

    @property
    def now(self) -> datetime:
        return self.clock.now()

    def stage(self, name: str) -> datetime:
        """把时钟推到某个定时槽，让 EVIDENCE 与 ALERT 的时间戳落在真实节奏上。"""
        return self.clock.set(self._slot(name))

    def collect_pack(self, day: date) -> str:
        """`PACK.md` 采集：确定性脚本，无 LLM。来源分级表是配置不是判断。"""
        snap = self._snapshot(day)
        panel = self._fixture("financial/ifind_panel.json")
        flags = self._fixture("dd/tianyancha.json")
        kline = self._fixture("quote/kline_5d.json")
        news = self._fixture("search/news.json")
        lines = [
            f"# PACK · {day.isoformat()}",
            "produced_by: planner.collect_pack（脚本 · 无 LLM）",
            f"as_of: {self.now.isoformat()}",
            "tiers: 交易所/公告 > iFinD > 天眼查 > 垂搜",
            "",
            "## 行情快照（腾讯源）",
            "| code | name | price_cents | prev_close_cents | volume_lots |",
            "|---|---|---|---|---|",
        ]
        for code, row in sorted(snap.items()):
            lines.append(
                f"| {code} | {row['name']} | {row['price_cents']}"
                f" | {row['prev_close_cents']} | {row['volume_lots']} |"
            )
        lines += [
            "",
            "## 财务面板（iFinD）",
            "| code | listed_days | avg_amount_cents | is_st |",
            "|---|---|---|---|",
        ]
        for code, row in sorted(panel.items()):
            lines.append(
                f"| {code} | {row['listed_days']} | {row['avg_amount_cents']} | {row['is_st']} |"
            )
        lines += ["", "## 工商与司法（天眼查）"]
        for code, row in sorted(flags.items()):
            lines.append(f"- {code}: " + "；".join(f"{k}={v}" for k, v in row.items()))
        lines += ["", "## 5 日均量（掘金）"]
        for code, row in sorted(kline.items()):
            lines.append(f"- {code}: vma5_lots={row['vma5_lots']}")
        lines += ["", "## 资讯命中（垂搜）"]
        for row in news:
            lines.append(f"- [{row['date']}] {row['code']} {row['title']}")
        text = "\n".join(lines).rstrip() + "\n"
        if self.archive.exists(day, "PACK.md"):
            self.archive.append(day, "PACK.md", text)
        else:
            self.archive.write_once(day, "PACK.md", text)
        return text

    def run_context(
        self, spec: RoleSpec, day: date, *, recall: RecallFn | None = None
    ) -> RunContext:
        quota = self.settings.quota
        return RunContext.build(
            role=spec.role,
            day=day,
            fixtures=self.settings.examples_dir / "fixtures",
            archive=self.archive,
            quota=QuotaMeter(
                {
                    "ifind_panel": quota.ifind,
                    "vertical_search": quota.vertical_search,
                    "gm_kline": quota.gm_kline,
                }
            ),
            clock=lambda: self.now,
            recall=recall,
        )

    def run_role(
        self,
        spec: RoleSpec,
        day: date,
        *,
        ask: str,
        cassette: str | None = None,
        recall: RecallFn | None = None,
    ) -> RoleRun:
        """跑一个角色到交卷。cassette 默认与角色同名。"""
        path = self.settings.examples_dir / "fixtures" / "agents" / f"{cassette or spec.role}.json"
        return run_role(
            spec,
            self.run_context(spec, day, recall=recall),
            path,
            root_dir=self.archive.daily_dir(day),
            ask=ask,
        )

    def build_candidates(self, day: date) -> list[Candidate]:
        """CANDIDATES 的判断 + 数据源的事实 + DD 报告的硬雷标记 = 引擎输入。"""
        facts = self._fixture("financial/ifind_panel.json")
        snapshot = self._snapshot(day)
        out: list[Candidate] = []
        for pick in parse_candidates(self.archive.read(day, "CANDIDATES.md")):
            row = facts.get(pick.code)
            if row is None:
                raise ValueError(f"数据源缺少 {pick.code} 的 edge gate 事实")
            out.append(
                Candidate(
                    code=pick.code,
                    name=pick.name,
                    listed_days=_int(row, "listed_days"),
                    avg_amount_cents=_int(row, "avg_amount_cents"),
                    is_st=bool(row["is_st"]),
                    ref_price_cents=_int(snapshot[pick.code], "price_cents"),
                    hard_red_flags=self._dd_flags(day, pick.code),
                    note=pick.note,
                )
            )
        return out

    def holdings(self) -> list[Holding]:
        """当前持仓表（fixture）。"""
        return [
            Holding(
                code=r["code"], name=r["name"], qty_lots=r["qty_lots"], cost_cents=r["cost_cents"]
            )
            for r in self._fixture("holdings.json")
        ]

    def lock_pool(self, day: date) -> Pool:
        pool = engine_lock_pool(
            self.build_candidates(day),
            self.holdings(),
            self._slot("lock_pool"),
            gate=self.settings.edge_gate,
            cash_cents=self._cash_cents(),
            alert_log=self.alert_log,
        )
        return pool

    def collect_decisions(self, day: date, pool: Pool, tags: tuple[str, ...]) -> list[DecisionFile]:
        """收卷：格式不齐 / SIG-001 命中 / 08:44 后交卷，一律整份作废且不计票。"""
        collected: list[DecisionFile] = []
        for tag in tags:
            name = f"DECISION-{tag}.md"
            if not self.archive.exists(day, name):
                continue
            text = self.archive.read(day, name)
            try:
                parsed = parse_decision(text)
            except ValueError as exc:
                reason = f"格式不合格: {exc}"
                collected.append(
                    DecisionFile(
                        tag=tag,
                        as_of=self.now,
                        pool_version=pool.pool_version,
                        entries=(),
                        voided=True,
                        void_reason=reason,
                    )
                )
                self._void(day, name, tag, reason)
                continue
            found = scan(text)
            reason = f"SIG-001 命中 {found}: {hits(text)}" if found else ""
            if not reason and parsed.as_of > deadline_of(day):
                reason = f"迟交 {parsed.as_of.strftime('%H:%M')}，截止 08:44"
            if reason:
                collected.append(replace(parsed, voided=True, void_reason=reason))
                self._void(day, name, tag, reason)
            else:
                collected.append(parsed)
        return collected

    def lock_plan(self, day: date, pool: Pool, tags: tuple[str, ...]) -> Plan:
        plan = engine_lock_plan(
            self.collect_decisions(day, pool, tags),
            pool,
            self._slot("lock_plan"),
            sizing=self.settings.sizing,
            alert_log=self.alert_log,
            expected_tags=tags,
        )
        self.archive.write_once(day, "MORNING.md", render_morning(plan, pool))
        for order in plan.orders:
            save(self.store, order, self.now)
        return plan

    def monitor_round(
        self, plan: Plan, day: date, config: MonitorConfig | None = None
    ) -> list[str]:
        """引擎侧三判定：命中即写 ALERT。只记现象，一个字都不归因。"""
        cfg = config or self.settings.monitor
        vma5 = {
            code: _int(row, "vma5_lots")
            for code, row in self._fixture("quote/kline_5d.json").items()
        }
        triggered: list[str] = []
        for code, row in self._snapshot(day).items():
            verdict = judge(
                Snapshot(
                    code=code,
                    name=str(row["name"]),
                    at=self.now,
                    price_cents=_int(row, "price_cents"),
                    volume_lots=_int(row, "volume_lots"),
                    prev_close_cents=_int(row, "prev_close_cents"),
                ),
                plan,
                vma5,
                cfg,
            )
            if verdict is not None:
                triggered.append(code)
                self.alert_log.emit(Alert(self.now, "volatility", code, verdict.detail))
        return triggered

    def intraday_proposal(self, plan: Plan, budget: IntradayBudget, code: str) -> tuple[bool, str]:
        """盘中提案护栏：仅限已持仓 / 已冻结未成交，再冷却；SIG-001 与人工确认照旧。"""
        eligible = {target.code for target in plan.targets} | {order.code for order in plan.orders}
        if code not in eligible:
            self.alert_log.emit(Alert(self.now, "offpool", code, "盘中提案引入新码"))
            return False, "盘中窗口禁止引入新码"
        granted, reason = budget.take(code)
        if not granted:
            self.alert_log.emit(Alert(self.now, "cooldown", code, reason))
        return granted, reason

    def backup_and_ingest(self, day: date, kb: KbStore) -> int:
        """15:30：把当日结论性档案增量写入 KB（plan §3.2 / §6）。"""
        self.stage("backup_and_ingest")
        return ingest(
            kb,
            self.archive.daily_dir(day),
            self.settings.examples_dir / "fixtures" / "quant-lab",
            day.isoformat(),
        )

    def push_morning(self, day: date, plan: Plan, pool: Pool) -> DispatchResult:
        """08:45 计划锁定后发早盘决策卡（plan §9，1/日）。"""
        numbers: dict[str, int] = {
            "账户总值_分": pool.portfolio_cents(),
            "订单数": len(plan.orders),
        }
        facts: list[str] = []
        for target in plan.targets:
            numbers[f"{target.code}_目标bps"] = target.target_bps
            numbers[f"{target.code}_触发线_分"] = target.protect_trigger_cents
            tail = "，极差≥2 已回落中性" if target.conflict else ""
            facts.append(f"{target.code} {target.name}：{target.stance}（{target.votes} 票{tail}）")
        facts += [f"移池淘汰 {code}：{reason}" for code, reason in pool.dropped]
        comments = tuple(
            line
            for code in sorted({order.code for order in plan.orders})
            for line in self.stance_summaries(day, code)
        )
        return self._dispatch(
            MORNING_DECISION, f"{day.isoformat()} 计划已锁定", numbers, comments, tuple(facts)
        )

    def push_proposal(self, plan: Plan, code: str, stance: Stance, reason: str) -> DispatchResult:
        """盘中提案卡（plan §9，≤4/日）。触发原因来自引擎判定，不是 agent 叙述。"""
        target = next((t for t in plan.targets if t.code == code), None)
        numbers: dict[str, int] = (
            {}
            if target is None
            else {"现仓_bps": target.current_bps, "冻结触发线_分": target.protect_trigger_cents}
        )
        title = f"{code} 盘中提案：{stance}"
        return self._dispatch(INTRADAY_PROPOSAL, title, numbers, (), (f"引擎判定：{reason}",))

    def push_summary(self, day: date, plan: Plan, pool: Pool) -> DispatchResult:
        """15:12 日报卡（plan §9，1/日）。数字一律引擎出，且只报引擎真算得出来的量。"""
        numbers = {
            "账户总值_分": pool.portfolio_cents(),
            "目标仓位合计_bps": sum(target.target_bps for target in plan.targets),
            "订单数": len(plan.orders),
            "待人工确认": sum(1 for order in plan.orders if order.state is OrderState.APPROVED),
            "风控否决": sum(1 for order in plan.orders if order.state is OrderState.REJECTED),
        }
        return self._dispatch(DAILY_SUMMARY, f"{day.isoformat()} 收盘", numbers)

    def push_alert(self, kind: str, subject: str, detail: str) -> DispatchResult:
        """告警卡（plan §9，不限次）。"""
        return self._dispatch(ALERT_CARD, f"{kind} · {subject}", {}, (), (detail,))

    def stance_summaries(self, day: date, code: str) -> list[str]:
        """各决策实例对该标的的 stance 与理由摘要。卡片与确认页共用，一律标「评论」。"""
        out: list[str] = []
        for tag in self.settings.tags:
            name = f"DECISION-{tag}.md"
            if not self.archive.exists(day, name):
                continue
            grabbing = False
            stance = reason = ""
            for line in self.archive.read(day, name).splitlines():
                if line.startswith("## "):
                    if grabbing and stance:
                        out.append(f"{tag}：{stance} — {reason}")
                    grabbing = line[3:].strip().startswith(code)
                    stance = reason = ""
                elif grabbing and line.startswith("stance:"):
                    stance = line.split(":", 1)[1].strip()
                elif grabbing and line.startswith("reasoning:"):
                    reason = line.split(":", 1)[1].strip()
            if grabbing and stance:
                out.append(f"{tag}：{stance} — {reason}")
        return out

    def _dispatch(
        self,
        kind: str,
        subject: str,
        numbers: dict[str, int],
        comments: tuple[str, ...] = (),
        facts: tuple[str, ...] = (),
    ) -> DispatchResult:
        event = PushEvent(
            kind=kind,
            at=self.now,
            subject=subject,
            numbers=numbers,
            comments=comments,
            facts=facts,
            confirm_url=self.settings.confirm_base_url
            if kind in (MORNING_DECISION, INTRADAY_PROPOSAL)
            else "",
        )
        return self.dispatcher.dispatch(event)

    def confirm(self, order: Order, intent_id: str, *, to: OrderState = OrderState.QUEUED) -> Order:
        """唯一放行口：intent_id 必须来自真实用户轮次。"""
        verify(TurnLedger(self.settings.turn_ledger_path()), intent_id)
        if not can_transition(order.state, to):
            raise IllegalTransition(f"{order.state} -> {to} 非法")
        moved = transition(order, to, at=self.now, intent_id=intent_id)
        save(self.store, moved, self.now)
        return moved

    def _void(self, day: date, name: str, tag: str, reason: str) -> None:
        self.archive.mark_rejected(day, name)
        self.alert_log.emit(Alert(self.now, "sig001", tag, reason))

    def _slot(self, name: str) -> datetime:
        entry = next(e for e in SCHEDULE if e.name == name)
        return entry.occurs_on(self.now.date())

    def _fixture(self, rel: str) -> Any:
        path = self.settings.examples_dir / "fixtures" / rel
        return json.loads(path.read_text(encoding="utf-8"))

    def _snapshot(self, day: date) -> Mapping[str, Any]:
        return {str(code): dict(row) for code, row in self._fixture(f"quote/{day}.json").items()}

    def _cash_cents(self) -> int:
        rows = self.store.conn.execute("SELECT amount_cents FROM ledger").fetchall()
        return self.settings.portfolio_cents - sum(int(row["amount_cents"]) for row in rows)

    def _dd_flags(self, day: date, code: str) -> frozenset[str]:
        root = self.archive.daily_dir(day) / "DD" / code
        reports = sorted(root.glob("*.md"))
        if not reports:
            return frozenset()
        return scan_dd(reports[-1].read_text(encoding="utf-8"))


def build_planner(settings: Settings, day: date) -> Planner:
    """按配置装配一天的 Planner，时钟起点钉在当天的决策截止时刻以便回放。"""
    store = Store(settings.db_path)
    archive = Archive(settings.results_dir)
    return Planner(
        settings=settings,
        store=store,
        archive=archive,
        clock=VirtualClock(datetime.combine(day, _DEADLINE.at, tzinfo=TZ_SHANGHAI)),
        alert_log=AlertLog(store, archive),
        dispatcher=PushDispatcher(
            outbox_dir=settings.outbox_dir,
            renderer=CardRenderer(),
            webhook_url=settings.wecom_webhook_url,
        ),
    )


def _int(row: Any, key: str) -> int:
    return int(row[key])
