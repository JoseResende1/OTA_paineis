# ======================================================
# main.py — Arranque seguro + OTA + Controller
# ======================================================

import time
import rs485
from config import debug
import wifi
import ota
from controller import Controller


debug("[MAIN] Arranque do sistema...")


# ======================================================
# 1) Tentar WiFi → OTA automático no arranque
# ======================================================
debug("[MAIN] Tentativa de ligação WiFi...")

if wifi.connect(timeout_ms=15000):  # 15 segundos
    debug("[MAIN] WiFi OK → verificar OTA")

    try:
        updated = ota.try_ota_update()
        if updated:
            debug("[MAIN] OTA bem sucedida → reiniciar")
            time.sleep(1000)
            import machine
            machine.reset()
        else:
            debug("[MAIN] OTA: Nenhuma atualização disponível.")
    except Exception as e:
        debug("[MAIN] OTA falhou: " + str(e))
else:
    debug("[MAIN] Não foi possível ligar ao WiFi → ignorar OTA inicial")


# ======================================================
# 2) Iniciar o controller
# ======================================================
controller = Controller()

# Enviar heartbeat inicial com versão
rs485.send(f"HB-START,ADDR:{controller.addr},VER:{ota.local_version()}")
debug(f"[MAIN] Heartbeat inicial enviado: VER={ota.local_version()}")


# ======================================================
# 3) LOOP PRINCIPAL
# ======================================================
while True:

    # Executa um ciclo do controlador (botões, motor, RS485, etc)
    controller.loop_once()

    # Ler comandos RS485
    for line in rs485.read_lines():

        if not line:
            continue

        su = line.upper().strip()

        # COMANDO GLOBAL – Broadcast = 128
        if su.startswith("ADDR:128 OTA"):
            debug("[MAIN] OTA forçada via RS485 BROADCAST")

            if wifi.connect(timeout_ms=15000):
                try:
                    updated = ota.try_ota_update()
                    if updated:
                        debug("[MAIN] OTA RS485 → reiniciar")
                        time.sleep(1000)
                        import machine
                        machine.reset()
                    else:
                        debug("[MAIN] OTA RS485: Sem update")
                except Exception as e:
                    debug("[MAIN] OTA RS485 falhou: " + str(e))
            else:
                debug("[MAIN] OTA RS485: Falha WiFi")

    time.sleep_ms(20)
