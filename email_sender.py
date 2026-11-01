"""Envío de campañas de mail vía Resend.

Reemplaza el flujo anterior de crear borradores en Gmail a mano. Lee una
lista de mensajes ya armados (mismo formato que `_drafts_ready.json` de las
tandas anteriores: to/subject/body/nombre/rubro/ciudad) y los manda por la
API de Resend, con:

- Link de baja agregado automáticamente al final de cada mail.
- Lista de supresión local para no mandarle dos veces a la misma dirección
  entre tandas distintas.
- Modo "dry run" por defecto: nunca envía nada real salvo que se lo pida
  explícitamente con --send. Esto es a propósito, no un detalle técnico:
  cada tanda se revisa y se dispara a mano, no en piloto automático.

Uso:
    python3 email_sender.py --campana output/_campana.json           # dry run, solo muestra qué mandaría
    python3 email_sender.py --campana output/_campana.json --send    # envío real
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

SUPPRESSION_PATH = DATA_DIR / "suppression_list.json"
SENT_LOG_PATH = DATA_DIR / "sent_log.jsonl"

RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
RESEND_FROM = os.getenv("RESEND_FROM", "Patricio de Certica <patricio@mail.certica.com.ar>")
RESEND_REPLY_TO = os.getenv("RESEND_REPLY_TO", "certica.ia@gmail.com")
UNSUBSCRIBE_MAILTO = os.getenv(
    "UNSUBSCRIBE_MAILTO",
    "mailto:certica.ia@gmail.com?subject=Baja",
)

RESEND_API_URL = "https://api.resend.com/emails"

SITE_URL = "https://certica.com.ar"
LOGO_ICON_WHITE = "https://www.certica.com.ar/img/certica-icon-white-email.png"
LOGO_WORDMARK_WHITE = "https://www.certica.com.ar/img/certica-wordmark-white-email.png"
LOGO_ICON_INDIGO = "https://www.certica.com.ar/img/certica-icon-indigo-email.png"


@dataclass
class SendResult:
    to: str
    status: str  # "sent" | "skipped_suppressed" | "skipped_duplicate" | "error" | "dry_run"
    detail: str = ""


def load_suppression_list() -> set[str]:
    if not SUPPRESSION_PATH.exists():
        return set()
    data = json.loads(SUPPRESSION_PATH.read_text())
    return {e.lower().strip() for e in data}


def load_previously_sent() -> set[str]:
    """Direcciones a las que ya se les mandó algo en tandas anteriores."""
    if not SENT_LOG_PATH.exists():
        return set()
    sent = set()
    for line in SENT_LOG_PATH.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("status") == "sent":
            sent.add(row["to"].lower().strip())
    return sent


def append_sent_log(result: SendResult, subject: str, rubro: str = "") -> None:
    with SENT_LOG_PATH.open("a") as f:
        f.write(
            json.dumps(
                {
                    "to": result.to,
                    "status": result.status,
                    "detail": result.detail,
                    "subject": subject,
                    "rubro": rubro,
                    "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                },
                ensure_ascii=False,
            )
            + "\n"
        )


def build_html_body(plain_body: str, cta_url: str = SITE_URL, cta_label: str = "Ver certica.com.ar",
                    cta2_url: str = "", cta2_label: str = "") -> str:
    """Convierte el body en texto plano (con \\n\\n entre párrafos) al template
    con marca (header con logo, botón, firma e ícono, footer de baja).

    Si el último párrafo es solo la firma ("Patricio"), se saca del cuerpo
    para no duplicarla: el template ya arma su propio bloque de firma.
    """
    paragraphs = [p.strip() for p in plain_body.split("\n\n") if p.strip()]
    if paragraphs and paragraphs[-1].strip().lower() == "patricio":
        paragraphs = paragraphs[:-1]

    html_paragraphs = "".join(
        f'<p style="margin:0 0 14px;color:#14161f;font-size:15px;line-height:1.6;'
        f'font-family:Arial,Helvetica,sans-serif;">{p}</p>'
        for p in paragraphs
    )

    cta2_html = ""
    if cta2_url and cta2_label:
        cta2_html = (
            f'<a href="{cta2_url}" style="display:inline-block;background:#ffffff;color:#4338ca;'
            f'text-decoration:none;font-weight:bold;font-size:14px;padding:9px 18px;'
            f'border:2px solid #4338ca;border-radius:8px;margin:8px 0 20px 8px;'
            f'font-family:Arial,Helvetica,sans-serif;">{cta2_label}</a>'
        )

    return f"""
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f2f3f8;padding:24px 0;">
  <tr>
    <td align="center">
      <table role="presentation" width="560" cellpadding="0" cellspacing="0"
             style="max-width:560px;width:100%;background:#ffffff;border-radius:12px;overflow:hidden;">
        <tr>
          <td style="background:#362d9e;padding:22px 28px;">
            <img src="{LOGO_ICON_WHITE}" width="26" height="26" alt=""
                 style="display:inline-block;vertical-align:middle;border:0;">
            <img src="{LOGO_WORDMARK_WHITE}" width="104" alt="Certica"
                 style="display:inline-block;vertical-align:middle;margin-left:8px;border:0;">
          </td>
        </tr>
        <tr>
          <td style="padding:28px 28px 4px;">
            {html_paragraphs}
            <a href="{cta_url}"
               style="display:inline-block;background:#4338ca;color:#ffffff;text-decoration:none;
                      font-weight:bold;font-size:14px;padding:11px 20px;border-radius:8px;
                      margin:8px 0 20px;font-family:Arial,Helvetica,sans-serif;">
              {cta_label}
            </a>{cta2_html}
          </td>
        </tr>
        <tr>
          <td style="padding:0 28px 26px;">
            <table role="presentation" cellpadding="0" cellspacing="0">
              <tr>
                <td style="padding-right:8px;">
                  <img src="{LOGO_ICON_INDIGO}" width="20" height="20" alt=""
                       style="display:block;border:0;">
                </td>
                <td style="font-family:Arial,Helvetica,sans-serif;font-size:14px;line-height:1.4;">
                  <span style="color:#4338ca;font-weight:bold;">Patricio · Certica</span><br>
                  <span style="color:#6b6e80;font-size:12.5px;">certica.com.ar</span>
                </td>
              </tr>
            </table>
          </td>
        </tr>
        <tr>
          <td style="background:#f2f3f8;padding:14px 28px;border-top:1px solid #ececf2;
                     font-family:Arial,Helvetica,sans-serif;font-size:11px;color:#8a8da0;">
            Si no querés recibir más mails de Certica,
            <a href="{UNSUBSCRIBE_MAILTO}" style="color:#8a8da0;">avisame acá</a> y te saco de la lista.
          </td>
        </tr>
      </table>
    </td>
  </tr>
