# Nebo — Plan de frontend y UX/UI (reajustado al backend real)

## Contexto
La idea del doc de Claude Docs (viaje de zoom en 3 escalas + blink comparator, Next.js + Aladin Lite + r3f + GSAP) sigue en pie y el stack está decidido (`CLAUDE.md`, no re-litigar). Lo que cambió es el **backend**, que ya existe y condiciona el diseño:

| El doc decía | La realidad (`backend/README.md`) | Consecuencia de diseño |
| --- | --- | --- |
| JSON estáticos | API FastAPI + PostgreSQL con `200/202/502/503` | Hay estados de carga reales: la pantalla warp se ata a `progress.done/total` del `202` |
| Recortes grandes | PNG de **31 / 59 / 147 px** (3′/6′/15′), 6.15″/px | El "campo profundo" es un mosaico pixelado: se diseña como instrumento (retícula, escala, `image-rendering: pixelated`), no como foto |
| Cualquier campo | Solo **5 objetos del reto** precargados (`/targets`, `/patches`); otras posiciones tardan 1–2 min | La escala "Región" se centra en 5 marcadores; la búsqueda libre existe pero asume espera |
| Una banda | **6 detectores**, no mezclar; WISE 0855 solo en el 6 | El selector de detector es parte del núcleo, con recomendado por objeto |
| Huellas de observación | El backend no entrega huellas; entrega épocas (`start_utc`, `frames_used`) | Las "huellas" salen de HiPS/MOC de Aladin o se omiten en MVP; la línea de tiempo usa las épocas reales |

No pude leer la página oficial del reto (error TLS); me baso en el enunciado resumido en el doc y en `CLAUDE.md`. Conviene que alguien del equipo verifique criterios de jurado.

## Dirección de arte (a fijar con `frontend-design` + `theme-factory` antes de codificar)
- **Concepto: "instrumento de observatorio", no "dashboard sci-fi genérico".** Cielo oscuro neutro (no morado-azul), tipografía mono/técnica para datos (fechas, MJD, RA/Dec) y una sans humana para el copy. Un único color de acento cálido (ámbar) para lo que cambia; todo lo demás monocromo. Evitar glassmorphism, neón y tarjetas clónicas (`design-review` lo audita).
- **El cambio es el protagonista visual:** lo que se mueve entre épocas lleva el acento; lo fijo queda en gris. Esto hace que la comprensión no dependa de ser astrónomo.
- **Honestidad como UI:** insignias fijas "cambio observado" / "señal candidata", pie con fecha de observación + versión QR2, fondo de adorno marcado como decorativo (`aria-hidden`, distinto programáticamente).

## Flujo de pantallas (3 escalas, una sola superficie)
1. **Cielo completo** — Aladin con DSS/HiPS infrarrojo; 5 marcadores de `/targets` con nombre y una línea de gancho ("la estrella que más corre"). Buscador por nombre/coordenadas. HUD mínimo: coordenadas del cursor, FoV.
2. **Región** — `animateToRaDec` + `zoomToFoV` al marcar un objeto; panel lateral con ficha (tipo, nota, movimiento propio, detector recomendado) y botón "Ver cambios".
3. **Campo (núcleo científico)** — imagen de la época actual escalada pixelada, **deslizador de tiempo** con una marca por época real, **blink** con velocidad ajustable y pausa, selector de detector 1–6 (con rango µm y "bueno para"), selector de tamaño small/medium/large, retícula con escala en arcmin y marca del píxel central (donde se ubica el objeto). Lectura de fecha/época siempre visible.
- **Transiciones/túnel y warp de carga**: segunda prioridad (`CLAUDE.md`: ciencia primero, el efecto acompaña). Un solo canvas r3f persistente. Con `prefers-reduced-motion` o móvil: fundido simple.

## Estados que hay que diseñar (suelen olvidarse)
`202` construyendo (warp + etapa `queued→querying→downloading→rendering` en lenguaje llano), `502` sin cobertura ("SPHEREx aún no cubre esta posición con este detector", con reintento), `503` sin BD/modo demo, vacío, error de red → video de respaldo.

## Orden de trabajo (alineado al plan de 48 h)
1. Scaffold `frontend/` (Next.js + TS + Tailwind), cliente tipado de `/api/v1` en `frontend/lib/api.ts` (tipos desde el contrato del README; `shared/` queda para tipos si el equipo lo pide), tokens de diseño.
2. Escala 3 primero: timeline + blink + detector sobre un target real (Barnard's Star, d3). Aquí se gana o pierde el reto.
3. Escala 1 y 2 con Aladin (cargado con `dynamic(..., { ssr: false })`, instancia única) y vuelo entre ellas.
4. Túnel/warp + GSAP timeline única; carga ligada a `progress`.
5. Objetos conocidos / señales candidatas (extras), modo narrativo, pulido, `a11y-review`, `design-review`, video de demo.

## Archivos y piezas (a crear en `frontend/`)
- `app/` (layout, página única), `components/sky/AladinView.tsx`, `components/field/{BlinkViewer,TimeSlider,DetectorPicker}.tsx`, `components/hud/*`, `components/fx/Tunnel.tsx` (r3f), `lib/api.ts`, `lib/useTimeline.ts` (polling con `Retry-After`).
- Reusar: contrato de `backend/README.md`; recetas de Aladin ya verificadas en `CLAUDE.md`; skills `frontend-design`, `theme-factory`, `motion-design`, `gsap-*`, `a11y-review`.

## Verificación
- Backend local (`uvicorn`) + `pytest` del backend intacto; frontend contra la API real con un target precargado.
- `chrome-devtools`: flujo completo cielo→campo, blink a distintas velocidades, estados 202/502, móvil (emulate), `lighthouse_audit`, consola sin errores.
- `a11y-review` (contraste, teclado en el deslizador, `prefers-reduced-motion`) y `design-review` contra el "look de IA".

## Decisiones que quedan abiertas (recomendación entre paréntesis)
- Nombre final de producto (mantener "Nebo").
- ¿Huellas de SPHEREx en el MVP? (No: usar marcadores de targets; huellas solo si sobra tiempo).
- Idioma de la UI (español + inglés para el jurado internacional; ES por defecto).
