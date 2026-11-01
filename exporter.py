"""Exportación de la base de leads a CSV, Excel y JSON."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pandas as pd

from config import Config

logger = logging.getLogger("lead_gen.exporter")


def _to_dataframe(leads: list[dict[str, Any]]) -> pd.DataFrame:
    flat = []
    for lead in leads:
        row = dict(lead)
        # Aplanar estructuras anidadas para que CSV/Excel queden legibles.
        row["emails_secundarios"] = "; ".join(lead.get("emails_secundarios", []) or [])
        row["redes_sociales"] = "; ".join(
            f"{k}: {v}" for k, v in (lead.get("redes_sociales", {}) or {}).items()
        )
        row.pop("score_breakdown", None)
        flat.append(row)
    return pd.DataFrame(flat)


def export_csv(leads: list[dict[str, Any]], path: Path) -> None:
    df = _to_dataframe(leads)
    df.to_csv(path, index=False, encoding="utf-8-sig")
    logger.info("CSV exportado: %s (%d filas)", path, len(df))


def export_excel(leads: list[dict[str, Any]], path: Path) -> None:
    df = _to_dataframe(leads)
    df.to_excel(path, index=False, engine="openpyxl")
    logger.info("Excel exportado: %s (%d filas)", path, len(df))


def export_json(leads: list[dict[str, Any]], path: Path) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(leads, f, ensure_ascii=False, indent=2)
    logger.info("JSON exportado: %s (%d leads)", path, len(leads))


def export_all(leads: list[dict[str, Any]], config: Config) -> dict[str, Path]:
    """Exporta la lista completa de leads en los 3 formatos. Devuelve las rutas."""
    base = config.output_dir / config.output_filename
    paths = {
        "csv": base.with_suffix(".csv"),
        "xlsx": base.with_suffix(".xlsx"),
        "json": base.with_suffix(".json"),
    }
    if not leads:
        logger.warning("No hay leads para exportar.")
        return paths

    export_csv(leads, paths["csv"])
    export_excel(leads, paths["xlsx"])
    export_json(leads, paths["json"])
    return paths
