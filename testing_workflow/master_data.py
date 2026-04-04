from __future__ import annotations

import os
from typing import Any

import requests


def _post_json_with_status(
    url: str,
    api_key: str,
    body: dict[str, Any],
    timeout_seconds: float = 20.0,
) -> tuple[dict[str, Any], int]:
    response = requests.post(
        url,
        headers={
            "ACIN-API-KEY": api_key,
            "Content-Type": "application/json",
        },
        json=body,
        timeout=timeout_seconds,
    )
    try:
        payload = response.json()
    except ValueError as err:
        raise RuntimeError(f"Invalid JSON response from {url}: {err}") from err

    return payload, int(response.status_code)


def _post_json(url: str, api_key: str, body: dict[str, Any], timeout_seconds: float = 20.0) -> dict[str, Any]:
    payload, status_code = _post_json_with_status(url, api_key, body, timeout_seconds)

    if status_code >= 400:
        raise RuntimeError(f"{url} failed with status {status_code}: {payload}")
    if payload.get("success") is not True:
        raise RuntimeError(f"{url} returned unsuccessful payload: {payload}")
    return payload


def _pick_specialization_id(items: list[dict[str, Any]], preferred_id: str | None) -> str:
    if preferred_id:
        for item in items:
            if str(item.get("id")) == preferred_id:
                return preferred_id
    if not items:
        raise RuntimeError("No specialization data returned.")
    return str(items[0].get("id"))


def _lookup_specialization_name(items: list[dict[str, Any]], specialization_id: str) -> str:
    for item in items:
        if str(item.get("id")) == specialization_id:
            name = item.get("name") or item.get("specialization_name")
            if name is not None:
                return str(name)
    return specialization_id


def _pick_company_id(items: list[dict[str, Any]], preferred_company_id: str | None, preferred_company_name: str | None) -> str:
    if preferred_company_id:
        for item in items:
            if str(item.get("companyId")) == preferred_company_id:
                return preferred_company_id
    if preferred_company_name:
        normalized = preferred_company_name.strip().lower()
        for item in items:
            if str(item.get("companyName", "")).strip().lower() == normalized:
                return str(item.get("companyId"))
    if not items:
        raise RuntimeError("No company data returned.")
    return str(items[0].get("companyId"))


def _normalize_company_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in items:
        company_id = (
            item.get("companyId")
            or item.get("company_id")
            or item.get("companyid")
            or item.get("id")
        )
        company_name = (
            item.get("companyName")
            or item.get("company_name")
            or item.get("companyname")
            or item.get("name")
        )
        if company_id:
            normalized.append(
                {
                    "companyId": str(company_id),
                    "companyName": "" if company_name is None else str(company_name),
                }
            )
    return normalized


def _fetch_companies_from_postgres() -> list[dict[str, Any]]:
    host = os.getenv("PG_HOST", "").strip()
    port = int(os.getenv("PG_PORT", "5432"))
    dbname = os.getenv("PG_DATABASE", "").strip()
    user = os.getenv("PG_USER", "").strip()
    password = os.getenv("PG_PASSWORD", "").strip()
    schema = os.getenv("PG_SCHEMA", "doc_common").strip()
    table = os.getenv("PG_COMPANIES_TABLE", "companies").strip()

    if not all([host, dbname, user, password]):
        raise RuntimeError("PostgreSQL settings are incomplete. Set PG_HOST, PG_DATABASE, PG_USER, PG_PASSWORD.")

    try:
        import psycopg
        from psycopg.rows import dict_row
    except Exception as err:
        raise RuntimeError(
            "PostgreSQL driver not installed. Install 'psycopg[binary]' in requirements."
        ) from err

    query = f'SELECT * FROM "{schema}"."{table}"'
    with psycopg.connect(
        host=host,
        port=port,
        dbname=dbname,
        user=user,
        password=password,
        connect_timeout=10,
    ) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(query)
            rows = cur.fetchall()
    return _normalize_company_items(list(rows))


def _fetch_main_specializations_from_postgres() -> list[dict[str, Any]]:
    host = os.getenv("PG_HOST", "").strip()
    port = int(os.getenv("PG_PORT", "5432"))
    dbname = os.getenv("PG_DATABASE", "").strip()
    user = os.getenv("PG_USER", "").strip()
    password = os.getenv("PG_PASSWORD", "").strip()
    schema = os.getenv("PG_SCHEMA", "doc_common").strip()
    table = os.getenv("PG_MAIN_SPECIALIZATIONS_TABLE", "main_specializations").strip()

    if not all([host, dbname, user, password]):
        raise RuntimeError("PostgreSQL settings are incomplete. Set PG_HOST, PG_DATABASE, PG_USER, PG_PASSWORD.")

    try:
        import psycopg
        from psycopg.rows import dict_row
    except Exception as err:
        raise RuntimeError(
            "PostgreSQL driver not installed. Install 'psycopg[binary]' in requirements."
        ) from err

    query = f'SELECT id, name FROM "{schema}"."{table}"'
    with psycopg.connect(
        host=host,
        port=port,
        dbname=dbname,
        user=user,
        password=password,
        connect_timeout=10,
    ) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(query)
            rows = cur.fetchall()
    return [{"id": str(row.get("id")), "name": str(row.get("name", ""))} for row in rows if row.get("id")]


