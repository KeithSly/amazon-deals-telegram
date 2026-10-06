# Amazon Deals Telegram

Monitor de **Amazon.es** orientado a ofertas, videojuegos y productos de stock limitado. Usa Keepa como fuente principal y Telegram como canal de aviso.

## Qué detecta

- 🔥 **Ofertas**: bajadas de precio filtradas por porcentaje, precio, rating y categorías.
- 🆕 **Productos nuevos**: ASIN que Keepa ha empezado a seguir recientemente.
- 🎮 **Reservas / preorders**: Buy Box marcada como preorder o disponibilidad futura de Amazon.
- ⚡ **Vuelta a stock**: productos que pasan de agotados a disponibles.
- 🚨 **Watchlist HOT**: ASIN concretos registrados en Keepa Tracking para eventos `OUT_OF_STOCK` / `BACK_IN_STOCK`.

El proyecto **no compra automáticamente**. No contiene checkout automatizado, almacenamiento de credenciales de Amazon ni bypass de CAPTCHA. Para productos limitados manda una alerta urgente con enlace directo a Amazon.

## Arquitectura

```text
Keepa
  ├─ /deal       -> ofertas + restocks recientes
  ├─ /query      -> nuevos productos + preorders
  ├─ /product    -> ficha/precio/fechas/estado
  └─ /tracking   -> ASIN HOT y notificaciones stock
        |
        v
Engines
  ├─ DealEngine
  ├─ DiscoveryEngine
  ├─ PreorderEngine
  └─ RestockEngine
        |
        v
SQLite
  ├─ products
  ├─ state_history
  ├─ sent_events
  ├─ sent_deals
  ├─ watchlist
  └─ processed_notifications
        |
        v
Telegram
  ├─ canal público -> puede usar Amazon Associates
  └─ chat personal -> siempre URL limpia, sin tag de afiliado
```

## Estados persistidos

`NEW`, `PREORDER`, `AVAILABLE`, `OUT_OF_STOCK`, `BACK_IN_STOCK`, `DEAL`, `EXPIRED`.

`products` guarda el último estado estable y `state_history` conserva las transiciones/eventos relevantes.

## Requisitos

- Python 3.11+
- API key de Keepa para funcionamiento real
- Bot de Telegram y chat/canal destino
- Opcional: tag de Amazon Afiliados

No hay dependencias Python de terceros en esta versión.

## Instalación

```bash
git clone https://github.com/KeithSly/amazon-deals-telegram.git
cd amazon-deals-telegram
python -m venv .venv
```

Windows:

```powershell
.venv\Scripts\activate
pip install -e .
copy .env.example .env
```

Linux/macOS:

```bash
source .venv/bin/activate
pip install -e .
cp .env.example .env
```

Edita `.env` y añade como mínimo:

```dotenv
KEEPA_API_KEY=...
TELEGRAM_BOT_TOKEN=...
TELEGRAM_PUBLIC_CHAT_ID=...
```

Para alertas personales HOT:

```dotenv
TELEGRAM_PERSONAL_CHAT_ID=...
```

## Prueba sin Keepa ni Telegram

```bash
amazon-deals-bot --source demo --dry-run --once
```

También puedes ejecutar solo un motor:

```bash
amazon-deals-bot --source demo --dry-run --once --mode preorders
amazon-deals-bot --source demo --dry-run --once --mode restock
```

## Añadir un producto HOT

```bash
amazon-deals-bot --watch-asin B0XXXXXXXX --watch-priority HOT
```

Por defecto es una alerta **personal**. El botón de Amazon no incluye el tag de afiliado.

Para vigilarlo y publicar los avisos en el canal público:

```bash
amazon-deals-bot --watch-asin B0XXXXXXXX --watch-priority HOT --public-watch
```

Ver watchlist:

```bash
amazon-deals-bot --list-watchlist
```

Eliminar:

```bash
amazon-deals-bot --unwatch-asin B0XXXXXXXX
```

Si `KEEPA_TRACKING_ENABLED=true`, al añadir un ASIN se crea también el tracking remoto de Keepa para avisos de salida/vuelta a stock.

## Gaming por defecto

La plantilla usa como categoría de descubrimiento:

```dotenv
DISCOVERY_ROOT_CATEGORIES=599383031
```

que corresponde a **Videojuegos** en Amazon.es. Puedes añadir más categorías separadas por coma.

El descubrimiento usa `trackingSince` de Keepa. Esto significa **"recién detectado por Keepa"**, no garantiza que el producto se detecte exactamente en el segundo en que Amazon crea la ficha.

## Frecuencia y tokens

La ejecución normal usa:

```dotenv
POLL_SECONDS=600
```

Es decir, un ciclo cada 10 minutos. Los motores se pueden ejecutar por separado si más adelante queremos dar a `restock`/`preorders` una cadencia más agresiva que a las ofertas.

Ten en cuenta que Product Finder (`/query`) y Product Request (`/product`) consumen más tokens que `/deal`. El log muestra `tokens_left`, `tokens_consumed` y `refill_rate` en cada llamada para poder ajustar el consumo con datos reales.

## Amazon Afiliados

Configura:

```dotenv
AMAZON_ASSOCIATE_TAG=mitag-21
AFFILIATE_DISCLOSURE=Enlace de afiliado
```

Las alertas públicas usarán:

```text
https://www.amazon.es/dp/ASIN?tag=mitag-21
```

Las alertas personales/HOT siempre usan:

```text
https://www.amazon.es/dp/ASIN
```

Esto evita usar tu propio tag cuando el aviso es para una compra personal.

## Docker

```bash
cp .env.example .env
# editar .env
docker compose up -d --build
```

La base de datos se conserva en `./data`.

## Tests

```bash
python -m unittest discover -s tests -v
```

## Siguiente evolución prevista

El código incluye una frontera `AmazonCreatorsProvider` para incorporar más adelante **Amazon Creators API** como fuente oficial de catálogo/enriquecimiento cuando la cuenta de Afiliados esté aprobada. Keepa seguiría siendo la fuente de histórico de precios, cambios y tracking.

También queda preparado el modelo público/personal para que una futura web pueda recibir las publicaciones públicas antes de redirigir a Amazon.
