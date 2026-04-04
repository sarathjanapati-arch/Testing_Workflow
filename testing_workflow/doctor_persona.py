from __future__ import annotations

import json
import os
import random
import time
from typing import Any

import requests

NAME_STARTS = ["an", "ar", "di", "ish", "ka", "me", "na", "ra", "sa", "vi"]
NAME_MIDDLES = ["ya", "va", "ni", "ra", "shi", "ta", "na", "la", "mi", "ri"]
NAME_ENDS = ["n", "a", "an", "ya", "it", "al", "esh", "ika", "am", "ya"]

SURNAME_STARTS = ["bh", "gu", "iy", "ka", "meh", "na", "red", "sh", "var", "ver"]
SURNAME_ENDS = ["atia", "pta", "er", "oor", "ta", "ir", "dy", "arma", "ma", "ma"]

MEDICAL_COUNCIL_BOARDS = [
    "Andhra Pradesh Medical Council",
    "Delhi Medical Council",
    "Karnataka Medical Council",
    "Maharashtra Medical Council",
    "Tamil Nadu Medical Council",
    "Telangana State Medical Council",
]

SHORT_BIOS = [
    "Cardiologist focused on preventive care, diagnostics, and patient education.",
    "Internal medicine specialist with a strong interest in continuity of care.",
    "Physician dedicated to evidence-based treatment and compassionate consultations.",
    "Doctor experienced in outpatient care, follow-ups, and multidisciplinary coordination.",
]

POOL_SIZE = 1000


def _slugify(value: str) -> str:
    allowed = [ch.lower() if ch.isalnum() else "." for ch in value.strip()]
    slug = "".join(allowed)
    while ".." in slug:
        slug = slug.replace("..", ".")
    return slug.strip(".") or "doctor"


def _capitalize_name(value: str) -> str:
    return value[:1].upper() + value[1:].lower()


def _build_generated_name(rng: random.Random) -> tuple[str, str]:
    first_name = _capitalize_name(
        rng.choice(NAME_STARTS) + rng.choice(NAME_MIDDLES) + rng.choice(NAME_ENDS)
    )
    last_name = _capitalize_name(rng.choice(SURNAME_STARTS) + rng.choice(SURNAME_ENDS))
    return first_name, last_name


def build_template_identity(
    rng: random.Random,
    run_timestamp: int,
    user_index: int,
    iteration_index: int,
) -> dict[str, Any]:
    first_name, last_name = _build_generated_name(rng)
    full_name = f"Dr. {first_name} {last_name}"
    email_local = f"dr.{_slugify(first_name)}.{_slugify(last_name)}"
    registration_number = f"AP{run_timestamp}{user_index:03d}{iteration_index:02d}"
    years_of_experience = 5 + ((user_index + iteration_index) % 16)
    month = 1 + ((user_index + iteration_index) % 12)
    day = 1 + ((user_index * 3 + iteration_index) % 28)
    year = 1978 + ((user_index + iteration_index) % 18)
    gender = "Female" if (user_index + iteration_index) % 2 == 0 else "Male"
    return {
        "doctor_first_name": first_name,
        "doctor_last_name": last_name,
        "doctor_fullname": full_name,
        "doctor_email_local": email_local,
        "registration_number": registration_number,
        "years_of_experience": years_of_experience,
        "date_of_birth": f"{year:04d}-{month:02d}-{day:02d}",
        "gender": gender,
        "medical_council_board": rng.choice(MEDICAL_COUNCIL_BOARDS),
        "short_bio": rng.choice(SHORT_BIOS),
        "identity_source": "template",
    }


def _build_identity_pool() -> list[dict[str, Any]]:
    pool: list[dict[str, Any]] = []
    seen_emails: set[str] = set()
    seed = 20260404
    index = 0
    while len(pool) < POOL_SIZE:
        rng = random.Random(seed + index)
        identity = build_template_identity(
            rng=rng,
            run_timestamp=seed,
            user_index=(index % POOL_SIZE) + 1,
            iteration_index=1,
        )
        email_local = str(identity["doctor_email_local"])
        if email_local in seen_emails:
            index += 1
            continue
        seen_emails.add(email_local)
        identity["identity_source"] = "pool"
        identity["identity_pool_index"] = len(pool)
        pool.append(identity)
        index += 1
    return pool


IDENTITY_POOL = _build_identity_pool()


