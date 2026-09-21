"""四类卡片（plan §9 / §13）：数字只来自引擎、卡片不含确认按钮、上限与 outbox 快照。"""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import AT_PLAN_LOCK
from duty_agent.notify.cards import TITLE_ZH, CardRenderer
from duty_engine.push_dispatcher import (
    ALERT_CARD,
    DAILY_SUMMARY,
    INTRADAY_PROPOSAL,
    MORNING_DECISION,
    PushDispatcher,
    PushEvent,
)

NUMBERS = {
    "账户总值_分": 115_000_000,
    "000001_目标bps": 1000,
    "000001_触发线_分": 1164,
    "订单数": 1,
}
COMMENTS = ["gpt: 息差企稳，量能正常，未见硬雷", "claude: 跳空后追价收益不对称"]


@pytest.fixture
def card() -> tuple[PushEvent, str]:
    event = PushEvent(
        kind=MORNING_DECISION,
        at=AT_PLAN_LOCK,
        subject="2026-09-16 计划已锁定",
        numbers=NUMBERS,
        comments=tuple(COMMENTS),
        confirm_url="http://127.0.0.1:8501/confirm",
    )
    return event, CardRenderer().render(event)


def engine_section(text: str) -> list[str]:
    return text.split("## 引擎数字", 1)[1].split("##", 1)[0].strip().splitlines()


def test_card_numbers_from_engine_only(card: tuple[PushEvent, str]) -> None:
    event, text = card
    lines = engine_section(text)
    assert [line.lstrip("- ").split(": ")[0] for line in lines] == sorted(event.numbers)
    assert all(
        f": {event.numbers[name]}" in line
        for name, line in zip(sorted(event.numbers), lines, strict=True)
    )
    for comment in event.comments:
        assert comment not in "\n".join(lines)
    assert "评论（agent 判断，不构成指令）" in text


def test_card_has_no_confirm_button(card: tuple[PushEvent, str]) -> None:
    _, text = card
    assert "卡片内没有确认按钮" in text
    assert "http://127.0.0.1:8501/confirm" in text
    for forbidden in ("[确认]", "点击确认", "✅ 确认", "button", "st.button"):
        assert forbidden not in text


def test_all_four_cards_render(tmp_path: Path) -> None:
    dispatcher = PushDispatcher(tmp_path / "outbox", CardRenderer())
    for kind in (MORNING_DECISION, INTRADAY_PROPOSAL, DAILY_SUMMARY, ALERT_CARD):
        result = dispatcher.dispatch(
            PushEvent(
                kind=kind,
                at=AT_PLAN_LOCK,
                subject="样本",
                numbers={"订单数": 1},
                confirm_url="http://x/confirm",
            )
        )
        assert result.channel == "outbox"
        body = Path(result.path).read_text(encoding="utf-8")
        assert body.startswith(f"# {TITLE_ZH[kind]}")
        assert "- 订单数: 1" in body


def test_outbox_snapshot_has_engine_numbers_and_no_llm_positions(
    tmp_path: Path, card: tuple[PushEvent, str]
) -> None:
    """落盘快照里只有引擎数字，通篇不出现数量/价格/仓位表述（plan §15.2）。"""
    dispatcher = PushDispatcher(tmp_path / "outbox", CardRenderer())
    body = Path(dispatcher.dispatch(card[0]).path).read_text(encoding="utf-8")
    assert "115000000" in body
    assert "引擎数字" in body and "评论" in body
    from duty_agent.guardrails.sig001 import scan

    assert scan(body) == ()


def test_alert_card_has_no_confirm_link(tmp_path: Path) -> None:
    dispatcher = PushDispatcher(tmp_path / "outbox", CardRenderer())
    result = dispatcher.dispatch(
        PushEvent(kind=ALERT_CARD, at=AT_PLAN_LOCK, subject="缺卷 gpt", numbers={})
    )
    body = Path(result.path).read_text(encoding="utf-8")
    assert "确认页" not in body
    assert "## 引擎数字" in body and "- 无" in body


def test_wecom_refuses_without_webhook() -> None:
    """没配 webhook 就不猜地址——「不联网」红线的落点。"""
    from duty_agent.notify.wecom import post_markdown

    with pytest.raises(ValueError):
        post_markdown("", "# 卡片")


def test_wecom_posts_markdown_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    """展示模式不发真实请求，这里只验证请求体形状。"""
    import duty_agent.notify.wecom as wecom

    sent: list[tuple[str, dict[str, object]]] = []

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"errcode": 0}

    def fake_post(url: str, json: dict[str, object] | None = None, timeout: int = 0) -> Response:
        sent.append((url, json or {}))
        return Response()

    monkeypatch.setattr("duty_agent.notify.wecom.requests.post", fake_post)
    assert wecom.post_markdown("https://example.invalid/hook/<token>", "# 标题") == {"errcode": 0}
    assert sent[0][0].endswith("/hook/<token>")
    payload = sent[0][1]
    assert payload["msgtype"] == "markdown"
    markdown = payload["markdown"]
    assert isinstance(markdown, dict)
    assert str(markdown["content"]).startswith("# 标题")
