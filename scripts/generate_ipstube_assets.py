#!/usr/bin/env python3
"""Generate the small default IPSTube HTTP-control BMP asset set."""

from pathlib import Path
import shutil
import struct

WIDTH = 135
HEIGHT = 240
ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

PALETTE = [
    (0, 0, 0),
    (14, 18, 28),
    (245, 245, 245),
    (70, 230, 135),
    (70, 140, 255),
    (255, 180, 55),
    (255, 85, 95),
    (100, 110, 130),
    (235, 100, 210),
    (80, 225, 235),
] + [(0, 0, 0)] * 246

FONT = {
    "A": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
    "D": ("11110", "10001", "10001", "10001", "10001", "10001", "11110"),
    "E": ("11111", "10000", "10000", "11110", "10000", "10000", "11111"),
    "I": ("11111", "00100", "00100", "00100", "00100", "00100", "11111"),
    "K": ("10001", "10010", "10100", "11000", "10100", "10010", "10001"),
    "L": ("10000", "10000", "10000", "10000", "10000", "10000", "11111"),
    "N": ("10001", "11001", "11001", "10101", "10011", "10011", "10001"),
    "O": ("01110", "10001", "10001", "10001", "10001", "10001", "01110"),
    "R": ("11110", "10001", "10001", "11110", "10100", "10010", "10001"),
    "T": ("11111", "00100", "00100", "00100", "00100", "00100", "00100"),
    "W": ("10001", "10001", "10001", "10101", "10101", "10101", "01010"),
}


def canvas():
    return [[0] * WIDTH for _ in range(HEIGHT)]


def rect(pixels, x0, y0, x1, y1, color):
    for y in range(max(0, y0), min(HEIGHT, y1)):
        pixels[y][max(0, x0) : min(WIDTH, x1)] = [color] * max(0, min(WIDTH, x1) - max(0, x0))


def circle(pixels, cx, cy, radius, color):
    rr = radius * radius
    for y in range(max(0, cy - radius), min(HEIGHT, cy + radius + 1)):
        for x in range(max(0, cx - radius), min(WIDTH, cx + radius + 1)):
            if (x - cx) ** 2 + (y - cy) ** 2 <= rr:
                pixels[y][x] = color


def line(pixels, x0, y0, x1, y1, color, width=3):
    steps = max(abs(x1 - x0), abs(y1 - y0), 1)
    for step in range(steps + 1):
        x = round(x0 + (x1 - x0) * step / steps)
        y = round(y0 + (y1 - y0) * step / steps)
        rect(pixels, x - width // 2, y - width // 2, x + width // 2 + 1, y + width // 2 + 1, color)


def text(pixels, value, y, color, scale=3):
    glyph_width = 5 * scale
    spacing = scale
    total = len(value) * glyph_width + (len(value) - 1) * spacing
    x0 = (WIDTH - total) // 2
    for char_index, char in enumerate(value):
        glyph = FONT[char]
        origin = x0 + char_index * (glyph_width + spacing)
        for row, bits in enumerate(glyph):
            for column, bit in enumerate(bits):
                if bit == "1":
                    rect(
                        pixels,
                        origin + column * scale,
                        y + row * scale,
                        origin + (column + 1) * scale,
                        y + (row + 1) * scale,
                        color,
                    )


def pet(status_color, label, expression):
    pixels = canvas()
    rect(pixels, 10, 18, WIDTH - 10, HEIGHT - 18, 1)
    rect(pixels, 14, 22, WIDTH - 14, HEIGHT - 22, 0)
    circle(pixels, 67, 101, 47, status_color)
    rect(pixels, 27, 95, 108, 142, status_color)
    circle(pixels, 38, 63, 15, status_color)
    circle(pixels, 96, 63, 15, status_color)
    circle(pixels, 50, 102, 6, 0)
    circle(pixels, 84, 102, 6, 0)
    circle(pixels, 52, 100, 2, 2)
    circle(pixels, 86, 100, 2, 2)

    if expression == "idle":
        line(pixels, 46, 102, 56, 102, 2, 2)
        line(pixels, 80, 102, 90, 102, 2, 2)
        line(pixels, 57, 126, 77, 126, 0, 3)
        text(pixels, "IDLE", 184, status_color)
    elif expression == "work":
        line(pixels, 57, 125, 67, 130, 0, 3)
        line(pixels, 67, 130, 79, 122, 0, 3)
        for x, y in ((22, 153), (103, 153), (18, 168), (107, 168)):
            rect(pixels, x - 4, y - 4, x + 5, y + 5, 3)
        text(pixels, "WORK", 184, status_color)
    elif expression == "wait":
        line(pixels, 57, 127, 77, 127, 0, 3)
        circle(pixels, 67, 160, 14, 5)
        rect(pixels, 65, 149, 70, 162, 0)
        rect(pixels, 65, 168, 70, 173, 0)
        text(pixels, "WAIT", 184, status_color)
    else:
        line(pixels, 50, 123, 62, 135, 0, 5)
        line(pixels, 62, 135, 85, 114, 0, 5)
        circle(pixels, 67, 159, 17, 3)
        line(pixels, 57, 159, 65, 167, 0, 4)
        line(pixels, 65, 167, 79, 151, 0, 4)
        text(pixels, "DONE", 184, status_color)
    return pixels


def write_bmp(path, pixels):
    row_stride = (WIDTH + 3) & ~3
    pixel_offset = 14 + 40 + 256 * 4
    image_size = row_stride * HEIGHT
    file_size = pixel_offset + image_size
    with path.open("wb") as output:
        output.write(struct.pack("<2sIHHI", b"BM", file_size, 0, 0, pixel_offset))
        output.write(
            struct.pack(
                "<IiiHHIIiiII",
                40,
                WIDTH,
                HEIGHT,
                1,
                8,
                0,
                image_size,
                2835,
                2835,
                256,
                0,
            )
        )
        for red, green, blue in PALETTE:
            output.write(bytes((blue, green, red, 0)))
        padding = bytes(row_stride - WIDTH)
        for row in reversed(pixels):
            output.write(bytes(row))
            output.write(padding)


def generate():
    DATA.mkdir(exist_ok=True)
    for digit in range(10):
        shutil.copyfile(DATA / f"{10 + digit}.bmp", DATA / f"{digit}.bmp")

    colon = canvas()
    circle(colon, WIDTH // 2, 82, 11, 9)
    circle(colon, WIDTH // 2, 158, 11, 9)
    write_bmp(DATA / "250.bmp", colon)
    write_bmp(DATA / "251.bmp", pet(9, "IDLE", "idle"))
    write_bmp(DATA / "252.bmp", pet(3, "WORK", "work"))
    write_bmp(DATA / "253.bmp", pet(5, "WAIT", "wait"))
    write_bmp(DATA / "254.bmp", pet(4, "DONE", "done"))


if __name__ == "__main__":
    generate()
