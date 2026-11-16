# Revisión independiente adicional: formularios del navegador

reviewer: codex, sesión independiente de la construcción (`review_watchlist`)
date: 2026-11-16
scope: corrección de seguridad de formularios, commit `9ecad51`

Esta revisión complementa WA-05 y WA-10. No cambia el veredicto histórico de
fase 3, sus firmas ni los estados humanos de comprensión.

## Problema y corrección revisada

El navegador enviaba `Origin: null` al confirmar «Revisar lista» bajo
`Referrer-Policy: no-referrer`; el middleware rechazaba correctamente ese origen.
La respuesta cambia a `Referrer-Policy: same-origin`, conservando la comparación
exacta de Origin y los controles CSRF. Los nombres de cookie incorporan una
huella de bind, puerto y URL pública: abrir otra instancia en el mismo host ya
no reemplaza la cookie de la primera. Las cookies siguen siendo firmadas,
HttpOnly, SameSite=Strict y Secure cuando corresponde.

## Hallazgos

No se han encontrado hallazgos bloqueantes ni importantes abiertos en el cambio.
No se acepta `Origin: null` ni se relaja la comprobación de origen para resolver
el fallo. La huella del nombre no contiene credenciales ni sustituye la firma
criptográfica de la sesión.

## Intentos de rotura y evidencia

- Revisión del diff de `src/digest/web/security.py`, tests nuevos y script de
  navegador; el control común de loopback, Host, identidad Tailscale, tamaño de
  cuerpo, firma de cookie y token CSRF permanece activo.
- `.venv/bin/python -m pytest -q tests/unit/test_web_security.py
  tests/e2e/test_web_reading.py tests/e2e/test_watchlist.py`: **45 pruebas pasan**.
  Ruff y formato de los dos archivos Python del cambio también pasan.
- Dos pruebas privadas adicionales en
  `build/review-browser-forms/test_adversarial.py`: **2 pasan**. Se intentaron
  Origin nulo, dominio ajeno y puerto distinto con token válido; Sec-Fetch-Site
  cross-site; identidad incorrecta; token ausente, inventado o de otra sesión;
  y trasplante de la cookie de otra instancia renombrándola al nombre esperado.
  Todos se rechazan con 403. El POST legítimo posterior conserva 200.
- Dos instancias sintéticas con el middleware real, en 8097 y 8098, y Chromium
  con Playwright: un formulario nativo de la primera sigue devolviendo 200
  después de abrir la segunda en el mismo contexto del navegador. Origin exacto
  `http://127.0.0.1:8097`; cookies con nombres distintos. Seguir un enlace a la
  segunda instancia no envía Referer: la nueva política no revela la ruta a otro
  origen. Resultado en `build/review-browser-forms/browser-result.json`, scripts
  `server.py` y `browser.cjs`. Las instancias sintéticas se detuvieron al terminar.
- Reejecución independiente contra las dos webapps existentes:
  `DIGEST_PLAYWRIGHT_MODULE=/home/aserrano/.cache/ms-playwright-go/1.57.0/package
  node scripts/check_browser_forms.cjs http://127.0.0.1:8091
  http://127.0.0.1:8090/`: **PASS**, preview 200 con Origin exacto y cookie después
  de visitar la otra instancia. Solo se preparó la vista previa; no se guardó
  ninguna ficha ni se encoló trabajo.

## Veredicto

**Aprobada técnicamente** sobre `9ecad51`. La corrección restaura el envío nativo
del navegador y mantiene la defensa de origen y sesión. La suite completa,
puerta automática y comprobaciones humanas de WA-05 conservan su propio flujo;
esta ficha no firma su aprobación.
