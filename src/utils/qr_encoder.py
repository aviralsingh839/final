"""Dependency-free QR code encoder (CHRONO-PCOS V8.1).

Purpose: encode a SHORT de-identified record token into a scannable QR code
with zero external dependencies (no `qrcode`, no `cv2`). The full longitudinal
report is never put in the QR — only a randomized record identifier, so the
code carries no personally identifying information.

Scope (deliberately minimal, documented):

  * byte mode only
  * QR versions 1-3 (sizes 21/25/29 modules)
  * error correction levels L and M
  * single RS block per code (true for versions 1-3 at L and M)

This covers report tokens of up to ~50 characters (V3-L byte capacity), which
is far more than the 12-24 character tokens this system issues.

Correctness self-checks used by the test-suite:

  1. Reed-Solomon syndromes of the produced codeword sequence are all zero
     (proves the EC encoding is a valid codeword of the RS code).
  2. A reverse reader (implemented in tests) re-extracts the data codewords
     from the rendered matrix, unmasks with the format-info mask, and verifies
     the payload round-trips.
  3. Structural checks: finder patterns, separators, timing, alignment,
     dark module, and identical format info in both copies.

The payload is always also displayed as plain text next to the QR, so a scan
failure degrades gracefully to manual token entry (consistent with the
low-infrastructure "print fallback" design).

Reference: ISO/IEC 18004 (QR Code). EC level bits: L=01, M=00.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

# ----------------------------------------------------------------- GF(256)
_POLY = 0x11D  # x^8 + x^4 + x^3 + x^2 + 1


def _gf_mul(a: int, b: int) -> int:
    r = 0
    while b:
        if b & 1:
            r ^= a
        a <<= 1
        if a & 0x100:
            a ^= _POLY
        b >>= 1
    return r & 0xFF


def _gf_pow(a: int, e: int) -> int:
    r = 1
    for _ in range(e % 255):
        r = _gf_mul(r, a)
    return r


def _poly_mul(a: List[int], b: List[int]) -> List[int]:
    out = [0] * (len(a) + len(b) - 1)
    for i, ai in enumerate(a):
        for j, bj in enumerate(b):
            out[i + j] ^= _gf_mul(ai, bj)
    return out


def _rs_generator(n: int) -> List[int]:
    """Generator polynomial of degree n: prod_{i=0}^{n-1} (x - alpha^i)."""
    g: List[int] = [1]
    for i in range(n):
        g = _poly_mul(g, [1, _gf_pow(2, i)])
    return g


def _rs_remainder(msg: List[int], gen: List[int]) -> List[int]:
    """Remainder of msg(x) * x^deg(gen) divided by gen(x)."""
    n = len(gen) - 1
    padded = list(msg) + [0] * n
    for i in range(len(msg)):
        coef = padded[i]
        if coef:
            for j, gj in enumerate(gen):
                padded[i + j] ^= _gf_mul(coef, gj)
    return padded[len(msg):]


def _rs_syndromes(codewords: List[int], n_ec: int) -> List[int]:
    """Syndromes S_i = r(alpha^i), i = 0..n_ec-1. All zero => valid codeword.

    `codewords` is the stream in transmission order (data first, then EC).
    The polynomial c(x) = sum c_k x^k uses the stream reversed, so the
    coefficient of x^k is codewords[N-1-k] — hence the reversal below.
    GF(2^8) addition is XOR, never integer sum.
    """
    asc = list(reversed(codewords))
    out: List[int] = []
    for i in range(n_ec):
        s = 0
        for k, c in enumerate(asc):
            if c:
                s ^= _gf_mul(c, _gf_pow(2, (i * k) % 255))
        out.append(s)
    return out


# ---------------------------------------------------------------- tables
# (version) -> (modules_per_side)
_VERSION_SIZE = {1: 21, 2: 25, 3: 29}
# (version, level) -> (data_codewords, ec_codewords) — single RS block for
# versions 1-3 at levels L/M (ISO/IEC 18004 table 1 + 13-22).
_RS_BLOCKS = {
    (1, "L"): (19, 7), (1, "M"): (16, 10),
    (2, "L"): (34, 10), (2, "M"): (28, 16),
    (3, "L"): (55, 15), (3, "M"): (44, 26),
}
_EC_LEVEL_BITS = {"L": 0b01, "M": 0b00, "Q": 0b11, "H": 0b10}
# alignment pattern centers; v1 has none, v2/v3 have one each.
_ALIGNMENT = {1: [], 2: [(18, 18)], 3: [(22, 22)]}

_MODE_BYTE = 0b0100


class QRError(Exception):
    pass


class QREncoder:
    """Minimal byte-mode QR encoder for short payloads."""

    def __init__(self, version: int = 2, level: str = "L"):
        if version not in _VERSION_SIZE:
            raise QRError(f"unsupported version {version} (supported: 1-3)")
        if level not in ("L", "M"):
            raise QRError(f"unsupported EC level {level} (supported: L, M)")
        self.version = version
        self.level = level
        self.size = _VERSION_SIZE[version]
        data_cw, self.ec_cw = _RS_BLOCKS[(version, level)]
        self.data_cw = data_cw
        self.max_bytes = (data_cw * 8 - 4 - 8) // 8  # byte-mode capacity

    # ------------------------------------------------------------- encode
    def _finish(self, payload: str, data: bytes) -> "QRCode":
        bits: List[int] = []
        # mode (4 bits) + count (8 bits) + data
        bits.extend(_bits(_MODE_BYTE, 4))
        bits.extend(_bits(len(data), 8))
        for byte in data:
            bits.extend(_bits(byte, 8))
        # terminator
        bits.extend([0] * min(4, self.data_cw * 8 - len(bits)))
        # pad to byte boundary
        while len(bits) % 8:
            bits.append(0)
        # pad codewords EC 11 11 EC ...
        pads = [0xEC, 0x11]
        i = 0
        while len(bits) < self.data_cw * 8:
            bits.extend(_bits(pads[i % 2], 8))
            i += 1
        data_codewords = [int("".join(str(b) for b in bits[i:i + 8]), 2)
                          for i in range(0, len(bits), 8)]
        if len(data_codewords) != self.data_cw:
            raise QRError("internal: data codeword count mismatch")
        ec = _rs_remainder(data_codewords, _rs_generator(self.ec_cw))
        codewords = data_codewords + ec
        # sanity: the produced sequence must be a valid RS codeword
        if any(_rs_syndromes(codewords, self.ec_cw)):
            raise QRError("internal: RS encoding failed syndrome check")
        return QRCode(self.version, self.level, data_codewords, ec)

    # --------------------------------------------------------------- API
    def make(self, payload: str) -> "QRCode":
        data = payload.encode("utf-8")
        if len(data) > self.max_bytes:
            raise QRError(f"payload of {len(data)} bytes exceeds capacity "
                          f"{self.max_bytes} for version {self.version}-{self.level}")
        return self._finish(payload, data)


def _bits(value: int, width: int) -> List[int]:
    return [(value >> (width - 1 - i)) & 1 for i in range(width)]


class QRCode:
    """A finished QR code: `matrix` is size x size of 0/1 ints."""

    def __init__(self, version: int, level: str,
                 data_codewords: List[int], ec_codewords: List[int]):
        self.version = version
        self.level = level
        self.data_codewords = data_codewords
        self.ec_codewords = ec_codewords
        self.codewords = data_codewords + ec_codewords
        self.size = _VERSION_SIZE[version]
        self.mask: int = -1
        self.matrix: List[List[int]] = []
        self._build()

    # --------------------------------------------------- function patterns
    def _new_matrix(self) -> List[List[int]]:
        m = [[-1] * self.size for _ in range(self.size)]
        # finder patterns + separators (three corners)
        for (fr, fc) in [(0, 0), (self.size - 7, 0), (0, self.size - 7)]:
            for r in range(7):
                for c in range(7):
                    on_edge = r in (0, 6) or c in (0, 6)
                    core = 2 <= r <= 4 and 2 <= c <= 4
                    m[fr + r][fc + c] = 1 if (on_edge or core) else 0
            # separator ring (light)
            for r in range(-1, 8):
                for c in range(-1, 8):
                    rr, cc = fr + r, fc + c
                    if 0 <= rr < self.size and 0 <= cc < self.size:
                        if not (0 <= r < 7 and 0 <= c < 7):
                            if m[rr][cc] == -1:
                                m[rr][cc] = 0
        # timing patterns
        for i in range(8, self.size - 8):
            m[6][i] = 1 if i % 2 == 0 else 0
            m[i][6] = 1 if i % 2 == 0 else 0
        # alignment patterns (single one for v2/v3)
        for (ar, ac) in _ALIGNMENT[self.version]:
            for r in range(-2, 3):
                for c in range(-2, 3):
                    if m[ar + r][ac + c] == -1:
                        ring = max(abs(r), abs(c))
                        m[ar + r][ac + c] = 1 if ring != 1 else 0
        # dark module
        m[8][4 * self.version + 9] = 1
        # reserve format areas (dark module spot handled; set rest to 0)
        for c in range(9):
            if m[8][c] == -1:
                m[8][c] = 0
        for r in range(9):
            if m[r][8] == -1:
                m[r][8] = 0
        for r in range(self.size - 8, self.size):
            if m[r][8] == -1:
                m[r][8] = 0
        for c in range(self.size - 8, self.size):
            if m[8][c] == -1:
                m[8][c] = 0
        return m

    def _format_info(self, mask: int) -> int:
        data = (_EC_LEVEL_BITS[self.level] << 3) | mask
        r = data << 10
        g = 0b10100110111  # 0x537
        while r.bit_length() >= 11:
            r ^= g << (r.bit_length() - 11)
        return ((data << 10) | r) ^ 0x5412

    def _place_format(self, m: List[List[int]], mask: int) -> None:
        fmt = self._format_info(mask)  # 15 bits
        # ISO 18004: bit 14 (MSB) goes at the first position in each list,
        # bit 0 (LSB) at the last.
        bits = [(fmt >> (14 - i)) & 1 for i in range(15)]
        # copy 1 around top-left
        pos1 = [(8, 0), (8, 1), (8, 2), (8, 3), (8, 4), (8, 5),
                (8, 7), (8, 8), (7, 8), (5, 8), (4, 8), (3, 8), (2, 8), (1, 8), (0, 8)]
        # copy 2: left column bottom + bottom row right
        pos2 = [(self.size - 1, 8), (self.size - 2, 8), (self.size - 3, 8),
                (self.size - 4, 8), (self.size - 5, 8), (self.size - 6, 8),
                (self.size - 7, 8), (8, self.size - 8), (8, self.size - 7),
                (8, self.size - 6), (8, self.size - 5), (8, self.size - 4),
                (8, self.size - 3), (8, self.size - 2), (8, self.size - 1)]
        for (r, c), b in zip(pos1, bits):
            m[r][c] = b
        for (r, c), b in zip(pos2, bits):
            m[r][c] = b

    def _mask_apply(self, mask: int, r: int, c: int) -> bool:
        i, j = r, c
        if mask == 0:
            return (i + j) % 2 == 0
        if mask == 1:
            return i % 2 == 0
        if mask == 2:
            return j % 3 == 0
        if mask == 3:
            return (i + j) % 3 == 0
        if mask == 4:
            return (i // 2 + j // 3) % 2 == 0
        if mask == 5:
            return (i * j) % 2 + (i * j) % 3 == 0
        if mask == 6:
            return ((i * j) % 2 + (i * j) % 3) % 2 == 0
        return ((i + j) % 2 + (i * j) % 3) % 2 == 0

    def _data_modules(self, m: List[List[int]]) -> List[Tuple[int, int]]:
        """Zigzag data-module coordinates (up-right pairs, skipping col 6 and
        function/reserved modules)."""
        coords: List[Tuple[int, int]] = []
        col = self.size - 1
        upward = True
        while col > 0:
            if col == 6:
                col -= 1
            c1, c2 = col, col - 1
            rows = range(self.size - 1, -1, -1) if upward else range(self.size)
            for r in rows:
                for c in (c1, c2):
                    if 0 <= r < self.size and 0 <= c < self.size:
                        if m[r][c] == -1:
                            coords.append((r, c))
            upward = not upward
            col -= 2
        return coords

    def _penalty(self, m: List[List[int]]) -> int:
        score = 0
        size = self.size
        # N1: runs of >= 5
        for r in range(size):
            run = 1
            for c in range(1, size):
                if m[r][c] == m[r][c - 1]:
                    run += 1
                else:
                    if run >= 5:
                        score += 3 + run - 5
                    run = 1
            if run >= 5:
                score += 3 + run - 5
        for c in range(size):
            run = 1
            for r in range(1, size):
                if m[r][c] == m[r - 1][c]:
                    run += 1
                else:
                    if run >= 5:
                        score += 3 + run - 5
                    run = 1
            if run >= 5:
                score += 3 + run - 5
        # N2: 2x2 blocks
        for r in range(size - 1):
            for c in range(size - 1):
                v = m[r][c]
                if m[r][c + 1] == v and m[r + 1][c] == v and m[r + 1][c + 1] == v:
                    score += 3
        # N3: 1011101 with 0000 on either side (row and column)
        pat = [1, 0, 1, 1, 1, 0, 1]
        for r in range(size):
            for c in range(size - 7):
                if m[r][c:c + 7] == pat:
                    if c + 7 + 4 <= size and m[r][c + 7:c + 11] == [0] * 4:
                        score += 40
                    if c - 4 >= 0 and m[r][c - 4:c] == [0] * 4:
                        score += 40
        for c in range(size):
            for r in range(size - 7):
                col = [m[r + k][c] for k in range(7)]
                if col == pat:
                    if r + 7 + 4 <= size and [m[r + 7 + k][c] for k in range(4)] == [0] * 4:
                        score += 40
                    if r - 4 >= 0 and [m[r - 4 + k][c] for k in range(4)] == [0] * 4:
                        score += 40
        # N4: dark proportion
        dark = sum(sum(row) for row in m)
        total = size * size
        pct = dark * 100 // total
        score += (abs(pct - 50) // 5) * 10
        return score

    def _build(self) -> None:
        base = self._new_matrix()
        coords = self._data_modules(base)
        bitstream: List[int] = []
        for cw in self.codewords:
            bitstream.extend(_bits(cw, 8))
        if len(bitstream) > len(coords):
            raise QRError("internal: data module count mismatch")
        if len(bitstream) < len(coords):
            # remainder bits (zero-filled) — versions 2 and 3 have 7
            # extra modules after the final codeword (ISO/IEC 18004)
            bitstream.extend([0] * (len(coords) - len(bitstream)))
        best_mask = 0
        best_score = None
        best_matrix = None
        for mask in range(8):
            m = [row[:] for row in base]
            for (r, c), bit in zip(coords, bitstream):
                v = bit
                if self._mask_apply(mask, r, c):
                    v ^= 1
                m[r][c] = v
            self._place_format(m, mask)
            score = self._penalty(m)
            if best_score is None or score < best_score:
                best_score = score
                best_mask = mask
                best_matrix = m
        self.mask = best_mask
        self.matrix = best_matrix

    # ---------------------------------------------------------- rendering
    def to_png_bytes(self, scale: int = 6, border: int = 4) -> bytes:
        """Render to PNG bytes (quiet zone of `border` light modules)."""
        try:
            from PIL import Image
            import io
        except Exception as exc:  # pragma: no cover
            raise QRError(f"PIL required for PNG rendering: {exc}")
        dim = (self.size + 2 * border) * scale
        img = Image.new("L", (dim, dim), 255)
        px = img.load()
        for r in range(self.size):
            for c in range(self.size):
                if self.matrix[r][c]:
                    for dr in range(scale):
                        for dc in range(scale):
                            px[(c + border) * scale + dc, (r + border) * scale + dr] = 0
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    def to_svg(self, scale: int = 6, border: int = 4) -> str:
        dim = (self.size + 2 * border) * scale
        parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{dim}" height="{dim}" '
                 f'viewBox="0 0 {dim} {dim}">',
                 f'<rect width="{dim}" height="{dim}" fill="#ffffff"/>']
        for r in range(self.size):
            for c in range(self.size):
                if self.matrix[r][c]:
                    x = (c + border) * scale
                    y = (r + border) * scale
                    parts.append(f'<rect x="{x}" y="{y}" width="{scale}" height="{scale}" fill="#000000"/>')
        parts.append("</svg>")
        return "".join(parts)


def make_qr_code(payload: str, version: int = 2, level: str = "L") -> QRCode:
    """Encode `payload` (UTF-8 byte mode). Raises QRError when it cannot fit."""
    enc = QREncoder(version=version, level=level)
    return enc.make(payload)
