# Política educativa de instrumentos

La versión `educational-1` es una regla determinista de cribado y compatibilidad operativa. **No está validada por especialistas**, no certifica elegibilidad financiera y no constituye asesoramiento ni recomendación personalizada. `expert_review` permanece `pending`.

## Orden de decisión

| Prioridad | Resultado | Regla |
| --- | --- | --- |
| 1 | Requiere revisión | Contradicciones entre fuentes o valores numéricos imposibles/ inválidos. |
| 2 | Excluir candidato | Cripto/BTC, categoría o moneda incompatible, presupuesto mínimo insuficiente, acceso no disponible, riesgo incompatible, solapamiento o liquidación fuera del horizonte. |
| 3 | Información insuficiente | Identidad, datos operativos, moneda económica o evidencia observada faltante, vencida o futura. |
| 4 | Conservar candidato | Solo con requisitos verificables completos y sin una exclusión conocida. |

Las contradicciones y datos numéricos inválidos requieren revisión; luego prevalecen las exclusiones conocidas sobre los campos faltantes para no ocultar incompatibilidades. Una cadena descriptiva o estado `validated` no sustituye evidencia: cada valor operativo requerido debe coincidir con un campo de evidencia observada que incluya fuente, URL HTTPS, fecha de observación con zona horaria y no futura, y vencimiento posterior a la observación. Los datos de identidad admiten fecha de datos ausente y se validan con antigüedad de observación de hasta 30 días; no se inventa una fecha de publicación. Los datos financieros requieren fecha de datos vigente: información de FCI hasta 7 días y precio de acciones, ADR, CEDEAR y ETF de hoy o del día anterior. Los FCI no requieren precio por unidad. Una fuente curada puede aportar contexto, pero no prueba elegibilidad.

## Umbrales ilustrativos

- Criptoactivos y cualquier vehículo con exposición `bitcoin` quedan excluidos.
- La renta variable queda excluida con perfil conservador, tolerancia cero, objetivo `Preservacion` o horizonte inferior a 36 meses. Para el horizonte, la asignación agregada se limita a 0% antes de 12 meses y 20% entre 12 y 35 meses; para preservación, a 10%. El excedente se mueve a liquidez inmediata. No se cambia la matriz base ni se aumenta riesgo por objetivo `Crecimiento` o `Renta`.
- Una necesidad de liquidez de 50% o más requiere liquidación acreditada como `immediate` y liquidación en cero días. `daily` y T+0 no prueban disponibilidad inmediata.
- Los instrumentos de la categoría liquidez inmediata requieren siempre `immediate` y liquidación cero. La búsqueda también debe declarar moneda objetivo y lista de accesos permitidos; no se asumen.
- El presupuesto se compara con el mayor entre mínimo y lote por precio, más costos conocidos. No se calcula cantidad a comprar.
- Duplicados de subyacente o tenencias identificadas en común se excluyen por solapamiento. La familiaridad solo desempata después de riesgo, operación, diversificación y costos; no usa métricas de rendimiento.
- La concentración muestra valor, peso sumado y estado `known`/`unknown` por emisor, sector, país y subyacente, con procedencia de evidencia fresca. Solo se aplican topes educativos cuando tanto los datos como los pesos están acreditados: emisor 50%, sector 75% y país 100%. El país de cotización/listado no se interpreta como país de exposición: requiere rol explícito `economic_exposure`. Para un FCI, la administradora no se cuenta como emisor económico; se necesita `issuer_role` respaldado como `economic_issuer` o `issuer`. Las tenencias solo mejoran la señal de diversificación si hay evidencia fresca de al menos dos subyacentes distintos.

Los límites y umbrales son decisiones educativas provisionales y deben revisarse externamente antes de cualquier uso real. Los registros con concentración o tenencias desconocidas no reciben afirmaciones de diversificación. No se asume que dos listados de mercados distintos tengan el mismo precio o identidad.

## Identificadores auditables

