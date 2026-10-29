# --- START OF FILE app.py (Mac Optimized for GitHub Actions) ---

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

# 🛑 ZeroGPU Fallback (HF ছাড়া অন্য কোথাও ক্র্যাশ করবে না)
try:
    import spaces
    has_spaces = True
except ImportError:
    has_spaces = False

# সক্রিয় প্রসেস ট্র্যাকিং
active_process = None

def kill_active_process():
    global active_process
    if active_process:
        try:
            pgid = os.getpgid(active_process.pid)
            os.killpg(pgid, signal.SIGTERM)
            os.killpg(pgid, signal.SIGKILL)
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
initial_text = "<div id='welcome_msg' style='color:#7ee787; font-size:11px;'>[ TERNAL macOS Apple Silicon is Ready...]</div>"

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

    html_out = re.sub(r'(\[Process exited with code 0\])', r'<span style="color: #50fa7b; font-weight: bold;">\1</span>', html_out)
    html_out = re.sub(r'(\[Process terminated by user\])', r'<span style="color: #ffb86c; font-weight: bold; background: rgba(255,184,108,0.15); padding: 2px 6px; border-radius: 4px;">\1</span>', html_out)
    html_out = re.sub(r'(\[Process exited with code [1-9]\d*\])', r'<span style="color: #ff5555; font-weight: bold;">\1</span>', html_out)
    return html_out

