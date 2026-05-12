from __future__ import annotations

import os
import random
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from .seed import agent_seed

PromptTemplate: Any = None
StableDiffusionPipeline: Any = None
torch: Any = None


@dataclass(frozen=True)
class GeneratedImages:
    profile_path: str
    cover_path: str
    post_path: str


_POST_CHAIN: Any = None
_IMAGE_PIPELINE: Any = None


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


def _get_post_chain() -> Any:
    global _POST_CHAIN, PromptTemplate
    if _POST_CHAIN is not None:
        return _POST_CHAIN
    try:
        from langchain_ollama import OllamaLLM
        from langchain_core.prompts import PromptTemplate as ImportedPromptTemplate
    except Exception:
        try:
            # Fallback to deprecated path if langchain-ollama not installed
            from langchain_community.llms import Ollama as OllamaLLM  # type: ignore[no-redef]
            from langchain_core.prompts import PromptTemplate as ImportedPromptTemplate
        except Exception:
            return None
    PromptTemplate = ImportedPromptTemplate

    prompt = PromptTemplate(
        input_variables=["Topic", "Style", "ExtraInfo"],
        template=(
            "You are a practicing Indian doctor writing a professional post on DocSynapse, "
            "a social platform for medical professionals.\n\n"
            "Write a {Style} post about \"{Topic}\" that reads like it was written by a real clinician — "
            "not a press release or a generic health tip article.\n\n"
            "Doctor context:\n{ExtraInfo}\n\n"
            "Requirements:\n"
            "- 150 to 220 words, no more.\n"
            "- Open with a specific clinical observation, a real challenge you face, or a question to peers — "
            "NOT a generic greeting like 'Hello everyone'.\n"
            "- Include one concrete insight, lesson, or perspective from your specialty.\n"
            "- End with a genuine call for peer input, collaboration, or referral discussion.\n"
            "- Tone must match the doctor's stated style: {Style}.\n"
            "- Write in first person as the doctor. Sound human, not corporate.\n"
            "- Add 2–3 specialty-relevant hashtags at the end on their own line.\n"
            "- Do NOT include a subject line, title, or any meta-commentary — just the post text.\n"
        ),
    )
    llm = OllamaLLM(model=os.getenv("OLLAMA_TEXT_MODEL", os.getenv("OLLAMA_MODEL", "gemma:7b")))
    _POST_CHAIN = prompt | llm
    return _POST_CHAIN


