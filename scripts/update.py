#!/usr/bin/env python3
"""OpenRouter のモデル一覧と Arena の総合順位から data.json を作る。標準ライブラリのみ。"""
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

OPENROUTER_URL = "https://openrouter.ai/api/v1/models"
ARENA_URL = (
    "https://datasets-server.huggingface.co/rows"
    "?dataset=lmarena-ai%2Fleaderboard-dataset&config=text&split=latest"
    "&offset={offset}&length=100"
)
DATA_PATH = Path(__file__).resolve().parent.parent / "data.json"
CURRENT_WINDOW_DAYS = 120  # その会社の最新モデルの公開日から遡ってこの日数以内だけを現行とする

# (キー, 表示名, OpenRouter の接頭辞, 対象 ID の正規表現, Arena の organization)
PROVIDERS = [
    ("openai", "OpenAI", "openai/", r"^(gpt-(?!oss)|o\d|chatgpt-)", "openai"),
    ("anthropic", "Anthropic", "anthropic/", r"^claude-", "anthropic"),
    ("google", "Gemini", "google/", r"^gemini-", "google"),
    ("xai", "Grok", "x-ai/", r"^grok-", "xai"),
    ("meta", "Muse", "meta/", r"^muse-", "meta"),
]


def normalize(name):
    """2つの取得元の表記ゆれを吸収した照合用の名前を返す。"""
    s = name.split(": ", 1)[-1].lower()
    s = re.sub(r"\([^)]*\)", " ", s)
    s = s.replace("-", " ")
    s = re.sub(r"\b(preview|beta|\d+b)\b", " ", s)  # 30b などの規模表記も片方にしか無い
    return " ".join(s.split())


def family(name):
    """版番号を除いた系列名。例: 'Claude Opus 5.5' -> 'claude opus'"""
    s = re.sub(r"(?<![\w.])\d+(\.\d+)*(?![\w.])", " ", normalize(name))
    return " ".join(s.split())


def major(name):
    """名前に含まれる最初の版番号の整数部。例: 'Gemini 4 Carbon' -> 4。版番号が無ければ None。"""
    m = re.search(r"(?<![\w.])(\d+)(\.\d+)*(?![\w.])", normalize(name))
    return int(m.group(1)) if m else None


def arena_scores(rows):
    """organization ごとに {照合名: {score, rank}} を作る。同名は最高点を採る。"""
    out = {}
    for r in rows:
        if r.get("category") != "overall" or r.get("rating") is None:
            continue
        org = out.setdefault(r.get("organization") or "", {})
        key = normalize(r["model_name"])
        if key not in org or r["rating"] > org[key]["score"]:
            org[key] = {"score": round(r["rating"]), "rank": int(r["rank"])}
    return out


def build_provider(spec, or_models, scores, now):
    key, label, prefix, pattern, arena_org = spec
    org_scores = scores.get(arena_org, {})
    models = []
    for m in or_models:
        mid = m.get("id", "")
        if not mid.startswith(prefix) or ":" in mid:
            continue
        short = mid[len(prefix):]
        if not re.search(pattern, short) or re.search(r"customtools|contributor", short):
            continue
        if (m.get("architecture") or {}).get("output_modalities") != ["text"]:
            continue
        exp = m.get("expiration_date")
        if exp and exp[:10] < now.strftime("%Y-%m-%d"):
            continue
        name = m["name"].split(": ", 1)[-1]
        s = org_scores.get(normalize(name), {})
        models.append({
            "id": short,
            "name": name,
            "released": datetime.fromtimestamp(m["created"], timezone.utc).strftime("%Y-%m-%d"),
            "score": s.get("score"),
            "rank": s.get("rank"),
            "current": False,
            "_created": m["created"],
            "_family": family(name),
            "_major": major(name),
        })
    newest = {}
    for m in models:
        f = m["_family"]
        if f not in newest or m["_created"] > newest[f]["_created"]:
            newest[f] = m
    latest = max((m["_created"] for m in models), default=0)
    cutoff = latest - CURRENT_WINDOW_DAYS * 86400
    # 最新世代だけを現行にする。例: Gemini 4 があれば Gemini 3.x は旧モデル
    top = max((m["_major"] for m in models if m["_major"] is not None), default=None)
    for m in newest.values():
        m["current"] = m["_created"] >= cutoff and m["_major"] in (None, top)
    models.sort(key=lambda m: -m["_created"])
    for m in models:
        del m["_created"], m["_family"], m["_major"]
    return {"key": key, "label": label, "models": models}


def carry_scores(providers, previous):
    """Arena が取れなかったとき、前回の data.json の点数を引き継ぐ。"""
    old = {}
    for p in (previous or {}).get("providers", []):
        for m in p["models"]:
            old[(p["key"], m["id"])] = (m.get("score"), m.get("rank"))
    for p in providers:
        for m in p["models"]:
            m["score"], m["rank"] = old.get((p["key"], m["id"]), (None, None))


def build(or_models, arena_rows, previous, now):
    """arena_rows が None なら前回の点数を引き継ぐ。5社のどれかが0件なら ValueError。"""
    scores = arena_scores(arena_rows) if arena_rows else {}
    providers = [build_provider(s, or_models, scores, now) for s in PROVIDERS]
    empty = [p["label"] for p in providers if not p["models"]]
    if empty:
        raise ValueError("モデルが0件: " + ", ".join(empty))
    if arena_rows:
        arena_date = max((r.get("leaderboard_publish_date") or "") for r in arena_rows) or None
    else:
        carry_scores(providers, previous)
        arena_date = (previous or {}).get("arena_date")
    return {
        "updated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "arena_date": arena_date,
        "providers": providers,
    }


def fetch_json(url, tries=4):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "ai-models-updater"})
            with urllib.request.urlopen(req, timeout=60) as res:
                return json.load(res)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            if i == tries - 1:
                raise
            print(f"再試行 {i + 1}: {e}", file=sys.stderr)
            time.sleep(10 * (i + 1))


def fetch_arena():
    """総合順位の行だけを返す。総合は先頭に並んでいるので、別区分が出たら止める。"""
    rows, offset = [], 0
    while offset < 3000:
        page = [r["row"] for r in fetch_json(ARENA_URL.format(offset=offset))["rows"]]
        rows += [r for r in page if r.get("category") == "overall"]
        if len(page) < 100 or page[-1].get("category") != "overall":
            break
        offset += 100
        time.sleep(1)
    if len(rows) < 50:
        raise ValueError(f"Arena の行が少なすぎる: {len(rows)}")
    return rows


def main():
    or_models = fetch_json(OPENROUTER_URL)["data"]
    previous = json.loads(DATA_PATH.read_text()) if DATA_PATH.exists() else None
    try:
        arena_rows = fetch_arena()
    except Exception as e:  # Arena が落ちていても一覧の更新は続ける
        print(f"Arena の取得に失敗、前回の点数を引き継ぐ: {e}", file=sys.stderr)
        arena_rows = None
    data = build(or_models, arena_rows, previous, datetime.now(timezone.utc))
    DATA_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n")
    for p in data["providers"]:
        cur = [m for m in p["models"] if m["current"]]
        rated = sum(1 for m in cur if m["score"])
        print(f"{p['label']}: 全{len(p['models'])}件 / 現行{len(cur)}件 / うち点数あり{rated}件")


if __name__ == "__main__":
    main()
