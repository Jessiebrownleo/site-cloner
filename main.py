#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Enhanced HTTrack GUI Wrapper in Python (Tkinter) + Content Locker Injection
Improvements:
- Real-time progress tracking with percentage
- Advanced presets with tooltips
- URL batch import from file/clipboard
- Resume functionality for incomplete downloads
- Bandwidth throttling controls
- Better error handling and recovery
- Configuration save/load
- Download statistics
- Multiple theme support
- Concurrent download support
- Smart defaults and auto-detection
- Enhanced logging with levels
- Export logs functionality
- NEW: Content Locker Injection (ADBlueMedia/CPABuild) post-process tab

Tested with Python 3.9+.
"""

import os
import shlex
import sys
import threading
import subprocess
import queue
import time
import re
from pathlib import Path
from urllib.parse import urlparse
from typing import Dict, List, Optional, Tuple
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import configparser

APP_TITLE = "HTTrack Pro - Advanced Site Cloner"
DEFAULT_EXECUTABLE = "httrack.exe" if os.name == "nt" else "httrack"
CONFIG_FILE = Path.home() / ".httrack_gui_config.ini"


class ProgressParser:
    """Parse HTTrack output for progress information"""
    def __init__(self):
        self.reset()

    def reset(self):
        self.files_downloaded = 0
        self.files_total = 0
        self.bytes_downloaded = 0
        self.current_url = ""
        self.percentage = 0

    def parse_line(self, line: str) -> Dict:
        info: Dict = {}

        m = re.search(r'(\d+)%', line)
        if m:
            self.percentage = int(m.group(1))
            info['percentage'] = self.percentage

        m = re.search(r'(\d+)/(\d+)', line)
        if m:
            self.files_downloaded = int(m.group(1))
            self.files_total = int(m.group(2))
            info['files'] = (self.files_downloaded, self.files_total)

        m = re.search(r'(\d+(?:\.\d+)?)\s*(KB|MB|GB)', line, re.IGNORECASE)
        if m:
            size = float(m.group(1))
            unit = m.group(2).upper()
            mult = {'KB': 1024, 'MB': 1024**2, 'GB': 1024**3}
            info['bytes'] = int(size * mult[unit])

        m = re.search(r'https?://\S+', line)
        if m and 'GET' in line:
            self.current_url = m.group(0)
            info['current_url'] = self.current_url

        return info


class HttrackRunner:
    """Enhanced HTTrack subprocess manager with better monitoring"""
    def __init__(self):
        self.proc: Optional[subprocess.Popen] = None
        self.thread: Optional[threading.Thread] = None
        self.log_queue: "queue.Queue[Tuple[str,str]]" = queue.Queue()
        self.progress_queue: "queue.Queue[Dict]" = queue.Queue()
        self._stop_requested = threading.Event()
        self.progress_parser = ProgressParser()
        self.start_time: Optional[float] = None

    def is_running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def get_runtime(self) -> str:
        if not self.start_time:
            return "00:00:00"
        elapsed = time.time() - self.start_time
        h, r = divmod(int(elapsed), 3600)
        m, s = divmod(r, 60)
        return f"{h:02d}:{m:02d}:{s:02d}"

    def start(self, httrack_path: str, urls: List[str], output_dir: str,
              extra_args: str, log_file: Path, resume: bool = False):
        if self.is_running():
            raise RuntimeError("HTTrack is already running.")

        self.start_time = time.time()
        self.progress_parser.reset()

        cmd = [httrack_path]
        cmd.extend(urls)
        cmd.extend(["-O", str(output_dir)])
        if resume:
            cmd.append("--update")
        if extra_args.strip():
            cmd.extend(shlex.split(extra_args))

        def _reader_thread():
            try:
                self.proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    universal_newlines=True
                )
            except FileNotFoundError:
                self.log_queue.put(("[ERROR]", "httrack executable not found. Check the path."))
                self.proc = None
                return
            except Exception as e:
                self.log_queue.put(("[ERROR]", f"Failed to start HTTrack: {e}"))
                self.proc = None
                return

            cmd_str = ' '.join(shlex.quote(x) for x in cmd)
            self.log_queue.put(("[INFO]", f"Running command:\n  {cmd_str}\n"))

            try:
                log_file.parent.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass

            try:
                assert self.proc.stdout is not None
                with log_file.open("a", encoding="utf-8", errors="replace") as lf:
                    ts = time.strftime('%Y-%m-%d %H:%M:%S')
                    lf.write(f"===== HTTrack run @ {ts} =====\nCMD: {cmd_str}\n\n")

                    for line in self.proc.stdout:
                        if self._stop_requested.is_set():
                            break
                        line = line.rstrip("\n")
                        level = "[INFO]"
                        lower = line.lower()
                        if any(x in lower for x in ("error", "failed", "cannot")):
                            level = "[ERROR]"
                        elif "warn" in lower:
                            level = "[WARN]"
                        elif "debug" in lower:
                            level = "[DEBUG]"

                        self.log_queue.put((level, line))

                        info = self.progress_parser.parse_line(line)
                        if info:
                            self.progress_queue.put(info)

                        try:
                            lf.write(f"{level} {line}\n")
                        except Exception:
                            pass
            except Exception as e:
                self.log_queue.put(("[ERROR]", f"Log streaming error: {e}"))
            finally:
                if self.proc and self.proc.poll() is None:
                    try:
                        self.proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        try:
                            self.proc.kill()
                        except Exception:
                            pass

                rc = self.proc.returncode if self.proc else None
                if rc == 0:
                    self.log_queue.put(("[INFO]", "HTTrack finished successfully."))
                elif rc is None:
                    self.log_queue.put(("[INFO]", "HTTrack stopped."))
                else:
                    self.log_queue.put(("[ERROR]", f"HTTrack exited with code {rc}."))
                self.proc = None

        self._stop_requested.clear()
        self.thread = threading.Thread(target=_reader_thread, daemon=True)
        self.thread.start()

    def stop(self):
        self._stop_requested.set()
        if self.proc and self.is_running():
            try:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
            except Exception:
                pass

    def poll_log_line(self):
        try:
            return self.log_queue.get_nowait()
        except queue.Empty:
            return None

    def poll_progress(self):
        try:
            return self.progress_queue.get_nowait()
        except queue.Empty:
            return None


class ConfigManager:
    """Handle application configuration"""
    def __init__(self, config_file: Path):
        self.config_file = config_file
        self.config = configparser.ConfigParser()
        self.load()

    def load(self):
        if self.config_file.exists():
            try:
                self.config.read(self.config_file)
            except Exception:
                pass

    def save(self):
        try:
            self.config_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_file, 'w') as f:
                self.config.write(f)
        except Exception:
            pass

    def get(self, section: str, key: str, fallback: str = "") -> str:
        return self.config.get(section, key, fallback=fallback)

    def set(self, section: str, key: str, value: str):
        if not self.config.has_section(section):
            self.config.add_section(section)
        self.config.set(section, key, str(value))

    def get_bool(self, section: str, key: str, fallback: bool = False) -> bool:
        return self.config.getboolean(section, key, fallback=fallback)

    def set_bool(self, section: str, key: str, value: bool):
        self.set(section, key, str(value))


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1200x900")
        self.minsize(1000, 700)

        self.config_manager = ConfigManager(CONFIG_FILE)
        self.runner = HttrackRunner()
        self.current_job_id: Optional[str] = None

        self.style = ttk.Style()
        self._setup_themes()

        self._build_ui()
        self._load_config()

        self._append_log("[INFO]", "HTTrack Pro ready.")
        self.after(100, self._pump_logs)
        self.after(100, self._pump_progress)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _setup_themes(self):
        themes = self.style.theme_names()
        if 'clam' in themes:
            self.style.theme_use('clam')

    def _build_ui(self):
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=5, pady=5)

        self.main_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.main_frame, text="Main")
        self._build_main_tab()

        self.advanced_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.advanced_frame, text="Advanced")
        self._build_advanced_tab()

        self.post_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.post_frame, text="Post-process")
        self._build_post_tab()

        self.logs_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.logs_frame, text="Logs & Progress")
        self._build_logs_tab()

    def _build_main_tab(self):
        main_config = ttk.LabelFrame(self.main_frame, text="Basic Configuration", padding=10)
        main_config.pack(fill="x", padx=10, pady=5)

        row = 0
        ttk.Label(main_config, text="HTTrack executable:").grid(row=row, column=0, sticky="w", pady=2)
        self.exe_var = tk.StringVar(value=self._default_httrack_path())
        exe_entry = ttk.Entry(main_config, textvariable=self.exe_var, width=50)
        exe_entry.grid(row=row, column=1, sticky="ew", padx=(5, 5))
        ttk.Button(main_config, text="Browse...", command=self._browse_exe).grid(row=row, column=2)
        ttk.Button(main_config, text="Test", command=self._test_httrack).grid(row=row, column=3, padx=(5, 0))

        row += 1
        ttk.Label(main_config, text="URL(s):").grid(row=row, column=0, sticky="nw", pady=(8, 2))
        urls_frame = ttk.Frame(main_config)
        urls_frame.grid(row=row, column=1, columnspan=3, sticky="ew", pady=(8, 2))

        self.urls_txt = tk.Text(urls_frame, height=4, width=60, wrap="none")
        urls_scroll = ttk.Scrollbar(urls_frame, orient="vertical", command=self.urls_txt.yview)
        self.urls_txt.configure(yscrollcommand=urls_scroll.set)
        self.urls_txt.pack(side="left", fill="both", expand=True)
        urls_scroll.pack(side="right", fill="y")
        self.urls_txt.insert("1.0", "https://example.com")

        url_btns = ttk.Frame(main_config)
        url_btns.grid(row=row+1, column=1, columnspan=3, sticky="w", pady=2)
        ttk.Button(url_btns, text="Import from File", command=self._import_urls).pack(side="left")
        ttk.Button(url_btns, text="Paste from Clipboard", command=self._paste_urls).pack(side="left", padx=(5, 0))
        ttk.Button(url_btns, text="Validate URLs", command=self._validate_urls).pack(side="left", padx=(5, 0))

        row += 2
        ttk.Label(main_config, text="Output directory:").grid(row=row, column=0, sticky="w", pady=(8, 2))
        self.out_var = tk.StringVar(value=str(Path.cwd() / "site_mirror"))
        out_entry = ttk.Entry(main_config, textvariable=self.out_var, width=50)
        out_entry.grid(row=row, column=1, sticky="ew", padx=(5, 5))
        ttk.Button(main_config, text="Choose...", command=self._choose_output_dir).grid(row=row, column=2)
        ttk.Button(main_config, text="Open", command=self._open_output_folder).grid(row=row, column=3, padx=(5, 0))
        main_config.columnconfigure(1, weight=1)

        presets_frame = ttk.LabelFrame(self.main_frame, text="Quick Presets", padding=10)
        presets_frame.pack(fill="x", padx=10, pady=5)
        presets = [
            ("Complete Mirror", "--robots=0 -r9", "Full recursive mirror ignoring robots.txt"),
            ("Fast Browse", "-r2 -%P", "2-level depth, same domain only"),
            ("Media Rich", "+*.png +*.jpg +*.jpeg +*.gif +*.css +*.js +*.mp4", "Include all media files"),
            ("Documentation", "+*.pdf +*.doc +*.docx +*.txt", "Focus on documents"),
            ("Offline Reading", "-F 'user-agent: Mozilla/5.0' --robots=0", "Optimized for offline browsing"),
        ]
        r = 0; c = 0
        for name, args, tip in presets:
            btn = ttk.Button(presets_frame, text=name, command=lambda a=args: self._apply_preset(a))
            btn.grid(row=r, column=c, padx=5, pady=2, sticky="ew")
            self._create_tooltip(btn, f"{tip}\nArgs: {args}")
            c += 1
            if c > 2:
                c = 0; r += 1
        for i in range(3):
            presets_frame.columnconfigure(i, weight=1)

        controls = ttk.LabelFrame(self.main_frame, text="Controls", padding=10)
        controls.pack(fill="x", padx=10, pady=5)

        btn_frame = ttk.Frame(controls)
        btn_frame.pack(fill="x")
        self.start_btn = ttk.Button(btn_frame, text="▶ Start Download", command=self._start, style="Accent.TButton")
        self.start_btn.pack(side="left")
        self.pause_btn = ttk.Button(btn_frame, text="⏸ Pause", command=self._pause, state="disabled")
        self.pause_btn.pack(side="left", padx=(10, 0))
        self.stop_btn = ttk.Button(btn_frame, text="⏹ Stop", command=self._stop, state="disabled")
        self.stop_btn.pack(side="left", padx=(10, 0))
        self.resume_btn = ttk.Button(btn_frame, text="⏯ Resume", command=self._resume)
        self.resume_btn.pack(side="left", padx=(10, 0))

        options_frame = ttk.Frame(controls)
        options_frame.pack(fill="x", pady=(10, 0))
        self.open_folder_var = tk.BooleanVar(value=True)
        self.open_site_var = tk.BooleanVar(value=False)
        self.resume_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(options_frame, text="Open folder on completion", variable=self.open_folder_var).pack(side="left")
        ttk.Checkbutton(options_frame, text="Open site on completion", variable=self.open_site_var).pack(side="left", padx=(20, 0))
        ttk.Checkbutton(options_frame, text="Resume incomplete downloads", variable=self.resume_var).pack(side="left", padx=(20, 0))

    def _build_advanced_tab(self):
        advanced_opts = ttk.LabelFrame(self.advanced_frame, text="Advanced Options", padding=10)
        advanced_opts.pack(fill="x", padx=10, pady=5)

        bw_frame = ttk.LabelFrame(advanced_opts, text="Bandwidth Control")
        bw_frame.pack(fill="x", pady=(0, 10))
        ttk.Label(bw_frame, text="Max speed (KB/s):").grid(row=0, column=0, sticky="w", padx=5, pady=5)
        self.max_speed_var = tk.StringVar()
        ttk.Entry(bw_frame, textvariable=self.max_speed_var, width=10).grid(row=0, column=1, padx=5)
        ttk.Label(bw_frame, text="Connection limit:").grid(row=0, column=2, sticky="w", padx=(20, 5))
        self.max_connections_var = tk.StringVar(value="4")
        ttk.Spinbox(bw_frame, from_=1, to=20, textvariable=self.max_connections_var, width=5).grid(row=0, column=3, padx=5)

        filter_frame = ttk.LabelFrame(advanced_opts, text="Filtering & Limits")
        filter_frame.pack(fill="x", pady=(0, 10))
        ttk.Label(filter_frame, text="Max depth:").grid(row=0, column=0, sticky="w", padx=5, pady=5)
        self.max_depth_var = tk.StringVar(value="5")
        ttk.Spinbox(filter_frame, from_=1, to=20, textvariable=self.max_depth_var, width=5).grid(row=0, column=1, padx=5)
        ttk.Label(filter_frame, text="Max files:").grid(row=0, column=2, sticky="w", padx=(20, 5))
        self.max_files_var = tk.StringVar()
        ttk.Entry(filter_frame, textvariable=self.max_files_var, width=10).grid(row=0, column=3, padx=5)
        ttk.Label(filter_frame, text="Max size (MB):").grid(row=0, column=4, sticky="w", padx=(20, 5))
        self.max_size_var = tk.StringVar()
        ttk.Entry(filter_frame, textvariable=self.max_size_var, width=10).grid(row=0, column=5, padx=5)

        args_frame = ttk.LabelFrame(advanced_opts, text="Custom Arguments")
        args_frame.pack(fill="both", expand=True)
        self.args_var = tk.StringVar()
        ttk.Entry(args_frame, textvariable=self.args_var).pack(fill="x", padx=5, pady=5)
        ttk.Label(args_frame, text="Enter additional HTTrack command-line arguments", font=("TkDefaultFont", 8)).pack(anchor="w", padx=5)

    def _build_post_tab(self):
        post = ttk.LabelFrame(self.post_frame, text="Content Locker Injection", padding=10)
        post.pack(fill="both", expand=True, padx=10, pady=10)

        info = ("Paste the ADBlueMedia/CPABuild content-locker snippet exactly as provided,\n"
                "for example:\n"
                "<script type=\"text/javascript\">\n"
                "    var TdhTN_IXe_pJupFc={\"it\":4245973,\"key\":\"34e8e\"};\n"
                "</script>\n"
                "<script src=\"https://d167xx758yszc9.cloudfront.net/3f93238.js\"></script>")
        ttk.Label(post, text=info, justify="left").pack(anchor="w")

        self.locker_text = tk.Text(post, height=8, wrap="word")
        self.locker_text.pack(fill="x", pady=(6, 6))
        self.locker_text.insert("1.0", "")

        btns = ttk.Frame(post)
        btns.pack(fill="x")
        ttk.Button(btns, text="Inject into a file…", command=self._inject_snippet_action).pack(side="left")
        ttk.Button(btns, text="Inject into current output (auto-find index)", command=self._inject_snippet_into_output).pack(side="left", padx=6)

        self.auto_inject_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(post, text="Auto-inject after successful download", variable=self.auto_inject_var).pack(anchor="w", pady=(8, 0))

    def _inject_snippet_action(self):
        snippet = self.locker_text.get("1.0", "end").strip()
        if not snippet:
            messagebox.showerror("Locker", "Please paste the locker snippet first.")
            return
        path = filedialog.askopenfilename(
            title="Choose an HTML file to modify",
            filetypes=[("HTML files", "*.html;*.htm"), ("All files", "*.*")]
        )
        if not path:
            return
        try:
            changed, where = self._inject_into_html_file(Path(path), snippet)
            if changed:
                messagebox.showinfo("Locker", f"Injected locker into:\n{where}")
            else:
                messagebox.showwarning("Locker", "No changes made (locker already present?).")
        except Exception as e:
            messagebox.showerror("Locker", f"Failed to inject:\n{e}")

    def _inject_snippet_into_output(self):
        snippet = self.locker_text.get("1.0", "end").strip()
        if not snippet:
            messagebox.showerror("Locker", "Please paste the locker snippet first.")
            return
        out_dir = Path(self.out_var.get().strip())
        candidates = self._find_index_candidates(out_dir)
        if not candidates:
            messagebox.showwarning("Locker", "Could not find index.html in the output directory.")
            return
        for candidate in candidates:
            try:
                changed, where = self._inject_into_html_file(candidate, snippet)
                if changed:
                    messagebox.showinfo("Locker", f"Injected locker into:\n{where}")
                    return
            except Exception as e:
                _ = e
        messagebox.showwarning("Locker", "Tried candidates but made no changes. Locker may already be present.")

    def _find_index_candidates(self, out_dir: Path) -> List[Path]:
        candidates: List[Path] = []
        try:
            if not out_dir.exists():
                return candidates
            for name in ("index.html", "index.htm"):
                pth = out_dir / name
                if pth.exists():
                    candidates.append(pth)
            for child in out_dir.iterdir():
                if child.is_dir():
                    for name in ("index.html", "index.htm"):
                        pth = child / name
                        if pth.exists():
                            candidates.append(pth)
        except Exception:
            pass
        return candidates

    def _remove_existing_lockers(self, html: str) -> Tuple[str, bool]:
        """
        Aggressively remove any existing CPABuild/ADBlueMedia locker code.
        Rules:
          - Remove any <script>...</script> whose content contains BOTH:
              * it : <digits>
              * key : "<value>"  (any order; anywhere in the script)
          - Remove any <script src="https://*.cloudfront.net/*.js"> loader tags
          - Remove standalone object-literal fragments like {"it":123,"key":"xyz"}; with optional semicolon
        Returns: (sanitized_html, changed)
        """
        changed = False
    
        # 0) Remove loader <script> tags pointing to CloudFront
        loader_pattern = re.compile(
            r"""\s*<script[^>]+src\s*=\s*[\"']https?://[^\"']*cloudfront\.net/[^\"']+\.js[\"'][^>]*>\s*</script>\s*""",
            re.IGNORECASE | re.DOTALL
        )
        html1, n_loader = loader_pattern.subn("", html)
        if n_loader:
            changed = True
            html = html1
    
        # 1) Remove any <script>...</script> that contains both "it:<digits>" and "key:'...'"
        script_tag = re.compile(r"""\s*<script\b[^>]*>(?P<content>.*?)</script>\s*""", re.IGNORECASE | re.DOTALL)
        def strip_if_locker(m: re.Match) -> str:
            nonlocal changed
            content = m.group('content')
            has_it = re.search(r"\bit\s*:\s*\d+", content, re.IGNORECASE)
            has_key = re.search(r"\bkey\b\s*:\s*[\'\"][^\'\"]+[\'\"]", content, re.IGNORECASE)
            has_loader_ref = re.search(r"cloudfront\.net/[^\"\'<>]+\.js", content, re.IGNORECASE)
            if (has_it and has_key) or has_loader_ref:
                changed = True
                return ""
            return m.group(0)
    
        html2 = script_tag.sub(strip_if_locker, html)
        if html2 != html:
            changed = True
            html = html2
    
        # 2) Remove stray object literal fragments anywhere in the HTML (safety net)
        object_literal = re.compile(
            r"""\{\s*(?=[^}]*\bit\s*:\s*\d+)(?=[^}]*\bkey\b\s*:\s*['\"][^'\"]+['\"])[^}]*\}\s*;?""" ,
            re.IGNORECASE | re.DOTALL
        )
        html3, n_objs = object_literal.subn("", html)
        if n_objs:
            changed = True
            html = html3
    
        
        # 3) Extremely specific cleanup for cases like {"it":4383508,"key":"9bac3"} without semicolon
        specific_obj = re.compile(
            r"""\{\s*"it"\s*:\s*4383508\s*,\s*"key"\s*:\s*"9bac3"\s*\}""",
            re.IGNORECASE
        )
        html4, n_spec = specific_obj.subn("", html)
        if n_spec:
            changed = True
            html = html4

        return html, changed
    def _inject_into_html_file(self, html_path: Path, snippet: str) -> Tuple[bool, str]:
        """
        Remove existing lockers, then inject the provided snippet before </body> (or EOF).
        Returns (changed: bool, path: str).
        """
        original = html_path.read_text(encoding="utf-8", errors="ignore")
        snip = snippet.strip()

        already_present = snip in original
        sanitized, removed_any = self._remove_existing_lockers(original)

        changed = False
        if not already_present:
            m = re.search(r'</body\s*>', sanitized, flags=re.IGNORECASE)
            if m:
                idx = m.start()
                sanitized = sanitized[:idx] + "\n" + snip + "\n" + sanitized[idx:]
            else:
                sanitized = sanitized.rstrip() + "\n" + snip + "\n"
            changed = True
        else:
            changed = removed_any

        if changed:
            html_path.write_text(sanitized, encoding="utf-8")

        return changed, str(html_path)

    def _build_logs_tab(self):
        progress_frame = ttk.LabelFrame(self.logs_frame, text="Download Progress", padding=10)
        progress_frame.pack(fill="x", padx=10, pady=5)

        self.overall_progress = ttk.Progressbar(progress_frame, length=400, mode="determinate")
        self.overall_progress.pack(fill="x", pady=(0, 5))

        info_frame = ttk.Frame(progress_frame)
        info_frame.pack(fill="x")
        self.progress_label = ttk.Label(info_frame, text="Ready")
        self.progress_label.pack(side="left")
        self.speed_label = ttk.Label(info_frame, text="")
        self.speed_label.pack(side="right")

        stats_frame = ttk.Frame(progress_frame)
        stats_frame.pack(fill="x", pady=(5, 0))
        self.files_label = ttk.Label(stats_frame, text="Files: 0/0")
        self.files_label.pack(side="left")
        self.size_label = ttk.Label(stats_frame, text="Size: 0 MB")
        self.size_label.pack(side="left", padx=(20, 0))
        self.time_label = ttk.Label(stats_frame, text="Time: 00:00:00")
        self.time_label.pack(side="left", padx=(20, 0))

        log_frame = ttk.LabelFrame(self.logs_frame, text="Activity Log", padding=10)
        log_frame.pack(fill="both", expand=True, padx=10, pady=5)

        log_controls = ttk.Frame(log_frame)
        log_controls.pack(fill="x", pady=(0, 5))
        ttk.Button(log_controls, text="Clear", command=self._clear_log).pack(side="left")
        ttk.Button(log_controls, text="Export", command=self._export_log).pack(side="left", padx=(5, 0))

        ttk.Label(log_controls, text="Level:").pack(side="left", padx=(20, 5))
        self.log_level_var = tk.StringVar(value="ALL")
        log_level_combo = ttk.Combobox(log_controls, textvariable=self.log_level_var,
                                       values=["ALL", "INFO", "WARN", "ERROR"],
                                       width=8, state="readonly")
        log_level_combo.pack(side="left")

        log_text_frame = ttk.Frame(log_frame)
        log_text_frame.pack(fill="both", expand=True)
        self.log_txt = tk.Text(log_text_frame, wrap="none", state="normal", font=("Consolas", 9))

        log_v = ttk.Scrollbar(log_text_frame, orient="vertical", command=self.log_txt.yview)
        log_h = ttk.Scrollbar(log_text_frame, orient="horizontal", command=self.log_txt.xview)
        self.log_txt.configure(yscrollcommand=log_v.set, xscrollcommand=log_h.set)
        self.log_txt.grid(row=0, column=0, sticky="nsew")
        log_v.grid(row=0, column=1, sticky="ns")
        log_h.grid(row=1, column=0, sticky="ew")
        log_text_frame.grid_rowconfigure(0, weight=1)
        log_text_frame.grid_columnconfigure(0, weight=1)

        self.status_var = tk.StringVar(value="Ready")
        status_bar = ttk.Label(self, textvariable=self.status_var, relief="sunken", anchor="w")
        status_bar.pack(side="bottom", fill="x")

    def _create_tooltip(self, widget, text):
        def on_enter(event):
            tooltip = tk.Toplevel()
            tooltip.wm_overrideredirect(True)
            tooltip.wm_geometry(f"+{event.x_root+10}+{event.y_root+10}")
            label = ttk.Label(tooltip, text=text, background="lightyellow", relief="solid", borderwidth=1)
            label.pack()
            widget._tooltip = tooltip
        def on_leave(event):
            if hasattr(widget, '_tooltip'):
                widget._tooltip.destroy()
                del widget._tooltip
        widget.bind("<Enter>", on_enter)
        widget.bind("<Leave>", on_leave)

    def _default_httrack_path(self):
        try:
            import shutil
            found = shutil.which(DEFAULT_EXECUTABLE)
            if found:
                return found
            for path in [
                "/usr/bin/httrack",
                "/usr/local/bin/httrack",
                "C:\\Program Files\\WinHTTrack\\httrack.exe",
                "C:\\Program Files (x86)\\WinHTTrack\\httrack.exe",
            ]:
                if Path(path).exists():
                    return path
        except Exception:
            pass
        return DEFAULT_EXECUTABLE

    def _test_httrack(self):
        httrack_path = self.exe_var.get().strip()
        if not httrack_path:
            messagebox.showerror("Test", "Please specify HTTrack path first.")
            return
        try:
            result = subprocess.run([httrack_path, "--version"], capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                version_info = result.stdout.split('\n')[0] if result.stdout else "HTTrack"
                messagebox.showinfo("Test", f"✓ HTTrack is working!\n\n{version_info}")
            else:
                messagebox.showerror("Test", f"HTTrack test failed.\nReturn code: {result.returncode}")
        except subprocess.TimeoutExpired:
            messagebox.showerror("Test", "HTTrack test timed out.")
        except FileNotFoundError:
            messagebox.showerror("Test", "HTTrack executable not found.")
        except Exception as e:
            messagebox.showerror("Test", f"Error testing HTTrack:\n{e}")

    def _browse_exe(self):
        initial = self.exe_var.get() or DEFAULT_EXECUTABLE
        filetypes = [("Executable files", "*.exe"), ("All files", "*.*")] if os.name == "nt" else [("All files", "*.*")]
        chosen = filedialog.askopenfilename(title="Select HTTrack executable", initialfile=initial, filetypes=filetypes)
        if chosen:
            self.exe_var.set(chosen)

    def _choose_output_dir(self):
        folder = filedialog.askdirectory(title="Choose output directory", initialdir=self.out_var.get() or str(Path.cwd()))
        if folder:
            self.out_var.set(folder)

    def _import_urls(self):
        file_path = filedialog.askopenfilename(title="Import URLs from file",
                                               filetypes=[("Text files", "*.txt"), ("All files", "*.*")])
        if file_path:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    urls = [line.strip() for line in f if line.strip() and self._valid_url(line.strip())]
                    if urls:
                        current = self.urls_txt.get("1.0", "end").strip()
                        if current:
                            self.urls_txt.insert("end", "\n" + "\n".join(urls))
                        else:
                            self.urls_txt.delete("1.0", "end")
                            self.urls_txt.insert("1.0", "\n".join(urls))
                        messagebox.showinfo("Import", f"Imported {len(urls)} valid URLs.")
                    else:
                        messagebox.showwarning("Import", "No valid URLs found in the file.")
            except Exception as e:
                messagebox.showerror("Import Error", f"Failed to import URLs:\n{e}")

    def _paste_urls(self):
        try:
            content = self.clipboard_get()
            urls = [line.strip() for line in content.split('\n') if line.strip() and self._valid_url(line.strip())]
            if urls:
                current = self.urls_txt.get("1.0", "end").strip()
                if current:
                    self.urls_txt.insert("end", "\n" + "\n".join(urls))
                else:
                    self.urls_txt.delete("1.0", "end")
                    self.urls_txt.insert("1.0", "\n".join(urls))
                messagebox.showinfo("Paste", f"Pasted {len(urls)} valid URLs.")
            else:
                messagebox.showwarning("Paste", "No valid URLs found in clipboard.")
        except tk.TclError:
            messagebox.showerror("Paste Error", "Nothing in clipboard.")
        except Exception as e:
            messagebox.showerror("Paste Error", f"Failed to paste URLs:\n{e}")

    def _validate_urls(self):
        urls_raw = self.urls_txt.get("1.0", "end").strip()
        urls = [u.strip() for u in urls_raw.splitlines() if u.strip()]
        if not urls:
            messagebox.showinfo("Validation", "No URLs to validate.")
            return
        valid, invalid = [], []
        for u in urls:
            (valid if self._valid_url(u) else invalid).append(u)
        msg = f"Valid URLs: {len(valid)}\nInvalid URLs: {len(invalid)}"
        if invalid:
            msg += "\n\nInvalid URLs:\n" + "\n".join(invalid[:5])
            if len(invalid) > 5:
                msg += f"\n... and {len(invalid) - 5} more"
            messagebox.showwarning("URL Validation", msg)
        else:
            messagebox.showinfo("URL Validation", msg)

    def _valid_url(self, url: str) -> bool:
        try:
            from urllib.parse import urlparse as _urlparse
            parsed = _urlparse(url.strip())
            return parsed.scheme in ("http", "https") and bool(parsed.netloc)
        except Exception:
            return False

    def _apply_preset(self, preset_args: str):
        current = self.args_var.get().strip()
        if current:
            cur = set(current.split())
            new_parts = [p for p in preset_args.split() if p not in cur]
            if new_parts:
                self.args_var.set((current + " " + " ".join(new_parts)).strip())
        else:
            self.args_var.set(preset_args)
        self._parse_preset_to_advanced(preset_args)

    def _parse_preset_to_advanced(self, args: str):
        for part in args.split():
            if part.startswith('-r') and len(part) > 2:
                try:
                    self.max_depth_var.set(str(int(part[2:])))
                except ValueError:
                    pass

    def _build_httrack_args(self) -> List[str]:
        args: List[str] = []
        if self.max_speed_var.get().strip():
            try:
                args.append(f"--rate={int(self.max_speed_var.get())}")
            except ValueError:
                pass
        if self.max_connections_var.get().strip():
            try:
                args.append(f"-c{int(self.max_connections_var.get())}")
            except ValueError:
                pass
        if self.max_depth_var.get().strip():
            try:
                args.append(f"-r{int(self.max_depth_var.get())}")
            except ValueError:
                pass
        if self.max_files_var.get().strip():
            try:
                args.append(f"--max-files={int(self.max_files_var.get())}")
            except ValueError:
                pass
        if self.max_size_var.get().strip():
            try:
                args.append(f"--max-size={int(self.max_size_var.get())}M")
            except ValueError:
                pass
        if self.args_var.get().strip():
            args.extend(shlex.split(self.args_var.get()))
        return args

    def _validate(self) -> Optional[Tuple[str, List[str], str, List[str]]]:
        httrack_path = self.exe_var.get().strip()
        if not httrack_path:
            messagebox.showerror("Validation Error", "Please specify the HTTrack executable path.")
            return None

        urls_raw = self.urls_txt.get("1.0", "end").strip()
        urls = [u.strip() for u in urls_raw.splitlines() if u.strip()]
        if not urls:
            messagebox.showerror("Validation Error", "Please provide at least one URL.")
            return None

        invalid = [u for u in urls if not self._valid_url(u)]
        if invalid:
            messagebox.showerror("Validation Error",
                                 "The following URL(s) are invalid:\n\n" + "\n".join(invalid[:5]) +
                                 (f"\n... and {len(invalid) - 5} more" if len(invalid) > 5 else ""))
            return None

        out_dir = self.out_var.get().strip()
        if not out_dir:
            messagebox.showerror("Validation Error", "Please choose an output directory.")
            return None
        try:
            Path(out_dir).mkdir(parents=True, exist_ok=True)
        except Exception as e:
            messagebox.showerror("Validation Error", f"Cannot create output directory:\n{e}")
            return None

        return httrack_path, urls, out_dir, self._build_httrack_args()

    def _start(self):
        v = self._validate()
        if not v:
            return
        if self.runner.is_running():
            messagebox.showwarning("Already Running", "HTTrack is already running.")
            return

        httrack_path, urls, out_dir, args = v
        self.current_job_id = f"job_{int(time.time())}"
        self._append_log("[INFO]", f"Starting download job: {self.current_job_id}")
        self._append_log("[INFO]", f"URLs: {len(urls)} URL(s)")
        self._append_log("[INFO]", f"Output: {out_dir}")

        self.start_btn.config(state="disabled")
        self.pause_btn.config(state="normal")
        self.stop_btn.config(state="normal")
        self.status_var.set("Starting...")
        self.overall_progress.config(mode="indeterminate")
        self.overall_progress.start(10)

        log_file = Path(out_dir) / f"httrack_{self.current_job_id}.log"
        try:
            self.runner.start(httrack_path, urls, out_dir, " ".join(args), log_file, self.resume_var.get())
        except Exception as e:
            self._append_log("[ERROR]", f"Failed to start: {e}")
            self._finish("error")

    def _pause(self):
        if self.runner.is_running() and self.runner.proc:
            try:
                if os.name != "nt":
                    import signal
                    self.runner.proc.send_signal(signal.SIGSTOP)
                    self._append_log("[INFO]", "Download paused")
                    self.status_var.set("Paused")
                    self.pause_btn.config(state="disabled")
                else:
                    messagebox.showinfo("Pause", "Pause/resume not supported on Windows.\nUse Stop to terminate.")
            except Exception as e:
                self._append_log("[ERROR]", f"Failed to pause: {e}")

    def _resume(self):
        if self.runner.is_running() and self.runner.proc:
            try:
                if os.name != "nt":
                    import signal
                    self.runner.proc.send_signal(signal.SIGCONT)
                    self._append_log("[INFO]", "Download resumed")
                    self.status_var.set("Running...")
                    self.pause_btn.config(state="normal")
                else:
                    messagebox.showinfo("Resume", "Use the 'Resume incomplete downloads' option and Start.")
            except Exception as e:
                self._append_log("[ERROR]", f"Failed to resume: {e}")
        else:
            self.resume_var.set(True)
            self._start()

    def _stop(self):
        if self.runner.is_running():
            self._append_log("[INFO]", "Stopping download...")
            self.runner.stop()
            self.status_var.set("Stopping...")

    def _finish(self, run_state: str):
        self.overall_progress.stop()
        self.overall_progress.config(mode="determinate")
        self.stop_btn.config(state="disabled")
        self.pause_btn.config(state="disabled")
        self.start_btn.config(state="normal")

        # Auto-inject after successful download
        try:
            if run_state == "success" and self.auto_inject_var.get():
                snippet = self.locker_text.get("1.0", "end").strip()
                if snippet:
                    out_dir = Path(self.out_var.get().strip())
                    for candidate in self._find_index_candidates(out_dir):
                        try:
                            changed, where = self._inject_into_html_file(candidate, snippet)
                            if changed:
                                self._append_log("[INFO]", f"Auto-injected locker into: {where}")
                                break
                        except Exception as e:
                            self._append_log("[WARN]", f"Auto-inject failed on {candidate}: {e}")
        except Exception as e:
            self._append_log("[WARN]", f"Auto-inject step error: {e}")

        if run_state == "success":
            self.status_var.set("✓ Completed successfully")
            self.overall_progress.config(value=100)
            if self.open_folder_var.get():
                self.after(500, self._open_output_folder)
            if self.open_site_var.get():
                self.after(800, self._open_index_html)
            messagebox.showinfo("Download Complete", f"✓ Mirroring finished successfully!\n\nJob ID: {self.current_job_id}")
        elif run_state == "stopped":
            self.status_var.set("⏹ Stopped by user")
            messagebox.showinfo("Download Stopped", "Download was stopped by user.")
        else:
            self.status_var.set("✗ Error occurred")
            messagebox.showerror("Download Error", "Download failed. Check the logs for details.")

    def _open_output_folder(self):
        out_dir = self.out_var.get().strip()
        if not out_dir:
            messagebox.showinfo("Open Folder", "Please choose an output directory first.")
            return
        self._open_path(Path(out_dir))

    def _open_index_html(self):
        out_dir = Path(self.out_var.get().strip())
        candidates = [out_dir / "index.html", out_dir / "index.htm"]
        try:
            for child in out_dir.iterdir():
                if child.is_dir():
                    candidates.extend([child / "index.html", child / "index.htm"])
        except Exception:
            pass
        for c in candidates:
            if c.exists():
                self._open_path(c)
                return
        messagebox.showinfo("Open Site", "Could not find index.html in the output directory.")

    def _open_path(self, path: Path):
        try:
            if os.name == "nt":
                os.startfile(str(path))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as e:
            messagebox.showerror("Open Error", f"Failed to open:\n{path}\n\n{e}")

    def _append_log(self, level: str, message: str):
        timestamp = time.strftime("%H:%M:%S")
        entry = f"[{timestamp}] {level} {message}\n"
        current_filter = getattr(self, "log_level_var", tk.StringVar(value="ALL")).get()
        if current_filter != "ALL" and current_filter not in level:
            return
        self.log_txt.insert("end", entry)
        start = self.log_txt.index("end-2c linestart")
        end = self.log_txt.index("end-1c")
        if "[ERROR]" in level:
            self.log_txt.tag_add("error", start, end); self.log_txt.tag_config("error", foreground="red")
        elif "[WARN]" in level:
            self.log_txt.tag_add("warning", start, end); self.log_txt.tag_config("warning", foreground="orange")
        elif "[INFO]" in level:
            self.log_txt.tag_add("info", start, end); self.log_txt.tag_config("info", foreground="blue")
        self.log_txt.see("end")

    def _clear_log(self):
        self.log_txt.delete("1.0", "end")

    def _export_log(self):
        content = self.log_txt.get("1.0", "end")
        if not content.strip():
            messagebox.showinfo("Export Log", "Log is empty.")
            return
        fp = filedialog.asksaveasfilename(
            title="Export log",
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            initialname=f"httrack_gui_log_{time.strftime('%Y%m%d_%H%M%S')}.txt"
        )
        if fp:
            try:
                Path(fp).write_text(content, encoding="utf-8")
                messagebox.showinfo("Export Log", f"Log exported successfully to:\n{fp}")
            except Exception as e:
                messagebox.showerror("Export Error", f"Failed to export log:\n{e}")

    def _pump_logs(self):
        log_line = self.runner.poll_log_line()
        processed = False
        while log_line is not None:
            level, msg = log_line
            self._append_log(level, msg)
            processed = True
            log_line = self.runner.poll_log_line()
        if self.runner.is_running():
            rt = self.runner.get_runtime()
            self.time_label.config(text=f"Time: {rt}")
        if not self.runner.is_running() and processed:
            self.after(500, self._check_completion)
        self.after(200, self._pump_logs)

    def _pump_progress(self):
        info = self.runner.poll_progress()
        while info is not None:
            self._update_progress_display(info)
            info = self.runner.poll_progress()
        self.after(500, self._pump_progress)

    def _update_progress_display(self, info: Dict):
        if 'percentage' in info:
            pct = info['percentage']
            self.overall_progress.config(mode="determinate", value=pct)
            self.progress_label.config(text=f"Progress: {pct}%")
        if 'files' in info:
            done, total = info['files']
            self.files_label.config(text=f"Files: {done}/{total}")
        if 'bytes' in info:
            mb = info['bytes'] / (1024 * 1024)
            self.size_label.config(text=f"Size: {mb:.1f} MB")
        if 'current_url' in info:
            url = info['current_url']
            disp = url if len(url) <= 80 else (url[:77] + "...")
            self.status_var.set(f"Downloading: {disp}")

    def _check_completion(self):
        if self.runner.is_running():
            return
        log_content = self.log_txt.get("end-20l", "end").lower()
        if "finished successfully" in log_content:
            self._finish("success")
        elif "stopped" in log_content:
            self._finish("stopped")
        elif any(w in log_content for w in ("error", "failed", "exited with code")):
            self._finish("error")
        else:
            self._finish("success")

    def _save_config(self):
        try:
            self.config_manager.set("paths", "httrack_exe", self.exe_var.get())
            self.config_manager.set("paths", "output_dir", self.out_var.get())
            self.config_manager.set("options", "open_folder", str(self.open_folder_var.get()))
            self.config_manager.set("options", "open_site", str(self.open_site_var.get()))
            self.config_manager.set("options", "resume", str(self.resume_var.get()))
            self.config_manager.set("advanced", "max_speed", self.max_speed_var.get())
            self.config_manager.set("advanced", "max_connections", self.max_connections_var.get())
            self.config_manager.set("advanced", "max_depth", self.max_depth_var.get())
            self.config_manager.set("advanced", "max_files", self.max_files_var.get())
            self.config_manager.set("advanced", "max_size", self.max_size_var.get())
            self.config_manager.set("advanced", "custom_args", self.args_var.get())
            self.config_manager.save()
        except Exception as e:
            print(f"Failed to save config: {e}")

    def _load_config(self):
        try:
            exe_path = self.config_manager.get("paths", "httrack_exe")
            if exe_path and Path(exe_path).exists():
                self.exe_var.set(exe_path)
            output_dir = self.config_manager.get("paths", "output_dir")
            if output_dir:
                self.out_var.set(output_dir)
            self.open_folder_var.set(self.config_manager.get_bool("options", "open_folder", True))
            self.open_site_var.set(self.config_manager.get_bool("options", "open_site", False))
            self.resume_var.set(self.config_manager.get_bool("options", "resume", False))
            self.max_speed_var.set(self.config_manager.get("advanced", "max_speed"))
            self.max_connections_var.set(self.config_manager.get("advanced", "max_connections", "4"))
            self.max_depth_var.set(self.config_manager.get("advanced", "max_depth", "5"))
            self.max_files_var.set(self.config_manager.get("advanced", "max_files"))
            self.max_size_var.set(self.config_manager.get("advanced", "max_size"))
            self.args_var.set(self.config_manager.get("advanced", "custom_args"))
        except Exception as e:
            print(f"Failed to load config: {e}")

    def _on_close(self):
        if self.runner.is_running():
            if not messagebox.askyesno("Quit", "HTTrack is still running. Stop the download and exit?"):
                return
            self.runner.stop()
        self._save_config()
        self.destroy()


def main():
    try:
        app = App()
        app.mainloop()
    except KeyboardInterrupt:
        print("\nApplication interrupted by user.")
    except Exception as e:
        print(f"Fatal error: {e}")
        try:
            messagebox.showerror("Fatal Error", f"Application crashed:\n{e}")
        except Exception:
            pass


if __name__ == "__main__":
    main()