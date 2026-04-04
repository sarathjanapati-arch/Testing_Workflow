from __future__ import annotations

import os
import random
import textwrap
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


@dataclass(frozen=True)
class GeneratedImages:
    profile_path: str
    cover_path: str
    post_path: str


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value).strip().lower()
    return text in {"1", "true", "yes", "y", "on", "enabled"}


def images_enabled(context_vars: dict[str, object]) -> bool:
    return _truthy(context_vars.get("generate_images")) or _truthy(os.getenv("GENERATE_IMAGES"))


def _safe_filename(value: str) -> str:
    allowed = []
    for ch in value.strip():
        if ch.isalnum():
            allowed.append(ch.lower())
        else:
            allowed.append("-")
    name = "".join(allowed)
    while "--" in name:
        name = name.replace("--", "-")
    return name.strip("-") or "image"


def _load_font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates = []
    if os.name == "nt":
        windir = os.getenv("WINDIR", r"C:\Windows")
        candidates.extend(
            [
                Path(windir) / "Fonts" / ("segoeuib.ttf" if bold else "segoeui.ttf"),
                Path(windir) / "Fonts" / ("arialbd.ttf" if bold else "arial.ttf"),
            ]
        )
    for path in candidates:
        try:
            if path.exists():
                return ImageFont.truetype(str(path), size=size)
        except Exception:
            continue
    return ImageFont.load_default()


def _initials(full_name: str) -> str:
    words = [w for w in full_name.replace(".", " ").split() if w]
    words = [w for w in words if w.lower() not in {"dr", "doctor"}]
    if not words:
        return "DR"
    if len(words) == 1:
        return words[0][:2].upper()
    return (words[0][:1] + words[-1][:1]).upper()


def _palette(rng: random.Random) -> tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]]:
    palettes = [
        ((23, 34, 64), (122, 35, 166), (255, 255, 255)),
        ((10, 80, 90), (32, 150, 125), (255, 255, 255)),
        ((60, 15, 70), (155, 45, 85), (255, 255, 255)),
        ((15, 25, 35), (60, 105, 180), (255, 255, 255)),
        ((45, 55, 65), (180, 90, 35), (255, 255, 255)),
    ]
    return rng.choice(palettes)


def _gradient(size: tuple[int, int], start: tuple[int, int, int], end: tuple[int, int, int]) -> Image.Image:
    width, height = size
    img = Image.new("RGB", size, start)
    draw = ImageDraw.Draw(img)
    for y in range(height):
        t = 0.0 if height <= 1 else y / (height - 1)
        r = int(start[0] + (end[0] - start[0]) * t)
        g = int(start[1] + (end[1] - start[1]) * t)
        b = int(start[2] + (end[2] - start[2]) * t)
        draw.line([(0, y), (width, y)], fill=(r, g, b))
    return img


def _wrap(text: str, width: int) -> list[str]:
    if not text:
        return []
    return textwrap.wrap(text.strip(), width=width, break_long_words=False, break_on_hyphens=False)


def generate_images_for_agent(
    *,
    output_dir: Path,
    run_timestamp: int,
    user_index: int,
    iteration_index: int,
    doctor_fullname: str,
    specialization_name: str,
    post_content: str,
) -> GeneratedImages:
    seed = (run_timestamp * 1_000_003) + (user_index * 9_973) + iteration_index
    rng = random.Random(seed)
    primary, secondary, text_color = _palette(rng)

    slug = _safe_filename(f"{doctor_fullname}-{specialization_name}-{user_index}-{iteration_index}")
    agent_dir = output_dir / f"run_{run_timestamp}" / f"agent_{user_index}" / f"iter_{iteration_index}"
    agent_dir.mkdir(parents=True, exist_ok=True)

    profile_path = agent_dir / f"profile_{slug}.jpg"
    cover_path = agent_dir / f"cover_{slug}.jpg"
    post_path = agent_dir / f"post_{slug}.jpg"

    # Profile (512x512): initials badge
    profile = _gradient((512, 512), primary, secondary)
    d = ImageDraw.Draw(profile)
    initials = _initials(doctor_fullname)
    font_big = _load_font(170, bold=True)
    font_small = _load_font(28, bold=False)
    d.ellipse((76, 86, 436, 446), outline=(255, 255, 255), width=10)
    bbox = d.textbbox((0, 0), initials, font=font_big)
    d.text(
        ((512 - (bbox[2] - bbox[0])) / 2, 150),
        initials,
        font=font_big,
        fill=text_color,
    )
    d.text((48, 468), doctor_fullname.strip(), font=font_small, fill=(245, 245, 250))

    # Cover (1200x400): name + specialization
    cover = _gradient((1200, 400), secondary, primary)
    d = ImageDraw.Draw(cover)
    font_name = _load_font(56, bold=True)
    font_spec = _load_font(34, bold=False)
    d.rounded_rectangle((40, 52, 1160, 348), radius=26, fill=(255, 255, 255, 255), outline=(255, 255, 255), width=3)
    d.text((80, 110), doctor_fullname.strip(), font=font_name, fill=(15, 15, 25))
    d.text((84, 185), specialization_name.strip() or "Specialist care", font=font_spec, fill=(70, 70, 90))
    d.text((84, 240), "DocSynapse • Test image", font=_load_font(22), fill=(110, 30, 160))

    # Post (1080x1080): quote-style snippet
    post = _gradient((1080, 1080), primary, (20, 20, 28))
    d = ImageDraw.Draw(post)
    font_title = _load_font(52, bold=True)
    font_body = _load_font(30, bold=False)
    font_footer = _load_font(26, bold=False)

    snippet = " ".join(post_content.strip().split())
    if len(snippet) > 260:
        snippet = snippet[:257].rstrip() + "..."
    lines = _wrap(snippet, 36)[:7]

    d.rounded_rectangle((70, 90, 1010, 980), radius=34, fill=(255, 255, 255), outline=(255, 255, 255), width=3)
    d.text((120, 140), "New Post", font=font_title, fill=(15, 15, 25))

    y = 230
    for line in lines:
        d.text((120, y), line, font=font_body, fill=(40, 40, 55))
        y += 44

    footer = f"{doctor_fullname.strip()} • {specialization_name.strip() or 'Specialist care'}"
    d.text((120, 915), footer, font=font_footer, fill=(110, 30, 160))

    # Save JPEGs
    profile.save(profile_path, format="JPEG", quality=92, optimize=True)
    cover.save(cover_path, format="JPEG", quality=92, optimize=True)
    post.save(post_path, format="JPEG", quality=92, optimize=True)

    return GeneratedImages(
        profile_path=str(profile_path.as_posix()),
        cover_path=str(cover_path.as_posix()),
        post_path=str(post_path.as_posix()),
    )

