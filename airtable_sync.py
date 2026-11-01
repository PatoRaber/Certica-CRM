"""Sincronización de leads a una tabla de Airtable (interfaz/CRM de Fase 1).

Airtable hace de "dashboard": vista grilla para filtrar/ordenar por score,
vista Kanban agrupada por "Estado CRM" para trackear a quién ya se contactó.
Este módulo crea la tabla sola la primera vez (si no existe) y después hace
upsert de cada lead usando "Place ID" como clave única — no duplica registros
en corridas sucesivas, y nunca pisa el "Estado CRM" que el usuario haya
cambiado a mano en Airtable.

Requiere AIRTABLE_API_KEY (Personal Access Token) y AIRTABLE_BASE_ID en el
.env. Si no están configurados, sync_leads() no hace nada (feature opcional).
"""

from __future__ import annotations

import logging
import time
from typing import Any

import requests

from config import Config

logger = logging.getLogger("lead_gen.airtable_sync")

API_BASE = "https://api.airtable.com/v0"
BATCH_SIZE = 10  # límite de la API de Airtable para create/update en batch
REQUEST_DELAY = 0.25  # margen bajo el límite de 5 req/seg por base

FIELD_SPECS: list[dict[str, Any]] = [
    {"name": "Place ID", "type": "singleLineText"},
    {"name": "Nombre", "type": "singleLineText"},
    {"name": "Rubro", "type": "singleLineText"},
    {"name": "Ciudad", "type": "singleLineText"},
    {"name": "Provincia", "type": "singleLineText"},
    {"name": "Pais", "type": "singleLineText"},
    {"name": "Direccion", "type": "singleLineText"},
    {"name": "Telefono", "type": "singleLineText"},
    {"name": "Sitio Web", "type": "url"},
    {"name": "Cantidad Resenas", "type": "number", "options": {"precision": 0}},
    {"name": "Puntuacion", "type": "number", "options": {"precision": 1}},
    {"name": "Horario", "type": "multilineText"},
    {"name": "Descripcion", "type": "multilineText"},
    {"name": "Maps URL", "type": "url"},
    {"name": "Business Status", "type": "singleLineText"},
    {"name": "Sitio Alcanzable", "type": "checkbox", "options": {"icon": "check", "color": "greenBright"}},
    {"name": "Tiene Formulario Contacto", "type": "checkbox", "options": {"icon": "check", "color": "greenBright"}},
    {"name": "Responde WhatsApp", "type": "checkbox", "options": {"icon": "check", "color": "greenBright"}},
    {"name": "Redes Sociales", "type": "multilineText"},
    {"name": "Email Principal", "type": "email"},
    {"name": "Emails Secundarios", "type": "multilineText"},
    {"name": "Score", "type": "number", "options": {"precision": 0}},
    {
        "name": "Score Label",
        "type": "singleSelect",
        "options": {"choices": [{"name": "alta"}, {"name": "media"}, {"name": "baja"}]},
    },
    {
        "name": "Estado CRM",
        "type": "singleSelect",
        "options": {
            "choices": [
                {"name": "Nuevo"},
                {"name": "Contactado"},
                {"name": "Respondio"},
                {"name": "Reunion agendada"},
                {"name": "Cliente"},
                {"name": "Descartado"},
            ]
        },
    },
    {
        "name": "Fuente",
        "type": "singleSelect",
        "options": {
            "choices": [
                {"name": "Google Places (pipeline automático)"},
                {"name": "Lista Parque Industrial Moreno"},
            ]
        },
    },
]

# Campos que se completan en cada sync. "Estado CRM" queda afuera a propósito:
# solo se manda al crear el registro, nunca al actualizarlo.
_SYNCED_FIELD_NAMES = [f["name"] for f in FIELD_SPECS if f["name"] not in ("Place ID", "Estado CRM")]


def _headers(config: Config) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {config.airtable_api_key}",
        "Content-Type": "application/json",
    }


def _find_table_id(config: Config) -> str | None:
    resp = requests.get(
        f"{API_BASE}/meta/bases/{config.airtable_base_id}/tables",
        headers=_headers(config),
        timeout=config.request_timeout,
    )
    resp.raise_for_status()
    for table in resp.json().get("tables", []):
        if table.get("name") == config.airtable_table_name:
            return table.get("id")
    return None


def ensure_table(config: Config) -> str:
    """Devuelve el ID de la tabla de leads, creándola (con sus campos) si no existe."""
    table_id = _find_table_id(config)
    if table_id:
        return table_id

    logger.info("Tabla '%s' no existe en la base — creándola", config.airtable_table_name)
    resp = requests.post(
        f"{API_BASE}/meta/bases/{config.airtable_base_id}/tables",
        headers=_headers(config),
        json={"name": config.airtable_table_name, "fields": FIELD_SPECS},
        timeout=config.request_timeout,
    )
    resp.raise_for_status()
    return resp.json()["id"]


