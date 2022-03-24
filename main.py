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
data = ""
tankNumber = ""
dataUpdate = [0.0, 0.0]

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
    # comports = [
    #     c for c in comports if regex.match(r"(.*Ard.*)|(.*Ser.*)", f"{c[1]} {c[2]}")
    # ]

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
    global dataUpdate
    global data
    global tankNumber

    with Serial(p, cl_args.baud, timeout=cl_args.timeout) as ser:
        while True:
            try:
                arduinoOutput = str(ser.readline().decode(errors="ignore"))
                if arduinoOutput != "":
                    # print(arduinoOutput)
                    try:
                        outputParsed = arduinoOutput[1:-1]
                        outputParsed = outputParsed.split(";")
                        tank = outputParsed[0]
                        dataRec = outputParsed[1]
                        tankNo = int(tank.split(":")[1])
                        dataNo = float(dataRec.split(":")[1])
                        dataUpdate[tankNo] = dataNo
                    except:
                        pass

            except serial.SerialTimeoutException:
                print(f"Connection with device on port {port} timed out, exiting...")
                exit(1)

            except serial.SerialException:
                print(f"Connection lost on port {port}, exiting...")
                exit(1)

            if ev_command.is_set(): # wait for command
                ev_command.clear()
                if command == "c1" or command == "c2":
                    message = f"{command}({tankNumber}):{data}\n"
                else:
                    message = f"{command}({tankNumber})\n"

                print("Message:", message)

                ev_read_cmd.set() # enable command input again
                ser.write(message.encode())


def run_command(cl_args):
    global command
    global data
    global tankNumber

    while True:
        valid = False
        command = input(">> ")
        if command == "quit":
            ev_quit_sig.set()
            ev_quit_ack.wait(1)
            ev_quit_ack.clear()
            kill(getpid(), signal.SIGKILL)
        elif command == "t":
            valid = True
            print("Okay, taring...")
            tankNumber = input("Tank number >> ")
            data = ""
        elif command == "c1":
            valid = True
            print("Okay, entering phase 1 of the calibration process...")
            tankNumber = input("Tank number >> ")
            data = input("Mass 1 (lb) >> ")
        elif command == "c2":
            valid = True
            print("Okay, entering phase 2 of the calibration process...")
            tankNumber = input("Tank number >> ")
            data = input("Mass 2 (lb) >> ")
        elif command == "c3":
            valid = True
            print("Okay, entering phase 3 of the calibration process...")
            data = ""
            tankNumber = input("Tank number >> ")
        elif command == "r":
            valid = True
            print("Okay, resetting the Arduino...")
            data = ""
            tankNumber = input("Tank number >> ")
        else:
            print(f'Invalid command: "{command}"')

        if valid:
            ev_command.set()
            ev_read_cmd.wait(cl_args.timeout * 2)
            ev_read_cmd.clear()

if __name__ == "__main__":

    # This is to prevent really annoying errors cropping up in the command-line from libtk
    # It likes to complain about threading even though it is running on the main thread :eye-roll:
    if "linux" in platform or "darwin" in platform:
        sys.stderr = open("log.txt", "w")
    elif "win32" in platform:
        pass
        # sys.stderr = TemporaryFile()

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
        help="baud rate to use for the serial connection (default: 19200)",
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
        default=2,
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
        print(f"Established communication with device on port {port} with baud rate {args.baud}")
    else:
        print(f"Max attempts reached, exiting...")
        exit(1)

    # PLOTTING STUFF
    mpl.style.use("seaborn-colorblind")
    labels = [f"Tank {n}" for n in range(args.num_tanks)]
    bar_width = 0.5

    fig, ax = plot.subplots(figsize=(10,10))

    def animation(_):
        global dataUpdate
        # data = [massData for _ in range(args.num_tanks)]
        plot.cla()
        plot.bar(list(range(args.num_tanks)), dataUpdate)
        ax.set_ylim(bottom=0, top=30)
        ax.set_xlabel("Tanks")
        ax.set_ylabel("Mass (lb)")
        ax.set_title("Air Seeder Tank Mass")
        plot.xticks([0, 1], ["0", "1"])


    anim = FuncAnimation(plot.gcf(), animation, interval=10)



    ax.set_ylim(bottom=0, top=55)
    plot.show(block=False)
    plot.pause(0.1)

    bg = fig.canvas.copy_from_bbox(fig.bbox)

    serial_thread = Thread(target=run_serial, args=[port, args])
    serial_thread.daemon = True
    serial_thread.start()

    command_thread = Thread(target=run_command, args=[args, ])
    command_thread.daemon = True
    command_thread.start()

    while True:
        plot.pause(0.1)
        if ev_quit_sig.is_set():
            plot.close(fig)
            ev_quit_sig.clear()
            ev_quit_ack.set()
        pass

    pass
