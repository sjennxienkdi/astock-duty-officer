"""企业微信通道（plan §9）：webhook 未配置即不推送，由 dispatcher 落 outbox。"""

from __future__ import annotations

from typing import Any

import requests

TIMEOUT_SECONDS = 5


def post_markdown(webhook_url: str, text: str) -> dict[str, Any]:
    """发送一条 markdown 卡片。webhook 为空时直接拒绝，不猜地址。"""
    if not webhook_url:
        raise ValueError("未配置 webhook，展示模式应走 outbox 落盘")
    payload: dict[str, Any] = {"msgtype": "markdown", "markdown": {"content": text[:4000]}}
    response = requests.post(webhook_url, json=payload, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()
    return dict(response.json())
