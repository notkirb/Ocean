import subprocess
import os

# Base PyInstaller command
cmd = [
    "pyinstaller",
    "--onefile",
    "--name=Ocean",
    "--noconsole",
    "--add-data=icon.png:.",
    "--icon=icon.png",
    "main.py",
    # Always include this so ttkbootstrap + Pillow works
    "--hidden-import=PIL._tkinter_finder",
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

print("Running:", " ".join(cmd))
subprocess.run(cmd)
