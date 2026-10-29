# --- START OF FILE app.py (Final Fixed Edition) ---

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

try:
    import spaces
    has_spaces = True
except ImportError:
    has_spaces = False

active_process = None

def kill_active_process():
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
initial_text = "<div id='welcome_msg' style='color:#7ee787; font-size:11px;'>[⚡ TERNAL Engine is Live & Ready...]</div>"

RE_CMD_NOT_FOUND = re.compile(r"(?:/bin/bash|/bin/sh|/bin/zsh|zsh|bash):\s*(?:line\s*\d+:\s*)?([a-zA-Z0-9_\-\.]+):\s*(?:command\s*)?not found", re.IGNORECASE)
RE_MOD_NOT_FOUND = re.compile(r"ModuleNotFoundError:\s*No module named ['\"]([^'\"]+)['\"]")

def resolve_missing_package(missing_cmd):
    if sys.platform == "darwin":
        try:
            res = subprocess.run(f"brew search --formula '^{missing_cmd}$'", shell=True, capture_output=True, text=True, timeout=5)
            lines = res.stdout.strip().split('\n')
            if lines and lines[0] and "No formulae" not in lines[0]:
                return lines[0].strip(), "brew"
        except Exception:
            pass
        return missing_cmd, "brew"
    else:
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

    html_out = re.sub(r'(\b[A-Za-z0-9_]+Error:|\b[A-Za-z0-9_]+Exception:|\bCRITICAL:|\bFATAL:)', r'<span style="color: #ff5555; font-weight: bold;">\1</span>', html_out)
    html_out = re.sub(r'(\[Process exited with code 0\])', r'<span style="color: #50fa7b; font-weight: bold;">\1</span>', html_out)
    html_out = re.sub(r'(\[Process terminated by user\])', r'<span style="color: #ffb86c; font-weight: bold;">\1</span>', html_out)
    html_out = re.sub(r'(\[Process exited with code [1-9]\d*\])', r'<span style="color: #ff5555; font-weight: bold;">\1</span>', html_out)
    return html_out

def format_with_cursor(painted_text, cursor_tag):
    clean_text = painted_text.rstrip('\r\n')
    return f"{clean_text}{cursor_tag}" if clean_text else cursor_tag

# ⚡ রিয়েলটাইম আনবাফার্ড স্ট্রিমিং
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
    last_yield_time = 0.0
    MAX_CHARS = 70000

    try:
        os.set_blocking(master_fd, False)
        while True:
            try:
                raw_bytes = os.read(master_fd, 1024)
                if raw_bytes:
                    output_buffer += raw_bytes.decode("utf-8", errors="replace")
                    current_time = time.time()
                    
                    if current_time - last_yield_time >= 0.02:
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
                    time.sleep(0.01)
                    while True:
                        try:
                            rem = os.read(master_fd, 1024)
                            if rem:
                                output_buffer += rem.decode("utf-8", errors="replace")
                            else:
                                break
                        except Exception:
                            break
                    break
                time.sleep(0.008)

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

    missing_cmd = detect_missing_command(ret_code, out_buf, cmd_clean)
    if missing_cmd:
        pkg_name, manager = resolve_missing_package(missing_cmd)
        pilot_msg = f"<div class='pilot-banner-warn'>🤖 <b>[Auto-Pilot]</b> 🔍 <code>{missing_cmd}</code> নেই! ইনস্টল হচ্ছে <code>{pkg_name}</code>...</div>"
        new_history = new_history + f"<div class='term-block'><pre>{ultra_color_engine(out_buf)}</pre></div>" + pilot_msg
        yield new_history, ""

        install_cmd = f"brew install {pkg_name}" if manager == "brew" else f"apt-get update -qq && apt-get install -y {pkg_name}"
        inst_code, inst_buf = yield from run_pty_stream(install_cmd, new_history)
        if inst_code == 0:
            rerun_msg = f"<div class='pilot-banner-ok'>🚀 <b>[Auto-Pilot]</b> এবার মূল কমান্ড <code>{cmd_clean}</code> চালানো হচ্ছে...</div>"
            new_history = new_history + f"<div class='term-block'><pre>{ultra_color_engine(inst_buf)}</pre></div>" + rerun_msg
            yield new_history, ""
            yield from run_pty_stream(cmd_clean, new_history)
        return

    missing_mod = detect_missing_module(out_buf)
    if missing_mod:
        pilot_msg = f"<div class='pilot-banner-cyan'>🤖 <b>[Auto-Pilot]</b> 🐍 মিসিং পাইথন মডিউল <code>{missing_mod}</code> ইনস্টল হচ্ছে...</div>"
        new_history = new_history + f"<div class='term-block'><pre>{ultra_color_engine(out_buf)}</pre></div>" + pilot_msg
        yield new_history, ""

        inst_code, inst_buf = yield from run_pty_stream(f"pip install --no-cache-dir {missing_mod}", new_history)
        if inst_code == 0:
            rerun_msg = f"<div class='pilot-banner-ok'>🚀 <b>[Auto-Pilot]</b> এবার মূল কোড <code>{cmd_clean}</code> চালানো হচ্ছে...</div>"
            new_history = new_history + f"<div class='term-block'><pre>{ultra_color_engine(inst_buf)}</pre></div>" + rerun_msg
            yield new_history, ""
            yield from run_pty_stream(cmd_clean, new_history)
        return

