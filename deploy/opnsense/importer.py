import socket
import subprocess
import sys
import time

CONSOLE = 4555
MONITOR = 4556
BOOT_WAIT = 3600
STOP_WAIT = 600
STEPS = (
    (b"Press any key to start the configuration importer", b"x"),
    (b"Select device to import from", b"vtbd1\r"),
    (b"Restoring config.xml...done.", b""),
    (b"login:", b""),
)


def reached(port: int, deadline: float) -> socket.socket:
    while True:
        try:
            return socket.create_connection(("127.0.0.1", port), timeout=5)
        except OSError:
            if time.monotonic() > deadline:
                raise
            time.sleep(1)


def awaited(console: socket.socket, wanted: bytes, deadline: float, heard: bytearray) -> None:
    while wanted not in heard:
        if time.monotonic() > deadline:
            tail = bytes(heard[-2000:]).decode(errors="replace")
            raise SystemExit(f"the OPNsense console never printed {wanted.decode()!r}:\n{tail}")
        try:
            chunk = console.recv(4096)
        except socket.timeout:
            continue
        if not chunk:
            raise SystemExit("QEMU closed the serial console")
        sys.stdout.write(chunk.decode(errors="replace"))
        heard += chunk
    del heard[: heard.index(wanted) + len(wanted)]


def main(disk: str, seed: str) -> None:
    nics = [argument for _ in range(3) for argument in ("-nic", "user,model=virtio-net-pci")]
    qemu = subprocess.Popen([
        "qemu-system-x86_64", "-machine", "accel=kvm:tcg", "-m", "2048", "-smp", "2",
        "-display", "none",
        "-serial", f"tcp:127.0.0.1:{CONSOLE},server=on,wait=on",
        "-monitor", f"tcp:127.0.0.1:{MONITOR},server=on,wait=off",
        "-drive", f"file={disk},format=raw,if=virtio",
        "-drive", f"file={seed},format=raw,if=virtio",
        *nics,
    ])
    deadline = time.monotonic() + BOOT_WAIT
    console = reached(CONSOLE, deadline)
    heard = bytearray()
    for wanted, answer in STEPS:
        awaited(console, wanted, deadline, heard)
        if answer:
            console.sendall(answer)
    reached(MONITOR, deadline).sendall(b"system_powerdown\n")
    try:
        qemu.wait(timeout=STOP_WAIT)
    except subprocess.TimeoutExpired:
        qemu.kill()
        raise SystemExit("OPNsense did not power off after taking its configuration")


if __name__ == "__main__":
    main(*sys.argv[1:])
