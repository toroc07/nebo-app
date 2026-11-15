# Imágenes distintas y transición de salida/entrada

Observe the sky conserva el campo profundo; Begin exploring usa una fotografía distinta de la galaxia Cartwheel. No se trata de otro recorte del mismo archivo.

Al elegir una opción, los otros cuadros se apartan, se reducen y se desvanecen. El elegido aumenta ligeramente antes de cambiar de pantalla; después se abren las tarjetas del menú nuevo. La transición también se aplica a Back y a la entrada al visor. La navegación se confirma al terminar la salida, no antes. Mientras dura la salida, el contenido se marca ocupado e inerte para impedir activaciones duplicadas. El foco pasa al título de destino. Con movimiento reducido el cambio es inmediato, incluso si la preferencia cambia durante una salida.

## Verificado

- npm run build: exit 0. Compilación de producción final aislada en /tmp/nebo-menu-transition-preview/frontend para evitar interferencias de otra compilación en el directorio .next compartido. Los SHA256 de components/Nebo.tsx y app/globals.css coinciden con los archivos del proyecto.
- NEBO_TEST_URL=http://localhost:3002 node tests/navigation-motion.mjs: Navigation motion passed, exit 0. Verifica que el menú anterior permanece durante la salida, que los nuevos cuadros no aparecen antes, la diferencia de opacidad/escala entre seleccionado y hermanos, limpieza del estado ocupado, clics repetidos y cambio de preferencia durante la salida. Detalle en navigation-results.json.
- NEBO_TEST_URL=http://localhost:3002 node tests/observe-panel.mjs: Observe menu interactions passed, exit 0. Incluye imágenes distintas entre niveles, hover, proximidad, teclado, primer toque, movimiento reducido, centrado, texto ampliado y axe claro/oscuro. La entrada se muestrea con MutationObserver para no depender de la velocidad de la captura.
- NEBO_TEST_URL=http://localhost:3002 node tests/home-panel.mjs: Home panel interactions passed, exit 0.
- NEBO_TEST_URL=http://localhost:3002 node tests/browser.mjs: Browser flows passed, exit 0. Incluye acceso al visor y las comprobaciones de navegación de regreso existentes.
- git diff --check: exit 0.

## Auditorías

node ~/.codex/tools/ui-audit.mjs http://localhost:3002 --out /home/jasen/Documentos/Nebo-app/artifacts/menu-transitions/home-audit --viewports 320x568,375x812,568x320,768x1024,1280x800,1920x1080 --full

Exit 0, OK: sin bloqueantes. Advertencia menor conservada: radio uniforme de 3px del diseño existente.

node ~/.codex/tools/ui-audit.mjs http://127.0.0.1:3003/observe --out /home/jasen/Documentos/Nebo-app/artifacts/menu-transitions/observe-audit --viewports 320x568,375x812,568x320,768x1024,1280x800,1920x1080 --full

Exit 0, sin hallazgos en las doce combinaciones. Observe se auditó como DOM renderizado sin scripts mediante el servidor auxiliar audit-proxy.mjs; la navegación y las animaciones se probaron en la aplicación viva con Playwright. Se revisó texto hasta 400 %; no se midió por separado zoom nativo del navegador.

## Capturas revisadas

Primera revisión: begin-hover.png, home-audit/dark-375x812.png y estados de salida. Una captura durante el movimiento podía avanzar al siguiente menú antes de terminar de guardarse; se corrigió la prueba congelando una copia del DOM del instante muestreado.

Revisión final: exit-desktop.png (DOM del fotograma real de salida), observe-audit/dark-375x812.png y observe-audit/light-1280x800.png. Se comprobaron salida de los hermanos, énfasis del seleccionado, Cartwheel distinta del campo profundo, centrado y legibilidad. La prueba de entrada confirma cuadros nuevos inicialmente transparentes y la limpieza de estilos al acabar.

Un intento de la suite amplia sobre el build compartido falló durante cambios concurrentes. La compilación aislada y las cuatro suites finales pasaron. Se usó Chrome headless con Playwright y CDP; no se obtuvo puntuación Lighthouse.

Imagen decorativa: [Cartwheel Galaxy — NASA, ESA, CSA, STScI, Webb ERO Production Team](https://science.nasa.gov/asset/webb/cartwheel-galaxy-nircam-and-miri-composite-image/). Créditos también en public/panels/credits.json. No se presenta como una observación de SPHEREx.

Vista previa actualizada: http://localhost:3002
