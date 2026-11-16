"""Streak-flow analysis: finds the direction of star trails in an image and traces them.

The orientation field comes from a smoothed structure tensor. Streaks run along the
eigenvector with the smaller eigenvalue, so the traced lines follow the trails.
"""
import numpy as np
from PIL import Image

W, H = 896, 448  # analysis resolution (2:1, like the art box)


def _blur(a, r):
    k = np.exp(-0.5 * (np.arange(-int(3 * r) - 1, int(3 * r) + 2) / r) ** 2)
    k /= k.sum()
    pad = len(k) // 2
    a = np.apply_along_axis(lambda v: np.convolve(np.pad(v, pad, mode="edge"), k, "valid"), 1, a)
    return np.apply_along_axis(lambda v: np.convolve(np.pad(v, pad, mode="edge"), k, "valid"), 0, a)


class Flow:
    def __init__(self, image: Image.Image):
        g = image.convert("L").resize((W, H), Image.LANCZOS)
        I = np.asarray(g).astype(np.float32) / 255
        gy, gx = np.gradient(_blur(I, 1.2))
        jxx, jyy, jxy = _blur(gx * gx, 5), _blur(gy * gy, 5), _blur(gx * gy, 5)
        self.theta = 0.5 * np.arctan2(2 * jxy, jxx - jyy) + np.pi / 2  # streak direction
        self.coh = np.sqrt((jxx - jyy) ** 2 + 4 * jxy ** 2) / (jxx + jyy + 1e-9)
        self.lum = _blur(I, 3)

    def trace(self, n=26, minlen=160, seed=1, seed_lum=.18, stop_lum=.08):
        """Trace up to n non-overlapping streak lines (image px coordinates)."""
        theta, coh, L = self.theta, self.coh, self.lum
        rng = np.random.default_rng(seed)
        occ = np.zeros((H // 6 + 1, W // 6 + 1), bool)
        cand = np.argwhere((L > seed_lum) & (coh > .45))
        rng.shuffle(cand)
        paths = []
        for y0, x0 in cand[:20000]:
            if occ[y0 // 6, x0 // 6]:
                continue

            def go(sign):
                x, y, prev, out = float(x0), float(y0), None, []
                for _ in range(400):
                    xi, yi = int(x), int(y)
                    if not (0 <= xi < W and 0 <= yi < H) or L[yi, xi] < stop_lum or coh[yi, xi] < .22:
                        break
                    dx, dy = np.cos(theta[yi, xi]), np.sin(theta[yi, xi])
                    if prev is None:
                        dx, dy = dx * sign, dy * sign
                    elif dx * prev[0] + dy * prev[1] < 0:
                        dx, dy = -dx, -dy
                    prev = (dx, dy)
                    x += dx * 3
                    y += dy * 3
                    out.append((x, y))
                return out

            pts = go(-1)[::-1] + [(x0, y0)] + go(1)
            if len(pts) * 3 < minlen:
                continue
            cells = [(int(y) // 6, int(x) // 6) for x, y in pts if 0 <= x < W and 0 <= y < H]
            if sum(occ[c] for c in cells) > len(cells) * .15:
                continue
            for c in cells:
                occ[max(c[0] - 1, 0):c[0] + 2, max(c[1] - 1, 0):c[1] + 2] = True
            paths.append(np.array(pts))
            if len(paths) >= n:
                break
        return paths
