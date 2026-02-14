# Man10ShopV3

Minecraft 向けのショップ連携サービスです。  
FastAPI ベースで API を公開し、MongoDB と Man10Socket に接続して動作します。

## 前提

- `uv` がインストール済み
- MongoDB が利用可能
- 接続先 Minecraft サーバー側のソケット受け口が利用可能

## 開発環境セットアップ（uv）

1. Python 3.9 を用意

```bash
uv python install 3.9
```

2. 依存を同期（`.venv` が自動作成されます）

```bash
uv sync --python 3.9
```

3. 仮想環境を手動で使いたい場合

```bash
source .venv/bin/activate
```

### サンドボックス環境などで `uv` が権限エラーになる場合

`uv` のキャッシュ・Python 配置先をプロジェクト配下に切り替えて実行してください。

```bash
UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python uv sync --python 3.9
```

## 設定ファイル

`config/config.json` が必須です。  
まず雛形をコピーしてから値を編集してください。

```bash
cp config/config.example.json config/config.json
```

最低限、以下は環境に合わせて変更してください。

- `mongodbConnectionString`
- `man10socket.hosts`
- `hostPort`
- 必要に応じて `api.endpoint` / `api.key`

## 起動

```bash
uv run python main.py
```

## 補足

- 依存定義は `pyproject.toml`、ロックは `uv.lock` を利用します。