def get_live_header():
    vm = psutil.virtual_memory()
    used_gb = round(vm.used / (1024**3), 1)
    total_gb = round(vm.total / (1024**3), 1)
    cpu_cores = psutil.cpu_count(logical=False) or psutil.cpu_count() or 3
    cpu_load = int(psutil.cpu_percent())

    return f"""
    <div style='display: flex; justify-content: space-between; align-items: center; width: 100%; box-sizing: border-box; padding: 0 4px;'>
        <div style='background: rgba(121, 192, 255, 0.12); border: 1px solid rgba(121, 192, 255, 0.25); border-radius: 6px; padding: 3px 8px; display: flex; align-items: center; gap: 4px;'>
            <span style='color: #79c0ff; font-weight: bold; font-size: 10.5px;'>💾 RAM:</span>
            <span style='color: #c9d1d9; font-weight: 600; font-size: 10.5px;'>{used_gb}/{total_gb}GB</span>
        </div>
        <div style='background: rgba(126, 231, 135, 0.12); border: 1px solid rgba(126, 231, 135, 0.25); border-radius: 6px; padding: 3px 8px; display: flex; align-items: center; gap: 4px;'>
            <span style='color: #7ee787; font-weight: bold; font-size: 10.5px;'>⚡ M-Chip:</span>
            <span style='color: #c9d1d9; font-weight: 600; font-size: 10.5px;'>{cpu_cores}C ({cpu_load}%)</span>
        </div>
    </div>
    """

custom_css = """
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&display=swap');

footer { display: none !important; }
html, body {
    height: 100dvh !important; width: 100vw !important;
    background-color: #07090e !important; overflow: hidden !important;
    margin: 0 !important; padding: 0 !important; position: fixed !important;
}

.loading, .generating, .progress-bar, .meta-text,
[data-testid="loading-status"], .wrap.default, .animate-spin, .loading-status {
    display: none !important;
    opacity: 0 !important;
    visibility: hidden !important;
    pointer-events: none !important;
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
    height: 34px !important; background-color: #12161f !important;
    border-bottom: 1px solid #212631 !important; padding: 0 10px !important;
    display: flex !important; align-items: center !important; box-sizing: border-box !important;
    z-index: 9999 !important; font-family: 'JetBrains Mono', monospace !important;
}
#live_header > div { width: 100% !important; }

#ternal_branding {
    position: fixed !important; top: 34px !important; left: 0 !important; width: 100vw !important;
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
    position: fixed !important; top: 60px !important; bottom: 65px !important; left: 0 !important;
    width: 100vw !important; overflow-y: auto !important; overflow-x: hidden !important;
    padding: 10px 12px !important; font-family: 'JetBrains Mono', monospace !important; 
    box-sizing: border-box !important; background-color: #07090e !important;
}

.term-block { margin-bottom: 5px !important; }
.term-prompt { margin-top: 8px !important; margin-bottom: 2px !important; font-size: 11.5px !important; }

#terminal_output pre {
    margin: 0 !important; font-family: 'JetBrains Mono', monospace !important;
    font-size: 11.5px !important; color: #c9d1d9 !important; white-space: pre-wrap !important;
}

.term-cursor { color: #58a6ff !important; animation: cursor-blink 0.75s infinite ease-in-out !important; }
@keyframes cursor-blink { 0%, 100% { opacity: 1; } 50% { opacity: 0; } }

#bottom_row {
    position: fixed !important; bottom: 0 !important; left: 0 !important; width: 100vw !important;
    height: 65px !important; background-color: #0b0e14 !important; border-top: 1px solid #212631 !important;
    display: flex !important; flex-direction: row !important; align-items: center !important; flex-wrap: nowrap !important;
    padding: 8px 10px !important; box-sizing: border-box !important; z-index: 9999 !important; gap: 8px !important;
}

#btn_clear {
    background-color: #da3633 !important; color: #ffffff !important; min-width: 65px !important; max-width: 65px !important;
    height: 40px !important; font-size: 11px !important; border-radius: 6px !important; border: none !important;
    flex-shrink: 0 !important; cursor: pointer !important;
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
    flex-shrink: 0 !important; cursor: pointer !important;
}

#btn_stop {
    display: none !important; background-color: #da3633 !important; color: #ffffff !important; min-width: 65px !important;
    max-width: 65px !important; height: 40px !important; font-size: 11px !important; border-radius: 6px !important;
    flex-shrink: 0 !important; animation: pulse-stop 1.5s infinite;
}
@keyframes pulse-stop { 0%, 100% { box-shadow: 0 0 0 0 rgba(218, 54, 51, 0.4); } 50% { box-shadow: 0 0 0 6px rgba(218, 54, 51, 0); } }

.is-executing #btn_send { display: none !important; }
.is-executing #btn_stop { display: flex !important; }
#btn_hidden_clear, #btn_hidden_stop { position: absolute !important; opacity: 0 !important; pointer-events: none !important; }
"""

