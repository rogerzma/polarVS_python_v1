"""
Interfaz de escritorio (Tkinter) para monitorear y registrar el Polar Verity Sense.
Requiere registrar_verity_sense.py en la misma carpeta.

    python app_verity_sense.py          # con la pulsera
    python app_verity_sense.py --demo   # datos simulados, para probar la interfaz sin pulsera
"""
import argparse
import asyncio
import math
import random
import threading
import time
import tkinter as tk
from collections import deque
from datetime import datetime
from pathlib import Path
from tkinter import ttk

from bleak import BleakScanner
from polar_python import PolarDevice
from polar_python.models import ACCData, GyroData, HRData, MAGData, PPGData, PPIData
from polar_python.models.mag_data import CalibrationStatus, MAGSample

from registrar_verity_sense import Registro, crear_callbacks

# ---------- Estilo (mismo esquema de colores del mockup de Android) ----------
AZUL, FONDO, TARJETA = "#1565C0", "#F0F0F0", "#FFFFFF"
VERDE, AMBAR, ROJO = "#2E7D32", "#F9A825", "#C62828"
TXT, TXT2 = "#212121", "#616161"

VENTANA_HRV_S = 60
MAX_ERROR_PPI_MS = 30


def hrv(intervalos):
    """RR medio, RMSSD, SDNN y pNN50 de una lista de intervalos en ms."""
    rr = [x for x in intervalos if 300 <= x <= 2000]
    if len(rr) < 2:
        return (rr[0] if rr else 0.0), 0.0, 0.0, 0.0, len(rr)
    media = sum(rr) / len(rr)
    sdnn = math.sqrt(sum((x - media) ** 2 for x in rr) / (len(rr) - 1))
    dif = [b - a for a, b in zip(rr, rr[1:])]
    rmssd = math.sqrt(sum(d * d for d in dif) / len(dif))
    pnn50 = 100.0 * sum(abs(d) > 50 for d in dif) / len(dif)
    return media, rmssd, sdnn, pnn50, len(rr)


