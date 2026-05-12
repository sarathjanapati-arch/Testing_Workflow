from __future__ import annotations

import json
import os
import random
import time
from typing import Any

import requests

from .seed import agent_seed

POOL_SIZE = 1000


def _slugify(value: str) -> str:
    allowed = [ch.lower() if ch.isalnum() else "." for ch in value.strip()]
    slug = "".join(allowed)
    while ".." in slug:
        slug = slug.replace("..", ".")
    return slug.strip(".") or "doctor"


def build_template_identity(
    rng: random.Random,
    run_timestamp: int,
    user_index: int,
    iteration_index: int,
) -> dict[str, Any]:
    fallback_first_names = [
        "Aarav",
        "Anika",
        "Divya",
        "Ishaan",
        "Kavya",
        "Meera",
        "Naina",
        "Raghav",
        "Saanvi",
        "Vihaan",
    ]
    fallback_last_names = [
        "Bhatia",
        "Gupta",
        "Iyer",
        "Kapoor",
        "Mehra",
        "Nair",
        "Reddy",
        "Sharma",
        "Varma",
        "Verma",
    ]
    fallback_boards = [
        "Andhra Pradesh Medical Council",
        "Delhi Medical Council",
        "Karnataka Medical Council",
        "Maharashtra Medical Council",
        "Tamil Nadu Medical Council",
        "Telangana State Medical Council",
    ]
    fallback_bios = [
        "Doctor focused on evidence-based care, collaboration, and patient communication.",
        "Healthcare professional with an interest in preventive care and clinical learning.",
        "Practitioner committed to compassionate consultations and better health outcomes.",
        "Doctor engaged in multidisciplinary care, follow-ups, and professional networking.",
    ]

    first_name = rng.choice(fallback_first_names)
    last_name = rng.choice(fallback_last_names)
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
        "medical_council_board": rng.choice(fallback_boards),
        "short_bio": rng.choice(fallback_bios),
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
            email_local = f"{email_local}.{len(pool) + 1}"
            identity["doctor_email_local"] = email_local
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


def _extract_json_text(payload: dict[str, Any]) -> str:
    if isinstance(payload.get("response"), str):
        return str(payload["response"])

    message = payload.get("message")
    if isinstance(message, dict) and isinstance(message.get("content"), str):
        return str(message["content"])

    raise RuntimeError(f"Unexpected Ollama response payload: {payload}")


def _ollama_generate_json(
    rng: random.Random,
    prompt: str,
    seed: int,
    max_retries_env: str = "OLLAMA_IDENTITY_MAX_RETRIES",
    error_label: str = "Ollama request",
) -> dict[str, Any]:
    base_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").strip().rstrip("/")
    model = os.getenv("OLLAMA_MODEL", "llama3.1").strip() or "llama3.1"
    timeout_seconds = float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "60"))
    max_attempts = max(1, int(os.getenv(max_retries_env, "3")))
    base_backoff_seconds = float(os.getenv("OLLAMA_IDENTITY_BACKOFF_SECONDS", "1.5"))

    request_body = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {
            "temperature": float(os.getenv("OLLAMA_TEMPERATURE", "0.7")),
            "seed": seed,
        },
    }

    response: requests.Response | None = None
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            response = requests.post(
                f"{base_url}/api/generate",
                headers={"Content-Type": "application/json"},
                json=request_body,
                timeout=timeout_seconds,
            )
            response.raise_for_status()
            break
        except Exception as err:
            last_error = err
            if attempt >= max_attempts:
                raise
            time.sleep(base_backoff_seconds * attempt + rng.uniform(0.0, 0.5))

    if response is None:
        if last_error is not None:
            raise last_error
        raise RuntimeError(f"{error_label} did not return a response.")

    payload = response.json()
    content = _extract_json_text(payload)
    return json.loads(content)


