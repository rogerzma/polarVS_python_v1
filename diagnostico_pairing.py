"""
Diagnóstico de conexión y emparejamiento del Polar Verity Sense en Windows.

    python diagnostico_pairing.py "Polar Sense 236DD038"

Intenta, en orden: conectar -> emparejar desde código (bleak) -> activar las
notificaciones del canal PMD (la operación que fallaba con 'Insufficient Authentication').
Pega la salida completa para ver en qué paso falla.
"""
import asyncio
import sys

from bleak import BleakClient, BleakScanner

PMD_CONTROL = "FB005C81-02E7-F387-1CAD-8ACD2D8DF0C8"


async def probar_notify(client, etiqueta):
    try:
        await client.start_notify(PMD_CONTROL, lambda *_: None)
        await client.stop_notify(PMD_CONTROL)
        print(f"  [{etiqueta}] activar notificaciones PMD: OK")
        return True
    except Exception as e:
        print(f"  [{etiqueta}] activar notificaciones PMD: FALLÓ -> {e!r}")
        return False


async def main(nombre):
    print(f"Buscando '{nombre}' (15 s)...")
    dev = await BleakScanner.find_device_by_filter(
        lambda bd, ad: bd.name and nombre.lower() in bd.name.lower(), timeout=15)
    if dev is None:
        print("No se encontró. Despierta la pulsera y cierra otras apps que la usen.")
        return
    print(f"Encontrado: {dev.name}  {dev.address}")

    async with BleakClient(dev) as client:
        print(f"1) Conectado: {client.is_connected}")
        if await probar_notify(client, "sin emparejar"):
            print("\nYa funciona sin emparejar. El problema era otro; vuelve a correr la app.")
            return

        print("2) Intentando emparejar desde código...")
        try:
            await client.pair()
            print("  pair(): terminó sin error")
        except Exception as e:
            print(f"  pair(): FALLÓ -> {e!r}")

        if await probar_notify(client, "después de pair(), misma conexión"):
            print("\nListo: tras emparejar desde código funciona. Vuelve a correr la app.")
            return

    # En Windows el cifrado se aplica en la siguiente conexión y los servicios pueden estar en caché.
    print("3) Reconectando sin caché de servicios (espera 3 s)...")
    await asyncio.sleep(3)
    try:
        async with BleakClient(dev.address, winrt=dict(use_cached_services=False)) as client2:
            print(f"  Reconectado: {client2.is_connected}")
            if await probar_notify(client2, "reconexión sin caché"):
                print("\nFunciona tras reconectar. Se resuelve emparejando y conectando de nuevo.")
                return
    except Exception as e:
        print(f"  Reconexión FALLÓ -> {e!r}")

    print("\nSigue fallando. Pega esta salida completa para revisar el siguiente paso.")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "Sense"))