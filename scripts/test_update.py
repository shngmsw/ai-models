import unittest
from datetime import datetime, timezone

import update

NOW = datetime(2026, 11, 17, tzinfo=timezone.utc)


def ts(date):
    return int(datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())


def orm(mid, name, date, out=("text",), exp=None):
    return {"id": mid, "name": name, "created": ts(date),
            "architecture": {"output_modalities": list(out)}, "expiration_date": exp}


def arena(name, org, rating, rank, category="overall"):
    return {"model_name": name, "organization": org, "rating": rating, "rank": rank,
            "category": category, "leaderboard_publish_date": "2026-11-11"}


OR = [
    orm("openai/gpt-6.1-terra", "OpenAI: GPT-6.1 Terra", "2026-10-26"),
    orm("openai/gpt-6.1-terra:batch", "OpenAI: GPT-6.1 Terra (batch)", "2026-10-26"),
    orm("openai/gpt-oss-120b", "OpenAI: gpt-oss-120b", "2025-08-05"),
    orm("openai/gpt-5-image", "OpenAI: GPT-5 Image", "2025-10-14", out=("image", "text")),
    orm("openai/gpt-5", "OpenAI: GPT-5", "2025-08-07", exp="2026-11-01"),
    orm("anthropic/claude-opus-5.5", "Anthropic: Claude Opus 5.5", "2026-09-22"),
    orm("anthropic/claude-opus-5", "Anthropic: Claude Opus 5", "2026-07-24"),
    orm("anthropic/claude-opus-4.1", "Anthropic: Claude Opus 4.1", "2025-08-05"),
    orm("google/gemini-3.5-flash-lite", "Google: Gemini 3.5 Flash Lite", "2026-07-21"),
    orm("google/gemini-2.5-pro", "Google: Gemini 2.5 Pro", "2025-06-17"),
    orm("google/gemma-4-31b-it", "Google: Gemma 4 31B", "2026-04-02"),
    orm("x-ai/grok-4.7", "SpaceXAI: Grok 4.7", "2026-09-21"),
    orm("meta/muse-ember", "Meta: Muse Ember", "2026-11-09"),
    orm("meta-llama/llama-4-scout", "Meta: Llama 4 Scout", "2025-04-05"),
]
ARENA = [
    arena("Claude Opus 5.5 (High)", "anthropic", 1513.6, 3),
    arena("Claude Opus 5 (High)", "anthropic", 1502.0, 7),
    arena("Claude Opus 5 (Max)", "anthropic", 1506.5, 5),
    arena("Gemini 3.5 Flash-Lite", "google", 1435.2, 90),
    arena("Grok 4.7 (xHigh)", "xai", 1400.1, 158),
    arena("Grok 4.7 (xHigh)", "xai", 1999.0, 1, category="chinese"),
]


def by_id(data, key):
    return {m["id"]: m for p in data["providers"] if p["key"] == key for m in p["models"]}


class NormalizeTest(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(update.normalize("Anthropic: Claude Opus 5.5"), "claude opus 5.5")
        self.assertEqual(update.normalize("Claude Opus 4.5 (High, 32K, 20251101)"), "claude opus 4.5")
        self.assertEqual(update.normalize("Gemini 3.5 Flash-Lite"), "gemini 3.5 flash lite")
        self.assertEqual(update.normalize("Gemini 3.1 Pro Preview"), "gemini 3.1 pro")

    def test_family(self):
        self.assertEqual(update.family("Claude Opus 5.5"), "claude opus")
        self.assertEqual(update.family("OpenAI: GPT-6.1 Terra Pro"), "gpt terra pro")
        self.assertEqual(update.family("Grok 4.20 Multi-Agent"), "grok multi agent")
        self.assertEqual(update.family("o3 Pro"), "o3 pro")
        self.assertEqual(update.normalize("Muse Glimmer 30B"), update.normalize("Muse Glimmer"))


class BuildTest(unittest.TestCase):
    def setUp(self):
        self.data = update.build(OR, ARENA, None, NOW)

    def test_filters(self):
        self.assertEqual(set(by_id(self.data, "openai")), {"gpt-6.1-terra"})
        self.assertEqual(set(by_id(self.data, "google")), {"gemini-3.5-flash-lite", "gemini-2.5-pro"})
        self.assertEqual(set(by_id(self.data, "meta")), {"muse-ember"})

    def test_scores(self):
        a = by_id(self.data, "anthropic")
        self.assertEqual((a["claude-opus-5.5"]["score"], a["claude-opus-5.5"]["rank"]), (1514, 3))
        self.assertEqual((a["claude-opus-5"]["score"], a["claude-opus-5"]["rank"]), (1506, 5))
        self.assertEqual(by_id(self.data, "google")["gemini-3.5-flash-lite"]["score"], 1435)
        self.assertEqual(by_id(self.data, "xai")["grok-4.7"]["score"], 1400)
        self.assertIsNone(by_id(self.data, "meta")["muse-ember"]["score"])

    def test_current(self):
        a = by_id(self.data, "anthropic")
        self.assertTrue(a["claude-opus-5.5"]["current"])
        self.assertFalse(a["claude-opus-5"]["current"])
        self.assertFalse(by_id(self.data, "google")["gemini-2.5-pro"]["current"])  # 365日超

    def test_shape(self):
        self.assertEqual(self.data["arena_date"], "2026-11-11")
        self.assertEqual(self.data["updated_at"], "2026-11-17T00:00:00Z")
        m = by_id(self.data, "anthropic")["claude-opus-5.5"]
        self.assertEqual(set(m), {"id", "name", "released", "score", "rank", "current"})
        self.assertEqual((m["name"], m["released"]), ("Claude Opus 5.5", "2026-09-22"))

    def test_arena_failure_carries_previous_scores(self):
        data = update.build(OR, None, self.data, NOW)
        self.assertEqual(by_id(data, "anthropic")["claude-opus-5.5"]["score"], 1514)
        self.assertEqual(data["arena_date"], "2026-11-11")

    def test_arena_failure_without_previous(self):
        data = update.build(OR, None, None, NOW)
        self.assertIsNone(by_id(data, "anthropic")["claude-opus-5.5"]["score"])

    def test_empty_provider_aborts(self):
        with self.assertRaises(ValueError):
            update.build([m for m in OR if not m["id"].startswith("x-ai/")], ARENA, None, NOW)

    def test_malformed_model_is_skipped(self):
        data = update.build(OR + [{"id": "openai/gpt-x", "name": "X", "created": 1, "architecture": None}],
                            ARENA, None, NOW)
        self.assertNotIn("gpt-x", by_id(data, "openai"))


if __name__ == "__main__":
    unittest.main()
