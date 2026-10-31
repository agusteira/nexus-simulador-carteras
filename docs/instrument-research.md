# Investigación de instrumentos: de dónde salen los datos

Después de calcular los porcentajes, NEXUS busca opciones para cada grupo de la cartera. Esta búsqueda no cambia el reparto ni calcula cuántos instrumentos comprarías. Si un dato necesario no aparece, se conserva como desconocido; no se interpreta como cero ni se completa por intuición.

### Busca opciones

NEXUS consulta listas y datos públicos de fondos y valores. CAFCI aporta información publicada por fondos, como su clase, patrimonio y composición. BYMADATA muestra ofertas y cantidades observadas en el mercado. La búsqueda puede ser limitada y no representa todo lo que existe.

### Comprueba los datos

El sistema revisa si los datos corresponden al instrumento y siguen dentro del plazo que acepta la regla. Una composición de fondo incluye la fecha en que se publicó. Puede describir una cartera pasada, aunque sea reciente; no confirma las tenencias de hoy. Una cotización observada puede tener demora y no es una operación realizada.

### Muestra qué puede sostener

Si los datos cumplen las condiciones, NEXUS puede mostrar una opción y explicar qué hechos la respaldan. Si falta un dato necesario, lo deja sin confirmar. Un valor desconocido no equivale a cero; por ejemplo, un costo no publicado no significa que sea gratis. Una identidad conocida tampoco demuestra que el fondo invierta hoy en un activo determinado.

Hasta dos opciones de un mismo grupo usan el mismo monto de la cartera. La segunda es una alternativa para ese monto, no una inversión adicional. Las fuentes no confirman si tu intermediario ofrece el instrumento ni si una orden se puede ejecutar.

### Guarda esta consulta

Cada consulta guarda lo que se buscó, qué fuente respondió, las fechas, las decisiones y los límites de búsqueda. Actualizar la consulta crea una revisión nueva y deja intactos los porcentajes y el resultado anterior. La política completa y el [glosario](glosario.md) explican términos como FCI, cuotaparte, liquidez y CEDEAR.

La comprobación de cobertura que sigue corresponde al **30/10/2026**; los conteos son de esa revisión y no describen el estado actual de las fuentes.

<details>
<summary>Cobertura, contratos y persistencia técnica</summary>

## Flujo técnico y límites

## Flujo

1. Se consultan en paralelo CAFCI (catálogo y planilla diaria) y BYMADATA público (panel general y CEDEARs). ArgentinaDatos y `build_examples` se conservan por compatibilidad histórica.
2. Los registros se normalizan y pasan por las reglas educativas versionadas.
3. Si faltan candidatos, la búsqueda se amplía dentro de un universo curado pequeño y limitado por consultas, tiempo y cantidad de resultados.
4. Solo se consultan referencias HTTPS fijas. Al proveedor se envía un registro normalizado; nunca el perfil ni el escenario personal.
5. Las tres pestañas conservan la UI previa. La pestaña de instrumentos muestra solo la selección del motor (`selected`) cuando coincide con una evaluación elegible, sin campos obligatorios faltantes. Las categorías empiezan cerradas y las exclusiones permanecen en el detalle. Cada resultado mantiene `expert_review: pending`.
6. Las señales de conocimiento y corrección se guardan para contexto futuro. Una corrección marca revisión; no modifica hechos de mercado.
7. Actualizar una investigación añade una revisión inmutable al historial. La evaluación original queda intacta.

## Límites y evidencia

La búsqueda usa `ResearchLimits` (12 consultas de fichas, 24 segundos y 12 candidatos por categoría). Los catálogos tienen hasta seis solicitudes HTTP separadas de ocho segundos, con hasta dos páginas por panel BYMA. Se recorre el pool completo antes de limitar fichas; se agrupan clases del mismo fondo y se consultan candidatos por turnos entre categorías. Los datos faltantes de una fuente permanecen desconocidos.

El esquema 4 (`ARGENTINA_SIN_BROKER`) selecciona instrumentos con la política `argentina-4`. Se conserva el evaluador estricto anterior, mientras `instrument_recommendations.py` separa la selección del instrumento de los hechos pendientes de una orden (`execution_checks`). La comisión de un broker desconocido no bloquea por sí sola la selección, ni se interpreta como cero. `educational_selection` es una proyección exacta del mismo `selected`, sin selección paralela. La familiaridad no interviene en el ranking. No se priorizan familias ni tickers.

Para CER/FX se exige mayoría estricta corroborada en renglones explícitos de una composición con fecha de hasta 35 días. El porcentaje identificado es una inferencia registrada, no evidencia observada nueva ni garantía de cobertura actual. Para MM se controla clasificación y rescate T+0; no se promete disponibilidad 24/7. CAFCI diario aporta Calificado, patrimonio y VCP por mil: este último no se transforma en precio por unidad. Gastos de administración se comparan como porcentajes anuales, sin confundirlos con cargos de una orden.

BYMADATA no informa fecha de último negocio en los paneles consultados. Se conservan ofertas indicativas con la hora UTC de observación y una vigencia de observación de 15 minutos; `unit_price` y `quote_data_date` siguen desconocidos. Las fichas técnicas verifican el tipo/representación y se mantienen separados CEDEAR y subyacente. La norma documentada de unidad CEDEAR no se extrapola a acciones ni bonos. Se dejan sin selección los tipos o montos cuya evidencia necesaria no está completa.

