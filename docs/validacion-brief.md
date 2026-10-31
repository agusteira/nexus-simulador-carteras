# Validación del recorrido y del brief

Esta página reúne diez ejemplos ficticios para revisar que la aplicación responda de forma consistente a los datos ingresados. Los porcentajes de referencia usan la tabla de reparto v1. La revisión de instrumentos usa reglas provisionales. Que una prueba coincida con el ejemplo solo muestra que el sistema siguió sus reglas; no confirma que el resultado sea adecuado para una persona.

El horizonte y el objetivo pueden limitar renta variable y mover el excedente a liquidez. Las reglas y sus umbrales aún requieren revisión experta.

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

**Revisión experta pendiente.** Un docente o asesor debe revisar los porcentajes, los motivos y los posibles conflictos; anotar nombre, fecha y observaciones. Que una prueba automática pase no cuenta como aprobación experta.

## Criterios del recorrido

- Cada botón principal avanza al paso siguiente y hay una forma de volver.
- Las respuestas se mantienen al navegar. Los borradores se distinguen de las respuestas guardadas.
- Los errores señalan qué respuesta corregir; la aplicación no cambia tus respuestas sin avisar.
- Cada cálculo conserva una copia de las respuestas usadas. Si las cambiás, el resultado anterior se identifica como desactualizado.
- El resultado, su detalle y la descarga corresponden al mismo cálculo.
- Si el sistema no puede continuar, lo informa. No envía una consulta a un asesor.
- Los datos pueden perderse al recargar o cerrar la sesión; este recorrido no garantiza almacenamiento permanente.
- La interfaz se revisa con teclado, foco visible, texto para errores y gráficos, y contraste legible.
- Se revisan pantallas de 375, 768, 1024 y 1440 píxeles, además de zoom, orientación horizontal y movimiento reducido.

<details>
<summary>Requisitos del brief: identificadores RF y alcance técnico</summary>

## Diferencias respecto del brief

| Requisito | Alcance de esta entrega | Pendiente funcional |
|---|---|---|
| RF-01 | Captura guiada y validación del perfil en la web | Ingesta mediante API |
| RF-02 | Escenario manual confirmado; fuente pública de FCI con fechas, timeout, caché y ventana de calidad de 7 días | Indicadores macroeconómicos reales y definición experta de su vigencia |
| RF-03/RF-04 | Conservar reglas e invariantes del motor | Validación financiera de las reglas por un experto |
| RF-05 | Investigación con CAFCI y BYMADATA: clases de FCI, datos diarios, composición publicada y observaciones públicas de valores BYMA, según la evidencia disponible | Cobertura completa del mercado, compatibilidad financiera integral, disponibilidad operativa y revisión experta |
| RF-06 | Acceso comprensible a la traza disponible y JSON | Traza completa de reglas evaluadas y de ajustes de cartera |
| RF-07 | Causa y ruta de recuperación en casos derivados | Atención real por un asesor, si se define integración |
| RF-08 | Administración y versionado persistente de matrices | Revisión experta de cambios |
| RF-09 | Historial SQLite por usuario y comparación; revisiones de investigación inmutables | Identificación/autenticación de usuarios y almacenamiento duradero en hosting efímero |

No se incorporan compra/venta, predicción de precios, custodia ni gestión de saldos. Con las mismas respuestas y reglas, el cálculo produce el mismo resultado.

</details>
