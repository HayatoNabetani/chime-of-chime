import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from src.profile import ChimeProfile
from src.recorder import ProfileRecorder, RecorderConfig


class ChimeProfileTest(unittest.TestCase):
    def test_save_creates_parent_and_round_trips(self) -> None:
        profile = ChimeProfile(f1=440, f2=550, interval=0.4, tone_duration=0.2)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "profile.json"
            profile.save(path)
            loaded = ChimeProfile.load(path)
        self.assertEqual(loaded.f1, 440)
        self.assertEqual(loaded.f2, 550)

    def test_load_rejects_non_object_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profile.json"
            path.write_text(json.dumps([]), encoding="utf-8")
            with self.assertRaises(TypeError):
                ChimeProfile.load(path)


class ProfileRecorderTest(unittest.TestCase):
    def test_exactly_one_window_produces_one_frame(self) -> None:
        config = RecorderConfig(sample_rate=100, frame_win_sec=0.1, frame_hop_sec=0.05)
        recorder = ProfileRecorder(config)
        frames = recorder._frame_features(np.ones(10, dtype=np.float32))
        self.assertEqual(len(frames), 1)


if __name__ == "__main__":
    unittest.main()
