from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
png_path = ROOT / "packaging/assets/AIQuoteDualSystem_1024.png"
ico_path = ROOT / "packaging/assets/AIQuoteDualSystem.ico"

image = Image.open(png_path).convert("RGBA")
assert image.size == (1024, 1024)
assert image.getpixel((0, 0))[3] == 0
assert image.getpixel((512, 100))[:3] == (220, 232, 247)
assert image.getpixel((330, 350))[:3] == (37, 99, 235)
assert image.getpixel((650, 350))[:3] == (24, 95, 165)
green = image.getpixel((752, 756))[:3]
assert green == (139, 195, 74)

icon = Image.open(ico_path)
assert {(16, 16), (32, 32), (48, 48), (256, 256)} <= icon.info.get("sizes", set())
print("PASS: application icon matches the approved blue cabinet mark and Windows size layers")
