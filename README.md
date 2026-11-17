# AIモデル早見表

OpenAI・Anthropic・Gemini・Grok・Muse の現行モデル名と版番号を一覧するページ。毎日 06:17 JST に GitHub Actions が自動更新する。

- 会社順（既定）と賢い順を切り替えられる。賢さの基準は Arena のテキスト総合スコア。
- モデル名を押すと API 用の ID をコピーする。
- 点数のないモデルは「未評価」と表示する。

## 仕組み

| ファイル | 役割 |
|---|---|
| `index.html` | ページ本体。`data.json` を読んで表示する |
| `data.json` | `scripts/update.py` が作る生成物。手で編集しない |
| `scripts/update.py` | OpenRouter の一覧と Arena の順位を取得して整形する |
| `.github/workflows/update.yml` | 毎日の自動更新と手動実行 |

設計の詳細は `docs/superpowers/specs/2026-11-17-ai-models-design.md`。

## 手元で動かす

```bash
cd scripts && python -m unittest test_update
```

```bash
python scripts/update.py
```

```bash
python -m http.server 8000
```

## データの出典

- モデル一覧: [OpenRouter](https://openrouter.ai/models)
- 点数: [lmarena-ai/leaderboard-dataset](https://huggingface.co/datasets/lmarena-ai/leaderboard-dataset)（CC BY 4.0）
