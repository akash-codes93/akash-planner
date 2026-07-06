import subprocess
import sys
import os

os.chdir(os.path.dirname(os.path.abspath(__file__)))

EXCLUDES = [
    "matplotlib", "tkinter", "PIL", "IPython", "pandas",
    "scipy", "sympy", "numba", "notebook", "jupyter",
    "bokeh", "plotly", "seaborn", "networkx",
]

cmd = [
    sys.executable, "-m", "PyInstaller",
    "--onefile",
    "--name", "server",
    "--add-data", f"api{os.pathsep}api",
    "--add-data", f"db{os.pathsep}db",
    "--add-data", f"agent{os.pathsep}agent",
    "--add-data", f"planner.sqlite3{os.pathsep}.",
    *[e for mod in EXCLUDES for e in ("--exclude-module", mod)],
    "api/server.py",
]

print("Running PyInstaller...")
subprocess.run(cmd, check=True)
print("Done. Binary at dist/server" + (".exe" if sys.platform == "win32" else ""))
