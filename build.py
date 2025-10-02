import subprocess
import os
import sys
import tkinter

# Find tkinter files to bundle in binary
def get_tcl_tk_data():
    paths = []

    # Tcl library
    tcl_paths = [
        "/usr/share/tcltk/tcl8.6",  # Ubuntu CI
        "/usr/lib/tcl8.6",
        os.path.join(sys.prefix, "tcl"),
        os.path.join(sys.prefix, "lib", "tcl"),
    ]

    # Tk library
    tk_paths = [
        "/opt/hostedtoolcache/Python/3.11.13/x64/lib/python3.11/tkinter",  # Ubuntu CI
        "/usr/share/tcltk/tk8.6",
        "/usr/lib/tk8.6",
        os.path.join(sys.prefix, "tk"),
        os.path.join(sys.prefix, "lib", "tk"),
    ]

    # Pick the first existing Tcl path
    for path in tcl_paths:
        if os.path.exists(path):
            paths.append(f"{path}:tcl")
            break

    # Pick the first existing Tk path
    for path in tk_paths:
        if os.path.exists(path):
            paths.append(f"{path}:tk")
            break

    return paths



# Imports that aren't explicitly listed in requirements.txt
hidden_imports = [
    "PIL._tkinter_finder",
    "tkinter",
    "tkinter.ttk",
    "tkinter.constants",
    "tkinter.messagebox",
    "tkinter.scrolledtext",
    "tkinter.filedialog",
    "tkinter.simpledialog",
    "tkinter.font",
    "ttkbootstrap",
    "ttkbootstrap.locales",
    "ttkbootstrap.localization.msgs",
    "ttkbootstrap.localization.msgcat",
]

# Base PyInstaller command
cmd = [
    "pyinstaller",
    "--onefile",
    "--name=Ocean",
    "--noconsole",
    "--add-data=icon.png:.",
    "--icon=icon.png",
    "main.py"
]

# Read requirements.txt if it exists
if os.path.exists("requirements.txt"):
    with open("requirements.txt") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            pkg = line.split("==")[0]  # strip version if present
            # Avoid duplicates
            if f"--hidden-import={pkg}" not in cmd:
                cmd.append(f"--hidden-import={pkg}")

# Append hidden_imports to cmd
for pkg in hidden_imports:
    if f"--hidden-import={pkg}" not in cmd:
                cmd.append(f"--hidden-import={pkg}")

# append tkinter files
for data in get_tcl_tk_data():
    cmd.append(f"--add-data={data}")

print("Running:", " ".join(cmd))
subprocess.run(cmd)
