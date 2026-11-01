# Lead Gen — Certica

Pipeline autónomo para armar una base de leads B2B: busca empresas de un rubro
en Google Places, entra a su sitio, saca emails públicos, arma redes sociales,
puntúa el lead y exporta todo a CSV/Excel/JSON.

## Setup

```bash
cd lead-gen
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Editá `.env` y pegá tu `GOOGLE_MAPS_API_KEY` (Google Cloud Console → habilitar
"Places API" → crear credencial). Es un servicio con costo por uso — revisá el
pricing vigente en la consola de Google antes de correr búsquedas grandes.

## Uso

Editando `config.py` (sección `DEFAULTS` de la clase `Config`):

```bash
python main.py
```

O por línea de comandos, sin tocar el código:

```bash
python main.py --rubro "estudios contables" --ciudad "Rosario" \
  --provincia "Santa Fe" --pais Argentina --cantidad 30 \
  --output leads_contadores_rosario
```

## Qué genera

- `output/<nombre>.csv`, `.xlsx`, `.json` — la base de leads lista para campañas.
- `data/<nombre>.jsonl` — log incremental de cada lead a medida que se procesa
  (si el proceso se corta a mitad de camino, no se pierde lo ya hecho).
- `data/processed_ids.json` — registro de `place_id` ya procesados, para no
  volver a analizar la misma empresa en corridas futuras.
- `logs/<nombre>.log` — log completo de la corrida (requests, reintentos,
  errores por empresa, etc.).

## Interfaz: Airtable (opcional)

Si completás `AIRTABLE_API_KEY` y `AIRTABLE_BASE_ID` en `.env`, cada corrida
sincroniza los leads a una tabla de Airtable (se crea sola la primera vez,
con todos los campos) además de generar CSV/Excel/JSON. Airtable hace de
interfaz/CRM sin código propio: vista grilla para filtrar/ordenar por score,
vista Kanban agrupada por "Estado CRM" para trackear a quién ya contactaste.

La sincronización es un upsert por `Place ID`: corridas sucesivas actualizan
los mismos registros en vez de duplicarlos, y nunca pisa el "Estado CRM" que
hayas cambiado a mano en Airtable.

**Setup (una sola vez):**
1. Cuenta gratis en [airtable.com](https://airtable.com) y una base vacía (cualquier nombre).
2. El Base ID está en la URL de la base o en `airtable.com/api/` (empieza con `app`).
3. Personal Access Token en `airtable.com/create/tokens`, con scopes
   `data.records:read`, `data.records:write`, `schema.bases:read`,
   `schema.bases:write`, con acceso solo a esa base.
4. Pegá ambos valores en `.env`.

Plan gratis de Airtable: 1.000 registros por base, API incluida — de sobra
para el volumen de este pipeline.

## Cómo se decide el score (1-100)

Ver `lead_scorer.py` — es una suma de señales explícitas (tiene sitio, tiene
formulario, responde WhatsApp, cantidad de reseñas, rating, redes sociales
activas, emails encontrados). No es una IA, es una heurística auditable
pensada para priorizar a quién escribirle primero.

## Límites éticos (a propósito, no son bugs)

- No se scrapea Google Maps directamente: se usa la API oficial de Google
  Places, respetando sus Términos de Servicio.
- Antes de leer cualquier página de un sitio se chequea su `robots.txt`; si
  no permite el acceso, se omite esa página sin insistir.
- Si un sitio devuelve 403/429 (bloqueo o rate-limit) se descarta esa fuente
  y se sigue con la siguiente empresa — nunca se intenta esquivar el bloqueo.
- Solo se leen páginas públicas (home, contacto, about, aviso legal, etc.).
  No se completan formularios, no se autentica en ningún lado, no se leen
  áreas privadas.

## Rubros y ubicaciones sugeridos

La lista completa de rubros de alto valor para Certica y el formato de
ubicación (ciudad / provincia / país configurables) están documentados en
`config.py`. Cambiar de rubro o ciudad es solo cambiar 3-4 valores ahí o
pasarlos por línea de comandos.
