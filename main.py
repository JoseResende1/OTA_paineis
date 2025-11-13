import wifi
import ota
import controller
import rs485
import time

print("[DBG] [MAIN] Arranque do sistema...")

print("[DBG] [MAIN] Tentativa de ligação WiFi...")
wifi.connect()

print("[DBG] [MAIN] WiFi OK → verificar OTA")
ota.check_update()   # Se houver update, reinicia automaticamente

print("[DBG] [MAIN] Nenhuma atualização pendente. Continuar.")

# Iniciar RS485 / controller
rs485.init()
ctrl = controller.Controller()

print("[DBG] Sistema iniciado sem OTA.")

while True:
    ctrl.loop_once()
    time.sleep_ms(20)