def build_pooled_identity(
    run_timestamp: int,
    user_index: int,
    iteration_index: int,
) -> dict[str, Any]:
    pool_index = ((user_index - 1) * 37 + (iteration_index - 1)) % len(IDENTITY_POOL)
    identity = dict(IDENTITY_POOL[pool_index])
    identity["registration_number"] = f"AP{run_timestamp}{user_index:03d}{iteration_index:02d}"
    return identity


def _request_openai_identity(
    rng: random.Random,
    run_timestamp: int,
    user_index: int,
    iteration_index: int,
) -> dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set.")

    model = os.getenv("OPENAI_MODEL", "gpt-5.2").strip() or "gpt-5.2"
    timeout_seconds = float(os.getenv("OPENAI_TIMEOUT_SECONDS", "30"))
    max_attempts = max(1, int(os.getenv("OPENAI_IDENTITY_MAX_RETRIES", "4")))
    base_backoff_seconds = float(os.getenv("OPENAI_IDENTITY_BACKOFF_SECONDS", "1.5"))
    seed = (run_timestamp * 1_000_003) + (user_index * 9_973) + iteration_index

    prompt = (
        "Generate a unique virtual doctor persona for API testing. "
        "Return only valid JSON with these keys: "
        "first_name, last_name, gender, date_of_birth, years_of_experience, short_bio, medical_council_board. "
        "Use realistic Indian doctor details. "
        "date_of_birth must be YYYY-MM-DD. years_of_experience must be an integer from 3 to 25. "
        f"Distinct seed: {seed}. "
        f"Agent number: {user_index}. Iteration: {iteration_index}."
    )

    response: requests.Response | None = None
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            response = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [
                        {
                            "role": "developer",
                            "content": "You generate realistic but synthetic doctor personas for automated testing. Reply with JSON only.",
                        },
                        {
                            "role": "user",
                            "content": prompt,
                        },
                    ],
                    "response_format": {"type": "json_object"},
                    "reasoning_effort": os.getenv("OPENAI_REASONING_EFFORT", "low"),
                },
                timeout=timeout_seconds,
            )
            response.raise_for_status()
            break
        except requests.HTTPError as err:
            last_error = err
            status_code = err.response.status_code if err.response is not None else None
            if status_code != 429 or attempt >= max_attempts:
                raise
            retry_after_header = err.response.headers.get("retry-after") if err.response is not None else None
            if retry_after_header and retry_after_header.isdigit():
                sleep_seconds = float(retry_after_header)
            else:
                sleep_seconds = base_backoff_seconds * (2 ** (attempt - 1))
            sleep_seconds += rng.uniform(0.0, 0.5)
            time.sleep(sleep_seconds)
        except Exception as err:
            last_error = err
            raise

    if response is None:
        if last_error is not None:
            raise last_error
        raise RuntimeError("OpenAI persona request did not return a response.")

    payload = response.json()
    content = payload["choices"][0]["message"]["content"]
    data = json.loads(content)

    first_name = str(data["first_name"]).strip()
    last_name = str(data["last_name"]).strip()
    full_name = f"Dr. {first_name} {last_name}"
    email_local = f"dr.{_slugify(first_name)}.{_slugify(last_name)}"
    registration_number = f"AP{run_timestamp}{user_index:03d}{iteration_index:02d}"

    return {
        "doctor_first_name": first_name,
        "doctor_last_name": last_name,
        "doctor_fullname": full_name,
        "doctor_email_local": email_local,
        "registration_number": registration_number,
        "years_of_experience": int(data["years_of_experience"]),
        "date_of_birth": str(data["date_of_birth"]).strip(),
        "gender": str(data["gender"]).strip(),
        "medical_council_board": str(data["medical_council_board"]).strip(),
        "short_bio": str(data["short_bio"]).strip(),
        "identity_source": "openai",
    }


def build_doctor_identity(
    rng: random.Random,
    run_timestamp: int,
    user_index: int,
    iteration_index: int,
) -> dict[str, Any]:
    mode = os.getenv("DOCTOR_IDENTITY_MODE", "template").strip().lower()
    if mode == "pool":
        return build_pooled_identity(run_timestamp, user_index, iteration_index)
    if mode != "openai":
        return build_template_identity(rng, run_timestamp, user_index, iteration_index)

    try:
        return _request_openai_identity(rng, run_timestamp, user_index, iteration_index)
    except Exception as err:
        fallback = build_template_identity(rng, run_timestamp, user_index, iteration_index)
        fallback["identity_source"] = "template_fallback"
        fallback["identity_error"] = str(err)
        return fallback
