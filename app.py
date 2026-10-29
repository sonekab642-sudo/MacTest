# --- START OF FILE app.py (Full TERNAL for macOS & Linux) ---

import os
import sys
import time
import subprocess
import html
import re
import pty
import termios
import struct
import fcntl
import errno
import threading
import signal

# 🛑 1. ZeroGPU সেফটি (হাগিংফেস ও গিটহাব উভয়ের জন্য সেফ)
try:
    import spaces
    has_spaces = True
except ImportError:
    has_spaces = False

# 🛑 ২. সক্রিয় প্রসেস ট্র্যাকিং (ইনস্ট্যান্ট কিলার)
active_process = None

def kill_active_process():
    """চলমান প্রসেস ও তার সমস্ত চাইল্ড প্রসেসকে ০ মিলিসেকেন্ডে SIGKILL দিয়ে থামানো"""
    global active_process
    if active_process:
        try:
            pgid = os.getpgid(active_process.pid)
            os.killpg(pgid, signal.SIGTERM)
            os.killpg(pgid, signal.SIGKILL)
        except Exception:
            try:
                active_process.kill()
            except Exception:
                pass
        active_process = None

# pip root warning বন্ধ করা
os.environ["PIP_ROOT_USER_ACTION"] = "ignore"

for pkg in ["gradio", "psutil", "pygments", "ansi2html"]:
    try:
        __import__(pkg)
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", pkg, "-q"], check=True)

import gradio as gr
import psutil

from pygments import highlight
from pygments.lexers import BashLexer
from pygments.formatters import HtmlFormatter
from ansi2html import Ansi2HTMLConverter

current_working_dir = os.path.expanduser("~")
initial_text = "<div id='welcome_msg' style='color:#7ee787; font-size:11px;'>[ TERNAL Engine is Live & Ready...]</div>"

RE_CMD_NOT_FOUND = re.compile(r"(?:/bin/bash|/bin/sh|/bin/zsh|zsh|bash):\s*(?:line\s*\d+:\s*)?([a-zA-Z0-9_\-\.]+):\s*(?:command\s*)?not found", re.IGNORECASE)
RE_MOD_NOT_FOUND = re.compile(r"ModuleNotFoundError:\s*No module named ['\"]([^'\"]+)['\"]")

# অটো-পাইলট প্যাকেজ রেজলভার (Mac ও Linux উভয়ের জন্য)
def resolve_missing_package(missing_cmd):
    if sys.platform == "darwin":
        # macOS এ Homebrew চেক
        try:
            res = subprocess.run(f"brew search --formula '^{missing_cmd}$'", shell=True, capture_output=True, text=True, timeout=5)
            lines = res.stdout.strip().split('\n')
            if lines and lines[0] and "No formulae" not in lines[0]:
                return lines[0].strip(), "brew"
        except Exception:
            pass
        return missing_cmd, "brew"
    else:
        # Linux / Ubuntu
        try:
            res = subprocess.run(["/usr/lib/command-not-found", "--", missing_cmd], capture_output=True, text=True, timeout=5)
            matches = re.findall(r'apt(?:-get)?\s+install\s+([a-zA-Z0-9_\-\.]+)', res.stdout + res.stderr)
            if matches:
                return matches[0], "apt"
        except Exception:
            pass
        return missing_cmd, "apt"

def detect_missing_command(ret_code, out_buf, full_cmd):
    if ret_code == 127 or "not found" in out_buf.lower():
        match = RE_CMD_NOT_FOUND.search(out_buf)
        if match:
            return match.group(1).strip()
        parts = full_cmd.strip().split()
        if parts:
            return parts[0]
    return None

def detect_missing_module(out_buf):
    match = RE_MOD_NOT_FOUND.search(out_buf)
    if match:
        raw_mod = match.group(1).strip()
        return raw_mod.split('.')[0]
    return None

# ==========================================
# 💎 ULTRA-MAX COLOR & VT100 CLEANER
# ==========================================
cmd_formatter = HtmlFormatter(nowrap=True, noclasses=True, style="monokai")
ansi_converter = Ansi2HTMLConverter(inline=True, dark_bg=True)

def pygments_colorize_cmd(cmd_text):
    try:
        return highlight(cmd_text, BashLexer(), cmd_formatter).strip()
    except Exception:
        return html.escape(cmd_text)

