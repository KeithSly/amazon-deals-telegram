from __future__ import annotations

import html
import logging
from urllib.parse import urlencode

from .config import Config
from .http import HttpError, post_json
from .models import Deal

LOGGER = logging.getLogger(__name__)


class TelegramNotifier:
    def __init__(self, config: Config):
        self.config = config
        self.base_url = f"https://api.telegram.org/bot{config.telegram_bot_token}"

    def amazon_url(self, asin: str) -> str:
        base = f"https://www.amazon.es/dp/{asin}"
        if not self.config.amazon_associate_tag:
            return base
        return f"{base}?{urlencode({'tag': self.config.amazon_associate_tag})}"

    def render_message(self, deal: Deal) -> str:
        title = html.escape(deal.title[:500])
        current = _eur(deal.current_price_cents)
        lines = ["<b>OFERTA AMAZON</b>", "", f"<b>{title}</b>"]
        if deal.reference_price_cents and deal.reference_price_cents > deal.current_price_cents:
            lines.append(
                f"Precio medio: <s>{_eur(deal.reference_price_cents)}</s> -> <b>{current}</b>"
            )
        else:
            lines.append(f"Precio: <b>{current}</b>")
        lines.append(f"Bajada: <b>-{deal.discount_percent}%</b>")
        if deal.lightning_end:
            lines.append(f"Oferta flash hasta: {deal.lightning_end.astimezone().strftime('%d/%m %H:%M')}")
        if self.config.amazon_associate_tag and self.config.affiliate_disclosure:
            lines.extend(["", f"<i>{html.escape(self.config.affiliate_disclosure)}</i>"])
        return "\n".join(lines)

    def send(self, deal: Deal) -> None:
        url = self.amazon_url(deal.asin)
        reply_markup = {
            "inline_keyboard": [[{"text": "Ver oferta en Amazon", "url": url}]]
        }
        common = {
            "chat_id": self.config.telegram_chat_id,
            "parse_mode": "HTML",
            "disable_notification": self.config.telegram_disable_notification,
            "reply_markup": reply_markup,
        }
        message = self.render_message(deal)

        if self.config.telegram_send_image and deal.image_url:
            try:
                payload = {**common, "photo": deal.image_url, "caption": message[:1024]}
                response = post_json(
                    f"{self.base_url}/sendPhoto", payload, self.config.http_timeout_seconds
                )
                _ensure_telegram_ok(response)
                return
            except (HttpError, RuntimeError) as exc:
                LOGGER.warning("sendPhoto failed, falling back to sendMessage: %s", exc)

        payload = {
            **common,
            "text": f"{message}\n\n<a href=\"{html.escape(url, quote=True)}\">Abrir producto</a>",
            "disable_web_page_preview": False,
        }
        response = post_json(
            f"{self.base_url}/sendMessage", payload, self.config.http_timeout_seconds
        )
        _ensure_telegram_ok(response)


def _ensure_telegram_ok(response: dict) -> None:
    if not response.get("ok"):
        raise RuntimeError(f"Telegram error: {response.get('description', 'unknown error')}")


def _eur(cents: int) -> str:
    return f"{cents / 100:.2f} EUR".replace(".", ",")