def _request_ollama_identity(
    rng: random.Random,
    run_timestamp: int,
    user_index: int,
    iteration_index: int,
) -> dict[str, Any]:
    seed = agent_seed(run_timestamp, user_index, iteration_index)

    prompt = (
        "Generate a unique synthetic Indian doctor persona for automated API workflow testing. "
        "This persona will behave like an autonomous doctor agent performing signup, signin, profile updates, posting, and networking actions. "
        "Return only valid JSON with these keys: "
        "first_name, last_name, gender, date_of_birth, years_of_experience, short_bio, medical_council_board, "
        "doctor_tone, profile_focus, onboarding_motivation. "
        "Use realistic Indian doctor details and make each agent distinct. "
        "The short_bio must sound natural and professional, suitable for a doctor profile. "
        "medical_council_board must be a realistic Indian medical council board name. "
        "doctor_tone should be a short descriptor like informative, warm, direct, reflective, or upbeat. "
        "profile_focus should be a short phrase about the doctor's clinical or professional interests. "
        "onboarding_motivation should be one sentence about why this doctor is joining the platform. "
        "date_of_birth must be YYYY-MM-DD. "
        "years_of_experience must be an integer from 3 to 25. "
        f"Distinct seed: {seed}. Agent number: {user_index}. Iteration: {iteration_index}."
    )

    data = _ollama_generate_json(
        rng, prompt, seed,
        max_retries_env="OLLAMA_IDENTITY_MAX_RETRIES",
        error_label="Ollama persona request",
    )

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
        "doctor_tone": str(data.get("doctor_tone", "")).strip(),
        "profile_focus": str(data.get("profile_focus", "")).strip(),
        "onboarding_motivation": str(data.get("onboarding_motivation", "")).strip(),
        "identity_source": "ollama",
    }


_MEDICAL_COLLEGES = [
    "All India Institute of Medical Sciences, New Delhi",
    "Christian Medical College, Vellore",
    "Maulana Azad Medical College, Delhi",
    "Seth GS Medical College, Mumbai",
    "Kasturba Medical College, Manipal",
    "Sri Ramachandra Institute of Higher Education, Chennai",
    "Jawaharlal Nehru Medical College, Belgaum",
    "Amrita Institute of Medical Sciences, Kochi",
    "Gandhi Medical College, Hyderabad",
    "Osmania Medical College, Hyderabad",
    "Andhra Medical College, Visakhapatnam",
    "Bangalore Medical College and Research Institute",
    "Grant Medical College, Mumbai",
    "Kilpauk Medical College, Chennai",
    "Rajiv Gandhi Government General Hospital, Chennai",
]

_EXPERIENCE_START_YEARS = [
    "2014-07-01", "2015-01-15", "2016-03-01", "2017-06-01",
    "2018-01-01", "2018-09-01", "2019-04-01", "2020-01-15",
]

_EDUCATION_DEGREES = ["MD", "MS", "MBBS", "DNB", "DM", "MCh"]
_EDUCATION_GRADES = ["A", "A", "A", "B+", "A+"]
_LANGUAGES = [
    ("English", "PROFESSIONAL"),
    ("Hindi", "NATIVE_BILINGUAL"),
    ("Telugu", "NATIVE_BILINGUAL"),
    ("Tamil", "CONVERSATIONAL"),
    ("Kannada", "CONVERSATIONAL"),
]


def _fallback_profile_context(context_vars: dict[str, Any], rng: random.Random | None = None) -> dict[str, Any]:
    specialization_name = str(
        context_vars.get("specialization_name")
        or context_vars.get("specialization_id")
        or "General Medicine"
    ).strip()

    _rng = rng if rng is not None else random.Random()
    school = _rng.choice(_MEDICAL_COLLEGES)
    updated_school = _rng.choice([c for c in _MEDICAL_COLLEGES if c != school]) or school
    exp_start = _rng.choice(_EXPERIENCE_START_YEARS)
    degree = _rng.choice(_EDUCATION_DEGREES)
    grade = _rng.choice(_EDUCATION_GRADES)
    updated_grade = "A+" if grade in {"A", "B+"} else grade
    lang_name, lang_level = _rng.choice(_LANGUAGES)

    edu_year_start = 2005 + (hash(school) % 8)
    edu_year_end = edu_year_start + 3
    edu_start = f"{edu_year_start}-06-01"
    edu_end   = f"{edu_year_end}-05-31"

    return {
        "job_title_signup": f"Consultant {specialization_name}",
        "job_title_current": f"Senior {specialization_name} Specialist",
        "experience_start_date": exp_start,
        "education_degree_name": degree,
        "education_school_name": school,
        "education_field_name": specialization_name,
        "education_start_date": edu_start,
        "education_end_date": edu_end,
        "education_grade": grade,
        "updated_education_school_name": updated_school,
        "updated_education_grade": updated_grade,
        "language_name": lang_name,
        "language_proficiency_level": lang_level,
        "skill_name": f"{specialization_name} Care",
        "interest_2": f"{specialization_name} Research",
    }


