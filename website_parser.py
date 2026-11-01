"""Descarga y análisis liviano del sitio web público de una empresa.

Solo lee páginas ya publicadas para el público (home, contacto, about,
aviso legal, etc.), respeta robots.txt y nunca intenta eludir bloqueos,
CAPTCHAs o restricciones de acceso: si un sitio no se puede leer, se
continúa sin ese dato.
"""

from __future__ import annotations

import logging
import time
import urllib.robotparser as robotparser
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from config import Config

logger = logging.getLogger("lead_gen.website_parser")

SOCIAL_DOMAINS = {
    "instagram.com": "instagram",
    "facebook.com": "facebook",
    "linkedin.com": "linkedin",
    "twitter.com": "twitter",
    "x.com": "twitter",
    "tiktok.com": "tiktok",
    "wa.me": "whatsapp",
    "api.whatsapp.com": "whatsapp",
}


@dataclass
class WebsiteAnalysis:
    homepage_html: str = ""
    contact_pages_html: dict[str, str] = field(default_factory=dict)
    social_links: dict[str, str] = field(default_factory=dict)
    has_contact_form: bool = False
    has_whatsapp: bool = False
    descripcion: str = ""
    reachable: bool = False

    def all_html(self) -> list[str]:
        return [self.homepage_html, *self.contact_pages_html.values()]


def _robots_allows(url: str, user_agent: str, timeout: int) -> bool:
    """Chequea robots.txt del dominio. Ante cualquier duda, permite (fail-open
    en la lectura del propio robots.txt, pero respeta un Disallow explícito)."""
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    rp = robotparser.RobotFileParser()
    try:
        resp = requests.get(robots_url, timeout=timeout, headers={"User-Agent": user_agent})
        if resp.status_code >= 400:
            return True  # no hay robots.txt publicado -> sin restricciones declaradas
        rp.parse(resp.text.splitlines())
        return rp.can_fetch(user_agent, url)
    except requests.RequestException:
        return True  # no se pudo leer robots.txt; no bloqueamos por eso


def fetch_page(url: str, config: Config) -> Optional[str]:
    """Descarga una página respetando robots.txt, timeouts y reintentos.
    Devuelve None si el sitio está caído, bloquea el acceso, o no autoriza
    el path según robots.txt — nunca intenta esquivar esas restricciones."""
    if not _robots_allows(url, config.user_agent, config.request_timeout):
        logger.info("robots.txt no permite leer %s — se omite", url)
        return None

    headers = {"User-Agent": config.user_agent}
    for attempt in range(1, config.max_retries + 1):
        try:
            resp = requests.get(url, timeout=config.request_timeout, headers=headers)
            if resp.status_code == 403 or resp.status_code == 429:
                logger.info("Acceso denegado/limitado (%s) en %s — se omite", resp.status_code, url)
                return None
            resp.raise_for_status()
            resp.encoding = resp.encoding or "utf-8"
            return resp.text
        except requests.RequestException as exc:
            logger.warning("Error descargando %s (intento %d/%d): %s", url, attempt, config.max_retries, exc)
            time.sleep(config.retry_backoff_seconds * attempt)
    return None


def _normalize_url(base_url: str, href: str) -> Optional[str]:
    if not href or href.startswith(("mailto:", "tel:", "javascript:", "#")):
        return None
    return urljoin(base_url, href)


def discover_contact_pages(base_url: str, html: str, config: Config) -> list[str]:
    """Busca links cuyo texto o href sugieran una página de contacto/legal."""
    soup = BeautifulSoup(html, "lxml")
    candidates: set[str] = set()
    base_domain = urlparse(base_url).netloc

    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = (a.get_text() or "").strip().lower()
        haystack = f"{href.lower()} {text}"
        if any(kw in haystack for kw in config.contact_page_keywords):
            resolved = _normalize_url(base_url, href)
            if resolved and urlparse(resolved).netloc == base_domain:
                candidates.add(resolved)

    return list(candidates)[: config.max_contact_pages_per_site]


def extract_social_links(html: str) -> dict[str, str]:
    soup = BeautifulSoup(html, "lxml")
    found: dict[str, str] = {}
    for a in soup.find_all("a", href=True):
        href = a["href"]
        netloc = urlparse(href).netloc.replace("www.", "")
        for domain, label in SOCIAL_DOMAINS.items():
            if domain in netloc and label not in found:
                found[label] = href
    return found


def extract_description(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    meta = soup.find("meta", attrs={"name": "description"}) or soup.find(
        "meta", attrs={"property": "og:description"}
    )
    if meta and meta.get("content"):
        return meta["content"].strip()
    first_p = soup.find("p")
    return first_p.get_text().strip() if first_p else ""


def _has_contact_form(html: str) -> bool:
    soup = BeautifulSoup(html, "lxml")
    return soup.find("form") is not None


def analyze_website(url: str, config: Config) -> WebsiteAnalysis:
    """Orquesta la descarga de home + páginas de contacto y arma el análisis."""
    analysis = WebsiteAnalysis()
    homepage_html = fetch_page(url, config)
    if not homepage_html:
        return analysis

    analysis.reachable = True
    analysis.homepage_html = homepage_html
    analysis.social_links = extract_social_links(homepage_html)
    analysis.has_whatsapp = "whatsapp" in analysis.social_links
    analysis.has_contact_form = _has_contact_form(homepage_html)
    analysis.descripcion = extract_description(homepage_html)

    contact_urls = discover_contact_pages(url, homepage_html, config)
    for contact_url in contact_urls:
        time.sleep(config.delay_between_requests)
        page_html = fetch_page(contact_url, config)
        if page_html:
            analysis.contact_pages_html[contact_url] = page_html
            if not analysis.has_whatsapp:
                social = extract_social_links(page_html)
                if "whatsapp" in social:
                    analysis.has_whatsapp = True
                    analysis.social_links.setdefault("whatsapp", social["whatsapp"])
            if not analysis.has_contact_form:
                analysis.has_contact_form = _has_contact_form(page_html)

    return analysis
