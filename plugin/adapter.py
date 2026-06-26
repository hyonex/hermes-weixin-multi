"""
Weixin Multi-Account Platform Adapter — Plugin Entry Point.

Registers the weixin_multi platform adapter under the name "weixin_multi",
separate from the built-in "weixin" (single-account) adapter.
Both can coexist in the same Hermes instance.

config.yaml::

    gateway:
      platforms:
        weixin_multi:
          enabled: true
          extra:
            dm_policy: open
            accounts:
              wechat-1:
                token: "..."
              wechat-2:
                token: "..."
"""

import importlib.util
import json
import os
import sys
import uuid
import time
from pathlib import Path
from typing import Any, Optional

# Resolve the multi-weixin source directory
_MULTI_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "..", "..", "..", "opt", "hermes-weixin-multi"
)
_MULTI_DIR = os.path.realpath(_MULTI_DIR)

if _MULTI_DIR not in sys.path:
    sys.path.insert(0, _MULTI_DIR)


def check_requirements() -> bool:
    try:
        import aiohttp  # noqa: F401
        import cryptography  # noqa: F401
        return True
    except ImportError:
        return False


def validate_config(config: Any) -> bool:
    """Validate config: True if platform is enabled (even without accounts).
    
    Accounts can be added dynamically via /wechat-login, so we don't require
    pre-configured accounts. Just check that weixin_multi is enabled.
    """
    enabled = getattr(config, "enabled", False)
    if not enabled:
        return False
    
    # Check if there are pre-configured accounts (optional)
    extra = getattr(config, "extra", {}) or {}
    accounts = extra.get("accounts", {})
    if isinstance(accounts, dict) and accounts and any(
        (a.get("token") or a.get("access_token") or "").strip()
        for a in accounts.values()
    ):
        return True
    
    # Even without pre-configured accounts, still valid — accounts
    # will be added via /wechat-login from any channel.
    return True


def _env_enablement() -> Optional[dict]:
    token = os.getenv("WEIXIN_MULTI_TOKEN") or os.getenv("WEIXIN_TOKEN")
    if not token:
        return None
    account_id = os.getenv("WEIXIN_MULTI_ACCOUNT_ID") or os.getenv("WEIXIN_ACCOUNT_ID", "default")
    base_url = os.getenv("WEIXIN_MULTI_BASE_URL") or os.getenv("WEIXIN_BASE_URL", "")
    dm_policy = os.getenv("WEIXIN_MULTI_DM_POLICY") or os.getenv("WEIXIN_DM_POLICY", "open")
    extra: dict[str, Any] = {
        "dm_policy": dm_policy,
        "accounts": {
            account_id: {
                "token": token,
                **({"base_url": base_url} if base_url else {}),
            }
        },
    }
    return extra


# ── Standalone command helpers (work from any process) ──
# These don't need the adapter instance — they use iLink API directly
# and read/write account files on disk.

ILINK_BASE_URL = "https://ilinkai.weixin.qq.com"
CDN_BASE_URL = "https://novac2c.cdn.weixin.qq.com/c2c"
EP_GET_BOT_QR = "/ilink/bot/get_bot_qrcode"
EP_GET_QR_STATUS = "/ilink/bot/get_qrcode_status"
QR_TIMEOUT_MS = 5000

def _accounts_dir() -> str:
    hermes_home = os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))
    return os.path.join(hermes_home, "weixin", "accounts")

def _generate_account_id() -> str:
    """Generate next available wechat-N account ID."""
    accounts_dir = _accounts_dir()
    existing = set()
    if os.path.isdir(accounts_dir):
        for f in os.listdir(accounts_dir):
            if f.endswith(".json"):
                existing.add(f.replace(".json", ""))
    
    n = 1
    while f"wechat-{n}" in existing:
        n += 1
    return f"wechat-{n}"

def _save_account(account_id: str, token: str, base_url: str = "") -> str:
    """Save account to disk. Returns file path."""
    accounts_dir = _accounts_dir()
    os.makedirs(accounts_dir, exist_ok=True)
    
    account_data = {
        "token": token,
        "base_url": base_url or ILINK_BASE_URL,
        "cdn_base_url": CDN_BASE_URL,
        "saved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    
    path = os.path.join(accounts_dir, f"{account_id}.json")
    with open(path, "w") as f:
        json.dump(account_data, f, indent=2)
    return path

def _list_accounts() -> list:
    """List all accounts from disk."""
    accounts_dir = _accounts_dir()
    accounts = []
    if os.path.isdir(accounts_dir):
        for f in sorted(os.listdir(accounts_dir)):
            # Only match actual account files: wechat-N.json
            if f.endswith(".json") and f.startswith("wechat-") and not "." in f[:-5]:
                account_id = f.replace(".json", "")
                path = os.path.join(accounts_dir, f)
                try:
                    with open(path) as fh:
                        data = json.load(fh)
                    accounts.append({
                        "id": account_id,
                        "token": data.get("token", ""),
                        "base_url": data.get("base_url", ""),
                    })
                except Exception:
                    accounts.append({"id": account_id, "token": "???", "base_url": ""})
    return accounts

# ── Pending QR management ──
# When /wechat-login is called from WebUI, the QR data is saved to disk.
# The gateway process polls this file and completes the login when confirmed.

def _pending_qr_file() -> str:
    hermes_home = os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))
    return os.path.join(hermes_home, "weixin", "pending_qr.json")

def _save_pending_qr(qrcode_value: str, qr_link: str) -> None:
    """Save pending QR for gateway to poll."""
    pending_file = _pending_qr_file()
    os.makedirs(os.path.dirname(pending_file), exist_ok=True)
    with open(pending_file, "w") as f:
        json.dump({
            "qrcode": qrcode_value,
            "link": qr_link,
            "created_at": time.time(),
        }, f)