</table>
""".strip()


def build_html_pilot(p: dict) -> str:
    """Formato de tres bloques para las rondas personalizadas con mockup.

    Claves de `p`: slogan, intro (bloque 1), invitacion (str o lista de
    párrafos), mockup_url, mockup_label (bloque 2), contacto (texto del
    bloque 3) y links (lista de pares [etiqueta, url] para los botones
    secundarios del bloque 3).
    """
    inv = p["invitacion"] if isinstance(p["invitacion"], list) else [p["invitacion"]]
    inv_html = "".join(
        f'<p style="margin:0 0 14px;color:#14161f;font-size:15px;line-height:1.6;'
        f'font-family:Arial,Helvetica,sans-serif;">{t}</p>'
        for t in inv
    )
    links_html = "".join(
        f'<a href="{url}" style="display:inline-block;background:#ffffff;color:#4338ca;'
        f'text-decoration:none;font-weight:bold;font-size:13px;padding:8px 16px;'
        f'border:2px solid #4338ca;border-radius:8px;margin:6px 8px 0 0;'
        f'font-family:Arial,Helvetica,sans-serif;">{label}</a>'
        for label, url in p.get("links", [])
    )
    return f"""
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f2f3f8;padding:24px 0;">
  <tr>
    <td align="center">
      <table role="presentation" width="560" cellpadding="0" cellspacing="0"
             style="max-width:560px;width:100%;background:#ffffff;border-radius:12px;overflow:hidden;">
        <tr>
          <td style="background:#362d9e;padding:22px 28px;">
            <img src="{LOGO_ICON_WHITE}" width="26" height="26" alt=""
                 style="display:inline-block;vertical-align:middle;border:0;">
            <img src="{LOGO_WORDMARK_WHITE}" width="104" alt="Certica"
                 style="display:inline-block;vertical-align:middle;margin-left:8px;border:0;">
          </td>
        </tr>
        <tr>
          <td style="background:#eeedfc;padding:26px 28px;">
            <div style="font-family:Arial,Helvetica,sans-serif;font-size:11px;letter-spacing:1.5px;
                        text-transform:uppercase;color:#4338ca;font-weight:bold;margin-bottom:8px;">
              Agencia de potenciación digital
            </div>
            <div style="font-family:Arial,Helvetica,sans-serif;font-size:22px;line-height:1.3;
                        color:#14161f;font-weight:bold;margin-bottom:10px;">{p["slogan"]}</div>
            <div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;line-height:1.55;
                        color:#5a5d70;">{p["intro"]}</div>
          </td>
        </tr>
        <tr>
          <td style="padding:28px 28px 8px;">
            {inv_html}
            <a href="{p["mockup_url"]}"
               style="display:inline-block;background:#4338ca;color:#ffffff;text-decoration:none;
                      font-weight:bold;font-size:15px;padding:13px 24px;border-radius:8px;
                      margin:6px 0 22px;font-family:Arial,Helvetica,sans-serif;">
              {p.get("mockup_label", "Ver el mockup")}
            </a>
          </td>
        </tr>
        <tr>
          <td style="padding:0 28px 8px;border-top:1px solid #ececf2;">
            <p style="margin:18px 0 6px;color:#14161f;font-size:14px;line-height:1.6;
                      font-family:Arial,Helvetica,sans-serif;">{p["contacto"]}</p>
            <div style="margin-bottom:14px;">{links_html}</div>
          </td>
        </tr>
        <tr>
          <td style="padding:6px 28px 26px;">
            <table role="presentation" cellpadding="0" cellspacing="0">
              <tr>
                <td style="padding-right:8px;">
                  <img src="{LOGO_ICON_INDIGO}" width="20" height="20" alt="" style="display:block;border:0;">
                </td>
                <td style="font-family:Arial,Helvetica,sans-serif;font-size:14px;line-height:1.4;">
                  <span style="color:#4338ca;font-weight:bold;">Patricio · Certica</span><br>
                  <span style="color:#6b6e80;font-size:12.5px;">certica.com.ar</span>
                </td>
              </tr>
            </table>
          </td>
        </tr>
        <tr>
          <td style="background:#f2f3f8;padding:14px 28px;border-top:1px solid #ececf2;
                     font-family:Arial,Helvetica,sans-serif;font-size:11px;color:#8a8da0;">
            Si no querés recibir más mails de Certica,
            <a href="{UNSUBSCRIBE_MAILTO}" style="color:#8a8da0;">avisame acá</a> y te saco de la lista.
          </td>
        </tr>
      </table>
    </td>
  </tr>
