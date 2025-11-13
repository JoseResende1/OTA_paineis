# main.py
import time
import machine
import rs485
import mcp23017
from controller import Controller
from wifi import wifi_connect
from ota import ota_update
from config import CONFIG, debug

VERSION_FILE = "version.json"

# ------------------------------------------------------------
# Ler versão atual
# ------------------------------------------------------------
def get_local_version():
    try:
        import ujson
        with open(VERSION_FILE, "r") as f:
            data = ujson.load(f)
            return data.get("version", "0.0.0")
    except:
        return "0.0.0"


# ------------------------------------------------------------
# Arranque principal
# ------------------------------------------------------------
debug("[MAIN] Arranque do sistema...")

# Tentativa WiFi
debug("[MAIN] Tentativa de ligação WiFi...")
ip = wifi_connect(timeout_ms=20000)

if ip:
    debug("[MAIN] WiFi OK → verificar OTA")
    ota_update()
else:
    debug("[MAIN] Sem WiFi — iniciar modo normal")

# Heartbeat inicial com versão
ver = get_local_version()
rs485.set_tx()
rs485.send(f"HB-START,ADDR:0,VER:{ver}")
rs485.set_rx()
debug("[MAIN] HB inicial enviado")

# Iniciar controlador
c = Controller()

# ------------------------------------------------------------
# Loop principal
# ------------------------------------------------------------
while True:
    # Loop único do controlador
    c.loop_once()

    # Verificar comandos RS485
    for line in rs485.read_lines():

        # Comando de OTA forçada
        if line.upper().startswith("ADDR:128 OTA"):
            debug("[MAIN] OTA forçada via RS485")
            ip = wifi_connect(timeout_ms=60000)
            if ip:
                ota_update()
            else:
                debug("[MAIN] WiFi falhou para OTA via RS485")

    time.sleep_ms(CONFIG["RS485_POLL_MS"])