# Fuentes iniciales del piloto

Inventario exploratorio de solo lectura, acotado por profundidad, número de
entradas y tamaño de lectura. No es una lista exhaustiva ni acredita que los
archivos estén actualizados. Su fecha de modificación no demuestra que un
resultado se haya producido durante el intervalo del informe.

## Benchmark

Candidatos documentales, relativos a la raíz del proyecto:

- `blindDataset/results/revision_tareas_20260817/09_reports/INFORME_INTEGRADO.md`.
- `metricas/new_data/results/informe_metricas.md`.
- `blindDataset/results/metricas/01_Global_Metrics/*.html` y su variante `lp/`:
  comprobar procedencia y duplicación antes de considerarlos informes distintos.
- Documentos de interpretación, claims y controles vinculados desde Kanvas.

Candidatos tabulares:

- `blindDataset/results/revision_tareas_20260817/04_surface_metrics/hodgkin_paired_summary.csv`:
  `subset`, `hodgkin_type`, `model`, `mean_delta_H`, `lcl`, `ucl`, `median_delta_H`.
- `blindDataset/results/revision_tareas_20260817/04_surface_metrics/reference_area_summary.csv`:
  `comparison`, `mean`, `median`, `sd`, `q025`, `q975`, `max_abs`.
- `*/analysis/results/run_summary.csv`: cobertura de ejecuciones. Sus recuentos
  no se usan como medida de avance científico.

Hay tablas de mayor tamaño que no se leyeron en este inventario. La selección
definitiva de patrones y columnas se hará en CP-04, respetando los límites de
configuración y registrando omisiones. Las cifras deben conservar su definición,
escala, unidad y referencia experimental; el nombre de columna no basta.

## VCD

- `backend_2/results_benchmark/benchmark/benchmark_report.tsv`.
- `backend_2/results_benchmark_12_targets_cap1000/*/cavity_benchmark/benchmark_report.tsv`.
- Columnas verificadas: `metric`, `value`, `threshold`, `status`.
- Documentación de interpretación y validación en `backend_2/docs/` y `docs/`.
- `VCD/templates/report_steps56.html` y `report_export_links.html` son plantillas,
  no informes de una ejecución concreta. Los resultados generados deben conservar
  su asociación con la diana y la ejecución.

## Markdown, informes y sesiones

La persona confirma que deben incluirse los Markdown y los informes generados,
además de tablas y figuras. Su contenido se trata como evidencia, nunca como
instrucciones al servicio. HTML y PDF requieren el tratamiento seguro del formato;
no se ejecuta JavaScript ni contenido embebido.

También acepta sesiones relevantes de Codex, OpenCode y Hermes y no indica otras
herramientas. El recolector de fase 2 deberá verificar ubicaciones y formatos,
aplicar exclusiones de secretos y enviar únicamente extractos acotados vinculados
al proyecto. Esta aceptación no habilita la carga indiscriminada de historiales.

La documentación consultada de VCD menciona SGE y Nextflow. No se da por probado
que `sacct` esté disponible ni que ambos repositorios compartan un planificador.
La selección de logs y acceso al clúster se verificará en CP-05; Slurm continúa
desactivado en la configuración local del piloto.
