#!/usr/bin/env python3
"""
News Radar — Automated news monitoring system.

Fetches news from NewsAPI, analyzes with Claude, sends HTML email reports.

Usage:
    python news_monitor.py daily     # Generate and send daily report
    python news_monitor.py breaking  # Check for breaking news (past 2h)
"""

import json
import os
import re
import smtplib
import sys
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import anthropic
import requests

# ─── Configuration ─────────────────────────────────────────────────────────────
NEWSAPI_KEY = os.environ.get("NEWSAPI_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
GMAIL_USER = os.environ.get("GMAIL_USER", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
RECIPIENT_EMAIL = os.environ.get("RECIPIENT_EMAIL", "")

MODEL = "claude-sonnet-4-6"
NEWSAPI_BASE = "https://newsapi.org/v2/everything"

# Sydney AEST = UTC+10; during AEDT (Oct–Apr) clocks are UTC+11
# The daily cron runs at 22:00 UTC which equals 08:00 AEST / 09:00 AEDT
SYDNEY_TZ = timezone(timedelta(hours=10))


# ─── Validation ────────────────────────────────────────────────────────────────
def validate_config() -> None:
    missing = [
        k for k, v in {
            "NEWSAPI_KEY": NEWSAPI_KEY,
            "ANTHROPIC_API_KEY": ANTHROPIC_API_KEY,
            "GMAIL_USER": GMAIL_USER,
            "GMAIL_APP_PASSWORD": GMAIL_APP_PASSWORD,
            "RECIPIENT_EMAIL": RECIPIENT_EMAIL,
        }.items()
        if not v
    ]
    if missing:
        print(f"[Error] Missing env vars: {', '.join(missing)}")
        sys.exit(1)


# ─── News Fetching ─────────────────────────────────────────────────────────────
def fetch_news(query: str, hours_back: int = 24, page_size: int = 10) -> list[dict]:
    """Fetch articles from NewsAPI for the given query and time window."""
    from_time = (datetime.utcnow() - timedelta(hours=hours_back)).strftime("%Y-%m-%dT%H:%M:%SZ")
    params = {
        "q": query,
        "from": from_time,
        "sortBy": "relevancy",
        "language": "en",
        "pageSize": page_size,
        "apiKey": NEWSAPI_KEY,
    }
    try:
        resp = requests.get(NEWSAPI_BASE, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") != "ok":
            print(f"  [NewsAPI] Error: {data.get('message', 'unknown')}")
            return []
        return [
            {
                "title": a.get("title") or "",
                "description": a.get("description") or "",
                "source": (a.get("source") or {}).get("name", ""),
                "url": a.get("url") or "",
                "publishedAt": a.get("publishedAt") or "",
            }
            for a in data.get("articles", [])
            # Filter out removed/deleted articles
            if a.get("title") and "[Removed]" not in (a.get("title") or "")
        ]
    except requests.RequestException as e:
        print(f"  [NewsAPI] Request failed: {e}")
        return []


def fetch_all_news(hours_back: int = 24) -> dict[str, list[dict]]:
    """Fetch news for all three monitored categories."""
    print(f"  Fetching Trump news...")
    trump = fetch_news(
        "(Trump) AND (tariff OR policy OR sanction OR executive OR statement OR speech OR order OR deal)",
        hours_back=hours_back,
        page_size=10,
    )
    print(f"  Fetching AI news...")
    ai_news = fetch_news(
        '(OpenAI OR "Google Gemini" OR Anthropic OR "GPT-5" OR "AI model" OR "large language model") AND (launch OR release OR announce OR update OR funding OR breakthrough)',
        hours_back=hours_back,
        page_size=10,
    )
    print(f"  Fetching crypto news...")
    crypto = fetch_news(
        "(Bitcoin OR Ethereum OR cryptocurrency OR BTC OR ETH) AND (price OR regulation OR market OR ETF OR SEC OR rally OR crash OR adopt)",
        hours_back=hours_back,
        page_size=10,
    )
    print(f"  Found: Trump={len(trump)}, AI={len(ai_news)}, Crypto={len(crypto)}")
    return {"trump": trump, "ai": ai_news, "crypto": crypto}


# ─── Helpers ───────────────────────────────────────────────────────────────────
def format_articles(articles: list[dict]) -> str:
    """Format article list as readable text for Claude prompts."""
    if not articles:
        return "（暂无相关新闻）"
    lines = []
    for i, a in enumerate(articles, 1):
        date = a["publishedAt"][:10] if a["publishedAt"] else ""
        lines.append(
            f"{i}. 【{a['source']}】{date}\n"
            f"   标题：{a['title']}\n"
            f"   摘要：{a['description'][:200] or '（无摘要）'}"
        )
    return "\n\n".join(lines)


def extract_html(text: str) -> str:
    """Strip markdown code fences from Claude output if present."""
    text = text.strip()
    text = re.sub(r"^```(?:html)?\s*\n?", "", text)
    text = re.sub(r"\n?```\s*$", "", text)
    return text.strip()


def wrap_email_html(body: str) -> str:
    """Wrap inner HTML in a minimal valid document shell."""
    return (
        '<!DOCTYPE html>\n'
        '<html lang="zh">\n'
        '<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        '</head>\n'
        '<body style="margin:0;padding:0;background-color:#f9f9f9;">\n'
        f'{body}\n'
        '</body>\n'
        '</html>'
    )


# ─── Claude: Daily Report ──────────────────────────────────────────────────────
def generate_daily_report(news: dict[str, list[dict]]) -> str:
    """Ask Claude to generate a full HTML daily briefing."""
    sydney_now = datetime.now(SYDNEY_TZ)
    date_str = sydney_now.strftime("%Y年%m月%d日")
    time_str = sydney_now.strftime("%Y-%m-%d %H:%M 悉尼时间")

    prompt = f"""你是一名专业财经与科技分析师。根据以下过去24小时的英文新闻，用中文生成完整的每日情报简报。

# 原始新闻数据

## 特朗普相关新闻
{format_articles(news["trump"])}

## AI圈动态
{format_articles(news["ai"])}

## 加密货币动态
{format_articles(news["crypto"])}

---

# 输出要求

**只输出HTML代码，不含任何markdown包裹或额外解释文字。**

使用以下精确的HTML结构（全部inline style，确保邮件客户端兼容）：

<div style="background-color:#f9f9f9;padding:24px 0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
  <div style="max-width:600px;margin:0 auto;background:#ffffff;">

    <!-- Header -->
    <div style="border-top:4px solid #e86c1f;padding:28px 32px 20px;">
      <h1 style="margin:0 0 6px;font-size:22px;color:#1a1a1a;font-weight:700;">每日情报简报</h1>
      <p style="margin:0;font-size:13px;color:#888;">{date_str}</p>
    </div>

    <!-- 今日摘要 -->
    <div style="padding:20px 32px 24px;border-top:1px solid #eeeeee;">
      <h2 style="margin:0 0 12px;font-size:16px;color:#1a1a1a;font-weight:600;">📋 今日摘要</h2>
      <p style="margin:0;font-size:15px;color:#333333;line-height:1.8;">[100字以内的当天最重要1-2件事]</p>
    </div>

    <!-- 特朗普板块 -->
    <div style="padding:20px 32px 24px;border-top:1px solid #eeeeee;">
      <h2 style="margin:0 0 16px;font-size:16px;color:#1a1a1a;font-weight:600;">🇺🇸 特朗普动态</h2>
      [每条新闻：标题用 p font-weight:600 color:#1a1a1a + 分析正文 font-size:14px color:#555555 line-height:1.8]
    </div>

    <!-- AI板块 -->
    <div style="padding:20px 32px 24px;border-top:1px solid #eeeeee;">
      <h2 style="margin:0 0 16px;font-size:16px;color:#1a1a1a;font-weight:600;">🤖 AI圈动态</h2>
      [同上结构]
    </div>

    <!-- 加密板块 -->
    <div style="padding:20px 32px 24px;border-top:1px solid #eeeeee;">
      <h2 style="margin:0 0 16px;font-size:16px;color:#1a1a1a;font-weight:600;">💰 加密货币动态</h2>
      [同上结构]
    </div>

    <!-- 投资者关注 -->
    <div style="padding:20px 32px 24px;border-top:1px solid #eeeeee;">
      <h2 style="margin:0 0 16px;font-size:16px;color:#1a1a1a;font-weight:600;">⚠️ 投资者重点关注</h2>
      <div style="border-left:3px solid #e86c1f;background:#fffaf5;padding:16px 20px;">
        [2-3个关键变量/风险点]
      </div>
    </div>

    <!-- Footer -->
    <div style="padding:16px 32px 28px;border-top:1px solid #eeeeee;text-align:center;">
      <p style="margin:0;font-size:12px;color:#aaaaaa;">AI生成 · {time_str}</p>
    </div>

  </div>
</div>

# 每个板块的内容要求

**今日摘要**：100字以内，精炼概括当天1-2件最重要的事。

**特朗普板块** — 每条新闻单独展开，包含：
- 事件背景（这件事的来龙去脉）
- 具体言论或政策内容（引用关键表述）
- 为什么值得关注（影响范围）
- 对市场/地缘政治的影响预判

**AI圈板块** — 每条新闻分析：
- 技术意义或商业影响
- 对行业格局的影响
- 不只是复述标题，要有独到见解

**加密货币板块** — 结合市场情绪：
- 分析对BTC/ETH价格的具体影响方向
- 监管、机构动向等关键驱动力
- 短期vs长期影响判断

**投资者重点关注** — 2-3个具体的关键变量或风险点，语言有操作指向，例如"关注X是否在Y时间内突破Z水位"。

**总字数要求：中文内容不少于1000字，每个板块都要有实质性分析。**"""

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    resp = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    html_body = extract_html(resp.content[0].text)
    return wrap_email_html(html_body)


# ─── Claude: Breaking News Detection ──────────────────────────────────────────
def check_breaking_news(news: dict[str, list[dict]]) -> tuple[bool, str]:
    """Ask Claude whether any article qualifies as major breaking news."""
    snippets = []
    for category, articles in news.items():
        label = {"trump": "特朗普", "ai": "AI", "crypto": "加密货币"}[category]
        for a in articles[:5]:
            desc = (a["description"] or "")[:120]
            snippets.append(f"[{label}] {a['title']} — {desc}")

    if not snippets:
        return False, ""

    prompt = f"""以下是过去2小时内抓取的新闻标题和摘要：

{chr(10).join(snippets)}

判断这些新闻中是否存在**重大突发事件**（会立即影响股市、加密货币市场或全球格局的事件）。

重大事件判断标准（满足其一即是）：
- 加密货币价格剧烈波动（±10%以上）或大型交易所/协议暴雷
- 重大监管政策突然宣布（SEC诉讼、美联储紧急决议、各国央行重大表态）
- 特朗普宣布重大关税/制裁/军事行动/重大外交突破
- AI领域颠覆性产品发布或重大安全/伦理事件（如AGI突破声明）
- 重大地缘政治危机升级（战争、核威胁、大国冲突）
- 全球性金融风险事件（银行危机、主权债务违约）

**只输出以下JSON格式，不要其他任何内容：**
{{"is_breaking": true或false, "reason": "触发原因中文描述（50字以内）或null", "article_title": "触发文章英文标题或null"}}"""

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    resp = client.messages.create(
        model=MODEL,
        max_tokens=256,
        messages=[{"role": "user", "content": prompt}],
    )
    try:
        raw = resp.content[0].text.strip()
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            result = json.loads(match.group())
            return bool(result.get("is_breaking")), result.get("reason") or ""
    except (json.JSONDecodeError, AttributeError):
        print(f"  [Claude] JSON parse failed: {resp.content[0].text[:200]}")
    return False, ""


# ─── Claude: Breaking News Report ─────────────────────────────────────────────
def generate_breaking_report(news: dict[str, list[dict]], reason: str) -> str:
    """Generate an HTML breaking news alert email."""
    sydney_now = datetime.now(SYDNEY_TZ)
    time_str = sydney_now.strftime("%Y-%m-%d %H:%M 悉尼时间")

    sections = []
    for category, articles in news.items():
        if articles:
            label = {"trump": "特朗普", "ai": "AI", "crypto": "加密货币"}[category]
            sections.append(f"### {label}相关新闻\n{format_articles(articles[:3])}")
    articles_text = "\n\n".join(sections)

    prompt = f"""你是专业财经分析师。检测到重大突发事件，立即生成紧急提醒邮件。

**触发原因**：{reason}

**相关新闻**：
{articles_text}

---

**只输出HTML代码，不含markdown包裹。**

使用以下结构（inline style）：

<div style="background-color:#f9f9f9;padding:24px 0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
  <div style="max-width:600px;margin:0 auto;background:#ffffff;">

    <!-- Header：红色顶线 -->
    <div style="border-top:4px solid #cc0000;padding:28px 32px 20px;">
      <h1 style="margin:0 0 6px;font-size:22px;color:#cc0000;font-weight:700;">🚨 突发新闻提醒</h1>
      <p style="margin:0;font-size:13px;color:#888;">{time_str}</p>
    </div>

    <!-- 事件标题 -->
    <div style="padding:8px 32px 20px;">
      <h2 style="margin:0;font-size:18px;color:#1a1a1a;font-weight:700;">[用一句话概括核心事件]</h2>
    </div>

    <!-- 正文 -->
    <div style="padding:0 32px 28px;">
      [详细分析内容，font-size:15px color:#333333 line-height:1.8]
    </div>

    <!-- Footer -->
    <div style="padding:16px 32px 28px;border-top:1px solid #eeeeee;text-align:center;">
      <p style="margin:0;font-size:12px;color:#aaaaaa;">AI生成 · {time_str}</p>
    </div>

  </div>
</div>

# 正文内容要求（总字数不少于200字）

按以下顺序展开：
1. **事件概述**（2-3句，说清楚发生了什么）
2. **事件背景**（来龙去脉，为什么这件事重要）
3. **市场影响分析**（对BTC/ETH价格、股市的潜在影响方向，给出判断）
4. **投资者注意事项**（需要密切关注哪些后续指标或动向）

写作要求：语言简洁有力，数据具体，分析有深度，帮助读者在5分钟内理解事件全貌并做出初步判断。"""

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    resp = client.messages.create(
        model=MODEL,
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )
    html_body = extract_html(resp.content[0].text)
    return wrap_email_html(html_body)


# ─── Email ─────────────────────────────────────────────────────────────────────
def send_email(subject: str, html: str) -> None:
    """Send an HTML email via Gmail SMTP SSL."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = GMAIL_USER
    msg["To"] = RECIPIENT_EMAIL
    msg.attach(MIMEText(html, "html", "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        smtp.sendmail(GMAIL_USER, RECIPIENT_EMAIL, msg.as_string())

    print(f"  [Email] Sent ✓  Subject: {subject}")


# ─── Entry Points ──────────────────────────────────────────────────────────────
def run_daily() -> None:
    print("[Daily] Fetching past 24h news...")
    news = fetch_all_news(hours_back=24)

    print("[Daily] Generating report with Claude (this takes ~30s)...")
    html = generate_daily_report(news)

    sydney_now = datetime.now(SYDNEY_TZ)
    subject = f"📰 每日情报简报 · {sydney_now.strftime('%Y年%m月%d日')}"

    print("[Daily] Sending email...")
    send_email(subject, html)
    print("[Daily] Done.")


def run_breaking() -> None:
    print("[Breaking] Fetching past 2h news...")
    news = fetch_all_news(hours_back=2)

    total = sum(len(v) for v in news.values())
    if total == 0:
        print("[Breaking] No articles found. Nothing to check.")
        return

    print(f"[Breaking] Checking {total} articles with Claude...")
    is_breaking, reason = check_breaking_news(news)

    if not is_breaking:
        print("[Breaking] No major events detected.")
        return

    print(f"[Breaking] Major event detected: {reason}")
    print("[Breaking] Generating alert email...")
    html = generate_breaking_report(news, reason)

    sydney_now = datetime.now(SYDNEY_TZ)
    subject = f"🚨 突发新闻提醒 · {sydney_now.strftime('%m月%d日 %H:%M')}"
    send_email(subject, html)
    print("[Breaking] Alert sent.")


if __name__ == "__main__":
    validate_config()
    mode = sys.argv[1] if len(sys.argv) > 1 else "daily"
    if mode == "daily":
        run_daily()
    elif mode == "breaking":
        run_breaking()
    else:
        print(f"[Error] Unknown mode '{mode}'. Use: daily | breaking")
        sys.exit(1)
