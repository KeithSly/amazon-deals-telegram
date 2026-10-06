from __future__ import annotations

import html
import logging
from urllib.parse import urlencode

from .config import Config
from .http import HttpError, post_json
from .models import Alert, AlertKind, Priority

LOGGER = logging.getLogger(__name__)


class TelegramNotifier:
    def __init__(self, config: Config):
        self.config = config
        self.base_url = f"https://api.telegram.org/bot{config.telegram_bot_token}"

    def amazon_url(self, asin: str, personal: bool = False) -> str:
        base = f"https://www.amazon.es/dp/{asin}"
        if personal or not self.config.amazon_associate_tag:
            return base
        return f"{base}?{urlencode({'tag': self.config.amazon_associate_tag})}"

    def render_message(self, alert: Alert) -> str:
        product = alert.product
        title = html.escape(product.title[:500])
        header = {
            AlertKind.DEAL: "🔥 <b>OFERTA AMAZON</b>",
            AlertKind.NEW_PRODUCT: "🆕 <b>NUEVO PRODUCTO EN AMAZON</b>",
            AlertKind.PREORDER: "🎮 <b>NUEVA RESERVA AMAZON</b>",
            AlertKind.RESTOCK: "⚡ <b>HA VUELTO EL STOCK</b>",
            AlertKind.OUT_OF_STOCK: "⛔ <b>PRODUCTO AGOTADO</b>",
        }[alert.kind]
        lines = [header, "", f"<b>{title}</b>"]

        if alert.deal is not None:
            deal = alert.deal
            if deal.reference_price_cents and deal.reference_price_cents > deal.current_price_cents:
                lines.append(f"Precio medio: <s>{_eur(deal.reference_price_cents)}</s> → <b>{_eur(deal.current_price_cents)}</b>")
            else:
                lines.append(f"Precio: <b>{_eur(deal.current_price_cents)}</b>")
            lines.append(f"Bajada: <b>-{deal.discount_percent}%</b>")
            if deal.lightning_end:
                lines.append(f"Oferta flash hasta: {deal.lightning_end.astimezone().strftime('%d/%m %H:%M')}")
        elif product.current_price_cents:
            lines.append(f"Precio: <b>{_eur(product.current_price_cents)}</b>")

        if alert.kind == AlertKind.PREORDER:
            lines.append("✅ Reserva detectada")
            if product.release_date:
                lines.append(f"Lanzamiento: <b>{product.release_date.astimezone().strftime('%d/%m/%Y')}</b>")
        elif alert.kind == AlertKind.NEW_PRODUCT:
            lines.append("🔎 Detectado por primera vez por nuestro monitor")
        elif alert.kind == AlertKind.RESTOCK:
            lines.append("⚠️ Puede volver a agotarse rápidamente")
        elif alert.kind == AlertKind.OUT_OF_STOCK:
            lines.append("Seguiremos vigilando su vuelta a stock")

        if alert.priority in {Priority.HOT, Priority.RESTOCK}:
            lines.extend(["", "🚨 <b>PRIORIDAD ALTA</b>"])
        if not alert.personal and self.config.amazon_associate_tag and self.config.affiliate_disclosure:
            lines.extend(["", f"<i>{html.escape(self.config.affiliate_disclosure)}</i>"])
        return "\n".join(lines)

    def send(self, alert: Alert) -> None:
        if alert.personal:
            chat_id = self.config.telegram_personal_chat_id
            if not chat_id:
                raise RuntimeError("TELEGRAM_PERSONAL_CHAT_ID is required for personal/HOT alerts")
        else:
            chat_id = self.config.telegram_public_chat_id
        url = self.amazon_url(alert.product.asin, personal=alert.personal)
        button_text = "Comprar / reservar ahora" if alert.kind in {AlertKind.PREORDER, AlertKind.RESTOCK} else "Ver en Amazon"
        reply_markup = {"inline_keyboard": [[{"text": button_text, "url": url}]]}
        disable_notification = self.config.telegram_disable_notification
        if alert.priority in {Priority.NEW_RELEASE, Priority.HOT, Priority.RESTOCK}:
            disable_notification = False
        common = {
            "chat_id": chat_id,
            "parse_mode": "HTML",
            "disable_notification": disable_notification,
            "reply_markup": reply_markup,
        }
        message = self.render_message(alert)

        if self.config.telegram_send_image and alert.product.image_url:
            try:
                response = post_json(
                    f"{self.base_url}/sendPhoto",
                    {**common, "photo": alert.product.image_url, "caption": message[:1024]},
                    self.config.http_timeout_seconds,
                )
                _ensure_telegram_ok(response)
                return
            except (HttpError, RuntimeError) as exc:
                LOGGER.warning("sendPhoto failed, falling back to sendMessage: %s", exc)

        response = post_json(
            f"{self.base_url}/sendMessage",
            {**common, "text": f'{message}\n\n<a href="{html.escape(url, quote=True)}">Abrir producto</a>', "disable_web_page_preview": False},
            self.config.http_timeout_seconds,
        )
        _ensure_telegram_ok(response)


def _ensure_telegram_ok(response: dict) -> None:
    if not response.get("ok"):
        raise RuntimeError(f"Telegram error: {response.get('description', 'unknown error')}")


def _eur(cents: int) -> str:
    return f"{cents / 100:.2f} EUR".replace(".", ",")
