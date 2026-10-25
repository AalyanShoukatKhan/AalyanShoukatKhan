#!/usr/bin/env python3
"""Refresh the auto-generated parts of the profile from the GitHub API.

Updates, inside README.md:   stats, all (repository table), bylang (grouped list)
Writes:                      assets/languages.svg (language chart)

Standard library only. If anything fails, nothing is modified, so a bad
API day never breaks the profile.
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from html import escape

USER = os.environ.get("GH_USER", "AalyanShoukatKhan")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
# Repositories to hide (lowercase names). The profile repo is always hidden.
EXCLUDE = {USER.lower(), "codealpha_tasks."}
MAX_TABLE = 20
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
README = os.path.join(ROOT, "README.md")
LANG_SVG = os.path.join(ROOT, "assets", "languages.svg")

COLORS = {"Python": "#3572A5", "C++": "#F34B7D", "C": "#8B949E", "C#": "#178600",
          "Java": "#B07219", "JavaScript": "#F1E05A", "TypeScript": "#3178C6",
          "HTML": "#E34C26", "CSS": "#9B6BDF", "Dart": "#00B4AB", "Shell": "#89E051",
          "Jupyter Notebook": "#DA5B0B"}
FALLBACK = "#58A6FF"


def request(url, data=None):
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "profile-readme-updater"}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def rest(path):
    return request(f"https://api.github.com{path}")


def contributions_last_year():
    """Needs a token (provided automatically inside GitHub Actions)."""
    if not TOKEN:
        return None
    query = {"query": "query($l:String!){user(login:$l){contributionsCollection{"
                      "contributionCalendar{totalContributions}}}}",
             "variables": {"l": USER}}
    try:
        out = request("https://api.github.com/graphql", json.dumps(query).encode())
        return out["data"]["user"]["contributionsCollection"]["contributionCalendar"]["totalContributions"]
    except Exception:
        return None


def cell(text):
    return (text or "").replace("|", "\\|").replace("\n", " ").strip()


def language_svg(langs):
    """Dark card with a proportional bar and a legend, in the banner's style."""
    mono = "Consolas, 'SFMono-Regular', Menlo, 'Courier New', monospace"
    total = sum(langs.values())
    head = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 190" width="900" height="190" '
            'role="img" aria-labelledby="t"><title id="t">Code by language across public repositories</title>'
            '<rect x="1" y="1" width="898" height="188" rx="14" fill="#14100A" stroke="#5A4510" stroke-width="2"/>'
            f'<text x="32" y="46" font-family="{mono}" font-size="22" fill="#E6EDF3">'
            '<tspan fill="#F5B301">$</tspan> languages --by-size</text>')
    if not total:
        return head + (f'<text x="32" y="110" font-family="{mono}" font-size="20" fill="#8B949E">'
                       'Updates automatically after the first workflow run.</text></svg>')
    top = langs.most_common(6)
    shown = sum(b for _, b in top)
    if total > shown:
        top.append(("Other", total - shown))
    bar_x, bar_w = 32, 836
    parts = ['<clipPath id="r"><rect x="32" y="66" width="836" height="22" rx="11"/></clipPath><g clip-path="url(#r)">']
    x = bar_x
    for i, (name, b) in enumerate(top):
        w = bar_w - (x - bar_x) if i == len(top) - 1 else max(4, bar_w * b / total)
        parts.append(f'<rect x="{x:.1f}" y="66" width="{w:.1f}" height="22" fill="{COLORS.get(name, FALLBACK)}"/>')
        x += w
    parts.append("</g>")
    for i, (name, b) in enumerate(top):
        col, row = i % 3, i // 3
        lx, ly = 32 + col * 284, 128 + row * 34
        pct = round(b * 100 / total)
        parts.append(f'<circle cx="{lx + 8}" cy="{ly - 7}" r="7" fill="{COLORS.get(name, FALLBACK)}"/>'
                     f'<text x="{lx + 24}" y="{ly}" font-family="{mono}" font-size="20" fill="#E6EDF3">'
                     f'{escape(name)} <tspan fill="#8B949E">{pct}%</tspan></text>')
    return head + "".join(parts) + "</svg>"


def build():
    profile = rest(f"/users/{USER}")
    repos = rest(f"/users/{USER}/repos?per_page=100&sort=pushed&type=owner")
    repos = [r for r in repos if not r["fork"] and r["name"].lower() not in EXCLUDE]
    repos.sort(key=lambda r: r["pushed_at"], reverse=True)

    langs = Counter()
    for r in repos:
        try:
            langs.update(rest(f"/repos/{r['full_name']}/languages"))
        except Exception:
            pass

    parts = [f"📦 **{len(repos)}** public repositories", f"👥 **{profile['followers']}** followers"]
    contrib = contributions_last_year()
    if contrib is not None:
        parts.append(f"🔥 **{contrib}** contributions in the last year")
    stats = " · ".join(parts)

    rows = ["| Repository | Description | Language | Updated |", "|---|---|---|---|"]
    for r in repos[:MAX_TABLE]:
        rows.append(f"| [{cell(r['name'])}]({r['html_url']}) | {cell(r['description']) or '—'} | "
                    f"{cell(r['language']) or '—'} | {r['pushed_at'][:10]} |")
    table = "\n".join(rows) if repos else "No public repositories yet."
    if len(repos) > MAX_TABLE:
        table += f"\n\n[View all {len(repos)} on GitHub →](https://github.com/{USER}?tab=repositories)"

    groups = defaultdict(list)
    for r in repos:
        groups[r["language"] or "Other"].append(f"[{cell(r['name'])}]({r['html_url']})")
    ordered = sorted(groups.items(), key=lambda kv: (kv[0] == "Other", -len(kv[1]), kv[0]))
    bylang = "\n".join(f"- **{lang}** — " + " · ".join(links) for lang, links in ordered)

    return {"stats": stats, "all": table, "bylang": bylang}, language_svg(langs)


def inject(text, name, body):
    pattern = re.compile(rf"(<!--START_SECTION:{name}-->)(.*?)(<!--END_SECTION:{name}-->)", re.S)
    if not pattern.search(text):
        raise RuntimeError(f"marker '{name}' not found in README.md")
    return pattern.sub(lambda m: f"{m.group(1)}\n{body}\n{m.group(3)}", text)


def main():
    try:
        sections, svg = build()
        with open(README, encoding="utf-8") as f:
            text = f.read()
        for name, body in sections.items():
            text = inject(text, name, body)
    except (urllib.error.URLError, RuntimeError, KeyError, ValueError) as exc:
        print(f"Skipped update, nothing changed: {exc}")
        return 0
    with open(README, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    os.makedirs(os.path.dirname(LANG_SVG), exist_ok=True)
    with open(LANG_SVG, "w", encoding="utf-8", newline="\n") as f:
        f.write(svg)
    print("README.md and assets/languages.svg refreshed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
