# Documentación técnica — Polar Verity Sense en PC

Índice

1. [Visión general](#1-visión-general)
2. [Arquitectura](#2-arquitectura)
3. [Módulo `registrar_verity_sense.py`](#3-módulo-registrar_verity_sensepy)
4. [Aplicación `app_verity_sense.py`](#4-aplicación-app_verity_sensepy)
5. [Formato de los archivos CSV](#5-formato-de-los-archivos-csv)
6. [Cálculo de HRV](#6-cálculo-de-hrv)
7. [Solución de problemas](#7-solución-de-problemas)
8. [Script `diagnostico_pairing.py`](#8-script-diagnostico_pairingpy)
9. [Análisis de los datos](#9-análisis-de-los-datos)
10. [Extender el proyecto](#10-extender-el-proyecto)

---

## 1. Visión general

El proyecto conecta una computadora con el **Polar Verity Sense** por BLE y recibe sus
*streams* de datos mediante el protocolo **PMD** (Polar Measurement Data) de Polar, a través
de la librería `polar-python` (que a su vez usa `bleak`).

Hay dos formas de uso que comparten la misma lógica de grabación:

- **Interfaz gráfica** (`app_verity_sense.py`): visualiza en vivo y graba bajo demanda.
- **Línea de comandos** (`registrar_verity_sense.py`): graba directamente, útil para sesiones
  largas o automatizadas.

## 2. Arquitectura

```
                 ┌──────────────────────────┐
  Verity Sense ──►  bleak (BLE)             │
     (PMD)       │   └─ polar_python        │
                 │       PolarDevice        │
                 └───────────┬──────────────┘
                             │ callbacks (HRData, PPIData, PPGData, ACCData, GyroData, MAGData)
              ┌──────────────┴───────────────┐
              ▼                              ▼
  registrar_verity_sense.py         app_verity_sense.py
   ├─ Registro (CSV)  ◄──────────── reutiliza Registro y crear_callbacks
   └─ crear_callbacks                ├─ hilo BLE (asyncio)  ─► valores en memoria (lock)
                                     └─ hilo Tkinter (refresco cada 200 ms)
```

### Configuración de los streams

Ambos programas inician los mismos streams con estos parámetros:

| Stream | Frecuencia | Resolución | Rango | Canales |
|--------|-----------:|-----------:|------:|--------:|
| HR     | —          | —          | —     | —       |
| PPI    | —          | —          | —     | —       |
| PPG    | 55 Hz      | 22 bits    | —     | 4 (3 PPG + ambiental) |
| ACC    | 52 Hz      | 16 bits    | 8 g   | 3       |
| GYRO   | 52 Hz      | 16 bits    | 2000 °/s | 3    |
| MAG    | 50 Hz      | 16 bits    | 50 G  | 3       |

Para consultar las configuraciones que admite tu sensor:

```powershell
python -m polar_python inspect --name "Polar Sense 236DD038"
```

Si cambias algún parámetro, debes hacerlo en **los dos archivos** (`main()` en
`registrar_verity_sense.py` y `_ble()` en `app_verity_sense.py`).

## 3. Módulo `registrar_verity_sense.py`

### `class Registro(carpeta: Path)`

Crea la carpeta de sesión y abre un CSV por señal, escribiendo la fila de encabezados
definida en `Registro.COLUMNAS`.

| Miembro | Descripción |
|---------|-------------|
| `COLUMNAS` | Diccionario `señal -> lista de columnas` |
| `carpeta` | Ruta de la sesión |
| `conteo` | Diccionario `señal -> filas escritas` |
| `fila(nombre, *valores)` | Escribe una fila en el CSV de la señal `nombre` |
| `cerrar()` | Hace `flush` y cierra todos los archivos |

### `crear_callbacks(reg: Registro)`

Devuelve una tupla de 6 funciones `(on_hr, on_ppi, on_ppg, on_acc, on_gyro, on_mag)` que
reciben los objetos de `polar-python` y los escriben en `reg`. Cada paquete se *desempaqueta*
en una fila por muestra; todas las muestras de un mismo paquete comparten `t_pc_ns` y
`t_sensor_ns`, y se distinguen con `idx` (posición dentro del paquete).

### `main(args)`

1. Busca durante 15 s un dispositivo BLE cuyo nombre contenga `--nombre` (sin distinguir mayúsculas).
2. Crea la carpeta `[<sujeto>_]sesion_AAAAMMDD_HHMMSS` dentro de `--salida`.
3. Conecta, inicia los 6 streams e imprime un resumen cada 5 s.
4. Al terminar (duración cumplida, Ctrl+C o error) cierra los archivos en el bloque `finally`,
   por lo que los datos recibidos hasta ese momento **no se pierden**.

## 4. Aplicación `app_verity_sense.py`

### Hilos

- **Hilo principal (Tkinter)**: dibuja la interfaz y ejecuta `refrescar()` cada 200 ms.
- **Hilo de trabajo**: ejecuta `asyncio.run(self._ble())` (o `_hilo_demo()` en modo `--demo`).
  Los callbacks guardan el último valor de cada señal en `self.v` protegidos con `self.lock`.

La interfaz **nunca** toca Tkinter desde el hilo BLE; solo lee `self.v` y `self.estado_txt`
en `refrescar()`.

### Estados de conexión

`Desconectado` → `Buscando dispositivo...` → `Conectando...` → `Conectado`
(o `Sin dispositivo encontrado` / `Error: ...`).

### Registro

- **Iniciar registro**: crea un `Registro` en `datos/` (junto al script) y activa los callbacks
  de CSV (`self.csv`). El ID del participante se usa como prefijo de la carpeta.
- **Detener registro**: desactiva los callbacks, espera 100 ms y cierra los archivos.
- Desconectar o cerrar la ventana detiene el registro automáticamente.

### Modo demo

`python app_verity_sense.py --demo` genera, cada 0.5 s, datos simulados con las **mismas
clases** de `polar-python` (`HRData`, `PPIData`, ...). Sirve para probar la interfaz y la
grabación sin pulsera; los CSV generados tienen el mismo formato que los reales.

### Constantes ajustables

| Constante | Valor | Uso |
|-----------|------:|-----|
| `VENTANA_HRV_S` | 60 | Segundos de PPI usados para calcular HRV |
| `MAX_ERROR_PPI_MS` | 30 | Error estimado máximo para aceptar un PPI |

## 5. Formato de los archivos CSV

Convenciones comunes:

- Codificación UTF-8, separador `,`, primera fila = encabezados.
- `t_pc_ns`: hora de la PC (`time.time_ns()`, nanosegundos desde la época Unix, UTC) en el momento
  en que **llegó el paquete**. Úsala para alinear señales entre sí y con otros equipos.
- `t_sensor_ns`: marca de tiempo que el sensor asigna al paquete (reloj interno del Verity Sense,
  en nanosegundos). Útil para medir intervalos con precisión, no para hora absoluta.
- `idx`: índice de la muestra dentro del paquete (0, 1, 2, ...).

### `hr.csv`

| Columna | Unidad | Descripción |
|---------|--------|-------------|
| `t_pc_ns` | ns | Hora de la PC |
| `hr_bpm` | bpm | Frecuencia cardiaca |
| `rr_ms` | ms | Intervalos RR separados por `;` (puede venir vacío) |

### `ppi.csv`

| Columna | Unidad | Descripción |
|---------|--------|-------------|
| `t_pc_ns`, `t_sensor_ns` | ns | Tiempos |
| `ppi_ms` | ms | Intervalo pico a pico |
| `error_ms` | ms | Error estimado del intervalo |
| `hr_bpm` | bpm | FC asociada al intervalo |
| `ppi_invalido` | 0/1 | 1 = el sensor marcó el PPI como no válido |
| `contacto_piel` | 0/1 | 1 = hay contacto con la piel |
| `contacto_soportado` | 0/1 | 1 = el sensor soporta detección de contacto |

> El stream PPI suele tardar unos segundos en empezar a enviar datos tras conectar.

### `ppg.csv`

| Columna | Descripción |
|---------|-------------|
| `t_pc_ns`, `t_sensor_ns`, `idx` | Tiempos e índice |
| `ppg0`, `ppg1`, `ppg2` | Canales ópticos (valor crudo, sin unidad) |
| `ambient` | Canal de luz ambiental |

### `acc.csv` / `gyro.csv` / `mag.csv`

| Archivo | Columnas de datos | Unidad |
|---------|-------------------|--------|
| `acc.csv`  | `x_mg`, `y_mg`, `z_mg` | mG (1000 mG ≈ 1 g) |
| `gyro.csv` | `x_dps`, `y_dps`, `z_dps` | °/s (4 decimales) |
| `mag.csv`  | `x_gauss`, `y_gauss`, `z_gauss`, `calibracion` | gauss; `calibracion` = estado de calibración reportado por el sensor |

## 6. Cálculo de HRV

La interfaz calcula, sobre los PPI de los últimos `VENTANA_HRV_S` segundos, la función `hrv()`:

**Filtro de PPI aceptados** (en `on_ppi`):
`ppi_invalido == False` **y** `contacto_piel == True` **y** `error_ms <= 30`.
Además, `hrv()` descarta intervalos fuera de **300–2000 ms** (≈ 30–200 bpm).

| Métrica | Fórmula |
|---------|---------|
| RR medio | media de los intervalos |
| SDNN | desviación estándar muestral (n − 1) de los intervalos |
| RMSSD | √(media de (RRᵢ₊₁ − RRᵢ)²) |
| pNN50 | % de diferencias sucesivas con \|Δ\| > 50 ms |

> Estos valores son orientativos para monitoreo. Para análisis formales, procesa `ppi.csv`
> fuera de línea (ver sección 9) con limpieza de artefactos adecuada.

## 7. Solución de problemas

| Síntoma | Causa probable | Qué hacer |
|---------|----------------|-----------|
| "No se encontró" / "Sin dispositivo encontrado" | Sensor dormido, conectado a otro equipo o Bluetooth apagado | Ponte la pulsera o presiona su botón; cierra Polar Flow/Beat y desconéctala del celular; verifica el Bluetooth de la PC |
| Se conecta a otro sensor | Hay varios "Sense" cerca | Usa `--nombre` con el ID del sensor (p. ej. `--nombre 236DD038`) |
| `Insufficient Authentication` al iniciar streams | Windows exige emparejamiento cifrado para el canal PMD | Ejecuta `diagnostico_pairing.py`; si no basta, empareja la pulsera en *Configuración → Bluetooth* de Windows y vuelve a intentar |
| Error tras emparejar/desemparejar | Caché de servicios GATT de Windows | Quita el dispositivo en Configuración de Windows, reinicia el Bluetooth y vuelve a emparejar |
| PPI vacío o con muchos `ppi_invalido = 1` | Movimiento, mal contacto o pulsera floja | Ajusta la banda, permanece quieto; espera unos segundos tras conectar |
| CSV con solo encabezados | La sesión se cortó antes de recibir datos | Revisa la salida de la consola / estado de la app |
| La ventana no cabe en la pantalla | Resolución baja | La zona de tarjetas tiene scroll (rueda del ratón); los botones quedan fijos abajo |

## 8. Script `diagnostico_pairing.py`

```powershell
python diagnostico_pairing.py "Polar Sense 236DD038"
```

Pasos que ejecuta y cómo interpretarlos:

1. **Conectar y activar notificaciones PMD sin emparejar.** Si funciona, el problema no es el emparejamiento.
2. **`client.pair()` desde código** y volver a probar en la misma conexión.
3. **Reconectar sin caché de servicios** (`use_cached_services=False`), porque en Windows el
   cifrado suele aplicarse hasta la siguiente conexión.

Si los tres pasos fallan, guarda la salida completa para revisarla.

## 9. Análisis de los datos

Ejemplo con `pandas` (no incluido en `requirements.txt`):

```python
import pandas as pd

ses = "datos/S01_sesion_20261119_152540"
ppi = pd.read_csv(f"{ses}/ppi.csv")
acc = pd.read_csv(f"{ses}/acc.csv")

# Hora legible a partir del reloj de la PC
for df in (ppi, acc):
    df["t"] = pd.to_datetime(df["t_pc_ns"], unit="ns", utc=True)

# PPI válidos
ok = ppi[(ppi.ppi_invalido == 0) & (ppi.contacto_piel == 1) & (ppi.error_ms <= 30)]
print(ok.ppi_ms.describe())

# Alinear aceleración con PPI por tiempo de la PC
alineado = pd.merge_asof(ok.sort_values("t"), acc.sort_values("t"), on="t", direction="nearest")
```

## 10. Extender el proyecto

- **Agregar o quitar una señal**: modifica `Registro.COLUMNAS`, añade el callback en
  `crear_callbacks()` y el `start_*_stream` correspondiente en ambos programas. En la app,
  mantén el mismo orden de índices en `_csv(i, d)`.
- **Cambiar frecuencias**: verifica primero con `python -m polar_python inspect` y actualiza
  la tabla de la sección 2.
- **Buenas prácticas de datos**: no subas `datos/` al repositorio (ya está en `.gitignore`);
  usa IDs anónimos de participante (`S01`, `S02`, ...).
