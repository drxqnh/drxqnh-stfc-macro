import time
import threading
import pyautogui
import keyboard
import cv2
import numpy as np
import tkinter as tk
from tkinter import ttk
from pynput.mouse import Controller as MouseController
import ctypes
import os

# ==========================================================
# DEFAULT CONFIG (OVERWRITTEN BY GUI)
# ==========================================================
SCREEN_SCAN = (0, 100, 1919, 724)

IDLE_ROI = [870, 950, 50, 40]
DEAD_ROI = IDLE_ROI

ENEMY_COLOR = (233, 116, 117)
COLOR_TOLERANCE = 10
CLICK_OFFSET = (-30, 0)

CLICK_AFTER_ENEMY = (1320, 640)
DOCK1_SYSTEM = "Jinnia"
SHIP_COORDS = [890, 1000]

RESTART_INTERVAL = 600
BATTLE_TIMEOUT = 60
MAX_ENEMY_FAILS = 3

# ==========================================================
# PORTABLE PATHS
# ==========================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IMAGES_DIR = os.path.join(BASE_DIR, "Images", "Ships")

TEMPLATES = {
    "scan":   (os.path.join(IMAGES_DIR, "Scan.png"), 0.8, True),
    "battle": (os.path.join(IMAGES_DIR, "InBattle.png"), 0.8, True),
    "dead":   (os.path.join(IMAGES_DIR, "Dead.png"), 0.8, False),
    "idle":   (os.path.join(IMAGES_DIR, "Idle.png"), 0.85, False),
    "arrows": (os.path.join(IMAGES_DIR, "Arrows.png"), 0.8, True),
}


mouse = MouseController()
running = False
attack_thread = None
restart_thread = None

# ==========================================================
# UTILITIES
# ==========================================================
def real_click(x, y, delay=0.001):
    pyautogui.moveTo(x, y)
    time.sleep(delay)
    pyautogui.mouseDown()
    time.sleep(delay)
    pyautogui.mouseUp()

def color_match(px, target, tol):
    return all(abs(px[i] - target[i]) <= tol for i in range(3))

def load_template(path, gray):
    img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if img is None:
        raise FileNotFoundError(path)
    if img.ndim == 3 and img.shape[2] == 4:
        img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if gray else img

def click_sequence(points, delay=1):
    for x, y in points:
        real_click(x, y)
        time.sleep(delay)

# ==========================================================
# IMAGE MATCHING
# ==========================================================
templates = {
    name: (load_template(p, gray), threshold)
    for name, (p, threshold, gray) in TEMPLATES.items()
}

def match_template(name, region=None):
    img, threshold = templates[name]
    shot = pyautogui.screenshot(region=region)
    screen = np.array(shot)

    if img.ndim == 2:
        screen = cv2.cvtColor(screen, cv2.COLOR_RGB2GRAY)
    else:
        screen = cv2.cvtColor(screen, cv2.COLOR_RGB2BGR)

    res = cv2.matchTemplate(screen, img, cv2.TM_CCOEFF_NORMED)
    return cv2.minMaxLoc(res)[1] >= threshold

# ==========================================================
# STATE WAITERS
# ==========================================================
def wait_for_state_timeout(check_fn, timeout):
    start = time.time()
    while running:
        if check_fn():
            return True
        if time.time() - start > timeout:
            return False
        time.sleep(0.5)

def wait_for_idle():
    confirmations = 0
    while running:
        if match_template("idle", tuple(IDLE_ROI)):
            confirmations += 1
            if confirmations >= 3:
                time.sleep(1)
                return
        else:
            confirmations = 0
        time.sleep(0.5)

# ==========================================================
# ENEMY LOGIC
# ==========================================================
def find_enemy():
    shot = pyautogui.screenshot(region=SCREEN_SCAN)
    w, h = shot.size

    for x in range(w):
        for y in range(h):
            if not running:
                return False
            if color_match(shot.getpixel((x, y)), ENEMY_COLOR, COLOR_TOLERANCE):
                real_click(
                    SCREEN_SCAN[0] + x + CLICK_OFFSET[0],
                    SCREEN_SCAN[1] + y + CLICK_OFFSET[1]
                )
                time.sleep(0.4)

                if match_template("scan"):
                    real_click(*CLICK_AFTER_ENEMY)
                    return True
                return False
    return False

def check_arrows_and_click():
    if match_template("arrows"):
        real_click(1880, 910)
        time.sleep(0.3)

# ==========================================================
# RECOVERY
# ==========================================================
def handle_dead_ship():
    real_click(*SHIP_COORDS)
    time.sleep(0.2)
    click_sequence([
        (110, 980),
        (110, 1040),
        (110, 1040),
        (1140, 400),
        (1150, 470)
    ])