def _load_pending_qr() -> Optional[dict]:
    """Load pending QR data. Returns None if none or expired."""
    pending_file = _pending_qr_file()
    if not os.path.exists(pending_file):
        return None
    try:
        with open(pending_file) as f:
            data = json.load(f)
        # Expire after 5 minutes
        if time.time() - data.get("created_at", 0) > 300:
            os.remove(pending_file)
            return None
        return data
    except Exception:
        return None

def _clear_pending_qr() -> None:
    """Remove pending QR file after successful login."""
    pending_file = _pending_qr_file()
    if os.path.exists(pending_file):
        os.remove(pending_file)


def register(ctx):
    """
    Plugin entry point — called by Hermes plugin system.

    Dynamically imports WeixinMultiAdapter from /opt/hermes-weixin-multi/weixin.py
    and registers it as the "weixin_multi" platform adapter.

    Also registers /wechat-login and /wechat-list as GLOBAL slash commands
    (available from any channel — WebUI, Telegram, etc.).
    """
    weixin_path = os.path.join(_MULTI_DIR, "weixin.py")
    if not os.path.exists(weixin_path):
        raise FileNotFoundError(
            f"weixin_multi adapter not found at {weixin_path}. "
            f"Install: cp weixin.py to {_MULTI_DIR}/weixin.py"
        )

    # Dynamic import of the weixin module
    spec = importlib.util.spec_from_file_location("weixin_multi_impl", weixin_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["weixin_multi_impl"] = mod
    spec.loader.exec_module(mod)

    WeixinMultiAdapter = mod.WeixinMultiAdapter

    # ── Fix platform identity: set self.platform after __init__ ──
    from gateway.config import Platform

    _orig_init = WeixinMultiAdapter.__init__

    def _patched_init(self, config, **kwargs):
        _orig_init(self, config, **kwargs)
        self.platform = Platform("weixin_multi")

    WeixinMultiAdapter.__init__ = _patched_init

    # Register with the platform registry
    ctx.register_platform(
        name="weixin_multi",
        label="Weixin Multi",
        adapter_factory=lambda cfg: WeixinMultiAdapter(cfg),
        check_fn=check_requirements,
        validate_config=validate_config,
        required_env=[],
        install_hint="pip install aiohttp cryptography",
        env_enablement_fn=_env_enablement,
    )

    # ── Register global slash commands ──
    # These work from ANY channel (WebUI, Telegram, etc.) and from ANY
    # process (gateway or WebUI) — they use iLink API directly and
    # read/write account files on disk, no adapter instance needed.

    async def _handle_wechat_login_cmd(raw_args: str) -> str:
        """Global /wechat-login: generate QR and wait for scan.
        
        Runs in whatever process calls it (gateway or WebUI).
        Saves token to ~/.hermes/weixin/accounts/<id>.json on success.
        """
        try:
            import aiohttp as aio
        except ImportError:
            return "❌ aiohttp 未安装。请运行: pip install aiohttp"

        try:
            ssl_ctx = aio.TCPConnector(ssl=False, limit=10)
        except Exception:
            ssl_ctx = None

        try:
            async with aio.ClientSession(trust_env=True, connector=ssl_ctx) as session:
                # Step 1: Get QR code
                url = f"{ILINK_BASE_URL}{EP_GET_BOT_QR}?bot_type=3"
                timeout = aio.ClientTimeout(total=QR_TIMEOUT_MS / 1000)
                async with session.get(url, timeout=timeout) as resp:
                    qr_resp = await resp.json(content_type=None)

                qrcode_value = str(qr_resp.get("qrcode") or "")
                qrcode_url = str(qr_resp.get("qrcode_img_content") or "")

                if not qrcode_value:
                    return "❌ 获取二维码失败：服务端无响应"

                qr_link = qrcode_url or qrcode_value

                # Store pending QR for gateway to poll
                _save_pending_qr(qrcode_value, qr_link)

                return (
                    f"📱 请用微信扫描以下链接登录：\n\n"
                    f"{qr_link}\n\n"
                    f"⏳ 二维码5分钟内有效，请尽快扫描。\n\n"
                    f"扫码后手机上点「确认」，Gateway 会自动完成登录。\n"
                    f"登录成功后直接在微信发消息测试即可。\n"
                    f"用 /wechat-list 查看账号状态。"
                )
        except Exception as e:
            return f"❌ 获取二维码失败: {e}"

    def _handle_wechat_list_cmd(raw_args: str) -> str:
        """Global /wechat-list: show all accounts and status.
        
        Works from any process — reads account files from disk.
        """
        accounts = _list_accounts()
        if not accounts:
            return "📱 暂无微信账号。发送 /wechat-login 添加第一个账号。"

        lines = ["📱 Weixin Multi 账号列表：\n"]
        for acc in accounts:
            has_token = "✅" if acc.get("token") and acc["token"] != "???" else "❌"
            lines.append(f"  {has_token} {acc['id']} — token={'已配置' if has_token == '✅' else '未配置'}")
        lines.append(f"\n共 {len(accounts)} 个账号")
        lines.append("发送 /wechat-login 添加新账号")
        return "\n".join(lines)

    ctx.register_command(
        name="wechat-login",
        handler=_handle_wechat_login_cmd,
        description="添加新微信账号（扫码登录）",
    )
    ctx.register_command(
        name="wechat-list",
        handler=_handle_wechat_list_cmd,
        description="查看所有微信账号状态",
    )