def _fallback_behavior_context(context_vars: dict[str, Any]) -> dict[str, Any]:
    specialization_name = str(
        context_vars.get("specialization_name")
        or context_vars.get("specialization_id")
        or "General Medicine"
    ).strip()
    return {
        "consultation_modes": ["IN_PERSON", "TELEMEDICINE"],
        "doctor_search_term": specialization_name,
        "post_visibility": "ANYONE",
        "post_reaction_type": "LIKE",
        "network_action": "SEND",
        "post_mentions": [],
        "post_video_url": None,
        "profile_search_style": "broad",
        "engagement_preference": "educational",
    }


def _request_ollama_profile_context(
    rng: random.Random,
    context_vars: dict[str, Any],
    run_timestamp: int,
    user_index: int,
    iteration_index: int,
) -> dict[str, Any]:
    seed = agent_seed(run_timestamp, user_index, iteration_index, salt=101)

    prompt = (
        "Generate realistic profile-update details for a synthetic Indian doctor agent using valid JSON only. "
        "This doctor will perform signup, profile updates, education updates, language addition, and skill addition. "
        "Return these keys only: "
        "job_title_signup, job_title_current, experience_start_date, education_degree_name, education_school_name, "
        "education_field_name, education_start_date, education_end_date, education_grade, "
        "updated_education_school_name, updated_education_grade, language_name, language_proficiency_level, "
        "skill_name, interest_2. "
        f"Doctor name: {context_vars.get('doctor_fullname', 'Doctor')}. "
        f"Specialization: {context_vars.get('specialization_name', context_vars.get('specialization_id', 'General Medicine'))}. "
        f"Company: {context_vars.get('company_name', 'Hospital')}. "
        f"Years of experience: {context_vars.get('years_of_experience', 'N/A')}. "
        f"Short bio: {context_vars.get('short_bio', '')}. "
        "Constraints: dates must be YYYY-MM-DD, job titles must look like real doctor roles, "
        "language_proficiency_level must be one of BASIC, CONVERSATIONAL, PROFESSIONAL, NATIVE_BILINGUAL, "
        "skill_name must be a realistic doctor skill, interest_2 must be a realistic second professional interest. "
        f"Distinct seed: {seed}. Agent number: {user_index}. Iteration: {iteration_index}."
    )

    data = _ollama_generate_json(
        rng, prompt, seed,
        max_retries_env="OLLAMA_PROFILE_MAX_RETRIES",
        error_label="Ollama profile request",
    )
    return {
        "job_title_signup": str(data["job_title_signup"]).strip(),
        "job_title_current": str(data["job_title_current"]).strip(),
        "experience_start_date": str(data["experience_start_date"]).strip(),
        "education_degree_name": str(data["education_degree_name"]).strip(),
        "education_school_name": str(data["education_school_name"]).strip(),
        "education_field_name": str(data["education_field_name"]).strip(),
        "education_start_date": str(data["education_start_date"]).strip(),
        "education_end_date": str(data["education_end_date"]).strip(),
        "education_grade": str(data["education_grade"]).strip(),
        "updated_education_school_name": str(data["updated_education_school_name"]).strip(),
        "updated_education_grade": str(data["updated_education_grade"]).strip(),
        "language_name": str(data["language_name"]).strip(),
        "language_proficiency_level": str(data["language_proficiency_level"]).strip(),
        "skill_name": str(data["skill_name"]).strip(),
        "interest_2": str(data["interest_2"]).strip(),
    }