# ==========================================================
# DOCK / ATTACK LOOP
# ==========================================================
def dock1_setup(wait_idle=True):
    if match_template("dead", tuple(IDLE_ROI)):
            handle_dead_ship()
            time.sleep(1)
            return
    

    click_sequence([(1820, 910), (1730, 100)])
    pyautogui.typewrite(DOCK1_SYSTEM)

    real_click(1340, 120)
    real_click(960, 1030)
    time.sleep(2)

    for _ in range(100):
        mouse.scroll(0, -1)
        time.sleep(0.01)

    real_click(*SHIP_COORDS)
    time.sleep(0.2)

    check_arrows_and_click()

    if wait_idle:
        click_sequence([(960, 540), (1060, 480)], 0.5)
        wait_for_idle()

def dock1_attack_loop():
    dock1_setup()
    enemy_fails = 0

    while running:
        if not find_enemy():
            enemy_fails += 1
            if enemy_fails >= MAX_ENEMY_FAILS:
                enemy_fails = 0
                dock1_setup(wait_idle=False)
            time.sleep(0.2)
            continue

        enemy_fails = 0

        if not wait_for_state_timeout(lambda: match_template("battle"), BATTLE_TIMEOUT):
            dock1_setup(wait_idle=False)
            continue

        if not wait_for_state_timeout(lambda: not match_template("battle"), BATTLE_TIMEOUT):
            dock1_setup(wait_idle=False)
            continue

        if match_template("dead", tuple(IDLE_ROI)):
            handle_dead_ship()
            return

# ==========================================================
# GAME ACTIVATION
# ==========================================================
def activate_game_window():
    windows = pyautogui.getWindowsWithTitle("Star Trek Fleet Command")
    if windows:
        win = windows[0]
        if win.isMinimized:
            win.restore()
        win.activate()
        time.sleep(0.5)

# ==========================================================
# START / STOP
# ==========================================================
def start_attack():
    global running, attack_thread
    if running:
        return

    activate_game_window()
    running = True
    attack_thread = threading.Thread(target=dock1_attack_loop, daemon=True)
    attack_thread.start()

def stop_attack():
    global running
    running = False

# ==========================================================
# GUI
# ==========================================================
root = tk.Tk()
root.title("STFC Macro")

def apply_settings():
    global DOCK1_SYSTEM, SHIP_COORDS, IDLE_ROI
    DOCK1_SYSTEM = system_entry.get()
    SHIP_COORDS[:] = [int(ship_x.get()), int(ship_y.get())]
    IDLE_ROI[:] = [
        int(idle_x.get()),
        int(idle_y.get()),
        int(idle_w.get()),
        int(idle_h.get())
    ]

frame = ttk.Frame(root, padding=10)
frame.pack()

ttk.Label(frame, text="System").grid(row=0, column=0)
system_entry = ttk.Entry(frame)
system_entry.insert(0, DOCK1_SYSTEM)
system_entry.grid(row=0, column=1)

ttk.Label(frame, text="Ship X").grid(row=1, column=0)
ship_x = ttk.Entry(frame); ship_x.insert(0, SHIP_COORDS[0]); ship_x.grid(row=1, column=1)

ttk.Label(frame, text="Ship Y").grid(row=2, column=0)
ship_y = ttk.Entry(frame); ship_y.insert(0, SHIP_COORDS[1]); ship_y.grid(row=2, column=1)

ttk.Label(frame, text="Idle ROI X").grid(row=3, column=0)
idle_x = ttk.Entry(frame); idle_x.insert(0, IDLE_ROI[0]); idle_x.grid(row=3, column=1)

ttk.Label(frame, text="Idle ROI Y").grid(row=4, column=0)
idle_y = ttk.Entry(frame); idle_y.insert(0, IDLE_ROI[1]); idle_y.grid(row=4, column=1)

ttk.Label(frame, text="Idle ROI W").grid(row=5, column=0)
idle_w = ttk.Entry(frame); idle_w.insert(0, IDLE_ROI[2]); idle_w.grid(row=5, column=1)

ttk.Label(frame, text="Idle ROI H").grid(row=6, column=0)
idle_h = ttk.Entry(frame); idle_h.insert(0, IDLE_ROI[3]); idle_h.grid(row=6, column=1)

ttk.Button(frame, text="Apply Settings", command=apply_settings).grid(row=7, column=0, pady=5)
ttk.Button(frame, text="Start", command=start_attack).grid(row=7, column=1)
ttk.Button(frame, text="Stop", command=stop_attack).grid(row=8, column=1)

keyboard.add_hotkey("k", start_attack)
keyboard.add_hotkey("l", stop_attack)

root.mainloop()