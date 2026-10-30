# NEXUS | Simulador de carteras

Prototipo académico de un sistema experto para evaluar un perfil inversor, analizar un escenario macroeconómico ingresado manualmente y generar una distribución ilustrativa de cartera. Está construido con Python, Streamlit y Experta.

> **Aviso:** NEXUS funciona en modo demostración. Consulta un catálogo público de FCI para mostrar ejemplos; el escenario sigue siendo manual y no hay cotizaciones ni indicadores en tiempo real. Sus resultados no constituyen asesoramiento financiero personalizado.

## 1. Requisitos

- Python instalado.
- `pip` disponible desde la terminal.
- Conexión a Internet para instalar dependencias y consultar el catálogo público de instrumentos. La tipografía web es opcional; el motor sigue funcionando si falla la fuente externa.

## 2. Archivos del proyecto

El código está organizado por responsabilidad para mantener separadas la interfaz y las reglas de negocio:

```text
nexus-simulador-carteras/
├── app.py
├── .streamlit/config.toml  # Tema nativo oscuro
├── config/matriz_decision.json  # Matriz de decisión inicial (versión 1)
├── data/                   # Generada en ejecución: historial.db y versiones (no versionar)
├── docs/                   # Alcance y casos del brief
├── tests/                  # Regresiones del flujo y motor
├── nexus/
│   ├── engine.py       # Hechos y reglas de Experta
│   ├── matrices.py     # RF-08: carga, validación y versionado de la matriz
│   ├── history.py      # RF-09: historial de evaluaciones en SQLite
│   ├── portfolio.py    # Reglas de asignación de cartera
│   ├── service.py      # Evaluación completa, independiente de Streamlit
│   ├── state.py        # Inicialización del estado de sesión
│   ├── validation.py   # Validaciones de entrada
│   ├── ui/
│   │   ├── common.py   # Componentes comunes
│   │   └── styles.css  # Estilos de la aplicación
│   └── views/          # Inicio, Perfil, Escenario, Revisión, Resultado, Auditoría, Historial y Administración
└── README.md
```

El `README.md` documenta el proyecto y cómo usarlo; no es necesario para ejecutar la aplicación.

## 3. Instalación

Para clonar el repositorio privado, usá una cuenta con acceso:

```bash
git clone https://github.com/agusteira/nexus-simulador-carteras.git
cd nexus-simulador-carteras
```

Abrí una terminal dentro de la carpeta del proyecto y ejecutá:

```bash
python -m pip install -r requirements.txt
```

Si en tu sistema el comando `python` no funciona, probá con `py` en Windows:

```bash
py -m pip install -r requirements.txt
```

## 4. Ejecutar la aplicación

Desde la carpeta que contiene `app.py`, ejecutá:

```bash
python -m streamlit run app.py
```

En Windows también podés probar:

```bash
py -m streamlit run app.py
```

Streamlit mostrará una dirección local en la terminal (normalmente `http://localhost:8501`). Abrila en el navegador.