Las reglas registran todas las causas aplicables. La prioridad del resultado es revisión → exclusión → información insuficiente → elegibilidad; ordenar por familiaridad solo ocurre después de esa decisión.

| Regla | Condición y resultado |
| --- | --- |
| `R_CONTRADICCION` | Fuentes vigentes discrepan sobre un campo o la ficha está en revisión: `REQUIERE_REVISION`. |
| `R_DATO_NUMERICO_INVALIDO` | Mínimo, costo, plazo, lote o precio inválido, negativo o no finito: revisión. Lote/precio cero también es inválido. |
| `R_CATEGORY_EXPOSURE_CONTRADICTION` | Categoría y exposición declaradas se contradicen: revisión. |
| `R_CRYPTO_POLICY` | Criptoactivo o cualquier vehículo con exposición Bitcoin: exclusión mientras no exista política validada de asignación. |
| `R_CATEGORIA_INCOMPATIBLE` | Categoría explícita distinta de la categoría investigada: exclusión. Categoría desconocida no prueba incompatibilidad ni compatibilidad. |
| `R_MONEDA_INCOMPATIBLE` | Cotización/suscripción explícitas incompatibles entre sí o con la moneda original: exclusión. La exposición económica se evalúa por separado. |
| `R_PRESUPUESTO_MINIMO` | Presupuesto menor que mínimo, lote × precio o el mayor de ambos más costos conocidos: exclusión; costos desconocidos no levantan una exclusión que ya prueba una cota inferior. |
| `R_ACCESO_INCOMPATIBLE` | Acceso requerido fuera de la lista operativa conocida: exclusión. Falta de lista deja información insuficiente. |
| `R_PERFIL_EQUITY`, `R_TOLERANCIA_EQUITY` | Renta variable con perfil conservador o tolerancia cero: exclusión. |
| `R_HORIZONTE_EQUITY`, `R_OBJETIVO_PRESERVACION` | Renta variable antes de 36 meses o con objetivo preservación: exclusión del instrumento, conservando la distribución ilustrativa. |
| `R_LIQUIDEZ_INMEDIATA` | La categoría de liquidez o necesidad ≥50% exige disponibilidad inmediata y plazo cero; una condición conocida contraria excluye. T+0 por sí solo no acredita disponibilidad. |
| `R_PLAZO_LIQUIDACION` | Plazo conocido superior a horizonte × 30 días: exclusión. Es una aproximación de cribado educativo, no un calendario de liquidaciones. |
| `R_OVERLAP` | Subyacente o tenencias respaldadas coinciden con una elección previa: exclusión por solapamiento; duplicados permanecen en la traza. |
| `R_CONCENTRACION_EMISOR`, `R_CONCENTRACION_SECTOR`, `R_CONCENTRACION_PAIS` | Exposición hipotética respaldada y pesos conocidos superiores a 50%, 75% o 100% respectivamente: exclusión. El país debe representar exposición económica. No se confunde administradora de FCI con emisor de sus tenencias. |
| `R_EVIDENCIA_INSUFICIENTE` | Campos, contexto, autorización operativa o evidencia válida faltantes: se documentan los faltantes y se impide seleccionar sin una exclusión prioritaria. |
| `R_ELEGIBLE_EDUCATIVO` | Sin exclusiones ni faltantes obligatorios: conservar bajo la política educativa. No certifica idoneidad financiera. |
| `R_ALTERNATIVA_COMPATIBLE` | Otro candidato elegible supera al inicial o este fue excluido: proponer alternativa con comparación explícita. |
| `R_SIN_CANDIDATO_AMPLIAR` | Aún no hay elegibles y queda búsqueda compatible disponible: ampliar. El coordinador registra la ampliación y termina en información insuficiente/revisión si se agotan sus fuentes o límites. |
| `R_ASIGNACION_HORIZONTE`, `R_ASIGNACION_OBJETIVO` | Aplicar topes agregados configurados, mover excedente a liquidez y registrar porcentajes antes/después. Actualizar investigación nunca vuelve a aplicar estos ajustes. |
