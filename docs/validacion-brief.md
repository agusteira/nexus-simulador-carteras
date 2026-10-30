# Validación del recorrido y del brief

Los datos de estos casos son ficticios. Las salidas de referencia usan la matriz v1 y la política provisional `educational-1`. La coincidencia técnica no certifica idoneidad financiera ni cumplimiento regulatorio. Horizonte y objetivo ahora pueden limitar renta variable y trasladar el excedente a liquidez; las reglas y sus umbrales requieren revisión experta.

## Diez casos para revisión del docente o asesor

Entradas y salidas completas: `casos-brief.json`. Capital de referencia: ARS 100.000; horizonte: 24 meses. La liquidez mínima es 20%, salvo indicación específica.

| Caso | Perfil o condición | Escenario simulado | Resultado a revisar |
|---|---|---|---|
| C01 | Tolerancia 0% | Sin alertas | Conservador, 0% renta variable, suma 100% |
| C02 | Tolerancia 0% | Inflación elevada | Conservador, 0% renta variable, cobertura ajustada |
| C03 | Tolerancia 10% | Sin alertas | Moderado; preservación limita renta variable a 10%, liquidez 30% |
| C04 | Tolerancia 10% | Inflación elevada | Moderado, cobertura ajustada |
| C05 | Tolerancia 20% | Sin alertas | Agresivo; topes por horizonte y preservación: renta variable 10%, liquidez 55% |
| C06 | Tolerancia 20% | Inflación elevada | Agresivo; renta variable 10%, liquidez 45%, renta fija inflación 30% |
| C07 | Tolerancia 20% | Volatilidad elevada | Renta variable trasladada a liquidez |
| C08 | Tolerancia 20%, liquidez mínima 100% | Sin alertas | 100% liquidez, suma 100% |
| C09 | Tolerancia 0%, objetivo Crecimiento | Sin alertas | Derivación controlada con causa comprensible |
| C10 | Escenario sin confirmar | Sin alertas | Derivación controlada por confirmación faltante |

**Aprobación experta pendiente.** El docente o asesor debe revisar los porcentajes, las justificaciones y las contradicciones; registrar nombre, fecha, observaciones y aprobación. No marcar estos casos como aprobados por el mero hecho de superar pruebas automáticas.

## Criterios del recorrido

- Una acción principal lleva al siguiente paso; siempre existe una ruta para volver.
- Perfil y escenario conservan los valores al navegar. Los borradores y las entradas guardadas tienen responsabilidades explícitas.
- Los errores identifican el campo y cómo corregirlo, sin cambiar silenciosamente las preferencias del usuario.
- Una evaluación conserva copia de las entradas usadas. Cambiar las entradas vuelve desactualizada la salida anterior; nunca se presenta como una evaluación de los datos nuevos.
- Resultado, detalle técnico y exportación se refieren a la misma ejecución.
- La derivación es un estado del prototipo; no implica que se haya enviado una solicitud a un asesor.
- Los datos se conservan durante la sesión de Streamlit. Recargar el navegador o cerrar la sesión puede perderlos; no se promete almacenamiento permanente.
- La interfaz tiene foco visible, orden de teclado comprensible, errores expresados con texto, contraste medido y alternativas textuales a los gráficos.
- Se revisan ventanas de 375, 768, 1024 y 1440 px, orientación horizontal, zoom y movimiento reducido.

## Diferencias respecto del brief

| Requisito | Alcance de esta entrega | Pendiente funcional |
|---|---|---|
| RF-01 | Captura guiada y validación del perfil en la web | Ingesta mediante API |
| RF-02 | Escenario manual confirmado; fuente pública de FCI con fechas, timeout, caché y ventana de calidad de 7 días | Indicadores macroeconómicos reales y definición experta de su vigencia |
| RF-03/RF-04 | Conservar reglas e invariantes del motor | Validación financiera de las reglas por un experto |
| RF-05 | Ejemplos concretos de FCI publicados por ArgentinaDatos; clasificación, moneda y mínimo revisados cuando hay metadatos suficientes; alternativas explícitamente sin compatibilidad verificada | Elegibilidad financiera integral, exposición CER/cambiaria verificada, disponibilidad operativa y revisión experta |
| RF-06 | Acceso comprensible a la traza disponible y JSON | Traza completa de reglas evaluadas y de ajustes de cartera |
| RF-07 | Causa y ruta de recuperación en casos derivados | Atención real por un asesor, si se define integración |
| RF-08 | Administración y versionado persistente de matrices | Revisión experta de cambios |
| RF-09 | Historial SQLite por usuario y comparación; revisiones de investigación inmutables | Identificación/autenticación de usuarios y almacenamiento duradero en hosting efímero |

No se incorporan compra/venta, predicción de precios, custodia ni gestión de saldos. El motor continúa siendo determinístico.
