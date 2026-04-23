"""マイク入力をリアルタイムでFFT解析し、チャイム(2音)を検出する。

チャイムのF1→F2が時系列で現れたらNotifier経由で通知する。
検知後はCOOLDOWN_SECの間は再通知しない。ピーク周波数だけでなく、
スペクトル平坦度とピーク優位性の双方を用いて、タイピング等の広帯域ノイズを
弾くようにしている。

環境変数:
  CHIME_DEBUG=1        閾値を超えた全フレームの peak 周波数を表示
  CHIME_DRY_RUN=1      通知を送らず、検知ログのみ出力
  CHIME_RMS=0.003      エネルギー閾値を上書き
  CHIME_FLATNESS=0.3   平坦度しきい値(これ以上はノイズ扱い)
  CHIME_PROM=8         ピーク優位性の下限
"""

import os
import queue
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import sounddevice as sd

from .features import SpectralFeatures, extract_features
from .notifiers import Notifier, build_notifier_from_env
from .profile import ChimeProfile, DEFAULT_PROFILE_PATH


@dataclass
class DetectorConfig:
    sample_rate: int = 44100
    block_size: int = 2048  # 約46ms / 周波数分解能 ~21.5Hz
    freq_min: float = 150.0
    freq_max: float = 4000.0
    cooldown_sec: float = 10.0
    energy_threshold: float = 0.003
    flatness_max: float = 0.30
    prominence_min: float = 8.0
    min_freq_tolerance_hz: float = 25.0
    freq_tolerance_ratio: float = 0.05
    max_freq_tolerance_ratio: float = 0.20
    f1_f2_min_gap: float = 0.03
    f1_f2_timeout_ratio: float = 2.0
    min_streak_frames: int = 2
    debug: bool = False
    dry_run: bool = False
    notify_message: str = "🔔 チャイムが鳴りました"

    @classmethod
    def from_env(cls, profile: ChimeProfile | None = None) -> "DetectorConfig":
        """環境変数を読む。プロファイルが与えられれば推奨値をデフォルトに使う。"""
        if profile is not None:
            default_flat = profile.suggested_flatness_max
            default_prom = profile.suggested_prominence_min
        else:
            default_flat = 0.30
            default_prom = 8.0

        return cls(
            energy_threshold=float(os.getenv("CHIME_RMS", "0.003")),
            flatness_max=float(os.getenv("CHIME_FLATNESS", str(default_flat))),
            prominence_min=float(os.getenv("CHIME_PROM", str(default_prom))),
            debug=os.getenv("CHIME_DEBUG", "0") == "1",
            dry_run=os.getenv("CHIME_DRY_RUN", "0") == "1",
        )


