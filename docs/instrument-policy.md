# Política de recomendación de instrumentos

## Qué se comprueba antes de elegir

Primero se revisa si el instrumento pertenece a los grupos que cubre esta versión y si hay datos publicados suficientes. Por ejemplo, un fondo necesita información sobre su moneda, monto mínimo, plazo para retirar el dinero y composición cuando se busca exposición a inflación o al dólar. Para una acción o un CEDEAR se revisan su identidad y las ofertas públicas disponibles. Si falta una condición necesaria o los datos se contradicen, el instrumento no pasa a la comparación.

La exposición a inflación o al dólar se comprueba con la lista fechada de activos publicada por el fondo. Deben identificarse más de la mitad de sus activos y la lista debe tener como máximo 35 días. Por ejemplo, si en una lista de hace 20 días se identifica 60% de activos CER, el dato puede apoyar esa exposición para la regla. No demuestra qué tiene el fondo hoy. Que el fondo declare ese objetivo no reemplaza la composición publicada.

## Cómo elige entre las opciones

Entre los instrumentos que pasaron las comprobaciones, se comparan solo datos que se pueden contrastar. Por ejemplo, se pueden comparar gastos publicados de dos fondos o el margen entre oferta de compra y venta de dos valores observados. Un dato ausente sigue siendo desconocido; no se cuenta como cero. Si una categoría no tiene instrumentos que pasen las reglas, queda sin opción en vez de completar la lista con uno que no cumple.

Una categoría tiene un monto simulado. NEXUS puede mostrar hasta dos opciones que compiten por ese mismo monto: la segunda es una alternativa que reemplaza a la primera, no una posición adicional.

## Qué te queda confirmar

La selección no comprueba que tu intermediario ofrezca el instrumento, habilite tu cuenta, acepte la moneda que tenés o cobre un costo determinado. Tampoco calcula una orden ejecutable. Antes de operar, esas condiciones, el precio final, la cantidad y los plazos se confirman con el intermediario. La revisión experta de las reglas sigue pendiente.

Consultá el [glosario](glosario.md) para términos como FCI, cuotaparte, CEDEAR y T+0.

<details>
<summary>Umbrales, reglas y referencias técnicas</summary>

## Detalle técnico y reglas vigentes

La política `argentina-4` compara instrumentos identificados en el mercado argentino con hechos publicados y contexto congelado del escenario. La selección del instrumento es distinta de comprobar una orden en un intermediario. No demuestra que un usuario pueda operar un activo, no valida una cuenta concreta y no constituye validación profesional. `expert_review` permanece `pending`.

## Alcance y salidas

La investigación usa `selection_scope=ARGENTINA_SIN_BROKER` y `schema_version=4`. Solo `selected` es la selección. `educational_selection`, si se mantiene por compatibilidad, es exactamente una proyección de `selected`; nunca genera tarjetas por separado. La comprobación estricta anterior sigue disponible en `STRICT_EXECUTION` y en la evaluación directa predeterminada de reglas.

Cada evaluación de recomendación informa `decision`, `eligible`, `missing_fields`, `selection_explanation` y factores de ranking observables. `execution_checks.status=PENDIENTE_INTERMEDIARIO` conserva pendientes de broker, aranceles, moneda y canal de suscripción, autorización de cuenta, precio final, cantidad y liquidación. No se inventan costos cero, moneda de fondeo o autorización.

Se evalúan FCI argentinos y acciones locales/CEDEAR identificados por fuentes como instrumentos BYMA. Fondos o valores externos, cripto, ETF, representaciones no ordinarias y exposición no identificada no entran por familiaridad o nombre. Moneda de cotización/denominación debe coincidir con la moneda simulada; no se presupone conversión.

## FCI

Se requiere evidencia vigente de identidad, categoría/exposición, moneda de clase, mínimo, plazo de liquidación, estado abierto del fondo y de la suscripción/rescate, condición de calificado y horizonte. El mínimo publicado y una comisión de ingreso publicada se usan como cota inferior de presupuesto; una tarifa del broker desconocida no bloquea la recomendación y permanece pendiente de ejecución. La suscripción en el broker y el dinero disponible para fondearla no se infieren de la moneda de denominación del FCI.

Horizonte mínimo de CAFCI y duración se comprueban con los umbrales provisionales del simulador. Los fondos de renta fija necesitan duración publicada con evidencia vigente; el horizonte flexible solo pasa cuando esa duración está identificada y puede compararse con el horizonte del usuario. La categoría de liquidez inmediata exige clasificación de mercado de dinero y rescate T+0 informados; no implica disponibilidad 24/7 ni garantía de depósito. Los mandatos de inflación/cambiarios no bastan: hace falta una composición fechada de hasta 35 días con más de 50% de renglones explícitos identificables. La suma y clasificación se guardan como inferencia con su fecha, método y renglones fuente; los demás activos permanecen desconocidos.

