# Validación humana del piloto de fase 2

La revisión técnica independiente está aprobada en [phase-2.md](phase-2.md).
La puerta automática da PROVISIONAL; faltan las comprobaciones y la firma humana.

## Generación real sin entrega

Las ejecuciones de validación usan `--no-send`: no envían correo ni escriben nuevas
copias en Obsidian o Drive. Los jobs 5 y 6 se cancelaron para ajustar la prioridad
provisional de extracción tras observar la latencia de Qwen; se conservan sus
estados y auditoría, incluida la revisión fallida `rep_daily_2026-11-05_r2`.

Los jobs de reemplazo son:

- **7, diario:** rehace el intervalo del primer diario como revisión nueva.
  Archivo previsto: `build/pilot/data/reports/daily/rep_daily_2026-11-05_r3/report.html`.
- **8, semanal:** espera el bloqueo del worker y después genera los siete días
  completos anteriores. Archivo previsto:
  `build/pilot/data/reports/weekly/rep_weekly_2026-W45_r1/report.html`.

Esos archivos solo aparecen al finalizar la generación y superar el validador.
El plazo máximo configurado es 60 minutos por trabajo desde que empieza a
procesarse; el semanal espera al diario. Una sección sin salida válida queda
mecánica y se indica en el informe. No se afirma que los jobs hayan terminado
solo porque esta ficha exista.

Para consultar el estado desde la raíz del repositorio, sin modificar datos:

```bash
.venv/bin/python -c "import sqlite3; db=sqlite3.connect('file:build/pilot/data/digest.db?mode=ro', uri=True); print(db.execute('SELECT id,kind,state,error FROM job WHERE id IN (7,8)').fetchall()); db.close()"
```

`queued` significa en cola; `running`, en curso; `done`, finalizado; `failed`,
fallido. Los informes terminados se abren como archivos HTML locales.

## Las tres comprobaciones

1. **Cinco afirmaciones:** elige cinco afirmaciones concretas del diario, de
   resultados y proyectos diferentes. Abre los IDs de evidencia enlazados;
   comprueba que respaldan el texto, las cifras y sus unidades. Si la evidencia
   solo fue observada en la captura, no demuestra que el trabajo terminase hoy.
2. **Plan ejecutable:** comprueba que las acciones propuestas tienen criterio de
   finalización claro y dependencias resolubles, y que no repiten tareas
   terminadas. Si la sección es mecánica, no hay aún un plan LLM que aprobar.
3. **Utilidad del semanal:** contrasta su balance con los objetivos de Benchmark
   y VCD. Busca una relación, patrón, duda o prioridad que ayude más que releer
   los diarios. Las hipótesis deben estar marcadas como interpretaciones y las
   revisiones pendientes no deben darse por comprendidas.

Las limitaciones conocidas de fuentes siguen apareciendo en Cobertura: exploración
y texto acotados, tablas de métricas todavía no declaradas y, en las sesiones
SQLite, posibles cambios recientes en WAL no incluidos en la lectura inmutable.
No se considera demostrada una tendencia científica solo por disponer de un
informe semanal.

Tras hacer las comprobaciones, marca únicamente las satisfactorias en la sección
Firma de [phase-2.md](phase-2.md). La fase siguiente espera esa aprobación.
