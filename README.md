# Polar Verity Sense en PC (Python)

Herramientas en Python para **monitorear y registrar** las señales del sensor óptico
**Polar Verity Sense** desde una computadora vía **Bluetooth Low Energy (BLE)**, sin
necesidad del celular ni de la app de Polar.

Señales que se capturan:

| Señal | Descripción | Configuración |
|-------|-------------|---------------|
| HR    | Frecuencia cardiaca (bpm) | — |
| PPI   | Intervalo pico a pico (ms), base para HRV | — |
| PPG   | Fotopletismografía cruda: 3 canales + luz ambiental | 55 Hz, 22 bits |
| ACC   | Acelerómetro 3 ejes (mG) | 52 Hz, ±8 g |
| GYRO  | Giroscopio 3 ejes (°/s) | 52 Hz, ±2000 °/s |
| MAG   | Magnetómetro 3 ejes (gauss) | 50 Hz, ±50 G |

## Contenido del repositorio

| Archivo | Para qué sirve |
|---------|----------------|
| [app_verity_sense.py](app_verity_sense.py) | Interfaz gráfica (Tkinter): monitoreo en tiempo real, HRV y registro a CSV |
| [registrar_verity_sense.py](registrar_verity_sense.py) | Registro desde línea de comandos (sin interfaz) |
| [diagnostico_pairing.py](diagnostico_pairing.py) | Diagnóstico de conexión/emparejamiento en Windows |
| [requirements.txt](requirements.txt) | Dependencias de Python |
| [docs/DOCUMENTACION.md](docs/DOCUMENTACION.md) | Documentación técnica detallada |

## Requisitos

- Python **3.10 o superior** (probado con 3.11.5).
- Computadora con **Bluetooth 4.0+ (BLE)** activo. Probado en Windows 11.
- Un **Polar Verity Sense** con batería, puesto en el brazo (o "despierto" presionando su botón).
- Que la pulsera **no esté conectada a otra app** (Polar Flow, Polar Beat, el celular, etc.):
  BLE solo admite una conexión de datos a la vez.

## Instalación

```powershell
# 1. Clonar el repositorio
git clone <url-del-repositorio>
cd PolarVeritySensePC

# 2. Crear y activar un entorno virtual
python -m venv env
.\env\Scripts\Activate.ps1        # Windows (PowerShell)
# source env/bin/activate          # Linux / macOS

# 3. Instalar dependencias
pip install -r requirements.txt
```

> Si PowerShell bloquea el script de activación, ejecuta una vez
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

## Uso rápido

### 1. Interfaz gráfica (recomendado)

```powershell
python app_verity_sense.py          # con la pulsera
python app_verity_sense.py --demo   # datos simulados, para probar sin pulsera
```

1. Presiona **Conectar**: busca durante 15 s un dispositivo cuyo nombre contenga "Sense".
2. Cuando el estado diga **Conectado**, verás FC, PPI, HRV (ventana de 60 s), PPG, ACC, GYRO y MAG.
3. (Opcional) Escribe el **ID del participante**, p. ej. `S01`.
4. **Iniciar registro** / **Detener registro** para guardar los CSV en `datos/`.
5. **Desconectar** o cerrar la ventana al terminar.

### 2. Línea de comandos

```powershell
python registrar_verity_sense.py                          # registra hasta Ctrl+C
python registrar_verity_sense.py --duracion 300           # 5 minutos
python registrar_verity_sense.py --sujeto S01 --salida datos
python registrar_verity_sense.py --nombre "236DD038"      # elegir un sensor concreto
```

| Opción | Valor por defecto | Descripción |
|--------|-------------------|-------------|
| `--duracion` | `0` | Segundos a registrar (`0` = hasta Ctrl+C) |
| `--salida`   | `datos` | Carpeta donde se crean las sesiones |
| `--nombre`   | `Sense` | Texto que debe contener el nombre BLE del sensor |
| `--sujeto`   | *(vacío)* | Prefijo con el ID del participante |

Cada 5 s imprime cuántas filas lleva cada señal.

### 3. Diagnóstico de emparejamiento (Windows)

Si al conectar aparece un error como `Insufficient Authentication`:

```powershell
python diagnostico_pairing.py "Polar Sense 236DD038"
```

El script prueba conectar, emparejar desde código y reconectar sin caché, e indica en qué paso falla.
Ver [Solución de problemas](docs/DOCUMENTACION.md#7-solución-de-problemas).

## Datos generados

Cada registro crea una carpeta de sesión:

```
datos/
└── S01_sesion_20261119_152540/
    ├── hr.csv
    ├── ppi.csv
    ├── ppg.csv
    ├── acc.csv
    ├── gyro.csv
    └── mag.csv
```

Todas las filas incluyen `t_pc_ns` (hora de la PC en nanosegundos, para alinear señales) y,
cuando aplica, `t_sensor_ns` (marca de tiempo del sensor). El detalle de columnas está en
[docs/DOCUMENTACION.md](docs/DOCUMENTACION.md#5-formato-de-los-archivos-csv).

> La carpeta `datos/` está en `.gitignore`: los registros de participantes **no** deben subirse al repositorio.

## Dependencias

- [`polar-python`](https://pypi.org/project/polar-python/) — protocolo PMD de Polar (streams de datos).
- [`bleak`](https://pypi.org/project/bleak/) — Bluetooth Low Energy multiplataforma.
- `tkinter` — incluido con Python (solo para la interfaz gráfica).

## Documentación

Arquitectura, formato de datos, cálculo de HRV y solución de problemas:
**[docs/DOCUMENTACION.md](docs/DOCUMENTACION.md)**.