def _lead_to_fields(lead: dict[str, Any]) -> dict[str, Any]:
    redes = "; ".join(f"{k}: {v}" for k, v in (lead.get("redes_sociales", {}) or {}).items())
    emails_secundarios = "; ".join(lead.get("emails_secundarios", []) or [])
    fields = {
        "Place ID": lead.get("place_id", ""),
        "Nombre": lead.get("nombre", ""),
        "Rubro": lead.get("rubro", ""),
        "Ciudad": lead.get("ciudad", ""),
        "Provincia": lead.get("provincia", ""),
        "Pais": lead.get("pais", ""),
        "Direccion": lead.get("direccion", ""),
        "Telefono": lead.get("telefono", ""),
        "Cantidad Resenas": lead.get("cantidad_resenas", 0),
        "Puntuacion": lead.get("puntuacion", 0.0),
        "Horario": lead.get("horario", ""),
        "Descripcion": lead.get("descripcion", ""),
        "Business Status": lead.get("business_status", ""),
        "Sitio Alcanzable": bool(lead.get("sitio_alcanzable", False)),
        "Tiene Formulario Contacto": bool(lead.get("tiene_formulario_contacto", False)),
        "Responde WhatsApp": bool(lead.get("responde_whatsapp", False)),
        "Redes Sociales": redes,
        "Emails Secundarios": emails_secundarios,
        "Score": lead.get("score", 0),
        "Score Label": lead.get("score_label", ""),
        "Fuente": "Google Places (pipeline automático)",
    }
    # Los campos URL/email de Airtable rechazan strings vacíos: solo se incluyen si hay valor.
    if lead.get("sitio_web"):
        fields["Sitio Web"] = lead["sitio_web"]
    if lead.get("maps_url"):
        fields["Maps URL"] = lead["maps_url"]
    if lead.get("email_principal"):
        fields["Email Principal"] = lead["email_principal"]
    return fields


def _existing_records_by_place_id(config: Config, table_id: str) -> dict[str, str]:
    """Pagina todos los registros existentes y devuelve {place_id: record_id}."""
    mapping: dict[str, str] = {}
    offset = None
    while True:
        params: dict[str, Any] = {"fields[]": "Place ID", "pageSize": 100}
        if offset:
            params["offset"] = offset
        resp = requests.get(
            f"{API_BASE}/{config.airtable_base_id}/{table_id}",
            headers=_headers(config),
            params=params,
            timeout=config.request_timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        for record in data.get("records", []):
            place_id = record.get("fields", {}).get("Place ID")
            if place_id:
                mapping[place_id] = record["id"]
        offset = data.get("offset")
        if not offset:
            return mapping


def _batched(items: list[Any], size: int) -> Any:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def sync_leads(leads: list[dict[str, Any]], config: Config) -> None:
    """Sincroniza la lista de leads a Airtable. No hace nada si falta config."""
    if not config.airtable_api_key or not config.airtable_base_id:
        return
    if not leads:
        return

    table_id = ensure_table(config)
    existing = _existing_records_by_place_id(config, table_id)

    to_create: list[dict[str, Any]] = []
    to_update: list[dict[str, Any]] = []
    for lead in leads:
        place_id = lead.get("place_id", "")
        fields = _lead_to_fields(lead)
        record_id = existing.get(place_id)
        if record_id:
            to_update.append({"id": record_id, "fields": fields})
        else:
            fields["Estado CRM"] = "Nuevo"
            to_create.append({"fields": fields})

    url = f"{API_BASE}/{config.airtable_base_id}/{table_id}"
    created = updated = 0

    for batch in _batched(to_create, BATCH_SIZE):
        try:
            resp = requests.post(url, headers=_headers(config), json={"records": batch}, timeout=config.request_timeout)
            resp.raise_for_status()
            created += len(batch)
        except requests.RequestException:
            logger.exception("Falló un batch de creación en Airtable (%d registros) — sigo con el resto", len(batch))
        time.sleep(REQUEST_DELAY)

    for batch in _batched(to_update, BATCH_SIZE):
        try:
            resp = requests.patch(url, headers=_headers(config), json={"records": batch}, timeout=config.request_timeout)
            resp.raise_for_status()
            updated += len(batch)
        except requests.RequestException:
            logger.exception("Falló un batch de actualización en Airtable (%d registros) — sigo con el resto", len(batch))
        time.sleep(REQUEST_DELAY)

    logger.info("Airtable sincronizado: %d creados, %d actualizados", created, updated)
