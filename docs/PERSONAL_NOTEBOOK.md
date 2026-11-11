# Cuaderno personal sobre las tareas de Kanvas

WA-09, aprobada por la persona e implementada en fase 3 el 2026-11-11. La webapp permite
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

## Fecha y prioridad

Kanvas ya incluye `at` como fecha de creación cuando está disponible. Se muestra
con esa procedencia; una fecha ausente no se inventa. El servicio registra además
desde cuándo conoce la tarea. Si solo dispone de una captura observada, lo indica
como tal, sin presentarla como fecha de creación histórica.

La prioridad base es editable entre 0 y 100; valor inicial 50. Por defecto,
las tareas abiertas añaden un punto por día de antigüedad, hasta veinte puntos:

`prioridad sugerida = min(100, base editable + min(20, días de antigüedad))`

Los días son intervalos completos de 24 horas en UTC; las fechas se muestran en
Europe/Madrid. Una fecha futura no produce aumento negativo. Las reglas generales
permiten base 0–100, incremento 0–10 puntos/día y tope 0–100; el total nunca supera
100. Cada tarea permite heredar, activar o desactivar el aumento.

Los valores por defecto y el aumento se pueden ajustar o desactivar. La ficha
muestra por separado base, aumento y valor sugerido. La base no se modifica
silenciosamente y una tarea no se convierte en urgente sin límite por ser antigua.
Al faltar la creación, el aumento se calcula desde el seguimiento observado y
se rotula así. Las tareas terminadas no siguen acumulando aumento.

Una tarea bloqueada conserva su bloqueo aunque tenga prioridad alta; las flechas
permiten abrir lo que la bloquea. La ordenación de las disponibles usa el valor
sugerido, sin aprobar, desbloquear ni iniciar tareas automáticamente.

## Relación con el digest

El próximo plan diario tiene en cuenta estas prioridades como preferencias humanas y las
notas como contexto humano, manteniendo el ámbito conservador de privacidad.
La antigüedad ayuda a no olvidar trabajo; no demuestra valor científico ni
prevalece automáticamente sobre controles, dependencias o una misión aceptada.

Las notas se limitan a 4000 caracteres por tarea y el paquete del plan a 6000
caracteres de notas completas: una nota que no cabe se omite con aviso, sin
recortarla. Solo las tareas disponibles pueden ser candidatas. Los ajustes son
contexto humano; las afirmaciones del plan siguen necesitando evidencias válidas.
Si falta una política histórica de privacidad, el plan queda pendiente antes de
llamar al proveedor. El semanal no recibe estas notas por este flujo.

## Persistencia y conservación

Se usan claves de la tabla `meta` existente: revisiones `nb_revision:<id>` con su
huella `nb_hash:<id>`, punteros `nb_task:<hash(proyecto, ID)>` y `nb_settings`, y
peticiones `nb_submission:<nonce>`. Guardar añade una versión; el control de
edición obsoleta impide pisar cambios concurrentes y reenviar un formulario no
duplica versiones. No cambia el esquema SQLite ni los formatos de Obsidian/Drive.
El respaldo del cuaderno será el de SQLite previsto en la fase de operación;
estas notas todavía no tienen entrega externa propia.

Las notas sobreviven a las capturas. Una tarea retirada conserva ficha e historial
como «Fuera de captura», sin aumento ni disponibilidad para el plan. Si un ID se
reutiliza con otra creación, el historial permanece, pero sus ajustes anteriores
no se aplican automáticamente a la tarea nueva. El ámbito de privacidad incluye
los proyectos configurados y registrados al guardar y nunca se estrecha al editar.

La web muestra hasta 60 tareas por página, 20 versiones y 50 evidencias por página
de ficha. Las notas de origen se separan del texto personal y muestran las últimas
20, con un máximo de 4000 caracteres por nota y aviso de recorte. El grafo incluye
las tareas de la página e indica las dependencias que quedan fuera de ella.
