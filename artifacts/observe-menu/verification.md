# Observe: imágenes, navegación y movimiento

Se reemplazó la foto de la tarjeta Observe the sky por una imagen de campo profundo, distinta del paisaje general. El menú Observe usa el mismo sistema de tarjetas centradas que Home: desenfoque en reposo, nitidez al hover/foco, resplandor y borde púrpuras por proximidad, ampliación leve y respuesta al pulsar. Se eliminaron el título visual redundante, la numeración y las coordenadas decorativas. Back permanece visible y el h1 sigue disponible para lectores de pantalla.

Las entradas de menú usan una secuencia GSAP de opacidad de tarjetas y desplazamiento corto de su contenido, completada en menos de medio segundo. Los efectos de hover conservan el control de las transformaciones de cada tarjeta; la entrada actúa sobre otros objetivos para que no se interrumpan. La imagen nítida reduce suavemente su escala al aparecer y la flecha acompaña la acción. Movimiento reducido elimina entradas animadas, escala y desplazamiento de flechas. Táctil muestra imágenes nítidas y permite abrir al primer toque.

## Verificado

- npm run build: exit 0, compilación y TypeScript correctos.
- NEBO_TEST_URL=http://localhost:3002 node tests/browser.mjs: Browser flows passed, exit 0. Incluye coordenadas, datos simulados, tutorial, preferencias persistentes y acceso al visor real de la app.
- NEBO_TEST_URL=http://localhost:3002 node tests/home-panel.mjs: Home panel interactions passed, exit 0.
- NEBO_TEST_URL=http://localhost:3002 node tests/observe-panel.mjs: Observe menu interactions passed, exit 0. Observa la opacidad de entrada, espera la limpieza de estilos, prueba proximidad, nitidez, flechas, navegación rápida repetida, teclado a 375px, ambos destinos, retorno, primer toque y axe en claro/oscuro. Ver interaction-results.json.
- Texto 100 %, 200 % y 400 % en seis tamaños: sin overflow de documento ni contenido de tarjetas. RTL sin overflow. Márgenes simétricos medidos. No se midió zoom nativo por separado.
- git diff --check: exit 0.
- design-lint: texto sobre superficie de respaldo 14.16:1; acento sobre superficie de respaldo 7.38:1. Fotografías con capa oscura; axe sin violaciones en ambos temas.

## Auditoría medible

Home: node ~/.codex/tools/ui-audit.mjs http://localhost:3002 --out /home/jasen/Documentos/Nebo-app/artifacts/observe-menu/home-final --viewports 320x568,375x812,568x320,768x1024,1280x800,1920x1080 --full

Salida: exit 0, OK: sin bloqueantes. Advertencia menor conservada: radios uniformes de 3px del diseño existente.

Observe: node ~/.codex/tools/ui-audit.mjs http://127.0.0.1:3003/observe --out /home/jasen/Documentos/Nebo-app/artifacts/observe-menu/observe-final-audit --viewports 320x568,375x812,568x320,768x1024,1280x800,1920x1080 --full

Salida: exit 0, sin hallazgos en las doce combinaciones. Para esta segunda pantalla se auditó una instantánea del DOM ya renderizado, con scripts retirados, servida por audit-proxy.mjs junto con los recursos reales. La navegación y las animaciones se probaron por separado en la aplicación viva con Playwright. Un primer intento del barrido se interrumpió al detenerse el servidor auxiliar; se repitió completo manteniendo servidor y auditor en el mismo proceso supervisor.

## Revisión visual en dos pasadas

Primera pasada: observe-rest.png, start-tile-hover.png, coordinate-tile-hover.png y home-audit/dark-375x812.png. Se detectó que la carta de coordenadas desaparecía demasiado bajo el desenfoque; se reforzaron sus estrellas y cuadrícula y se redujo el desenfoque de esa tarjeta.

Segunda pasada: observe-rest.png actualizado, observe-final-audit/dark-375x812.png, observe-final-audit/light-1280x800.png y home-final/dark-375x812.png. Se comprobaron separación del fondo, lectura, centrado, imágenes distintas y motivos específicos para explorar imágenes o buscar posiciones celestes.

Se usó Chrome headless con Playwright y CDP. No se obtuvo puntuación Lighthouse.

## Recursos y alcance

El campo profundo es una fotografía decorativa de [Webb’s First Deep Field — NASA, ESA, CSA, STScI](https://science.nasa.gov/asset/webb/webbs-first-deep-field-nircam-image/), no una observación de SPHEREx. La carta de coordenadas es una ilustración SVG sin valores astronómicos medidos. Créditos en public/panels/credits.json.

Se conserva el idioma inglés ya establecido en el código y la ruta /lab/observation. El visor y su lógica no se modificaron.

Vista previa viva: http://localhost:3002 — abrir Observe the sky para ver el segundo menú.
