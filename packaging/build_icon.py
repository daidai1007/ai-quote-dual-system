"""Generate the AI dual-quote application and NSIS installer artwork."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


HERE = Path(__file__).resolve().parent
ASSETS = HERE / "assets"
ASSETS.mkdir(parents=True, exist_ok=True)

NAVY = "#0B1F33"
NAVY_2 = "#123A5A"
BLUE = "#1682D4"
BLUE_HI = "#55B8F3"
MINT = "#28B58C"
MINT_HI = "#72E0BE"
WHITE = "#F5FBFF"
ICE = "#CBEFFF"


def scaled_box(box: tuple[int, int, int, int], scale: int) -> tuple[int, int, int, int]:
    return tuple(value * scale for value in box)


def draw_mark(size: int = 1024) -> Image.Image:
    scale = 4
    canvas = Image.new("RGBA", (size * scale, size * scale), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    # Pale-blue rounded tile from the approved application-icon reference.
    draw.rounded_rectangle(
        scaled_box((116, 70, 908, 946), scale),
        radius=188 * scale,
        fill="#DCE8F7",
    )

    # Two cabinet doors: formula pricing blue and deep-blue quick pricing.
    draw.rounded_rectangle(
        scaled_box((254, 270, 496, 690), scale),
        radius=48 * scale,
        fill="#2563EB",
    )
    draw.rounded_rectangle(
        scaled_box((528, 270, 770, 690), scale),
        radius=48 * scale,
        fill="#185FA5",
    )

    for x in (308, 582):
        draw.rounded_rectangle(
            scaled_box((x, 424, x + 118, 454), scale),
            radius=15 * scale,
            fill="#FFFFFF",
        )
        draw.rounded_rectangle(
            scaled_box((x, 504, x + 72, 534), scale),
            radius=15 * scale,
            fill="#FFFFFF",
        )

    # Central divider and open support legs match the supplied mark.
    draw.rounded_rectangle(
        scaled_box((492, 196, 532, 664), scale),
        radius=20 * scale,
        fill="#1F3A6A",
    )
    draw.line(
        [(512 * scale, 650 * scale), (416 * scale, 786 * scale)],
        fill="#1F3A6A",
        width=40 * scale,
    )
    draw.line(
        [(512 * scale, 650 * scale), (608 * scale, 786 * scale)],
        fill="#1F3A6A",
        width=40 * scale,
    )

    draw.ellipse(scaled_box((714, 718, 790, 794), scale), fill="#8BC34A")
    return canvas.resize((size, size), Image.Resampling.LANCZOS)


def make_sidebar(icon: Image.Image) -> Image.Image:
    image = Image.new("RGB", (164, 314), NAVY)
    draw = ImageDraw.Draw(image)
    for y in range(314):
        blend = y / 313
        r = int(11 + (18 - 11) * blend)
        g = int(31 + (58 - 31) * blend)
        b = int(51 + (90 - 51) * blend)
        draw.line((0, y, 164, y), fill=(r, g, b))
    draw.polygon([(0, 224), (164, 152), (164, 210), (0, 282)], fill="#126AA8")
    draw.polygon([(42, 314), (164, 258), (164, 314)], fill=MINT)
    mark = icon.resize((112, 112), Image.Resampling.LANCZOS)
    image.paste(mark, (26, 28), mark)
    draw.rounded_rectangle((26, 174, 138, 178), radius=2, fill=BLUE_HI)
    draw.rounded_rectangle((26, 190, 108, 194), radius=2, fill=MINT_HI)
    return image


def make_header(icon: Image.Image) -> Image.Image:
    image = Image.new("RGB", (150, 57), "#F5F8FA")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 53, 150, 57), fill=BLUE)
    draw.rectangle((104, 53, 150, 57), fill=MINT)
    mark = icon.resize((48, 48), Image.Resampling.LANCZOS)
    image.paste(mark, (96, 3), mark)
    return image


def main() -> None:
    icon = draw_mark()
    icon.save(ASSETS / "AIQuoteDualSystem_1024.png")
    icon.save(
        ASSETS / "AIQuoteDualSystem.ico",
        format="ICO",
        sizes=[(16, 16), (20, 20), (24, 24), (32, 32), (40, 40), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    make_sidebar(icon).save(ASSETS / "installer_sidebar.bmp")
    make_header(icon).save(ASSETS / "installer_header.bmp")


if __name__ == "__main__":
    main()
