import subprocess
import os

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

for pkg in hidden_imports:
    if f"--hidden-import={pkg}" not in cmd:
                cmd.append(f"--hidden-import={pkg}")

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

print("Running:", " ".join(cmd))
subprocess.run(cmd)
