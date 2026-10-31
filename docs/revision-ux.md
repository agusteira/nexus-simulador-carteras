# Revisión de experiencia de uso

Este documento registra una revisión anterior de la interfaz: qué cambió y qué se comprobó en ese momento. No es un tutorial de inversiones ni una certificación de accesibilidad o de idoneidad financiera.

El trabajo buscó conservar el aspecto de NEXUS y hacer que los pasos y preguntas fueran comprensibles para personas sin experiencia financiera.

## Cambios

- Inicio con colores violeta y cian, tarjetas adaptables y una acción principal.
- Cuatro pasos: perfil, escenario, revisión y resultado. La navegación muestra el avance y permite volver.
- Preguntas cotidianas y ejemplos de dinero para explicar tolerancia y liquidez.
- Cuatro escenarios ficticios opcionales que se pueden editar.
- Respuestas guardadas y borradores separados, que se restauran al navegar y se pueden descartar.
- Un cálculo desde la pantalla de revisión. Las respuestas usadas se guardan junto al resultado para distinguirlo de cálculos posteriores.
- Resultado con resumen, tabla, barras y explicación del perfil.
- Auditoría y archivo JSON disponibles como detalle. La traza no necesariamente muestra cada ajuste porcentual.

## Verificación realizada

- Nueve pruebas automáticas de recorrido, respuestas guardadas, errores, confirmación del escenario, resultados anteriores, recálculo, descarte de cambios, auditoría y escenarios de ejemplo.
- Diez casos de referencia, calculados dos veces para comprobar que las mismas entradas den el mismo resultado. La revisión experta de los porcentajes sigue pendiente.
- En esa revisión, no se modificaron las reglas de cálculo, las validaciones ni la construcción de la cartera.
- Recorrido real en navegador desde las acciones del contenido, usando un importe ficticio y un escenario de ejemplo.
- Anchos de 375, 768, 1024 y 1440 px: sin desplazamiento horizontal de la página en las mediciones del resultado. También se inspeccionó el panel habitual de aproximadamente 890 px.
- Foco visible de 3 px y navegación con Tab. Contraste de los pares principales medido por encima de 4,5:1.
- Tarjeta final de resumen y encabezado porcentual revisados visualmente tras el último ajuste.

## Límites de la comprobación

Estas comprobaciones no certifican accesibilidad. Quedaron pendientes la revisión con lector de pantalla, el zoom y el enfoque automático del resumen de errores. La preferencia de movimiento reducido se comprobó en los estilos de la interfaz.

Las pruebas comprobaron que la descarga estuviera disponible y que las vistas usaran el mismo resultado. La herramienta usada no confirmó que el archivo JSON se hubiera guardado en el dispositivo.

Las diferencias funcionales con el brief y los casos para revisión experta se detallan en `validacion-brief.md` y `casos-brief.json`.
