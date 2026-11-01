"""Orquestador del pipeline de lead generation.

Uso:
    python main.py
    python main.py --rubro "estudios contables" --ciudad "Rosario" --provincia "Santa Fe" --pais Argentina --cantidad 30 --output leads_contadores_rosario

El flujo es 100% autónomo: por cada empresa encontrada en Google Places,
intenta traer su sitio, buscar emails públicos, puntuarla, y sigue con la
siguiente aunque alguna falle. Guarda incrementalmente en un .jsonl para
poder cortar y retomar sin perder trabajo, y al final exporta CSV/XLSX/JSON.
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path
from typing import Any

import airtable_sync
import email_extractor
import exporter
import lead_scorer
import maps_search
import website_parser
from config import Config, load_config

logger = logging.getLogger("lead_gen")


def setup_logging(config: Config) -> None:
    log_path = config.log_dir / f"{config.output_filename}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def load_processed_ids(config: Config) -> set[str]:
    if config.processed_ids_path.exists():
        with open(config.processed_ids_path, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_processed_ids(processed_ids: set[str], config: Config) -> None:
    with open(config.processed_ids_path, "w", encoding="utf-8") as f:
        json.dump(sorted(processed_ids), f, ensure_ascii=False, indent=2)


def append_lead_jsonl(lead: dict[str, Any], config: Config) -> None:
    with open(config.leads_jsonl_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(lead, ensure_ascii=False) + "\n")


def load_existing_leads(config: Config) -> list[dict[str, Any]]:
    if not config.leads_jsonl_path.exists():
        return []
    leads = []
    with open(config.leads_jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                leads.append(json.loads(line))
    return leads


def enrich_lead(base_lead: dict[str, Any], config: Config) -> dict[str, Any]:
    """Agrega análisis de sitio web + emails + score a un lead base de Maps."""
    lead = dict(base_lead)
    lead.update(
        sitio_alcanzable=False,
        tiene_formulario_contacto=False,
        responde_whatsapp=False,
        redes_sociales={},
        email_principal="",
        emails_secundarios=[],
    )

    sitio_web = lead.get("sitio_web")
    if sitio_web:
        try:
            analysis = website_parser.analyze_website(sitio_web, config)
            lead["sitio_alcanzable"] = analysis.reachable
            lead["tiene_formulario_contacto"] = analysis.has_contact_form
            lead["responde_whatsapp"] = analysis.has_whatsapp
            lead["redes_sociales"] = analysis.social_links
            if analysis.descripcion and not lead.get("descripcion"):
                lead["descripcion"] = analysis.descripcion

            raw_emails: set[str] = set()
            for html in analysis.all_html():
                raw_emails |= email_extractor.extract_emails(html)
            valid_emails = email_extractor.clean_emails(raw_emails, config)

            if valid_emails:
                lead["email_principal"] = valid_emails[0]
                lead["emails_secundarios"] = valid_emails[1:]
        except Exception:  # noqa: BLE001 - nunca frenar el pipeline por un sitio
            logger.exception("Falló el análisis de sitio para %s (%s)", lead.get("nombre"), sitio_web)

    score, breakdown = lead_scorer.score_lead(lead)
    lead["score"] = score
    lead["score_label"] = lead_scorer.score_label(score)
    lead["score_breakdown"] = breakdown
    return lead


def run(config: Config) -> list[dict[str, Any]]:
    setup_logging(config)
    logger.info("=== Iniciando pipeline: %s ===", config.search_query)
    logger.info("Objetivo: %d empresas nuevas", config.cantidad_empresas)

    processed_ids = load_processed_ids(config)
    leads = load_existing_leads(config)
    logger.info("%d IDs ya procesados previamente, %d leads ya guardados", len(processed_ids), len(leads))

    nuevos = 0
    try:
        for raw_place in maps_search.search_places(config):
            place_id = raw_place.get("place_id")
            if not place_id or place_id in processed_ids:
                continue

            try:
                details = maps_search.get_place_details(place_id, config)
                base_lead = maps_search.normalize_place(raw_place, details, config)
                lead = enrich_lead(base_lead, config)

                leads.append(lead)
                append_lead_jsonl(lead, config)
                processed_ids.add(place_id)
                save_processed_ids(processed_ids, config)
                nuevos += 1

                logger.info(
                    "[%d/%d] %s | email=%s | score=%d (%s)",
                    nuevos, config.cantidad_empresas, lead["nombre"],
                    lead["email_principal"] or "—", lead["score"], lead["score_label"],
                )
            except Exception:  # noqa: BLE001 - una empresa fallida no debe frenar el resto
                logger.exception("Falló el procesamiento de place_id=%s — continúo", place_id)
                processed_ids.add(place_id)  # evita reintentar indefinidamente el mismo fallo
                save_processed_ids(processed_ids, config)
                continue

            if nuevos >= config.cantidad_empresas:
                break

            time.sleep(config.delay_between_requests)

    except maps_search.MapsSearchError as exc:
        logger.error("Error irrecuperable de Places API: %s", exc)
    except KeyboardInterrupt:
        logger.warning("Interrumpido por el usuario — exportando lo acumulado hasta ahora.")

    paths = exporter.export_all(leads, config)
    logger.info("=== Fin. %d leads nuevos en esta corrida, %d leads totales ===", nuevos, len(leads))
    for fmt, path in paths.items():
        logger.info("  %s -> %s", fmt.upper(), path)

    if config.airtable_api_key and config.airtable_base_id:
        try:
            airtable_sync.sync_leads(leads, config)
        except Exception:  # noqa: BLE001 - Airtable es opcional, no debe tirar abajo la corrida
            logger.exception("Falló la sincronización con Airtable — los exports locales sí se guardaron.")

    return leads


def parse_args() -> dict[str, Any]:
    parser = argparse.ArgumentParser(description="Pipeline autónomo de lead generation B2B")
    parser.add_argument("--rubro", type=str)
    parser.add_argument("--ciudad", type=str)
    parser.add_argument("--provincia", type=str)
    parser.add_argument("--pais", type=str)
    parser.add_argument("--cantidad", type=int, dest="cantidad_empresas")
    parser.add_argument("--output", type=str, dest="output_filename")
    parser.add_argument("--no-verify-mx", action="store_false", dest="verify_mx")
    args = parser.parse_args()
    return {k: v for k, v in vars(args).items() if v is not None}


if __name__ == "__main__":
    overrides = parse_args()
    cfg = load_config(**overrides)
    run(cfg)
