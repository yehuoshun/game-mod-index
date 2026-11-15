#!/usr/bin/env python3
"""game-mod-index 维护脚本。

子命令：
  sync    拉取 GitHub 元数据 -> data/latest.json（数据没变就不写）
  render  由 mods/*.yaml + data/latest.json -> README.md
  all     sync + render（日常就用这个）
  check   校验 mods/*.yaml 与 config.yaml
  add     向 mods/<游戏>.yaml 追加一条登记

环境变量：
  GITHUB_TOKEN  设了走认证（5000 次/小时），不设走匿名（60 次/小时）
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
MODS_DIR = ROOT / "mods"
DATA_FILE = ROOT / "data" / "latest.json"
CONFIG_FILE = ROOT / "config.yaml"
TEMPLATE_FILE = ROOT / "templates" / "README.md.tpl"
README_FILE = ROOT / "README.md"

SCHEMA_VERSION = 1
API = "https://api.github.com"

KIND_LABELS = {
    "mod": "mod",
    "lib": "前置库",
    "template": "模板",
    "example": "示例",
    "tool": "工具",
}
LIFECYCLES = ("active", "paused", "archived")
TABLE_ORDERS = ("newest_first", "oldest_first")
SORT_NOTES = {
    "newest_first": "主表格按「最后更新」从新到旧排列；久未更新的不在这张表里比早晚，看上面「需要关注」区块。",
    "oldest_first": "主表格按「多久没更新」从久到近排列，最久没动的永远排在最前面。",
}

STATUS_META = {
    "active": ("✅", "活跃"),
    "watch": ("🟡", "低频"),
    "stale": ("⏳", "停滞"),
    "dead": ("🪦", "疑似废弃"),
    "archived": ("📦", "已归档"),
    "paused": ("💤", "已暂停"),
    "unknown": ("❓", "待核查"),
}

ATTENTION_TIPS = {
    "stale": "看一眼上游 API/依赖有没有变；还能跑就先放着，或把 config 阈值调宽",
    "dead": "确认是否弃坑：要继续就动手改一次，确定不做了把 lifecycle 改成 archived 留档",
    "archived": "仓库已被作者归档：找替代品，或把 lifecycle 改成 archived 留档",
    "unknown": "拉不到数据：检查仓库是否改名/删除，修正 repo 字段",
}

ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
REPO_RE = re.compile(r"^[\w.-]+/[\w.-]+$")


# ---------------------------------------------------------------- 基础工具


def warn(msg: str) -> None:
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print(f"::warning::{msg}")
    print(f"[warn] {msg}", file=sys.stderr)


def say(msg: str) -> None:
    print(msg)


def read_text(path: Path) -> str:
    """读文本，容忍 UTF-8 BOM —— Windows 上手工编辑很容易带上 BOM。"""
    return path.read_text(encoding="utf-8-sig")


def esc(value) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ").strip()


def parse_dt(value):
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def local_date(value, tz):
    """把 ISO 时间串 / YYYY-MM-DD 转成给定时区下的日期；解析不了返回 None。"""
    if not value:
        return None
    dt = parse_dt(value)
    if dt is not None:
        return dt.astimezone(tz).date()
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError:
        return None


def fmt_days(days) -> str:
    if days is None:
        return "—"
    if days <= 0:
        return "今天"
    return f"{days} 天"


def fmt_release(meta) -> str:
    rel = (meta or {}).get("latest_release") or {}
    tag = rel.get("tag")
    return esc(tag) if tag else "—"


# ---------------------------------------------------------------- 读配置与数据


def load_config() -> dict:
    raw = yaml.safe_load(read_text(CONFIG_FILE)) or {}
    fresh = raw.get("freshness") or {}
    cfg = {
        "freshness": {
            "active_within_days": int(fresh.get("active_within_days", 30)),
            "watch_within_days": int(fresh.get("watch_within_days", 90)),
            "stale_within_days": int(fresh.get("stale_within_days", 180)),
        },
        "utc_offset_hours": float(raw.get("utc_offset_hours", 8)),
        "timezone_label": raw.get("timezone_label", "UTC+8"),
        "table_order": str(raw.get("table_order") or "newest_first").strip().lower(),
        "games": raw.get("games") or {},
    }
    return cfg


def tz_of(cfg) -> timezone:
    return timezone(timedelta(hours=cfg["utc_offset_hours"]))


def load_mods(cfg) -> list[dict]:
    entries: list[dict] = []
    for path in sorted(MODS_DIR.glob("*.yaml")):
        game = path.stem
        data = yaml.safe_load(read_text(path)) or []
        if not isinstance(data, list):
            raise SystemExit(f"{path.relative_to(ROOT)}: 顶层必须是列表（一条一个 mod）")
        for index, raw in enumerate(data, 1):
            if not isinstance(raw, dict):
                raise SystemExit(f"{path.relative_to(ROOT)}: 第 {index} 条不是字典")
            entry = dict(raw)
            entry["_file"] = path.name
            entry["_game"] = (entry.get("game") or game).strip()
            entry["_index"] = index
            entries.append(entry)
    return entries


def load_data() -> dict:
    if not DATA_FILE.exists():
        return {"schema": SCHEMA_VERSION, "synced_at": None, "mods": {}}
    try:
        return json.loads(read_text(DATA_FILE))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"data/latest.json 解析失败：{exc}") from exc


def write_data(data: dict) -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    DATA_FILE.write_text(text, encoding="utf-8", newline="\n")


# ---------------------------------------------------------------- GitHub


def gh_get(path: str, token, allow_404: bool = False):
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "game-mod-index",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(API + path, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8")), resp.headers
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:300]
        if exc.code == 404 and allow_404:
            return None, exc.headers
        if exc.code in (403, 429) and exc.headers.get("X-RateLimit-Remaining") == "0":
            reset = exc.headers.get("X-RateLimit-Reset")
            hint = ""
            if reset:
                when = datetime.fromtimestamp(int(reset), timezone.utc).astimezone()
                hint = f"，额度重置于 {when:%Y-%m-%d %H:%M}"
            raise RuntimeError(f"GitHub API 限流（匿名 60 次/小时，设 GITHUB_TOKEN 可到 5000）{hint}") from exc
        raise RuntimeError(f"GET {path} -> HTTP {exc.code}：{body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"GET {path} 网络失败：{exc.reason}") from exc


def fetch_meta(repo: str, token) -> dict:
    info, _ = gh_get(f"/repos/{repo}", token)
    meta = {
        "repo": repo,
        "html_url": info.get("html_url") or f"https://github.com/{repo}",
        "pushed_at": info.get("pushed_at"),
        "default_branch": info.get("default_branch"),
        "stars": info.get("stargazers_count", 0),
        "forks": info.get("forks_count", 0),
        "open_issues": info.get("open_issues_count", 0),
        "archived": bool(info.get("archived")),
        "language": info.get("language"),
        "license": (info.get("license") or {}).get("spdx_id"),
        "error": None,
    }

    try:
        commits, _ = gh_get(f"/repos/{repo}/commits?per_page=1", token)
        if commits:
            meta["last_commit_at"] = commits[0]["commit"]["committer"]["date"]
    except RuntimeError as exc:
        warn(f"{repo}：取最后提交失败（{exc}）")

    try:
        rel, _ = gh_get(f"/repos/{repo}/releases/latest", token, allow_404=True)
        meta["latest_release"] = (
            {"tag": rel.get("tag_name"), "published_at": rel.get("published_at")} if rel else None
        )
    except RuntimeError as exc:
        warn(f"{repo}：取最新发行失败（{exc}）")
        meta["latest_release"] = None

    return meta


# ---------------------------------------------------------------- 状态判定


def bucket_for(days, cfg) -> str:
    if days is None:
        return "unknown"
    f = cfg["freshness"]
    if days <= f["active_within_days"]:
        return "active"
    if days <= f["watch_within_days"]:
        return "watch"
    if days <= f["stale_within_days"]:
        return "stale"
    return "dead"


@dataclass
class Row:
    entry: dict
    meta: dict
    status: str
    days: int | None
    attention: bool

    @property
    def name(self) -> str:
        return self.entry.get("name") or self.entry.get("id")

    @property
    def url(self) -> str:
        return self.meta.get("html_url") or self.entry.get("url") or ""

    @property
    def game(self) -> str:
        return self.entry["_game"]


def build_rows(cfg, entries, data) -> list[Row]:
    tz = tz_of(cfg)
    synced = parse_dt(data.get("synced_at"))
    ref_date = (synced.astimezone(tz).date() if synced else datetime.now(tz).date())
    meta_map = data.get("mods") or {}
    rows: list[Row] = []

    for entry in entries:
        meta = meta_map.get(entry.get("id")) or {}
        lifecycle = str(entry.get("lifecycle") or "active").strip().lower()

        if lifecycle == "archived":
            status, attention = "archived", False
        elif lifecycle == "paused":
            status, attention = "paused", False
        elif meta.get("archived"):
            status, attention = "archived", True
        elif meta.get("error"):
            status, attention = "unknown", True
        else:
            status = meta.get("status") or "unknown"
            attention = status in ("stale", "dead")

        source = meta.get("pushed_at") or entry.get("last_checked")
        when = local_date(source, tz)
        days = (ref_date - when).days if when else None
        rows.append(Row(entry=entry, meta=meta, status=status, days=days, attention=attention))

    return rows


# ---------------------------------------------------------------- 渲染


def status_badge(key: str) -> str:
    icon, label = STATUS_META.get(key, STATUS_META["unknown"])
    return f"{icon} {label}"


def summary_cell(row: Row) -> str:
    parts = []
    summary = esc(row.entry.get("summary") or "")
    if summary:
        parts.append(summary)
    for link in row.entry.get("links") or []:
        if isinstance(link, dict) and link.get("url"):
            parts.append(f"[{esc(link.get('label') or '链接')}]({link['url']})")
    return " · ".join(parts) if parts else "—"


def upstream_cell(row: Row) -> str:
    if row.entry.get("repo"):
        return esc(row.entry["repo"])
    return "手工登记"


def render_attention(rows: list[Row], cfg) -> str:
    items = [r for r in rows if r.attention]
    if not items:
        return "> 🎉 当前没有需要关注的条目：没有超过阈值的 mod，也没有拉不到数据的仓库。"

    items.sort(key=lambda r: (-(r.days if r.days is not None else 10**6), r.name.lower()))
    lines = [
        f"> 共 **{len(items)}** 条需要关注，按「多久没动」从久到近排列。",
        "",
        "| 状态 | Mod | 最后更新 | 未更新 | 该做什么 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in items:
        updated = (row.meta.get("last_commit_at") or row.meta.get("pushed_at") or "")
        when = local_date(updated, tz_of(cfg))
        when_text = when.isoformat() if when else "—"
        lines.append(
            "| {status} | {name} | {when} | {days} | {tip} |".format(
                status=status_badge(row.status),
                name=f"[{esc(row.name)}]({row.url})" if row.url else esc(row.name),
                when=when_text,
                days=fmt_days(row.days),
                tip=ATTENTION_TIPS.get(row.status, "看一眼"),
            )
        )
    return "\n".join(lines)


def table_sort_key(row: Row, cfg):
    """主表格排序：newest_first 新→旧（默认），oldest_first 旧→新；拉不到数据的永远垫底。"""
    days = row.days
    if days is None:
        return (1, 0, row.name.lower())
    sign = -1 if cfg.get("table_order", "newest_first") == "oldest_first" else 1
    return (0, sign * days, row.name.lower())


def render_tables(rows: list[Row], cfg) -> str:
    games = cfg["games"]
    order = list(games.keys())
    for row in rows:
        if row.game not in order:
            order.append(row.game)

    blocks: list[str] = []
    for game in order:
        group = [r for r in rows if r.game == game]
        if not group:
            continue
        # 排序由 config.yaml 的 table_order 决定（新→旧 或 旧→新）
        group.sort(key=lambda r: table_sort_key(r, cfg))
        meta = games.get(game) or {}
        title = meta.get("title") or game
        subtitle = meta.get("subtitle")
        heading = f"### {title}" + (f" · {subtitle}" if subtitle else "") + f"  `{game}`"
        lines = [
            heading,
            "",
            "| Mod | 类型 | 上游 | 最后更新 | 未更新 | 状态 | 最新版 | 说明 |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        for row in group:
            updated = row.meta.get("last_commit_at") or row.meta.get("pushed_at")
            when = local_date(updated, tz_of(cfg))
            kind = row.entry.get("kind") or "mod"
            lines.append(
                "| {name} | {kind} | {up} | {when} | {days} | {status} | {rel} | {desc} |".format(
                    name=f"[{esc(row.name)}]({row.url})" if row.url else esc(row.name),
                    kind=esc(KIND_LABELS.get(kind, kind)),
                    up=upstream_cell(row),
                    when=when.isoformat() if when else "—",
                    days=fmt_days(row.days),
                    status=status_badge(row.status),
                    rel=fmt_release(row.meta),
                    desc=summary_cell(row),
                )
            )
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) if blocks else "_还没有登记任何 mod。_"


def render_stats(rows: list[Row]) -> str:
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.status] = counts.get(row.status, 0) + 1
    order = ["active", "watch", "stale", "dead", "archived", "paused", "unknown"]
    chunks = [f"{status_badge(k)} {counts[k]}" for k in order if counts.get(k)]
    return " · ".join(chunks) if chunks else "—"


def render_thresholds(cfg) -> str:
    f = cfg["freshness"]
    a, w, s = f["active_within_days"], f["watch_within_days"], f["stale_within_days"]
    return "\n".join(
        [
            "| 状态 | 判据 |",
            "| --- | --- |",
            f"| ✅ 活跃 | 最后更新在 {a} 天内 |",
            f"| 🟡 低频 | {a + 1}–{w} 天没更新 |",
            f"| ⏳ 停滞 | {w + 1}–{s} 天没更新 |",
            f"| 🪦 疑似废弃 | 超过 {s} 天没更新 |",
            f"| 📦 已归档 | 仓库被归档，或你手动标了 `lifecycle: archived` |",
            "",
            f"阈值写在 `config.yaml` 的 `freshness`，改一行就生效（当前 {a}/{w}/{s} 天）。",
        ]
    )


def render_readme(cfg, rows: list[Row], data: dict) -> str:
    tz = tz_of(cfg)
    synced = parse_dt(data.get("synced_at"))
    if synced:
        stamp = synced.astimezone(tz).strftime("%Y-%m-%d %H:%M")
        stamp = f"{stamp}（{cfg['timezone_label']}）"
    else:
        stamp = "尚未核查"

    games = {row.game for row in rows}
    order = cfg.get("table_order", "newest_first")
    replacements = {
        "DATA_STAMP": stamp,
        "SORT_NOTE": SORT_NOTES.get(order, SORT_NOTES["newest_first"]),
        "MOD_COUNT": str(len(rows)),
        "GAME_COUNT": str(len(games)),
        "STATS_LINE": render_stats(rows),
        "ATTENTION_BLOCK": render_attention(rows, cfg),
        "MOD_TABLES": render_tables(rows, cfg),
        "THRESHOLDS": render_thresholds(cfg),
    }

    text = read_text(TEMPLATE_FILE)
    for key, value in replacements.items():
        text = text.replace("{{" + key + "}}", value)
    return text


# ---------------------------------------------------------------- 子命令


def cmd_sync(args) -> int:
    cfg = load_config()
    entries = load_mods(cfg)
    data = load_data()
    prev_mods = data.get("mods") or {}
    tz = tz_of(cfg)
    now = datetime.now(timezone.utc)
    today = now.astimezone(tz).date()
    token = args.token or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")

    if not token:
        warn("未设置 GITHUB_TOKEN，走匿名 60 次/小时；登记多了会不够用。")

    new_mods: dict[str, dict] = {}
    changed: list[str] = []
    failures = 0

    for entry in entries:
        mid = entry.get("id")
        repo = str(entry.get("repo") or "").strip()
        prev = prev_mods.get(mid) or {}

        if repo:
            try:
                meta = fetch_meta(repo, token)
            except Exception as exc:  # noqa: BLE001 - 单条失败不该中断整轮
                failures += 1
                meta = dict(prev)
                meta["repo"] = repo
                meta["html_url"] = prev.get("html_url") or f"https://github.com/{repo}"
                meta["error"] = f"{type(exc).__name__}: {exc}"
                warn(f"{mid}：拉取 {repo} 失败，沿用上次数据（{meta['error']}）")
        else:
            meta = dict(prev)
            meta["repo"] = None
            meta["html_url"] = entry.get("url") or prev.get("html_url")
            meta["error"] = None
            meta.setdefault("pushed_at", None)

        meta["first_seen"] = prev.get("first_seen") or today.isoformat()

        source = meta.get("pushed_at") or entry.get("last_checked")
        when = local_date(source, tz)
        days = (today - when).days if when else None
        meta["status"] = bucket_for(days, cfg)

        if json.dumps(meta, sort_keys=True, ensure_ascii=False) != json.dumps(
            prev, sort_keys=True, ensure_ascii=False
        ):
            changed.append(mid)
        new_mods[mid] = meta

    removed = [mid for mid in prev_mods if mid not in new_mods]
    if removed:
        say(f"从登记表移除：{', '.join(removed)}")

    if not changed and not removed and data.get("schema") == SCHEMA_VERSION:
        say("数据无变化，data/latest.json 保持不动。")
        return 0

    data["schema"] = SCHEMA_VERSION
    data["synced_at"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    data["mods"] = new_mods
    write_data(data)
    say(f"已更新 data/latest.json（变化 {len(changed)} 条{'，失败 ' + str(failures) + ' 条' if failures else ''}）")
    if changed:
        say("  " + ", ".join(changed))
    return 0


def cmd_render(args) -> int:
    cfg = load_config()
    entries = load_mods(cfg)
    data = load_data()
    rows = build_rows(cfg, entries, data)
    text = render_readme(cfg, rows, data)

    if args.check:
        current = read_text(README_FILE) if README_FILE.exists() else ""
        if current != text:
            say("README.md 与数据不一致，请执行：python scripts/modindex.py render")
            return 1
        say("README.md 已是最新。")
        return 0

    README_FILE.write_text(text, encoding="utf-8", newline="\n")
    say(f"已重写 README.md（{len(rows)} 条 mod）")
    return 0


def cmd_all(args) -> int:
    code = cmd_sync(args)
    if code:
        return code
    return cmd_render(args)


def cmd_check(args) -> int:
    cfg = load_config()
    f = cfg["freshness"]
    problems: list[str] = []

    if not (f["active_within_days"] < f["watch_within_days"] < f["stale_within_days"]):
        problems.append(
            "config.yaml: freshness 阈值必须递增"
            f"（当前 {f['active_within_days']}/{f['watch_within_days']}/{f['stale_within_days']}）"
        )

    entries = load_mods(cfg)
    if not entries:
        problems.append("mods/ 下没有任何登记")

    if cfg.get("table_order") not in TABLE_ORDERS:
        problems.append(
            f"config.yaml: table_order「{cfg.get('table_order')}」只能是 {'/'.join(TABLE_ORDERS)}"
        )

    seen_ids: dict[str, str] = {}
    seen_links: dict[str, str] = {}

    for entry in entries:
        where = f"{entry['_file']} 第 {entry['_index']} 条"
        mid = entry.get("id")
        if not mid:
            problems.append(f"{where}: 缺 id")
        elif not ID_RE.match(str(mid)):
            problems.append(f"{where}: id「{mid}」只能用小写字母/数字/._-")
        elif mid in seen_ids:
            problems.append(f"{where}: id「{mid}」与 {seen_ids[mid]} 重复")
        else:
            seen_ids[mid] = where

        if not entry.get("name"):
            problems.append(f"{where}: 缺 name")

        kind = entry.get("kind") or "mod"
        if kind not in KIND_LABELS:
            problems.append(f"{where}: kind「{kind}」只能是 {'/'.join(KIND_LABELS)}")

        lifecycle = str(entry.get("lifecycle") or "active").lower()
        if lifecycle not in LIFECYCLES:
            problems.append(f"{where}: lifecycle「{lifecycle}」只能是 {'/'.join(LIFECYCLES)}")

        repo = entry.get("repo")
        if repo:
            if not REPO_RE.match(str(repo)):
                problems.append(f"{where}: repo「{repo}」应为 owner/name")
            if repo in seen_links:
                problems.append(f"{where}: repo「{repo}」与 {seen_links[repo]} 重复")
            seen_links[repo] = where
        elif not entry.get("url"):
            problems.append(f"{where}: 既没有 repo 也没有 url")
        elif not entry.get("last_checked"):
            problems.append(f"{where}: 非 GitHub 条目需要手填 last_checked（YYYY-MM-DD）")

        if entry["_game"] not in cfg.get("games", {}):
            problems.append(f"{where}: 游戏「{entry['_game']}」没在 config.yaml 的 games 里登记标题")

    if problems:
        say(f"校验未通过（{len(problems)} 项）：")
        for item in problems:
            say(f"  - {item}")
        return 1

    say(f"校验通过：{len(entries)} 条登记，分布在 {len({e['_game'] for e in entries})} 个游戏。")
    return 0


def _scalar(value: str) -> str:
    text = str(value)
    if not text:
        return '""'
    if re.match(r"^[\w\u4e00-\u9fff][\w\u4e00-\u9fff .,/（）()·:+%-]*$", text) and not text.endswith(" "):
        if text.lower() not in {"true", "false", "null", "yes", "no", "on", "off"} and not re.match(
            r"^[\d.]+$", text
        ):
            return text
    return json.dumps(text, ensure_ascii=False)


def cmd_add(args) -> int:
    cfg = load_config()
    path = MODS_DIR / f"{args.game}.yaml"
    if not path.exists():
        raise SystemExit(f"{path.name} 不存在：先建 mods/{args.game}.yaml 并写好表头注释")

    mid = args.id or re.sub(r"[^a-z0-9]+", "-", str(args.name).lower()).strip("-")
    if not mid or not ID_RE.match(mid):
        raise SystemExit(f"id「{mid}」不合法：只能小写字母/数字/._-，用 --id 指定")
    if not (args.repo or args.url):
        raise SystemExit("至少给 --repo（GitHub 仓库）或 --url（其他链接）")

    existing = {str(e.get("id")) for e in load_mods(cfg)}
    if mid in existing:
        raise SystemExit(f"id「{mid}」已存在")

    lines = [f"- id: {mid}", f"  name: {_scalar(args.name)}"]
    if args.repo:
        lines.append(f"  repo: {args.repo}")
    if args.url:
        lines.append(f"  url: {args.url}")
    lines.append(f"  kind: {args.kind}")
    lines.append(f"  lifecycle: {args.lifecycle}")
    if args.summary:
        lines.append(f"  summary: {_scalar(args.summary)}")
    if args.tags:
        lines.append(f"  tags: [{', '.join(args.tags)}]")
    if not args.repo:
        today = datetime.now(tz_of(cfg)).date().isoformat()
        lines.append(f"  last_checked: {args.last_checked or today}")
    block = "\n".join(lines) + "\n"

    text = read_text(path)
    if not text.endswith("\n"):
        text += "\n"
    path.write_text(text + block, encoding="utf-8", newline="\n")

    load_mods(cfg)  # 追加后立刻解析一次，语法错就当场炸
    say(f"已追加到 mods/{args.game}.yaml：")
    say(block.rstrip())
    say("下一步：python scripts/modindex.py all")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="modindex", description="game-mod-index 维护脚本")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_sync = sub.add_parser("sync", help="拉取 GitHub 元数据")
    p_sync.add_argument("--token", help="GitHub token（默认读 GITHUB_TOKEN）")
    p_sync.set_defaults(func=cmd_sync)

    p_render = sub.add_parser("render", help="重生成 README.md")
    p_render.add_argument("--check", action="store_true", help="只检查 README 是否最新，不写文件")
    p_render.set_defaults(func=cmd_render)

    p_all = sub.add_parser("all", help="sync + render")
    p_all.add_argument("--token", help="GitHub token（默认读 GITHUB_TOKEN）")
    p_all.add_argument("--check", action="store_true", help=argparse.SUPPRESS)
    p_all.set_defaults(func=cmd_all)

    p_check = sub.add_parser("check", help="校验 mods/*.yaml 与 config.yaml")
    p_check.set_defaults(func=cmd_check)

    p_add = sub.add_parser("add", help="追加一条登记")
    p_add.add_argument("--game", required=True, help="游戏 key，对应 mods/<game>.yaml")
    p_add.add_argument("--name", required=True, help="显示名")
    p_add.add_argument("--repo", help="GitHub 仓库 owner/name")
    p_add.add_argument("--url", help="非 GitHub 链接")
    p_add.add_argument("--id", help="唯一 id（默认由 name 推导）")
    p_add.add_argument("--kind", default="mod", choices=list(KIND_LABELS))
    p_add.add_argument("--lifecycle", default="active", choices=list(LIFECYCLES))
    p_add.add_argument("--summary", help="一句话说明")
    p_add.add_argument("--tags", nargs="*", help="标签，空格分隔")
    p_add.add_argument("--last-checked", help="非 GitHub 条目的检查日期 YYYY-MM-DD")
    p_add.set_defaults(func=cmd_add)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001 - 老环境没有 reconfigure 就算了
        pass
    sys.exit(main())
