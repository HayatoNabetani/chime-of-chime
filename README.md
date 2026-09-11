# chime-of-chime

マイクで拾った環境音からチャイム(ピンポーン等の2音パターン)を検出し、LINE/Slackへ通知するツール。
LINE通知には、SwitchBotでインターホン音声ボタンと玄関解錠ボタンを押すための操作を表示できます。
Mac/Linux/Raspberry Pi で動作します。

## しくみ

1. 事前にチャイム音を数回録音し、**2音の周波数(F1/F2)・時間間隔・トーナル性**をJSONに保存(= プロファイル)
2. マイクを常時ストリーミングし、短時間FFTで各ブロックの**ピーク周波数・スペクトル平坦度・ピーク優位性**を算出
3. F1が連続検出された後、一定時間内にF2が現れたら「チャイム検知」として通知
4. 検知後は10秒のクールダウン

平坦度と優位性の2指標で、タイピング音のような広帯域インパルスノイズを弾いています。

## セットアップ

```bash
# 依存関係
uv sync

# macOSでPortAudioが無い場合
brew install portaudio
# Raspberry Pi / Ubuntuの場合
sudo apt install libportaudio2

# 設定ファイルを作成
cp .env.example .env
# NOTIFIER や各種トークンを編集
```

## 使い方

### 1. 通知先の疎通確認

```bash
uv run python main.py test-notify
```

`.env`の`NOTIFIER`に応じて、LINE/Slack/コンソールのいずれかに「🔔 テスト通知…」が届きます。

### 2. プロファイル作成

```bash
uv run python main.py record
```

3回チャイムを鳴らして録音します。各録音は`recordings/sample_N.wav`に保存されるので後で確認可能。
成功すると`chime_profile.json`が生成され、最後に**推奨の検知パラメータ**が表示されます:

```
💡 誤検知が多い場合は検出器を以下の環境変数で起動してみてください:
   CHIME_FLATNESS=0.15 CHIME_PROM=50 python main.py detect
```

### 3. 検知開始

```bash
uv run python main.py detect
```

Ctrl+Cで終了。デバッグ表示を出したい場合:

```bash
CHIME_DEBUG=1 uv run python main.py detect
```

調整中に通知を飛ばしたくない時:

```bash
CHIME_DRY_RUN=1 uv run python main.py detect
```

## テスト

### 自動テスト

依存関係をインストールした後、リポジトリのルートで実行します。

```bash
uv sync
uv run python -m unittest discover -s tests -v

# Cloudflare Worker
cd worker
npm ci
npm test
```

自動テストではSwitchBot API、LINE API、マイク入力をモックしているため、実際の通知送信や
SwitchBotの物理操作は行いません。主に次の内容を確認しています。

- SwitchBot OpenAPI v1.1の署名生成、デバイス取得、ボタン押下、APIエラー処理
- LINE通知の2ボタン、Webhook署名検証、許可ユーザーの制限
- 解錠の二段階確認、60秒の有効期限、確認トークンの再利用防止
- プロファイルの保存・読み込み、録音フレームの境界処理

### 静的チェック

Ruffは`uvx`で一時実行するため、プロジェクトへの追加インストールは不要です。初回のみ
Ruffのダウンロードが発生します。

```bash
uvx ruff check src tests main.py
uvx ruff format --check src tests main.py
python -m compileall -q src tests main.py
sh -n scripts/test-switchbot
```

フォーマットを自動修正する場合:

```bash
uvx ruff check --fix src tests main.py
uvx ruff format src tests main.py
```

### SwitchBot実機テスト

最初に、物理操作を伴わないデバイス一覧・状態取得から確認します。

```bash
./scripts/test-switchbot devices
./scripts/test-switchbot status
```

続いてインターホン用Botを確認します。以下は実際にボタンを1回押します。

```bash
./scripts/test-switchbot intercom
```

最後に、安全を確認したうえで解錠用Botをテストします。`unlock`と再入力しない限り実行されません。

```bash
./scripts/test-switchbot unlock
```

### LINE連携の結合テスト