</table>
""".strip()


def build_plain_pilot(p: dict) -> str:
    inv = p["invitacion"] if isinstance(p["invitacion"], list) else [p["invitacion"]]
    lines = [
        "AGENCIA DE POTENCIACIÓN DIGITAL",
        p["slogan"],
        p["intro"],
        "",
        *[t + "\n" for t in inv],
        f'{p.get("mockup_label", "Ver el mockup")}: {p["mockup_url"]}',
        "",
        p["contacto"],
        *[f"{label}: {url}" for label, url in p.get("links", [])],
        "",
        "Patricio",
    ]
    return "\n".join(lines) + (
        "\n\n---\nSi no querés recibir más mails de Certica, respondé este correo "
        "pidiendo la baja y te saco de la lista."
    )



def build_plain_body(plain_body: str) -> str:
    footer = (
        "\n\n---\n"
        "Si no querés recibir más mails de Certica, respondé este correo "
        "pidiendo la baja y te saco de la lista."
    )
    return plain_body + footer


def send_one(to: str, subject: str, body: str, dry_run: bool,
             cta_url: str = SITE_URL, cta_label: str = "Ver certica.com.ar",
             cta2_url: str = "", cta2_label: str = "", pilot: dict | None = None) -> SendResult:
    if dry_run:
        return SendResult(to=to, status="dry_run", detail="no enviado (dry run)")

    if not RESEND_API_KEY:
        return SendResult(to=to, status="error", detail="falta RESEND_API_KEY en .env")

    import requests  # import local para no exigir la dependencia en dry run

    payload = {
        "from": RESEND_FROM,
        "to": [to],
        "reply_to": RESEND_REPLY_TO,
        "subject": subject,
        "html": build_html_pilot(pilot) if pilot else build_html_body(body, cta_url, cta_label, cta2_url, cta2_label),
        "text": build_plain_pilot(pilot) if pilot else build_plain_body(body),
        "headers": {
            "List-Unsubscribe": f"<{UNSUBSCRIBE_MAILTO}>",
        },
    }
    try:
        resp = requests.post(
            RESEND_API_URL,
            headers={
                "Authorization": f"Bearer {RESEND_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=15,
        )
    except requests.RequestException as e:
        return SendResult(to=to, status="error", detail=str(e))

    if resp.status_code in (200, 201):
        return SendResult(to=to, status="sent", detail=resp.json().get("id", ""))
    return SendResult(to=to, status="error", detail=f"{resp.status_code}: {resp.text[:200]}")


def run_campaign(campaign_path: Path, send: bool, delay_seconds: float = 0.6) -> None:
    messages = json.loads(campaign_path.read_text())
    suppressed = load_suppression_list()
    already_sent = load_previously_sent()

    print(f"Campaña: {len(messages)} mensajes | modo: {'ENVÍO REAL' if send else 'dry run'}")
    if suppressed:
        print(f"Lista de supresión: {len(suppressed)} direcciones")
    if already_sent:
        print(f"Ya contactados en tandas anteriores: {len(already_sent)} direcciones")
    print()

    counts = {"sent": 0, "skipped_suppressed": 0, "skipped_duplicate": 0, "error": 0, "dry_run": 0}

    for msg in messages:
        to = msg["to"].strip()
        subject = msg["subject"]
        body = msg["body"]
        rubro = msg.get("rubro", "")

        if to.lower() in suppressed:
            result = SendResult(to=to, status="skipped_suppressed")
        elif to.lower() in already_sent and not msg.get("seguimiento"):
            # "seguimiento": true solo para un seguimiento pedido explícitamente (las bajas igual se respetan)
            result = SendResult(to=to, status="skipped_duplicate")
        else:
            result = send_one(
                to, subject, body, dry_run=not send,
                cta_url=msg.get("cta_url", SITE_URL),
                cta_label=msg.get("cta_label", "Ver certica.com.ar"),
                cta2_url=msg.get("cta2_url", ""),
                cta2_label=msg.get("cta2_label", ""),
                pilot=msg.get("pilot"),
            )

        counts[result.status] = counts.get(result.status, 0) + 1
        print(f"[{result.status:18s}] {to:45s} {result.detail}")

        if result.status in ("sent",):
            append_sent_log(result, subject, rubro)
            time.sleep(delay_seconds)  # ritmo prudente para no pegarle todo junto a la API

    print("\n=== Resumen ===")
    for k, v in counts.items():
        if v:
            print(f"{k}: {v}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Envío de campañas de mail vía Resend")
    parser.add_argument("--campana", required=True, help="Path al JSON con los mensajes (to/subject/body)")
    parser.add_argument("--send", action="store_true", help="Envía de verdad. Sin este flag, es dry run.")
    args = parser.parse_args()

    campaign_path = Path(args.campana)
    if not campaign_path.exists():
        print(f"No existe el archivo: {campaign_path}", file=sys.stderr)
        sys.exit(1)

    if args.send:
        confirm = input(
            f"Vas a ENVIAR DE VERDAD la campaña '{campaign_path.name}'. Escribí 'enviar' para confirmar: "
        )
        if confirm.strip().lower() != "enviar":
            print("Cancelado.")
            sys.exit(0)

    run_campaign(campaign_path, send=args.send)


if __name__ == "__main__":
    main()
