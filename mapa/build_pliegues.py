"""Textura de pliegues para el mapa de carreteras (static_big/pliegues.png).

En vez de rayas dibujadas, se modela la hoja como un relieve: un mapa de carreteras doblado en acordeón
(4 paneles, pliegues alternos de monte y valle) y por la mitad, que al desplegarlo no queda plano.
Cada panel se abomba un poco, cada pliegue levanta o hunde el papel a su lado y el propio pliegue es
una arista viva. Encima, ondulaciones de papel usado, arrugas sueltas y desgaste donde se cruzan los
pliegues. Luego se ilumina con luz rasante desde arriba a la izquierda.

Sale una imagen en escala de grises donde el gris 128 no cambia nada: más oscuro sombrea y más claro
aclara. En la página se mezcla con el mapa con mix-blend-mode: soft-light / multiply.

    .venv-laya/Scripts/python mapa/build_pliegues.py
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

import numpy as np

OUT = Path(__file__).resolve().parent / "static_big" / "pliegues.png"
W, H = 2400, 1490
rng = np.random.default_rng(1994)


def blur(a, sigma):
    """Desenfoque gaussiano por FFT (sin scipy)."""
    fy = np.fft.fftfreq(a.shape[0])[:, None]
    fx = np.fft.fftfreq(a.shape[1])[None, :]
    g = np.exp(-2 * (np.pi * sigma) ** 2 * (fx ** 2 + fy ** 2))
    return np.real(np.fft.ifft2(np.fft.fft2(a) * g))


def noise(sigma, amp=1.0):
    n = blur(rng.standard_normal((H, W)), sigma)
    return n / (np.abs(n).max() + 1e-9) * amp


y, x = np.mgrid[0:H, 0:W].astype(np.float32)
h = np.zeros((H, W), np.float32)
albedo = np.zeros((H, W), np.float32)      # desgaste: el papel se aclara donde roza

# pliegues: posición, orientación y signo (+1 monte, -1 valle)
folds = [(0.25, "v", -1), (0.50, "v", +1), (0.75, "v", -1), (0.50, "h", -1)]
for f, ori, s in folds:
    d = (x - f * W) if ori == "v" else (y - f * H)
    along = y if ori == "v" else x
    # la línea del pliegue no es perfecta: se tuerce un pelo a lo largo
    wob = blur(rng.standard_normal((1, W if ori == "h" else H)), 40)[0]
    wob = wob / (np.abs(wob).max() + 1e-9) * 2.5
    d = d + wob[along.astype(int)]
    ad = np.abs(d)
    strength = 0.85 + 0.3 * noise(120)                     # unos tramos más marcados que otros
    h += s * strength * (26 * np.exp(-ad / 70) + 5 * np.exp(-ad / 9) + 2.2 * np.exp(-ad / 2.2))
    # desgaste a lo largo del pliegue, a trozos
    wear = np.clip(noise(6, 1) + noise(30, 0.8), 0, None)
    albedo += np.exp(-ad / 2.8) * wear * (0.9 if s > 0 else 0.45)

# cada panel se abomba un poco (se ha quedado con la forma de estar doblado)
px = (x / W * 4) % 1.0
py = (y / H * 2) % 1.0
h += 10 * np.sin(np.pi * px) * np.sin(np.pi * py) * (1 + 0.4 * noise(300))

# ondulación de papel usado y arrugas sueltas
h += noise(90, 9) + noise(28, 2.2) + noise(4, 0.35)
for _ in range(9):
    cx, cy = rng.uniform(0.05, 0.95) * W, rng.uniform(0.05, 0.95) * H
    ang = rng.uniform(0, np.pi)
    L = rng.uniform(60, 260)
    u = (x - cx) * np.cos(ang) + (y - cy) * np.sin(ang)
    v = -(x - cx) * np.sin(ang) + (y - cy) * np.cos(ang)
    env = np.exp(-(u / L) ** 2 * 2)
    h += rng.choice([-1, 1]) * rng.uniform(1.5, 3.5) * env * np.exp(-np.abs(v) / 3)

# cruces de pliegues: el papel se rompe un poco y se ve la fibra
for fx_ in (0.25, 0.5, 0.75):
    cx, cy = fx_ * W, 0.5 * H
    r = np.hypot(x - cx, y - cy)
    m = np.exp(-(r / 22) ** 2)
    albedo += m * np.clip(0.6 + noise(3, 1.2), 0, None) * 1.3
    h += m * noise(2.5, 3)

# bordes de la hoja algo más gastados
edge = np.minimum.reduce([x, W - 1 - x, y, H - 1 - y])
albedo += np.exp(-edge / 10) * np.clip(noise(5, 1), 0, None) * 0.6

# iluminación rasante desde arriba a la izquierda
gy, gx = np.gradient(h)
nx, ny, nz = -gx, -gy, np.ones_like(h) * 6.0
norm = np.sqrt(nx ** 2 + ny ** 2 + nz ** 2)
lx, ly, lz = -0.55, -0.6, 0.58
ll = np.sqrt(lx ** 2 + ly ** 2 + lz ** 2)
shade = (nx * lx + ny * ly + nz * lz) / (norm * ll) / (lz / ll)

v = 128 + (shade - 1) * 190 + albedo * 46
# un poco de viñeta: la hoja coge menos luz hacia los bordes
rr = np.hypot((x - W / 2) / (W / 2), (y - H / 2) / (H / 2))
v -= np.clip(rr - 0.75, 0, None) * 38
img = np.clip(v, 0, 255).astype(np.uint8)


def write_png(path, a):
    raw = b"".join(b"\x00" + row.tobytes() for row in a)
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", a.shape[1], a.shape[0], 8, 0, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")
    path.write_bytes(png)


write_png(OUT, img)
print(f"{OUT.name}: {img.shape[1]}x{img.shape[0]}, {OUT.stat().st_size / 1e6:.1f} MB, gris medio {img.mean():.0f}")
