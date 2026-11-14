# Nebo frontend

Menú de observación con paisaje terrestre, mapa Aladin y comparación temporal de imágenes SPHEREx.

Requiere Node.js 20.9+.

```bash
npm ci
npm run dev
```

Abre http://localhost:3000. El backend se espera en http://127.0.0.1:8000. Para cambiarlo, crea `.env.local` con `NEXT_PUBLIC_API_ORIGIN=https://tu-api.example` y reinicia Next.js. En un despliegue, usa una URL pública HTTPS alcanzable desde el navegador; configura también el origen permitido en el backend.

El catálogo y las imágenes requieren el backend con PostgreSQL configurado y datos disponibles. El menú, tutorial y ajustes funcionan sin API; los errores del servicio se muestran en el lugar de los datos. No se incluyen imágenes científicas ficticias. DSS2 es un mapa de referencia visible; los recortes de comparación proceden de SPHEREx.

```bash
npm test
npm run typecheck
npm run build
```

La configuración visual se guarda solo en localStorage. La reproducción comienza en pausa y se detiene al ocultar la pestaña. El movimiento reducido del sistema tiene prioridad. Las búsquedas usan grados ICRS y el visor conserva el detector entre épocas.

El paisaje es una imagen decorativa generada para Nebo. Las fuentes Barlow Condensed e IBM Plex se sirven localmente; sus licencias OFL se incluyen en `public/fonts`.

Para repetir los recorridos de navegador en Linux con Chrome instalado:

```bash
npm run build
npm run start -- --port 3001
# En otra terminal:
node tests/browser.mjs
```

Las pruebas interceptan la API y guardan resultados y capturas en `artifacts/nebo` del workspace. Para otra URL usa `NEBO_TEST_URL`. El informe de esta sesión está en `artifacts/nebo/verification.md`.
