# Investigación educativa de instrumentos

La investigación de instrumentos es una capa educativa y de solo lectura sobre la simulación de cartera. No modifica asignaciones, no calcula cantidades ni rendimientos futuros, y no convierte una señal de familiaridad en una recomendación.

## Flujo

1. Se consulta el universo público de fondos y clases de CAFCI. Los datos de ArgentinaDatos y `build_examples` se conservan por compatibilidad histórica.
2. Los registros se normalizan y pasan por las reglas educativas versionadas.
3. Si faltan candidatos, la búsqueda se amplía dentro de un universo curado pequeño y limitado por consultas, tiempo y cantidad de resultados.
4. Solo se consultan referencias HTTPS fijas. Al proveedor se envía un registro normalizado; nunca el perfil ni el escenario personal.
5. Las tres pestañas conservan la UI previa. La pestaña de instrumentos muestra solo la selección del motor (`selected`) cuando coincide con una evaluación elegible, sin campos obligatorios faltantes. Las categorías empiezan cerradas y las exclusiones permanecen en el detalle. Cada resultado mantiene `expert_review: pending`.
6. Las señales de conocimiento y corrección se guardan para contexto futuro. Una corrección marca revisión; no modifica hechos de mercado.
7. Actualizar una investigación añade una revisión inmutable al historial. La evaluación original queda intacta.

## Límites y evidencia

La búsqueda usa `ResearchLimits` (6 consultas, 16 segundos y 20 resultados por categoría por defecto). Se recorre el catálogo completo antes de limitar los candidatos; el orden alfabético no decide las fichas. Una fuente sin datos no se interpreta como confirmación negativa. FCI puede confirmar algunos metadatos, pero no acredita por sí solo exposición económica, costos, acceso, liquidez ni condiciones de rescate. Un valor desconocido se muestra como tal y las reglas lo excluyen de una selección operativa.

El esquema 3 elimina la selección educativa independiente que mostraba fichas pese a una decisión de información insuficiente. `educational_selection` queda como proyección del mismo `selected`, sin requisitos menores. No se priorizan familias comerciales ni tickers durante la búsqueda; el pool completo se evalúa antes de limitar consultas. Se conserva por separado la evaluación del candidato inicial si queda fuera del límite. La familiaridad solo desempata entre elegibles, después de los criterios financieros y operativos. El mandato orienta la investigación y no prueba composición actual.

Las consultas guardadas con el esquema anterior no se reinterpretan como selecciones. La interfaz pide actualizarlas y conserva el JSON original. El resultado no agrega una biblioteca de Bitcoin ni otros instrumentos sin asignación.

Cada `investigacion` conserva `execution_id`, versiones de política y universo, entradas originales, categorías evaluadas, decisiones, fuentes observadas, reglas, errores y límites aplicados. `ejemplos_instrumentos` mantiene el resultado previo de los ejemplos legados y agrega esta investigación.

Las fichas separan campos observados, contenido curado y `explanation` (plantilla educativa versionada). Las fuentes respaldan campos concretos: ni una descripción ni una marca conocida prueban que el fondo tenga CER, cobertura cambiaria o disponibilidad inmediata. Los candidatos nuevos ingresan como propuestas. No hay agente que ejecute instrucciones de páginas externas ni entrenamiento de modelos.

## Cobertura comprobada

Verificación controlada del 30/10/2026 (Buenos Aires), mediante solicitudes públicas de lectura y TLS verificado:

| Fuente | Cobertura observada | Límite |
| --- | --- | --- |
| [CAFCI](https://estadisticas.cafci.org.ar/consulta-avanzada) | Catálogo público: 1.209 fondos con clases abiertas y 4.818 registros normalizados en la verificación; mínimos por clase, mandato, plazos y honorarios desglosados. Fichas con composición y fecha explícita | La composición comprobada era del 09/10/2026. No prueba tenencias de hoy ni costos efectivos, moneda de suscripción, exposición económica o acceso por broker. Los honorarios no se convierten en comisiones en pesos |
| [ArgentinaDatos](https://raw.githubusercontent.com/enzonotario/argentinadatos.com/main/datos/v1/finanzas/fci/fondos/index.json) | Catálogo de 4.795 registros de FCI; publicación del 29/10/2026 | Clasificación amplia y datos de catálogo; no composición, riesgo detallado, costos totales ni acceso personal |
| [State Street](https://www.ssga.com/us/en/individual/etfs/state-street-spdr-sp-500-etf-trust-spy) | Identidad SPY, ETF, NYSE ARCA y moneda de cotización USD mediante tabla del emisor | No se extraen precios ni se equipara moneda de cotización con exposición económica |
| [Comafi](https://www.comafi.com.ar/custodiaglobal/Programas-CEDEARs-2483.note.aspx) | Programa e ISIN de CEDEAR MELI; identidad separada del subyacente MELI en Nasdaq | No verifica por sí solo acceso vía broker ni cotización local; no conserva ratios como constantes |
| [YPF](https://inversores.ypf.com/faq.html) | Acción local YPFD y ADR YPF en mercados distintos | Sin precio, lote, costos ni relación ADR/acción fijada |
| [Bitcoin](https://bitcoin.org/es/faq) | Identidad del criptoactivo Bitcoin | Contenido educativo; política de asignación cripto deshabilitada |
| [Caja de Valores](https://cajadevalores.com.ar/Servicios/Cedears) | Identidad, ISIN y mercado BYMA del CEDEAR SPY en la tabla oficial; consulta en vivo verificada | Se usa el almacén de confianza de certifi con validación TLS habilitada; no acredita precio, costos ni acceso personal |
| [Fondos Fima](https://www.fondosfima.com.ar/es/personas/nuestros-fondos/plazo-fijo/fima-premium) | Identidad y mandato publicados de Fima Premium, Fima Renta en Pesos y Fima Capital Plus; contenido estructurado oficial `.model.json` | El mandato no equivale a composición actual. No se promueven mínimos genéricos del catálogo como condiciones verificadas de cada clase |

Los ejemplos SPY, MELI, YPF y BTC son casos de identificación y auditoría. No forman un universo completo de negociación ni tienen prioridad como ganadores. Los proveedores de identidad no aportan precios, lotes, costos o acceso suficientes para una recomendación operativa. Un estado `identity_observed` informa identidad, **no disponibilidad para negociar ni elegibilidad financiera**. Si falta evidencia obligatoria, se informa información insuficiente. Integrar una fuente de mercado adecuada y completar/revisar la política sigue pendiente para presentar recomendaciones financieras reales.

La comprobación de los adaptadores de identidad puede repetirse con `python scripts/check_instrument_sources.py`. El cliente CAFCI y su proveedor se prueban por separado con fixtures y consultas controladas. Las pruebas normales no dependen de Internet. Además del timeout, los adaptadores limitan el tamaño y las redirecciones. No se envían perfiles a las fuentes.

## Persistencia y revisiones

`instrument_knowledge.db` contiene fichas con versiones por identidad y eventos de feedback separados. Restaurar una ficha crea una versión nueva. Las correcciones marcan revisión y se conservan al volver a consultar; no pueden promover elegibilidad. El perfil personal no se almacena en esa base.

`historial.db` agrega la tabla `revisiones_investigacion`; la creación es aditiva y conserva las evaluaciones existentes. La inserción valida tanto las entradas como el hash del resultado de esa evaluación. La descarga desde sesión o historial incluye revisiones previas, sin modificar los porcentajes ni las entradas originales. Para conservar estos datos al reiniciar el hosting se necesita un `NEXUS_DATA_DIR` persistente.
