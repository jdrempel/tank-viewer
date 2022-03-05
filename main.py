#!/usr/bin/python3

from argparse import ArgumentParser
from io import BytesIO
import matplotlib as mpl
import matplotlib.pyplot as plot
from matplotlib.animation import FuncAnimation
from os import kill, getpid
from random import randint
import re as regex
import serial
from serial import Serial
import signal
import sys
from sys import platform
from tempfile import TemporaryFile
import time
from threading import Thread, Event

if "linux" in platform:
    from serial.tools import list_ports_linux as list_ports
elif "darwin" in platform:
    from serial.tools import list_ports_osx as list_ports
elif "win32" in platform:
    from serial.tools import list_ports_windows as list_ports
else:
    from serial.tools import list_ports_posix as list_ports

CRLF = bytes(bytearray([13, 10]))

command = ""
ev_command = Event()
ev_quit_sig = Event()
ev_quit_ack = Event()


def configure_port(arg):
    comports = [tuple(p) for p in list(list_ports.comports())]
    comports = [
        c for c in comports if regex.match(r"(.*Ard.*)|(.*Ser.*)", f"{c[1]} {c[2]}")
    ]

    if len(comports) == 0:
        print("No available ports found, exiting...")
        exit(1)

    selection = 0
    if arg is None:
        print()
        print(
            "No port argument provided -- scanned and found the following candidate(s):"
        )
        for c in comports:
            print(c)

        if len(comports) > 1:
            print("More than one Arduino device found. Please select one:")
            for n, c in enumerate(comports):
                print(f"{n}.", c)
            selection = int(input("Selection:"))

    else:
        sub_comports = [c[0] for c in comports]
        if arg not in sub_comports:
            print(f"Port {arg} not found in list of available ports, exiting...")
            exit(1)
        else:
            selection = sub_comports.index(arg)

    return comports[selection][0]


def check_port_presence(device, backoff, baud, timeout):
    try:
        with Serial(device, baud, timeout=timeout) as s:
            s.write(b"0xabc123")
    except serial.PortNotOpenError:
        time.sleep(backoff)
        return False
    return True


def run_serial(p, cl_args):
    global command
    with Serial(p, cl_args.baud, timeout=cl_args.timeout) as ser:
        while True:
            try:
                byte_stream.write(ser.read())
            except serial.SerialTimeoutException:
                print(f"Connection with device on port {port} timed out, exiting...")
                exit(1)
            except serial.SerialException:
                print(f"Connection lost on port {port}, exiting...")
                exit(1)

            if ev_command.is_set():
                ev_command.clear()
                print("Reading command!")
                print(command)
                pass


def run_command():
    global command
    state = "command"
    while True:
        if state == "command":
            command = input(">> ")
            if command == "quit":
                ev_quit_sig.set()
                ev_quit_ack.wait(1)
                ev_quit_ack.clear()
                kill(getpid(), signal.SIGKILL)
            elif command == "tare":
                print("Okay, taring...")
                pass
            elif command == "zero":
                print("Okay, starting the zero process...")
                state = "zero-1"
                pass
            elif command == "reset":
                print("Okay, resetting the Arduino...")
                pass
            else:
                print(f'Invalid command: "{command}"')
                pass
        elif state == "zero-1":
            command = input("Mass 1 (kg) >> ")
            state = "zero-2"
            pass
        elif state == "zero-2":
            command = input("Mass 2 (kg) >> ")
            state = "command"
            print("Finished zeroing.")
            pass


if __name__ == "__main__":

    # This is to prevent really annoying errors cropping up in the command-line from libtk
    # It likes to complain about threading even though it is running on the main thread :eye-roll:
    if "linux" in platform or "darwin" in platform:
        sys.stderr = open("log.txt", "w")
    elif "win32" in platform:
        sys.stderr = TemporaryFile()

    parser = ArgumentParser(description="Display tank weights in real time")
    parser.add_argument("port", type=str, nargs="?")
    parser.add_argument(
        "--max-tries",
        dest="max_tries",
        type=int,
        nargs=1,
        default=5,
        help="number of times to attempt a serial connection (default: 5)",
    )
    parser.add_argument(
        "--baud",
        dest="baud",
        type=int,
        nargs=1,
        default=115200,
        help="baud rate to use for the serial connection (default: 115200)",
    )
    parser.add_argument(
        "--timeout",
        dest="timeout",
        type=float,
        nargs=1,
        default=1.0,
        help="length of time in seconds to wait on serial connection before aborting (default: 1)",
    )
    parser.add_argument(
        "--num-tanks",
        dest="num_tanks",
        nargs=1,
        default=5,
        help="number of presented air seeder tanks (default: 5)",
    )
    args = parser.parse_args()
    port = configure_port(args.port)

    byte_stream = BytesIO()

    tries = 0
    max_tries = args.max_tries
    success = False
    while tries < max_tries:
        tries += 1
        if check_port_presence(port, tries, args.baud, args.timeout):
            success = True
            break
        print(f"Unable to communicate on port {port} ({tries}/{max_tries}")

    if success:
        print(f"Established communication with device on port {port}")
    else:
        print(f"Max attempts reached, exiting...")
        exit(1)

    # PLOTTING STUFF
    mpl.style.use("seaborn-colorblind")
    labels = [f"Tank {n}" for n in range(args.num_tanks)]
    bar_width = 0.5

    fig, ax = plot.subplots()

    def animation(_):
        data = [randint(2, 7) for _ in range(args.num_tanks)]
        plot.cla()
        plot.bar(list(range(args.num_tanks)), data)
        # bars = ax.bar(list(range(args.num_tanks)), data, animated=True)
        # return bars

    anim = FuncAnimation(plot.gcf(), animation, interval=10)

    ax.set_xlabel("Tank")
    ax.set_ylabel("Mass (kg)")
    ax.set_title("Air Seeder Tank Masses")

    plot.xlim([0, args.num_tanks])
    plot.ylim([0, 10])
    plot.show(block=False)
    plot.pause(0.1)

    bg = fig.canvas.copy_from_bbox(fig.bbox)

    serial_thread = Thread(target=run_serial, args=[port, args])
    serial_thread.daemon = True
    serial_thread.start()

    command_thread = Thread(target=run_command)
    command_thread.daemon = True
    command_thread.start()

    while True:
        plot.pause(0.1)
        if ev_quit_sig.is_set():
            plot.close(fig)
            ev_quit_sig.clear()
            ev_quit_ack.set()

    pass