def clean_carriage_returns(text):
    normalized = text.replace('\r\n', '\n')
    lines = []
    for line in normalized.split('\n'):
        if '\r' in line:
            parts = [p for p in line.split('\r') if p]
            lines.append(parts[-1] if parts else '')
        else:
            lines.append(line)
    return '\n'.join(lines)

def strip_terminal_artifacts(text):
    text = re.sub(r'\x1b\[\?[0-9]+[a-zA-Z]', '', text)
    text = re.sub(r'\x1b\[[0-9;]*[A-Za-z]', lambda m: m.group(0) if m.group(0).endswith('m') else '', text)
    text = re.sub(
        r'WARNING: Running pip as the [\'"]root[\'"] user can result in broken permissions.*?(?:suppress this warning\.|https://pip\.pypa\.io/warnings/venv\b.*?\n)',
        '',
        text,
        flags=re.DOTALL | re.IGNORECASE
    )
    return text

def ultra_color_engine(raw_text):
    if not raw_text:
        return ""

    cleaned = clean_carriage_returns(raw_text)
    cleaned = strip_terminal_artifacts(cleaned)

    try:
        html_out = ansi_converter.convert(cleaned, full=False)
    except Exception:
        html_out = html.escape(cleaned)

    html_out = re.sub(
        r'(Traceback \(most recent call last\):)',
        r'<span style="color: #ff5555; font-weight: bold; background: rgba(255,85,85,0.18); padding: 1px 6px; border-radius: 4px;">\1</span>',
        html_out
    )
    html_out = re.sub(
        r'(\b[A-Za-z0-9_]+Error:|\b[A-Za-z0-9_]+Exception:|\bCRITICAL:|\bFATAL:)',
        r'<span style="color: #ff5555; font-weight: bold; text-shadow: 0 0 8px rgba(255,85,85,0.6);">\1</span>',
        html_out
    )
    html_out = re.sub(r'(\bWARNING:|\bWARN:|\bAlert:)', r'<span style="color: #ffb86c; font-weight: bold;">\1</span>', html_out)
    html_out = re.sub(r'(\bRequirement already satisfied:)', r'<span style="color: #50fa7b; font-weight: bold;">\1</span>', html_out)
    html_out = re.sub(r'(File &quot;.*?&quot;, line \d+)', r'<span style="color: #8be9fd; font-weight: 600;">\1</span>', html_out)
    html_out = re.sub(r'\b(\d+(?:\.\d+)?\s*(?:MB/s|KB/s|GB/s|B/s))\b', r'<span style="color: #f1fa8c; font-weight: bold;">\1</span>', html_out)
    html_out = re.sub(r'([\w.-]+(?:\.whl|\.tar\.gz|\.safetensors|\.bin|\.pt))\b', r'<span style="color: #ff79c6; font-weight: 600;">\1</span>', html_out)
    html_out = re.sub(r'(\[Process exited with code 0\])', r'<span style="color: #50fa7b; font-weight: bold;">\1</span>', html_out)
    html_out = re.sub(r'(\[Process terminated by user\])', r'<span style="color: #ffb86c; font-weight: bold; background: rgba(255,184,108,0.15); padding: 2px 6px; border-radius: 4px;">\1</span>', html_out)
    html_out = re.sub(r'(\[Process exited with code [1-9]\d*\])', r'<span style="color: #ff5555; font-weight: bold;">\1</span>', html_out)

    return html_out

def format_with_cursor(painted_text, cursor_tag):
    clean_text = painted_text.rstrip('\r\n')
    return f"{clean_text}{cursor_tag}" if clean_text else cursor_tag