Para inflación se buscan términos completos BONCER, CER o UVA. Para FX se buscan etiquetas inequívocas como dollar-linked o vinculado al dólar. No se usa un ticker aislado, el nombre del fondo, una cuenta USD o `Fut Reg ARS` como prueba de exposición. Composición de hasta 7 días se presenta como reciente; entre 8 y 35 días se advierte que es la última publicada, no la cartera de hoy. No se consideran suficientes calificaciones crediticias antiguas como medida del riesgo total.

Los gastos anuales del fondo solo se derivan cuando se conocen sus componentes de administración y gasto ordinario. Las tasas de ingreso/rescate se conservan separadas. Campos ausentes no significan gratuidad.

## Acciones y CEDEAR

BYMADATA da un snapshot referencial. La evaluación requiere bid/offer y cantidades positivas, evidencia coincidente de snapshot, observación con zona horaria no futura y menor o igual a 15 minutos, vencimiento vigente y spread dentro del umbral configurable. `unit_price` y la fecha del último negocio siguen desconocidos: no se fabrican con `tradeHour` ni con la hora de consulta. La observación no es un precio ejecutable y no completa los controles estrictos de una orden.

La ficha de producto debe acreditar tipo, mercado, moneda e identidad. CEDEAR debe ser representación ordinaria para entrar como renta variable. Para CD se acepta una cota de una unidad nominal según BYMA 17710, manteniendo `indicative_minimum` como inferencia; no se marca `lot_size=1` como un dato del quote. Acciones locales requieren una unidad mínima respaldada antes de juzgar su asequibilidad. Esta política no equipara ETF, cripto, commodities ni cuotapartes con acciones.

## Ranking y límites

Primero se aplican exclusiones y suficiencia de hechos; el ranking solo compara candidatos elegibles. Los topes y compatibilidad de perfil se aplican como reglas explícitas; las fuentes consultadas no aportan un puntaje comparable de riesgo total, así que `risk_fit` permanece desconocido y no desempata. Plazos, diversificación cuando se acredita, gastos publicados del FCI, spread del snapshot y presencia medida se comparan solo cuando la misma métrica está disponible para ambos candidatos. Los gastos de FCI no se comparan con spreads de valores; los empates entre familias con métricas no comparables se resuelven por identidad canónica. Métricas como AUM y monto negociado describen presencia observada, no seguridad, familiaridad ni liquidez futura. No se puntúa rentabilidad pasada, marca, ticker, familia, orden de API ni clase A. Se seleccionan hasta dos alternativas de una categoría como opciones al mismo presupuesto, no como dos asignaciones completas.

Se agrupan clases del mismo fondo/subyacente. La búsqueda examina el pool recibido antes del límite de resultados, rota las consultas entre categorías y conserva el candidato original en auditoría aunque quede fuera de la cola investigada. Los valores predeterminados son hasta 12 consultas, 24 segundos y 12 candidatos de resultado por categoría. Fallas de fuente o límites agotados dejan la información insuficiente; no activan una lista sustitutiva. El universo de búsqueda no se afirma completo.

Los factores, umbrales y composición se pueden reproducir a partir de las entradas congeladas, evidencia, fuentes y fecha de evaluación. No se afirma diversificación cuando las concentraciones no se pueden medir. Se mantienen los topes de perfil y asignación configurados, sin relajar reglas para producir un ganador.

## Fuentes de política

- [Glosario CAFCI](https://www.cafci.org.ar/glosario.html) y [Manual de Idoneidad](https://www.argentina.gob.ar/sites/default/files/pdf_cafci.pdf): terminología de horizontes. Los umbrales concretos de este simulador son una regla provisional propia.
- [Ficha técnica de títulos públicos](https://www.argentina.gob.ar/sites/default/files/ficha_tecnica_valuacion_titulos_publicos10052022.pdf): definición de bonos ajustables por CER.
- [BYMA COM 17710](https://data-widgets.byma.com.ar/wp-content/uploads/2020/08/BYMA-COM-17710-Modificacion-de-unidad-minima-de-negociacion-CEDEAR.pdf): unidad nominal mínima de CEDEAR.
- [Acceso público a BYMADATA](https://www.byma.com.ar/newsroom/byma-habilita-un-acceso-abierto-a-bymadata): contexto de demora del feed público. El evaluador conserva la hora observada de consulta, no la fecha de negocio.

</details>
