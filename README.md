# Amazon Deals -> Telegram

Bot en Python para detectar ofertas recientes de Amazon.es mediante Keepa y publicarlas automaticamente en Telegram.

La version inicial esta pensada para ser simple de desplegar y mantener: solo usa la libreria estandar de Python, guarda el historico en SQLite y puede ejecutarse directamente, con Docker o Docker Compose.

## Funciones

- Consulta el endpoint `/deal` de Keepa.
- Restringido de forma intencionada a Amazon.es (`domainId=9`).
- Filtra por descuento minimo, rango de precio, rating minimo, categorias y palabras excluidas.
- Puede exigir que exista una oferta vendida por Amazon.
- Puede limitarse a precios en minimo de 90 dias.
- Ordena las ofertas por porcentaje de bajada.
- Guarda en SQLite los productos ya enviados.
- No repite un producto al mismo precio.
- Permite reenviar inmediatamente si el precio cae de nuevo un porcentaje configurable.
- Envia mensajes a chats, grupos o canales de Telegram.
- Incluye boton directo al producto de Amazon.
- Soporta opcionalmente un tag de Amazon Associates.
- Incluye modo `demo` y `dry-run` para probar sin Telegram ni Keepa.
- No requiere paquetes Python externos.

## Arquitectura

```text
Keepa /deal
     |
     v
KeepaProvider
     |
     v
DealService ----> filtros locales
     |
     +----> SQLite (deduplicacion)
     |
     v
TelegramNotifier ----> Telegram Bot API
```

## 1. Requisitos

- Python 3.11 o superior, o Docker.
- Una API key de Keepa para el modo real.
- Un bot de Telegram creado con `@BotFather`.
- El `chat_id` del chat, grupo o canal donde publicara el bot.

Keepa documenta que `/deal` cuesta 5 tokens por consulta y devuelve hasta 150 resultados por pagina. El bot usa una sola pagina por defecto para controlar el consumo.

## 2. Configuracion

Copia el fichero de ejemplo:

```bash
cp .env.example .env
```

Edita `.env`:

```dotenv
SOURCE=keepa
KEEPA_API_KEY=TU_API_KEY
TELEGRAM_BOT_TOKEN=TU_TOKEN
TELEGRAM_CHAT_ID=TU_CHAT_ID

MIN_DISCOUNT_PERCENT=25
MIN_PRICE_EUR=5
MAX_PRICE_EUR=1500
MIN_RATING=4.0
POLL_SECONDS=600
```

El fichero `.env` esta ignorado por Git y no debe subirse al repositorio.

### Keepa

Valores principales:

- `KEEPA_DOMAIN_ID=9`: Amazon.es.
- `KEEPA_PRICE_TYPE=0`: precio de Amazon.
- `KEEPA_DATE_RANGE=0`: cambio durante el ultimo dia.
- `KEEPA_MAX_PAGES=1`: maximo de paginas por ciclo.
- `MIN_DISCOUNT_PERCENT=25`: descuento minimo.
- `MIN_RATING=4.0`: rating minimo. Keepa lo recibe internamente en escala 0-50.
- `ONLY_LOWEST_90=true`: opcional, solo precios en minimo de 90 dias.
- `MUST_HAVE_AMAZON_OFFER=true`: exige una oferta actual de Amazon.

`KEEPA_DATE_RANGE` acepta:

```text
0 = dia
1 = semana
2 = mes
3 = 90 dias
```

### Categorias

Se pueden limitar o excluir categorias mediante IDs de Amazon separados por comas:

```dotenv
INCLUDE_CATEGORIES=123,456
EXCLUDE_CATEGORIES=789
```

Si se dejan vacios se aceptan todas las categorias.

### Telegram

Crea un bot con `@BotFather`, copia su token y anadelo a `.env`.

Para un canal, anade el bot como administrador con permiso para publicar y usa el identificador del canal o su `chat_id`.

El bot utiliza los metodos oficiales `sendMessage` y, opcionalmente, `sendPhoto` de Telegram Bot API.