En este equipo, el entorno local ya preparado se inicia desde PowerShell con:

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py
```

## 5. Cómo utilizar NEXUS

El recorrido principal tiene cuatro pasos, con acciones para avanzar y volver. La auditoría está disponible desde el resultado y en las opciones del menú lateral.

### Inicio

Elegí **Comenzar simulación** o retomá el trabajo de la sesión. El escenario es simulado; al generar un resultado exitoso se consulta una publicación pública de fondos. No se envían solicitudes a un asesor.

### Paso 1 — Tu perfil

Ingresá capital y moneda, horizonte en meses, objetivo, tolerancia a una caída temporal y liquidez mínima. El capital empieza vacío. Los demás valores iniciales son editables. Los ejemplos monetarios ayudan a interpretar los porcentajes; no son pronósticos ni garantías.

Elegí **Guardar perfil y continuar**. Los errores de formato o valores faltantes se muestran en este paso. Una combinación que requiere revisión manual puede conservarse para obtener la explicación del motor.

### Paso 2 — Escenario

Podés empezar con uno de los cuatro ejemplos ficticios y luego ajustar las señales: inflación, presión cambiaria y volatilidad elevadas. Los ejemplos no representan el mercado actual. Ninguna señal marcada significa “sin alertas en esta simulación”, no que el mercado real esté estable.

La casilla confirma que comprendés que el escenario es manual y simulado. Para compatibilidad con la interfaz del servicio original, la confirmación se transmite en `mercado_actualizado`; **no es una comprobación de vigencia real**. La procedencia de la simulación se identifica por separado en el estado de sesión. Luego elegí **Guardar escenario y revisar**.

### Paso 3 — Revisar datos

Verificá el perfil y el escenario guardados; podés volver a editarlos. Si hay cambios en borrador sin guardar, deben resolverse antes de ejecutar, para evitar evaluar otras entradas por accidente.

Elegí **Ejecutar evaluación**. Este es el único paso que ejecuta el motor.

### Paso 4 — Resultado

Consultá la distribución, importes y motivos de la última evaluación. Si cambiaste entradas o dejaste borradores pendientes, la salida anterior se identifica como desactualizada hasta volver a evaluar. Sus importes y descargas siguen correspondiendo a las entradas de aquella ejecución.

Podés editar el perfil, simular otro escenario, consultar la auditoría y descargar JSON. Si el motor deriva el caso a revisión manual, la pantalla explica el motivo y ofrece una ruta de corrección; **no significa que se haya contactado o asignado un asesor real**.

### Conservación de datos

Las respuestas y los borradores se conservan al navegar durante la misma sesión de Streamlit. Cada evaluación y sus revisiones de investigación también se guardan en SQLite en el servidor (sección 14). Los borradores no guardados pueden perderse al recargar. El identificador de usuario es una etiqueta de consulta; no implementa autenticación ni aislamiento entre usuarios.

## 6. ¿Qué significa “DERIVADO_ASESOR_MANUAL”?

Es un estado de control: el prototipo no genera una asignación cuando detecta una condición que sus reglas consideran inválida, inconsistente o incompleta.

Entre las causas contempladas por el código están:
- Capital igual o menor que cero.
- Horizonte de inversión igual o menor que cero.
- Valores de tolerancia al riesgo o liquidez fuera del rango permitido.
- No confirmar el escenario de simulación.
- Tolerancia a pérdidas del 0 % junto con el objetivo **Crecimiento**.
- Inferencia incompleta o una asignación que no cumple las reglas de distribución.

**La confirmación corresponde al ejercicio simulado.** No comprueba cotizaciones, fuentes externas ni antigüedad de indicadores.

## 7. Descargar resultados

En la pantalla Resultado, la aplicación permite descargar la última salida como JSON, incluyendo la consulta de ejemplos y sus fechas cuando esté disponible. La sección Auditoría también permite exportar la traza disponible. Estos archivos se generan al descargarlos; no hace falta crearlos antes de iniciar la aplicación.

## 8. Dependencias

Las dependencias principales usadas por el código son:
- `streamlit`: interfaz web.
- `experta`: motor de reglas del sistema experto.

Los módulos `json`, `datetime` y `pathlib` pertenecen a la biblioteca estándar de Python.

## 9. Limitaciones conocidas

- El catálogo externo puede estar incompleto o no disponible; no hay cotizaciones en tiempo real ni elegibilidad financiera completa.
- El escenario de mercado se ingresa manualmente.
- Las asignaciones son ilustrativas y se basan en reglas determinísticas definidas en el código.
- El historial (SQLite) y las versiones de la matriz se guardan en `data/`, en el disco del servidor. En Streamlit Community Cloud ese disco es efímero: se pierde al reiniciar o redesplegar la app.
- El prototipo no debe utilizarse como asesoramiento financiero real.

## 10. Solución de problemas

### `streamlit` no se reconoce como comando
Ejecutá la aplicación con:

```bash
python -m streamlit run app.py
```

### Falta el módulo `experta` o `streamlit`
Instalá las dependencias de nuevo:

```bash
python -m pip install -r requirements.txt
```

### Aparece `ERR_DATOS_MERCADO_NO_DISPONIBLES`
Entrá en **Escenario**, revisá el ejercicio simulado y confirmá su naturaleza manual antes de guardar. La UI impide avanzar sin esa confirmación; el servicio mantiene el código de error original para otras entradas.

### La aplicación indica que faltan datos
Guardá primero **Tu perfil** y después **Escenario**. En **Revisar datos**, verificá las entradas y ejecutá la evaluación.

---

**NEXUS · Simulador de carteras · Prototipo académico · Modo demostración**

## 11. Verificación y alcance del brief

Ejecutá las pruebas desde el entorno que contiene Streamlit y Experta:

```bash
python -m unittest discover -s tests -v
```

Las pruebas cubren el recorrido, borradores, restauración de respuestas, resultados desactualizados, errores controlados y diez casos de regresión del motor. Los casos y las funciones pendientes del brief se documentan en [docs/validacion-brief.md](docs/validacion-brief.md). Su aprobación por el docente o asesor sigue pendiente; una prueba técnica no certifica idoneidad financiera ni cumplimiento regulatorio.


## 12. Universo de candidatos y selección

Al abrir un resultado exitoso, NEXUS consulta una vez el [catálogo público de CAFCI](https://estadisticas.cafci.org.ar/consulta-avanzada). El adaptador normaliza fondos y clases abiertos con identificadores, moneda, mínimo, plazo de liquidación, mandato y honorarios desglosados. Investiga las fichas oficiales por ID de fondo y clase. No fija ganadores por nombre, marca ni ticker. El cliente de ArgentinaDatos se conserva para compatibilidad con consultas anteriores y pruebas inyectadas.

La consulta de catálogo tiene timeout de 8 segundos y caché de 15 minutos. Se exige una publicación fechada y vigente. Cada composición conserva su propia fecha: consultar hoy una ficha no convierte sus tenencias históricas en actuales. **Actualizar investigación** crea una revisión; navegar no repite consultas ni altera la distribución.

La pantalla conserva las tres pestañas de distribución, instrumentos e interpretación. Los paneles empiezan cerrados. En el esquema de investigación 3, solo `category.selected` genera tarjetas y debe coincidir con una evaluación elegible del motor, sin faltantes obligatorios. Las referencias informativas de esquemas anteriores requieren actualización explícita; su JSON histórico permanece intacto.

Se compara el pool completo por categoría antes de acotar las consultas. Se preserva la evaluación del primer candidato de la API para explicar una conservación o sustitución. Se ordenan candidatos elegibles por las reglas; la familiaridad solo puede desempatar después de los factores financieros y operativos. Un candidato desconocido puede ganar si sus datos y restricciones lo justifican.

- Un mandato CER o dollar-linked orienta la investigación; no acredita por sí solo exposición efectiva.
- Los honorarios anuales publicados se conservan con su desglose. No equivalen a un costo operativo en pesos.
- T+0 y una marca de liquidez no prueban disponibilidad inmediata ni horarios de rescate.
- El acceso de mercado es una declaración opcional del perfil. No confirma oferta o habilitación de un intermediario concreto.

Si faltan hechos exigidos por la política, el resultado es **información insuficiente**: no se rellena la categoría con una ficha conocida. La cobertura actual de CAFCI aporta hechos parciales y no completa costos efectivos, exposición económica ni acceso por broker. Las referencias de identidad de acciones/CEDEARs tampoco aportan un universo de precios y negociación. Por ello, esta integración todavía no constituye un recomendador financiero listo para uso real. La revisión experta de las reglas sigue pendiente.

La consulta queda dentro de `resultado_robo.ejemplos_instrumentos`, con hash de la ejecución, copia de las entradas originales, fechas, fuente, moneda, criterios y limitaciones. Resultado, auditoría y JSON conservan esa misma consulta aunque se edite el perfil. Una nueva evaluación genera otra consulta; actualizar los ejemplos no vuelve a ejecutar las reglas ni cambia sus porcentajes. Cada actualización añade una revisión al historial SQLite, sin sobrescribir la evaluación original.


## 13. Matrices de decisión configurables (RF-08)

Los umbrales de perfil, las carteras base, los topes por clase de activo, las reglas de ajuste por escenario y su prioridad se leen en cada evaluación desde la versión activa de la matriz. La versión 1 es `config/matriz_decision.json` y reproduce exactamente las reglas originales.

Desde el menú lateral, **Más opciones → Administración de matrices**, se editan los valores, se indica responsable y motivo y se guarda una **versión nueva** (no se sobrescriben las anteriores). La tabla de historial muestra número, fecha, responsable y nota; cualquier versión anterior se puede ver en JSON y **restaurar**, lo que crea otra versión nueva con su contenido. Las versiones se guardan en `data/matrices_versiones.json`. Cada resultado incluye `version_matriz`.

Si se define la variable de entorno o el secreto `NEXUS_ADMIN_CLAVE`, la pantalla pide esa clave; sin ella funciona en modo demo. Las categorías de activos son fijas porque los ejemplos de instrumentos dependen de ellas. El orden de retiro para cubrir la liquidez mínima (`orden_retiro_liquidez`) sólo se edita en el JSON.

## 14. Historial de evaluaciones (RF-09)

El perfil tiene un **identificador de usuario** opcional (vacío = `anonimo`). Cada evaluación ejecutada se guarda en `data/historial.db` (SQLite) con entradas, escenario, resultado, asignación, traza, errores, versión de la matriz y fecha.

En **Más opciones → Historial de evaluaciones** se filtra por usuario (sin distinguir mayúsculas) y rango de fechas, se abre el detalle completo con su traza y su JSON descargable, y se comparan dos evaluaciones lado a lado con las diferencias por categoría. La variable `NEXUS_DATA_DIR` permite cambiar la carpeta de datos; las pruebas la usan para no tocar `data/`.

## 15. Investigación y conocimiento de instrumentos (issue #1)

La consulta agrega `ejemplos_instrumentos.investigacion`: candidato inicial, alternativas, exclusiones, reglas, evidencia por campo, faltantes y versiones de política, universo y fichas. Primero se aplican exclusiones; solo los candidatos elegibles se ordenan por criterios operativos y diversificación conocida. La familiaridad educativa actúa después y nunca elimina una exclusión. No hay un puntaje de “mejor inversión” ni se usan rendimientos recientes.

El universo curado distingue SPY exterior y su CEDEAR, MELI exterior y su CEDEAR, acción local YPFD y ADR YPF, Bitcoin directo y un fondo con exposición a Bitcoin. Cada ficha conserva mercado, vehículo y subyacente; no se comparten precios ni unidades. Las fuentes oficiales verifican identidad y los campos que efectivamente publican. No prueban condiciones del broker, costos totales, liquidez inmediata ni disponibilidad para operar. IBIT permanece como propuesta educativa sin proveedor habilitado. BTC y sus vehículos no reciben asignación.

La investigación tiene límites configurables mediante `ResearchLimits`: seis fuentes de referencia, dieciséis segundos de presupuesto y veinte candidatos por categoría por defecto; cada solicitud tiene timeout de hasta cuatro segundos. La consulta inicial de FCI tiene su propio timeout de ocho segundos. La caché HTTP dura quince minutos; **Actualizar investigación** fuerza una nueva revisión y permite reintentar. Los fallos quedan registrados sin sustituir datos desconocidos por supuestos. Solo se consultan URLs fijas permitidas; no se envían respuestas personales a proveedores.

La política provisional `config/instrument_policy.json` hace intervenir horizonte y objetivo en la asignación, con topes explícitos y trazas. **Su revisión experta está pendiente**: ningún resultado se presenta como compatibilidad financiera validada. Reglas, prioridades, umbrales y limitaciones: [política educativa](docs/instrument-policy.md).

Las fichas y evidencias se guardan en `data/instrument_knowledge.db` con versiones, vencimiento e historial. `KnowledgeStore.history` y `restore` permiten consultar y restaurar creando una versión nueva. Un instrumento nuevo sigue como propuesta hasta completar sus verificaciones. Las señales **Entendí**, **Ya lo conocía** y **Señalar un dato** se registran por separado: una corrección obliga a revisión futura y ninguna señal cambia por sí sola las reglas de riesgo. Es reutilización de conocimiento, no entrenamiento automático.

Los arrays legados se conservan en el JSON y no generan tarjetas. `educational_selection` queda como proyección de compatibilidad del mismo `selected`; no existe una segunda selección con requisitos menores. BTC y los vehículos sin política de asignación permanecen en la auditoría; el resultado no agrega una biblioteca independiente. Consultá el [flujo y la cobertura de fuentes](docs/instrument-research.md).
