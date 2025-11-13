# ======================================================
# controller.py — versão industrial v4.0
# ======================================================

import time, json, re
from config import CONFIG, debug
import rs485, mcp23017
from drv887x import DRV


# ------------------------------------------------------
# Constantes
# ------------------------------------------------------
CALIB_FILE = "calib.json"
POS_FILE   = "pos.json"

SHORT_PRESS_MIN = 50
SHORT_PRESS_MAX = 300
FIVE_PRESS_WINDOW_MS = 3000
MOTION_HB_MS = 300


class Controller:

    # --------------------------------------------------
    # Inicialização
    # --------------------------------------------------
    def __init__(self):

        # MCP + endereço RS485
        mcp23017.init()
        self.addr = mcp23017.address()
        self.broadcast = CONFIG.get("BROADCAST_ADDR", 128)

        # Motores
        self.m1 = DRV(17, 16, 23, motor_id=1)  # EN, PH, NSLEEP
        self.m2 = DRV(19, 18, 25, motor_id=2)

        # Estados internos
        self.positions   = {"motor1": 0.0, "motor2": 0.0}
        self.calibration = self.load_calibration()
        self.load_positions()

        self.active_motor = None
        self.active_dir   = None
        self.active_start = 0

        # Botões / press detection
        self.btn1_state = False
        self.btn2_state = False
        self.btn1_t0    = 0
        self.btn2_t0    = 0
        self.btn1_history = []
        self.btn2_history = []

        # Auto-learn
        self.auto_learn_start_time = None
        self.auto_learn_start_endstop = None

        self.last_hb = 0
        self.last_motion_hb = 0

        rs485.set_rx()
        debug("Sistema iniciado com fins de curso, timeout e rastreamento de posição.")

    # --------------------------------------------------
    # Persistência
    # --------------------------------------------------
    def load_calibration(self):
        try:
            with open(CALIB_FILE, "r") as f:
                debug("Calibração carregada.")
                return json.load(f)
        except:
            debug("Sem calibração existente.")
            return {"motor1": {}, "motor2": {}}

    def save_calibration(self):
        with open(CALIB_FILE, "w") as f:
            json.dump(self.calibration, f)
        debug("Calibração salva.")

    def load_positions(self):
        try:
            with open(POS_FILE, "r") as f:
                self.positions.update(json.load(f))
                debug("Posições carregadas.")
        except:
            debug("Sem pos.json; usar 0%")

    def save_positions(self):
        with open(POS_FILE, "w") as f:
            json.dump(self.positions, f)

    # --------------------------------------------------
    # Heartbeat
    # --------------------------------------------------
    def heartbeat(self):
        es = mcp23017.endstops_and_faults()
        msg = (
            f"HB,ADDR:{self.addr},"
            f"POS1:{int(self.positions['motor1'])}%,"
            f"POS2:{int(self.positions['motor2'])}%,"
            f"M1_FA:{int(es['m1_open'])},FC:{int(es['m1_close'])},"
            f"M2_FA:{int(es['m2_open'])},FC:{int(es['m2_close'])}"
        )
        rs485.send(msg)

    # --------------------------------------------------
    # Arranque do motor
    # --------------------------------------------------
    def start_motor(self, motor, direction):
        self.active_motor = motor
        self.active_dir   = direction
        self.active_start = time.ticks_ms()

        es = mcp23017.endstops_and_faults()

        if es[f"m{motor.id}_close"]:
            self.auto_learn_start_endstop = "FC"
        elif es[f"m{motor.id}_open"]:
            self.auto_learn_start_endstop = "FA"
        else:
            self.auto_learn_start_endstop = None

        self.auto_learn_start_time = time.ticks_ms()

        debug(f"[DRV{motor.id}] START {direction.upper()}")
        motor.run(direction)

    # --------------------------------------------------
    # Paragem segura
    # --------------------------------------------------
    def stop_motor(self):

        if not self.active_motor:
            return

        motor = self.active_motor
        mkey  = f"motor{motor.id}"

        elapsed = time.ticks_diff(time.ticks_ms(), self.active_start)

        # Atualização de posição baseada no tempo / calib
        calib = self.calibration.get(mkey, {})
        base = calib.get("open_ms" if self.active_dir == "open" else "close_ms", 0)

        if base > 0:
            delta_pct = (elapsed / base) * 100
            if self.active_dir == "open":
                self.positions[mkey] = min(100, self.positions[mkey] + delta_pct)
            else:
                self.positions[mkey] = max(0, self.positions[mkey] - delta_pct)

        motor.stop()
        debug(f"[DRV{motor.id}] STOP t={elapsed}ms pos={self.positions[mkey]}%")

        self.save_positions()

        # AUTO-LEARN
        try:
            es = mcp23017.endstops_and_faults()
            elapsed2 = time.ticks_diff(time.ticks_ms(), self.auto_learn_start_time)

            if self.auto_learn_start_endstop == "FC" and es[f"m{motor.id}_open"]:
                old = calib.get("open_ms")
                if old and old * 0.4 < elapsed2 < old * 1.6:
                    new = int(old * 0.7 + elapsed2 * 0.3)
                    self.calibration[mkey]["open_ms"] = new
                    self.save_calibration()
                    debug(f"[AUTOLEARN] M{motor.id} OPEN {old}→{new}")

            if self.auto_learn_start_endstop == "FA" and es[f"m{motor.id}_close"]:
                old = calib.get("close_ms")
                if old and old * 0.4 < elapsed2 < old * 1.6:
                    new = int(old * 0.7 + elapsed2 * 0.3)
                    self.calibration[mkey]["close_ms"] = new
                    self.save_calibration()
                    debug(f"[AUTOLEARN] M{motor.id} CLOSE {old}→{new}")

        except Exception as e:
            debug(f"[AUTOLEARN] erro: {e}")

        # reset estado
        self.active_motor = None
        self.active_dir   = None
        self.auto_learn_start_endstop = None
        self.auto_learn_start_time = None

    # --------------------------------------------------
    # Inverter direção
    # --------------------------------------------------
    def invert_motor(self):
        if not self.active_motor:
            return
        old = self.active_dir
        new = "close" if old == "open" else "open"
        debug(f"[DRV{self.active_motor.id}] inverter {old}→{new}")
        self.stop_motor()
        time.sleep_ms(CONFIG["MOTOR_INVERT_DELAY_MS"])
        self.start_motor(self.active_motor, new)

    # --------------------------------------------------
    # Calibração industrial
    # --------------------------------------------------
    def calibrate_motor(self, motor):
        mid = motor.id
        mkey = f"motor{mid}"

        debug(f"[CALIB] Iniciar calibração motor {mid}")

        # 1) FECHAR até FC
        if not mcp23017.endstops_and_faults()[f"m{mid}_close"]:
            self.start_motor(motor, "close")
            while not mcp23017.endstops_and_faults()[f"m{mid}_close"]:
                time.sleep_ms(10)
            motor.stop()

        time.sleep_ms(200)

        # 2) MEDIR ABRIR
        debug(f"[CALIB] M{mid} medir ABRIR")
        self.start_motor(motor, "open")
        t0 = time.ticks_ms()
        while not mcp23017.endstops_and_faults()[f"m{mid}_open"]:
            time.sleep_ms(10)
        motor.stop()
        t_open = time.ticks_diff(time.ticks_ms(), t0)

        time.sleep_ms(200)

        # 3) MEDIR FECHAR
        debug(f"[CALIB] M{mid} medir FECHAR")
        self.start_motor(motor, "close")
        t0 = time.ticks_ms()
        while not mcp23017.endstops_and_faults()[f"m{mid}_close"]:
            time.sleep_ms(10)
        motor.stop()
        t_close = time.ticks_diff(time.ticks_ms(), t0)

        # Guardar
        self.calibration[mkey] = {"open_ms": t_open, "close_ms": t_close}
        self.save_calibration()

        self.positions[mkey] = 0.0
        self.save_positions()

        debug(f"[CALIB] M{mid} OK → OPEN:{t_open} CLOSE:{t_close}")
        rs485.send(
            f"ACK ADDR:{self.addr} CALIB_OK M{mid} OPEN:{t_open} CLOSE:{t_close}"
        )

    # --------------------------------------------------
    # Botões
    # --------------------------------------------------
    def process_button(self, motor, pressed_bit, state, t0, hist):

        now = time.ticks_ms()
        is_pressed = pressed_bit == 1

        # Rising edge
        if is_pressed and not state:
            t0 = now

        # Falling edge
        elif not is_pressed and state:
            dur = time.ticks_diff(now, t0)

            # Short press
            if SHORT_PRESS_MIN <= dur <= SHORT_PRESS_MAX:

                # acumula
                hist.append(now)
                hist[:] = [
                    t for t in hist if time.ticks_diff(now, t) < FIVE_PRESS_WINDOW_MS
                ]

                # 5 short → calibração
                if len(hist) >= 5:
                    hist.clear()
                    debug(f"[BTN{motor.id}] 5 shorts → Calibração")
                    self.calibrate_motor(motor)
                    return False, 0

                # stop se motor em marcha
                if self.active_motor == motor:
                    debug(f"[BTN{motor.id}] short → STOP")
                    self.stop_motor()

            # Long press
            elif dur >= 500:
                if self.active_motor == motor:
                    debug(f"[BTN{motor.id}] long → inverter")
                    self.invert_motor()
                else:
                    es = mcp23017.endstops_and_faults()
                    direction = "close" if es[f"m{motor.id}_open"] else "open"
                    debug(f"[BTN{motor.id}] long → arrancar {direction}")
                    self.start_motor(motor, direction)

        return is_pressed, t0

    # --------------------------------------------------
    # Movimento por percentagem
    # --------------------------------------------------
    def move_to_percent(self, motor_id, pct):

        motor = self.m1 if motor_id == 1 else self.m2
        mkey = f"motor{motor_id}"

        if mkey not in self.calibration:
            rs485.send(f"NACK ADDR:{self.addr} Sem calibração {mkey}")
            return

        curr = self.positions[mkey]
        delta = pct - curr
        if abs(delta) < 1:
            return

        direction = "open" if delta > 0 else "close"
        base = self.calibration[mkey]["open_ms"] if delta > 0 else self.calibration[mkey]["close_ms"]
        move_ms = abs(delta) / 100 * base

        debug(f"[DRV{motor_id}] Mover {direction} {int(move_ms)}ms → {pct}%")

        self.start_motor(motor, direction)
        t0 = time.ticks_ms()

        while time.ticks_diff(time.ticks_ms(), t0) < move_ms:
            es = mcp23017.endstops_and_faults()

            if direction == "open" and es[f"m{motor_id}_open"]:
                self.positions[mkey] = 100.0
                break

            if direction == "close" and es[f"m{motor_id}_close"]:
                self.positions[mkey] = 0.0
                break

            time.sleep_ms(10)

        self.stop_motor()

    # --------------------------------------------------
    # Comandos RS485
    # --------------------------------------------------
    def handle_command(self, cmd):

        su = cmd.upper().strip()
        debug(f"RS485 CMD: {su}")

        # Percentagem: "50-1"
        m = re.search(r"\s*([0-9]+)\s*-\s*([12])", su)
        if m:
            pct = int(m.group(1))
            motor_id = int(m.group(2))
            self.move_to_percent(motor_id, pct)
            return

        # Calibrações diretas
        if su == "CALIBRAR1":
            self.calibrate_motor(self.m1)
            return
        if su == "CALIBRAR2":
            self.calibrate_motor(self.m2)
            return

        # Comandos diretos
        if su == "ABRIR1":
            self.start_motor(self.m1, "open")
        elif su == "FECHAR1":
            self.start_motor(self.m1, "close")
        elif su == "ABRIR2":
            self.start_motor(self.m2, "open")
        elif su == "FECHAR2":
            self.start_motor(self.m2, "close")
        elif su.startswith("STOP"):
            self.stop_motor()

        rs485.send(f"ACK ADDR:{self.addr} CMD OK [{cmd}]")

    # --------------------------------------------------
    # Executar iteração única
    # --------------------------------------------------
    def loop_once(self):
        now = time.ticks_ms()

        # Heartbeat
        if not self.active_motor:
            if time.ticks_diff(now, self.last_hb) > CONFIG["HEARTBEAT_MS"]:
                self.last_hb = now
                self.heartbeat()
        else:
            if time.ticks_diff(now, self.last_motion_hb) > MOTION_HB_MS:
                self.last_motion_hb = now
                self.heartbeat()

        # Ler botões (GPA)
        gpa = mcp23017.read_reg(0x12)

        b1 = (gpa >> 6) & 1
        b2 = (gpa >> 7) & 1

        self.btn1_state, self.btn1_t0 = self.process_button(
            self.m1, b1, self.btn1_state, self.btn1_t0, self.btn1_history
        )
        self.btn2_state, self.btn2_t0 = self.process_button(
            self.m2, b2, self.btn2_state, self.btn2_t0, self.btn2_history
        )

        # Fins de curso automáticos
        if self.active_motor:
            motor = self.active_motor
            mkey  = f"motor{motor.id}"
            es = mcp23017.endstops_and_faults()

            if self.active_dir == "open" and es[f"m{motor.id}_open"]:
                self.stop_motor()
                self.positions[mkey] = 100.0
                self.save_positions()

            if self.active_dir == "close" and es[f"m{motor.id}_close"]:
                self.stop_motor()
                self.positions[mkey] = 0.0
                self.save_positions()

            # Timeout industrial
            if time.ticks_diff(now, self.active_start) > CONFIG["MOTOR_TIMEOUT_MS"]:
                rs485.send(f"ALERT ADDR:{self.addr} M{motor.id} TIMEOUT")
                self.stop_motor()

        # Comandos RS485
        for line in rs485.read_lines():
            line = line.strip()
            if not line.upper().startswith("ADDR:"):
                continue

            try:
                addr = int(line.split()[0].replace("ADDR:", ""))
            except:
                continue

            if addr in (self.addr, self.broadcast):
                cmd = line.split(None, 1)[1] if " " in line else ""
                self.handle_command(cmd)

        time.sleep_ms(CONFIG["RS485_POLL_MS"])
