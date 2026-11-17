import struct
import zlib

import numpy as np
import pytest

from autofisher.vision import Detector, blob_center, color_mask, draw_rect, find_span, write_png


def solid(h, w, color):
    img = np.zeros((h, w, 3), dtype=np.uint8)
    img[:] = color
    return img


def test_color_mask_tolerance_and_multiple_colors():
    img = solid(2, 3, (100, 100, 100))
    img[0, 0] = (110, 95, 100)
    img[1, 2] = (200, 0, 0)
    assert color_mask(img, [100, 100, 100], 0).sum() == 4
    assert color_mask(img, [100, 100, 100], 10).sum() == 5
    assert color_mask(img, [[100, 100, 100], [200, 0, 0]], 10).sum() == 6


def test_color_mask_rejects_bad_color():
    with pytest.raises(ValueError):
        color_mask(solid(1, 1, (0, 0, 0)), [1, 2], 5)


def test_find_span_picks_biggest_group_and_bridges_small_gaps():
    mask = np.zeros((4, 40), dtype=bool)
    mask[:, 2:4] = True          # small noise
    mask[:, 10:15] = True        # bar part 1
    mask[:, 18:25] = True        # bar part 2 (3-column hole, e.g. covered by the fish)
    assert find_span(mask, "x", max_gap=3) == (10, 24, 48)
    # with no gap allowed the right-hand part wins on its own
    assert find_span(mask, "x", max_gap=0)[:2] == (18, 24)
    assert find_span(mask, "x", max_gap=3, min_pixels=100) is None
    assert find_span(np.zeros((3, 3), dtype=bool), "x") is None


def test_find_span_vertical():
    mask = np.zeros((30, 5), dtype=bool)
    mask[7:12, 1:3] = True
    assert find_span(mask, "y")[:2] == (7, 11)


def test_blob_center_separates_side_by_side_blobs():
    mask = np.zeros((50, 50), dtype=bool)
    mask[5:15, 5:15] = True       # 100 px blob
    mask[30:34, 40:44] = True     # 16 px blob
    cx, cy = blob_center(mask)
    assert (cx, cy) == (9.5, 9.5)


def test_detector_present_and_invert():
    img = solid(20, 20, (0, 0, 0))
    img[5:10, 5:10] = (255, 0, 0)
    d = Detector.from_config({"region": [0, 0, 20, 20], "color": [250, 5, 5], "tolerance": 10, "min_pixels": 20})
    assert d.count(img) == 25 and d.present(img)
    inv = Detector.from_config({"region": [0, 0, 20, 20], "color": [250, 5, 5], "tolerance": 10,
                                "min_pixels": 20, "invert": True})
    assert not inv.present(img)
    assert inv.present(solid(20, 20, (0, 0, 0)))


def test_write_png_roundtrip(tmp_path):
    img = solid(3, 4, (10, 20, 30))
    draw_rect(img, 0, 0, 4, 3, (255, 0, 255), 1)
    path = tmp_path / "x.png"
    write_png(str(path), img)
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    w, h = struct.unpack(">II", data[16:24])
    assert (w, h) == (4, 3)
    idat_len = struct.unpack(">I", data[33:37])[0]
    raw = zlib.decompress(data[41:41 + idat_len])
    rows = [raw[i * (1 + 12) + 1:(i + 1) * (1 + 12)] for i in range(3)]
    assert rows[0][:3] == bytes((255, 0, 255))
