# Used Cars Monitor

Herramienta que rastrea anuncios de coches de segunda mano y genera una página web estática con el historial de precios y aparición/desaparición de anuncios.

## Características

- Scraping con Playwright (soporta páginas JavaScript/Next.js)
- Historial de precios por vehículo
- Registro de cuándo apareció y desapareció cada anuncio
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
TARGET_URL=https://...  # URL de la página a monitorear
```

## Uso

```bash
# Primera ejecución (modo debug para ver las llamadas API capturadas)
venv/bin/python run.py --debug

# Ejecución normal
venv/bin/python run.py

# Solo regenerar la página HTML sin hacer scraping
venv/bin/python run.py --generate
```

La página generada se guarda en `output/index.html`.

## Estructura del proyecto

```
.
├── run.py          # Punto de entrada principal
├── scraper.py      # Scraper con Playwright
├── db.py           # Operaciones SQLite
├── generate.py     # Generador de página HTML
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

Para ver el cron actual:
```bash
crontab -l
```