def _fallback_social_content(
    rng: random.Random,
    context_vars: dict[str, Any],
    user_index: int,
    iteration_index: int,
) -> dict[str, Any]:
    first_name = str(context_vars.get("doctor_first_name") or "Doctor").strip()
    full_name = str(context_vars.get("doctor_fullname") or f"Dr. {first_name}").strip()
    specialization_name = str(
        context_vars.get("specialization_name")
        or context_vars.get("specialization_id")
        or "specialist care"
    ).strip()
    years = context_vars.get("years_of_experience", "")
    company_name = str(context_vars.get("company_name") or "our institution").strip()
    short_bio = str(context_vars.get("short_bio") or "").strip()
    doctor_tone = str(context_vars.get("doctor_tone") or "professional").strip().lower()
    profile_focus = str(context_vars.get("profile_focus") or specialization_name).strip()

    years_str = f"{years} years" if years else "several years"

    # Clinical insight sentences vary by specialization context
    clinical_insights = [
        f"One thing I have learned over {years_str} in {specialization_name} is that the best outcomes come from listening closely before acting.",
        f"In {specialization_name}, early detection and clear patient communication consistently make the biggest difference.",
        f"A recurring challenge in {specialization_name} is ensuring continuity of care — something I believe peer networks like this one can genuinely help address.",
        f"Multidisciplinary collaboration has transformed how I approach complex {specialization_name} cases, and I hope to bring that perspective here.",
        f"Evidence-based practice in {specialization_name} continues to evolve rapidly — staying updated through peer conversations is essential.",
        f"What I find most rewarding in {specialization_name} is translating complex findings into care plans patients actually understand and follow.",
    ]
    community_questions = [
        f"Would love to hear from others working in {specialization_name} — what referral patterns have you found most effective?",
        f"Curious how peers handle the documentation load while maintaining quality {specialization_name} consultations.",
        f"Are there specific digital tools the community recommends for {specialization_name} case tracking?",
        f"Happy to connect with anyone working at the intersection of {specialization_name} and preventive care.",
    ]
    join_lines = [
        f"I am {full_name}, a {specialization_name} specialist with {years_str} of clinical experience, joining DocSynapse to build meaningful professional connections.",
        f"Joining this community as a {specialization_name} practitioner based at {company_name}. {years_str.capitalize()} in practice has taught me that peer learning is irreplaceable.",
        f"{full_name} here — {specialization_name} specialist, {years_str} in practice, and genuinely excited to engage with a community of dedicated clinicians.",
        f"Hello from {company_name}. I am {full_name}, and I work in {specialization_name}. Looking forward to meaningful clinical dialogue on this platform.",
    ]
    tag_sets = [
        [specialization_name.lower().replace(" ", ""), "clinicalpractice", "docsynapse"],
        ["medicalnetwork", specialization_name.lower().replace(" ", ""), "collaboration"],
        ["doctorcommunity", "evidencebasedmedicine", specialization_name.lower().replace(" ", "")],
        ["specialistcare", "referrals", specialization_name.lower().replace(" ", "")],
        ["continuityofcare", "medicallearning", "docsynapse"],
    ]

    # Tone-aware post assembly
    if doctor_tone in {"informative", "educational"}:
        body = rng.choice(clinical_insights)
        closing = rng.choice(community_questions)
    elif doctor_tone in {"warm", "friendly"}:
        body = rng.choice(community_questions)
        closing = f"Currently at {company_name} and open to collaboration, referrals, and knowledge exchange."
    elif doctor_tone in {"direct", "concise"}:
        body = rng.choice(clinical_insights)
        closing = f"Open to referrals and peer consultations in {specialization_name}. Feel free to connect."
    else:
        body = rng.choice(clinical_insights)
        closing = rng.choice(community_questions)

    create_content = f"{rng.choice(join_lines)} {body} {closing}"

    update_content = (
        f"{create_content} — Update: after a few days on the platform I have already found the referral "
        f"conversations particularly useful. The {profile_focus} focus area has great representation here."
    )

    tag_set = rng.choice(tag_sets)
    public_image_url = "https://acintyotech-public.s3.ap-south-1.amazonaws.com/assets/e04a8228-ccee-4794-95e3-3d2a6a19474b.jpg"

    return {
        "post_content": create_content,
        "update_post_content": update_content,
        "post_tag_1": tag_set[0],
        "post_tag_2": tag_set[1],
        "post_tag_3": tag_set[2],
        "profile_photo_url": public_image_url,
        "cover_photo_url": public_image_url,
        "post_image_url": public_image_url,
    }


def generate_social_content_for_agent(
    rng: random.Random,
    context_vars: dict[str, Any],
    user_index: int,
    iteration_index: int,
) -> dict[str, Any]:
    if not _truthy(os.getenv("OLLAMA_GENERATE_POSTS", "true")):
        return _fallback_social_content(rng, context_vars, user_index, iteration_index)

    chain = _get_post_chain()
    if chain is None:
        return _fallback_social_content(rng, context_vars, user_index, iteration_index)

    specialization_name = str(
        context_vars.get("specialization_name")
        or context_vars.get("specialization_id")
        or "specialist care"
    ).strip()
    company_name = str(context_vars.get("company_name") or "healthcare practice").strip()
    profile_focus = str(context_vars.get("profile_focus") or f"{specialization_name} practice").strip()
    topic = profile_focus
    style = str(context_vars.get("doctor_tone") or "informative").strip() or "informative"
    years = context_vars.get("years_of_experience", "")
    extra_info = (
        f"Name: {context_vars.get('doctor_fullname', 'Doctor')}.\n"
        f"Specialty: {specialization_name}.\n"
        f"Current focus: {profile_focus}.\n"
        f"Institution: {company_name}.\n"
        f"Years of experience: {years}.\n"
        f"Short bio: {context_vars.get('short_bio', '')}.\n"
        f"Motivation for joining: {context_vars.get('onboarding_motivation', '')}.\n"
        f"Engagement preference: {context_vars.get('engagement_preference', '')}.\n"
        f"Write a post that is distinctly different from a generic introduction — "
        f"agent {user_index}, run {iteration_index}."
    )

    try:
        post = str(
            chain.invoke(
                {
                    "Topic": topic,
                    "Style": style,
                    "ExtraInfo": extra_info,
                }
            )
        ).strip()
        if not post:
            raise RuntimeError("Ollama returned an empty post.")
        update_post = (
            f"{post}\n\nUpdate note: continuing to learn and collaborate with peers in {specialization_name}. "
            f"Run marker {user_index}-{iteration_index}."
        ).strip()
        public_image_url = "https://acintyotech-public.s3.ap-south-1.amazonaws.com/assets/e04a8228-ccee-4794-95e3-3d2a6a19474b.jpg"
        return {
            "post_content": post,
            "update_post_content": update_post,
            "post_tag_1": specialization_name.lower().replace(" ", ""),
            "post_tag_2": "doctorcommunity",
            "post_tag_3": "healthcare",
            "profile_photo_url": public_image_url,
            "cover_photo_url": public_image_url,
            "post_image_url": public_image_url,
        }
    except Exception:
        return _fallback_social_content(rng, context_vars, user_index, iteration_index)