class ChimeDetector:
    """プロファイルと設定に従ってストリーム上のチャイム音を検出する。"""

    def __init__(
        self,
        profile: ChimeProfile,
        config: DetectorConfig,
        notifier: Notifier,
    ) -> None:
        self.profile = profile
        self.config = config
        self.notifier = notifier

        self.interval = max(profile.interval, 0.1)
        self.f1_tol = self._tolerance(profile.f1, profile.f1_std)
        self.f2_tol = self._tolerance(profile.f2, profile.f2_std)

        print(
            f"   許容幅: F1={profile.f1:.0f}±{self.f1_tol:.0f}Hz "
            f"F2={profile.f2:.0f}±{self.f2_tol:.0f}Hz"
        )
        print(
            f"   RMS={config.energy_threshold} "
            f"flat≤{config.flatness_max} prom≥{config.prominence_min} "
            f"F1→F2タイムアウト={self.interval * config.f1_f2_timeout_ratio:.2f}s"
        )
        print(
            f"   DEBUG={config.debug} DRY_RUN={config.dry_run} "
            f"COOLDOWN={config.cooldown_sec}s"
        )

        self._f1_seen_at: float | None = None
        self._last_notify_at: float | None = None
        self._last_debug_log = 0.0
        self._streak_label = "-"
        self._streak = 0

    def _tolerance(self, center: float, std: float) -> float:
        c = self.config
        return min(
            max(c.min_freq_tolerance_hz, center * c.freq_tolerance_ratio, std * 2),
            center * c.max_freq_tolerance_ratio,
        )

    def _classify(self, features: SpectralFeatures) -> str:
        c = self.config
        if features.flatness > c.flatness_max or features.prominence < c.prominence_min:
            return "-"
        if abs(features.peak_freq - self.profile.f1) <= self.f1_tol:
            return "F1"
        if abs(features.peak_freq - self.profile.f2) <= self.f2_tol:
            return "F2"
        return "-"

    def process(self, block: np.ndarray, now: float) -> None:
        c = self.config
        in_cooldown = (
            self._last_notify_at is not None
            and now - self._last_notify_at < c.cooldown_sec
        )

        feats = extract_features(
            block, c.sample_rate, c.freq_min, c.freq_max
        )

        if feats.rms < c.energy_threshold:
            if (
                self._f1_seen_at is not None
                and now - self._f1_seen_at > self.interval * c.f1_f2_timeout_ratio
            ):
                self._f1_seen_at = None
            return

        label = self._classify(feats)

        if c.debug and now - self._last_debug_log > 0.1:
            state = (
                "CD" if in_cooldown
                else ("F1待ち" if self._f1_seen_at is None else "F2待ち")
            )
            tonal = (
                "✓" if feats.flatness <= c.flatness_max
                and feats.prominence >= c.prominence_min else "✗"
            )
            print(
                f"[{now:7.2f}s] peak={feats.peak_freq:6.1f}Hz "
                f"rms={feats.rms:.3f} flat={feats.flatness:.2f} "
                f"prom={feats.prominence:6.1f} {tonal} {label:2s} state={state}"
            )
            self._last_debug_log = now

        if label == self._streak_label:
            self._streak += 1
        else:
            self._streak_label = label
            self._streak = 1

        if in_cooldown:
            return

        confirmed = label if self._streak >= c.min_streak_frames else "-"

        if confirmed == "F1":
            if self._f1_seen_at is None:
                print(
                    f"[{now:7.2f}s] ▶ F1確定 peak={feats.peak_freq:.1f}Hz "
                    f"rms={feats.rms:.3f}"
                )
            self._f1_seen_at = now
            return

        if confirmed == "F2" and self._f1_seen_at is not None:
            dt = now - self._f1_seen_at
            if c.f1_f2_min_gap <= dt <= self.interval * c.f1_f2_timeout_ratio:
                print(
                    f"[{now:7.2f}s] 🔔 チャイム検知! "
                    f"F1→F2 dt={dt:.2f}s peak={feats.peak_freq:.1f}Hz"
                )
                self._trigger(now)
                self._f1_seen_at = None
            return

        if (
            self._f1_seen_at is not None
            and now - self._f1_seen_at > self.interval * c.f1_f2_timeout_ratio
        ):
            self._f1_seen_at = None

    def _trigger(self, now: float) -> None:
        self._last_notify_at = now
        if self.config.dry_run:
            print("   (DRY_RUN: 通知はスキップ)")
            return
        self.notifier.send(self.config.notify_message)


def run(profile_path: str | Path = DEFAULT_PROFILE_PATH) -> None:
    profile = ChimeProfile.load(profile_path)
    print(
        f"📋 プロファイル: F1={profile.f1:.1f}Hz "
        f"F2={profile.f2:.1f}Hz 間隔={profile.interval:.2f}s"
    )

    config = DetectorConfig.from_env(profile)
    notifier = build_notifier_from_env()
    detector = ChimeDetector(profile, config, notifier)

    audio_q: queue.Queue[tuple[int, np.ndarray]] = queue.Queue()
    samples_seen = 0

    def callback(indata, frames, time_info, status):  # noqa: ANN001
        nonlocal samples_seen
        if status:
            print(f"⚠️ stream status: {status}", file=sys.stderr)
        audio_q.put((samples_seen, indata[:, 0].copy()))
        samples_seen += frames

    print("🎤 検知開始 (Ctrl+Cで終了)\n")
    with sd.InputStream(
        samplerate=config.sample_rate,
        blocksize=config.block_size,
        channels=1,
        dtype="float32",
        callback=callback,
    ):
        try:
            while True:
                sample_idx, block = audio_q.get()
                now = (sample_idx + len(block) / 2) / config.sample_rate
                detector.process(block, now)
        except KeyboardInterrupt:
            print("\n👋 終了します")


if __name__ == "__main__":
    run()