def format_with_cursor(painted_text, cursor_tag):
    clean_text = painted_text.rstrip('\r\n')
    return f"{clean_text}{cursor_tag}" if clean_text else cursor_tag

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
        env["TERM"] = "xterm-256color"
        env["COLORTERM"] = "truecolor"
        env["CLICOLOR_FORCE"] = "1"
        env["FORCE_COLOR"] = "1"

        # macOS এ ডিফল্ট শেল zsh বা bash
        shell_bin = "/bin/zsh" if os.path.exists("/bin/zsh") else "/bin/bash"

        process = subprocess.Popen(
            cmd_str,
            shell=True,
            executable=shell_bin,
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
                    if current_time - last_yield_time >= 0.06:
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

    yield from run_pty_stream(cmd_clean, new_history)

# লাইভ ম্যাক র‍্যাম ও সিপিইউ হেডার
def get_live_header():
    vm = psutil.virtual_memory()
    used_gb = round(vm.used / (1024**3), 1)
    total_gb = round(vm.total / (1024**3), 1)
    cpu_cores = psutil.cpu_count(logical=False) or psutil.cpu_count() or 3
    cpu_load = int(psutil.cpu_percent())

    ram_svg = """<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#79c0ff" stroke-width="2"><ellipse cx="12" cy="5" rx="9" ry="3"></ellipse><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"></path><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"></path></svg>"""
    cpu_svg = """<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#7ee787" stroke-width="2"><rect x="4" y="4" width="16" height="16" rx="2"></rect><path d="M9 9h6v6H9z"></path></svg>"""

    return f"""
    <div style='display: flex; justify-content: space-between; align-items: center; width: 100%;'>
        <div style='display: flex; align-items: center; gap: 5px; white-space: nowrap;'>
            {ram_svg} <span style='color: #79c0ff; font-weight: bold;'>Apple RAM:</span> {used_gb}/{total_gb}GB
        </div>
        <div style='display: flex; align-items: center; gap: 5px; white-space: nowrap;'>
            {cpu_svg} <span style='color: #7ee787; font-weight: bold;'>Apple M-Chip:</span> {cpu_cores} Cores ({cpu_load}%)
        </div>
    </div>
    """

custom_css = """
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&display=swap');
footer { display: none !important; }
html, body { height: 100dvh !important; width: 100vw !important; background-color: #07090e !important; overflow: hidden !important; margin: 0 !important; }
.gradio-container { padding: 0 !important; margin: 0 !important; width: 100vw !important; height: 100dvh !important; border: none !important; background-color: #07090e !important; }
#main_wrapper { position: absolute !important; top: 0 !important; left: 0 !important; width: 100vw !important; height: 100dvh !important; background-color: #07090e !important; }
#live_header { position: fixed !important; top: 0 !important; left: 0 !important; width: 100vw !important; height: 32px !important; background-color: #12161f !important; border-bottom: 1px solid #212631 !important; padding: 0 15px !important; display: flex !important; align-items: center !important; z-index: 9999 !important; font-family: 'JetBrains Mono', monospace !important; font-size: 11px !important; }
#ternal_branding { position: fixed !important; top: 32px !important; left: 0 !important; width: 100vw !important; height: 26px !important; background-color: #0a0d14 !important; display: flex !important; justify-content: center !important; align-items: center !important; z-index: 9998 !important; }
.ternal-text { font-family: 'JetBrains Mono', monospace; font-size: 11.5px; font-weight: bold; letter-spacing: 1.5px; color: #79c0ff; }
#terminal_output { position: fixed !important; top: 58px !important; bottom: 75px !important; left: 0 !important; width: 100vw !important; overflow-y: auto !important; padding: 10px 12px !important; font-family: 'JetBrains Mono', monospace !important; box-sizing: border-box !important; }
.term-prompt { margin-top: 8px !important; font-size: 11.5px !important; }
#terminal_output pre { margin: 0 !important; font-family: 'JetBrains Mono', monospace !important; font-size: 11.5px !important; color: #c9d1d9 !important; white-space: pre-wrap !important; }
.term-cursor { color: #58a6ff !important; animation: cursor-blink 0.75s infinite ease-in-out !important; }
@keyframes cursor-blink { 0%, 100% { opacity: 1; } 50% { opacity: 0; } }
#bottom_row { position: fixed !important; bottom: 0 !important; left: 0 !important; width: 100vw !important; height: 75px !important; background-color: #0b0e14 !important; border-top: 1px solid #212631 !important; display: flex !important; padding: 8px !important; gap: 8px !important; box-sizing: border-box !important; z-index: 9999 !important; }
#btn_clear { background-color: #da3633 !important; color: #ffffff !important; width: 70px !important; height: 40px !important; font-size: 12px !important; border-radius: 6px !important; border: none !important; }
#cmd_input { flex-grow: 1 !important; height: 40px !important; }
#cmd_input input { background-color: #12161f !important; color: #58a6ff !important; font-family: 'JetBrains Mono', monospace !important; font-size: 14px !important; border: 1px solid #212631 !important; height: 40px !important; padding: 0 10px !important; width: 100% !important; border-radius: 6px !important; }
#btn_send { background-color: #238636 !important; color: #ffffff !important; width: 70px !important; height: 40px !important; font-size: 12px !important; border-radius: 6px !important; border: none !important; }
#btn_stop { display: none !important; background-color: #da3633 !important; color: #ffffff !important; width: 70px !important; height: 40px !important; font-size: 12px !important; border-radius: 6px !important; }
.is-executing #btn_send { display: none !important; }
.is-executing #btn_stop { display: flex !important; }
#btn_hidden_clear, #btn_hidden_stop { position: absolute !important; opacity: 0 !important; }
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
            <button onclick="document.getElementById('stop_modal').style.display='none'; document.querySelector('#bottom_row')?.classList.remove('is-executing'); const el = document.getElementById('btn_hidden_stop') || document.querySelector('#btn_hidden_stop button'); if(el) el.click();" style="background: #da3633; color: #fff; border: none; padding: 6px 14px; border-radius: 6px;">Stop</button>
        </div>
    </div>
</div>
"""

ternal_html = """<div id="ternal_branding"><span class="ternal-text"> TERNAL (macOS ARM64)</span></div>"""

client_js = """
() => {
    const term = document.querySelector('#terminal_output');
    if (!term) return;
    const observer = new MutationObserver(() => { term.scrollTop = term.scrollHeight; });
    observer.observe(term, { childList: true, subtree: true });
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

    cmd_submit = cmd_input.submit(execute_terminal, inputs=[cmd_input, terminal_box], outputs=[terminal_box, cmd_input])
    cmd_submit.then(fn=None, js=end_js)

    btn_submit = btn_send.click(execute_terminal, inputs=[cmd_input, terminal_box], outputs=[terminal_box, cmd_input])
    btn_submit.then(fn=None, js=end_js)

    btn_hidden_stop.click(kill_active_process, cancels=[cmd_submit, btn_submit])

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860, css=custom_css, js=client_js)