def _request_ollama_behavior_context(
    rng: random.Random,
    context_vars: dict[str, Any],
    run_timestamp: int,
    user_index: int,
    iteration_index: int,
) -> dict[str, Any]:
    seed = agent_seed(run_timestamp, user_index, iteration_index, salt=211)

    prompt = (
        "Generate behavior preferences for a synthetic doctor agent using valid JSON only. "
        "This doctor will use these preferences during signup, profile updates, searching, posting, and reactions. "
        "Return these keys only: consultation_modes, doctor_search_term, post_visibility, post_reaction_type, "
        "network_action, post_mentions, post_video_url, profile_search_style, engagement_preference. "
        f"Doctor name: {context_vars.get('doctor_fullname', 'Doctor')}. "
        f"Specialization: {context_vars.get('specialization_name', context_vars.get('specialization_id', 'General Medicine'))}. "
        f"Profile focus: {context_vars.get('profile_focus', '')}. "
        f"Doctor tone: {context_vars.get('doctor_tone', '')}. "
        "Constraints: consultation_modes must be an array containing one or more of IN_PERSON or TELEMEDICINE. "
        "doctor_search_term must be a short realistic search phrase. "
        "post_visibility must be ANYONE or CONNECTIONS. "
        "post_reaction_type must be LIKE. "
        "network_action must be SEND. "
        "post_mentions must be an array, usually empty. "
        "post_video_url must be null. "
        "profile_search_style and engagement_preference must be short natural descriptors. "
        f"Distinct seed: {seed}. Agent number: {user_index}. Iteration: {iteration_index}."
    )

    data = _ollama_generate_json(
        rng, prompt, seed,
        max_retries_env="OLLAMA_BEHAVIOR_MAX_RETRIES",
        error_label="Ollama behavior request",
    )
    consultation_modes = data.get("consultation_modes", [])
    if not isinstance(consultation_modes, list):
        consultation_modes = ["IN_PERSON", "TELEMEDICINE"]
    normalized_modes = [
        str(item).strip().upper()
        for item in consultation_modes
        if str(item).strip().upper() in {"IN_PERSON", "TELEMEDICINE"}
    ]
    if not normalized_modes:
        normalized_modes = ["IN_PERSON", "TELEMEDICINE"]

    post_mentions = data.get("post_mentions", [])
    if not isinstance(post_mentions, list):
        post_mentions = []

    raw_visibility = str(data.get("post_visibility", "ANYONE")).strip().upper()
    post_visibility = raw_visibility if raw_visibility in {"ANYONE", "CONNECTIONS"} else "ANYONE"
    raw_reaction = str(data.get("post_reaction_type", "LIKE")).strip().upper()
    post_reaction_type = raw_reaction if raw_reaction == "LIKE" else "LIKE"
    raw_network_action = str(data.get("network_action", "SEND")).strip().upper()
    network_action = raw_network_action if raw_network_action == "SEND" else "SEND"

    return {
        "consultation_modes": normalized_modes,
        "doctor_search_term": str(data.get("doctor_search_term", "")).strip(),
        "post_visibility": post_visibility,
        "post_reaction_type": post_reaction_type,
        "network_action": network_action,
        "post_mentions": [item for item in post_mentions],
        "post_video_url": data.get("post_video_url"),
        "profile_search_style": str(data.get("profile_search_style", "")).strip(),
        "engagement_preference": str(data.get("engagement_preference", "")).strip(),
    }


def build_doctor_profile_context(
    rng: random.Random,
    context_vars: dict[str, Any],
    run_timestamp: int,
    user_index: int,
    iteration_index: int,
) -> dict[str, Any]:
    mode = os.getenv("DOCTOR_IDENTITY_MODE", "ollama").strip().lower()
    if mode not in {"ollama", "llm"}:
        return _fallback_profile_context(context_vars, rng)
    try:
        profile = _request_ollama_profile_context(
            rng=rng,
            context_vars=context_vars,
            run_timestamp=run_timestamp,
            user_index=user_index,
            iteration_index=iteration_index,
        )
        profile["profile_generation_source"] = "ollama"
        return profile
    except Exception as err:
        fallback = _fallback_profile_context(context_vars, rng)
        fallback["profile_generation_source"] = "template_fallback"
        fallback["profile_generation_error"] = str(err)
        return fallback


def build_doctor_behavior_context(
    rng: random.Random,
    context_vars: dict[str, Any],
    run_timestamp: int,
    user_index: int,
    iteration_index: int,
) -> dict[str, Any]:
    mode = os.getenv("DOCTOR_IDENTITY_MODE", "ollama").strip().lower()
    if mode not in {"ollama", "llm"}:
        return _fallback_behavior_context(context_vars)
    try:
        behavior = _request_ollama_behavior_context(
            rng=rng,
            context_vars=context_vars,
            run_timestamp=run_timestamp,
            user_index=user_index,
            iteration_index=iteration_index,
        )
        behavior["behavior_generation_source"] = "ollama"
        return behavior
    except Exception as err:
        fallback = _fallback_behavior_context(context_vars)
        fallback["behavior_generation_source"] = "template_fallback"
        fallback["behavior_generation_error"] = str(err)
        return fallback


def build_doctor_identity(
    rng: random.Random,
    run_timestamp: int,
    user_index: int,
    iteration_index: int,
) -> dict[str, Any]:
    mode = os.getenv("DOCTOR_IDENTITY_MODE", "ollama").strip().lower()
    if mode == "pool":
        return build_pooled_identity(run_timestamp, user_index, iteration_index)
    if mode not in {"ollama", "llm"}:
        return build_template_identity(rng, run_timestamp, user_index, iteration_index)

    try:
        return _request_ollama_identity(rng, run_timestamp, user_index, iteration_index)
    except Exception as err:
        fallback = build_template_identity(rng, run_timestamp, user_index, iteration_index)
        fallback["identity_source"] = "template_fallback"
        fallback["identity_error"] = str(err)
        return fallback
