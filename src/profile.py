"""チャイムプロファイルのデータ構造とI/O。

録音フェーズで書き出し、検知フェーズで読み込む。
"""

import json
from dataclasses import asdict, dataclass
from pathlib import Path


DEFAULT_PROFILE_PATH = Path("chime_profile.json")


@dataclass
class ChimeProfile:
    f1: float
    f2: float
    interval: float
    tone_duration: float
    f1_std: float = 0.0
    f2_std: float = 0.0
    interval_std: float = 0.0
    flatness_mean: float = 0.0
    prominence_mean: float = 0.0
    suggested_flatness_max: float = 0.3
    suggested_prominence_min: float = 8.0
    sample_rate: int = 44100
    num_samples: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    def save(self, path: str | Path = DEFAULT_PROFILE_PATH) -> Path:
        p = Path(path)
        p.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False))
        return p

    @classmethod
    def load(cls, path: str | Path = DEFAULT_PROFILE_PATH) -> "ChimeProfile":
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(
                f"プロファイルが見つかりません: {p}\n"
                "  先に `python main.py record` を実行してください"
            )
        data = json.loads(p.read_text())
        # 未知フィールドを無視して互換性を保つ
        allowed = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in allowed})
