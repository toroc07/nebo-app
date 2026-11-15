# Panel de inicio: verificación

Cambios: eliminada la barra de pestañas; los cuatro accesos viven en el panel de inicio. Eliminados el hero y su texto introductorio, las etiquetas NEBO / sección, los lemas de cabecera y el texto decorativo del pie. Se mantiene el fondo y sistema tipográfico existente. Las tarjetas usan imágenes diferentes, desenfoque en reposo y una capa nítida que aparece por opacidad al pasar el cursor o recibir foco. La proximidad del cursor (64px) activa el brillo; el hover añade un aumento del 1.2 %. Las imágenes permanecen nítidas en táctil. Movimiento reducido desactiva escalado y transiciones.

## Pruebas ejecutadas

- npm run typecheck: exit 0.
- npm run build: exit 0 (compilación y TypeScript).
- NEBO_TEST_URL=http://localhost:3002 node tests/browser.mjs: Browser flows passed, exit 0. Suite adaptada para acceder por el panel y regresar por el logo; API simulada.
- NEBO_TEST_URL=http://localhost:3002 node tests/home-panel.mjs: Home panel interactions passed, exit 0. Proximidad, hover, retorno al desenfoque, escala, teclado, navegación de vuelta, primer toque, movimiento reducido y axe en claro/oscuro. Resultados detallados en interaction-results.json.
- Texto 140 %, 200 % y 400 % en 320, 375, 568 y 1280px: 12 casos sin desbordamiento de documento ni contenido de tarjetas; RTL comprobado. No se midió por separado el zoom nativo del navegador.
- node ~/.codex/tools/ui-audit.mjs http://localhost:3002 --out /home/jasen/Documentos/Nebo-app/artifacts/panel-home/final --viewports 320x568,375x812,568x320,768x1024,1280x800,1920x1080 --full: exit 0, OK: sin bloqueantes. Doce combinaciones de pantalla y tema. Advertencia menor conservada: radio uniforme de 3px, correspondiente al diseño anterior que se mantiene.
- design-lint: texto sobre superficie de respaldo 14.16:1; acento sobre superficie 7.38:1. Las fotografías llevan una capa oscura para proteger la legibilidad.

## Revisión visual

Primera pasada: pass-1/dark-1280x800.png y pass-1/dark-375x812.png. Se corrigieron el contraste medido del título accesible oculto en tema claro y el tamaño del enlace de salto; se reforzó el ajuste del contenido con texto grande.

Segunda pasada: final/dark-375x812.png, final/light-1280x800.png, rest-desktop.png y hover-desktop.png. Se verificaron la ausencia de la barra y del hero, los cuatro accesos, la diferencia de nitidez, el borde púrpura con resplandor y el aumento leve. Sin cambios de layout al activar el efecto. La prueba específica de teclado y hover usa un navegador con ratón; el auditor general sin dispositivo de entrada puede seleccionar la alternativa sin hover.

El navegador conectado chrome-devtools no estaba operativo por falta de servidor X en esta sesión; se usó Chrome headless con Playwright y CDP. No se obtuvo puntuación Lighthouse.

## Imágenes

Imágenes decorativas del panel; no se presentan como observaciones de SPHEREx.
- Nebulosa: [Pillars of Creation — NASA, ESA, CSA, STScI](https://science.nasa.gov/asset/webb/pillars-of-creation-nircam-image/).
- Telescopio: [NASA’s Hubble Space Telescope](https://science.nasa.gov/asset/hubble/nasas-hubble-space-telescope/).
- Cielo/observatorio: recurso horizon.webp ya presente en el proyecto.
- Ajustes: diagrama SVG de controles ópticos creado en código.

Vista previa: http://localhost:3002