modal_html = """
<div id="clear_modal" style="display: none; position: fixed; top: 0; left: 0; width: 100vw; height: 100vh; background: rgba(0,0,0,0.85); z-index: 100000; justify-content: center; align-items: center;">
    <div style="background: #12161f; border: 1px solid #212631; border-radius: 12px; padding: 22px; width: 85%; max-width: 300px; text-align: center; font-family: 'JetBrains Mono', monospace;">
        <div style="font-size: 14px; font-weight: bold; color: #f85149; margin-bottom: 8px;">Clear Logs?</div>
        <div style="display: flex; gap: 10px; justify-content: center; margin-top: 15px;">
            <button onclick="document.getElementById('clear_modal').style.display='none';" style="background: #1a1e27; color: #c9d1d9; border: 1px solid #212631; padding: 6px 14px; border-radius: 6px;">Cancel</button>
            <button onclick="document.getElementById('clear_modal').style.display='none'; const el = document.getElementById('btn_hidden_clear') || document.querySelector('#btn_hidden_clear button'); if(el) el.click();" style="background: #da3633; color: #fff; border: none; padding: 6px 14px; border-radius: 6px;">Clear</button>
        </div>
    </div>
</div>

<div id="stop_modal" style="display: none; position: fixed; top: 0; left: 0; width: 100vw; height: 100vh; background: rgba(0,0,0,0.85); z-index: 100000; justify-content: center; align-items: center;">
    <div style="background: #12161f; border: 1px solid #212631; border-radius: 12px; padding: 22px; width: 85%; max-width: 300px; text-align: center; font-family: 'JetBrains Mono', monospace;">
        <div style="font-size: 14px; font-weight: bold; color: #f85149; margin-bottom: 8px;">Stop Command?</div>
        <div style="display: flex; gap: 10px; justify-content: center; margin-top: 15px;">
            <button onclick="document.getElementById('stop_modal').style.display='none';" style="background: #1a1e27; color: #c9d1d9; border: 1px solid #212631; padding: 6px 14px; border-radius: 6px;">Cancel</button>
            <button onclick="document.getElementById('stop_modal').style.display='none'; document.querySelector('#bottom_row')?.classList.remove('is-executing'); const el = document.getElementById('btn_hidden_stop') || document.querySelector('#btn_hidden_stop button'); if(el) el.click();" style="background: #da3633; color: #fff; border: none; padding: 6px 14px; border-radius: 6px;">Stop (Kill)</button>
        </div>
    </div>
</div>
"""

ternal_html = """
<div id="ternal_branding">
    <span class="ternal-text">⚡ TERNAL (macOS ARM64)</span>
</div>
"""

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
                if (deltaY > 10) autoScroll = false;
                else if (deltaY < -10) {
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
            if (autoScroll) term.scrollTop = term.scrollHeight;
        });

        observer.observe(term, { childList: true, subtree: true });
    }

    setTimeout(initLiquidScroll, 300);
    setTimeout(initLiquidScroll, 1000);
}
"""

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

    cmd_submit = cmd_input.submit(
        execute_terminal, 
        inputs=[cmd_input, terminal_box], 
        outputs=[terminal_box, cmd_input],
        show_progress="hidden"
    )
    cmd_submit.then(fn=None, js=end_js)

    btn_submit = btn_send.click(
        execute_terminal, 
        inputs=[cmd_input, terminal_box], 
        outputs=[terminal_box, cmd_input],
        show_progress="hidden"
    )
    btn_submit.then(fn=None, js=end_js)

    btn_hidden_stop.click(kill_active_process, cancels=[cmd_submit, btn_submit])

if __name__ == "__main__":
    demo.queue(default_concurrency_limit=10)
    demo.launch(server_name="0.0.0.0", server_port=7860, css=custom_css, js=client_js)
