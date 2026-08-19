# Telegram Market Risk Monitor

No usa OpenAI ni ChatGPT: **0 tokens de LLM**.

Vigila:
- HY OAS: FRED `BAMLH0A0HYM2`
- S&P 500 frente a SMA10 mensual: FRED `SP500`

La Action se ejecuta de martes a sábado a las 08:30, hora de Madrid, para leer la sesión estadounidense ya cerrada del día anterior. Solo manda Telegram si detecta un cruce relevante. Una ejecución manual manda siempre el informe.

## Configuración

1. En Telegram, habla con el bot oficial `@BotFather`, usa `/newbot` y guarda el token.
2. Abre tu bot nuevo y envíale `/start`.
3. Para obtener el chat ID, en tu ordenador:

```bash
export TELEGRAM_BOT_TOKEN='TU_TOKEN'
python market_watch.py --show-chat-ids
```

En PowerShell:

```powershell
$env:TELEGRAM_BOT_TOKEN='TU_TOKEN'
python market_watch.py --show-chat-ids
```

4. Crea un repositorio de GitHub con:
   - `market_watch.py`
   - `.github/workflows/market-watch.yml`
5. En `Settings -> Secrets and variables -> Actions`, crea:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
6. Ve a `Actions -> Market risk monitor -> Run workflow` para probarlo.

**No pongas el token dentro del código ni lo publiques.**

## Alertas

HY OAS:
- cruces de 4%, 5% y 6%
- activación/desactivación de estrés: OAS >=4% y >=1 punto porcentual sobre su mínimo aproximado de seis meses

S&P 500:
- cruce intramensual provisional de SMA10
- cruce formal de SMA10 al cierre mensual

Semáforo:
- VERDE: bolsa sobre SMA10 y sin estrés de crédito
- AMARILLO: una familia se deteriora
- NARANJA: bolsa bajo SMA10 + estrés de crédito
- ROJO: bolsa bajo SMA10 + HY OAS >=5%

## Si prefieres solo L-X-V

Para revisar aproximadamente los cierres de lunes, miércoles y viernes, cambia el cron a:

```yaml
- cron: '30 8 * * 2,4,6'
  timezone: "Europe/Madrid"
```

Esto ejecuta martes, jueves y sábado por la mañana.

## Siguiente mejora

Esta primera versión usa S&P 500 porque tanto el índice como HY OAS salen directamente de FRED y no requieren una API de mercado adicional. Para vigilar tus ETF exactos de Trade Republic hay que introducir sus tickers/ISINs exactos y elegir una fuente de precios; no conviene adivinarlos.
