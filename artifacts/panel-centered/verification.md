# Panel centrado e imágenes con más separación del fondo

Cambio limitado a app/globals.css: centrado horizontal del panel, centrado vertical cuando hay espacio disponible y redistribución de la capa oscura sobre las imágenes. El paisaje del inicio se atenúa al 58 % de brillo para separar las tarjetas del fondo. Se conservan el desenfoque, la nitidez al hover/foco y el brillo púrpura.

Verificado:
- npm run build: exit 0.
- NEBO_TEST_URL=http://localhost:3002 node tests/home-panel.mjs: Home panel interactions passed, exit 0. Hover, proximidad, teclado, táctil, movimiento reducido, textos ampliados y axe claro/oscuro correctos.
- Centrado medido: márgenes 20/20px a 375px, 90/90px a 1280px y 320/320px a 1920px. Detalle en centering.json.
- node ~/.codex/tools/ui-audit.mjs http://localhost:3002 --out /home/jasen/Documentos/Nebo-app/artifacts/panel-centered/audit --viewports 320x568,375x812,568x320,768x1024,1280x800,1920x1080 --full: exit 0, OK: sin bloqueantes. Se mantiene únicamente la advertencia menor de radios uniformes del sistema existente.

Capturas abiertas y revisadas: artifacts/panel-home/rest-desktop.png, audit/dark-1920x1080.png y audit/light-375x812.png. Se comprobó la separación visual entre fotos y paisaje, la legibilidad de los textos y el panel centrado en escritorio. El contraste fotográfico se revisó visualmente además de axe; el auditor general omite el cálculo sobre imágenes.

Vista previa: http://localhost:3002
