from __future__ import annotations

import argparse
import json
import os
import urllib.parse
import urllib.request
from pathlib import Path


def _load_openclaw_bot_token(cfg_path: Path, account: str) -> str:
    cfg = json.loads(cfg_path.read_text())
    channels = cfg.get("channels", {})
    tg = channels.get("telegram", {})
    accts = tg.get("accounts", {})
    acct = accts.get(account, {})
    token = acct.get("botToken", "")
    if not token:
        raise SystemExit(f"Missing botToken in openclaw config account={account}")
    return token


def _get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.loads(r.read())


def _post_form(url: str, data: dict) -> dict:
    body = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def _discover_latest_chat_id(token: str) -> str | None:
    u = f"https://api.telegram.org/bot{token}/getUpdates"
    res = _get_json(u)
    updates = res.get("result", [])
    if not updates:
        return None
    for upd in reversed(updates):
        msg = upd.get("message") or upd.get("channel_post") or upd.get("edited_message") or {}
        chat = msg.get("chat", {})
        cid = chat.get("id")
        if cid is not None:
            return str(cid)
    return None


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Send memo text to Telegram using OpenClaw bot token")
    p.add_argument("--memo-path", type=Path, required=True)
    p.add_argument("--openclaw-config", type=Path, default=Path("/Users/mini/.openclaw/openclaw.json"))
    p.add_argument("--account", type=str, default=os.environ.get("OPENCLAW_TELEGRAM_ACCOUNT", "rabbit"))
    p.add_argument("--chat-id", type=str, default=os.environ.get("TELEGRAM_CHAT_ID", ""))
    p.add_argument("--discover-chat-id", action="store_true", help="If chat-id missing, try Telegram getUpdates latest chat id")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    memo = args.memo_path.read_text().strip()
    if not memo:
        raise SystemExit("Memo is empty")

    token = _load_openclaw_bot_token(args.openclaw_config, args.account)
    chat_id = (args.chat_id or "").strip()
    if not chat_id and args.discover_chat_id:
        chat_id = _discover_latest_chat_id(token) or ""
    if not chat_id:
        raise SystemExit("No chat id. Set TELEGRAM_CHAT_ID or pass --chat-id, or use --discover-chat-id after messaging bot once.")

    # Telegram hard message limit is 4096 chars.
    chunks = []
    text = memo
    while text:
        chunks.append(text[:3900])
        text = text[3900:]

    for i, chunk in enumerate(chunks):
        prefix = "" if i == 0 else f"(cont. {i+1}/{len(chunks)})\\n"
        payload = {
            "chat_id": chat_id,
            "text": prefix + chunk,
            "disable_web_page_preview": "true",
        }
        out = _post_form(f"https://api.telegram.org/bot{token}/sendMessage", payload)
        if not out.get("ok"):
            raise SystemExit(f"Telegram send failed: {out}")

    print(json.dumps({"ok": True, "chat_id": chat_id, "parts": len(chunks), "account": args.account}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
