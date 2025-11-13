# ======================================================
# controller.py — controlo com percentagem + HBM rápido
# ======================================================
import time, json, re
from machine import Pin
from config import CONFIG, debug
import rs485, mcp23017
from drv887x import DRV

LED = Pin(26, Pin.OUT)
CALIB_FILE = "calib.json"
POS_FILE = "pos.json"

# heartbeat rápido durante movimento
MOTOR_HB_MS = 350     # mais fiável que 300 ms em RS485 half-duplex com motor


class Controller:
    def __init__(self):
        mcp23017.init()
        self.addr = mcp23017.address()
        self.broadcast = CONFIG["BROADCAST_ADDR"]

        # Motores
        self.m1 = DRV(17, 16, 23, motor_id=1)
        self.m2 = DRV(19, 18, 25, motor_id=2)

        # Estado/Armazenamento
        self.positions = {"motor1": 0.0, "motor2": 0.0}
        self.calibration = self.load_calibration()
        self.load_positions()

        self.active_motor = None
        self.active_dir = None
        self.active_start = 0
        self.is_inverting = False

        # Botões
        self.btn1_pressed = False
        self.btn2_pressed = False
        self.btn1_press_time = 0
        self.btn2_press_time = 0
        self.btn1_short = []
        self.btn2_short = []

        # Timers
        self.last_led = time.ticks_ms()
        self.last_hb = time.ticks_ms()
        self.last_motor_hb = time.ticks_ms()

        rs485.set_rx()
        debug("Controller iniciado.")

    # --------------------------------------------------
    # Persistência
    # --------------------------------------------------
    def load_calibration(self):
        try:
            with open(CALIB_FILE) as f:
                return json.load(f)
        except:
            return {"motor1": {}, "motor2": {}}

    def save_calibration(self):
        with open(CALIB_FILE, "w") as f:
            json.dump(self.calibration, f)

    def load_positions(self):
        try:
            with open(POS_FILE) as f:
                self.positions.update(json.load(f))
        except:
            pass

    def save_positions(self):
        with open(POS_FILE, "w") as f:
            json.dump(self.positions, f)

    # --------------------------------------------------
    # Mensagens heartbeat
    # --------------------------------------------------
    def blink(self):
        LED.value(1 ^ LED.value())

    def build_hb(self, prefix="HB"):
        es = mcp23017.endstops_and_faults()
        return (
            f"{prefix},ADDR:{self.addr},"
            f"POS1:{int(self.positions['motor1'])}%,POS2:{int(self.positions['motor2'])}%;"
            f"M1_FA:{int(es['m1_open'])},FC:{int(es['m1_close'])};"
            f"M2_FA:{int(es['m2_open'])},FC:{int(es['m2_close'])}"
        )

    def heartbeat(self):
        rs485.send(self.build_hb("HB"))

    def heartbeat_motor(self):
        rs485.send(self.build_hb("HBM"))

    # --------------------------------------------------
    # Movimento motor
    # --------------------------------------------------
    def start_motor(self, motor, direction):
        self.active_motor = motor
        self.active_dir = direction
        self.active_start = time.ticks_ms()
        motor.run(direction)

    def stop_motor(self):
        if self.active_motor:
            # atualiza posição final
            mkey = f"motor{self.active_motor.id}"
            self.update_position(mkey)
            self.save_positions()
            self.active_motor.stop()

        self.active_motor = None
        self.active_dir = None

    def invert_motor(self, source="manual"):
        if not self.active_motor or self.is_inverting:
            return

        self.is_inverting = True
        mot = self.active_motor
        old = self.active_dir
        new = "close" if old == "open" else "open"

        mot.stop()
        time.sleep_ms(CONFIG["MOTOR_INVERT_DELAY_MS"])
        self.start_motor(mot, new)

        self.is_inverting = False

    # --------------------------------------------------
    # Atualizar posição
    # --------------------------------------------------
    def update_position(self, mkey):
        if not self.active_motor:
            return

        elapsed = time.ticks_diff(time.ticks_ms(), self.active_start)
        calib = self.calibration.get(mkey, {})

        if not calib:
            return

        base = calib["open_ms"] if self.active_dir == "open" else calib["close_ms"]
        delta = (elapsed / base) * 100

        if self.active_dir == "open":
            self.positions[mkey] = min(100, self.positions[mkey] + delta)
        else:
            self.positions[mkey] = max(0, self.positions[mkey] - delta)

    # --------------------------------------------------
    # Movimento por percentagem
    # --------------------------------------------------
    def move_to_percent(self, motor, pct):
        mkey = f"motor{motor.id}"
        calib = self.calibration.get(mkey, {})

        if not calib:
            rs485.send(f"NACK ADDR:{self.addr} Sem calibração.")
            return

        cur = self.positions[mkey]
        delta = pct - cur

        if abs(delta) < 1:
            return

        direction = "open" if delta > 0 else "close"
        base = calib["open_ms"] if delta > 0 else calib["close_ms"]
        time_needed = abs(delta) / 100 * base

        self.start_motor(motor, direction)
        start = time.ticks_ms()

        while time.ticks_diff(time.ticks_ms(), start) < time_needed:
            es = mcp23017.endstops_and_faults()

            if direction == "open" and es[f"m{motor.id}_open"]:
                self.positions[mkey] = 100
                break
            if direction == "close" and es[f"m{motor.id}_close"]:
                self.positions[mkey] = 0
                break

            if time.ticks_diff(time.ticks_ms(), self.active_start) > CONFIG["MOTOR_TIMEOUT_MS"]:
                rs485.send(f"ALERT ADDR:{self.addr} M{motor.id} TIMEOUT")
                break

            time.sleep_ms(10)

        self.stop_motor()

    # --------------------------------------------------
    # Botões
    # --------------------------------------------------
    def handle_button(self, motor, pin, pressed, ptime):
        now = time.ticks_ms()
        new_state = (pin == 1)

        if new_state and not pressed:
            ptime = now

        elif not new_state and pressed:
            dur = time.ticks_diff(now, ptime)

            if 50 <= dur <= 300:
                self.stop_motor()

            elif 500 <= dur <= 1500:
                if self.active_motor == motor:
                    self.invert_motor()
                else:
                    es = mcp23017.endstops_and_faults()
                    direction = "close" if es[f"m{motor.id}_open"] else "open"
                    self.start_motor(motor, direction)

        return new_state, ptime

    # --------------------------------------------------
    # Comandos RS485
    # --------------------------------------------------
    def handle_command(self, cmd):
        su = cmd.upper().strip()

        # Ex: 50-1
        match = re.search(r"([0-9]+)\s*-\s*([12])", su)
        if match:
            pct = int(match.group(1))
            mid = int(match.group(2))
            self.move_to_percent(self.m1 if mid == 1 else self.m2, pct)
            return

        def go(motor, want):
            if self.active_motor == motor and self.active_dir != want:
                self.invert_motor("rs485")
            else:
                self.start_motor(motor, want)

        if su == "ABRIR1":
            go(self.m1, "open")
        elif su == "FECHAR1":
            go(self.m1, "close")
        elif su == "ABRIR2":
            go(self.m2, "open")
        elif su == "FECHAR2":
            go(self.m2, "close")
        elif su == "STOP":
            self.stop_motor()

        rs485.send(f"ACK ADDR:{self.addr} CMD OK [{cmd}]")

    # --------------------------------------------------
    # LOOP PRINCIPAL
    # --------------------------------------------------
    def loop(self):
        while True:
            now = time.ticks_ms()

            # LED
            if time.ticks_diff(now, self.last_led) > CONFIG["LED_BLINK_MS"]:
                self.last_led = now
                self.blink()

            # Heartbeat normal
            if time.ticks_diff(now, self.last_hb) > CONFIG["HEARTBEAT_MS"]:
                self.last_hb = now
                self.heartbeat()

            # Heartbeat rápido
            if self.active_motor:
                if time.ticks_diff(now, self.last_motor_hb) > MOTOR_HB_MS:
                    self.last_motor_hb = now
                    self.update_position(f"motor{self.active_motor.id}")
                    self.heartbeat_motor()

            # Botões
            gpa = mcp23017.read_reg(0x12)
            b1 = (gpa >> 4) & 1
            b2 = (gpa >> 5) & 1

            es = mcp23017.endstops_and_faults()

            self.btn1_pressed, self.btn1_press_time = self.handle_button(
                self.m1, b1, self.btn1_pressed, self.btn1_press_time
            )
            self.btn2_pressed, self.btn2_press_time = self.handle_button(
                self.m2, b2, self.btn2_pressed, self.btn2_press_time
            )

            # Fins de curso
            if self.active_motor:
                mid = self.active_motor.id
                mkey = f"motor{mid}"

                if self.active_dir == "open" and es[f"m{mid}_open"]:
                    self.positions[mkey] = 100
                    self.stop_motor()

                elif self.active_dir == "close" and es[f"m{mid}_close"]:
                    self.positions[mkey] = 0
                    self.stop_motor()

                elif time.ticks_diff(now, self.active_start) > CONFIG["MOTOR_TIMEOUT_MS"]:
                    rs485.send(f"ALERT ADDR:{self.addr} M{mid} TIMEOUT")
                    self.stop_motor()

            # Comandos RS485
            for line in rs485.read_lines():
                if not line or not line.upper().startswith("ADDR"):
                    continue
                parts = line.upper().replace("ADDR:", "").split(None, 1)
                if len(parts) == 2 and parts[0].isdigit():
                    addr = int(parts[0])
                    cmd = parts[1].strip()
                    if addr == self.addr or addr == self.broadcast:
                        self.handle_command(cmd)

            time.sleep_ms(CONFIG["RS485_POLL_MS"])

