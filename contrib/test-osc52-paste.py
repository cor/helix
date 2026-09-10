#!/usr/bin/env python3
"""Test real Helix OSC 52 reads in a private PTY; emulate only the terminal.

No desktop clipboard or multiplexer is required. Requires Python 3 on Unix.
Run after cargo build: python3 contrib/test-osc52-paste.py --helix target/debug/hx
"""
import argparse
import base64
from collections import deque
import fcntl
import os
from pathlib import Path
import pty
import re
import select
import struct
import subprocess
import tempfile
import termios
import time


def run_case(helix, root, name, payload, selection='c', fragmented=False, denied=False):
    out = root / f'{name}.txt'
    out.write_bytes(b'anchor\n')
    log = root / f'{name}.log'
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 40, 120, 960, 640))
    env = dict(os.environ, TERM='xterm-256color', XDG_CONFIG_HOME=str(root / 'config'))
    for key in ('DISPLAY', 'WAYLAND_DISPLAY', 'SSH_TTY'):
        env.pop(key, None)

    def controlling_terminal():
        os.setsid()
        fcntl.ioctl(0, termios.TIOCSCTTY, 0)

    child = subprocess.Popen(
        [helix, '-c', str(root / 'config.toml'), '--log', str(log), str(out)],
        stdin=slave, stdout=slave, stderr=slave, env=env, cwd=root,
        preexec_fn=controlling_terminal,
    )
    os.close(slave)
    writes = deque()
    output = b''
    queries = 0
    deny_next = denied

    def pump(seconds):
        nonlocal output, queries, deny_next
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            while writes and writes[0][0] <= time.monotonic():
                _, data = writes.popleft()
                os.write(master, data)
            if not select.select([master], [], [], .005)[0]:
                continue
            output += os.read(master, 65536)
            while match := re.search(rb'\x1b]52;([cp]);\?(?:\x1b\\|\x07)', output):
                output = output[match.end():]
                queries += 1
                assert match[1].decode() == selection
                if deny_next:
                    deny_next = False
                    continue
                # Include focus, mouse and keyboard events before the response.
                # F6 must be preserved for the editor and save the pasted text.
                os.write(master, b'\x1b[O\x1b[<35;10;10M\x1b[I\x1b[17~')
                response = b'\x1b]52;' + match[1] + b';' + base64.b64encode(payload)
                response += b'\x07' if fragmented else b'\x1b\\'
                parts = [response]
                if fragmented:
                    parts = [response[:1], response[1:3], response[3:7]]
                    parts += [response[i:i + 4096] for i in range(7, len(response), 4096)]
                at = time.monotonic() + .15
                for part in parts:
                    writes.append((at, part))
                    at += .035
            output = output[-8192:]

    def wait(predicate, timeout=12):
        until = time.monotonic() + timeout
        while not predicate():
            assert child.poll() is None, (name, 'Helix exited', output)
            assert time.monotonic() < until, (name, 'timed out', log.read_text(), output)
            pump(.025)

    try:
        pump(1)
        if denied:
            os.write(master, b' P')
            wait(lambda: 'terminal clipboard read timed out' in log.read_text())
            assert out.read_bytes() == b'anchor\n'
        before = queries
        os.write(master, b' P' if selection == 'c' else b'\x1b[18~')
        wait(lambda: queries > before)
        wait(lambda: not writes and out.read_bytes() == payload + b'anchor\n')
        os.write(master, b'\x1b[19~')  # F8: quit after verifying the saved file.
        until = time.monotonic() + 5
        while child.poll() is None and time.monotonic() < until:
            try:
                pump(.025)
            except OSError:  # PTY closes when Helix exits.
                break
        assert child.wait(timeout=5) == 0
        assert out.read_bytes() == payload + b'anchor\n'
        assert log.read_text().count('[ERROR]') == int(denied), log.read_text()
        print(f'PASS: {name} ({len(payload)} bytes)', flush=True)
    finally:
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        os.close(master)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--helix', type=Path, required=True)
    args = parser.parse_args()
    helix = str(args.helix.resolve())
    root = Path(tempfile.mkdtemp(prefix='helix-native-osc52-'))
    (root / 'config.toml').write_text(
        '[editor]\nclipboard-provider = "termcode"\n'
        '[keys.normal]\nF6 = ":write"\nF7 = "paste_primary_clipboard_before"\nF8 = ":quit!"\n'
    )
    try:
        run_case(helix, root, 'focus-mouse-and-queued-save', b'clipboard with terminal events\n')
        run_case(helix, root, 'fragmented-unicode-bel', '☃ café\nsecond line\n\n'.encode(), fragmented=True)
        run_case(helix, root, 'empty', b'')
        run_case(helix, root, 'large', b'long clipboard line\n' * 8192)
        run_case(helix, root, 'primary', b'primary selection\n', selection='p')
        run_case(helix, root, 'denied-read-recovery', b'recovered after denial\n', denied=True)
    finally:
        print(f'Logs and saved files: {root}', flush=True)


if __name__ == '__main__':
    main()