# ==========================================
# 💎 REALTIME PTY STREAM RUNNER (SSH FEEL)
# ==========================================
def run_pty_stream(cmd_str, history_base):
    global current_working_dir, active_process
    
    cursor_tag = "<span class='term-cursor'>|</span>"
    master_fd, slave_fd = pty.openpty()
    
    try:
        winsize = struct.pack("HHHH", 30, 80, 0, 0)
        fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, winsize)
        attrs = termios.tcgetattr(slave_fd)
        attrs[3] = attrs[3] & ~termios.ECHO
        termios.tcsetattr(slave_fd, termios.TCSANOW, attrs)
    except Exception:
        pass

    try:
        env = os.environ.copy()
        env["OMP_NUM_THREADS"] = "8"
        env["PYTHONUNBUFFERED"] = "1"
        env["TERM"] = "xterm-256color"
        env["COLORTERM"] = "truecolor"
        env["CLICOLOR_FORCE"] = "1"
        env["FORCE_COLOR"] = "1"

        shell_exec = "/bin/zsh" if os.path.exists("/bin/zsh") else "/bin/bash"

        process = subprocess.Popen(
            cmd_str,
            shell=True,
            executable=shell_exec,
            cwd=current_working_dir,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            close_fds=True,
            start_new_session=True,
            env=env
        )
        active_process = process
    finally:
        os.close(slave_fd)

    output_buffer = ""
    last_yield_time = time.time()
    MAX_CHARS = 70000

    try:
        os.set_blocking(master_fd, False)
        while True:
            try:
                raw_bytes = os.read(master_fd, 4096)
                if raw_bytes:
                    output_buffer += raw_bytes.decode("utf-8", errors="replace")
                    current_time = time.time()
                    
                    # রিয়েলটাইমে লাইভ বাফারিং ডিসপ্লে
                    if current_time - last_yield_time >= 0.04:
                        display_text = output_buffer
                        if len(display_text) > MAX_CHARS:
                            display_text = "[... Truncated early logs ...]\n" + display_text[-MAX_CHARS:]
                        painted_out = ultra_color_engine(display_text)
                        live_content = format_with_cursor(painted_out, cursor_tag)
                        out_html = f"<div class='term-block'><pre>{live_content}</pre></div>"
                        yield history_base + out_html, ""
                        last_yield_time = current_time
                else:
                    break
            except (BlockingIOError, OSError) as e:
                if isinstance(e, OSError) and e.errno == errno.EIO:
                    break
                if process.poll() is not None:
                    time.sleep(0.02)
                    while True:
                        try:
                            rem = os.read(master_fd, 4096)
                            if rem:
                                output_buffer += rem.decode("utf-8", errors="replace")
                            else:
                                break
                        except Exception:
                            break
                    break
                time.sleep(0.01)

        return_code = process.poll()
        if return_code is not None and return_code != 0:
            if return_code in [-2, -15, -9, 130, 137]:
                output_buffer += "\n^C\n[Process terminated by user]"
            else:
                output_buffer += f"\n[Process exited with code {return_code}]"

        display_text = output_buffer
        if len(display_text) > MAX_CHARS:
            display_text = "[... Truncated early logs ...]\n" + display_text[-MAX_CHARS:]

        painted_out = ultra_color_engine(display_text)
        final_content = painted_out.rstrip('\r\n')
        out_html = f"<div class='term-block'><pre>{final_content}</pre></div>"
        yield history_base + out_html, ""

        return return_code if return_code is not None else 0, output_buffer

    except Exception as e:
        err_html = f"<div class='term-block'><span style='color: #ff5555;'>[Error: {html.escape(str(e))}]</span></div>"
        yield history_base + err_html, ""
        return 1, str(e)
    finally:
        active_process = None
        try:
            os.close(master_fd)
        except Exception:
            pass