後述のCloudflare WorkerをデプロイしてLINE DevelopersのWebhook URLを設定した後、
Raspberry Piまたは開発PCからテスト通知を送信します。

```bash
uv run python main.py test-notify
```

LINEに届いた通知で次を確認します。

1. `🎧 インターホンを聞く`でインターホン用Botが1回押され、操作結果が返信される
2. `🔓 玄関を解錠`ではすぐに解錠されず、確認画面が表示される
3. 確認画面の`キャンセル`ではBotが動かない
4. 再度操作し、60秒以内に`解錠する`を選ぶと解錠用Botが1回だけ動く

Workerのログは別のターミナルで確認できます。

```bash
cd worker
npx wrangler tail
```

## 通知先の切り替え

`.env`の`NOTIFIER`で制御(カンマ区切りで複数指定可):

| 値 | 送信先 | 必要な環境変数 |
|---|---|---|
| `console` | 標準出力のみ | なし(デバッグ用) |
| `line` | LINE Messaging API | `LINE_CHANNEL_ACCESS_TOKEN`, `LINE_USER_ID` |
| `slack` | Slack Incoming Webhook | `SLACK_WEBHOOK_URL` |
| `line,slack` | LINEとSlack両方 | 上記両方 |

### LINE設定

1. [LINE Developers](https://developers.line.biz/) でMessaging APIチャネルを作成
2. チャネルアクセストークン(長期)を発行 → `LINE_CHANNEL_ACCESS_TOKEN`
3. Botと友だちになり、Webhook等で自身のUser IDを取得 → `LINE_USER_ID`

## SwitchBot操作ボタン

チャイム検知時のLINE通知には次の2ボタンが表示されます。

- `🎧 インターホンを聞く`: インターホン用Botへ`press`を送信
- `🔓 玄関を解錠`: 確認画面で「解錠する」を選んだ後、解錠用Botへ`press`を送信

### 1. SwitchBotを準備

SwitchBotアプリで、インターホン用Botと解錠用Botの両方を**押すモード**に設定し、
HubのBluetooth範囲内へ設置します。SwitchBot APIから操作するにはSwitchBot Hubが必要です。

SwitchBotアプリ（v9.0以降）の「プロフィール → 設定 → アプリについて」でアプリバージョンを
10回タップして「開発者向けオプション」を表示し、Open TokenとSecretを取得します。
各BotのDevice IDとともに`.env`へ設定してください。

```dotenv
NOTIFIER=line

LINE_CHANNEL_ACCESS_TOKEN=...
LINE_CHANNEL_SECRET=...
LINE_USER_ID=U...

SWITCHBOT_TOKEN=...
SWITCHBOT_SECRET=...
SWITCHBOT_INTERCOM_DEVICE_ID=...
SWITCHBOT_UNLOCK_DEVICE_ID=...

# WebhookはCloudflare Workerで受信するため、Pi側では起動しない
ACTION_SERVER_ENABLED=0
```

### 2. SwitchBot単体の動作確認

LINE連携より先に2台のSwitchBotを確認できます。実行ファイルを起動すると対話メニューが表示されます。

```bash
./scripts/test-switchbot
```

Device IDがまだ分からない場合は、メニューの`1. デバイス一覧を確認`で一覧を取得できます。
`.env`へ2台のIDを設定したら、`2. 設定した2台の状態を確認`で接続を確認してください。
個別コマンドとしても実行できます。

```bash
./scripts/test-switchbot devices       # アカウントのデバイス一覧
./scripts/test-switchbot status
./scripts/test-switchbot intercom      # インターホン用Botを1回押す
./scripts/test-switchbot unlock       # 実行前に確認入力あり
```

`unlock --yes`は確認なしで物理ボタンを押すため、自動テスト以外では使用を避けてください。

### 3. Cloudflare Workerをデプロイ（推奨）

LINEのpostbackは`worker/`のCloudflare Workerで受信します。Cloudflare Tunnelや独自ドメインは不要で、
デプロイ時に固定の`https://chime-of-chime-webhook.<サブドメイン>.workers.dev`が発行されます。
WorkerがLINE署名とユーザーIDを検証し、SwitchBot APIを直接呼び出します。そのため、Raspberry Piへ
外部から到達できるポートを開ける必要はありません。

参考: [Workers.dev](https://developers.cloudflare.com/workers/configuration/routing/workers-dev/)、
[LINE Webhook署名検証](https://developers.line.biz/en/docs/messaging-api/verify-webhook-signature/)

必要なものはNode.js 20以降とCloudflareアカウントです。初回だけ次を実行します。

```bash
cd worker
npm install
npx wrangler login

# D1データベースを作成し、DB bindingをwrangler.jsoncへ自動追記
npx wrangler d1 create chime-of-chime-actions --location apac --binding DB --update-config

# 二重実行防止・解錠確認用テーブルを作成
npx wrangler d1 execute chime-of-chime-actions --remote --file=./schema.sql
```

続いて秘密情報をWorker Secretsへ登録します。コマンドごとに値の入力を求められます。
値は`wrangler.jsonc`やGitには書かないでください。

```bash
npx wrangler secret put LINE_CHANNEL_ACCESS_TOKEN
npx wrangler secret put LINE_CHANNEL_SECRET
npx wrangler secret put LINE_USER_ID
npx wrangler secret put SWITCHBOT_TOKEN
npx wrangler secret put SWITCHBOT_SECRET
npx wrangler secret put SWITCHBOT_INTERCOM_DEVICE_ID
npx wrangler secret put SWITCHBOT_UNLOCK_DEVICE_ID
```

テスト後にデプロイします。

```bash
npm test
npm run deploy
```

デプロイ結果に表示されたURLへ`/line/webhook`を付け、LINE DevelopersのMessaging APIチャネルで
Webhook URLに設定します。

```text
https://chime-of-chime-webhook.<サブドメイン>.workers.dev/line/webhook
```

Webhookの「検証」を実行して成功することを確認し、「Webhookの利用」をONにします。
ヘルスチェックはブラウザまたは次のコマンドで確認できます。

```bash
curl https://chime-of-chime-webhook.<サブドメイン>.workers.dev/health
# {"ok":true}
```

最後にRaspberry Piの`.env`を次の状態にします。LINE通知の送信にはPi側にも
`LINE_CHANNEL_ACCESS_TOKEN`と`LINE_USER_ID`が必要ですが、Webhook受信用の
`LINE_CHANNEL_SECRET`とSwitchBotの秘密情報はWorker側だけでも動作します。

```dotenv
NOTIFIER=line
ACTION_SERVER_ENABLED=0
```

設定変更後は検知サービスを再起動します。

```bash
systemctl --user restart chime-detector.service
systemctl --user status chime-detector.service --no-pager -l
```

#### Workerを更新する

コードをpullしただけではデプロイ済みWorkerは更新されません。Workerに変更がある場合は次を実行します。

```bash
git pull --ff-only
cd worker
npm ci
npm test
npx wrangler deploy
```

`schema.sql`が変更された場合は、デプロイ前に次も実行します。現在のSQLは何度実行しても安全です。

```bash
npx wrangler d1 execute chime-of-chime-actions --remote --file=./schema.sql
```

ログをリアルタイム表示する場合は`npx wrangler tail`を使います。

#### ローカルPython Webhookを使う場合（代替）

Workerを使わず、従来どおりRaspberry PiのPythonサーバーをCloudflare Tunnelなどで公開することもできます。
その場合だけPiの`.env`を`ACTION_SERVER_ENABLED=1`にし、公開URLの
`https://<公開ホスト名>/line/webhook`をLINEへ設定してください。操作サーバーだけなら
`uv run python main.py serve-actions`で起動できます。

> 解錠は安全に直結する操作です。Workerは`X-Line-Signature`、`LINE_USER_ID`、60秒・1回限りの
> 解錠確認を検証します。D1によりLINEの再配信による同一イベントの二重実行も抑止します。

### Slack設定

1. [Slack API](https://api.slack.com/apps) で「Create New App」→ From scratch
2. 左メニュー「Incoming Webhooks」→ Activate
3. 「Add New Webhook to Workspace」で投稿先チャンネルを選択
4. 発行された`https://hooks.slack.com/services/...`を`SLACK_WEBHOOK_URL`に設定

## 検知パラメータ

| 環境変数 | デフォルト | 意味 |
|---|---|---|
| `CHIME_RMS` | `0.003` | マイク入力の最小音量 (RMS)。小さいほど敏感 |
| `CHIME_FLATNESS` | プロファイル依存 | スペクトル平坦度の上限。小さいほど「純音らしさ」を厳しく要求 |
| `CHIME_PROM` | プロファイル依存 | ピーク優位性の下限。大きいほど厳しい |
| `CHIME_SR` | `44100` | マイクのサンプルレート。Piでoverflowが出るなら`22050`へ |
| `CHIME_BLOCK` | `2048` | FFTブロックサイズ。大きいほどコールバック頻度が下がる |
| `CHIME_DEBUG` | `0` | `1`で全フレームの判定ログを出力 |
| `CHIME_DRY_RUN` | `0` | `1`で通知を送らず検知ログのみ出力 |

プロファイル作成時に自動で算出される推奨値が`chime_profile.json`の`suggested_*`フィールドに入り、
`detect`時のデフォルト値として使われます。環境変数で明示すると上書きできます。

## Raspberry Piで常駐させる

SSHを切ってもチャイム検知を動かし続けるには `systemd` のユーザサービスとして登録するのが楽です。
`cron @reboot` でも起動はできますが、クラッシュ時の自動再復帰やログ管理は systemd の方が圧倒的にラク。

### 1. `input overflow` 対策

```
⚠️ stream status: input overflow
```

これは PortAudio のリングバッファが Python 側の処理に追いつかれず取りこぼしている状態。
**`CHIME_BLOCK=4096` でブロックサイズを倍に**するのが最も効きます(コールバック頻度が半分になりPiのCPU負荷が大幅に下がる)。Raspberry Pi 4 + USBマイクで検証済み:

```bash
CHIME_BLOCK=4096 uv run python main.py detect
```

`InputStream(latency="high")` は既に指定済み。

> ⚠️ サンプルレートを下げる(`CHIME_SR=22050`)方法は、USBマイクが 22050Hz をネイティブサポートしていないと `paInvalidSampleRate` で起動失敗します。多くのUSBマイクは 44100/48000 のみ対応なので、まず `CHIME_BLOCK=4096` を試すのが安全。マイクの対応レートは `arecord --dump-hw-params -D plughw:<card>,<dev> /dev/null` で確認できます。

### 2. サービス登録

リポジトリ同梱の `scripts/chime-detector.service` を `~/.config/systemd/user/` に置きます:

```bash
# (Pi 上で。先にgit pullで最新化しておく)
cd ~/Desktop/dev/chime-of-chime
git pull

mkdir -p ~/.config/systemd/user
cp scripts/chime-detector.service ~/.config/systemd/user/
```

`ExecStart=` の `uv` のパスを実環境に合わせて差し替えます。Raspbian標準では vim/nano のどちらかが入っているはず(vim が無ければ `sudo apt install -y vim` でインストール、または `nano` を使ってもOK):

```bash
which uv                                              # 例: /home/hnabetani/.local/bin/uv
vim ~/.config/systemd/user/chime-detector.service     # ExecStart の /usr/bin/env uv を which uv の結果に置換
```

非対話で一発置換したい場合:

```bash
UV_PATH=$(which uv)
sed -i "s|/usr/bin/env uv|$UV_PATH|" ~/.config/systemd/user/chime-detector.service
grep ExecStart ~/.config/systemd/user/chime-detector.service   # 確認
```

サービスを起動:

```bash
systemctl --user daemon-reload
systemctl --user enable --now chime-detector.service
systemctl --user status chime-detector.service        # Active: active (running) になればOK
```

### 3. コード更新を常駐サービスへ反映

別のPCで変更をpushした後、Raspberry PiへSSH接続して次を実行します。

```bash
cd ~/Desktop/dev/chime-of-chime

# ローカルに意図しない変更がないことを確認してから更新
git status --short
git pull --ff-only

# pyproject.toml / uv.lockの変更も反映
uv sync --locked

# 実機を動かさない自動テスト
uv run python -m unittest discover -s tests -v

# 実行中のPythonプロセスは自動更新されないため、必ず再起動
systemctl --user restart chime-detector.service
systemctl --user status chime-detector.service
```

最後に起動ログを確認します。

```bash
journalctl --user -u chime-detector.service -n 50 --no-pager
```

`git pull`だけでは、すでに起動しているサービスのコードは切り替わりません。
`systemctl --user restart chime-detector.service`まで実行して反映完了です。

`.env`、`chime_profile.json`、`recordings/`はGit管理外なので、通常の`git pull`では削除・上書きされません。
`git status --short`に管理対象ファイルの変更が表示された場合は、pullする前に内容を確認してください。

`scripts/chime-detector.service`自体が更新された場合だけ、インストール済みファイルとの差分を確認し、
必要な変更を反映してからdaemon-reloadします。単純コピーすると、Pi用に調整したパスや
`CHIME_DEVICE`を上書きする可能性があります。

```bash
diff -u ~/.config/systemd/user/chime-detector.service scripts/chime-detector.service
# 必要な変更を手動反映した後
systemctl --user daemon-reload
systemctl --user restart chime-detector.service
```

### 4. SSH切断後 / 再起動後も生き残らせる

ユーザサービスはデフォルトだとログアウト時に停止します。再起動後も含めて自走させるには **linger** を有効化:

```bash
sudo loginctl enable-linger $USER
```

これで Pi をリブートしてもログイン不要で自動起動 → クラッシュ時は5秒後に自動再起動、になります。

### 5. 動作確認

実際にチャイムを鳴らして、LINE通知が飛んでくることを確認します。ログをtailしながら鳴らすのが分かりやすい:

```bash
journalctl --user -u chime-detector.service -f
```

`🔔 チャイム検知!` と `✅ LINE送信成功` が出れば完成。

### 6. 運用コマンド

```bash
systemctl --user status chime-detector.service        # 状態確認
systemctl --user restart chime-detector.service       # プロファイル更新後など
systemctl --user stop chime-detector.service          # 一時停止
systemctl --user disable --now chime-detector.service # 自動起動を解除
journalctl --user -u chime-detector.service -f        # ログtail
journalctl --user -u chime-detector.service --since today  # 今日のログ
journalctl --user -u chime-detector.service | grep overflow | wc -l  # overflowの発生件数
```

サービスに渡されている環境変数の確認:

```bash
systemctl --user show chime-detector.service -p Environment
```

### 7. トラブルシューティング

#### `No journal files were found`

`enable --now` 直後だと journal がまだ書かれていないので出ることがあります。数秒〜数十秒待ってから再度 `journalctl --user -u chime-detector.service -f` で取れるか確認。永続化されていないだけの場合は:

```bash
sudo mkdir -p /var/log/journal
sudo systemd-tmpfiles --create --prefix /var/log/journal
sudo systemctl restart systemd-journald
```

#### 起動時に1〜2件だけ `⚠️ stream status: input overflow`

PortAudioのストリーム初期化時に出る一過性の警告。継続発生していなければ無視してOK。継続発生している場合は次項。

#### `input overflow` が連続して出続ける

CPU負荷が追いついていない状態。順に試す:

1. `Environment=CHIME_BLOCK=8192` に増やす(ブロックを倍に)
2. service に `Nice=-5` を追加してプロセス優先度を上げる
3. それでもダメなら `Environment=CHIME_SR=48000` を追加(マイクが48kHz対応の場合)

編集後は `systemctl --user daemon-reload && systemctl --user restart chime-detector.service`。

#### `PortAudioError: Error querying device -1` / チャイムに無反応になった

USBマイクが**再認識でcard番号がズレ**、システムのデフォルト入力デバイスが無効になった状態。
`-1` は「デフォルト入力デバイス無し」の意味。マイク自体は生きていることが多い。常駐プロセスは
古いデバイスを掴んだまま生き続け、無音を拾って `input overflow` だけ出す（=チャイムに無反応）。

```bash
arecord -l        # card N: [USB PnP Sound Device] のように生きていれば物理脱落ではない
lsusb             # マイクがバス上に居るか
```

マイクが `arecord -l` に出るなら、デフォルト任せをやめて **`CHIME_DEVICE` で名前指定**して固定する。
名前の部分一致なので、今後 card 番号がズレても追従する:

```bash
# service に追記済み（scripts/chime-detector.service）。名前は arecord -l の [...] に合わせる
Environment="CHIME_DEVICE=USB PnP"
```

手元で素早く確認するには:

```bash
systemctl --user stop chime-detector.service          # デバイス解放
CHIME_DEVICE="USB PnP" uv run python main.py detect    # 🎙 入力デバイス: [N] ... が出ればOK
```

マイクが `arecord -l` にも出ない場合は物理脱落。**セルフパワーUSBハブ経由**で挿し直す
（Pi のポート直挿しは電力不足で脱落しやすい）。

#### `paInvalidSampleRate` で起動失敗

USBマイクが要求のサンプルレートに非対応。マイクの対応レートを確認:

```bash
arecord -l                                              # カードと device 番号
arecord --dump-hw-params -D plughw:2,0 /dev/null        # RATE: 行を確認
```

`CHIME_SR` を対応値(通常 44100 or 48000)に合わせる。

#### USBマイクが複数 / デフォルト入力が想定外

```bash
uv run python -c "import sounddevice as sd; print(sd.query_devices())"
```

特定のデバイスに固定したいなら `~/.asoundrc` で ALSA デフォルト入力を指定:

```
pcm.!default { type asym capture.pcm "plughw:2,0" }
```

(`plughw:<card>,<device>` の数字は `arecord -l` で確認)

## プロジェクト構成

```
chime-of-chime/
├── main.py                  CLIエントリー
├── .env.example             設定テンプレート
├── chime_profile.json       プロファイル (record時に生成)
├── recordings/              プロファイル作成時の録音WAV
├── pyproject.toml
├── scripts/
│   ├── chime-detector.service  systemdユーザサービステンプレ
│   └── test-switchbot          SwitchBot対話テスト実行ファイル
├── worker/                  Cloudflare Worker版LINE Webhook
│   ├── src/index.js         署名検証 / SwitchBot操作 / 解錠確認
│   ├── test/index.test.js   Worker自動テスト
│   ├── schema.sql           D1テーブル定義
│   └── wrangler.jsonc       Cloudflare設定
├── tests/
│   ├── test_actions_and_notifier.py  LINE通知 / Webhook操作テスト
│   ├── test_profile_and_recorder.py  プロファイル / 録音処理テスト
│   ├── test_switchbot.py              SwitchBot APIクライアントテスト
│   └── test_switchbot_tester.py       SwitchBotテストCLIテスト
└── src/
    ├── features.py          FFT / スペクトル特徴量抽出
    ├── profile.py           ChimeProfile dataclass + I/O
    ├── recorder.py          ProfileRecorder (録音→プロファイル抽出)
    ├── detector.py          ChimeDetector (リアルタイム検知)
    ├── switchbot.py         SwitchBot OpenAPI v1.1クライアント
    ├── switchbot_tester.py  SwitchBot単体テストCLI
    ├── action_server.py     LINE postback受信 / SwitchBot操作
    ├── notifiers.py         Notifier ABC / LINE / Slack / Console / Multi
    └── cli.py               argparse サブコマンド
```

## 配布先での新規Notifier追加

`src/notifiers.py`に`Notifier`を継承したクラスを追加し、`_build_single()`に分岐を1つ足せばOK:

```python
class DiscordNotifier(Notifier):
    def __init__(self, webhook_url: str) -> None:
        self.webhook_url = webhook_url

    def send(self, message: str) -> bool:
        res = requests.post(self.webhook_url, json={"content": message}, timeout=5)
        res.raise_for_status()
        return True


def _build_single(target: str) -> Notifier | None:
    ...
    if target == "discord":
        url = os.getenv("DISCORD_WEBHOOK_URL")
        return DiscordNotifier(url) if url else None
    ...
```

## ライセンス

MIT
