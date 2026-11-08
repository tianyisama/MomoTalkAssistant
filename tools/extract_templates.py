"""Developer-only asset extraction from the user's two local recordings.

Coordinates below describe source material, never runtime click positions.
The executable ships only small control templates, not the recordings.
"""
from pathlib import Path
import json
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "templates"
SOURCES = {
    "story": ROOT / "_analysis/video_review",
    "filter": ROOT / "_analysis/filter_review",
}

# name, source sequence, frame, source crop (1920 x 1080), threshold
SPECS = [
    ("home_phone", "story", 1, (177, 174, 233, 235), .78),
    ("home_notice", "story", 1, (47, 176, 96, 231), .75),
    ("momo_logo", "story", 4, (218, 159, 436, 199), .82),
    ("momo_close", "story", 4, (1650, 150, 1709, 207), .86),
    ("people_idle", "story", 4, (225, 258, 285, 315), .75),
    ("people_active", "story", 2, (225, 258, 285, 315), .75),
    ("chat_active", "story", 4, (225, 405, 285, 441), .75),
    ("chat_idle", "story", 2, (225, 405, 285, 441), .75),
    ("people_label", "story", 2, (347, 254, 412, 286), .81),
    ("empty_chat", "filter", 14, (1202, 565, 1537, 597), .83),
    ("filter_latest", "filter", 14, (770, 251, 827, 282), .84),
    ("filter_unread", "filter", 20, (770, 251, 827, 282), .84),
    ("sort_title", "filter", 14, (353, 335, 473, 368), .85),
    ("sort_unread_idle", "filter", 14, (802, 429, 868, 462), .82),
    ("sort_unread_active", "filter", 17, (802, 429, 868, 462), .82),
    ("sort_ok", "filter", 14, (646, 695, 701, 729), .82),
    ("reply_label", "story", 4, (1189, 650, 1302, 683), .83),
    ("bond_label", "story", 19, (1188, 798, 1333, 831), .83),
    ("story_start", "story", 20, (1189, 826, 1570, 870), .83),
    ("menu_light", "story", 24, (1738, 42, 1884, 81), .83),
    ("menu_dark", "story", 27, (1738, 42, 1884, 81), .83),
    ("fast_forward", "story", 27, (1785, 157, 1849, 200), .82),
    ("skip_question", "story", 28, (741, 648, 1180, 686), .83),
    ("skip_ok", "story", 28, (1112, 760, 1193, 808), .85),
    ("reward_title", "story", 30, (729, 193, 1195, 293), .83),
    ("reward_touch", "story", 30, (850, 929, 1069, 972), .83),
]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = {}
    atlas = Image.new("RGB", (1000, ((len(SPECS) + 3) // 4) * 140), "#e9edf1")
    draw = ImageDraw.Draw(atlas)
    for i, (name, source, number, box, threshold) in enumerate(SPECS):
        source_path = SOURCES[source] / f"frame_{number:03d}.jpg"
        im = Image.open(source_path).crop(box)
        size = (max(2, round(im.width * 2 / 3)), max(2, round(im.height * 2 / 3)))
        im = im.resize(size, Image.Resampling.LANCZOS)
        im.save(OUT / f"{name}.png")
        manifest[name] = {"file": f"{name}.png", "threshold": threshold,
                          "source": source_path.name, "source_crop": list(box)}
        thumb = im.copy(); thumb.thumbnail((230, 95))
        x, y = (i % 4) * 250, (i // 4) * 140
        draw.text((x + 8, y + 8), name, fill="#152334")
        atlas.paste(thumb, (x + 8, y + 37))
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    atlas.save(ROOT / "_analysis/template_atlas.png")
    print(f"Created {len(manifest)} templates")


if __name__ == "__main__":
    main()