# ==========================================
# 💎 TERMINAL EXECUTION ENGINE & AUTO-PILOT
# ==========================================
def execute_terminal(cmd, current_history):
    global current_working_dir
    
    if current_history is None:
        current_history = initial_text
        
    if not cmd or not str(cmd).strip():
        yield current_history, ""
        return

    cmd_clean = str(cmd).strip()

    if cmd_clean == "clear":
        yield initial_text, ""
        return

    if current_history and initial_text in current_history:
        current_history = current_history.replace(initial_text, "")

    MAX_HISTORY_LEN = 150000
    if current_history and len(current_history) > MAX_HISTORY_LEN:
        cut_idx = current_history.find("<div class='term-block'>", len(current_history) - MAX_HISTORY_LEN)
        if cut_idx != -1:
            current_history = "<div style='color: #6e7681; font-size: 10px; padding: 4px 0;'>[... পূর্ববর্তী লগ মেমরি সুরক্ষার জন্য ট্রাঙ্কেট করা হয়েছে ...]</div>" + current_history[cut_idx:]

    colored_cmd = pygments_colorize_cmd(cmd_clean)
    user_part = "<span style='color: #ff79c6; font-weight: bold;'>apple@mac</span>"
    path_part = f"<span style='color: #79c0ff;'>:{os.path.basename(current_working_dir) or '/'}</span>"
    cmd_part = f"<span style='color: #f2cc60; font-weight: bold;'>$</span> {colored_cmd}"
    prompt_line = f"<div class='term-prompt'>{user_part}{path_part} {cmd_part}</div>"
    
    new_history = (current_history if current_history else "") + prompt_line
    cursor_start = "<div class='term-block'><pre><span class='term-cursor'>|</span></pre></div>"
    yield new_history + cursor_start, ""

    if cmd_clean.startswith("cd ") or cmd_clean == "cd":
        target = cmd_clean[3:].strip() if len(cmd_clean) > 2 else os.path.expanduser("~")
        if target == "~":
            target = os.path.expanduser("~")
        try:
            new_path = os.path.abspath(os.path.join(current_working_dir, target))
            if os.path.isdir(new_path):
                current_working_dir = new_path
                output = f"<span style='color: #a6e22e;'>[Dir: {current_working_dir}]</span>"
            else:
                output = f"<span style='color: #f92672;'>cd: {target}: No such directory</span>"
        except Exception as e:
            output = f"<span style='color: #f92672;'>cd error: {str(e)}</span>"
        
        output_block = f"<div class='term-block'>{output}</div>"
        yield new_history + output_block, ""
        return

    ret_code, out_buf = yield from run_pty_stream(cmd_clean, new_history)

    # 🤖 Auto-Pilot কমান্ড মিসিং হ্যান্ডলার
    missing_cmd = detect_missing_command(ret_code, out_buf, cmd_clean)
    if missing_cmd:
        pkg_name, manager = resolve_missing_package(missing_cmd)
        pilot_msg = f"<div class='pilot-banner-warn'>🤖 <b>[Auto-Pilot]</b> 🔍 <code>{missing_cmd}</code> নেই! সিস্টেম থেকে <code>{pkg_name}</code> ইনস্টল হচ্ছে...</div>"
        new_history = new_history + f"<div class='term-block'><pre>{ultra_color_engine(out_buf)}</pre></div>" + pilot_msg
        yield new_history, ""

        install_cmd = f"brew install {pkg_name}" if manager == "brew" else f"apt-get update -qq && apt-get install -y {pkg_name}"
        inst_code, inst_buf = yield from run_pty_stream(install_cmd, new_history)
        if inst_code == 0:
            rerun_msg = f"<div class='pilot-banner-ok'>🚀 <b>[Auto-Pilot]</b> ইনস্টলেশন সম্পন্ন! এবার মূল কমান্ড <code>{cmd_clean}</code> চালানো হচ্ছে...</div>"
            new_history = new_history + f"<div class='term-block'><pre>{ultra_color_engine(inst_buf)}</pre></div>" + rerun_msg
            yield new_history, ""
            yield from run_pty_stream(cmd_clean, new_history)
        return

    # 🤖 Auto-Pilot পাইথন মডিউল হ্যান্ডলার
    missing_mod = detect_missing_module(out_buf)
    if missing_mod:
        pilot_msg = f"<div class='pilot-banner-cyan'>🤖 <b>[Auto-Pilot]</b> 🐍 মিসিং পাইথন মডিউল <code>{missing_mod}</code>! PyPI থেকে <code>{missing_mod}</code> ইনস্টল হচ্ছে...</div>"
        new_history = new_history + f"<div class='term-block'><pre>{ultra_color_engine(out_buf)}</pre></div>" + pilot_msg
        yield new_history, ""

        inst_code, inst_buf = yield from run_pty_stream(f"pip install --no-cache-dir {missing_mod}", new_history)
        if inst_code == 0:
            rerun_msg = f"<div class='pilot-banner-ok'>🚀 <b>[Auto-Pilot]</b> ইনস্টলেশন সম্পন্ন! এবার মূল কোড <code>{cmd_clean}</code> চালানো হচ্ছে...</div>"
            new_history = new_history + f"<div class='term-block'><pre>{ultra_color_engine(inst_buf)}</pre></div>" + rerun_msg
            yield new_history, ""
            yield from run_pty_stream(cmd_clean, new_history)
        return

