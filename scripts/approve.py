#!/usr/bin/env python3
"""
Signal Watch Approve — runs when Prof Dr Tan closes a "Signal Watch candidates"
issue. Reads which checkboxes he ticked, pulls the matching entries from the
pending JSON file, injects ONLY those into index.html (Signal Watch panel) or
book.html (as a flagged addendum), pushes, comments back on the issue with what
was published, and re-labels it. Anything left unchecked is discarded silently.
"""
import json, os, re, base64, urllib.request, urllib.error

GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
REPO = os.environ["GITHUB_REPOSITORY"]
ISSUE_NUMBER = os.environ["ISSUE_NUMBER"]
ISSUE_BODY = os.environ["ISSUE_BODY"]

def gh_api(method, path, payload=None, raw=False):
    url = f"https://api.github.com{path}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "signal-watch-approve",
    })
    with urllib.request.urlopen(req) as r:
        return json.load(r)

def find_pending_path(body):
    m = re.search(r"Source file:\s*`([^`]+)`", body)
    if not m:
        raise RuntimeError("Could not find pending file path in issue body")
    return m.group(1)

def parse_approved_indices(body):
    # Matches "- [x] Approve item N" (case-insensitive x)
    approved = []
    for m in re.finditer(r"-\s\[[xX]\]\s*Approve item (\d+)", body):
        approved.append(int(m.group(1)) - 1)
    return approved

def get_file(path):
    d = gh_api("GET", f"/repos/{REPO}/contents/{path}")
    content = base64.b64decode(d["content"]).decode("utf-8")
    return content, d["sha"]

def put_file(path, content, sha, message):
    payload = {
        "message": message,
        "content": base64.b64encode(content.encode("utf-8")).decode("utf-8"),
        "sha": sha,
    }
    return gh_api("PUT", f"/repos/{REPO}/contents/{path}", payload)

SIGNAL_WATCH_MARKER = '<p style="font-size:0.72rem;color:var(--text-muted);margin-top:12px;line-height:1.5;">This panel updates when a new Signal Watch digest is run and rolled in'

def inject_signal_watch(entry):
    content, sha = get_file("index.html")
    color = "var(--red)" if entry.get("confidence") == "high" else "var(--gold)"
    src_html = ""
    if entry.get("sources"):
        src_html = " Sources: " + ", ".join(
            f'<a href="{s["url"]}" style="color:inherit;">{s["name"]}</a>' for s in entry["sources"]
        )
    block = (
        f'  <div style="padding:0.7rem 0.9rem;background:var(--bg);border:1px solid var(--border);'
        f'border-left:3px solid {color};border-radius:0 4px 4px 0;font-size:0.78rem;'
        f'color:var(--text-dim);margin-bottom:10px;">\n'
        f'    <strong style="color:{color};">{entry["headline"]}</strong> — {entry.get("date","")}: '
        f'{entry["body"]}{src_html}\n  </div>\n'
    )
    idx = content.find(SIGNAL_WATCH_MARKER)
    if idx == -1:
        raise RuntimeError("Signal Watch marker not found in index.html")
    new_content = content[:idx] + block + "\n  " + content[idx:]
    put_file("index.html", new_content, sha, f"Signal Watch (approved): {entry['headline']}")

CH_MARKER = "<!-- CHAPTER 3 -->"

def inject_chapter_note(entry):
    content, sha = get_file("book.html")
    src_html = ""
    if entry.get("sources"):
        src_html = " Sources: " + ", ".join(
            f'<a href="{s["url"]}">{s["name"]}</a>' for s in entry["sources"]
        )
    block = (
        f'<p class="read-en" data-zh="">'
        f'<strong>{entry["headline"]} ({entry.get("date","")}):</strong> {entry["body"]}{src_html}</p>\n\n'
    )
    idx = content.find(CH_MARKER)
    if idx == -1:
        raise RuntimeError("Chapter 3 marker not found in book.html")
    new_content = content[:idx] + block + content[idx:]
    put_file("book.html", new_content, sha, f"Book addendum (approved): {entry['headline']}")

def comment_and_close(published, skipped):
    lines = ["**Signal Watch — approval processed**", ""]
    if published:
        lines.append("Published:")
        for e in published:
            lines.append(f"- {e['headline']} → `{e.get('target','signal_watch')}`")
    else:
        lines.append("Nothing was checked — no items published.")
    if skipped:
        lines.append("")
        lines.append("Discarded (not checked): " + ", ".join(e["headline"] for e in skipped))
    body = "\n".join(lines)
    gh_api("POST", f"/repos/{REPO}/issues/{ISSUE_NUMBER}/comments", {"body": body})
    gh_api("PATCH", f"/repos/{REPO}/issues/{ISSUE_NUMBER}", {"labels": ["signal-watch-published"]})

def main():
    pending_path = find_pending_path(ISSUE_BODY)
    approved_idx = set(parse_approved_indices(ISSUE_BODY))
    raw, _ = get_file(pending_path)
    candidates = json.loads(raw)

    published, skipped = [], []
    for i, entry in enumerate(candidates):
        if i in approved_idx:
            if entry.get("target") == "chapter":
                inject_chapter_note(entry)
            else:
                inject_signal_watch(entry)
            published.append(entry)
        else:
            skipped.append(entry)

    comment_and_close(published, skipped)
    print(f"Published {len(published)}, discarded {len(skipped)}")

if __name__ == "__main__":
    main()
