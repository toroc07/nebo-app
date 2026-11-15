# Cabina de observación — PC

Resultado: el visor de Begin exploring se convirtió en una cabina con estructura metálica continua, ventana central, pantallas verdes e instrumentos físicos. Los controles de navegación, óptica, tiempo y sensores están en la consola, con lecturas derivadas del visor y sus datos. El alcance final es escritorio, según la indicación del usuario.

Dirección elegida: cabina Apollo/Alien con consola en U y tipografía Barlow/Plex/PlexMono del proyecto. Se descartaron un puente LCARS (más abstracto) y un HUD de combate (volvería a superponer controles sobre la imagen). El elemento firma es la consola que rodea la ventana. Riesgo visual 6/10; navegación, formularios y teclado convencionales.

## Funciones verificadas

Zoom, desplazamiento, centrado sin perder escala, ajuste y campo completo; pin central y coordenadas; retícula y posición esperada; ganancia de pantalla; iluminación de cabina; bandas y paletas conservando la posición; reproducción, intervalo y avance por épocas; ampliación de la ventana; selección y recorrido de objetos y detectores. Se verificó recuperación de señal y de imágenes fallidas. La demo se identifica expresamente como simulada y la fuente predeterminada sigue siendo la API real.

## Pruebas ejecutadas

- npm run build: exit 0; compilación y TypeScript correctos. Compilación aislada en /tmp/nebo-cockpit-preview/frontend, con fuentes coincidentes con el proyecto.
- npm run typecheck: exit 0.
- npm test: 45 pruebas, 45 aprobadas.
- NEBO_TEST_URL=http://localhost:3002 node tests/browser.mjs: Browser flows passed, exit 0. El recorrido completo fue adaptado a las dimensiones de la ventana de cabina y al grupo de coordenadas.
- NEBO_TEST_URL=http://localhost:3002 node tests/cockpit.mjs: Cockpit controls passed, exit 0. Detalles en cockpit-results.json. Axe: cero violaciones en claro y oscuro. Pruebas del visor, teclado y recuperación mediante datos de demostración y respuestas API simuladas.
- git diff --check: exit 0.
- Contraste calculado con design-lint: texto/casco 11.17:1; texto secundario/casco 7.58:1; monitor verde 13.97:1; botón violeta 8.30:1; aviso de simulación 9.66:1. Todos AAA.

## Revisión visual

Primera pasada: pass-1-desktop.png. Se reforzó la estructura continua de la cabina, se hicieron más físicas las teclas, se corrigieron nombres accesibles de selectores y la región de coordenadas y se añadió ajuste de ventana y centrado real desde el mando.

Revisión final: desktop-final.png y capturas del directorio desktop-audit. Se comprobaron jerarquía, lectura de instrumentos, ventana principal, controles visibles y estados activos. La advertencia de simulación permanece visible. El aspecto de nave se expresa en el marco y los instrumentos; la imagen científica no se sustituye por una ilustración.

El navegador conectado no pudo arrancar por falta de servidor X; se utilizó Chrome headless con Playwright y CDP. No se obtuvo puntuación Lighthouse. La conexión a una API astronómica externa no se validó; se verificaron la demo local y las respuestas de error/reintento.

Auditoría de escritorio: node ~/.codex/tools/ui-audit.mjs 'http://localhost:3002/lab/observation?source=demo' --out /home/jasen/Documentos/Nebo-app/artifacts/cockpit/desktop-audit --viewports 1280x800,1440x900,1920x1080 --full --wait 800

Vista previa: http://localhost:3002/lab/observation?source=demo

Resultado del barrido final: exit 0, OK: sin bloqueantes en las seis combinaciones. En 1920px aparece una advertencia heurística menor por varios botones activos: son los conmutadores e instrumentos de la cabina, no acciones de navegación en competencia. Se abrieron dark-1920x1080.png y light-1280x800.png para la revisión visual final.
