"""
Registro de señales del Polar Verity Sense desde una computadora (BLE) con Python.

Guarda un CSV por señal (HR, PPI, PPG, ACC, GYRO, MAG) en una carpeta de sesión.
Cada fila lleva dos tiempos:
  - t_pc_ns:     hora de la computadora al llegar el dato (para alinear señales entre sí)
  - t_sensor_ns: marca de tiempo que reporta el sensor para ese paquete

Uso:
    python registrar_verity_sense.py                    # hasta Ctrl+C
    python registrar_verity_sense.py --duracion 300     # 5 minutos
    python registrar_verity_sense.py --sujeto S01 --salida datos
"""
import argparse
import asyncio
import csv
import time
from datetime import datetime
from pathlib import Path

from bleak import BleakScanner
from polar_python import PolarDevice

class Registro:
    """Abre un CSV por señal y escribe filas con el tiempo de la PC."""

    COLUMNAS = {
        "hr":   ["t_pc_ns", "hr_bpm", "rr_ms"],
        "ppi":  ["t_pc_ns", "t_sensor_ns", "ppi_ms", "error_ms", "hr_bpm",
                 "ppi_invalido", "contacto_piel", "contacto_soportado"],
        "ppg":  ["t_pc_ns", "t_sensor_ns", "idx", "ppg0", "ppg1", "ppg2", "ambient"],
        "acc":  ["t_pc_ns", "t_sensor_ns", "idx", "x_mg", "y_mg", "z_mg"],
        "gyro": ["t_pc_ns", "t_sensor_ns", "idx", "x_dps", "y_dps", "z_dps"],
        "mag":  ["t_pc_ns", "t_sensor_ns", "idx", "x_gauss", "y_gauss", "z_gauss", "calibracion"],
    }

    def __init__(self, carpeta: Path):
        carpeta.mkdir(parents=True, exist_ok=True)
        self.carpeta = carpeta
        self._archivos = {}
        self._writers = {}
        self.conteo = {k: 0 for k in self.COLUMNAS}
        for nombre, cols in self.COLUMNAS.items():
            f = open(carpeta / f"{nombre}.csv", "w", newline="", encoding="utf-8")
            w = csv.writer(f)
            w.writerow(cols)
            self._archivos[nombre] = f
            self._writers[nombre] = w

    def fila(self, nombre, *valores):
        self._writers[nombre].writerow(valores)
        self.conteo[nombre] += 1

    def cerrar(self):
        for f in self._archivos.values():
            f.flush()
            f.close()


def crear_callbacks(reg: Registro):
    def on_hr(d):
        reg.fila("hr", time.time_ns(), d.heartrate, ";".join(f"{r:.1f}" for r in d.rr_intervals))

    def on_ppi(d):
        t = time.time_ns()
        for s in d.samples:
            reg.fila("ppi", t, d.timestamp, s.ppi, s.error_estimate, s.hr,
                     int(s.invalid_ppi), int(s.skin_contact_status), int(s.skin_contact_supported))

    def on_ppg(d):
        t = time.time_ns()
        for i, s in enumerate(d.samples):
            canales = list(s) + [""] * (4 - len(s))
            reg.fila("ppg", t, d.timestamp, i, *canales[:4])

    def on_acc(d):
        t = time.time_ns()
        for i, (x, y, z) in enumerate(d.data):
            reg.fila("acc", t, d.timestamp, i, x, y, z)

    def on_gyro(d):
        t = time.time_ns()
        for i, (x, y, z) in enumerate(d.data):
            reg.fila("gyro", t, d.timestamp, i, f"{x:.4f}", f"{y:.4f}", f"{z:.4f}")

    def on_mag(d):
        t = time.time_ns()
        for i, s in enumerate(d.data):
            reg.fila("mag", t, d.timestamp, i, f"{s.x:.4f}", f"{s.y:.4f}", f"{s.z:.4f}", s.calibration_status.name)

    return on_hr, on_ppi, on_ppg, on_acc, on_gyro, on_mag


async def main(args):
    print(f"Buscando un dispositivo Polar con '{args.nombre}' en el nombre...")
    dispositivo = await BleakScanner.find_device_by_filter(
        lambda bd, ad: bd.name and args.nombre.lower() in bd.name.lower(), timeout=15
    )
    if dispositivo is None:
        print("No se encontró. Revisa que la pulsera esté puesta (o presiona su botón), "
              "que el Bluetooth de la PC esté activo y que no esté conectada a otra app o al celular.")
        return

    sesion = f"sesion_{datetime.now():%Y%m%d_%H%M%S}"
    if args.sujeto:
        sesion = f"{args.sujeto}_{sesion}"
    reg = Registro(Path(args.salida) / sesion)
    on_hr, on_ppi, on_ppg, on_acc, on_gyro, on_mag = crear_callbacks(reg)

    print(f"Encontrado: {dispositivo.name}. Conectando...")
    try:
        async with PolarDevice(dispositivo) as polar:
            # Configuraciones soportadas por la Verity Sense según la documentación de polar-python.
            # Verifícalas en tu equipo con:  python -m polar_python inspect --name "<nombre>"
            await polar.start_hr_stream(hr_callback=on_hr)
            await polar.start_ppi_stream(ppi_callback=on_ppi)
            await polar.start_ppg_stream(ppg_callback=on_ppg, sample_rate=55, resolution=22, channels=4)
            await polar.start_acc_stream(acc_callback=on_acc, sample_rate=52, resolution=16, range=8, channels=3)
            await polar.start_gyro_stream(gyro_callback=on_gyro, sample_rate=52, resolution=16, range=2000, channels=3)
            await polar.start_mag_stream(mag_callback=on_mag, sample_rate=50, resolution=16, range=50, channels=3)

            print(f"Registrando en: {reg.carpeta}")
            print("Presiona Ctrl+C para terminar." if not args.duracion else f"Duración: {args.duracion} s")
            inicio = time.monotonic()
            while args.duracion == 0 or time.monotonic() - inicio < args.duracion:
                await asyncio.sleep(5)
                resumen = ", ".join(f"{k}:{v}" for k, v in reg.conteo.items())
                print(f"  [{int(time.monotonic() - inicio):>4} s] filas -> {resumen}")
    finally:
        reg.cerrar()
        print(f"Archivos guardados en {reg.carpeta}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Registro de señales del Polar Verity Sense")
    p.add_argument("--duracion", type=int, default=0, help="segundos a registrar (0 = hasta Ctrl+C)")
    p.add_argument("--salida", default="datos", help="carpeta donde se guardan las sesiones")
    p.add_argument("--nombre", default="Sense", help="texto que debe contener el nombre del dispositivo")
    p.add_argument("--sujeto", default="", help="identificador opcional del participante, p. ej. S01")
    try:
        asyncio.run(main(p.parse_args()))
    except KeyboardInterrupt:
        print("\nInterrumpido por el usuario.")