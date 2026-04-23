"""FFTベースのスペクトル特徴量抽出。

recorder と detector の両方から使う純粋関数群。オーディオI/Oや状態を持たない。
"""

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class SpectralFeatures:
    """単一オーディオブロックから抽出した特徴量。

    peak_freq: 指定帯域内で最もエネルギーの大きい周波数 (Hz)
    flatness : スペクトル平坦度。純音は0、ホワイトノイズは1に近い。
    prominence: ピーク振幅 / 中央値。純音で大きく、ノイズで小さい。
    rms      : 時間領域のRMSエネルギー。
    """

    peak_freq: float
    flatness: float
    prominence: float
    rms: float


def compute_rms(block: np.ndarray) -> float:
    return float(np.sqrt(np.mean(block**2)))


def extract_features(
    block: np.ndarray,
    sample_rate: int,
    freq_min: float = 150.0,
    freq_max: float = 4000.0,
) -> SpectralFeatures:
    rms = compute_rms(block)
    windowed = block * np.hanning(len(block))
    spectrum = np.abs(np.fft.rfft(windowed))
    freqs = np.fft.rfftfreq(len(block), 1 / sample_rate)
    mask = (freqs >= freq_min) & (freqs <= freq_max)
    masked = spectrum[mask]
    if masked.size == 0 or masked.max() == 0:
        return SpectralFeatures(0.0, 1.0, 0.0, rms)
    eps = 1e-10
    sp = masked + eps
    flatness = float(np.exp(np.mean(np.log(sp))) / np.mean(sp))
    median = float(np.median(masked))
    prominence = float(masked.max() / (median + eps))
    peak_freq = float(freqs[mask][int(np.argmax(masked))])
    return SpectralFeatures(peak_freq, flatness, prominence, rms)
