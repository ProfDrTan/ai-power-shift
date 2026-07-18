#!/usr/bin/env python3
"""
Signal Watch Scout — runs daily via GitHub Actions.
Asks Claude (with web_search) to find genuinely new AI infrastructure /
compute / chip / geopolitics developments in the last ~48h relevant to
the AI Power Shift book's thesis, produces up to 6 candidate entries,
writes them to pending/candidates-<date>.json, opens a GitHub Issue for
Prof Dr Tan's approval, and pings Telegram. Nothing touches index.html
or book.html until a human approves via the Issue.
"""
import json, os, re, sys, urllib.request, datetime

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
REPO = os.environ["GITHUB_REPOSITORY"]  # e.g. ProfDrTan/ai-power-shift
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

TODAY = datetime.date.today().isoformat()

PROMPT = """You are a research scout for a nonfiction book called "AI Power Shift" \
(a live, continuously-updated web book about the economics and geopolitics of the \
AI infrastructure buildout — chip supply chains, hyperscaler capex, sovereign AI \
policy, export controls, US-China AI rivalry and coalition-building, model releases \
that shift the competitive landscape).

Search the web for genuinely new developments (roughly the last 48 hours) in:
- AI infrastructure / compute / data-center capex
- Chip export controls and semiconductor supply chains
- Major model releases that shift competitive/geopolitical balance
- AI geopolitics: US/China rivalry, coalition-building (e.g. Pax Silica, WAICO), \
sovereign AI policy
- AI capital markets moves that reveal something structural (not routine stock moves)

Only include items that are:
1. Genuinely new (not something already widely known before this week)
2. Structurally significant to the book's thesis, not routine product news
3. Backed by at least one credible source you can name

Return ONLY valid JSON (no markdown fences, no preamble), an array of up to 6 objects, \
each with these exact keys:
  "headline": short punchy title (under 10 words)
  "date": the event's date, ISO format
  "body": 2-4 sentences, written in analytical prose suitable for a book's running \
"Signal Watch" panel — paraphrase everything, no verbatim quotes over ~12 words, cite \
sources by name inline (e.g. "Reuters reported...")
  "sources": array of {"name": "...", "url": "..."} for every source cited
  "target": either "signal_watch" (short blurb, index.html panel) or "chapter" \
(if it's substantial enough to warrant deeper book treatment)
  "confidence": "high" | "medium" | "low" — your honest confidence that the facts \
here are accurate and well-corroborated, not just one outlet's framing

If you find fewer than 6 items that meet the bar, return fewer. Do not pad with \
routine news to hit 6. If you find zero qualifying items, return an empty array [].
"""

def call_claude():
    body = json.dumps({
        "model": "claude-sonnet-4-6",
        "max_tokens": 4000,
        "messages": [{"role": "user", "content": PROMPT}],
        "tools": [{"type": "web_search_20250305", "name": "web_search"}]
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=body,
        headers={
            "Content-Type": "application/json",
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        data = json.load(r)
    # Concatenate all text blocks (web_search produces tool_use/tool_result blocks too)
    text_parts = [b["text"] for b in data.get("content", []) if b.get("type") == "text"]
    raw = "\n".join(text_parts).strip()
    # Strip markdown fences defensively
    raw = re.sub(r"^```(json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Try to locate the first [ ... ] block
        m = re.search(r"\[.*\]", raw, re.DOTALL)
        if m:
            return json.loads(m.group(0))
        raise

def gh_api(method, path, payload=None):
    url = f"https://api.github.com{path}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "signal-watch-scout",
    })
    with urllib.request.urlopen(req) as r:
        return json.load(r)

def commit_pending_file(candidates):
    path = f"pending/candidates-{TODAY}.json"
    content_b64 = __import__("base64").b64encode(
        json.dumps(candidates, indent=2).encode("utf-8")
    ).decode("utf-8")
    payload = {
        "message": f"Signal Watch scout: {len(candidates)} candidates for {TODAY}",
        "content": content_b64,
    }
    try:
        gh_api("PUT", f"/repos/{REPO}/contents/{path}", payload)
    except urllib.error.HTTPError as e:
        print("Commit failed:", e.read().decode())
        raise
    return path

def open_issue(candidates, pending_path):
    lines = [
        f"**Signal Watch Scout — {TODAY}**",
        "",
        f"{len(candidates)} candidate update(s) found. Check the boxes for the ones "
        "you approve, then close this issue — approved items will be published "
        "automatically. Unchecked items are discarded.",
        "",
        f"_Source file: `{pending_path}`_",
        "",
    ]
    for i, c in enumerate(candidates):
        conf = c.get("confidence", "unknown")
        lines.append(f"### {i+1}. {c['headline']} ({c.get('date','')}) — confidence: {conf}")
        lines.append(f"- [ ] Approve item {i+1}")
        lines.append("")
        lines.append(f"> {c['body']}")
        lines.append("")
        lines.append(f"**Target:** `{c.get('target','signal_watch')}`")
        srcs = c.get("sources", [])
        if srcs:
            lines.append("**Sources:** " + ", ".join(f"[{s['name']}]({s['url']})" for s in srcs))
        lines.append("")
    body = "\n".join(lines)
    issue = gh_api("POST", f"/repos/{REPO}/issues", {
        "title": f"Signal Watch candidates — {TODAY}",
        "body": body,
        "labels": ["signal-watch-pending"],
    })
    return issue

def notify_telegram(issue_url, n):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram not configured, skipping notification.")
        return
    text = (
        f"🔔 Signal Watch: {n} new candidate update(s) ready for your review.\n"
        f"Check the boxes for what you approve, then close the issue:\n{issue_url}"
    )
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = json.dumps({"chat_id": TELEGRAM_CHAT_ID, "text": text}).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=15)
    except Exception as e:
        print("Telegram notify failed (non-fatal):", e)

def main():
    candidates = call_claude()
    if not candidates:
        print("No qualifying candidates today. Exiting quietly.")
        return
    pending_path = commit_pending_file(candidates)
    issue = open_issue(candidates, pending_path)
    notify_telegram(issue["html_url"], len(candidates))
    print(f"Done. Issue: {issue['html_url']}")

if __name__ == "__main__":
    main()
