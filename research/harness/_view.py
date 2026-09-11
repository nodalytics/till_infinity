import os, sys
name = os.environ.get("NAME", "cascade")
off = int(os.environ.get("OFF", "0"))
num = int(os.environ.get("NUM", "50"))
path = os.path.expanduser(f"~/till_infinity/logs/{name}.log")
lines = open(path, errors="replace").read().splitlines()
print(f"### {name}: lines {off}..{off+num} of {len(lines)}")
for i, line in enumerate(lines[off:off+num], off):
    print(f"{i:5d}|{line}")