Por defecto:

```dotenv
TELEGRAM_SEND_IMAGE=false
```

Keepa indica que el uso de la imagen del producto requiere disponer de los derechos correspondientes. Por esa razon el proyecto no publica imagenes de forma predeterminada.

## 3. Primera prueba sin credenciales

Puedes verificar toda la logica usando ofertas de demostracion:

```bash
PYTHONPATH=src python -m amazon_deals_bot --source demo --dry-run --once
```

Deberias ver en el log dos ofertas de prueba y ningun mensaje sera enviado.

## 4. Validar la configuracion

```bash
PYTHONPATH=src python -m amazon_deals_bot --check-config
```

## 5. Ejecutar una unica consulta real

```bash
PYTHONPATH=src python -m amazon_deals_bot --once
```

Esto consulta Keepa una vez, aplica los filtros y envia a Telegram las ofertas nuevas.

## 6. Ejecutar continuamente

```bash
PYTHONPATH=src python -m amazon_deals_bot
```

El intervalo se controla con:

```dotenv
POLL_SECONDS=600
```

El minimo permitido por esta aplicacion es 60 segundos. Un intervalo corto consume mas tokens de Keepa.

## 7. Docker

```bash
docker compose up -d --build
```

Ver logs:

```bash
docker compose logs -f
```

Parar:

```bash
docker compose down
```

La base de datos queda en `./data/deals.sqlite3`.

## 8. Evitar mensajes repetidos

La tabla SQLite conserva el ultimo precio enviado de cada ASIN y tipo de precio.

Politica predeterminada:

```dotenv
RESEND_COOLDOWN_HOURS=24
RESEND_MIN_EXTRA_DISCOUNT_PERCENT=5
```

- Mismo precio o precio superior: no se vuelve a enviar.
- Nueva bajada de al menos 5% respecto al ultimo precio enviado: se envia inmediatamente.
- Bajada menor: solo puede reenviarse despues del periodo de cooldown.

## 9. Amazon Associates

Si dispones de una cuenta valida de Amazon Associates puedes configurar tu tag:

```dotenv
AMAZON_ASSOCIATE_TAG=mitag-21
AFFILIATE_DISCLOSURE=Enlace de afiliado
```

El bot generara enlaces de la forma:

```text
https://www.amazon.es/dp/ASIN?tag=mitag-21
```

No actives esta opcion si no dispones de un identificador valido. Revisa siempre las condiciones vigentes del programa de afiliados y las obligaciones de identificacion de enlaces publicitarios que te correspondan.

## 10. Tests

No se necesitan dependencias de test adicionales:

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

## 11. Variables disponibles

Consulta `.env.example`. Las mas importantes son:

| Variable | Default | Uso |
| --- | ---: | --- |
| `SOURCE` | `keepa` | `keepa` o `demo` |
| `MIN_DISCOUNT_PERCENT` | `25` | Bajada minima |
| `MIN_PRICE_EUR` | `5` | Precio minimo |
| `MAX_PRICE_EUR` | `1500` | Precio maximo |
| `MIN_RATING` | `4.0` | Valoracion minima |
| `ONLY_LOWEST_90` | `false` | Exigir minimo de 90 dias |
| `MAX_DEALS_PER_CYCLE` | `20` | Limite de publicaciones por ciclo |
| `POLL_SECONDS` | `600` | Intervalo entre consultas |
| `TELEGRAM_SEND_IMAGE` | `false` | Intentar enviar imagen del producto |
| `DRY_RUN` | `false` | No enviar mensajes |

## Seguridad

- No subas `.env`.
- No escribas el token de Telegram ni la API key de Keepa en el codigo.
- Si una credencial aparece accidentalmente en Git, revocala y genera una nueva; borrarla en un commit posterior no la elimina del historial.

## Fuentes API

- Keepa API: https://keepa.com/api-docs/
- Keepa Deals: https://keepa.com/api-docs/deals.html
- Telegram Bot API: https://core.telegram.org/bots/api
