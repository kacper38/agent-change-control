"""What a shell does with a NUL character in its command: as an argument, and on standard input.

Harmless: the only command is an echo of two letters.
"""

import subprocess

try:
    subprocess.run(["bash", "-c", "echo a\0b"], check=False)
    print("argument: started")
except ValueError as exc:
    print("argument: not started:", exc)

for shell in ("bash", "sh"):
    r = subprocess.run([shell], input=b"echo a\0b\n", capture_output=True, check=False)
    print(f"standard input of {shell}: exit {r.returncode}, out {r.stdout!r}, err {r.stderr!r}")
