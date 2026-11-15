# Verificación de Nebo

Frontend implementado en `nebo-app/frontend`. Vista previa local de producción: http://localhost:3001.

## Verificado

- `npm run build`: compilación y comprobación TypeScript correctas; página estática y mapa cargado en cliente.
- `npm run typecheck`: exit 0.
- `npm test`: 5 pruebas, 5 aprobadas. Coordenadas límite, reproducción circular, polling 202, cancelación de solicitudes y mensaje 503.
- `node tests/browser.mjs`: recorridos aprobados con API interceptada: validación, 202 → 200, reproducción/pausa, una y cero épocas, error de base de datos, persistencia de preferencias, tutorial, activación con teclado y acceso al catálogo desde explorar. Sin excepciones JavaScript.
- Texto al 200 %, RTL y ausencia de desbordamiento de documento en 320×568, 375×812 y 568×320.
- axe-core 4.11.0: cero violaciones en Inicio. Resultado en `axe.json`.
- ui-audit final: **exit 0, sin bloqueantes**, 320×568, 375×812, 568×320, 768×1024, 1280×800 y 1920×1080, claro y oscuro. Reporte completo: `audit-final/report.json`.
- Contraste medido: texto sobre ámbar 9,48:1; secundario oscuro 9,33:1; secundario claro 6,94:1.

Se revisaron visualmente las capturas de inicio móvil oscuro, escritorio claro/oscuro y landscape claro, además de Observar y Campo en móvil. Campo usa un PNG sintético solo dentro de las pruebas, no en el producto.

## Dos pasadas de crítica

1. Se revisaron composición, jerarquía y adaptación. Se corrigieron favicon ausente, persistencia del mapa y captura del enlace de salto. La auditoría del servidor de desarrollo detectó errores de su WebSocket de recarga; la revisión posterior se hizo en producción.
2. Se revisó el render corregido en móvil, oscuro y landscape. La auditoría final no detectó bloqueantes. Aviso menor: el auditor mide el enlace de salto oculto como 24×24 px; cuando recibe foco se muestra con su tamaño natural. Los controles visibles móviles mantienen 44 px.

Anclaje propio del producto: paisaje de observatorio terrestre que cede el protagonismo al mapa, coordenadas celestes y comparación por fechas/detectores; el menú conserva la composición asimétrica de las referencias.

## Límites de la verificación

- El puerto 8000 no tiene backend activo; no fue posible verificar imágenes SPHEREx reales ni una base PostgreSQL. Las respuestas científicas de los recorridos se simularon exclusivamente en las pruebas. El producto conserva la conexión a la API real y muestra sus errores.
- El mapa DSS2 depende de recursos de CDS y WebGL; se comprobó el acceso a la lista y la selección alternativa, pero no la precisión visual de las teselas externas.
- No se ejecutó Lighthouse: Chrome DevTools MCP no arrancó por falta de servidor gráfico. Se usaron Chromium headless, ui-audit y axe.
- El zoom nativo del navegador al 400 % y la prueba completa de las tres tareas usando exclusivamente Tab no se verificaron. Se verificó reflow en 320 px, texto al 200 % y activación/foco por teclado.
- No se midieron FPS, LCP ni INP. Los efectos se limitan a transform/opacity, el canvas de transición se pausa tras 450 ms y se omite en pantallas pequeñas o con movimiento reducido.

No se modificaron el backend, `CLAUDE.md` ni el plan previo del usuario. No se publicó una versión remota; la API local requiere una configuración pública antes de desplegar.
