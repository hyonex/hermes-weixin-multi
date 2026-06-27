<div align="center">
  <h1>🤖 Hermes Weixin Multi</h1>
  <p><strong>多账号微信接入插件 · Multi-Account WeChat Plugin for Hermes Agent</strong></p>
  <p>基于腾讯 iLink Bot API，让你的 Hermes Agent 同时接入 <b>无限个微信账号</b>。<br>
  <em>Connect unlimited WeChat accounts to your Hermes Agent via Tencent iLink Bot API.</em></p>
</div>

<p align="center">
  <img src="screenshots/two-accounts.jpg" width="280" alt="双账号在线">
  <img src="screenshots/wechat-list.jpg" width="280" alt="账号列表">
  <img src="screenshots/chat-demo.jpg" width="280" alt="聊天演示">
</p>

---

## ✨ 特性 / Features

| 功能 | 官方 `weixin` | 本插件 `weixin_multi` |
|------|:------------:|:-------------------:|
| 多账号支持 / Multi-account | ❌ 单账号 | ✅ 无限账号，动态添加 |
| QR 扫码登录 / QR Login | ❌ CLI 本地 | ✅ 任何渠道（微信/Telegram/WebUI/CLI） |
| 扫码自动重试 / Auto Retry | ❌ 过期需重发 | ✅ 自动刷新 3 次 |
| 全局命令 / Slash Commands | ❌ | ✅ `/wechat-login`、`/wechat-list` |
| 消息收发 / Media Support | 基础文本 | ✅ 文本/图片/视频/文件/语音 |
| 错误反馈 / Error Feedback | 静默失败 | ✅ 超时/限流提示 |
| WebUI 状态 / Status Display | ❌ | ✅ 账号在线状态 |
| 独立轮询 / Independent Polling | ❌ 单线程 | ✅ 每账号独立线程 |

---

## 📦 安装 / Install

### 前置条件 / Prerequisites

