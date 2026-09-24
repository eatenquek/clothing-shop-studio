from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # discoverable from any cwd

from scripts.studio_core.pngcolour import decode_png, garment_colours
from tests.helpers import make_png

WHITE, NAVY, RED = (255, 255, 255, 255), (20, 30, 90, 255), (200, 20, 30, 255)


def garment(width=20, height=20, stripe=None):
    rows = []
    for y in range(height):
        row = []
        for x in range(width):
            inside = 4 <= x < 16 and 4 <= y < 16
            colour = (stripe if stripe and inside and x < 8 else NAVY) if inside else WHITE
            row.append(colour)
        rows.append(row)
    return rows


class PngColourTests(unittest.TestCase):
    def test_every_filter_type_round_trips(self):
        rows = garment(stripe=RED)
        for filter_type in range(5):
            with self.subTest(filter_type=filter_type):
                width, height, pixels = decode_png(make_png(20, 20, rows, 6, filter_type))
                self.assertEqual((width, height), (20, 20))
                self.assertEqual(pixels[5 * 20 + 5], RED)
                self.assertEqual(pixels[0], WHITE)

    def test_greyscale_rgb_and_palette(self):
        grey = decode_png(make_png(2, 1, [[(0,), (255,)]], colour_type=0))
        self.assertEqual(grey[2], [(0, 0, 0, 255), (255, 255, 255, 255)])
        rgb = decode_png(make_png(1, 1, [[(1, 2, 3)]], colour_type=2))
        self.assertEqual(rgb[2], [(1, 2, 3, 255)])
        pal = decode_png(make_png(1, 1, [[(1,)]], colour_type=3, palette=[(0, 0, 0), (9, 8, 7)]))
        self.assertEqual(pal[2], [(9, 8, 7, 255)])

    def test_primary_ignores_white_background(self):
        self.assertEqual(garment_colours(make_png(20, 20, garment()))["primary"], "#141E5A")
        self.assertIsNone(garment_colours(make_png(20, 20, garment()))["secondary"])

    def test_secondary_needs_real_coverage(self):
        colours = garment_colours(make_png(20, 20, garment(stripe=RED)))
        self.assertEqual(colours["secondary"], "#C8141E")

    def test_unsupported_or_blank_images_return_none(self):
        self.assertIsNone(decode_png(b"not a png"))
        self.assertIsNone(garment_colours(make_png(2, 2, [[WHITE, WHITE], [WHITE, WHITE]])))


if __name__ == "__main__":
    unittest.main()
