# Comprobación del piloto de fase 1

Fecha: 5 de noviembre de 2026. Informe `rep_daily_2026-11-05_r1`.

## Resultado verificado por el constructor

- Generado con `digest --config config.yaml run --now --no-send` contra Benchmark y VCD.
- Después, entregado explícitamente con `digest deliver --report rep_daily_2026-11-05_r1`.
- Correo: `sent`, un intento; Obsidian: `sent`, un intento.
- Drive: primer intento fallido con HTTP 403 asociado a cuota de la API;
  segundo intento, solo del canal Drive: `sent`. No se repitió el correo.
- PDF generado por WeasyPrint y copiado junto al Markdown, HTML y JSON.

La configuración privada conserva las rutas y destinatarios; no se copia aquí
el contenido científico de los informes ni las credenciales.

## Cobertura que debe tenerse en cuenta

Es la primera captura: un estado de tarea observado ahora no permite afirmar
que esa tarea se completó hoy. Las evidencias distinguen hora observada y hora
de evento; esta captura inicial sirve también como referencia para las siguientes.

Kanvas pasa en ambos proyectos. Git registra archivos demasiado grandes y diffs
recortados. Documentos, figuras y logs alcanzan el límite de exploración de
100 000 entradas; los documentos también alcanzan el presupuesto de texto.
En VCD hay logs recortados. Todo ello aparece en la sección Cobertura.

La configuración del piloto todavía no declara tablas de métricas: el estado
`ok` de esa fuente significa que no había tablas configuradas que leer, no que
se hayan validado sus resultados científicos. La selección de fuentes candidatas
está en [PILOT_SOURCES.md](../PILOT_SOURCES.md); habrá que acotar las rutas y
columnas antes de considerar representativa la cobertura de ambos proyectos.

## Comprobaciones humanas pendientes

La firma está en [phase-1.md](phase-1.md), sin marcar por el agente. Comprobar
el correo en el móvil, contrastar el informe real con el trabajo conocido y
abrir las copias en Obsidian y Drive. La aprobación de la fase exige que las
omisiones se consideren aceptables; las pruebas automáticas no deciden eso.

Informe local: `build/pilot/data/reports/daily/rep_daily_2026-11-05_r1/report.html`.
Obsidian: `Digest/2026-11-05.md`. Drive: `DailyDigest/reports/daily/rep_daily_2026-11-05_r1/`.