- 已安装 [Hermes Agent](https://hermes-agent.nousresearch.com)
- Python 依赖：`aiohttp`、`cryptography`、`qrcode[pil]`

```bash
pip install aiohttp cryptography qrcode[pil]
```

### 1. 克隆插件 / Clone Plugin

```bash
git clone https://github.com/hyonex/hermes-weixin-multi.git ~/.hermes/plugins/weixin-multi
```

### 2. 启用插件 / Enable Plugin

在 `~/.hermes/config.yaml` 中添加 / Add to your `config.yaml`:

```yaml
plugins:
  enabled:
    - weixin-multi

gateway:
  platforms:
    weixin_multi:
      enabled: true
      extra:
        dm_policy: open          # 私聊策略 / DM policy
        group_policy: disabled   # 群聊策略 / Group policy
```

### 3. 重启 Gateway / Restart Gateway

```bash
hermes gateway restart
```

---

## 🚀 使用方法 / Usage

### 添加微信账号 / Add WeChat Account

在任何已绑定的渠道发送 / Send from any connected channel:

```
/wechat-login
```

插件会生成二维码，用微信扫码并确认即可自动添加。
*The plugin generates a QR code — scan with WeChat and confirm to auto-add.*

### 查看账号列表 / List Accounts

```
/wechat-list
```

示例输出 / Example output:

```
📱 Weixin Multi 账号列表：
  ✅ wechat-1 — 🟢 轮询中 / polling
  ✅ wechat-2 — 🟢 轮询中 / polling

共 2 个账号 / Total 2 accounts
发送 /wechat-login 添加新账号
```

### 删除账号 / Remove Account

```bash
rm ~/.hermes/weixin/accounts/wechat-N.json
hermes gateway restart
```

---

## 🏗️ 多账号架构 / Architecture

```
Gateway (单进程 / Single Process)
├── wechat-1 → iLink Bot API → 📱 微信号 A / Account A
├── wechat-2 → iLink Bot API → 📱 微信号 B / Account B
└── wechat-N → iLink Bot API → 📱 微信号 N / Account N
```

每个账号**完全独立** / Each account is **fully independent**:

- ✅ 独立 iLink token / Independent token
- ✅ 独立异步轮询线程 / Independent async polling
- ✅ 独立消息收发 / Independent messaging
- ✅ 独立会话管理 / Independent session management

---

## ⚙️ 配置参考 / Configuration

### 账号文件 / Account File

存储位置：`~/.hermes/weixin/accounts/wechat-N.json`

```json
{
  "token": "***",
  "base_url": "https://ilinkai.weixin.qq.com",
  "cdn_base_url": "https://cdn2.weixin.qq.com"
}
```

### 环境变量 / Environment Variables

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `WEIXIN_MULTI_DM_POLICY` | 私聊策略 / DM policy | `open` |
| `WEIXIN_MULTI_ALLOWED_USERS` | 允许的用户 ID / Allowed user IDs | — |
| `WEIXIN_MULTI_BASE_URL` | API 地址 / API base URL | `https://ilinkai.weixin.qq.com` |

---

## ❓ 常见问题 / FAQ

### QR 码过期 / QR Code Expired

有效期约 5 分钟。插件会自动刷新最多 3 次，超时后重新发 `/wechat-login`。
*Valid for ~5 min. Auto-refreshes up to 3 times. Re-send `/wechat-login` if expired.*

### Token 过期 / Token Expired

iLink token 有时效性，过期后轮询静默失败（errcode=-14）。重新扫码即可。
*iLink tokens expire — polling silently fails (errcode=-14). Re-scan to refresh.*

### 消息发送失败 / Message Send Failed

```bash
journalctl --user -u hermes-gateway --since "5 min ago"
```

常见原因 / Common causes:
- Token 过期 / Token expired → 重新扫码 / re-scan
- 模型限流 429 / Rate limit → 等待或切换模型 / wait or switch model
- 网络问题 / Network → 检查代理配置 / check proxy config

---

## 🧑‍💻 开发 / Development

### 代码结构 / Code Structure

```
hermes-weixin-multi/
├── adapter.py       # 插件适配器（注册、命令、状态）Plugin adapter
├── weixin.py        # 核心逻辑（消息收发、媒体处理）Core logic
├── plugin.yaml      # 插件元数据 / Plugin metadata
├── screenshots/     # 功能截图 / Screenshots
└── README.md        # 本文件 / This file
```

### 修改后同步 / Sync After Changes

```bash
cp adapter.py weixin.py ~/.hermes/plugins/weixin-multi/
find ~/.hermes/plugins/weixin-multi/ -name "*.pyc" -delete
hermes gateway restart
```

---

## 📄 许可证 / License

本项目基于 [Hermes Agent](https://github.com/nousresearch/hermes-agent) 的 weixin.py 修改而来。
*This project is a fork of the `weixin.py` platform adapter from [Hermes Agent](https://github.com/nousresearch/hermes-agent).*

**原项目 / Original:** MIT License © 2025 Nous Research  
**本修改版 / This fork:** GNU Affero General Public License v3.0 (AGPL-3.0)

- ✅ 个人学习、研究可自由使用 / Free for personal & research use
- ✅ 修改后的代码**必须开源** / Modifications **must be open-sourced** (AGPL)
- ✅ 引用或再分发需注明来源 / Attribution required for redistribution
- ❌ 商业使用需谨慎（AGPL 传染性） / Commercial use: AGPL is copyleft

详见 / See [LICENSE](LICENSE) 文件。

---

<div align="center">
  <p>Made with ❤️ by <a href="https://github.com/hyonex">hyonex</a></p>
  <p>
    <a href="https://github.com/hyonex/hermes-weixin-multi">GitHub</a> ·
    <a href="https://gitee.com/hyonex/hermes-weixin-multi">Gitee</a>
  </p>
</div>
