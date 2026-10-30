"""Generate a small original synthetic fixture; no private photo or trained model."""
import json
from pathlib import Path
from PIL import Image, ImageDraw


def generate(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (480, 360), (20, 24, 20))
    draw = ImageDraw.Draw(image)
    draw.rectangle((15, 15, 465, 345), fill=(35, 168, 135))
    nodes = [(80, 80), (240, 80), (240, 240), (80, 240), (360, 80), (360, 240)]
    edges = [(0, 1), (1, 2), (2, 3), (3, 0), (4, 5)]
    for a, b in edges:
        draw.line((nodes[a], nodes[b]), fill=(27, 55, 40), width=13)
    for x, y in nodes:
        draw.ellipse((x-12, y-12, x+12, y+12), fill=(25, 50, 35))
        draw.ellipse((x-8, y-8, x+8, y+8), fill=(225, 227, 218))
    image.save(directory / "synthetic.png")
    (directory / "truth.json").write_text(json.dumps({"nodes": nodes, "edges": edges,
        "nets": [[0, 1, 2, 3], [4, 5]], "note": "Analytic fixture only; not representative of a real PCB photograph."}, indent=2) + "\n")


if __name__ == "__main__":
    generate(Path(__file__).parent)
