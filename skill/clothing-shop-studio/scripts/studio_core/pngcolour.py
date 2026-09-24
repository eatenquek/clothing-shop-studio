"""Read garment colours from PNG files with the standard library only.

Supports 8-bit, non-interlaced greyscale, RGB, palette, grey+alpha, and RGBA PNGs.
Anything else returns None so the caller records an estimated colour instead.
"""

from __future__ import annotations

import struct
import zlib

SIGNATURE = b"\x89PNG\r\n\x1a\n"
CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}
MAX_PIXELS = 40_000_000
BACKGROUND_MIN = 240
SECONDARY_SHARE = 0.15
DISTINCT_DISTANCE = 60


def _paeth(left: int, up: int, corner: int) -> int:
    p = left + up - corner
    pa, pb, pc = abs(p - left), abs(p - up), abs(p - corner)
    return left if pa <= pb and pa <= pc else up if pb <= pc else corner


def decode_png(data: bytes):
    if not data.startswith(SIGNATURE):
        return None
    offset, header, palette, idat = 8, None, None, bytearray()
    try:
        while offset < len(data):
            length, kind = struct.unpack(">I4s", data[offset:offset + 8])
            body = data[offset + 8:offset + 8 + length]
            offset += 12 + length
            if kind == b"IHDR":
                header = struct.unpack(">IIBBBBB", body)
            elif kind == b"PLTE":
                palette = [tuple(body[i:i + 3]) for i in range(0, len(body), 3)]
            elif kind == b"IDAT":
                idat += body
            elif kind == b"IEND":
                break
        if header is None:
            return None
        width, height, depth, colour_type, _, _, interlace = header
        if depth != 8 or interlace != 0 or colour_type not in CHANNELS or width * height > MAX_PIXELS:
            return None
        if colour_type == 3 and not palette:
            return None
        raw = zlib.decompress(bytes(idat))
    except (struct.error, zlib.error):
        return None
    channels = CHANNELS[colour_type]
    stride = width * channels
    if len(raw) < height * (stride + 1):
        return None
    pixels, previous = [], bytearray(stride)
    for y in range(height):
        start = y * (stride + 1)
        filter_type, line = raw[start], bytearray(raw[start + 1:start + 1 + stride])
        for i in range(stride):
            left = line[i - channels] if i >= channels else 0
            up, corner = previous[i], previous[i - channels] if i >= channels else 0
            if filter_type == 1:
                line[i] = (line[i] + left) % 256
            elif filter_type == 2:
                line[i] = (line[i] + up) % 256
            elif filter_type == 3:
                line[i] = (line[i] + (left + up) // 2) % 256
            elif filter_type == 4:
                line[i] = (line[i] + _paeth(left, up, corner)) % 256
            elif filter_type != 0:
                return None
        for x in range(width):
            values = line[x * channels:(x + 1) * channels]
            if colour_type == 0:
                pixels.append((values[0], values[0], values[0], 255))
            elif colour_type == 2:
                pixels.append((values[0], values[1], values[2], 255))
            elif colour_type == 3:
                if values[0] >= len(palette):
                    return None
                pixels.append((*palette[values[0]], 255))
            elif colour_type == 4:
                pixels.append((values[0], values[0], values[0], values[1]))
            else:
                pixels.append(tuple(values))
        previous = line
    return width, height, pixels


def _hex(rgb) -> str:
    return "#" + "".join(f"{round(value):02X}" for value in rgb)


def garment_colours(data: bytes):
    decoded = decode_png(data)
    if decoded is None:
        return None
    _, _, pixels = decoded
    buckets: dict[tuple, list] = {}
    total = 0
    for r, g, b, a in pixels:
        if a < 128 or (r >= BACKGROUND_MIN and g >= BACKGROUND_MIN and b >= BACKGROUND_MIN):
            continue
        total += 1
        key = (r >> 4, g >> 4, b >> 4)
        bucket = buckets.setdefault(key, [0, 0, 0, 0])
        bucket[0] += 1
        bucket[1] += r
        bucket[2] += g
        bucket[3] += b
    if not total:
        return None
    ranked = sorted(buckets.values(), key=lambda item: item[0], reverse=True)
    means = [(count, (sr / count, sg / count, sb / count)) for count, sr, sg, sb in ranked]
    primary = means[0][1]
    secondary = None
    for count, colour in means[1:]:
        if count / total < SECONDARY_SHARE:
            break
        if sum((a - b) ** 2 for a, b in zip(colour, primary)) ** 0.5 >= DISTINCT_DISTANCE:
            secondary = colour
            break
    return {"primary": _hex(primary), "secondary": _hex(secondary) if secondary else None}
