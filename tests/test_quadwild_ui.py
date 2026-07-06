import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UI_PATH = ROOT / "ui.py"


def _draw_quadwild_block():
    text = UI_PATH.read_text(encoding="utf-8")
    match = re.search(
        r"def _draw_quadwild\(self, box, qw\):\n(?P<body>.*?)(?:\n    def |\Z)",
        text,
        re.DOTALL,
    )
    if not match:
        raise AssertionError("_draw_quadwild block not found in ui.py")
    return match.group("body")


class QuadWildUITests(unittest.TestCase):
    def test_quadwild_ui_keeps_only_basic_controls(self):
        body = _draw_quadwild_block()

        self.assertIn('enable_preprocess', body)
        self.assertIn('enable_smoothing', body)
        self.assertIn('target_mode', body)
        self.assertIn('enable_sharp', body)
        self.assertIn('sharp_angle', body)

    def test_quadwild_ui_hides_advanced_controls(self):
        body = _draw_quadwild_block()

        forbidden = [
            'symmetry_x',
            'symmetry_y',
            'symmetry_z',
            'alpha',
            'ilp_method',
            'time_limit',
            'gap_limit',
            'minimum_gap',
            'fixed_chart_clusters',
            'flow_config',
            'satsuma_config',
            'debug',
            'use_cache',
        ]
        for token in forbidden:
            self.assertNotIn(token, body, token)


if __name__ == "__main__":
    unittest.main()
