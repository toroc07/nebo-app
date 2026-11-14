# Laboratorio de observación — hallazgos

Ruta de pruebas `/lab/observation` para ver cómo se consumen las imágenes de `shared/demo/`
(sintéticas) y, con el backend encendido, la API real. Se llega desde el menú:
**Inicio → Observar → "Laboratorio de imágenes (demo, sin backend)"**, y la página trae su
enlace "← Volver al menú".

**Único cambio en un archivo de Codex:** un bloque nuevo en `frontend/components/Nebo.tsx`,
justo antes de `{view === "Coordenadas" && (`: un `<p><a className="secondary" href="/lab/observation">`
visible solo en la vista "Observar". No toca la rejilla, el estado ni el CSS. Para quitar el
acceso basta borrar ese bloque. El backend no se ha tocado.

## Archivos del laboratorio (todos nuevos, borrables sin efecto en el menú)

| Archivo | Qué es |
| --- | --- |
| `frontend/app/lab/observation/page.tsx` | La página |
| `frontend/app/lab/demo/[...path]/route.ts` | Sirve `shared/demo/**` de solo lectura (404 fuera de esa carpeta y para tipos distintos de json/png) |
| `frontend/components/lab/ObservationLab.tsx`, `lab.module.css` | Visor básico, sin diseño |
| `frontend/lib/lab/contract.ts` | Contrato completo de `/timeline` + `loadTimeline(source, …)` común a demo y API |

Para verlo: `cd frontend && npm run dev` y abrir `/lab/observation`. Fuente "Demo" no necesita backend.

## Verificado (navegador real, servidor Next 16 en dev)
- Carga la imagen de cada época (31, 59 y 147 px) con `image-rendering: pixelated`; damero detrás para ver los píxeles transparentes.
- Precarga de las 3 épocas en ~40 ms en local; el blink recorre 1→2→3→1 sin carga intermedia.
- **`expected_position` verificado con los píxeles**: el píxel más brillante cae en (29,30), (29,29) y (29,28) para posiciones esperadas (28.92,30.04), (28.98,29.19), (29.05,28.35). Es decir, `x,y` son **centros de píxel con índice desde 0**. Para dibujar encima de la imagen: `left% = (x + 0.5) / width_px`, `top% = (y + 0.5) / height_px`.
- Cambio de objeto, detector (3/6) y tamaño; cada uno pide su timeline y reinicia la reproducción.
- Fuente "API real" con el backend apagado: mensaje de error legible, sin romper la página.

## Para Codex (no lo he tocado)
1. **`lib/api.ts` omite campos que el backend ya envía.** Snippet de tipos (ver `lib/lab/contract.ts` para el completo):
   ```ts
   export type Epoch = {
     // …campos actuales…
     mid_mjd: number; frames_available: number;
     display_min: number; display_max: number;
     releases: string[];
     expected_position?: { ra: number; dec: number; x: number; y: number; in_image: boolean };
   };
   export type Timeline = {
     // …campos actuales…
     sector?: { center: { ra: number; dec: number };
                corners: Record<"NW" | "NE" | "SE" | "SW", [number, number]> };
     data?: { source: string; processed_at: string };
     display: { stretch: string; unit: string; note: string };
   };
   ```
2. **`Field.tsx` escribe "SPHEREx QR2" a mano.** El dato trae `releases` (hoy `["qr2"]`); debería mostrarlo desde ahí y avisar si las épocas mezclan versiones.
3. **`Field.tsx` cambia `<img src>` sin precargar.** En local no se nota; con red real cada época puede parpadear al llegar. Recomendación: precargar todas las épocas (`new Image()`) y habilitar "Comparar épocas" solo cuando terminen (el laboratorio muestra el patrón).
4. `Field.tsx` aún no usa `expected_position` (marcador y estela del objeto) ni `sector.corners` (para colocar el recorte sobre Aladin).
5. Si quieren probar `Field` sin backend: `loadTimeline(source, …)` de `lib/lab/contract.ts` ya unifica demo y API; bastaría cambiar el origen.

## Trampa de Next 16 / Turbopack
Un route handler que lee archivos **fuera** del proyecto (`../shared/demo`) hacía que Turbopack rastreara todo el repo y cada lectura provocaba recompilar y recargar la página en bucle. Se arregla marcando `process.cwd()` con `/* turbopackIgnore: true */` (ya aplicado en el route handler del laboratorio). Hay que recordarlo si alguien más sirve archivos de `shared/`.

## Límites del demo
Sin imágenes `diff`, sin respuestas `202 building` (el estado de progreso del laboratorio solo se ejercita con la API real), solo 3 épocas y detectores 3 y 6; brillo y ruido inventados, no juzgar contraste.

## Pendiente de backend (nada bloqueante)
- Confirmar que `expected_position` también llega en la API real para posiciones que no son un target (aquí es opcional en el tipo).
- Con la API real encendida, repetir la prueba de precarga para medir el tiempo real de las imágenes.
