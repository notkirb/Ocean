"""
Minecraft plugin auto-builder GUI
- Input a Spigot / Modrinth / GitHub / GitLab / Bitbucket URL
- Tries to locate the source repository
- Downloads/clones it
- Detects build system (gradle/maven) and attempts to build
- Finds produced jar(s) and reports their paths
"""

import os
import sys
import threading
import tempfile
import shutil
import subprocess
import stat
import requests
import time
from urllib.parse import urlparse, urljoin
from bs4 import BeautifulSoup
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.style import ThemeDefinition

import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext
import shlex

import ttkbootstrap.localization
ttkbootstrap.localization.initialize_localities = bool


# ---------- Configuration ----------
TIMEOUT = 15
USER_AGENT = "Mozilla/5.0 (compatible; PluginBuilder/1.0; OceanPluginBuilder/1.0)"
# -----------------------------------

session = requests.Session()
session.headers.update({"User-Agent": USER_AGENT})

# ---------- Logging helpers (thread-safe) ----------
def log(msg, gui_log=None):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    if gui_log:
        gui_log_insert(gui_log, line)

def gui_log_insert(gui_log, text):
    """
    Thread-safe insertion into scrolled text widget:
    schedule the actual UI update on the main thread with .after(...)
    """
    def append():
        try:
            gui_log.configure(state="normal")
            gui_log.insert(tk.END, text + "\n")
            gui_log.yview(tk.END)
            gui_log.configure(state="disabled")
        except Exception:
            # widget might be destroyed while worker thread still running
            pass

    try:
        gui_log.after(0, append)
    except Exception:
        # if gui_log has no after (unlikely), fallback to immediate
        append()

# ---------- Command runner (streams output) ----------
def run_command(cmd, cwd, gui_log=None):
    """
    Run external command streaming stdout/stderr to gui_log (thread-safe).
    Returns True if exit code == 0.
    """
    # Accept cmd as list; if string, shlex split it for safety
    if isinstance(cmd, str):
        cmd_list = shlex.split(cmd)
    else:
        cmd_list = cmd

    log(f"Running: {' '.join(cmd_list)} (in {cwd})", gui_log)

    try:
        process = subprocess.Popen(
            cmd_list,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
            universal_newlines=True
        )
    except FileNotFoundError as e:
        log(f"Command not found: {cmd_list[0]}", gui_log)
        return False
    except Exception as e:
        log(f"Failed to start process: {e}", gui_log)
        return False

    # Stream output line-by-line to GUI
    try:
        for line in process.stdout:
            gui_log_insert(gui_log, line.rstrip())
    except Exception:
        pass

    process.wait()
    rc = process.returncode
    log(f"Process exited with code {rc}", gui_log)
    return rc == 0


