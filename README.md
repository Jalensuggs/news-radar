# News Radar 📡

自动新闻监控系统：GitHub Actions + Python + Claude API

每天早上8点（悉尼时间）发送日报，每2小时检测突发重大事件。监控范围：特朗普动态、AI圈、加密货币。

---

## 系统架构

```
GitHub Actions (定时触发)
    ↓
news_monitor.py
    ├── NewsAPI.org  → 抓取英文新闻
    ├── Claude API   → 分析生成中文报告（HTML格式）
    └── Gmail SMTP   → 发送邮件到你的邮箱
```

**运行频率与 API 消耗：**
| 任务 | 频率 | NewsAPI 调用次数 |
|------|------|----------------|
| 每日报告 | 每天1次 | 3次 |
| 突发检测 | 每2小时1次 = 每天12次 | 36次 |
| **合计** | — | **≤ 39次/天** |

NewsAPI 免费版限额 100次/天，安全余量充足。

---

## 准备工作（4个步骤）

### 第1步：获取 NewsAPI Key

1. 访问 [newsapi.org](https://newsapi.org)
2. 点击右上角 **Get API Key** → 注册免费账号
3. 注册完成后，在 Dashboard 页面复制你的 **API Key**（格式类似 `a1b2c3d4e5f6...`）

> 免费版：100次请求/天，过去30天内的新闻，足够本系统使用。

---

### 第2步：获取 Gmail 应用专用密码

> **重要**：不能使用你的 Gmail 登录密码，必须生成"应用专用密码"。

1. 登录你的 Google 账户，访问 [myaccount.google.com/security](https://myaccount.google.com/security)
2. 确保已开启**两步验证**（如未开启，先按提示开启）
3. 在安全页面搜索 **"应用专用密码"**（App Passwords）
4. 选择应用：**邮件**，选择设备：**其他（自定义名称）**，输入 `News Radar`
5. 点击 **生成**，复制显示的16位密码（格式：`xxxx xxxx xxxx xxxx`）

> 这个密码只显示一次，请立即复制保存。

---

### 第3步：创建 GitHub 仓库并上传代码

```bash
# 在项目目录下初始化 git 仓库
git init
git add .
git commit -m "Initial commit"

# 在 GitHub 创建新仓库（名称：news-radar）
# 然后推送代码
git remote add origin https://github.com/你的用户名/news-radar.git
git branch -M main
git push -u origin main
```

---

### 第4步：配置 GitHub Secrets（5个）

在 GitHub 仓库页面：**Settings → Secrets and variables → Actions → New repository secret**

逐个添加以下5个 Secret：

| Secret 名称 | 值 | 说明 |
|------------|-----|------|
| `NEWSAPI_KEY` | `你的NewsAPI密钥` | 第1步获取 |
| `ANTHROPIC_API_KEY` | `sk-ant-...` | 从 [console.anthropic.com](https://console.anthropic.com) 获取 |
| `GMAIL_USER` | `你的邮箱@gmail.com` | 发件邮箱地址 |
| `GMAIL_APP_PASSWORD` | `xxxx xxxx xxxx xxxx` | 第2步获取的16位应用密码（去掉空格） |
| `RECIPIENT_EMAIL` | `接收报告的邮箱@example.com` | 收件邮箱（可以和发件相同） |

---

## 验证部署

配置完成后，手动触发一次测试：

1. 在 GitHub 仓库点击 **Actions** 标签
2. 左侧选择 **News Radar** workflow
3. 右侧点击 **Run workflow**
4. 选择模式：`daily`（发送完整日报）或 `breaking`（只检测，可能不发邮件）
5. 点击绿色 **Run workflow** 按钮
6. 等待约60秒，查看运行日志
7. 检查你的邮箱是否收到邮件

---

## 运行时间表

| 任务 | GitHub Actions Cron | 悉尼时间 |
|------|-------------------|--------|
| 每日报告 | `0 22 * * *` (UTC) | 08:00 AEST / 09:00 AEDT |
| 突发检测 | `0 */2 * * *` (UTC) | 每2小时 |

> **说明**：GitHub Actions 使用 UTC 时区。悉尼夏令时（AEDT，10月到次年4月）为 UTC+11，此时日报会在悉尼时间9点到达。如需精确8点，可在夏令时期间将 cron 改为 `0 21 * * *`。

---

## 邮件样式预览

**每日报告邮件**：
- 顶部橙色细线 + "每日情报简报"标题
- 5个板块：今日摘要 / 特朗普动态 / AI圈 / 加密货币 / 投资者关注
- 投资者关注板块带橙色左竖线，米色背景
- 底部显示 AI 生成时间

**突发提醒邮件**：
- 顶部红色细线 + "🚨 突发新闻提醒"
- 事件经过 + 背景 + 市场影响分析
- 邮件标题带 🚨 标识

---

## 常见问题

**Q：收不到邮件怎么办？**
- 检查 Actions 日志是否有报错
- 确认 `GMAIL_APP_PASSWORD` 没有多余空格
- 检查 Gmail 是否开启了两步验证（必须开启才能用应用密码）
- 查看垃圾邮件文件夹

**Q：NewsAPI 返回空结果？**
- 免费版可能对某些查询有轻微延迟（最多12小时）
- 尝试手动触发 `daily` 模式，查看 Actions 日志中 `Found:` 那行的数字

**Q：GitHub Actions 显示失败？**
- 检查所有5个 Secret 是否都已添加，名称是否完全一致（区分大小写）
- 在 Actions 日志中查看具体错误信息

**Q：想修改监控关键词？**
- 编辑 `news_monitor.py` 中 `fetch_all_news()` 函数的三个查询字符串

**Q：想更改发送时间？**
- 编辑 `.github/workflows/news_monitor.yml` 中的 cron 表达式
- 使用 [crontab.guru](https://crontab.guru) 验证 cron 语法