# ==========================================
# 💎 LIVE APPLE RAM & CPU HEADER
# ==========================================
def get_live_header():
    vm = psutil.virtual_memory()
    used_gb = round(vm.used / (1024**3), 1)
    total_gb = round(vm.total / (1024**3), 1)
    cpu_cores = psutil.cpu_count(logical=False) or psutil.cpu_count() or 3
    cpu_load = int(psutil.cpu_percent())

    ram_svg = """<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#79c0ff" stroke-width="2"><ellipse cx="12" cy="5" rx="9" ry="3"></ellipse><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"></path><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"></path></svg>"""
    cpu_svg = """<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#7ee787" stroke-width="2"><rect x="4" y="4" width="16" height="16" rx="2"></rect><rect x="9" y="9" width="6" height="6"></rect><line x1="9" y1="1" x2="9" y2="4"></line><line x1="15" y1="1" x2="15" y2="4"></line><line x1="9" y1="20" x2="9" y2="23"></line><line x1="15" y1="20" x2="15" y2="23"></line></svg>"""

    return f"""
    <div style='display: flex; justify-content: space-between; align-items: center; width: 100%;'>
        <div style='display: flex; align-items: center; gap: 5px; white-space: nowrap;'>
            {ram_svg} <span style='color: #79c0ff; font-weight: bold;'>Apple RAM:</span> {used_gb}/{total_gb}GB
        </div>
        <div style='display: flex; align-items: center; gap: 5px; white-space: nowrap;'>
            {cpu_svg} <span style='color: #7ee787; font-weight: bold;'>Apple Silicon:</span> {cpu_cores}C ({cpu_load}%)
        </div>
    </div>
    """