def fetch_master_data(context: dict[str, Any]) -> dict[str, Any]:
    base_url = str(context.get("base_url", "")).rstrip("/")
    api_key = str(context.get("api_key", "")).strip()

    if not base_url:
        raise RuntimeError("Missing required context key: base_url")
    if not api_key:
        raise RuntimeError("Missing required context key: api_key")

    specialization_url = f"{base_url}/dc/api-auth/v1/master/specializations/search"
    company_url = f"{base_url}/dc/api-auth/v1/master/company/search/companyName"

    preferred_main = context.get("specialization_id")
    preferred_sub = context.get("sub_specialization_id")
    preferred_additional = context.get("additional_specialization_id")
    preferred_company_id = context.get("company_id")
    preferred_company_name = context.get("company_name")
    master_checks: list[dict[str, Any]] = []

    def call_master_api(check_name: str, url: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            payload, status_code = _post_json_with_status(url, api_key, body)
        except Exception as err:
            master_checks.append(
                {
                    "name": check_name,
                    "url": url,
                    "passed": False,
                    "status_code": None,
                    "error": str(err),
                }
            )
            raise

        passed = status_code < 400 and payload.get("success") is True
        master_checks.append(
            {
                "name": check_name,
                "url": url,
                "passed": passed,
                "status_code": status_code,
                "message": payload.get("message"),
                "error_code": payload.get("error", {}).get("code") if isinstance(payload.get("error"), dict) else None,
            }
        )
        if not passed:
            raise RuntimeError(f"{check_name} failed with status {status_code}: {payload}")
        return payload

    # Explicitly test master APIs each run.
    main_api_payload = call_master_api(
        "specializations_main_search",
        specialization_url,
        {"specializationType": "MAIN", "search": ""},
    )

    specialization_source = os.getenv("MASTER_DATA_SPECIALIZATION_SOURCE", "auto").strip().lower()
    main_items: list[dict[str, Any]] = []
    main_db_error: str | None = None
    used_postgres_specializations = False

    if specialization_source in {"postgres", "auto"}:
        try:
            main_items = _fetch_main_specializations_from_postgres()
            if main_items:
                used_postgres_specializations = True
        except Exception as err:
            main_db_error = str(err)
            if specialization_source == "postgres":
                raise RuntimeError(f"PostgreSQL specialization lookup failed: {err}") from err

    if not main_items:
        main_items = list(main_api_payload.get("data", []))
        if not main_items and main_db_error:
            raise RuntimeError(
                f"No specialization data from API fallback. Prior PostgreSQL error: {main_db_error}"
            )

    main_id = _pick_specialization_id(main_items, str(preferred_main) if preferred_main else None)

    sub_payload = call_master_api(
        "specializations_sub_search",
        specialization_url,
        {"specializationType": "SUB", "mainSpecializationId": main_id, "search": ""},
    )
    sub_items = list(sub_payload.get("data", []))
    sub_id = _pick_specialization_id(sub_items, str(preferred_sub) if preferred_sub else None)

    additional_payload = call_master_api(
        "specializations_additional_sub_search",
        specialization_url,
        {"specializationType": "ADDITIONAL_SUB", "subSpecializationId": sub_id, "search": ""},
    )
    additional_items = list(additional_payload.get("data", []))
    additional_id = _pick_specialization_id(additional_items, str(preferred_additional) if preferred_additional else None)

    company_source = os.getenv("MASTER_DATA_COMPANY_SOURCE", "auto").strip().lower()
    company_items: list[dict[str, Any]] = []
    db_error: str | None = None
    used_postgres = False

    if company_source in {"postgres", "auto"}:
        try:
            company_items = _fetch_companies_from_postgres()
            if company_items:
                used_postgres = True
        except Exception as err:
            db_error = str(err)
            if company_source == "postgres":
                raise RuntimeError(f"PostgreSQL company lookup failed: {err}") from err

    if not company_items:
        company_payload = call_master_api(
            "companies_search_by_name",
            company_url,
            {"companyName": str(preferred_company_name or "")},
        )
        company_items = _normalize_company_items(list(company_payload.get("data", [])))
        if not company_items and db_error:
            raise RuntimeError(
                f"No company data from API fallback. Prior PostgreSQL error: {db_error}"
            )
    else:
        # Even when using postgres source, still test the API endpoint.
        call_master_api(
            "companies_search_by_name",
            company_url,
            {"companyName": str(preferred_company_name or "")},
        )

    company_id = _pick_company_id(
        company_items,
        str(preferred_company_id) if preferred_company_id else None,
        str(preferred_company_name) if preferred_company_name else None,
    )
    specialization_name = _lookup_specialization_name(main_items, main_id)

    return {
        "specialization_id": main_id,
        "specialization_name": specialization_name,
        "sub_specialization_id": sub_id,
        "additional_specialization_id": additional_id,
        "company_id": company_id,
        "specialization_source": "postgres" if used_postgres_specializations else "api",
        "company_source": "postgres" if used_postgres else "api",
        "master_api_checks": master_checks,
    }
