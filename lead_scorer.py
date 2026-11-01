"""Scoring heurístico 1-100 de probabilidad de compra de automatizaciones.

Reglas explícitas y auditables (no una caja negra): cada señal suma o resta
puntos documentados. Pensado para priorizar a quién contactar primero, no
como una verdad absoluta.
"""

from __future__ import annotations

from typing import Any

MAX_SCORE = 100
MIN_SCORE = 1


def _score_reviews(cantidad_resenas: int) -> int:
    if cantidad_resenas >= 100:
        return 15
    if cantidad_resenas >= 30:
        return 10
    if cantidad_resenas >= 5:
        return 5
    return 0


def _score_rating(puntuacion: float) -> int:
    if puntuacion >= 4.5:
        return 5
    if puntuacion >= 4.0:
        return 3
    return 0


def _score_description_richness(descripcion: str) -> int:
    # Descripciones largas suelen indicar varios servicios / más complejidad operativa.
    length = len(descripcion or "")
    if length >= 400:
        return 5
    if length >= 150:
        return 3
    return 0


def score_lead(lead: dict[str, Any]) -> tuple[int, dict[str, int]]:
    """Devuelve (score_final, breakdown) para un lead ya enriquecido."""
    breakdown: dict[str, int] = {}

    breakdown["tiene_sitio_web"] = 15 if lead.get("sitio_web") else 0
    breakdown["sitio_alcanzable"] = 5 if lead.get("sitio_alcanzable") else 0
    breakdown["tiene_formulario_contacto"] = 10 if lead.get("tiene_formulario_contacto") else 0
    breakdown["responde_whatsapp"] = 10 if lead.get("responde_whatsapp") else 0
    breakdown["tiene_email_valido"] = 15 if lead.get("email_principal") else 0
    breakdown["varios_emails"] = 5 if len(lead.get("emails_secundarios", []) or []) >= 1 else 0
    breakdown["resenas"] = _score_reviews(int(lead.get("cantidad_resenas") or 0))
    breakdown["puntuacion"] = _score_rating(float(lead.get("puntuacion") or 0))
    breakdown["presencia_redes"] = min(10, 3 * len(lead.get("redes_sociales", {}) or {}))
    breakdown["descripcion_rica"] = _score_description_richness(lead.get("descripcion", ""))
    breakdown["negocio_activo"] = 5 if lead.get("business_status") == "OPERATIONAL" else 0

    total = sum(breakdown.values())
    total = max(MIN_SCORE, min(MAX_SCORE, total))
    return total, breakdown


def score_label(score: int) -> str:
    """Traduce el score numérico a una etiqueta de prioridad para ventas."""
    if score >= 70:
        return "alta"
    if score >= 40:
        return "media"
    return "baja"
