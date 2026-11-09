---
name: grounding_overview
version: 1
task: contrast
---

El target_section actual es conceptual y candidate es SOLO DailyOverview. Evalúa
esa pieza; generation_context.balances contiene balances padres como contexto,
no campos de candidate que debas corregir. Las reglas de ProjectDigest se aplican
cuando ese objeto es el candidato, no a sus copias dentro del contexto de esta capa.

La lectura móvil de cada proyecto reúne candidate.highlights y
generation_context.balances[project_id].reading_conditions: esas condiciones
acompañan automáticamente a los destacados. Antes de señalar missing_condition,
comprueba ambos lugares. No exijas repetir en cada destacado una condición ya
explícita y citada en las condiciones acompañantes. Si el aspecto decisivo no
aparece en ninguno, rechaza el destacado afectado.

Una condición acompañante no compensa una afirmación contradictoria o excesiva
del destacado: ese error sigue rechazándose en su campo. Si una premisa contextual
es dudosa y el candidato la convierte en certeza, señala dónde ocurre en candidate.
No atribuyas al servicio verificaciones que solo declara una nota.

Todas las rutas field son relativas a candidate: por ejemplo, highlights seguido
de su índice entero y la clave afectada. Nunca empieces field por candidate,
generation_context o balances. No señales como defecto de esta pieza un campo
del padre que no afecta lo que el candidato afirma ni su lectura acompañante.