# ==========================================
# 💎 নিখুঁত মোবাইল ফ্রেন্ডলি CSS (এক লাইনে বাটন ফিক্স)
# ==========================================
custom_css = """
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&display=swap');

footer { display: none !important; }
html, body {
    height: 100dvh !important; width: 100vw !important;
    background-color: #07090e !important; overflow: hidden !important;
    margin: 0 !important; padding: 0 !important; position: fixed !important;
}

.gradio-container { 
    padding: 0 !important; margin: 0 !important; max-width: 100% !important; 
    width: 100vw !important; height: 100dvh !important;
    border: none !important; background-color: #07090e !important;
}

#main_wrapper {
    position: absolute !important; top: 0 !important; left: 0 !important;
    width: 100vw !important; height: 100dvh !important;
    background-color: #07090e !important; margin: 0 !important; padding: 0 !important;
}

#live_header {
    position: fixed !important; top: 0 !important; left: 0 !important; width: 100vw !important;
    height: 32px !important; background-color: #12161f !important;
    border-bottom: 1px solid #212631 !important; padding: 0 15px !important;
    display: flex !important; align-items: center !important; box-sizing: border-box !important;
    z-index: 9999 !important; font-family: 'JetBrains Mono', monospace !important; font-size: 11px !important;
}
#live_header > div { width: 100% !important; }

#ternal_branding {
    position: fixed !important; top: 32px !important; left: 0 !important; width: 100vw !important;
    height: 26px !important; background-color: #0a0d14 !important; border-bottom: none !important;
    display: flex !important; justify-content: center !important; align-items: center !important;
    box-sizing: border-box !important; z-index: 9998 !important;
}

.ternal-text {
    font-family: 'JetBrains Mono', monospace; font-size: 11.5px; font-weight: bold; letter-spacing: 1.5px;
    background: linear-gradient(90deg, #ff007f, #79c0ff, #7ee787, #f2cc60, #ff007f);
    background-size: 200% auto; color: transparent !important;
    -webkit-background-clip: text !important; -webkit-text-fill-color: transparent !important;
    animation: shine 3s linear infinite; margin-right: 6px;
}
@keyframes shine { to { background-position: 200% center; } }

#terminal_output {
    position: fixed !important; top: 58px !important; bottom: 70px !important; left: 0 !important;
    width: 100vw !important; overflow-y: auto !important; overflow-x: hidden !important;
    padding: 10px 12px !important; font-family: 'JetBrains Mono', monospace !important; 
    box-sizing: border-box !important; background-color: #07090e !important;
    contain: layout style paint !important;
    transform: translateZ(0) !important;
    will-change: scroll-position !important;
    overscroll-behavior: contain !important;
    -webkit-overflow-scrolling: touch !important;
}

.term-block {
    contain: content !important;
    content-visibility: auto !important;
    contain-intrinsic-size: 0 35px !important;
    margin-bottom: 5px !important;
}

.term-prompt {
    margin-top: 8px !important;
    margin-bottom: 2px !important;
    font-size: 11.5px !important;
}

#terminal_output pre {
    margin: 0 !important; font-family: 'JetBrains Mono', monospace !important;
    font-size: 11.5px !important; line-height: 1.48 !important; letter-spacing: 0.2px !important;
    white-space: pre-wrap !important; word-break: normal !important; overflow-wrap: break-word !important;
    color: #c9d1d9 !important; text-rendering: optimizeSpeed !important;
}

.term-cursor {
    display: inline-block !important;
    font-weight: 700 !important;
    color: #58a6ff !important;
    text-shadow: 0 0 8px rgba(88, 166, 255, 0.8) !important;
    animation: cursor-blink 0.75s infinite ease-in-out !important;
    margin-left: 2px !important;
    vertical-align: baseline !important;
}
@keyframes cursor-blink {
    0%, 100% { opacity: 1; transform: scaleY(1); }
    50% { opacity: 0; transform: scaleY(0.85); }
}

.pilot-banner-warn {
    margin: 6px 0; padding: 5px 10px; background: rgba(241, 250, 140, 0.1); 
    border-left: 3px solid #f1fa8c; border-radius: 4px; font-size: 11px; color: #f1fa8c;
}
.pilot-banner-ok {
    margin: 6px 0; padding: 5px 10px; background: rgba(80, 250, 123, 0.1); 
    border-left: 3px solid #50fa7b; border-radius: 4px; font-size: 11px; color: #50fa7b;
}
.pilot-banner-cyan {
    margin: 6px 0; padding: 5px 10px; background: rgba(139, 233, 253, 0.1); 
    border-left: 3px solid #8be9fd; border-radius: 4px; font-size: 11px; color: #8be9fd;
}

/* 🟢 মোবাইল ফ্রেন্ডলি এক লাইনের বটম বার */
#bottom_row {
    position: fixed !important; bottom: 0 !important; left: 0 !important; width: 100vw !important;
    height: 65px !important; background-color: #0b0e14 !important; border-top: 1px solid #212631 !important;
    display: flex !important; flex-direction: row !important; align-items: center !important; flex-wrap: nowrap !important;
    padding: 8px 10px !important; box-sizing: border-box !important; z-index: 9999 !important; gap: 8px !important;
}

#btn_clear {
    background-color: #da3633 !important; color: #ffffff !important; min-width: 65px !important; max-width: 65px !important;
    height: 40px !important; font-size: 11px !important; border-radius: 6px !important; border: none !important;
    display: flex !important; justify-content: center !important; align-items: center !important; cursor: pointer !important; flex-shrink: 0 !important;
}

#cmd_input { flex-grow: 1 !important; min-width: 0 !important; height: 40px !important; }
#cmd_input input, #cmd_input textarea {
    background-color: #12161f !important; color: #58a6ff !important; font-family: 'JetBrains Mono', monospace !important;
    font-size: 13.5px !important; border: 1px solid #212631 !important; border-radius: 6px !important;
    height: 40px !important; padding: 0 10px !important; width: 100% !important; box-sizing: border-box !important;
}

#btn_send {
    background-color: #238636 !important; color: #ffffff !important; min-width: 65px !important; max-width: 65px !important;
    height: 40px !important; font-size: 11px !important; border-radius: 6px !important; border: none !important;
    display: flex !important; justify-content: center !important; align-items: center !important; cursor: pointer !important; flex-shrink: 0 !important;
}

#btn_stop {
    display: none !important;
    background-color: #da3633 !important; color: #ffffff !important; min-width: 65px !important; max-width: 65px !important;
    height: 40px !important; font-size: 11px !important; border-radius: 6px !important; border: none !important;
    justify-content: center !important; align-items: center !important; cursor: pointer !important; flex-shrink: 0 !important;
    animation: pulse-stop 1.5s infinite;
}
@keyframes pulse-stop {
    0%, 100% { box-shadow: 0 0 0 0 rgba(218, 54, 51, 0.4); }
    50% { box-shadow: 0 0 0 6px rgba(218, 54, 51, 0); }
}

.is-executing #btn_send { display: none !important; }
.is-executing #btn_stop { display: flex !important; }

#btn_hidden_clear, #btn_hidden_stop { position: absolute !important; opacity: 0 !important; pointer-events: none !important; }
"""