class App:
    def __init__(self, root, demo=False):
        self.root, self.demo = root, demo
        self.lock = threading.Lock()
        self.v = {}                      # últimos valores recibidos
        self.ppi_win = deque()           # (t_monotonic, ppi_ms) válidos
        self.estado_txt, self.estado_col = "Desconectado", ROJO
        self.nombre = "—"
        self.csv = None                  # callbacks CSV mientras se graba
        self.reg = None
        self.t_ini_reg = 0.0
        self.worker = None
        self.salida = Path(__file__).parent / "datos"

        root.title("Polar Verity Sense Monitor")
        root.configure(bg=FONDO)
        alto = min(860, root.winfo_screenheight() - 90)
        root.geometry(f"900x{alto}")
        root.minsize(760, 420)
        self._ui()
        self.refrescar()
        root.protocol("WM_DELETE_WINDOW", self.cerrar)

    # ---------------- Interfaz ----------------
    def _tarjeta(self, padre, titulo, fila, col, span=1, bg=TARJETA):
        f = tk.Frame(padre, bg=bg, highlightbackground="#D0D0D0", highlightthickness=1)
        f.grid(row=fila, column=col, columnspan=span, sticky="nsew", padx=6, pady=6)
        tk.Label(f, text=titulo.upper(), bg=bg, fg=TXT2, font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=12, pady=(10, 4))
        cuerpo = tk.Frame(f, bg=bg)
        cuerpo.pack(fill="x", padx=12, pady=(0, 10))
        cuerpo.columnconfigure(1, weight=1)
        return cuerpo

    def _fila(self, cuerpo, i, etiqueta, clave):
        var = tk.StringVar(value="—")
        self.vars[clave] = var
        tk.Label(cuerpo, text=etiqueta, bg=cuerpo["bg"], fg="#424242", font=("Segoe UI", 11)).grid(row=i, column=0, sticky="w")
        tk.Label(cuerpo, textvariable=var, bg=cuerpo["bg"], fg=AZUL, font=("Segoe UI", 11, "bold")).grid(row=i, column=1, sticky="e")

    def _ui(self):
        self.vars = {}
        tk.Label(self.root, text="  Polar Verity Sense Monitor", bg=AZUL, fg="white",
                 font=("Segoe UI", 16, "bold"), anchor="w", height=2).pack(fill="x")

        # Barra de botones fija en la parte inferior (siempre visible)
        barra = tk.Frame(self.root, bg=FONDO)
        barra.pack(side="bottom", fill="x", padx=14, pady=(6, 12))
        self.b_con = ttk.Button(barra, text="Conectar", command=self.conectar)
        self.b_des = ttk.Button(barra, text="Desconectar", command=self.desconectar)
        self.b_ini = ttk.Button(barra, text="● Iniciar registro", command=self.iniciar_registro)
        self.b_fin = ttk.Button(barra, text="■ Detener registro", command=self.detener_registro)
        for b in (self.b_con, self.b_des, self.b_ini, self.b_fin):
            b.pack(side="left", padx=4)
        tk.Label(barra, text="● Monitoreo en tiempo real", bg=FONDO, fg=VERDE, font=("Segoe UI", 10)).pack(side="right")

        # Zona de tarjetas con scroll vertical
        cont = tk.Frame(self.root, bg=FONDO)
        cont.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(cont, bg=FONDO, highlightthickness=0)
        sb = ttk.Scrollbar(cont, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        malla = tk.Frame(self.canvas, bg=FONDO)
        ventana = self.canvas.create_window((0, 0), window=malla, anchor="nw")
        malla.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(ventana, width=e.width))
        self.root.bind_all("<MouseWheel>", lambda e: self.canvas.yview_scroll(-1 if e.delta > 0 else 1, "units"))
        self.root.bind_all("<Button-4>", lambda e: self.canvas.yview_scroll(-1, "units"))   # Linux
        self.root.bind_all("<Button-5>", lambda e: self.canvas.yview_scroll(1, "units"))    # Linux
        malla.columnconfigure((0, 1), weight=1, uniform="c")

        # Estado
        c = self._tarjeta(malla, "Estado", 0, 0, span=2, bg="#E8F5E9")
        self.lbl_estado = tk.Label(c, text="", bg="#E8F5E9", font=("Segoe UI", 14, "bold"))
        self.lbl_estado.grid(row=0, column=0, sticky="w")
        self.lbl_disp = tk.Label(c, text="", bg="#E8F5E9", fg=TXT2, font=("Segoe UI", 10))
        self.lbl_disp.grid(row=1, column=0, sticky="w")

        # FC + PPI
        c = self._tarjeta(malla, "Frecuencia cardiaca (PPG óptico)", 1, 0)
        self.vars["hr"] = tk.StringVar(value="--")
        caja = tk.Frame(c, bg=TARJETA)
        caja.grid(row=0, column=0, columnspan=2, sticky="w")
        tk.Label(caja, textvariable=self.vars["hr"], bg=TARJETA, fg=TXT, font=("Segoe UI", 36, "bold")).pack(side="left")
        tk.Label(caja, text=" bpm", bg=TARJETA, fg=TXT2, font=("Segoe UI", 11)).pack(side="left", anchor="s", pady=10)
        self._fila(c, 1, "Intervalo PPI (ms)", "ppi")
        self._fila(c, 2, "Error estimado PPI (ms)", "err")
        self._fila(c, 3, "Contacto con la piel", "contacto")

        # HRV
        c = self._tarjeta(malla, f"HRV · ventana de {VENTANA_HRV_S} s (desde PPI)", 1, 1)
        for i, (e, k) in enumerate([("RR medio", "mean"), ("RMSSD", "rmssd"), ("SDNN", "sdnn"),
                                    ("pNN50", "pnn50"), ("N.º de PPI válidos", "npp")]):
            self._fila(c, i, e, k)

        # Señales
        for (t, fila, col, filas) in [
            ("PPG (3 canales + ambiental)", 2, 0, [("PPG 0", "ppg0"), ("PPG 1", "ppg1"), ("PPG 2", "ppg2"), ("Ambient", "amb")]),
            ("Acelerómetro (mG)", 2, 1, [("X", "ax"), ("Y", "ay"), ("Z", "az")]),
            ("Giroscopio (°/s)", 3, 0, [("X", "gx"), ("Y", "gy"), ("Z", "gz")]),
            ("Magnetómetro (gauss)", 3, 1, [("X", "mx"), ("Y", "my"), ("Z", "mz")]),
        ]:
            c = self._tarjeta(malla, t, fila, col)
            for i, (e, k) in enumerate(filas):
                self._fila(c, i, e, k)

        # Registro
        c = self._tarjeta(malla, "Registro en CSV", 4, 0, span=2)
        tk.Label(c, text="ID participante:", bg=TARJETA).grid(row=0, column=0, sticky="w")
        self.ent_id = ttk.Entry(c, width=14)
        self.ent_id.grid(row=0, column=1, sticky="w", padx=8)
        self.lbl_reg = tk.Label(c, text="Sin registrar", bg=TARJETA, fg=TXT2, font=("Segoe UI", 10))
        self.lbl_reg.grid(row=1, column=0, columnspan=3, sticky="w", pady=(6, 0))
        self.lbl_cont = tk.Label(c, text="", bg=TARJETA, fg=TXT2, font=("Segoe UI", 10))
        self.lbl_cont.grid(row=2, column=0, columnspan=3, sticky="w")

    # ---------------- Estado ----------------
    def estado(self, texto, color):
        self.estado_txt, self.estado_col = texto, color

    @property
    def conectado(self):
        return self.estado_txt == "Conectado"

    # ---------------- Callbacks de datos (hilo BLE) ----------------
    def _csv(self, i, d):
        c = self.csv
        if c:
            try:
                c[i](d)
            except ValueError:   # archivo cerrado justo al detener
                pass

    def on_hr(self, d: HRData):
        with self.lock:
            self.v["hr"] = d.heartrate
        self._csv(0, d)

    def on_ppi(self, d: PPIData):
        ahora = time.monotonic()
        with self.lock:
            for s in d.samples:
                self.v["ppi"], self.v["err"], self.v["contacto"] = s.ppi, s.error_estimate, s.skin_contact_status
                if not s.invalid_ppi and s.skin_contact_status and s.error_estimate <= MAX_ERROR_PPI_MS:
                    self.ppi_win.append((ahora, float(s.ppi)))
        self._csv(1, d)

    def on_ppg(self, d: PPGData):
        if d.samples:
            ch = list(d.samples[-1]) + [None] * 4
            with self.lock:
                self.v.update(ppg0=ch[0], ppg1=ch[1], ppg2=ch[2], amb=ch[3])
        self._csv(2, d)

    def on_acc(self, d: ACCData):
        if d.data:
            with self.lock:
                self.v.update(ax=d.data[-1][0], ay=d.data[-1][1], az=d.data[-1][2])
        self._csv(3, d)

    def on_gyro(self, d: GyroData):
        if d.data:
            with self.lock:
                self.v.update(gx=d.data[-1][0], gy=d.data[-1][1], gz=d.data[-1][2])
        self._csv(4, d)

    def on_mag(self, d: MAGData):
        if d.data:
            s = d.data[-1]
            with self.lock:
                self.v.update(mx=s.x, my=s.y, mz=s.z)
        self._csv(5, d)

    # ---------------- Conexión ----------------
    def conectar(self):
        if self.worker and self.worker.is_alive():
            return
        self.v.clear(); self.ppi_win.clear()
        self.worker = threading.Thread(target=self._hilo_demo if self.demo else self._hilo_ble, daemon=True)
        self.stop_evt = threading.Event()
        self.worker.start()

    def desconectar(self):
        self.detener_registro()
        if self.worker:
            self.stop_evt.set()

    def _hilo_ble(self):
        asyncio.run(self._ble())

    async def _ble(self):
        try:
            self.estado("Buscando dispositivo...", AMBAR)
            dev = await BleakScanner.find_device_by_filter(
                lambda bd, ad: bd.name and "sense" in bd.name.lower(), timeout=15)
            if dev is None:
                self.estado("Sin dispositivo encontrado", ROJO)
                return
            self.nombre = dev.name
            self.estado("Conectando...", AMBAR)
            async with PolarDevice(dev) as p:
                await p.start_hr_stream(hr_callback=self.on_hr)
                await p.start_ppi_stream(ppi_callback=self.on_ppi)
                await p.start_ppg_stream(ppg_callback=self.on_ppg, sample_rate=55, resolution=22, channels=4)
                await p.start_acc_stream(acc_callback=self.on_acc, sample_rate=52, resolution=16, range=8, channels=3)
                await p.start_gyro_stream(gyro_callback=self.on_gyro, sample_rate=52, resolution=16, range=2000, channels=3)
                await p.start_mag_stream(mag_callback=self.on_mag, sample_rate=50, resolution=16, range=50, channels=3)
                self.estado("Conectado", VERDE)
                while not self.stop_evt.is_set():
                    await asyncio.sleep(0.2)
            self.estado("Desconectado", ROJO)
        except Exception as e:
            self.estado(f"Error: {e}", ROJO)

    def _hilo_demo(self):
        """Datos simulados con las mismas clases que entrega polar-python."""
        self.nombre = "Polar Sense DEMO"
        self.estado("Conectado", VERDE)
        t0 = time.monotonic()
        while not self.stop_evt.is_set():
            t = time.monotonic() - t0
            ppi = int(830 + 40 * math.sin(t / 3) + random.randint(-15, 15))
            self.on_hr(HRData(heartrate=round(60000 / ppi), rr_intervals=[float(ppi)]))
            self.on_ppi(PPIData(timestamp=0, samples=[PPIData.PPISample(ppi, random.randint(5, 14), round(60000 / ppi), False, True, True)]))
            self.on_ppg(PPGData(timestamp=0, samples=[[410000 + random.randint(-900, 900), 398000 + random.randint(-900, 900),
                                                       405000 + random.randint(-900, 900), 1200 + random.randint(-30, 30)]],
                                type=PPGData.PPGType.PPG3_AMBIENT1))
            self.on_acc(ACCData(timestamp=0, data=[(random.randint(-20, 20), random.randint(20, 50), 1000 + random.randint(-8, 8))]))
            self.on_gyro(GyroData(timestamp=0, data=[(random.uniform(-1, 1), random.uniform(-1, 1), random.uniform(-1, 1))]))
            self.on_mag(MAGData(timestamp=0, data=[MAGSample(0.12, -0.31, 0.45, CalibrationStatus.OK)]))
            time.sleep(0.5)
        self.estado("Desconectado", ROJO)

    # ---------------- Registro ----------------
    def iniciar_registro(self):
        if not self.conectado or self.csv:
            return
        sujeto = self.ent_id.get().strip()
        nombre = f"{sujeto + '_' if sujeto else ''}sesion_{datetime.now():%Y%m%d_%H%M%S}"
        self.reg = Registro(self.salida / nombre)
        self.t_ini_reg = time.monotonic()
        self.csv = crear_callbacks(self.reg)

    def detener_registro(self):
        if self.csv:
            self.csv = None
            time.sleep(0.1)
            self.reg.cerrar()
            self.lbl_reg.config(text=f"Guardado en: {self.reg.carpeta}", fg=VERDE)

    # ---------------- Refresco de pantalla ----------------
    def refrescar(self):
        ahora = time.monotonic()
        with self.lock:
            while self.ppi_win and ahora - self.ppi_win[0][0] > VENTANA_HRV_S:
                self.ppi_win.popleft()
            datos = dict(self.v)
            media, rmssd, sdnn, pnn50, n = hrv([x for _, x in self.ppi_win])

        fmt = {"hr": "{}", "ppi": "{}", "err": "{}", "ax": "{} mg", "ay": "{} mg", "az": "{} mg",
               "gx": "{:.2f}", "gy": "{:.2f}", "gz": "{:.2f}", "mx": "{:.2f}", "my": "{:.2f}", "mz": "{:.2f}"}
        for k, var in self.vars.items():
            if k in datos and datos[k] is not None:
                val = datos[k]
                if k == "contacto":
                    var.set("Sí" if val else "No")
                else:
                    var.set(fmt.get(k, "{}").format(val))
        if n:
            self.vars["mean"].set(f"{media:.0f} ms"); self.vars["rmssd"].set(f"{rmssd:.1f} ms")
            self.vars["sdnn"].set(f"{sdnn:.1f} ms");  self.vars["pnn50"].set(f"{pnn50:.1f} %")
        self.vars["npp"].set(str(n))

        self.lbl_estado.config(text=f"Estado: {self.estado_txt}", fg=self.estado_col)
        self.lbl_disp.config(text=f"Dispositivo: {self.nombre}")

        if self.csv:
            seg = int(ahora - self.t_ini_reg)
            self.lbl_reg.config(text=f"● Grabando en {self.reg.carpeta}  ({seg // 60:02d}:{seg % 60:02d})", fg=ROJO)
            self.lbl_cont.config(text="Filas: " + ", ".join(f"{k}={v}" for k, v in self.reg.conteo.items()))
        elif not self.reg:
            self.lbl_cont.config(text="")

        busy = self.worker is not None and self.worker.is_alive()
        self.b_con.state(["disabled"] if busy else ["!disabled"])
        self.b_des.state(["!disabled"] if busy else ["disabled"])
        self.b_ini.state(["!disabled"] if (self.conectado and not self.csv) else ["disabled"])
        self.b_fin.state(["!disabled"] if self.csv else ["disabled"])
        self.root.after(200, self.refrescar)

    def cerrar(self):
        self.desconectar()
        self.root.after(300, self.root.destroy)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true", help="datos simulados (sin pulsera)")
    args = ap.parse_args()
    raiz = tk.Tk()
    App(raiz, demo=args.demo)
    raiz.mainloop()