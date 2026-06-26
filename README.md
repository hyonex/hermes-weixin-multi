# Hermes Weixin Multi - 多账号微信插件

基于 iLink Bot API 的微信多账号接入插件，用于 Hermes Agent。

## 与原版插件的区别

| 功能 | 原版 `weixin` | 本插件 `weixin_multi` |
|------|--------------|----------------------|
| 多账号支持 | ❌ 单账号 | ✅ 无限账号，动态添加 |
| QR 远程登录 | ❌ 只支持 CLI 本地 | ✅ 任何渠道扫码（微信/Telegram/WebUI/CLI） |
| 扫码重试 | ❌ 过期需重新发命令 | ✅ 自动刷新 3 次 |
| 全局命令 | ❌ | ✅ `/wechat-login`、`/wechat-list` |
| 消息投递 | 基础 | 完整（文本/图片/视频/文件/语音） |
| 错误反馈 | 静默失败 | 超时/限流反馈给用户 |
| Status 回调 | 无 | 有（WebUI 显示账号状态） |

## 安装

```bash
# 克隆仓库
git clone https://gitee.com/hyonex/hermes-weixin-multi.git
cd hermes-weixin-multi

# 安装到 Hermes 插件目录
cp -r plugin/* ~/.hermes/plugins/weixin-multi/
cp weixin.py ~/.hermes/plugins/weixin-multi/

# 或者用符号链接（开发用）
ln -sf /opt/hermes-weixin-multi/plugin/adapter.py ~/.hermes/plugins/weixin-multi/adapter.py
ln -sf /opt/hermes-weixin-multi/weixin.py ~/.hermes/plugins/weixin-multi/weixin.py
```

### 配置

在 `~/.hermes/config.yaml` 中添加平台：

```yaml
platforms:
  weixin_multi: {}
  telegram:
    token: "YOUR_BOT_TOKEN"
```

## 使用方法

### 方式一：微信命令（推荐）

在任意已绑定的微信对话中发送：

```
/wechat-login
```

插件会：
1. 生成 QR 码（文字链接 + 图片）
2. 等待扫码（5 分钟有效）
3. 扫码过期自动刷新（最多 3 次）
4. 确认后自动保存账号

查看所有账号：
```
/wechat-list
```

### 方式二：Telegram 命令

在 Telegram 中发送：

```
/wechat-login
```

显示文字链接 + ASCII QR 码，用手机微信扫码。

### 方式三：WebUI 命令

在 WebUI（`http://localhost:8787`）中输入：

```
/wechat-login
```

显示文字链接，点击后在新页面扫码。

### 方式四：CLI 命令

```bash
hermes chat
# 进入交互模式后输入：
/wechat-login
```

显示文字链接 + ASCII QR 码（终端渲染）。

## 账号管理

### 查看所有账号

```bash
# 任何渠道
/wechat-list

# 或直接查看文件
ls ~/.hermes/weixin/accounts/
```

### 删除账号

```bash
rm ~/.hermes/weixin/accounts/wechat-1.json
hermes gateway restart
```

### 账号文件格式

```json
{
  "account_id": "wechat-1",
  "token": "xxx@im.bot:yyy",
  "base_url": "https://ilinkai.weixin.qq.com",
  "user_id": "oxxx@im.wechat",
  "client_id": "hermes-weixin-xxx",
  "saved_at": "2026-06-26T02:38:25Z"
}
```

## 多账号架构

```
Gateway (单进程)
├── wechat-1 → iLink Bot API → 微信号 A
├── wechat-2 → iLink Bot API → 微信号 B
└── wechat-N → iLink Bot API → 微信号 N
```

每个账号独立：
- 独立 iLink token
- 独立轮询线程
- 独立消息处理
- 独立 session

## 常见问题

### QR 码过期

QR 码有效期约 5 分钟。插件支持自动刷新（最多 3 次），超时后需重新发送 `/wechat-login`。

### Token 过期

iLink token 有时效性。过期后轮询静默失败（errcode=-14）。解决：
1. 发送 `/wechat-list` 检查状态
2. 如果 token 过期，发送 `/wechat-login` 重新扫码

### 消息发送失败

检查日志：
```bash
journalctl --user -u hermes-gateway --since "5 min ago"
```

常见原因：
- Token 过期 → 重新扫码
- 模型限流（429）→ 等待或切换模型
- 网络问题 → 检查代理配置

## 开发

### 代码结构

```
hermes-weixin-multi/
├── adapter.py          # 插件适配器（注册、命令、状态）
├── weixin.py           # 核心逻辑（消息收发、媒体处理）
├── plugin.yaml         # 插件元数据
├── plugin/
│   ├── adapter.py      # 运行时副本
│   ├── plugin.yaml     # 运行时副本
│   └── ...
└── README.md
```

### 修改代码后同步

```bash
# 1. 同步到插件目录
cp adapter.py ~/.hermes/plugins/weixin-multi/
cp weixin.py ~/.hermes/plugins/weixin-multi/

# 2. 清除缓存
find ~/.hermes/plugins/weixin-multi/ -name "*.pyc" -delete

# 3. 重启 gateway
hermes gateway restart
```

## 许可证

GPL-3.0
