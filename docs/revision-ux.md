# Revisión de experiencia de uso

La implementación final de interfaz se rehízo con GPT-6.1-sol y razonamiento bajo, siguiendo la preferencia del usuario: conservar el atractivo de la primera versión de NEXUS y acompañar a una persona sin conocimientos financieros.

## Cambios

- Inicio con gradientes violeta/cian, tarjetas de recorrido adaptables y una acción principal.
- Cuatro etapas: perfil, escenario, revisión y resultado. La navegación identifica avance y permite volver.
- Preguntas cotidianas y ejemplos monetarios para interpretar tolerancia y liquidez.
- Cuatro escenarios ficticios opcionales, con señales manuales editables.
- Respuestas guardadas y borradores separados, restaurados al navegar y descartables.
- Ejecución única en revisión; las entradas se copian junto a la evaluación para evitar confundir resultados anteriores con datos nuevos.
- Resultado con resumen compacto, tabla semántica, barras de distribución y explicación de la clasificación.
- Auditoría y JSON como detalle adicional. No se afirma que la traza incluya cada ajuste porcentual.

## Verificación realizada

- Nueve pruebas automáticas: recorrido, valores guardados y borradores, errores, confirmación del escenario, resultados desactualizados, recálculo, descarte de cambios, auditoría y presets.
- Diez casos de referencia del motor, evaluados dos veces para comprobar determinismo; la aprobación financiera del docente o asesor continúa pendiente.
- Código del motor, servicio, validaciones y cartera idéntico al anterior a la mejora de UX.
- Recorrido real en navegador desde las acciones del contenido, usando un importe ficticio y un escenario de ejemplo.
- Anchos de 375, 768, 1024 y 1440 px: sin desplazamiento horizontal de la página en las mediciones del resultado. También se inspeccionó el panel habitual de aproximadamente 890 px.
- Foco visible de 3 px y navegación con Tab. Contraste de los pares principales medido por encima de 4,5:1.
- Tarjeta final de resumen y encabezado porcentual revisados visualmente tras el último ajuste.

## Límites de la comprobación

Esto no constituye una certificación de accesibilidad. Quedan para revisión manual el lector de pantalla, zoom y el foco automático del resumen de errores; la implementación mantiene controles nativos y errores junto a los campos, sin scripts que manipulen el documento padre. La regla de movimiento reducido se comprobó en el CSS.

Las pruebas verifican la disponibilidad de las exportaciones y que las vistas reutilizan la misma evaluación. El observador de descargas del navegador no devolvió un evento al probar el JSON; no se confirmó la escritura del archivo descargado mediante esa herramienta.

Las diferencias funcionales con el brief y los casos para revisión experta se detallan en `validacion-brief.md` y `casos-brief.json`.
