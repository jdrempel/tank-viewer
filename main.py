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
state = "command"
ev_command = Event()
ev_read_cmd = Event()
ev_quit_sig = Event()
ev_quit_ack = Event()


def crc16_mcrf4xx(crc, data, length):
    if not any(data) or length <= 0:
        return crc

    index = 0
    while length > 0:
        crc ^= ord(data[index])
        L = crc ^ (crc << 4)
        t = (L << 3) | (L >> 5)
        L ^= (t & 0x07)
        t = (t & 0xf8) ^ (((t << 1) | (t >> 7)) & 0x0f) ^ ((crc >> 8) & 0xff)
        crc = (L << 8) | t
        index += 1
        length -= 1

    return crc


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


def pack_754(f, bits, exp_bits):
    significand_bits = bits - exp_bits - 1

    if f == 0.0:
        return 0

    if f < 0:
        sign = 1
        fnorm = -f
    else:
        sign = 0
        fnorm = f

    shift = 0
    while fnorm >= 2.0:
        fnorm /= 2.0
        shift += 1
    while fnorm < 1.0:
        fnorm *= 2.0
        shift -= 1
    fnorm -= 1.0

    significand = fnorm * ((1 << significand_bits) + 0.5)

    exp = shift + ((1 << (exp_bits - 1)) -1)

    return (sign << (bits - 1)) | (exp << (bits - exp_bits - 1)) | significand


def run_serial(p, cl_args):
    global command
    global state

    with Serial(p, cl_args.baud, timeout=cl_args.timeout) as ser:
        while True:
            try:
                print(str(ser.readline()))
                # byte_stream.write(ser.read())

            except serial.SerialTimeoutException:
                print(f"Connection with device on port {port} timed out, exiting...")
                exit(1)

            except serial.SerialException:
                print(f"Connection lost on port {port}, exiting...")
                exit(1)

            if ev_command.is_set():
                ev_command.clear()
                data = ""

                if command == "tare":
                    data = "T"

                elif command == "zero":
                    data = "Z0"

                elif command == "reset":
                    data = "R"

                else:
                    # A number related to zeroing
                    if state == "zero-1":
                        data = f"Z1:{float(command)}"

                    elif state == "zero-2":
                        data = f"Z2:{float(command)}"

                    else:
                        # Invalid input
                        ev_read_cmd.set()
                        continue

                crc = crc16_mcrf4xx(0, data, len(data))
                data += f"/{crc & 0xffff};"
                print(data)

                ev_read_cmd.set()
                ser.write(data.encode())
            else:
                print(".")


def run_command(cl_args):
    global command
    global state
    while True:
        valid = False
        if state == "command":
            command = input(">> ")
            if command == "quit":
                ev_quit_sig.set()
                ev_quit_ack.wait(1)
                ev_quit_ack.clear()
                kill(getpid(), signal.SIGKILL)
            elif command == "t":
                valid = True
                print("Okay, taring...")
                pass
            elif command == "z":
                valid = True
                print("Okay, starting the zero process...")
                state = "zero-1"
                pass
            elif command == "r":
                valid = True
                print("Okay, resetting the Arduino...")
                pass
            else:
                valid = False
                print(f'Invalid command: "{command}"')
                pass
        elif state == "zero-1":
            command = input("Mass 1 (kg) >> ")
            valid = True
            state = "zero-2"
            pass
        elif state == "zero-2":
            command = input("Mass 2 (kg) >> ")
            valid = True
            state = "command"
            print("Finished zeroing.")
            pass

        if valid:
            ev_command.set()
            ev_read_cmd.wait(cl_args.timeout * 2)
            ev_read_cmd.clear()
            if state == "zero-1":
                state = "zero-2"
            elif state == "zero-2":
                state = "command"


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
        default=19200,
        help="baud rate to use for the serial connection (default: 115200)",
    )
    parser.add_argument(
        "--timeout",
        dest="timeout",
        type=float,
        nargs=1,
        default=0.5,
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
    # mpl.style.use("seaborn-colorblind")
    # labels = [f"Tank {n}" for n in range(args.num_tanks)]
    # bar_width = 0.5

    # fig, ax = plot.subplots()

    # def animation(_):
    #     data = [randint(2, 7) for _ in range(args.num_tanks)]
    #     plot.cla()
    #     plot.bar(list(range(args.num_tanks)), data)
    #     # bars = ax.bar(list(range(args.num_tanks)), data, animated=True)
    #     # return bars

    # anim = FuncAnimation(plot.gcf(), animation, interval=10)

    # ax.set_xlabel("Tank")
    # ax.set_ylabel("Mass (kg)")
    # ax.set_title("Air Seeder Tank Masses")

    # plot.xlim([0, args.num_tanks])
    # plot.ylim([0, 10])
    # plot.show(block=False)
    # plot.pause(0.1)

    # bg = fig.canvas.copy_from_bbox(fig.bbox)

    serial_thread = Thread(target=run_serial, args=[port, args])
    serial_thread.daemon = True
    serial_thread.start()

    command_thread = Thread(target=run_command, args=[args, ])
    command_thread.daemon = True
    command_thread.start()

    while True:
        # plot.pause(0.1)
        if ev_quit_sig.is_set():
            # plot.close(fig)
            ev_quit_sig.clear()
            ev_quit_ack.set()
        pass

    pass
