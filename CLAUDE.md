# Nebo — visor de cielo SPHEREx

Visor web del cielo infrarrojo con zoom de planetario: del cielo completo a un campo, y ahí
comparar épocas de SPHEREx (deslizador de tiempo + blink comparator). Proyecto para el reto
"Planet X and SPHEREx" de NASA Space Apps 2026. Plan completo: doc de Claude Docs
"Nebo — Visor de cielo SPHEREx: idea y stack frontend" (https://claude.ai/artifact/9AHiC9z8fX7MRQ5rxg1iDE).

## Estado

| Carpeta | Estado |
| --- | --- |
| `backend/` | Hecho: API FastAPI + PostgreSQL. Detalle y contrato en `backend/README.md` |
| `frontend/` | Vacío (solo README). Aquí va Next.js |
| `shared/`, `data/`, `docs/` | Solo README |

## Stack del frontend (decidido, no re-litigar)

Next.js + TypeScript · Aladin Lite v3 (cielo, HiPS, huellas, zoom) · react-three-fiber +
shader GLSL + postprocessing (túnel/warp) · GSAP (una timeline sincroniza cámara, shader e
interfaz) · Motion + Tailwind (HUD) · Rive/SVG (iconos animados) · Lenis opcional.
Un solo canvas WebGL persistente; no montar/desmontar escenas entre transiciones.

Prioridad: primero la parte científica (blink sobre datos reales), después la cinematografía.
El efecto acompaña al contenido, no lo tapa.

## Backend (resumen; el contrato manda `backend/README.md`)

Base `/api/v1`. `GET /targets` (marcadores, coordenadas ya a época 2026.2), `GET /patches`
(los que abren al instante), `GET /timeline?ra&dec|target&size&detector`, `GET /images/{id}.png`.
- `200` listo, `202` construyendo (repetir tras `Retry-After`, mostrar `progress`), `502` falló, `503` sin BD.
- Una imagen por época; todas las épocas de un tamaño comparten `display_min/max` → los cambios son reales.
- Orientación: norte arriba, este a la izquierda. Imágenes de 31/59/147 px: ampliar con
  `image-rendering: pixelated`. Un píxel = 6.15″; el centro del parche es el píxel central.
- Detector 1–6 = bandas distintas; WISE 0855 solo se ve en el 6. No mezclar detectores al comparar.

Nota: el plan original hablaba de JSON estáticos; el backend real sirve desde PostgreSQL.
Para la demo, precargar con `python -m app.preload` (~50 min) y tener video de respaldo.

## Aladin Lite v3 (verificado con context7, `/cds-astro/aladin-lite`)

```js
import A from "aladin-lite";           // verificar el nombre del paquete npm antes de instalar
A.init.then(() => {                    // WASM: esperar siempre A.init
  const aladin = A.aladin("#div", { target: "10.68 +41.14", fov: 8, projection: "AIT", survey: "P/DSS2/color" });
});
```
- Cámara: `aladin.gotoRaDec(ra, dec)`, `aladin.animateToRaDec(ra, dec, segundos, callback?)`,
  `aladin.zoomToFoV(fovDeg, segundos, callback?)`, `aladin.setFoV(deg)` (útil para zoom exponencial
  por frame: `fov = start / Math.pow(end/start, -t)`).
- Capas HiPS: `aladin.createImageSurvey(id, nombre, ...)` / `newImageSurvey(url)`,
  `setBaseImageLayer`, `setOverlayImageLayer(layer, nombre)`, `layer.setOpacity(0..1)`.
- Huellas: `A.graphicOverlay({color})` → `aladin.addOverlay(o)` → `o.addFootprints([A.polygon([[ra,dec],...])])`.
  Eventos: `footprintClicked`, `footprintHovered`, `objectClicked`. Cobertura: `A.MOCFromURL` + `aladin.addMOC`.
- Next.js: Aladin toca `window`/WASM → cargar solo en cliente (`dynamic(..., { ssr: false })`
  o `useEffect`), instancia única, limpiar al desmontar.
- La doc de context7 tiene solo ~305 fragmentos: si falta una API, leer el código en
  GitHub `cds-astro/aladin-lite` antes de asumir una firma.

## Ciencia: límites honestos (parte del producto)

- Etiquetas visibles: "cambio observado" / "señal candidata". Nunca "Planet X encontrado".
- Catalogados aparte de movimientos sin catálogo; mostrar fecha de observación y versión del dato (QR2).
- Estrellas de adorno del fondo, separadas visual y programáticamente de detecciones reales.

## Convenciones

- Accesibilidad: respetar `prefers-reduced-motion`; velocidad del blink ajustable.
- Móvil: limitar pixel ratio y apagar postprocesado en pantallas pequeñas.
- Antes de usar una API de librería, consultar context7 (Aladin, r3f, GSAP, Motion, Next.js).
- Skills útiles: `gsap-core`, `gsap-timeline`, `gsap-react`, `gsap-performance`,
  `threejs-fundamentals`, `threejs-shaders`, `threejs-postprocessing`, `astropy`,
  `frontend-design`, `motion-design`, `a11y-review`. Verificar UI real con `chrome-devtools`.
- Secretos: `backend/.env` está ignorado; solo `.env.example` se versiona. No commitear FITS ni `data/raw/`.

## Comandos del backend

```bash
cd backend && python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt && cp .env.example .env   # rellenar DATABASE_URL
python -m app.db init          # tablas + catálogo (idempotente)
uvicorn app.main:app --reload  # http://127.0.0.1:8000/docs
pytest                         # sin red ni BD
```
