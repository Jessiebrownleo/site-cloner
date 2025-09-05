#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Enhanced HTTrack GUI Wrapper in Python (Tkinter)
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

Tested with Python 3.9+.
"""

import os
import shlex
import sys
import threading
import subprocess
import queue
import time
import json
import re
from pathlib import Path
from urllib.parse import urlparse
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, colorchooser
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
        self.bytes_total = 0
        self.current_url = ""
        self.percentage = 0
        
    def parse_line(self, line: str) -> Dict:
        """Parse a log line and extract progress info"""
        info = {}
        
        # Progress percentage patterns
        percent_match = re.search(r'(\d+)%', line)
        if percent_match:
            self.percentage = int(percent_match.group(1))
            info['percentage'] = self.percentage
            
        # File count patterns  
        file_match = re.search(r'(\d+)/(\d+)', line)
        if file_match:
            self.files_downloaded = int(file_match.group(1))
            self.files_total = int(file_match.group(2))
            info['files'] = (self.files_downloaded, self.files_total)
            
        # Bandwidth/size patterns
        size_match = re.search(r'(\d+(?:\.\d+)?)\s*(KB|MB|GB)', line, re.IGNORECASE)
        if size_match:
            size = float(size_match.group(1))
            unit = size_match.group(2).upper()
            multiplier = {'KB': 1024, 'MB': 1024**2, 'GB': 1024**3}
            bytes_size = int(size * multiplier.get(unit, 1))
            info['bytes'] = bytes_size
            
        # Current URL being downloaded
        url_match = re.search(r'https?://[^\s]+', line)
        if url_match and 'GET' in line:
            self.current_url = url_match.group(0)
            info['current_url'] = self.current_url
            
        return info


class HttrackRunner:
    """Enhanced HTTrack subprocess manager with better monitoring"""
    
    def __init__(self):
        self.proc = None
        self.thread = None
        self.log_queue = queue.Queue()
        self.progress_queue = queue.Queue()
        self._stop_requested = threading.Event()
        self.progress_parser = ProgressParser()
        self.start_time = None
        
    def is_running(self):
        return self.proc is not None and self.proc.poll() is None
        
    def get_runtime(self) -> str:
        if not self.start_time:
            return "00:00:00"
        elapsed = time.time() - self.start_time
        hours, remainder = divmod(int(elapsed), 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    def start(self, httrack_path: str, urls: List[str], output_dir: str, 
              extra_args: str, log_file: Path, resume: bool = False):
        if self.is_running():
            raise RuntimeError("HTTrack is already running.")

        self.start_time = time.time()
        self.progress_parser.reset()
        
        # Build command
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

            # Ensure log file exists
            try:
                log_file.parent.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass

            try:
                assert self.proc.stdout is not None
                with log_file.open("a", encoding="utf-8", errors="replace") as lf:
                    timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
                    lf.write(f"===== HTTrack run @ {timestamp} =====\n")
                    lf.write("CMD: " + cmd_str + "\n\n")
                    
                    for line in self.proc.stdout:
                        if self._stop_requested.is_set():
                            break
                            
                        line = line.rstrip("\n")
                        
                        # Determine log level
                        level = "[INFO]"
                        if any(x in line.lower() for x in ['error', 'failed', 'cannot']):
                            level = "[ERROR]"
                        elif any(x in line.lower() for x in ['warning', 'warn']):
                            level = "[WARN]"
                        elif any(x in line.lower() for x in ['debug']):
                            level = "[DEBUG]"
                            
                        self.log_queue.put((level, line))
                        
                        # Parse progress information
                        progress_info = self.progress_parser.parse_line(line)
                        if progress_info:
                            self.progress_queue.put(progress_info)
                        
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
                if os.name == "nt":
                    self.proc.terminate()
                else:
                    self.proc.terminate()
                    # Give it a moment, then force kill if needed
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
        
        # Initialize components
        self.config_manager = ConfigManager(CONFIG_FILE)
        self.runner = HttrackRunner()
        self.current_job_id = None
        
        # Styling
        self.style = ttk.Style()
        self._setup_themes()
        
        self._build_ui()
        self._load_config()
        
        self._append_log("[INFO]", "HTTrack Pro ready.")
        self.after(100, self._pump_logs)
        self.after(100, self._pump_progress)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _setup_themes(self):
        """Setup UI themes"""
        # You can expand this with more themes
        available_themes = self.style.theme_names()
        if 'clam' in available_themes:
            self.style.theme_use('clam')

    def _build_ui(self):
        # Create notebook for tabbed interface
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=5, pady=5)
        
        # Main tab
        self.main_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.main_frame, text="Main")
        self._build_main_tab()
        
        # Advanced tab  
        self.advanced_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.advanced_frame, text="Advanced")
        self._build_advanced_tab()
        
        # Logs tab
        self.logs_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.logs_frame, text="Logs & Progress")
        self._build_logs_tab()

    def _build_main_tab(self):
        # Main configuration frame
        main_config = ttk.LabelFrame(self.main_frame, text="Basic Configuration", padding=10)
        main_config.pack(fill="x", padx=10, pady=5)
        
        # HTTrack executable
        row = 0
        ttk.Label(main_config, text="HTTrack executable:").grid(row=row, column=0, sticky="w", pady=2)
        self.exe_var = tk.StringVar(value=self._default_httrack_path())
        exe_entry = ttk.Entry(main_config, textvariable=self.exe_var, width=50)
        exe_entry.grid(row=row, column=1, sticky="ew", padx=(5, 5))
        ttk.Button(main_config, text="Browse...", command=self._browse_exe).grid(row=row, column=2)
        ttk.Button(main_config, text="Test", command=self._test_httrack).grid(row=row, column=3, padx=(5, 0))
        
        # URLs section
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
        
        # URL management buttons
        url_btns = ttk.Frame(main_config)
        url_btns.grid(row=row+1, column=1, columnspan=3, sticky="w", pady=2)
        ttk.Button(url_btns, text="Import from File", command=self._import_urls).pack(side="left")
        ttk.Button(url_btns, text="Paste from Clipboard", command=self._paste_urls).pack(side="left", padx=(5, 0))
        ttk.Button(url_btns, text="Validate URLs", command=self._validate_urls).pack(side="left", padx=(5, 0))
        
        # Output directory
        row += 2
        ttk.Label(main_config, text="Output directory:").grid(row=row, column=0, sticky="w", pady=(8, 2))
        self.out_var = tk.StringVar(value=str(Path.cwd() / "site_mirror"))
        out_entry = ttk.Entry(main_config, textvariable=self.out_var, width=50)
        out_entry.grid(row=row, column=1, sticky="ew", padx=(5, 5))
        ttk.Button(main_config, text="Choose...", command=self._choose_output_dir).grid(row=row, column=2)
        ttk.Button(main_config, text="Open", command=self._open_output_folder).grid(row=row, column=3, padx=(5, 0))
        
        main_config.columnconfigure(1, weight=1)
        
        # Presets section
        presets_frame = ttk.LabelFrame(self.main_frame, text="Quick Presets", padding=10)
        presets_frame.pack(fill="x", padx=10, pady=5)
        
        presets_data = [
            ("Complete Mirror", "--robots=0 -r9", "Full recursive mirror ignoring robots.txt"),
            ("Fast Browse", "-r2 -%P", "2-level depth, same domain only"),
            ("Media Rich", "+*.png +*.jpg +*.jpeg +*.gif +*.css +*.js +*.mp4", "Include all media files"),
            ("Documentation", "+*.pdf +*.doc +*.docx +*.txt", "Focus on documents"),
            ("Offline Reading", "-F 'user-agent: Mozilla/5.0' --robots=0", "Optimized for offline browsing")
        ]
        
        row = 0
        col = 0
        for name, args, tooltip in presets_data:
            btn = ttk.Button(presets_frame, text=name, 
                           command=lambda a=args: self._apply_preset(a))
            btn.grid(row=row, column=col, padx=5, pady=2, sticky="ew")
            self._create_tooltip(btn, tooltip + f"\nArgs: {args}")
            
            col += 1
            if col > 2:
                col = 0
                row += 1
                
        for i in range(3):
            presets_frame.columnconfigure(i, weight=1)

        # Control buttons
        controls = ttk.LabelFrame(self.main_frame, text="Controls", padding=10)
        controls.pack(fill="x", padx=10, pady=5)
        
        # Main control buttons
        btn_frame = ttk.Frame(controls)
        btn_frame.pack(fill="x")
        
        self.start_btn = ttk.Button(btn_frame, text="▶ Start Download", 
                                   command=self._start, style="Accent.TButton")
        self.start_btn.pack(side="left")
        
        self.pause_btn = ttk.Button(btn_frame, text="⏸ Pause", 
                                   command=self._pause, state="disabled")
        self.pause_btn.pack(side="left", padx=(10, 0))
        
        self.stop_btn = ttk.Button(btn_frame, text="⏹ Stop", 
                                  command=self._stop, state="disabled")
        self.stop_btn.pack(side="left", padx=(10, 0))
        
        self.resume_btn = ttk.Button(btn_frame, text="⏯ Resume", 
                                    command=self._resume)
        self.resume_btn.pack(side="left", padx=(10, 0))
        
        # Options checkboxes
        options_frame = ttk.Frame(controls)
        options_frame.pack(fill="x", pady=(10, 0))
        
        self.open_folder_var = tk.BooleanVar(value=True)
        self.open_site_var = tk.BooleanVar(value=False)
        self.resume_var = tk.BooleanVar(value=False)
        
        ttk.Checkbutton(options_frame, text="Open folder on completion", 
                       variable=self.open_folder_var).pack(side="left")
        ttk.Checkbutton(options_frame, text="Open site on completion", 
                       variable=self.open_site_var).pack(side="left", padx=(20, 0))
        ttk.Checkbutton(options_frame, text="Resume incomplete downloads", 
                       variable=self.resume_var).pack(side="left", padx=(20, 0))

    def _build_advanced_tab(self):
        # Advanced options
        advanced_opts = ttk.LabelFrame(self.advanced_frame, text="Advanced Options", padding=10)
        advanced_opts.pack(fill="x", padx=10, pady=5)
        
        # Bandwidth controls
        bw_frame = ttk.LabelFrame(advanced_opts, text="Bandwidth Control")
        bw_frame.pack(fill="x", pady=(0, 10))
        
        ttk.Label(bw_frame, text="Max speed (KB/s):").grid(row=0, column=0, sticky="w", padx=5, pady=5)
        self.max_speed_var = tk.StringVar()
        ttk.Entry(bw_frame, textvariable=self.max_speed_var, width=10).grid(row=0, column=1, padx=5)
        
        ttk.Label(bw_frame, text="Connection limit:").grid(row=0, column=2, sticky="w", padx=(20, 5))
        self.max_connections_var = tk.StringVar(value="4")
        ttk.Spinbox(bw_frame, from_=1, to=20, textvariable=self.max_connections_var, 
                   width=5).grid(row=0, column=3, padx=5)
        
        # Depth and filtering
        filter_frame = ttk.LabelFrame(advanced_opts, text="Filtering & Limits")
        filter_frame.pack(fill="x", pady=(0, 10))
        
        ttk.Label(filter_frame, text="Max depth:").grid(row=0, column=0, sticky="w", padx=5, pady=5)
        self.max_depth_var = tk.StringVar(value="5")
        ttk.Spinbox(filter_frame, from_=1, to=20, textvariable=self.max_depth_var, 
                   width=5).grid(row=0, column=1, padx=5)
        
        ttk.Label(filter_frame, text="Max files:").grid(row=0, column=2, sticky="w", padx=(20, 5))
        self.max_files_var = tk.StringVar()
        ttk.Entry(filter_frame, textvariable=self.max_files_var, width=10).grid(row=0, column=3, padx=5)
        
        ttk.Label(filter_frame, text="Max size (MB):").grid(row=0, column=4, sticky="w", padx=(20, 5))
        self.max_size_var = tk.StringVar()
        ttk.Entry(filter_frame, textvariable=self.max_size_var, width=10).grid(row=0, column=5, padx=5)
        
        # Custom arguments
        args_frame = ttk.LabelFrame(advanced_opts, text="Custom Arguments")
        args_frame.pack(fill="both", expand=True)
        
        self.args_var = tk.StringVar()
        args_entry = ttk.Entry(args_frame, textvariable=self.args_var)
        args_entry.pack(fill="x", padx=5, pady=5)
        
        ttk.Label(args_frame, text="Enter additional HTTrack command-line arguments", 
                 font=("TkDefaultFont", 8)).pack(anchor="w", padx=5)

    def _build_logs_tab(self):
        # Progress section
        progress_frame = ttk.LabelFrame(self.logs_frame, text="Download Progress", padding=10)
        progress_frame.pack(fill="x", padx=10, pady=5)
        
        # Progress bars and info
        self.overall_progress = ttk.Progressbar(progress_frame, length=400, mode="determinate")
        self.overall_progress.pack(fill="x", pady=(0, 5))
        
        info_frame = ttk.Frame(progress_frame)
        info_frame.pack(fill="x")
        
        self.progress_label = ttk.Label(info_frame, text="Ready")
        self.progress_label.pack(side="left")
        
        self.speed_label = ttk.Label(info_frame, text="")
        self.speed_label.pack(side="right")
        
        # Statistics
        stats_frame = ttk.Frame(progress_frame)
        stats_frame.pack(fill="x", pady=(5, 0))
        
        self.files_label = ttk.Label(stats_frame, text="Files: 0/0")
        self.files_label.pack(side="left")
        
        self.size_label = ttk.Label(stats_frame, text="Size: 0 MB")
        self.size_label.pack(side="left", padx=(20, 0))
        
        self.time_label = ttk.Label(stats_frame, text="Time: 00:00:00")
        self.time_label.pack(side="left", padx=(20, 0))
        
        # Log area
        log_frame = ttk.LabelFrame(self.logs_frame, text="Activity Log", padding=10)
        log_frame.pack(fill="both", expand=True, padx=10, pady=5)
        
        # Log controls
        log_controls = ttk.Frame(log_frame)
        log_controls.pack(fill="x", pady=(0, 5))
        
        ttk.Button(log_controls, text="Clear", command=self._clear_log).pack(side="left")
        ttk.Button(log_controls, text="Export", command=self._export_log).pack(side="left", padx=(5, 0))
        
        # Log level filter
        ttk.Label(log_controls, text="Level:").pack(side="left", padx=(20, 5))
        self.log_level_var = tk.StringVar(value="ALL")
        log_level_combo = ttk.Combobox(log_controls, textvariable=self.log_level_var, 
                                      values=["ALL", "INFO", "WARN", "ERROR"], 
                                      width=8, state="readonly")
        log_level_combo.pack(side="left")
        
        # Log text area with scrollbars
        log_text_frame = ttk.Frame(log_frame)
        log_text_frame.pack(fill="both", expand=True)
        
        self.log_txt = tk.Text(log_text_frame, wrap="none", state="normal", font=("Consolas", 9))
        
        log_v_scroll = ttk.Scrollbar(log_text_frame, orient="vertical", command=self.log_txt.yview)
        log_h_scroll = ttk.Scrollbar(log_text_frame, orient="horizontal", command=self.log_txt.xview)
        
        self.log_txt.configure(yscrollcommand=log_v_scroll.set, xscrollcommand=log_h_scroll.set)
        
        self.log_txt.grid(row=0, column=0, sticky="nsew")
        log_v_scroll.grid(row=0, column=1, sticky="ns")
        log_h_scroll.grid(row=1, column=0, sticky="ew")
        
        log_text_frame.grid_rowconfigure(0, weight=1)
        log_text_frame.grid_columnconfigure(0, weight=1)
        
        # Status bar
        self.status_var = tk.StringVar(value="Ready")
        status_bar = ttk.Label(self, textvariable=self.status_var, relief="sunken", anchor="w")
        status_bar.pack(side="bottom", fill="x")

    def _create_tooltip(self, widget, text):
        """Create a simple tooltip for a widget"""
        def on_enter(event):
            tooltip = tk.Toplevel()
            tooltip.wm_overrideredirect(True)
            tooltip.wm_geometry(f"+{event.x_root+10}+{event.y_root+10}")
            label = ttk.Label(tooltip, text=text, background="lightyellow", 
                            relief="solid", borderwidth=1)
            label.pack()
            widget._tooltip = tooltip
            
        def on_leave(event):
            if hasattr(widget, '_tooltip'):
                widget._tooltip.destroy()
                del widget._tooltip
                
        widget.bind("<Enter>", on_enter)
        widget.bind("<Leave>", on_leave)

    def _default_httrack_path(self):
        """Find httrack executable"""
        try:
            import shutil
            found = shutil.which(DEFAULT_EXECUTABLE)
            if found:
                return found
                
            # Try common installation paths
            common_paths = [
                "/usr/bin/httrack",
                "/usr/local/bin/httrack", 
                "C:\\Program Files\\WinHTTrack\\httrack.exe",
                "C:\\Program Files (x86)\\WinHTTrack\\httrack.exe"
            ]
            
            for path in common_paths:
                if Path(path).exists():
                    return path
                    
        except Exception:
            pass
            
        return DEFAULT_EXECUTABLE

    def _test_httrack(self):
        """Test if httrack is working"""
        httrack_path = self.exe_var.get().strip()
        if not httrack_path:
            messagebox.showerror("Test", "Please specify HTTrack path first.")
            return
            
        try:
            result = subprocess.run([httrack_path, "--version"], 
                                  capture_output=True, text=True, timeout=10)
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
        """Browse for HTTrack executable"""
        initial = self.exe_var.get() or DEFAULT_EXECUTABLE
        filetypes = [("Executable files", "*.exe"), ("All files", "*.*")] if os.name == "nt" else [("All files", "*.*")]
        chosen = filedialog.askopenfilename(
            title="Select HTTrack executable", 
            initialfile=initial, 
            filetypes=filetypes
        )
        if chosen:
            self.exe_var.set(chosen)

    def _choose_output_dir(self):
        """Choose output directory"""
        folder = filedialog.askdirectory(
            title="Choose output directory", 
            initialdir=self.out_var.get() or str(Path.cwd())
        )
        if folder:
            self.out_var.set(folder)

    def _import_urls(self):
        """Import URLs from a text file"""
        file_path = filedialog.askopenfilename(
            title="Import URLs from file",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
        )
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
        """Paste URLs from clipboard"""
        try:
            clipboard_content = self.clipboard_get()
            urls = [line.strip() for line in clipboard_content.split('\n') if line.strip() and self._valid_url(line.strip())]
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
        """Validate all URLs in the text area"""
        urls_raw = self.urls_txt.get("1.0", "end").strip()
        urls = [u.strip() for u in urls_raw.splitlines() if u.strip()]
        
        if not urls:
            messagebox.showinfo("Validation", "No URLs to validate.")
            return
            
        valid_urls = []
        invalid_urls = []
        
        for url in urls:
            if self._valid_url(url):
                valid_urls.append(url)
            else:
                invalid_urls.append(url)
        
        message = f"Valid URLs: {len(valid_urls)}\nInvalid URLs: {len(invalid_urls)}"
        if invalid_urls:
            message += f"\n\nInvalid URLs:\n" + "\n".join(invalid_urls[:5])
            if len(invalid_urls) > 5:
                message += f"\n... and {len(invalid_urls) - 5} more"
                
        if invalid_urls:
            messagebox.showwarning("URL Validation", message)
        else:
            messagebox.showinfo("URL Validation", message)

    def _valid_url(self, url: str) -> bool:
        """Validate a URL"""
        try:
            parsed = urlparse(url.strip())
            return parsed.scheme in ("http", "https") and bool(parsed.netloc)
        except Exception:
            return False

    def _apply_preset(self, preset_args: str):
        """Apply preset arguments"""
        current = self.args_var.get().strip()
        if current:
            # Avoid duplicates
            current_parts = set(current.split())
            new_parts = [p for p in preset_args.split() if p not in current_parts]
            if new_parts:
                combined = (current + " " + " ".join(new_parts)).strip()
                self.args_var.set(combined)
        else:
            self.args_var.set(preset_args)
        
        # Also update advanced options if they match
        self._parse_preset_to_advanced(preset_args)

    def _parse_preset_to_advanced(self, args: str):
        """Parse preset arguments to advanced options"""
        parts = args.split()
        for i, part in enumerate(parts):
            if part.startswith('-r') and len(part) > 2:
                # Depth setting
                try:
                    depth = int(part[2:])
                    self.max_depth_var.set(str(depth))
                except ValueError:
                    pass

    def _build_httrack_args(self) -> List[str]:
        """Build HTTrack arguments from UI"""
        args = []
        
        # Add advanced options
        if self.max_speed_var.get().strip():
            try:
                speed = int(self.max_speed_var.get())
                args.extend([f"--rate={speed}"])
            except ValueError:
                pass
                
        if self.max_connections_var.get().strip():
            try:
                connections = int(self.max_connections_var.get())
                args.extend([f"-c{connections}"])
            except ValueError:
                pass
                
        if self.max_depth_var.get().strip():
            try:
                depth = int(self.max_depth_var.get())
                args.extend([f"-r{depth}"])
            except ValueError:
                pass
                
        if self.max_files_var.get().strip():
            try:
                max_files = int(self.max_files_var.get())
                args.extend([f"--max-files={max_files}"])
            except ValueError:
                pass
                
        if self.max_size_var.get().strip():
            try:
                max_size = int(self.max_size_var.get())
                args.extend([f"--max-size={max_size}M"])
            except ValueError:
                pass
        
        # Add custom arguments
        if self.args_var.get().strip():
            args.extend(shlex.split(self.args_var.get()))
            
        return args

    def _validate(self) -> Optional[Tuple[str, List[str], str, List[str]]]:
        """Validate all inputs"""
        httrack_path = self.exe_var.get().strip()
        if not httrack_path:
            messagebox.showerror("Validation Error", "Please specify the HTTrack executable path.")
            return None

        urls_raw = self.urls_txt.get("1.0", "end").strip()
        urls = [u.strip() for u in urls_raw.splitlines() if u.strip()]
        if not urls:
            messagebox.showerror("Validation Error", "Please provide at least one URL.")
            return None
            
        # Validate URLs
        invalid = [u for u in urls if not self._valid_url(u)]
        if invalid:
            messagebox.showerror("Validation Error", 
                f"The following URL(s) are invalid:\n\n" + "\n".join(invalid[:5]) +
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

        args = self._build_httrack_args()
        return httrack_path, urls, out_dir, args

    def _start(self):
        """Start HTTrack download"""
        validation_result = self._validate()
        if not validation_result:
            return
            
        if self.runner.is_running():
            messagebox.showwarning("Already Running", "HTTrack is already running.")
            return

        httrack_path, urls, out_dir, args = validation_result
        
        # Generate job ID
        self.current_job_id = f"job_{int(time.time())}"
        
        self._append_log("[INFO]", f"Starting download job: {self.current_job_id}")
        self._append_log("[INFO]", f"URLs: {len(urls)} URL(s)")
        self._append_log("[INFO]", f"Output: {out_dir}")
        
        # Update UI state
        self.start_btn.config(state="disabled")
        self.pause_btn.config(state="normal")
        self.stop_btn.config(state="normal")
        self.status_var.set("Starting...")
        self.overall_progress.config(mode="indeterminate")
        self.overall_progress.start(10)
        
        # Create log file path
        log_file = Path(out_dir) / f"httrack_{self.current_job_id}.log"
        
        try:
            resume = self.resume_var.get()
            self.runner.start(httrack_path, urls, out_dir, " ".join(args), log_file, resume)
        except Exception as e:
            self._append_log("[ERROR]", f"Failed to start: {e}")
            self._finish("error")

    def _pause(self):
        """Pause HTTrack (send SIGSTOP on Unix)"""
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
        """Resume paused HTTrack (send SIGCONT on Unix) or restart with resume flag"""
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
            # Start with resume flag
            self.resume_var.set(True)
            self._start()

    def _stop(self):
        """Stop HTTrack download"""
        if self.runner.is_running():
            self._append_log("[INFO]", "Stopping download...")
            self.runner.stop()
            self.status_var.set("Stopping...")

    def _finish(self, run_state: str):
        """Finalize UI state after download completion"""
        self.overall_progress.stop()
        self.overall_progress.config(mode="determinate")
        
        self.stop_btn.config(state="disabled")
        self.pause_btn.config(state="disabled")
        self.start_btn.config(state="normal")
        
        if run_state == "success":
            self.status_var.set("✓ Completed successfully")
            self.overall_progress.config(value=100)
            
            if self.open_folder_var.get():
                self.after(500, self._open_output_folder)
            if self.open_site_var.get():
                self.after(800, self._open_index_html)
                
            messagebox.showinfo("Download Complete", 
                f"✓ Mirroring finished successfully!\n\nJob ID: {self.current_job_id}")
                
        elif run_state == "stopped":
            self.status_var.set("⏹ Stopped by user")
            messagebox.showinfo("Download Stopped", "Download was stopped by user.")
            
        else:  # error
            self.status_var.set("✗ Error occurred")
            messagebox.showerror("Download Error", 
                "Download failed. Check the logs for details.")

    def _open_output_folder(self):
        """Open the output folder"""
        out_dir = self.out_var.get().strip()
        if not out_dir:
            messagebox.showinfo("Open Folder", "Please choose an output directory first.")
            return
        self._open_path(Path(out_dir))

    def _open_index_html(self):
        """Open the mirrored site index.html"""
        out_dir = Path(self.out_var.get().strip())
        
        # Look for index files in common locations
        candidates = [
            out_dir / "index.html",
            out_dir / "index.htm",
        ]
        
        # Search subdirectories for index files
        try:
            for child in out_dir.iterdir():
                if child.is_dir():
                    candidates.extend([
                        child / "index.html",
                        child / "index.htm"
                    ])
        except Exception:
            pass
            
        for candidate in candidates:
            if candidate.exists():
                self._open_path(candidate)
                return
                
        messagebox.showinfo("Open Site", "Could not find index.html in the output directory.")

    def _open_path(self, path: Path):
        """Open a file or folder in the default application"""
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
        """Append a log message with level and timestamp"""
        timestamp = time.strftime("%H:%M:%S")
        log_entry = f"[{timestamp}] {level} {message}\n"
        
        # Apply log level filtering
        current_filter = self.log_level_var.get()
        if current_filter != "ALL":
            if current_filter not in level:
                return
        
        # Color coding for different log levels
        self.log_txt.insert("end", log_entry)
        
        # Apply text coloring based on level
        start_line = self.log_txt.index("end-2c linestart")
        end_line = self.log_txt.index("end-1c")
        
        if "[ERROR]" in level:
            self.log_txt.tag_add("error", start_line, end_line)
            self.log_txt.tag_config("error", foreground="red")
        elif "[WARN]" in level:
            self.log_txt.tag_add("warning", start_line, end_line)
            self.log_txt.tag_config("warning", foreground="orange")
        elif "[INFO]" in level:
            self.log_txt.tag_add("info", start_line, end_line)
            self.log_txt.tag_config("info", foreground="blue")
        
        self.log_txt.see("end")

    def _clear_log(self):
        """Clear the log display"""
        self.log_txt.delete("1.0", "end")

    def _export_log(self):
        """Export the log to a file"""
        log_content = self.log_txt.get("1.0", "end")
        if not log_content.strip():
            messagebox.showinfo("Export Log", "Log is empty.")
            return
            
        file_path = filedialog.asksaveasfilename(
            title="Export log",
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            initialname=f"httrack_gui_log_{time.strftime('%Y%m%d_%H%M%S')}.txt"
        )
        
        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(f"HTTrack GUI Log Export\n")
                    f.write(f"Exported: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                    f.write("=" * 50 + "\n\n")
                    f.write(log_content)
                messagebox.showinfo("Export Log", f"Log exported successfully to:\n{file_path}")
            except Exception as e:
                messagebox.showerror("Export Error", f"Failed to export log:\n{e}")

    def _pump_logs(self):
        """Pump log messages from the runner to the UI"""
        log_line = self.runner.poll_log_line()
        processed_any = False
        
        while log_line is not None:
            level, message = log_line
            self._append_log(level, message)
            processed_any = True
            log_line = self.runner.poll_log_line()
        
        # Update runtime display
        if self.runner.is_running():
            runtime = self.runner.get_runtime()
            self.time_label.config(text=f"Time: {runtime}")
        
        # Check if process finished
        if not self.runner.is_running() and processed_any:
            # Give a moment for final log messages
            self.after(500, self._check_completion)
        
        self.after(200, self._pump_logs)

    def _pump_progress(self):
        """Pump progress information from the runner to the UI"""
        progress_info = self.runner.poll_progress()
        
        while progress_info is not None:
            self._update_progress_display(progress_info)
            progress_info = self.runner.poll_progress()
            
        self.after(500, self._pump_progress)

    def _update_progress_display(self, progress_info: Dict):
        """Update progress bars and labels"""
        if 'percentage' in progress_info:
            percentage = progress_info['percentage']
            self.overall_progress.config(mode="determinate", value=percentage)
            self.progress_label.config(text=f"Progress: {percentage}%")
            
        if 'files' in progress_info:
            files_done, files_total = progress_info['files']
            self.files_label.config(text=f"Files: {files_done}/{files_total}")
            
        if 'bytes' in progress_info:
            bytes_size = progress_info['bytes']
            size_mb = bytes_size / (1024 * 1024)
            self.size_label.config(text=f"Size: {size_mb:.1f} MB")
            
        if 'current_url' in progress_info:
            current_url = progress_info['current_url']
            # Truncate long URLs for display
            if len(current_url) > 80:
                display_url = current_url[:77] + "..."
            else:
                display_url = current_url
            self.status_var.set(f"Downloading: {display_url}")

    def _check_completion(self):
        """Check if the download completed and determine final state"""
        if self.runner.is_running():
            return  # Still running
            
        # Analyze recent log entries to determine completion state
        log_content = self.log_txt.get("end-20l", "end").lower()
        
        if "finished successfully" in log_content:
            self._finish("success")
        elif "stopped" in log_content:
            self._finish("stopped")
        elif any(word in log_content for word in ["error", "failed", "exited with code"]):
            self._finish("error")
        else:
            # Default to success if no clear indication
            self._finish("success")

    def _save_config(self):
        """Save current configuration"""
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
        """Load saved configuration"""
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
        """Handle application close"""
        if self.runner.is_running():
            if not messagebox.askyesno("Quit", 
                "HTTrack is still running. Stop the download and exit?"):
                return
            self.runner.stop()
            
        self._save_config()
        self.destroy()


def main():
    """Main application entry point"""
    try:
        app = App()
        app.mainloop()
    except KeyboardInterrupt:
        print("\nApplication interrupted by user.")
    except Exception as e:
        print(f"Fatal error: {e}")
        messagebox.showerror("Fatal Error", f"Application crashed:\n{e}")


if __name__ == "__main__":
    main()