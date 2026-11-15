# Verificación de la interfaz de inicio de Nebo

Cambio: integración del logo original, paleta violeta/lavanda, superficies redondeadas, cabecera y navegación coordinadas, y temas claro/oscuro. Se conserva la estructura de navegación y la tipografía local del proyecto. El PNG se copió sin modificar; CSS encuadra sus márgenes transparentes.

## Verificado

- `npm run typecheck`: exit 0.
- `npm run build`: exit 0, página prerenderizada.
- `NEBO_TEST_URL=http://127.0.0.1:3002 node tests/browser.mjs`: exit 0, `Browser flows passed`. API simulada por la suite existente.
- `node ~/.codex/tools/ui-audit.mjs http://127.0.0.1:3002 --out /home/jasen/Documentos/Nebo-app/artifacts/logo-ui/final --viewports 320x568,375x812,568x320,768x1024,1280x800,1920x1080 --full`: exit 0. Los 12 casos devolvieron `sin hallazgos`; salida final `OK: sin bloqueantes.`
- Axe en claro y oscuro: cero violaciones. Detalle en interaction-results.json.
- Navegación solo con Tab y Enter a 375px: comenzar exploración (8 Tab), objetos destacados (5 Tab), tutorial (10 Tab); foco visible y destino comprobados.
- Texto 140 %, 200 % y 400 % en 320, 375, 568, 768 y 1280px: 15 casos sin overflow horizontal; RTL sin overflow. No se probó zoom nativo del navegador por separado.
- Contraste calculado con design-lint: texto/botón 8.99:1, secundario/panel oscuro 8.69:1, secundario/fondo claro 6.17:1 y acento/fondo claro 6.73:1.

## Dos pasadas de revisión visual

Primera: se abrieron pass-1/dark-1280x800.png y pass-1/light-375x812.png. Se corrigió el contraste del enlace de salto en claro (2.13:1), se amplió su objetivo a 44px y se redujo el peso de las órbitas y estrellas decorativas para proteger la lectura.

Segunda: se abrieron final/dark-375x812.png y final/light-1280x800.png. Sin hallazgos importantes de composición, identidad o legibilidad. El telescopio y la órbita del logo dan continuidad a los motivos de exploración del cielo.

## Límites y ejecución

El MCP chrome-devtools no pudo iniciar por falta de servidor X. Se usó Chrome headless con Playwright y el auditor CDP. No se obtuvo puntuación Lighthouse. La primera auditoría y el primer intento de la suite sobre desarrollo fallaron; la auditoría registró errores WebSocket de HMR y la suite agotó la espera tras pulsar Observar. Sobre la compilación de producción la suite y la auditoría completas pasaron.

Vista previa de producción: http://localhost:3002
