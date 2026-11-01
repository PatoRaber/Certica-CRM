"""Extracción y validación de emails públicos a partir de HTML.

Cubre tres fuentes: links mailto:, texto plano, y obfuscaciones comunes
(usuario [at] dominio [dot] com, etc.). Todo sobre HTML ya descargado de
páginas públicas — no se interactúa con formularios ni se autentica en
ningún lado.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from bs4 import BeautifulSoup

from config import Config

logger = logging.getLogger("lead_gen.email_extractor")

EMAIL_RE = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9._%+\-]*@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")

# user [at] domain [dot] tld [dot] tld2 ... (soporta TLDs de 2 partes como .com.ar)
OBFUSCATED_RE = re.compile(
    r"([a-zA-Z0-9._%+\-]+)\s*(?:\[at\]|\(at\)|\bat\b|arroba)\s*"
    r"([a-zA-Z0-9\-]+(?:\s*(?:\[dot\]|\(dot\)|\bdot\b|punto)\s*[a-zA-Z0-9\-]+)+)",
    re.IGNORECASE,
)
_DOT_TOKEN_RE = re.compile(r"\s*(?:\[dot\]|\(dot\)|\bdot\b|punto)\s*", re.IGNORECASE)

STATIC_IMAGE_EXT = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp")


def extract_from_mailto(html: str) -> set[str]:
    soup = BeautifulSoup(html, "lxml")
    found = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.lower().startswith("mailto:"):
            address = href[len("mailto:"):].split("?")[0].strip()
            if address:
                found.add(address)
    return found


def extract_from_text(html: str) -> set[str]:
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(" ")
    return set(EMAIL_RE.findall(text))


def extract_obfuscated(html: str) -> set[str]:
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(" ")
    found = set()
    for match in OBFUSCATED_RE.finditer(text):
        user, domain_raw = match.groups()
        domain = _DOT_TOKEN_RE.sub(".", domain_raw).strip(".")
        found.add(f"{user}@{domain}")
    return found


def extract_emails(html: str) -> set[str]:
    if not html:
        return set()
    return extract_from_mailto(html) | extract_from_text(html) | extract_obfuscated(html)


def _mx_record_exists(domain: str) -> bool:
    import dns.resolver

    try:
        answers = dns.resolver.resolve(domain, "MX", lifetime=5.0)
        return len(answers) > 0
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
        # El dominio no existe o no tiene MX declarado: email invalido de verdad.
        return False
    except Exception:  # noqa: BLE001 - timeouts, resolver caido, sin red, etc.
        # Fallo de infraestructura, no del dominio en si: no penalizamos al lead.
        return True


def validate_email(email: str, config: Config, verify_mx: Optional[bool] = None) -> bool:
    """Formato válido + no está en la blocklist + (opcional) el dominio tiene MX."""
    email = email.strip().lower()
    if not EMAIL_RE.fullmatch(email):
        return False
    if any(ext in email for ext in STATIC_IMAGE_EXT):
        return False
    if any(pattern in email for pattern in config.email_blocklist_patterns):
        return False

    domain = email.rsplit("@", 1)[-1]
    should_verify = config.verify_mx if verify_mx is None else verify_mx
    if should_verify and not _mx_record_exists(domain):
        logger.info("Email descartado por dominio sin MX: %s", email)
        return False

    return True


def clean_emails(raw_emails: set[str], config: Config) -> list[str]:
    """Normaliza, valida y deduplica una colección de emails candidatos."""
    normalized = {e.strip().lower() for e in raw_emails if e.strip()}
    valid = {e for e in normalized if validate_email(e, config)}
    return sorted(valid)