Las consultas guardadas con el esquema anterior no se reinterpretan como selecciones. La interfaz pide actualizarlas y conserva el JSON original. El resultado no agrega una biblioteca de Bitcoin ni otros instrumentos sin asignación.

Cada `investigacion` conserva `execution_id`, versiones de política y universo, entradas originales, categorías evaluadas, decisiones, fuentes observadas, reglas, errores y límites aplicados. `ejemplos_instrumentos` mantiene el resultado previo de los ejemplos legados y agrega esta investigación.

Las fichas separan campos observados, contenido curado y `explanation` (plantilla educativa versionada). Las fuentes respaldan campos concretos: ni una descripción ni una marca conocida prueban que el fondo tenga CER, cobertura cambiaria o disponibilidad inmediata. Los candidatos nuevos ingresan como propuestas. No hay agente que ejecute instrucciones de páginas externas ni entrenamiento de modelos.

## Cobertura comprobada

Verificación controlada del 30/10/2026 (Buenos Aires), mediante solicitudes públicas de lectura y TLS verificado:

| Fuente | Cobertura observada | Límite |
| --- | --- | --- |
| [BYMADATA público](https://open.bymadata.com.ar/) | Panel general y CEDEARs: 966 registros ARS/USD normalizados en la comprobación; ofertas, cantidades, monto negociado y ficha técnica por símbolo | Referencias con demora, sin fecha del último negocio. No prueban ejecución ni precio final; se preservan los lotes desconocidos y no se infiere exposición equity de un ETF/cripto por su ticker |
| [CAFCI](https://estadisticas.cafci.org.ar/consulta-avanzada) | Catálogo público: 1.209 fondos con clases abiertas y 4.818 registros normalizados en la verificación; mínimos por clase, mandato, plazos y honorarios desglosados. Fichas con composición y fecha explícita | La composición comprobada era del 09/10/2026. No prueba tenencias de hoy ni costos efectivos, moneda de suscripción, exposición económica o acceso por broker. Los honorarios no se convierten en comisiones en pesos |
| [ArgentinaDatos](https://raw.githubusercontent.com/enzonotario/argentinadatos.com/main/datos/v1/finanzas/fci/fondos/index.json) | Catálogo de 4.795 registros de FCI; publicación del 29/10/2026 | Clasificación amplia y datos de catálogo; no composición, riesgo detallado, costos totales ni acceso personal |
| [State Street](https://www.ssga.com/us/en/individual/etfs/state-street-spdr-sp-500-etf-trust-spy) | Identidad SPY, ETF, NYSE ARCA y moneda de cotización USD mediante tabla del emisor | No se extraen precios ni se equipara moneda de cotización con exposición económica |
| [Comafi](https://www.comafi.com.ar/custodiaglobal/Programas-CEDEARs-2483.note.aspx) | Programa e ISIN de CEDEAR MELI; identidad separada del subyacente MELI en Nasdaq | No verifica por sí solo acceso vía broker ni cotización local; no conserva ratios como constantes |
| [YPF](https://inversores.ypf.com/faq.html) | Acción local YPFD y ADR YPF en mercados distintos | Sin precio, lote, costos ni relación ADR/acción fijada |
| [Bitcoin](https://bitcoin.org/es/faq) | Identidad del criptoactivo Bitcoin | Contenido educativo; política de asignación cripto deshabilitada |
| [Caja de Valores](https://cajadevalores.com.ar/Servicios/Cedears) | Identidad, ISIN y mercado BYMA del CEDEAR SPY en la tabla oficial; consulta en vivo verificada | Se usa el almacén de confianza de certifi con validación TLS habilitada; no acredita precio, costos ni acceso personal |
| [Fondos Fima](https://www.fondosfima.com.ar/es/personas/nuestros-fondos/plazo-fijo/fima-premium) | Identidad y mandato publicados de Fima Premium, Fima Renta en Pesos y Fima Capital Plus; contenido estructurado oficial `.model.json` | El mandato no equivale a composición actual. No se promueven mínimos genéricos del catálogo como condiciones verificadas de cada clase |

Los ejemplos SPY, MELI, YPF y BTC son casos de identificación y auditoría y no tienen prioridad como ganadores. Los valores de mercado se descubren en el panel público, y los fondos en CAFCI. Un estado `identity_observed` informa identidad, no confirma que una cuenta pueda operar. La selección del simulador no sustituye la revisión experta pendiente ni la confirmación de una orden con el intermediario.

La comprobación de los adaptadores de identidad puede repetirse con `python scripts/check_instrument_sources.py`. El cliente CAFCI y su proveedor se prueban por separado con fixtures y consultas controladas. Las pruebas normales no dependen de Internet. Además del timeout, los adaptadores limitan el tamaño y las redirecciones. No se envían perfiles a las fuentes.

## Persistencia y revisiones

`instrument_knowledge.db` contiene fichas con versiones por identidad y eventos de feedback separados. Restaurar una ficha crea una versión nueva. Las correcciones marcan revisión y se conservan al volver a consultar; no pueden promover elegibilidad. El perfil personal no se almacena en esa base.

`historial.db` agrega la tabla `revisiones_investigacion`; la creación es aditiva y conserva las evaluaciones existentes. La inserción valida tanto las entradas como el hash del resultado de esa evaluación. La descarga desde sesión o historial incluye revisiones previas, sin modificar los porcentajes ni las entradas originales. Para conservar estos datos al reiniciar el hosting se necesita un `NEXUS_DATA_DIR` persistente.

</details>
