"""Deterministic representative test images for the Image Studio tests.

Synthetic stand-ins for each category the specification lists (portrait, landscape, logo, black-and-white
drawing, high-contrast, transparent, low-resolution, large photograph). They are generated from formulas
(no external files), so tests are reproducible and the images carry no third-party rights.
"""
from __future__ import annotations

import math

import numpy as np


def _rgba(rgb, a=None):
    h, w = rgb.shape[:2]
    if a is None:
        a = np.ones((h, w))
    arr = np.concatenate([np.clip(rgb, 0, 1), np.clip(a, 0, 1)[:, :, None]], axis=2)
    return w, h, np.floor(arr * 255 + 0.5).astype(np.uint8).tobytes()


def portrait(w=120, h=150):
    y, x = np.mgrid[0:h, 0:w].astype(np.float64)
    cx, cy = w / 2, h * 0.45
    bg = np.stack([0.25 + 0.3 * y / h, 0.3 + 0.2 * x / w, 0.45 + 0.0 * x], axis=2)
    face = ((x - cx) / (w * 0.3)) ** 2 + ((y - cy) / (h * 0.33)) ** 2 < 1
    shade = np.clip(1.0 - 0.6 * ((x - cx * 0.85) / w) ** 2 * 4 - 0.3 * ((y - cy) / h) ** 2 * 4, 0.3, 1)
    skin = np.stack([0.95 * shade, 0.75 * shade, 0.62 * shade], axis=2)
    rgb = np.where(face[:, :, None], skin, bg)
    for ex in (cx - w * 0.11, cx + w * 0.11):
        eye = ((x - ex) / (w * 0.05)) ** 2 + ((y - cy + h * 0.06) / (h * 0.025)) ** 2 < 1
        rgb[eye] = [0.1, 0.08, 0.06]
    mouth = (np.abs(y - (cy + h * 0.15) - 0.002 * (x - cx) ** 2) < 2) & (np.abs(x - cx) < w * 0.12)
    rgb[mouth] = [0.55, 0.15, 0.15]
    hair = (((x - cx) / (w * 0.34)) ** 2 + ((y - cy + h * 0.08) / (h * 0.36)) ** 2 < 1) & ~face & (y < cy)
    rgb[hair] = [0.2, 0.12, 0.07]
    return _rgba(rgb)


def landscape(w=200, h=110):
    y, x = np.mgrid[0:h, 0:w].astype(np.float64)
    sky = np.stack([0.35 + 0.4 * y / h, 0.55 + 0.3 * y / h, 0.95 - 0.1 * y / h], axis=2)
    ridge = h * 0.55 + 12 * np.sin(x / 17) + 7 * np.sin(x / 5.3 + 1)
    mount = y > ridge
    rock = np.stack([0.35 + 0.1 * np.sin(x / 3), 0.33 + 0.05 * np.cos(y / 4), 0.3 + 0 * x], axis=2)
    grass = y > h * 0.8 + 3 * np.sin(x / 9)
    rgb = np.where(mount[:, :, None], rock, sky)
    rgb = np.where(grass[:, :, None], np.stack([0.2 + 0 * x, 0.55 + 0.1 * np.sin(x / 2), 0.15 + 0 * x], axis=2), rgb)
    sun = (x - w * 0.8) ** 2 + (y - h * 0.2) ** 2 < (h * 0.09) ** 2
    rgb[sun] = [1.0, 0.92, 0.5]
    return _rgba(rgb)


def logo(w=160, h=100):
    y, x = np.mgrid[0:h, 0:w].astype(np.float64)
    rgb = np.ones((h, w, 3))
    ring = np.abs(np.hypot(x - w * 0.3, y - h / 2) - h * 0.3) < h * 0.08
    rgb[ring] = [0.85, 0.1, 0.2]
    bar = (np.abs(x - w * 0.68) < w * 0.06) & (np.abs(y - h / 2) < h * 0.35)
    rgb[bar] = [0.1, 0.3, 0.8]
    tri = (y > h * 0.2) & (y < h * 0.8) & (x > w * 0.78) & (x - w * 0.78 < (y - h * 0.2) * 0.5)
    rgb[tri] = [0.95, 0.75, 0.1]
    return _rgba(rgb)


def drawing(w=140, h=100):
    y, x = np.mgrid[0:h, 0:w].astype(np.float64)
    ink = np.zeros((h, w), dtype=bool)
    ink |= np.abs(np.hypot(x - w * 0.35, y - h * 0.5) - h * 0.32) < 1.2
    ink |= np.abs((y - h * 0.15) - (x - w * 0.55) * 0.9) < 1.0
    ink |= (np.abs(y - h * 0.8) < 1.0) & (x > w * 0.5)
    ink |= (np.abs(x - w * 0.85) < 1.0) & (y > h * 0.1) & (y < h * 0.8)
    v = np.where(ink, 0.0, 1.0)
    return _rgba(np.repeat(v[:, :, None], 3, axis=2))


def high_contrast(w=128, h=96):
    y, x = np.mgrid[0:h, 0:w].astype(np.float64)
    v = ((np.floor(x / 16) + np.floor(y / 16)) % 2).astype(np.float64)
    v = np.where(np.hypot(x - w / 2, y - h / 2) < 30, 1 - v, v)
    return _rgba(np.repeat(v[:, :, None], 3, axis=2))


def transparent(w=100, h=100):
    y, x = np.mgrid[0:h, 0:w].astype(np.float64)
    r = np.hypot(x - w / 2, y - h / 2)
    a = np.clip((w * 0.4 - r) / 2, 0, 1)
    rgb = np.stack([0.9 - x / w * 0.5, 0.2 + y / h * 0.6, 0.6 + 0 * x], axis=2)
    return _rgba(rgb, a)


def low_res(w=16, h=12):
    y, x = np.mgrid[0:h, 0:w].astype(np.float64)
    rgb = np.stack([x / (w - 1), y / (h - 1), 1 - x / (w - 1)], axis=2)
    rgb[4:8, 5:11] = [1, 1, 1]
    return _rgba(rgb)


def large_photo(w=1200, h=800):
    """Smooth multi-scale 'photograph-like' texture with soft shapes (deterministic)."""
    y, x = np.mgrid[0:h, 0:w].astype(np.float64)
    v = np.zeros((h, w))
    for k, (fx, fy, ph) in enumerate(((3, 2, 0.3), (7, 5, 1.1), (17, 11, 2.0), (41, 29, 0.7), (97, 71, 1.9))):
        v += np.sin(x / w * fx * math.pi + ph) * np.cos(y / h * fy * math.pi + ph * 1.3) / (k + 1)
    v = (v - v.min()) / (v.max() - v.min())
    rgb = np.stack([v, 0.6 * v + 0.3 * (x / w), 0.8 - 0.5 * v + 0.2 * (y / h)], axis=2)
    disc = np.hypot(x - w * 0.62, y - h * 0.45) < h * 0.22
    rgb[disc] = rgb[disc] * 0.3 + np.array([0.9, 0.5, 0.2]) * 0.7
    return _rgba(rgb)


ALL = {"portrait": portrait, "landscape": landscape, "logo": logo, "drawing": drawing, "high_contrast": high_contrast,
       "transparent": transparent, "low_res": low_res, "large_photo": large_photo}