def _get_image_pipeline() -> Any:
    global _IMAGE_PIPELINE, StableDiffusionPipeline, torch
    if _IMAGE_PIPELINE is not None:
        return _IMAGE_PIPELINE
    if not _truthy(os.getenv("OLLAMA_USE_DIFFUSERS_IMAGES", "true")):
        return None
    if StableDiffusionPipeline is None:
        try:
            from diffusers import StableDiffusionPipeline as ImportedStableDiffusionPipeline
            StableDiffusionPipeline = ImportedStableDiffusionPipeline
        except Exception:
            return None
    if torch is None:
        try:
            import torch as imported_torch
            torch = imported_torch
        except Exception:
            torch = None

    model_name = os.getenv("DIFFUSERS_MODEL", "runwayml/stable-diffusion-v1-5")
    try:
        pipeline = StableDiffusionPipeline.from_pretrained(model_name)
        device = os.getenv("DIFFUSERS_DEVICE", "")
        if torch is not None:
            if device:
                pipeline = pipeline.to(device)
            elif torch.cuda.is_available():
                pipeline = pipeline.to("cuda")
        _IMAGE_PIPELINE = pipeline
        return _IMAGE_PIPELINE
    except Exception:
        return None


def _generate_with_diffusers(prompt: str, output_path: Path) -> bool:
    pipeline = _get_image_pipeline()
    if pipeline is None:
        return False
    try:
        image = pipeline(prompt).images[0]
        image.save(output_path)
        return True
    except Exception:
        return False


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
    seed = agent_seed(run_timestamp, user_index, iteration_index)
    rng = random.Random(seed)
    primary, secondary, text_color = _palette(rng)

    slug = _safe_filename(f"{doctor_fullname}-{specialization_name}-{user_index}-{iteration_index}")
    agent_dir = output_dir / f"run_{run_timestamp}" / f"agent_{user_index}" / f"iter_{iteration_index}"
    agent_dir.mkdir(parents=True, exist_ok=True)

    profile_path = agent_dir / f"profile_{slug}.jpg"
    cover_path = agent_dir / f"cover_{slug}.jpg"
    post_path = agent_dir / f"post_{slug}.jpg"

    # Try Stable Diffusion first for the post image in the Ollama workflow.
    image_prompt = (
        f"Professional healthcare illustration for doctors about {specialization_name}. "
        f"Represent: {post_content[:180]}. "
        "Visually appealing, medically relevant, clean composition, no text."
    )
    _generate_with_diffusers(image_prompt, post_path)

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
    d.text((84, 240), "DocSynapse Test image", font=_load_font(22), fill=(110, 30, 160))

    # Fallback post image if Diffusers was unavailable.
    if not post_path.exists():
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

        footer = f"{doctor_fullname.strip()} | {specialization_name.strip() or 'Specialist care'}"
        d.text((120, 915), footer, font=font_footer, fill=(110, 30, 160))
        post.save(post_path, format="JPEG", quality=92, optimize=True)

    profile.save(profile_path, format="JPEG", quality=92, optimize=True)
    cover.save(cover_path, format="JPEG", quality=92, optimize=True)

    return GeneratedImages(
        profile_path=str(profile_path.as_posix()),
        cover_path=str(cover_path.as_posix()),
        post_path=str(post_path.as_posix()),
    )
