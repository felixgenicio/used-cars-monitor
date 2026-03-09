# Used Cars Monitor

Herramienta que rastrea anuncios de coches de segunda mano y genera una página web estática con el historial de precios y aparición/desaparición de anuncios.

## Características

- Scraping con Playwright (soporta páginas JavaScript/Next.js)
- Historial de precios por vehículo
- Registro de cuándo apareció y desapareció cada anuncio
- Valoración IA del precio (verde/amarillo/rojo) con justificación vía OpenAI (`gpt-4o-search-preview`, con búsqueda de precios reales actuales)
- Página HTML estática con filtros y ordenación
- Cron job (3 veces al día)

## Instalación

```bash
git clone <repo>
cd used-cars-monitor
bash setup.sh
```

El script:
1. Crea un entorno virtual Python
2. Instala dependencias y Playwright/Chromium
3. Crea `.env` desde la plantilla
4. Configura el cron job

## Configuración

Edita `.env`:

```
TARGET_URL=https://...   # URL de la página a monitorear
OPENAI_API_KEY=sk-...    # Opcional: para la valoración IA de precios
```

Si no se configura `OPENAI_API_KEY`, el scraper funciona con normalidad pero sin la columna de valoración.

## Uso

```bash
# Primera ejecución (modo debug para ver las llamadas API capturadas)
venv/bin/python run.py --debug

# Ejecución normal
venv/bin/python run.py

# Solo regenerar la página HTML sin hacer scraping
venv/bin/python run.py --generate

# Forzar re-valoración IA de todos los coches (ignora la caché)
venv/bin/python run.py --generate --rerate
```

La página generada se guarda en `output/index.html`.

## Estructura del proyecto

```
.
├── run.py          # Punto de entrada principal
├── scraper.py      # Scraper con Playwright
├── db.py           # Operaciones SQLite
├── generate.py     # Generador de página HTML
├── ai_rating.py    # Valoración IA de precios via OpenAI
├── templates/
│   └── index.html  # Plantilla Jinja2
├── setup.sh        # Script de instalación y configuración de cron
├── requirements.txt
├── .env.example    # Plantilla de configuración
└── .gitignore
```

## Primera ejecución con --debug

En la primera ejecución se recomienda usar `--debug`. Esto guarda todas las respuestas JSON capturadas en `logs/api_responses_*.json`. Si el scraper no detecta los vehículos automáticamente, puedes inspeccionar ese archivo para identificar el endpoint de la API y adaptar `scraper.py`.

## Cron

El cron se ejecuta a las 08:00, 14:00 y 20:00. Los logs se guardan en `logs/`.

### Configuración automática

`setup.sh` añade el cron automáticamente. Para comprobarlo:

```bash
crontab -l
```

Deberías ver una línea similar a:

```
0 8,14,20 * * * /ruta/al/proyecto/venv/bin/python /ruta/al/proyecto/run.py >> /ruta/al/proyecto/logs/cron.log 2>&1
```

### Configuración manual

Si prefieres configurarlo a mano, ejecuta `crontab -e` y añade:

```
# Monitor de coches — 3 veces al día (08:00, 14:00, 20:00)
0 8,14,20 * * * /ruta/al/proyecto/venv/bin/python /ruta/al/proyecto/run.py >> /ruta/al/proyecto/logs/cron.log 2>&1
```

Sustituye `/ruta/al/proyecto` por la ruta absoluta real, por ejemplo `/home/usuario/used-cars-monitor`.

Para obtenerla:

```bash
pwd  # ejecutar desde el directorio del proyecto
```

### Cambiar el horario

La sintaxis cron es `minuto hora día mes día_semana`. Algunos ejemplos:

```
# Cada 8 horas (00:00, 08:00, 16:00)
0 0,8,16 * * *

# Cada 6 horas
0 */6 * * *

# Solo en días laborables a las 9:00, 13:00 y 19:00
0 9,13,19 * * 1-5
```

### Verificar que el cron funciona

```bash
# Ver los últimos logs del cron
tail -f logs/cron.log

# Ver el log del día de hoy
tail -f logs/run_$(date +%Y%m%d).log
```

### Eliminar el cron

```bash
crontab -e  # borrar la línea correspondiente
```
