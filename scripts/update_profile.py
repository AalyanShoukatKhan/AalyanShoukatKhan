#!/usr/bin/env python3
"""Refresh the auto-generated sections of README.md from the GitHub API.

Uses only the Python standard library. If anything fails, README.md is left
untouched, so a bad API day never breaks the profile.
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request
from collections import Counter

USER = os.environ.get("GH_USER", "AalyanShoukatKhan")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
EXCLUDE = {USER.lower()}          # the profile repo itself; add more names here
MAX_RECENT = 4
README = os.path.join(os.path.dirname(__file__), "..", "README.md")


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


def build_sections():
    profile = rest(f"/users/{USER}")
    repos = rest(f"/users/{USER}/repos?per_page=100&sort=pushed&type=owner")
    repos = [r for r in repos if not r["fork"] and r["name"].lower() not in EXCLUDE]

    langs = Counter()
    for r in repos:
        try:
            langs.update(rest(f"/repos/{r['full_name']}/languages"))
        except Exception:
            pass
    total = sum(langs.values())

    parts = [f"**{profile['public_repos']}** public repositories",
             f"**{profile['followers']}** followers"]
    contrib = contributions_last_year()
    if contrib is not None:
        parts.append(f"**{contrib}** contributions in the last year")
    stats = " · ".join(parts)
    if total:
        mix = " ".join(f"`{n}` {round(b * 100 / total)}%" for n, b in langs.most_common(5))
        stats += f"\n\nCode by language across my public repositories: {mix}  \n"
        stats += "<sub>Share of code by size, not a measure of skill.</sub>"

    lines = []
    for r in repos[:MAX_RECENT]:
        desc = (r["description"] or "").strip()
        meta = " · ".join(x for x in (r["language"], f"updated {r['pushed_at'][:10]}") if x)
        lines.append(f"- [{r['name']}]({r['html_url']})" + (f" — {desc}" if desc else "") + f"  \n  <sub>{meta}</sub>")
    return {"stats": stats, "repos": "\n".join(lines)}


def inject(text, name, body):
    pattern = re.compile(rf"(<!--START_SECTION:{name}-->)(.*?)(<!--END_SECTION:{name}-->)", re.S)
    if not pattern.search(text):
        raise RuntimeError(f"marker '{name}' not found in README.md")
    return pattern.sub(lambda m: f"{m.group(1)}\n{body}\n{m.group(3)}", text)


def main():
    try:
        sections = build_sections()
        with open(README, encoding="utf-8") as f:
            text = f.read()
        for name, body in sections.items():
            text = inject(text, name, body)
        with open(README, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        print("README.md refreshed")
    except (urllib.error.URLError, RuntimeError, KeyError, ValueError) as exc:
        print(f"Skipped update, README.md left unchanged: {exc}")
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
