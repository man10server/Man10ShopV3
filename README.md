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

`.env` が必須です。  
まず雛形をコピーしてから値を編集してください。

```bash
cp .env.example .env
```

最低限、以下は環境に合わせて変更してください。

- `MONGODB_CONNECTION_STRING`
- `MAN10SOCKET_HOSTS`
- 必要に応じて `MAN10SOCKET_REPLY_STATE_TTL_SECONDS` / `MAN10SOCKET_DEFAULT_REPLY_TIMEOUT_SECONDS`
- 必要に応じて `MAN10SOCKET_HEARTBEAT_TIMEOUT_SECONDS`
- 必要に応じて `MAN10SOCKET_FRAMING_PROTOCOL` / `MAN10SOCKET_MAX_FRAME_BYTES`
- `HOST_PORT`
- 必要に応じて `API_ENDPOINT` / `API_KEY`

`.env.example` は Docker Compose 向けに `mongodb://mongodb:27017` を使っています。  
ローカル実行時は必要に応じて `mongodb://localhost:27017` に変更してください。

`MAN10SOCKET_HOSTS` は `name:host:port` をカンマ区切りで並べます。

```dotenv
MAN10SOCKET_HOSTS=man10:minecraft:6789,lobby:lobby-host:6790
```

`MAN10SOCKET_FRAMING_PROTOCOL` は以下を利用できます。

- `delimiter_v1`: 既存の `<E>` 区切り
- `length_prefix_v2`: 4 バイト長さプレフィックス + UTF-8 JSON

`length_prefix_v2` は接続先 Minecraft プラグイン側も同じプロトコルに対応している必要があります。

`MAN10SOCKET_HEARTBEAT_TIMEOUT_SECONDS` は、heartbeat対応が確認された接続で受信が途絶えてから
切断・再接続するまでの秒数です。既定値は `6` で、`0` を指定するとapplication heartbeatを
無効化します（TCP keepaliveは有効なままです）。有効時は `6`〜`300` 秒の範囲で指定してください。
接続先がheartbeatで通知した監視時間とローカル設定のうち、長い方をその接続の監視時間にします。

Minecraft側は2秒間隔で一方向のheartbeatを送ります。API側は再接続処理と独立した250ms周期の
watchdogで監視し、最初のtimeoutでは直ちに再接続を試みます。各接続先は専用の再接続workerで
並列処理し、購読通知も応答を待たずに送るため、別の接続先のtimeoutには巻き込まれません。
TCP接続のtimeoutも2秒のため、接続先が応答できる通常の経路ではhalf-open発生からおおむね
10秒以内の復旧を狙う設定です。

heartbeat timeout後はanti-flapping probationへ入り、60秒間安定するまで監視時間を15秒へ
緩和します。その間にtimeoutや確立済み接続のFIN/RSTが再発した場合は、再接続待ちをjitter付きで
最大30秒まで増やします。繰り返しflapしている間は安定性を優先するため、10秒以内の復旧対象外です。
60秒間連続してheartbeatを受信すると、監視時間と再接続待ちは通常値へ戻ります。
heartbeat未対応または無効化した接続では、120秒間TCP接続が維持された時点でprobationを解除します。

API側からMinecraft側への経路はTCP keepaliveと40秒のTCP user timeoutでも監視します。
ログはtimeout、再接続確認、probationの開始・終了といった状態変化時だけ出力し、正常なheartbeat
ごとには出力しません。

## 起動

```bash
uv run python main.py
```

## Docker buildx

マルチアーキ（`linux/amd64,linux/arm64`）のビルドスクリプトを用意しています。

```bash
./scripts/docker-buildx.sh --push -i shojabon/man10shopv3 -t latest
```

ローカルに取り込む場合（`--load`）は単一アーキのみ指定してください。

```bash
./scripts/docker-buildx.sh --load -p linux/amd64 -i man10shopv3-dev -t local
```

## Docker Compose (サンプル)

`docker-compose.yaml` は `app` と `mongodb` のみ起動します。  
`.env` の `MAN10SOCKET_HOSTS` は実サーバー向けに変更してください。

## Docker 起動トラブルシュート

`.venv/bin/python: no such file or directory` が出る場合は、古いイメージを使っている可能性があります。  
以下で再ビルドしてください。

```bash
docker compose down
docker compose build --no-cache app
docker compose up -d
```

## 補足

- 依存定義は `pyproject.toml`、ロックは `uv.lock` を利用します。
