# chime-of-chime

マイクで拾った環境音からチャイム(ピンポーン等の2音パターン)を検出し、LINE/Slackへ通知するツール。
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
# (Pi 上で)
mkdir -p ~/.config/systemd/user
cp ~/Desktop/dev/chime-of-chime/scripts/chime-detector.service ~/.config/systemd/user/

# uv のフルパスに合わせて ExecStart を編集 (`which uv` で確認)
vim ~/.config/systemd/user/chime-detector.service

systemctl --user daemon-reload
systemctl --user enable --now chime-detector.service

# ログ
journalctl --user -u chime-detector.service -f

# 状態
systemctl --user status chime-detector.service
```

### 3. SSH切断後 / 再起動後も生き残らせる

ユーザサービスはデフォルトだとログアウト時に停止します。再起動後も含めて自走させるには **linger** を有効化:

```bash
sudo loginctl enable-linger $USER
```

これで Pi をリブートしてもログイン不要で自動起動 → クラッシュ時は5秒後に自動再起動、になります。

### 4. デバイス選択 (任意)

USBマイクが複数あるとデフォルト入力が想定外になることがあります。確認:

```bash
uv run python -c "import sounddevice as sd; print(sd.query_devices())"
```

特定のデバイスに固定したいなら `~/.asoundrc` で ALSA デフォルト入力を指定するのが手軽:

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
│   └── chime-detector.service  systemdユーザサービステンプレ
└── src/
    ├── features.py          FFT / スペクトル特徴量抽出
    ├── profile.py           ChimeProfile dataclass + I/O
    ├── recorder.py          ProfileRecorder (録音→プロファイル抽出)
    ├── detector.py          ChimeDetector (リアルタイム検知)
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
