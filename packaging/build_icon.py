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

    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.rounded_rectangle(
        scaled_box((78, 92, 946, 960), scale),
        radius=210 * scale,
        fill=(1, 12, 24, 115),
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(26 * scale))
    canvas.alpha_composite(shadow)

    draw.rounded_rectangle(
        scaled_box((80, 70, 944, 934), scale),
        radius=210 * scale,
        fill=NAVY,
    )
    draw.rounded_rectangle(
        scaled_box((108, 96, 916, 390), scale),
        radius=160 * scale,
        fill=NAVY_2,
    )

    # Blue is formula pricing, mint is quick pricing.
    draw.rounded_rectangle(
        scaled_box((196, 214, 478, 760), scale),
        radius=66 * scale,
        fill=BLUE,
    )
    draw.rounded_rectangle(
        scaled_box((546, 214, 828, 760), scale),
        radius=66 * scale,
        fill=MINT,
    )

    # Folded corners make the mark specific to sheet-metal cabinet work.
    draw.polygon(
        [(382 * scale, 214 * scale), (478 * scale, 214 * scale), (478 * scale, 310 * scale)],
        fill=BLUE_HI,
    )
    draw.line(
        [(382 * scale, 214 * scale), (478 * scale, 310 * scale)],
        fill=ICE,
        width=12 * scale,
    )
    draw.polygon(
        [(546 * scale, 214 * scale), (642 * scale, 214 * scale), (546 * scale, 310 * scale)],
        fill=MINT_HI,
    )
    draw.line(
        [(642 * scale, 214 * scale), (546 * scale, 310 * scale)],
        fill=WHITE,
        width=12 * scale,
    )

    for x in (250, 600):
        draw.rounded_rectangle(
            scaled_box((x, 404, x + 174, 438), scale),
            radius=17 * scale,
            fill=WHITE,
        )
        draw.rounded_rectangle(
            scaled_box((x, 488, x + 132, 522), scale),
            radius=17 * scale,
            fill=WHITE,
        )

    # Cabinet-door split and comparison axis.
    draw.rounded_rectangle(
        scaled_box((496, 270, 528, 690), scale),
        radius=16 * scale,
        fill=WHITE,
    )
    draw.line(
        [(512 * scale, 684 * scale), (430 * scale, 790 * scale)],
        fill=WHITE,
        width=32 * scale,
    )
    draw.line(
        [(512 * scale, 684 * scale), (594 * scale, 790 * scale)],
        fill=WHITE,
        width=32 * scale,
    )

    draw.ellipse(scaled_box((744, 806, 806, 868), scale), fill=MINT_HI)
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
