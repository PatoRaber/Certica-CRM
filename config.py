"""Configuración central del pipeline de lead generation.

Editá los valores por defecto de `DEFAULTS` para correr una búsqueda distinta,
o pasá overrides a `load_config(...)` desde main.py / línea de comandos.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"
LOG_DIR = BASE_DIR / "logs"
DATA_DIR = BASE_DIR / "data"

for d in (OUTPUT_DIR, LOG_DIR, DATA_DIR):
    d.mkdir(parents=True, exist_ok=True)

# Palabras clave para localizar páginas de contacto dentro de un sitio.
# Se buscan en el texto del link y en el href (minúsculas, sin acentos).
CONTACT_PAGE_KEYWORDS: tuple[str, ...] = (
    "contacto", "contact", "about", "nosotros", "quienes-somos",
    "aviso-legal", "aviso legal", "legal", "privacidad", "privacy",
    "terminos", "términos", "terms",
)

# Dominios/patrones de email que casi siempre son basura (placeholders,
# trackers, direcciones de plantillas de sitios web, etc.)
EMAIL_BLOCKLIST_PATTERNS: tuple[str, ...] = (
    "example.com", "example.org", "test.com", "yourdomain",
    "sentry.io", "wixpress.com", "godaddy.com", "domain.com",
    "email.com", "@2x.png", "@3x.png", "no-reply@", "noreply@",
    "placeholder", "youremail", "tuemail", "correo@", "nombre@",
)


@dataclass
class Config:
    # --- Búsqueda ---
    rubro: str = "odontólogos"
    ciudad: str = "Moreno"
    provincia: str = "Buenos Aires"
    pais: str = "Argentina"
    cantidad_empresas: int = 20

    # --- Salida ---
    output_filename: str = "leads_odontologos_moreno"
    output_dir: Path = OUTPUT_DIR
    log_dir: Path = LOG_DIR
    data_dir: Path = DATA_DIR

    # --- Red / robustez ---
    request_timeout: int = 10
    max_retries: int = 3
    retry_backoff_seconds: float = 1.5
    delay_between_requests: float = 1.0  # segundos, entre requests a sitios de terceros
    max_contact_pages_per_site: int = 5
    user_agent: str = (
        "CerticaLeadBot/1.0 (+https://certica-automatizaciones.vercel.app; "
        "contacto: certica.ia@gmail.com) - bot de investigacion de leads B2B, "
        "solo lee paginas publicas y respeta robots.txt"
    )

    # --- Validación de email ---
    verify_mx: bool = True

    # --- Google Places API ---
    google_api_key: str = field(default_factory=lambda: os.getenv("GOOGLE_MAPS_API_KEY", ""))

    # --- Airtable (interfaz/CRM opcional) ---
    airtable_api_key: str = field(default_factory=lambda: os.getenv("AIRTABLE_API_KEY", ""))
    airtable_base_id: str = field(default_factory=lambda: os.getenv("AIRTABLE_BASE_ID", ""))
    airtable_table_name: str = "Leads"

    contact_page_keywords: tuple[str, ...] = CONTACT_PAGE_KEYWORDS
    email_blocklist_patterns: tuple[str, ...] = EMAIL_BLOCKLIST_PATTERNS

    @property
    def search_query(self) -> str:
        return f"{self.rubro} en {self.ciudad}, {self.provincia}, {self.pais}"

    @property
    def processed_ids_path(self) -> Path:
        return self.data_dir / "processed_ids.json"

    @property
    def leads_jsonl_path(self) -> Path:
        return self.data_dir / f"{self.output_filename}.jsonl"


def load_config(**overrides) -> Config:
    """Crea una Config con los defaults, aplicando overrides puntuales."""
    cfg = Config()
    for key, value in overrides.items():
        if not hasattr(cfg, key):
            raise ValueError(f"Config no tiene el campo '{key}'")
        setattr(cfg, key, value)
    return cfg
