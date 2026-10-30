# Investigación educativa de instrumentos

La investigación de instrumentos es una capa educativa y de solo lectura sobre la simulación de cartera. No modifica asignaciones, no calcula cantidades ni rendimientos futuros, y no convierte una señal de familiaridad en una recomendación.

## Flujo

1. Se conserva el catálogo de fondos y la salida histórica de `build_examples`.
2. Los registros se normalizan y pasan por las reglas educativas versionadas.
3. Si faltan candidatos, la búsqueda se amplía dentro de un universo curado pequeño y limitado por consultas, tiempo y cantidad de resultados.
4. Solo se consultan referencias HTTPS fijas. Al proveedor se envía un registro normalizado; nunca el perfil ni el escenario personal.
5. La interfaz muestra decisiones, reglas, evidencia, datos faltantes y riesgos. Cada resultado mantiene `expert_review: pending`.
6. Las señales de conocimiento y corrección se guardan para contexto futuro. Una corrección marca revisión; no modifica hechos de mercado.
7. Actualizar una investigación añade una revisión inmutable al historial. La evaluación original queda intacta.

## Límites y evidencia

La búsqueda usa `ResearchLimits` (4 consultas, 12 segundos y 20 resultados por categoría por defecto). Una fuente sin datos no se interpreta como confirmación negativa. FCI puede confirmar algunos metadatos, pero no acredita por sí solo exposición económica, costos, acceso, liquidez ni condiciones de rescate. Un valor desconocido se muestra como tal y las reglas lo excluyen de una selección operativa.

Cada `investigacion` conserva `execution_id`, versiones de política y universo, entradas originales, categorías evaluadas, decisiones, fuentes observadas, reglas, errores y límites aplicados. `ejemplos_instrumentos` mantiene el resultado previo de los ejemplos legados y agrega esta investigación.

Las fichas separan campos observados, contenido curado y `explanation` (plantilla educativa versionada). Las fuentes respaldan campos concretos: ni una descripción ni una marca conocida prueban que el fondo tenga CER, cobertura cambiaria o disponibilidad inmediata. Los candidatos nuevos ingresan como propuestas. No hay agente que ejecute instrucciones de páginas externas ni entrenamiento de modelos.

## Cobertura comprobada

Verificación controlada del 29/10/2026 (Buenos Aires), mediante solicitudes públicas de lectura y TLS verificado:

| Fuente | Cobertura observada | Límite |
| --- | --- | --- |
| [ArgentinaDatos](https://raw.githubusercontent.com/enzonotario/argentinadatos.com/main/datos/v1/finanzas/fci/fondos/index.json) | Catálogo de 4.795 registros de FCI; publicación del 29/10/2026 | Clasificación amplia y datos de catálogo; no composición, riesgo detallado, costos totales ni acceso personal |
| [State Street](https://www.ssga.com/us/en/individual/etfs/state-street-spdr-sp-500-etf-trust-spy) | Identidad SPY, ETF, NYSE ARCA y moneda de cotización USD mediante tabla del emisor | No se extraen precios ni se equipara moneda de cotización con exposición económica |
| [Comafi](https://www.comafi.com.ar/custodiaglobal/Programas-CEDEARs-2483.note.aspx) | Programa e ISIN de CEDEAR MELI; identidad separada del subyacente MELI en Nasdaq | No verifica por sí solo acceso vía broker ni cotización local; no conserva ratios como constantes |
| [YPF](https://inversores.ypf.com/faq.html) | Acción local YPFD y ADR YPF en mercados distintos | Sin precio, lote, costos ni relación ADR/acción fijada |
| [Bitcoin](https://bitcoin.org/es/faq) | Identidad del criptoactivo Bitcoin | Contenido educativo; política de asignación cripto deshabilitada |
| [Caja de Valores](https://cajadevalores.com.ar/Servicios/Cedears) | Adaptador estructurado para el CEDEAR de SPY probado con fixture | El cliente HTTPS local rechazó la cadena del certificado. La comprobación en vivo queda fallida, sin relajar TLS ni declarar disponibilidad |

IBIT es una propuesta de vehículo con exposición a Bitcoin sin adaptador de referencia habilitado. Un estado `identity_observed` informa identidad, **no disponibilidad para negociar ni elegibilidad financiera**. Si una fuente falla, la ficha conserva `source_unavailable` y puede reintentarse explícitamente. El universo educativo muestra también las referencias no consultadas por agotamiento del presupuesto.

La comprobación puede repetirse voluntariamente con `python scripts/check_instrument_sources.py`. Emite JSON con estados, campos observados y límites; no consulta perfiles ni escribe conocimiento. Las pruebas normales usan fixtures y no dependen de Internet. Además del timeout, los adaptadores limitan el tamaño de respuesta y rechazan redirecciones fuera de sus URLs permitidas. Se probaron timeout, caída de fuente, formato cambiado, caché, vencimiento, reintento y redirección no confiable.

## Persistencia y revisiones

`instrument_knowledge.db` contiene fichas con versiones por identidad y eventos de feedback separados. Restaurar una ficha crea una versión nueva. Las correcciones marcan revisión y se conservan al volver a consultar; no pueden promover elegibilidad. El perfil personal no se almacena en esa base.

`historial.db` agrega la tabla `revisiones_investigacion`; la creación es aditiva y conserva las evaluaciones existentes. La inserción valida tanto las entradas como el hash del resultado de esa evaluación. La descarga desde sesión o historial incluye revisiones previas, sin modificar los porcentajes ni las entradas originales. Para conservar estos datos al reiniciar el hosting se necesita un `NEXUS_DATA_DIR` persistente.
