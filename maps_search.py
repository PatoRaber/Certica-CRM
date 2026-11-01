"""Búsqueda de empresas vía la API oficial de Google Places.

Usa Text Search para encontrar candidatos y Place Details para ampliar cada
uno. No se scrapea Google Maps directamente: eso violaría los términos de
servicio de Google y es exactamente lo que este proyecto busca evitar.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Iterator

import requests

from config import Config

logger = logging.getLogger("lead_gen.maps_search")

TEXT_SEARCH_URL = "https://maps.googleapis.com/maps/api/place/textsearch/json"
PLACE_DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json"

DETAILS_FIELDS = ",".join([
    "name", "formatted_address", "address_components", "formatted_phone_number",
    "international_phone_number", "website", "rating", "user_ratings_total",
    "opening_hours", "business_status", "url", "editorial_summary",
])


class MapsSearchError(RuntimeError):
    """Error irrecuperable al consultar la API de Places (p. ej. API key inválida)."""


def _request_with_retries(url: str, params: dict[str, Any], config: Config) -> dict[str, Any]:
    last_exc: Exception | None = None
    for attempt in range(1, config.max_retries + 1):
        try:
            resp = requests.get(url, params=params, timeout=config.request_timeout)
            resp.raise_for_status()
            data = resp.json()
            status = data.get("status")
            if status in ("OK", "ZERO_RESULTS"):
                return data
            if status in ("REQUEST_DENIED", "INVALID_REQUEST"):
                raise MapsSearchError(
                    f"Google Places devolvió {status}: {data.get('error_message', '')}"
                )
            # OVER_QUERY_LIMIT / UNKNOWN_ERROR -> reintentar
            logger.warning("Places API status=%s (intento %d/%d)", status, attempt, config.max_retries)
        except (requests.RequestException, ValueError) as exc:
            last_exc = exc
            logger.warning("Error de red en Places API (intento %d/%d): %s", attempt, config.max_retries, exc)
        time.sleep(config.retry_backoff_seconds * attempt)
    if last_exc:
        raise MapsSearchError(f"Fallaron todos los reintentos: {last_exc}")
    raise MapsSearchError("Fallaron todos los reintentos contra Places API")


def search_places(config: Config) -> Iterator[dict[str, Any]]:
    """Itera resultados de Text Search para config.search_query, paginando.

    Yields dicts crudos de Places (con al menos place_id y name) hasta
    agotar páginas o alcanzar config.cantidad_empresas resultados.
    """
    if not config.google_api_key:
        raise MapsSearchError(
            "Falta GOOGLE_MAPS_API_KEY. Definila en un archivo .env "
            "(ver .env.example) o como variable de entorno."
        )

    yielded = 0
    params: dict[str, Any] = {"query": config.search_query, "key": config.google_api_key}

    while True:
        data = _request_with_retries(TEXT_SEARCH_URL, params, config)
        for result in data.get("results", []):
            if yielded >= config.cantidad_empresas:
                return
            yield result
            yielded += 1

        next_page_token = data.get("next_page_token")
        if not next_page_token or yielded >= config.cantidad_empresas:
            return

        # Google exige una pequeña espera antes de que next_page_token sea válido.
        time.sleep(2.5)
        params = {"pagetoken": next_page_token, "key": config.google_api_key}


def get_place_details(place_id: str, config: Config) -> dict[str, Any]:
    """Trae el detalle ampliado de un place_id."""
    params = {"place_id": place_id, "fields": DETAILS_FIELDS, "key": config.google_api_key}
    data = _request_with_retries(PLACE_DETAILS_URL, params, config)
    return data.get("result", {})


def _component(components: list[dict[str, Any]], type_name: str) -> str:
    for comp in components or []:
        if type_name in comp.get("types", []):
            return comp.get("long_name", "")
    return ""


def normalize_place(raw: dict[str, Any], details: dict[str, Any], config: Config) -> dict[str, Any]:
    """Combina el resultado de búsqueda + detalles en un dict de lead base."""
    components = details.get("address_components", [])
    opening_hours = details.get("opening_hours", {}).get("weekday_text", [])
    return {
        "place_id": raw.get("place_id"),
        "nombre": details.get("name") or raw.get("name", ""),
        "rubro": config.rubro,
        "ciudad": _component(components, "locality") or config.ciudad,
        "provincia": _component(components, "administrative_area_level_1") or config.provincia,
        "pais": _component(components, "country") or config.pais,
        "direccion": details.get("formatted_address", raw.get("formatted_address", "")),
        "telefono": details.get("international_phone_number")
        or details.get("formatted_phone_number", ""),
        "sitio_web": details.get("website", ""),
        "cantidad_resenas": details.get("user_ratings_total", 0),
        "puntuacion": details.get("rating", 0.0),
        "horario": " | ".join(opening_hours),
        "descripcion": details.get("editorial_summary", {}).get("overview", ""),
        "maps_url": details.get("url", ""),
        "business_status": details.get("business_status", ""),
    }
