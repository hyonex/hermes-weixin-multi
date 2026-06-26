#!/usr/bin/env python3
"""
WeChat QR Login Script
Run this to generate a QR code for WeChat login.
Usage: python3 wechat-login-script.py
"""

import asyncio
import json
import os
import sys
import time

# Add hermes to path
sys.path.insert(0, '/usr/local/lib/hermes-agent')

try:
    import aiohttp
except ImportError:
    print("❌ aiohttp not installed. Run: pip install aiohttp")
    sys.exit(1)

# iLink API endpoints
ILINK_BASE_URL = "https://ilinkai.weixin.qq.com"
EP_GET_BOT_QR = "/ilink/bot/get_qrcode"
EP_GET_QR_STATUS = "/ilink/bot/get_qrcode_status"
EP_GET_BOT_INFO = "/ilink/bot/get_bot_info"
QR_TIMEOUT_MS = 5000
LOGIN_TTL_SECONDS = 300  # 5 minutes

def _make_ssl_connector():
    """Create SSL connector that skips verification for iLink CDN."""
    try:
        return aiohttp.TCPConnector(ssl=False, limit=10)
    except Exception:
        return None

async def _api_get(session, base_url, endpoint, params=None, timeout_ms=5000):
    """GET request to iLink API."""
    url = f"{base_url.rstrip('/')}{endpoint}"
    timeout = aiohttp.ClientTimeout(total=timeout_ms / 1000)
    async with session.get(url, params=params, timeout=timeout) as resp:
        return await resp.json(content_type=None)

async def _api_post(session, base_url, endpoint, body, timeout_ms=10000):
    """POST request to iLink API."""
    url = f"{base_url.rstrip('/')}{endpoint}"
    timeout = aiohttp.ClientTimeout(total=timeout_ms / 1000)
    async with session.post(url, json=body, timeout=timeout) as resp:
        return await resp.json(content_type=None)

async def login():
    """Generate QR code and wait for scan."""
    print("📱 正在获取微信登录二维码...")
    
    connector = _make_ssl_connector()
    async with aiohttp.ClientSession(trust_env=True, connector=connector) as session:
        # Step 1: Get QR code
        try:
            qr_resp = await _api_get(
                session,
                base_url=ILINK_BASE_URL,
                endpoint=f"{EP_GET_BOT_QR}?bot_type=3",
                timeout_ms=QR_TIMEOUT_MS,
            )
        except Exception as e:
            print(f"❌ 获取二维码失败: {e}")
            return
        
        qrcode_value = str(qr_resp.get("qrcode") or "")
        qrcode_url = str(qr_resp.get("qrcode_img_content") or "")
        
        if not qrcode_value:
            print("❌ 获取二维码失败：服务端无响应")
            return
        
        qr_link = qrcode_url or qrcode_value
        print(f"\n📱 请用微信扫描以下链接登录：\n")
        print(f"   {qr_link}\n")
        print(f"⏳ 二维码5分钟内有效，请尽快扫描。\n")
        print(f"扫描后请在手机上确认登录...\n")
        
        # Step 2: Poll QR status
        current_base_url = ILINK_BASE_URL
        refresh_count = 0
        start_time = time.time()
        
        while time.time() - start_time < LOGIN_TTL_SECONDS:
            try:
                status_resp = await _api_get(
                    session,
                    base_url=current_base_url,
                    endpoint=f"{EP_GET_QR_STATUS}?qrcode={qrcode_value}",
                    timeout_ms=QR_TIMEOUT_MS,
                )
            except Exception:
                await asyncio.sleep(2)
                continue
            
            status = str(status_resp.get("status") or "wait")
            
            if status == "confirmed":
                token = str(status_resp.get("bot_token") or "")
                base_url = str(status_resp.get("baseurl") or ILINK_BASE_URL)
                
                if token:
                    print(f"\n✅ 登录成功！")
                    print(f"\nToken: {token}")
                    print(f"Base URL: {base_url}")
                    
                    # Save token to accounts directory
                    from hermes_cli.config import get_hermes_home
                    hermes_home = str(get_hermes_home())
                    
                    # Generate account ID
                    import uuid
                    account_id = f"wechat-{uuid.uuid4().hex[:8]}"
                    
                    # Create accounts directory
                    accounts_dir = os.path.join(hermes_home, "weixin", "accounts")
                    os.makedirs(accounts_dir, exist_ok=True)
                    
                    # Save account file
                    account_file = os.path.join(accounts_dir, f"{account_id}.json")
                    with open(account_file, "w") as f:
                        json.dump({
                            "token": token,
                            "base_url": base_url,
                            "cdn_base_url": "https://novac2c.cdn.weixin.qq.com/c2c",
                            "saved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        }, f, indent=2)
                    
                    print(f"\n账号已保存: {account_id}")
                    print(f"配置文件: {account_file}")
                    print(f"\n请重启 Hermes gateway 使账号生效:")
                    print(f"  hermes gateway restart")
                else:
                    print("❌ 登录确认但未收到 token")
                return
            
            elif status == "scaned":
                print("✅ 已扫码，请在手机上确认...")
                await asyncio.sleep(2)
            
            elif status == "scaned_but_redirect":
                redirect_host = str(status_resp.get("redirect_host") or "")
                if redirect_host:
                    current_base_url = f"https://{redirect_host}"
                    print(f"🔄 重定向到: {redirect_host}")
                await asyncio.sleep(2)
            
            elif status == "expired":
                refresh_count += 1
                if refresh_count > 3:
                    print("❌ 二维码已过期，请重新运行此脚本")
                    return
                
                print(f"🔄 二维码过期，正在刷新... (第{refresh_count}次)")
                try:
                    qr_resp = await _api_get(
                        session,
                        base_url=ILINK_BASE_URL,
                        endpoint=f"{EP_GET_BOT_QR}?bot_type=3",
                        timeout_ms=QR_TIMEOUT_MS,
                    )
                    qrcode_value = str(qr_resp.get("qrcode") or "")
                    qrcode_url = str(qr_resp.get("qrcode_img_content") or "")
                    qr_link = qrcode_url or qrcode_value
                    print(f"\n📱 新二维码：{qr_link}\n")
                except Exception:
                    pass
                await asyncio.sleep(2)
            
            else:
                await asyncio.sleep(2)
        
        print("❌ 登录超时，请重新运行此脚本")

if __name__ == "__main__":
    asyncio.run(login())