# ---------- Existing web / repo / build functions (kept mostly as-is) ----------
def fetch_page(url):
    resp = session.get(url, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.text

def find_repo_link_from_html(html, base_url):
    soup = BeautifulSoup(html, "html.parser")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "github.com" in href or "gitlab.com" in href or "bitbucket.org" in href:
            if href.startswith("/"):
                parsed_base = urlparse(base_url)
                href = parsed_base.scheme + "://" + parsed_base.netloc + href
            return href
    texts = soup.find_all(lambda tag: tag.name == "a" and tag.string and ("github" in tag.string.lower() or "source" in tag.string.lower()))
    for a in texts:
        href = a.get("href")
        if href:
            if href.startswith("/"):
                parsed_base = urlparse(base_url)
                href = parsed_base.scheme + "://" + parsed_base.netloc + href
            return href
    return None

def normalize_repo_url(repo_url):
    parsed = urlparse(repo_url)
    if "github.com" in parsed.netloc or "gitlab.com" in parsed.netloc or "bitbucket.org" in parsed.netloc:
        parts = parsed.path.rstrip("/").split("/")
        if len(parts) >= 3:
            new_path = "/".join(parts[:3])
            return f"{parsed.scheme}://{parsed.netloc}{new_path}"
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

def try_git_clone(repo_url, dest, gui_log=None, use_latest_tag=False):
    """
    Clone the repository. If use_latest_tag=True, checkout the latest tag
    based on creation date (newest first).
    """
    try:
        log(f"Cloning {repo_url} into {dest}...", gui_log)
        subprocess.check_call(
            ["git", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    except Exception:
        log("Git not available on PATH.", gui_log)
        return False

    try:
        subprocess.check_call(["git", "clone", repo_url, dest])
        log("Cloned repository.", gui_log)

        if use_latest_tag:
            # Get tags sorted by creation date (newest first)
            tags = subprocess.check_output(
                ["git", "tag", "--sort=-creatordate"], cwd=dest, text=True
            ).splitlines()

            if not tags:
                log("No tags found; using default branch.", gui_log)
            else:
                latest_tag = tags[0]
                log(f"Checking out latest tag: {latest_tag}", gui_log)
                subprocess.check_call(["git", "checkout", latest_tag], cwd=dest)

        return True

    except subprocess.CalledProcessError as e:
        log(f"git clone failed: {e}", gui_log)
        return False


def try_zip_download(repo_url, dest, gui_log=None):
    parsed = urlparse(repo_url)
    net = parsed.netloc.lower()
    path = parsed.path.rstrip("/")

    candidates = []
    if "github.com" in net:
        candidates = [
            f"{repo_url}/archive/refs/heads/main.zip",
            f"{repo_url}/archive/refs/heads/master.zip",
            f"{repo_url}/archive/refs/heads/develop.zip",
        ]
    elif "gitlab.com" in net:
        candidates = [
            f"{repo_url}/-/archive/main/{os.path.basename(path)}-main.zip",
            f"{repo_url}/-/archive/master/{os.path.basename(path)}-master.zip",
        ]
    elif "bitbucket.org" in net:
        candidates = [
            f"{repo_url}/get/main.zip",
            f"{repo_url}/get/master.zip",
        ]
    else:
        log("Zip download not supported for this host automatically.", gui_log)
        return False

    import zipfile
    from io import BytesIO

    for c in candidates:
        try:
            log(f"Attempting zip download: {c}", gui_log)
            r = session.get(c, timeout=TIMEOUT, stream=True)
            if r.status_code != 200:
                log(f"Not found: {c} (status {r.status_code})", gui_log)
                continue
            z = zipfile.ZipFile(BytesIO(r.content))
            z.extractall(dest)
            entries = os.listdir(dest)
            if len(entries) == 1:
                top = os.path.join(dest, entries[0])
                if os.path.isdir(top):
                    for name in os.listdir(top):
                        shutil.move(os.path.join(top, name), os.path.join(dest, name))
                    shutil.rmtree(top)
            log("Zip downloaded and extracted.", gui_log)
            return True
        except Exception as e:
            log(f"Zip download/extract failed for {c}: {e}", gui_log)
            continue
    return False

def filter_plugin_jars(jar_list, prefer_shadow=True):
    """
    Return all usable plugin jars from a list of produced jars.
    Filters out source/javadoc/test/original jars, but keeps multiple outputs.
    If prefer_shadow is True, prioritizes shadow/fat jars but keeps all valid jars.
    """
    if not jar_list:
        return []

    filtered = [
        j for j in jar_list
        if not any(bad in os.path.basename(j).lower()
                   for bad in ("sources", "javadoc", "tests", "original-", "gradle", "build-logic.jar"))
    ]
    if not filtered:
        return []

    if prefer_shadow:
        shadowed = [j for j in filtered if any(kw in os.path.basename(j).lower() for kw in ("shadow", "all"))]
        if shadowed:
            return shadowed

    # return all remaining filtered jars, sorted by modification time descending
    filtered.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return filtered


def ensure_executable(path, gui_log=None):
    if not path or not os.path.isfile(path):
        return
    try:
        st = os.stat(path)
        os.chmod(path, st.st_mode | stat.S_IEXEC)
        log(f"Set executable bit on {path}", gui_log)
    except Exception as e:
        log(f"Failed to chmod +x {path}: {e}", gui_log)

def find_build_files(root):
    res = {
        "gradlew": None,
        "build_gradle": None,
        "build_gradle_kts": None,
        "pom_xml": None,
    }
    for dirpath, dirnames, filenames in os.walk(root):
        for f in filenames:
            if f == "gradlew":
                res["gradlew"] = os.path.join(dirpath, f)
            if f == "build.gradle":
                res["build_gradle"] = os.path.join(dirpath, f)
            if f == "build.gradle.kts":
                res["build_gradle_kts"] = os.path.join(dirpath, f)
            if f == "pom.xml":
                res["pom_xml"] = os.path.join(dirpath, f)
        if any(res.values()):
            if res["gradlew"]:
                return res
    return res

def run_build(project_root, gui_log=None, prefer_shadow=False):
    """
    Try to build the project. Returns (success:boolean, path_to_jar_list:list)
    prefer_shadow: if True, attempt 'gradlew shadowJar' (or './gradlew shadowJar') when wrapper exists
    """
    bf = find_build_files(project_root)
    log(f"Build files: {bf}", gui_log)

    ensure_executable(bf.get("gradlew"), gui_log)
    ensure_executable(os.path.join(project_root, "gradlew"), gui_log)
    ensure_executable(os.path.join(project_root, "mvnw"), gui_log)

    if bf["gradlew"]:
        work_dir = os.path.dirname(bf["gradlew"])
        # Try shadowJar first if requested
        if prefer_shadow:
            cmd_shadow = ["./gradlew", "shadowJar", "-x", "test"]
            if sys.platform == "win32":
                cmd_shadow[0] = "gradlew.bat"
            ok_shadow = run_command(cmd_shadow, cwd=work_dir, gui_log=gui_log)
            if not ok_shadow:
                log("shadowJar failed or not present; falling back to build.", gui_log)
            else:
                # continue to collect jars below
                pass

        cmd = ["./gradlew", "build", "-x", "test"]
        if sys.platform == "win32":
            cmd[0] = "gradlew.bat"
        ok = run_command(cmd, cwd=work_dir, gui_log=gui_log)
        if not ok:
            log("Gradle wrapper build failed.", gui_log)
            return False, []
    elif bf["build_gradle"] or bf["build_gradle_kts"]:
        work_dir = os.path.dirname(bf["build_gradle"] or bf["build_gradle_kts"])
        ok = run_command(["gradle", "build", "-x", "test"], cwd=work_dir, gui_log=gui_log)
        if not ok:
            log("System Gradle build failed.", gui_log)
            return False, []
    elif bf["pom_xml"]:
        work_dir = os.path.dirname(bf["pom_xml"])
        ok = run_command(["mvn", "-DskipTests", "package"], cwd=work_dir, gui_log=gui_log)
        if not ok:
            log("Maven build failed.", gui_log)
            return False, []
    else:
        log("No recognized build file found.", gui_log)
        return False, []

    jars = []
    for dirpath, dirnames, filenames in os.walk(project_root):
        for f in filenames:
            if f.endswith(".jar"):
                full = os.path.join(dirpath, f)
                if "/.gradle/" in full.replace("\\", "/"):
                    continue
                jars.append(full)
    jars.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return (len(jars) > 0), jars

# ---------- GUI Worker ----------
def worker_process(url, out_dir, gui_log, progress_var, btn_start, status_var, recent_listbox, prefer_shadow, keep_temp_var, use_latest_tag_var):
    tmpdir = None
    try:
        btn_start.configure(state="disabled")
        progress_var.set(0)
        status_var.set("Starting...")
        log(f"Starting process for: {url}", gui_log)
        parsed = urlparse(url)
        if not parsed.scheme:
            url = "https://" + url
            parsed = urlparse(url)

        repo_url = None
        if "spigotmc.org" in parsed.netloc or "modrinth.com" in parsed.netloc or "curseforge.com" in parsed.netloc:
            status_var.set("Parsing plugin page for repository link...")
            log("Detected plugin host page; attempting to parse for repo link...", gui_log)
            try:
                html = fetch_page(url)
                repo = find_repo_link_from_html(html, url)
                if repo:
                    repo_url = normalize_repo_url(repo)
                    log(f"Found repo link: {repo_url}", gui_log)
                else:
                    log("No repository link found on page.", gui_log)
            except Exception as e:
                log(f"Failed to fetch or parse page: {e}", gui_log)
        else:
            if any(host in parsed.netloc for host in ("github.com", "gitlab.com", "bitbucket.org")):
                repo_url = normalize_repo_url(url)
                log(f"Assuming provided URL is repo: {repo_url}", gui_log)
            else:
                try:
                    html = fetch_page(url)
                    repo = find_repo_link_from_html(html, url)
                    if repo:
                        repo_url = normalize_repo_url(repo)
                        log(f"Found repo link: {repo_url}", gui_log)
                except Exception as e:
                    log(f"Could not fetch page: {e}", gui_log)

        if not repo_url:
            status_var.set("Could not determine repository URL.")
            log("Could not determine repository URL. Aborting.", gui_log)
            return

        tmpdir = tempfile.mkdtemp(prefix="plugin_build_")
        log(f"Working in temp dir: {tmpdir}", gui_log)
        status_var.set("Downloading repository...")
        progress_var.set(10)

        cloned = try_git_clone(repo_url, tmpdir, gui_log, use_latest_tag=use_latest_tag_var.get())

        progress_var.set(20)

        if not cloned:
            status_var.set("Trying zip download...")
            log("Git clone failed or not available; trying zip download.", gui_log)
            ok = try_zip_download(repo_url, tmpdir, gui_log)
            if not ok:
                status_var.set("Download failed.")
                log("Download failed. Aborting.", gui_log)
                return
        progress_var.set(40)
        status_var.set("Building project...")
        success, jars = run_build(tmpdir, gui_log, prefer_shadow=prefer_shadow.get())
        progress_var.set(80)
        if not success:
            status_var.set("Build failed or produced no jars.")
            log("Build did not produce jar(s). Check logs and build system manually.", gui_log)
            return

        usable_jars = filter_plugin_jars(jars)
        if not usable_jars:
            status_var.set("No usable plugin jars found.")
            log("No usable plugin jars found (only sources/docs/etc).", gui_log)
            return

        os.makedirs(out_dir, exist_ok=True)
        copied = []
        for jar in usable_jars:
            dest = os.path.join(out_dir, os.path.basename(jar))
            shutil.copy2(jar, dest)
            copied.append(dest)
            log(f"Copied {jar} -> {dest}", gui_log)

        progress_var.set(100)
        status_var.set("Build completed successfully.")
        log("Build completed successfully. JAR(s) are available:", gui_log)
        for c in copied:
            log(f"  {c}", gui_log)

        # update recent builds list on main thread
        def add_recent():
            recent_listbox.delete(0, tk.END)
            for p in copied:
                recent_listbox.insert(tk.END, p)

        recent_listbox.after(0, add_recent)

        messagebox.showinfo("Success", f"Build finished. {len(copied)} jar(s) saved to:\n{out_dir}")
    except Exception as e:
        status_var.set("Exception during process.")
        log(f"Exception during process: {e}", gui_log)
    finally:
        btn_start.configure(state="normal")
        if tmpdir and os.path.exists(tmpdir):
            if not keep_temp_var.get():
                try:
                    shutil.rmtree(tmpdir)
                    log(f"Temporary working directory deleted: {tmpdir}", gui_log)
                except Exception as e:
                    log(f"Failed to delete temp dir {tmpdir}: {e}", gui_log)
            else:
                log(f"Temporary working directory retained for inspection: {tmpdir}", gui_log)

# ---------- UI ----------
def start_gui():
    root = ttk.Window(themename="superhero")
    root.title("Ocean")
    root.geometry("1000x600")
    root.minsize(800, 520)
    icon = tk.PhotoImage(file=os.path.join(os.path.dirname(__file__) or sys._MEIPASS, "icon.png"))
    root.iconphoto(True, icon)

    # Main container
    container = ttk.Frame(root, padding=(12,12,12,12))
    container.pack(fill=BOTH, expand=True)

    # Top: Output and options
    top_frame = ttk.Frame(container)
    top_frame.pack(fill=X, pady=(0,10))

    io_frame = ttk.Frame(top_frame)
    io_frame.pack(side=LEFT, fill=X, expand=True)

    # Input group
    input_frame = ttk.LabelFrame(io_frame, text="Plugin Source", padding=10)
    input_frame.pack(fill=X, pady=(0,10))

    ttk.Label(input_frame, text="Plugin URL:").grid(row=0, column=0, sticky=W, pady=6)
    url_entry = ttk.Entry(input_frame)
    url_entry.grid(row=0, column=1, sticky="ew", padx=(8,0))
    input_frame.columnconfigure(1, weight=1)
    clipboard_hint = ttk.Label(input_frame, text="(Spigot/Modrinth/GitHub/GitLab/Bitbucket URL)", bootstyle="muted")
    clipboard_hint.grid(row=1, column=1, sticky=W, pady=(0,6))

    out_frame = ttk.LabelFrame(io_frame, text="Output", padding=10)
    out_frame.pack(fill=X)

    ttk.Label(out_frame, text="Output folder:").grid(row=0, column=0, sticky=W)
    out_entry = ttk.Entry(out_frame)
    out_entry.grid(row=0, column=1, sticky="ew", padx=6)
    out_entry.insert(0, os.path.expanduser("~/plugin_builds"))
    out_frame.columnconfigure(1, weight=1)

    def choose_out():
        d = filedialog.askdirectory(initialdir=os.path.expanduser("~"))
        if d:
            out_entry.delete(0, tk.END)
            out_entry.insert(0, d)

    ttk.Button(out_frame, text="Browse", bootstyle="secondary", width=10, command=choose_out).grid(row=0, column=2, padx=(6,0))

    options_frame = ttk.LabelFrame(top_frame, text="Options", padding=10, width=260)
    options_frame.pack(side=RIGHT, fill=Y, padx=(10,0))
    
    prefer_shadow = tk.BooleanVar(value=True)
    ttk.Checkbutton(
        options_frame, 
        text="Prefer shadowJar when available", 
        variable=prefer_shadow
    ).pack(anchor=W, pady=(6,0))
    ttk.Label(options_frame, text="(Helpful for fat/final plugin jars)", bootstyle="muted").pack(anchor=W)
    keep_temp_var = tk.BooleanVar(value=False)
    ttk.Checkbutton(
        options_frame,
        text="Keep temporary folder for inspection",
        variable=keep_temp_var
    ).pack(anchor=W, pady=(6,0))
    ttk.Label(options_frame, text="(Useful for debugging failed builds)", bootstyle="muted").pack(anchor=W)
    use_latest_tag_var = tk.BooleanVar(value=False)
    ttk.Checkbutton(
        options_frame,
        text="Use latest tag",
        variable=use_latest_tag_var
    ).pack(anchor=W, pady=(6,0))
    ttk.Label(options_frame, text="(Only use if a build is unsuccessful)", bootstyle="muted").pack(anchor=W)

    # Action row
    action_frame = ttk.Frame(container)
    action_frame.pack(fill=X, pady=(6,10))

    start_btn = ttk.Button(action_frame, text="Start", bootstyle="primary", width=18)
    start_btn.pack(side=LEFT, padx=(0,8))

    status_var = tk.StringVar(value="Ready")
    status_label = ttk.Label(action_frame, textvariable=status_var, bootstyle="muted")
    status_label.pack(side=RIGHT)

    progress = tk.DoubleVar(value=0)
    pbar = ttk.Progressbar(action_frame, variable=progress, maximum=100, bootstyle="primary-striped")
    pbar.pack(side=RIGHT, fill=X, expand=True, padx=(8,8))

    # Bottom: Log + Recent builds
    bottom_pane = ttk.PanedWindow(container, orient=HORIZONTAL)
    bottom_pane.pack(fill=BOTH, expand=True)

    # Logs
    log_frame = ttk.LabelFrame(bottom_pane, text="Build Logs", padding=8)
    logbox = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD, height=20, state="disabled", font=("Consolas", 10))
    logbox.pack(fill=BOTH, expand=True)
    bottom_pane.add(log_frame, weight=3)

    # Recent builds / actions
    recent_frame = ttk.LabelFrame(bottom_pane, text="Recent Builds", padding=8, width=300)
    recent_listbox = tk.Listbox(recent_frame, height=0)
    recent_listbox.pack(fill=BOTH, expand=True)
    recent_listbox_scroll = ttk.Scrollbar(recent_frame, command=recent_listbox.yview)
    recent_listbox.configure(yscrollcommand=recent_listbox_scroll.set)
    recent_listbox_scroll.pack(side=RIGHT, fill=Y)

    def open_selected():
        sel = recent_listbox.curselection()
        if not sel:
            return
        path = recent_listbox.get(sel[0])
        folder = os.path.dirname(path)
        try:
            if sys.platform.startswith("win"):
                os.startfile(folder)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", folder])
            else:
                subprocess.Popen(["xdg-open", folder])
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def copy_path():
        sel = recent_listbox.curselection()
        if not sel:
            return
        path = recent_listbox.get(sel[0])
        try:
            root.clipboard_clear()
            root.clipboard_append(path)
            messagebox.showinfo("Copied", "Path copied to clipboard.")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def reveal_in_file_manager():
        sel = recent_listbox.curselection()
        if not sel:
            return
        path = recent_listbox.get(sel[0])
        try:
            if sys.platform.startswith("win"):
                subprocess.Popen(['explorer', '/select,', path])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-R", path])
            else:
                # use file-manager selection if available, fallback to open folder
                try:
                    subprocess.Popen(["xdg-open", os.path.dirname(path)])
                except Exception:
                    subprocess.Popen(["xdg-open", os.path.dirname(path)])
        except Exception as e:
            messagebox.showerror("Error", str(e))

    btns_frame = ttk.Frame(recent_frame)
    btns_frame.pack(fill=X, pady=(6,0))
    ttk.Button(btns_frame, text="Open Folder", bootstyle="secondary", command=open_selected).pack(side=LEFT, padx=3, pady=3)
    ttk.Button(btns_frame, text="Copy Path", bootstyle="secondary", command=copy_path).pack(side=LEFT, padx=3, pady=3)
    ttk.Button(btns_frame, text="Reveal", bootstyle="secondary", command=reveal_in_file_manager).pack(side=LEFT, padx=3, pady=3)

    bottom_pane.add(recent_frame, weight=1)

    # Start action
    def on_start():
        url = url_entry.get().strip()
        out_dir = out_entry.get().strip()
        if not url:
            messagebox.showerror("Error", "Please enter a URL.")
            return
        # clear previous logs
        logbox.configure(state="normal")
        logbox.delete("1.0", tk.END)
        logbox.configure(state="disabled")
        recent_listbox.delete(0, tk.END)
        t = threading.Thread(
            target=worker_process,
            args=(url, out_dir, logbox, progress, start_btn, status_var, recent_listbox, prefer_shadow, keep_temp_var, use_latest_tag_var),
            daemon=True
        )


        t.start()

    start_btn.configure(command=on_start)

    # Try to paste URL from clipboard if any
    try:
        clipboard = root.clipboard_get()
        if clipboard.startswith("http"):
            url_entry.insert(0, clipboard)
    except Exception:
        pass

    log("Welcome to Ocean! Enter a URL into the Plugin Source box, choose your output location, then press Start!", logbox)

    root.mainloop()


if __name__ == "__main__":
    start_gui()