modal_html = """
<div id="clear_modal" style="display: none; position: fixed; top: 0; left: 0; width: 100vw; height: 100vh; background: rgba(0,0,0,0.85); backdrop-filter: blur(8px); z-index: 100000; justify-content: center; align-items: center;">
    <div style="background: #12161f; border: 1px solid #212631; border-radius: 12px; padding: 22px; width: 85%; max-width: 300px; text-align: center; font-family: 'JetBrains Mono', monospace;">
        <div style="font-size: 14px; font-weight: bold; color: #f85149; margin-bottom: 8px;">Clear Terminal?</div>
        <div style="font-size: 11.5px; color: #8b949e; margin-bottom: 20px;">This will clear all current screen logs. Are you sure?</div>
        <div style="display: flex; gap: 10px; justify-content: center;">
            <button onclick="document.getElementById('clear_modal').style.display='none';" style="background: #1a1e27; color: #c9d1d9; border: 1px solid #212631; padding: 8px 16px; border-radius: 6px; font-size: 12px;">Cancel</button>
            <button onclick="document.getElementById('clear_modal').style.display='none'; const el = document.getElementById('btn_hidden_clear') || document.querySelector('#btn_hidden_clear button'); if(el) el.click();" style="background: #da3633; color: #fff; border: none; padding: 8px 16px; border-radius: 6px; font-size: 12px; font-weight: bold;">Confirm</button>
        </div>
    </div>
</div>

<div id="stop_modal" style="display: none; position: fixed; top: 0; left: 0; width: 100vw; height: 100vh; background: rgba(0,0,0,0.85); backdrop-filter: blur(8px); z-index: 100000; justify-content: center; align-items: center;">
    <div style="background: #12161f; border: 1px solid #212631; border-radius: 12px; padding: 22px; width: 85%; max-width: 300px; text-align: center; font-family: 'JetBrains Mono', monospace;">
        <div style="font-size: 14px; font-weight: bold; color: #f85149; margin-bottom: 8px;">Stop Process?</div>
        <div style="font-size: 11.5px; color: #8b949e; margin-bottom: 20px;">Are you sure you want to terminate (Ctrl+C) the currently running command?</div>
        <div style="display: flex; gap: 10px; justify-content: center;">
            <button onclick="document.getElementById('stop_modal').style.display='none';" style="background: #1a1e27; color: #c9d1d9; border: 1px solid #212631; padding: 8px 16px; border-radius: 6px; font-size: 12px;">Cancel</button>
            <button onclick="document.getElementById('stop_modal').style.display='none'; document.querySelector('#bottom_row')?.classList.remove('is-executing'); const el = document.getElementById('btn_hidden_stop') || document.querySelector('#btn_hidden_stop button'); if(el) el.click();" style="background: #da3633; color: #fff; border: none; padding: 8px 16px; border-radius: 6px; font-size: 12px; font-weight: bold;">Stop (Kill)</button>
        </div>
    </div>
</div>
"""

ternal_html = """
<div id="ternal_branding">
    <span class="ternal-text"> TERNAL (macOS ARM64)</span>
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#79c0ff" stroke-width="2"><polyline points="4 17 10 11 4 5"></polyline><line x1="12" y1="19" x2="20" y2="19"></line></svg>
</div>
"""

