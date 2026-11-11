# Cuaderno personal sobre las tareas de Kanvas

Propuesta de fase 3 solicitada por la persona el 2026-11-11. La webapp permite
organizar su trabajo sobre las tareas capturadas, conservando Kanvas como fuente
de solo lectura. No se trata de ejecutar notebooks de código.

## Vista y contexto

- Vista de tarjetas por estado y vista de dependencias con flechas, inspiradas
  en los patrones de Kanvas. Filtros por proyecto, disponibilidad y prioridad.
- Ficha por `(proyecto, ID de tarea)`, sin mezclar tareas con el mismo ID en
  distintos proyectos: descripción, dependencias, objetivo y evidencias.
- Notas y ajustes personales separados de las notas de agentes y del tablero.
  Historial de versiones; ningún informe puede reescribirlos ni declarar una
  tarea comprendida.
- Abrir una tarea o cambiar prioridad no ejecuta nada ni cambia su estado en
  Kanvas. La prioridad de la cola técnica del digest no cambia por estas notas.

## Fecha y prioridad propuestas

Kanvas ya incluye `at` como fecha de creación cuando está disponible. Se muestra
con esa procedencia; una fecha ausente no se inventa. El servicio registra además
desde cuándo conoce la tarea. Si solo dispone de una captura observada, lo indica
como tal, sin presentarla como fecha de creación histórica.

La prioridad base es editable entre 0 y 100; valor inicial 50. Por defecto,
las tareas abiertas añaden un punto por día de antigüedad, hasta veinte puntos:

`prioridad sugerida = min(100, base editable + min(20, días de antigüedad))`

Los valores por defecto y el aumento se pueden ajustar o desactivar. La ficha
muestra por separado base, aumento y valor sugerido. La base no se modifica
silenciosamente y una tarea no se convierte en urgente sin límite por ser antigua.
Al faltar la creación, el aumento se calcula desde el seguimiento observado y
se rotula así. Las tareas terminadas no siguen acumulando aumento.

Una tarea bloqueada conserva su bloqueo aunque tenga prioridad alta; las flechas
permiten abrir lo que la bloquea. La ordenación de las disponibles usa el valor
sugerido, sin aprobar, desbloquear ni iniciar tareas automáticamente.

## Relación con el digest

El plan podrá tener en cuenta estas prioridades como preferencias humanas y las
notas como contexto humano, manteniendo el ámbito conservador de privacidad.
La antigüedad ayuda a no olvidar trabajo; no demuestra valor científico ni
prevalece automáticamente sobre controles, dependencias o una misión aceptada.

Antes de implementar se concretará la persistencia, manteniendo versiones y
el respaldo. Si exige cambiar SQLite o formatos publicados, se presentará ese
cambio concreto a la persona según AGENTS.md. Las pruebas deberán cubrir
fechas desconocidas, prioridad manual, envejecimiento limitado, tareas bloqueadas,
IDs repetidos entre proyectos, XSS y que los tableros originales no cambian.
