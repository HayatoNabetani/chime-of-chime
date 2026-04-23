"""プロファイル作成用の録音ワークフロー。

インタラクティブにマイクから複数回チャイムを録音し、
2音の周波数・時間間隔・トーナル性 (flatness / prominence) を抽出して
ChimeProfile として保存する。
"""

import wave
from dataclasses import dataclass
from pathlib import Path
from statistics import mean

import numpy as np
import sounddevice as sd

from .features import extract_features
from .profile import ChimeProfile, DEFAULT_PROFILE_PATH


@dataclass
class RecorderConfig:
    sample_rate: int = 44100
    duration: float = 4.0
    num_samples: int = 3
    freq_min: float = 150.0
    freq_max: float = 4000.0

    # フレーム切り出し
    frame_win_sec: float = 0.04
    frame_hop_sec: float = 0.02

    # 区間検出
    energy_rel_threshold: float = 0.2
    energy_abs_threshold: float = 0.005
    gap_sec: float = 0.08          # この長さの無音があれば別区間
    freq_jump_ratio: float = 0.08  # 周波数がこれ以上変わっても別区間
    min_segment_sec: float = 0.08


def save_wav(path: Path, audio: np.ndarray, sample_rate: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm.tobytes())


class ProfileRecorder:
    """マイクから複数回録音 → プロファイル抽出 → 保存までを行う。"""

    def __init__(
        self,
        config: RecorderConfig | None = None,
        output_dir: Path | None = None,
    ) -> None:
        self.config = config or RecorderConfig()
        self.output_dir = output_dir or Path("recordings")

    def record_once(self) -> np.ndarray:
        c = self.config
        print(f"  🎤 {c.duration}秒録音中...音を鳴らしてください")
        audio = sd.rec(
            int(c.duration * c.sample_rate),
            samplerate=c.sample_rate,
            channels=1,
            dtype="float32",
        )
        sd.wait()
        return audio.flatten()

    def _frame_features(self, audio: np.ndarray) -> list[dict]:
        c = self.config
        win = int(c.sample_rate * c.frame_win_sec)
        hop = int(c.sample_rate * c.frame_hop_sec)
        frames = []
        for i in range(0, len(audio) - win, hop):
            seg = audio[i : i + win]
            f = extract_features(seg, c.sample_rate, c.freq_min, c.freq_max)
            frames.append(
                {
                    "t": i / c.sample_rate,
                    "rms": f.rms,
                    "peak": f.peak_freq,
                    "flatness": f.flatness,
                    "prominence": f.prominence,
                }
            )
        return frames

    def _find_groups(self, frames: list[dict]) -> list[list[dict]]:
        c = self.config
        if not frames:
            return []
        max_rms = max(f["rms"] for f in frames)
        threshold = max(max_rms * c.energy_rel_threshold, c.energy_abs_threshold)

        groups: list[list[dict]] = []
        current: list[dict] = []
        for f in frames:
            if f["rms"] < threshold:
                if current:
                    groups.append(current)
                    current = []
                continue
            if not current:
                current = [f]
                continue
            prev = current[-1]
            time_gap = f["t"] - prev["t"]
            freq_jump = (
                abs(f["peak"] - prev["peak"]) / max(prev["peak"], 1e-6)
                if prev["peak"] > 0
                else 0
            )
            if time_gap > c.gap_sec or freq_jump > c.freq_jump_ratio:
                groups.append(current)
                current = [f]
            else:
                current.append(f)
        if current:
            groups.append(current)

        return [
            g for g in groups if (g[-1]["t"] - g[0]["t"]) >= c.min_segment_sec
        ]

    @staticmethod
    def _group_peak_freq(group: list[dict]) -> float:
        peaks = np.array([f["peak"] for f in group])
        weights = np.array([f["rms"] for f in group])
        if weights.sum() == 0:
            return float(np.median(peaks))
        return float(np.average(peaks, weights=weights))

    @staticmethod
    def _group_tonality(group: list[dict]) -> tuple[float, float]:
        flats = np.array([f["flatness"] for f in group])
        proms = np.array([f["prominence"] for f in group])
        return float(np.median(flats)), float(np.median(proms))

    def extract_sample(self, audio: np.ndarray) -> dict:
        frames = self._frame_features(audio)
        groups = self._find_groups(frames)
        print(f"    区間検出: {len(groups)}個")
        for i, g in enumerate(groups):
            print(
                f"      #{i}: {g[0]['t']:.2f}s〜{g[-1]['t']:.2f}s "
                f"peak={self._group_peak_freq(g):.1f}Hz"
            )

        if len(groups) < 2:
            raise ValueError(
                f"2つのトーンを検出できませんでした (検出区間数: {len(groups)})"
            )

        scored = sorted(groups, key=lambda g: sum(f["rms"] for f in g), reverse=True)
        top2 = sorted(scored[:2], key=lambda g: g[0]["t"])

        f1 = self._group_peak_freq(top2[0])
        f2 = self._group_peak_freq(top2[1])
        interval = top2[1][0]["t"] - top2[0][0]["t"]
        tone_dur = float(np.mean([g[-1]["t"] - g[0]["t"] for g in top2]))
        flat1, prom1 = self._group_tonality(top2[0])
        flat2, prom2 = self._group_tonality(top2[1])

        return {
            "f1": f1,
            "f2": f2,
            "interval": float(interval),
            "tone_duration": tone_dur,
            "flatness": float(np.mean([flat1, flat2])),
            "prominence": float(np.mean([prom1, prom2])),
        }

    def build_profile(self, samples: list[dict]) -> ChimeProfile:
        f1s = np.array([s["f1"] for s in samples])
        f2s = np.array([s["f2"] for s in samples])
        intervals = np.array([s["interval"] for s in samples])
        durations = np.array([s["tone_duration"] for s in samples])
        flats = np.array([s["flatness"] for s in samples])
        proms = np.array([s["prominence"] for s in samples])

        suggested_flat = round(float(flats.mean()) * 3.0 + 0.05, 3)
        suggested_prom = round(max(float(proms.mean()) * 0.3, 3.0), 1)

        return ChimeProfile(
            f1=float(f1s.mean()),
            f2=float(f2s.mean()),
            f1_std=float(f1s.std()),
            f2_std=float(f2s.std()),
            interval=float(intervals.mean()),
            interval_std=float(intervals.std()),
            tone_duration=float(durations.mean()),
            flatness_mean=float(flats.mean()),
            prominence_mean=float(proms.mean()),
            suggested_flatness_max=suggested_flat,
            suggested_prominence_min=suggested_prom,
            sample_rate=self.config.sample_rate,
            num_samples=len(samples),
        )

    def run(
        self, output_path: str | Path = DEFAULT_PROFILE_PATH
    ) -> ChimeProfile | None:
        c = self.config
        print("🔔 チャイム音のプロファイルを作成します")
        print(f"   {c.num_samples}回鳴らしてください")
        print(f"   録音WAVは {self.output_dir} に保存されます\n")

        samples: list[dict] = []
        for i in range(c.num_samples):
            input(f"[{i + 1}/{c.num_samples}] Enterを押してから鳴らしてください...")
            audio = self.record_once()
            wav_path = self.output_dir / f"sample_{i + 1}.wav"
            save_wav(wav_path, audio, c.sample_rate)
            print(f"    録音保存: {wav_path}")
            try:
                tones = self.extract_sample(audio)
            except ValueError as err:
                print(f"    ⚠️ {err} — スキップします\n")
                continue
            print(
                f"    ✓ F1={tones['f1']:.1f}Hz F2={tones['f2']:.1f}Hz "
                f"間隔={tones['interval']:.2f}s 音長={tones['tone_duration']:.2f}s "
                f"flat={tones['flatness']:.3f} prom={tones['prominence']:.1f}\n"
            )
            samples.append(tones)

        if len(samples) < 2:
            print("❌ 有効なサンプルが少なすぎます。もう一度お試しください。")
            print(f"   録音は {self.output_dir} にあります。音量・雑音を確認してみてください。")
            return None

        profile = self.build_profile(samples)
        out = profile.save(output_path)
        print(f"✅ プロファイル保存: {out}")
        import json

        print(json.dumps(profile.to_dict(), indent=2, ensure_ascii=False))
        print(
            f"\n💡 誤検知が多い場合は検出器を以下の環境変数で起動してみてください:\n"
            f"   CHIME_FLATNESS={profile.suggested_flatness_max} "
            f"CHIME_PROM={profile.suggested_prominence_min} python main.py detect"
        )
        return profile


def run() -> ChimeProfile | None:
    return ProfileRecorder().run()


if __name__ == "__main__":
    run()
