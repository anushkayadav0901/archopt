"""Compile the standalone C++20 optimization CLI used by the API."""
from pathlib import Path
import subprocess
import sys

root = Path(__file__).parent
source = root / "engine" / "archopt_engine.cpp"
output = root / "engine" / ("archopt_engine.exe" if sys.platform.startswith("win") else "archopt_engine")
base = ["g++", "-O2", "-mthreads", str(source), "-o", str(output)]
# The source and CMake target are C++20.  The legacy MinGW bundled on some
# Windows lab machines has no C++20 switch, so use the highest compatible
# dialect for this dependency-free implementation when compiling locally.
last_error = None
for standard, legacy_threads in (("-std=c++20", False), ("-std=gnu++17", False), ("-std=gnu++14", False), ("-std=gnu++14", True)):
    command = [base[0], standard, *( ["-DARCHOPT_SINGLE_THREAD"] if legacy_threads else []), *base[1:]]
    print(" ".join(command))
    try:
        subprocess.run(command, check=True)
        break
    except subprocess.CalledProcessError as exc:
        last_error = exc
else:
    raise last_error  # type: ignore[misc]
print(f"Built {output}")
