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
    # These work from ANY channel (WebUI, Telegram, etc.), not just WeChat.
    # This solves the bootstrap problem: first account can be added from WebUI.

    # Store adapter reference for command handlers
    _adapter_ref = {"instance": None}

    _orig_factory = ctx.register_platform

    def _capture_factory(cfg):
        adapter = WeixinMultiAdapter(cfg)
        _adapter_ref["instance"] = adapter
        return adapter

    # Re-register with capture wrapper
    ctx.register_platform(
        name="weixin_multi",
        label="Weixin Multi",
        adapter_factory=_capture_factory,
        check_fn=check_requirements,
        validate_config=validate_config,
        required_env=[],
        install_hint="pip install aiohttp cryptography",
        env_enablement_fn=_env_enablement,
    )

    async def _handle_wechat_login_cmd(raw_args: str) -> str:
        """Global /wechat-login: generate QR and wait for scan.

        Works from ANY channel (WebUI, Telegram, etc.).
        If no accounts exist yet, this is the bootstrap path.
        """
        adapter = _adapter_ref["instance"]
        if not adapter:
            return "❌ Weixin Multi 适配器未运行。请先在 config.yaml 中启用 weixin_multi 平台。"

        try:
            # Get QR code directly
            session = mod.aiohttp.ClientSession(
                trust_env=True,
                connector=mod._make_ssl_connector(),
            )
            try:
                qr_resp = await mod._api_get(
                    session,
                    base_url=mod.ILINK_BASE_URL,
                    endpoint=f"{mod.EP_GET_BOT_QR}?bot_type=3",
                    timeout_ms=mod.QR_TIMEOUT_MS,
                )
                qrcode_value = str(qr_resp.get("qrcode") or "")
                qrcode_url = str(qr_resp.get("qrcode_img_content") or "")
                if not qrcode_value:
                    return "❌ 获取二维码失败：服务端无响应"

                qr_link = qrcode_url or qrcode_value

                # Start background polling task for QR status
                import asyncio

                async def _poll_qr_status():
                    """Background task: poll QR scan status, add account on confirm."""
                    deadline = asyncio.get_event_loop().time() + 300
                    current_base_url = mod.ILINK_BASE_URL
                    refresh_count = 0

                    while asyncio.get_event_loop().time() < deadline:
                        try:
                            status_resp = await mod._api_get(
                                session,
                                base_url=current_base_url,
                                endpoint=f"{mod.EP_GET_QR_STATUS}?qrcode={qrcode_value}",
                                timeout_ms=mod.QR_TIMEOUT_MS,
                            )
                        except Exception:
                            await asyncio.sleep(2)
                            continue

                        status = str(status_resp.get("status") or "wait")
                        if status == "confirmed":
                            token_new = str(status_resp.get("bot_token") or "")
                            base_url_new = str(status_resp.get("baseurl") or mod.ILINK_BASE_URL)
                            if token_new:
                                generated_id = mod.generateAccountId()
                                mod.saveAccountToConfig(
                                    str(mod.get_hermes_home()),
                                    generated_id,
                                    {
                                        "token": token_new,
                                        "base_url": base_url_new,
                                        "cdn_base_url": mod.WEIXIN_CDN_BASE_URL,
                                    },
                                )
                                # Add to running adapter
                                adapter._accounts[generated_id] = {
                                    "token": token_new,
                                    "base_url": base_url_new,
                                    "cdn_base_url": mod.WEIXIN_CDN_BASE_URL,
                                }
                                # Start polling
                                no_timeout = mod.aiohttp.ClientTimeout(total=None)
                                poll_session = mod.aiohttp.ClientSession(
                                    trust_env=True, connector=mod._make_ssl_connector()
                                )
                                send_session = mod.aiohttp.ClientSession(
                                    trust_env=True, connector=mod._make_ssl_connector(),
                                    timeout=no_timeout,
                                )
                                adapter._poll_sessions[generated_id] = poll_session
                                adapter._send_sessions[generated_id] = send_session
                                adapter._sync_bufs[generated_id] = mod._load_sync_buf(
                                    str(mod.get_hermes_home()), generated_id
                                )
                                task = asyncio.create_task(
                                    adapter._poll_loop(generated_id),
                                    name=f"weixin-poll-{generated_id}",
                                )
                                adapter._poll_tasks[generated_id] = task
                                mod._LIVE_ADAPTERS[token_new] = adapter
                                mod.accountPolling[generated_id] = {"running": True, "task": task}
                                logger.info("✅ 新账号 %s 登录成功！", generated_id)
                            break
                        elif status == "scaned":
                            await asyncio.sleep(2)
                        elif status == "expired":
                            refresh_count += 1
                            if refresh_count > 3:
                                break
                            qr_resp2 = await mod._api_get(
                                session,
                                base_url=mod.ILINK_BASE_URL,
                                endpoint=f"{mod.EP_GET_BOT_QR}?bot_type=3",
                                timeout_ms=mod.QR_TIMEOUT_MS,
                            )
                            # Can't easily update user — just break
                            break
                        else:
                            await asyncio.sleep(2)

                    await session.close()

                asyncio.create_task(_poll_qr_status())

                return (
                    f"📱 请用微信扫描以下链接登录：\n\n"
                    f"{qr_link}\n\n"
                    f"⏳ 二维码5分钟内有效，请尽快扫描。\n"
                    f"扫描确认后会自动添加为新账号。"
                )
            except Exception as e:
                await session.close()
                return f"❌ 获取二维码失败: {e}"
        except Exception as e:
            return f"❌ 登录出错: {e}"

    def _handle_wechat_list_cmd(raw_args: str) -> str:
        """Global /wechat-list: show all accounts and status."""
        adapter = _adapter_ref["instance"]
        if not adapter:
            return "❌ Weixin Multi 适配器未运行。"

        lines = ["📱 Weixin Multi 账号列表：\n"]
        for acc_id, acc_state in adapter._accounts.items():
            token = acc_state.get("token", "")
            status = "✅" if token else "❌"
            task = adapter._poll_tasks.get(acc_id)
            running = task and not task.done()
            lines.append(f"  {status} {acc_id} — {'🟢 轮询中' if running else '🔴 未运行'}")
        lines.append(f"\n共 {len(adapter._accounts)} 个账号")
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
