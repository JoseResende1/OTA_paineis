# ======================================================
# rs485.py — RS485 robusto (TX/RX seguro)
# ======================================================
from machine import UART, Pin
import time
from config import debug

uart = UART(1, baudrate=115200, tx=13, rx=14, timeout=50)

# GPIOs RS485
DE = Pin(5, Pin.OUT)
RE = Pin(4, Pin.OUT)

def set_tx():
    DE.value(1)
    RE.value(1)

def set_rx():
    DE.value(0)
    RE.value(0)

def send(msg):
    """
    Envio RS485 com comutação segura TX→RX.
    Essencial quando se usa motores, PWM, ruído EM e HBM rápido.
    """
    # Mudar para TX
    set_tx()
    time.sleep_us(300)             # estabilização do transceiver

    uart.write(msg + "\r\n")
    uart.flush()                   # limpa FIFO UART

    time.sleep_us(400)             # garante envio completo físico

  
    # Voltar para RX
    set_rx()
    time.sleep_us(600)             # TEMPO CRÍTICO industrial

    debug("[TX] " + msg)


def read_line(timeout_ms=0):
    if timeout_ms <= 0:
        if uart.any():
            try:
                line = uart.readline()
                if line:
                    return line.decode().strip()
            except:
                pass
        return None

    t0 = time.ticks_ms()
    while time.ticks_diff(time.ticks_ms(), t0) < timeout_ms:
        if uart.any():
            try:
                line = uart.readline()
                if line:
                    return line.decode().strip()
            except:
                pass
        time.sleep_ms(2)
    return None


def read_lines():
    """Devolve todas as linhas recebidas."""
    lines = []
    if uart.any():
        try:
            raw = uart.read()
            if not raw:
                return lines
            try:
                txt = raw.decode()
            except:
                txt = ''.join(chr(b) for b in raw if 32 <= b < 127)

            for line in txt.splitlines():
                line = line.strip()
                if line:
                    lines.append(line)
        except:
            pass

    return lines
