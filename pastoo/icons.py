"""The app icon: an upward arrow on a rounded square, coloured by the backup's health."""
import io

from PIL import Image, ImageDraw

COLOURS = {
    "ok": (63, 185, 80),         # a recent good backup
    "old": (210, 153, 34),       # no good backup for a while
    "failed": (248, 81, 73),     # the last run failed
    "running": (61, 139, 253),   # backing up now
    "held": (210, 153, 34),      # an automatic backup waits for a look at its changes
}


def icon(size, health="ok"):
    s = size * 4                                    # draw big, shrink = smooth edges
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, s - 1, s - 1), radius=s // 5, fill=COLOURS.get(health, COLOURS["ok"]))
    white = (255, 255, 255)
    cx, w = s // 2, s // 7
    d.polygon([(cx, s * 0.16), (s * 0.80, s * 0.52), (cx + w, s * 0.52), (cx + w, s * 0.62),
               (cx - w, s * 0.62), (cx - w, s * 0.52), (s * 0.20, s * 0.52)], fill=white)   # arrow
    d.rectangle((s * 0.22, s * 0.72, s * 0.78, s * 0.82), fill=white)                       # base line
    return img.resize((size, size), Image.LANCZOS)


def png(image):
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
