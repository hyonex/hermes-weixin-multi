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
    "..", "..", "..", "opt", "hermes-weixin-multi"
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
    extra = getattr(config, "extra", {}) or {}
    accounts = extra.get("accounts", {})
    if isinstance(accounts, dict) and accounts:
        return any(
            (a.get("token") or a.get("access_token") or "").strip()
            for a in accounts.values()
        )
    if os.getenv("WEIXIN_MULTI_TOKEN") or os.getenv("WEIXIN_TOKEN"):
        return True
    if getattr(config, "token", ""):
        return True
    return False


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
    # The adapter's __init__ calls super().__init__(config, Platform.WEIXIN),
    # which sets self.platform = Platform.WEIXIN (the built-in single-account
    # platform). We override self.platform after init so all subsequent
    # self.platform.value references return "weixin_multi" instead.
    from gateway.config import Platform

    _orig_init = WeixinMultiAdapter.__init__

    def _patched_init(self, config, **kwargs):
        _orig_init(self, config, **kwargs)
        # Override platform identity to weixin_multi
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
