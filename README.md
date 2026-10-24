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
├── docs/                   # Alcance y casos del brief
├── tests/                  # Regresiones del flujo y motor
├── nexus/
│   ├── engine.py       # Hechos y reglas de Experta
│   ├── portfolio.py    # Reglas de asignación de cartera
│   ├── service.py      # Evaluación completa, independiente de Streamlit
│   ├── state.py        # Inicialización del estado de sesión
│   ├── validation.py   # Validaciones de entrada
│   ├── ui/
│   │   ├── common.py   # Componentes comunes
│   │   └── styles.css  # Estilos de la aplicación
│   └── views/          # Inicio, Perfil, Escenario, Revisión, Resultado y Auditoría
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

Las respuestas y los borradores se conservan al navegar durante la misma sesión de Streamlit. No hay almacenamiento permanente: recargar o cerrar el navegador puede iniciar una sesión nueva y perder los datos. El prototipo no implementa identificación de usuarios ni historial persistente.

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
- La aplicación conserva datos en la sesión de Streamlit; no implementa una base de datos para guardar perfiles permanentemente.
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


## 12. Ejemplos reales sin cuenta

Al abrir un resultado exitoso, NEXUS consulta una sola vez el catálogo público de FCI de **ArgentinaDatos**, desde la [publicación JSON del mismo proyecto en GitHub](https://raw.githubusercontent.com/enzonotario/argentinadatos.com/main/datos/v1/finanzas/fci/fondos/index.json). La [documentación del proveedor](https://argentinadatos.com/docs/operations/get-finanzas-fci-fondos) describe sus campos. No hacen falta credenciales. Se usa esta publicación porque el dominio de la API responde con una restricción de acceso desde este entorno; no se evade esa restricción ni se usa una copia local como si fuera una fuente vigente.

La consulta HTTP tiene timeout de 8 segundos y caché compartida de 15 minutos. Se exige fecha válida de publicación y del registro, no futura y de hasta 7 días calendario; esta ventana es un control de calidad del ejemplo, no un umbral del escenario macroeconómico. **Actualizar ejemplos** fuerza una consulta nueva. Si falla, se guarda el error de esa consulta y se ofrece reintentar, sin afectar la distribución ni repetir peticiones en cada interacción.

Una consulta fallida muestra un único aviso de conexión y permite reintentar. Cuando el catálogo responde, las alternativas disponibles se muestran abiertas; si no hay fondos compatibles, cada categoría explica los motivos de descarte y el monto usado para comparar la inversión mínima. Cambiar moneda o capital requiere editar el perfil y ejecutar otra evaluación; actualizar los ejemplos conserva las entradas originales.

Sólo aparecen categorías con asignación positiva. La clasificación y ambas monedas deben estar informadas; mínimos conocidos superiores al monto de la categoría quedan excluidos. Un mínimo ausente deja el fondo como alternativa sin compatibilidad verificada; mínimos inválidos se excluyen. El horizonte publicado es cualitativo: se muestra, pero no se inventa una equivalencia en meses.

- Renta variable: ejemplos con clasificación y moneda coincidentes, sin certificar idoneidad completa.
- Inflación: la renta fija genérica aparece sólo como alternativa; nombres comerciales no prueban ajuste CER/UVA.
- Cambiaria: un benchmark A3500 explícito prioriza alternativas para investigar, pero no verifica cobertura efectiva. La renta fija genérica tampoco prueba cobertura.
- Liquidez inmediata: los fondos de mercado de dinero son alternativas para revisar, incluso con liquidación T+0. No se promete rescate inmediato ni disponibilidad fuera de horarios de corte.

Se eligen hasta dos fondos diferentes por categoría en orden alfabético, priorizando A3500 en las alternativas cambiarias. No se ordena por rendimiento. La unidad de cuotaparte no está normalizada por NEXUS: su valor se identifica como reportado por la fuente y no se calculan cantidades a comprar.

La consulta queda dentro de `resultado_robo.ejemplos_instrumentos`, con hash de la ejecución, copia de las entradas originales, fechas, fuente, moneda, criterios y limitaciones. Resultado, auditoría y JSON conservan esa misma consulta aunque se edite el perfil. Una nueva evaluación genera otra consulta; actualizar los ejemplos no vuelve a ejecutar las reglas ni cambia sus porcentajes. La persistencia sigue limitada a la sesión.