# 🍃 আপনার আসল লিকুইড অটো-স্ক্রোল ও স্টপ বাটন কন্ট্রোলার JS
client_js = """
() => {
    function initLiquidScroll() {
        const term = document.querySelector('#terminal_output');
        const inp = document.querySelector('#cmd_input input') || document.querySelector('#cmd_input textarea');
        const sendBtn = document.querySelector('#btn_send');
        if (!term || term.dataset.scrollInit) return;
        term.dataset.scrollInit = "true";

        let autoScroll = true;
        let touchStartY = 0;

        function scrollToBottom() {
            term.scrollTop = term.scrollHeight;
        }

        term.addEventListener('touchstart', (e) => {
            if (e.touches.length > 0) touchStartY = e.touches[0].clientY;
        }, { passive: true });

        term.addEventListener('touchmove', (e) => {
            if (e.touches.length > 0) {
                const currentY = e.touches[0].clientY;
                const deltaY = currentY - touchStartY;
                if (deltaY > 10) {
                    autoScroll = false;
                } else if (deltaY < -10) {
                    const dist = term.scrollHeight - term.scrollTop - term.clientHeight;
                    if (dist < 180) autoScroll = true;
                }
                touchStartY = currentY;
            }
        }, { passive: true });

        term.addEventListener('wheel', (e) => {
            if (e.deltaY < 0) autoScroll = false;
            else if (e.deltaY > 0) {
                const dist = term.scrollHeight - term.scrollTop - term.clientHeight;
                if (dist < 180) autoScroll = true;
            }
        }, { passive: true });

        term.addEventListener('scroll', () => {
            const dist = term.scrollHeight - term.scrollTop - term.clientHeight;
            if (dist <= 30) autoScroll = true;
        }, { passive: true });

        if (inp) {
            inp.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' && inp.value.trim().length > 0) {
                    document.querySelector('#bottom_row')?.classList.add('is-executing');
                    autoScroll = true;
                    scrollToBottom();
                }
            });
        }

        if (sendBtn) {
            sendBtn.addEventListener('click', () => {
                if (inp && inp.value.trim().length > 0) {
                    document.querySelector('#bottom_row')?.classList.add('is-executing');
                    autoScroll = true;
                    scrollToBottom();
                }
            });
        }

        const observer = new MutationObserver(() => {
            if (autoScroll) {
                term.scrollTop = term.scrollHeight;
            }
        });

        observer.observe(term, { childList: true, subtree: true, characterData: false });
    }

    setTimeout(initLiquidScroll, 300);
    setTimeout(initLiquidScroll, 1000);
    setTimeout(initLiquidScroll, 2000);
}
"""

# ==========================================
# 💎 GRADIO UI INTERFACE
# ==========================================
with gr.Blocks(title="Ternal Mac") as demo:
    with gr.Column(elem_id="main_wrapper"):
        modal_component = gr.HTML(value=modal_html)
        header_bar = gr.HTML(value=get_live_header, elem_id="live_header")
        timer = gr.Timer(2.0)
        timer.tick(get_live_header, outputs=header_bar, show_progress="hidden")

        ternal_bar = gr.HTML(value=ternal_html)
        terminal_box = gr.HTML(value=initial_text, elem_id="terminal_output")

        with gr.Row(elem_id="bottom_row"):
            btn_clear = gr.Button("Clear", elem_id="btn_clear")
            cmd_input = gr.Textbox(placeholder="Enter Mac command...", elem_id="cmd_input", container=False, max_lines=1)
            btn_send = gr.Button("Send", elem_id="btn_send")
            btn_stop = gr.Button("Stop", elem_id="btn_stop")

        btn_hidden_clear = gr.Button("HiddenClear", elem_id="btn_hidden_clear")
        btn_hidden_stop = gr.Button("HiddenStop", elem_id="btn_hidden_stop")

    btn_clear.click(fn=None, js="() => { document.getElementById('clear_modal').style.display = 'flex'; }")
    btn_hidden_clear.click(lambda: (initial_text, ""), outputs=[terminal_box, cmd_input])

    btn_stop.click(fn=None, js="() => { document.getElementById('stop_modal').style.display = 'flex'; }")

    end_js = "() => { document.querySelector('#bottom_row')?.classList.remove('is-executing'); }"

    cmd_submit = cmd_input.submit(execute_terminal, inputs=[cmd_input, terminal_box], outputs=[terminal_box, cmd_input])
    cmd_submit.then(fn=None, js=end_js)

    btn_submit = btn_send.click(execute_terminal, inputs=[cmd_input, terminal_box], outputs=[terminal_box, cmd_input])
    btn_submit.then(fn=None, js=end_js)

    btn_hidden_stop.click(kill_active_process, cancels=[cmd_submit, btn_submit])

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860, css=custom_css, js=client_js)
