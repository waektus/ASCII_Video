"""
ASCII Player Video Creator
Converts video files into ASCII art for terminal playback and MP4 export.
By Plankton
"""

import os
import sys
import time
import shutil
import threading
from queue import Queue
from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont


# ── ANSI Escape Codes ────────────────────────────────────────────────────────

class ANSI:
    CURSOR_HOME  = "\033[H"
    CLEAR_SCREEN = "\033[2J"
    HIDE_CURSOR  = "\033[?25l"
    SHOW_CURSOR  = "\033[?25h"
    RESET        = "\033[0m"
    BOLD         = "\033[1m"
    CYAN         = "\033[96m"
    GREEN        = "\033[92m"
    YELLOW       = "\033[93m"
    RED          = "\033[91m"
    GRAY         = "\033[90m"

    @staticmethod
    def rgb(r: int, g: int, b: int) -> str:
        return f"\033[38;2;{r};{g};{b}m"

    @staticmethod
    def move_to(line: int, col: int = 1) -> str:
        return f"\033[{line};{col}H"


# ── UI Strings ────────────────────────────────────────────────────────────────

T = {
    "app_name":          "ASCII Player Video Creator",
    "input_path":        "Enter video path: ",
    "enable_color":      "Character color? (y/N): ",
    "output_width":      "Output width (blank for Auto, terminal={}): ",
    "skip_n_frames":     "Skip every N frames (default 1): ",
    "repeat_video":      "Preview in loop? (y/N): ",
    "playback_finished": "Playback finished.",
    "export_q":          "Do you want to export it as MP4? (y/N): ",
    "export_folder":     "Create a temp folder, copy its path and paste it here: ",
    "export_mode_q":     "What to keep? (1. Only MP4 video | 2. Video + Each PNG frame): ",
    "export_bg":         "Background color (1. Black | 2. White | 3. Blue | 4. Custom Hex): ",
    "export_start":      "Creating video... Please wait.",
    "export_done":       "Video finished! Saved at: ",
    "cleaning_temp":     "Deleting temporary frames folder...",
    "try_again_q":       "Do you want to try another video? (y/N): ",
    "error_not_found":   "File not found: '{}'",
    "processing_frame":  "Frame {}/{}...",
}

LOGO = f"""
{ANSI.CYAN}    ╔══════════════════════════════════════════════════════════════════════════╗
    ║                                                                          ║
    ║   {ANSI.BOLD}{ANSI.GREEN} █████╗ ███████╗ ██████╗██╗██╗     ██████╗ ██╗      █████╗ ██╗   ██╗   {ANSI.CYAN}║
    ║   {ANSI.BOLD}{ANSI.GREEN}██╔══██╗██╔════╝██╔════╝██║██║     ██╔══██╗██║     ██╔══██╗╚██╗ ██╔╝   {ANSI.CYAN}║
    ║   {ANSI.BOLD}{ANSI.GREEN}███████║███████╗██║     ██║██║     ██████╔╝██║     ███████║  ╚████╔╝   {ANSI.CYAN}║
    ║   {ANSI.BOLD}{ANSI.GREEN}██╔══██║╚════██║██║     ██║██║     ██╔═══╝ ██║     ██╔══██║   ╚██╔╝    {ANSI.CYAN}║
    ║   {ANSI.BOLD}{ANSI.GREEN}██║  ██║███████║╚██████╗██║██║     ██║     ███████╗██║  ██║    ██║     {ANSI.CYAN}║
    ║   {ANSI.BOLD}{ANSI.GREEN}╚═╝  ╚═╝╚══════╝ ╚═════╝╚═╝╚═╝     ╚═╝     ╚══════╝╚═╝  ╚═╝    ╚═╝     {ANSI.CYAN}║
    ║                                                                          ║
    ║        {ANSI.BOLD}{ANSI.YELLOW}V I D E O    C R E A T O R    -    B Y    P L A N K T O N{ANSI.CYAN}         ║
    ╚══════════════════════════════════════════════════════════════════════════╝{ANSI.RESET}
"""


# ── ASCII Conversion Config ───────────────────────────────────────────────────

ASCII_CHARS   = " .'`^\",:;Il!i><~+_-?][}{1)(|\\/tfjrxnuvczmwqpdbkhao*#MW&8%B@$0QSXGZJKPHDAUYTRENVLCF"
_CHARS_ARRAY  = np.array(list(ASCII_CHARS))
DEFAULT_FPS   = 30.0
FONT_SIZE     = 10
FONT_CHAR_W_RATIO = 0.6


# ── Data Containers ───────────────────────────────────────────────────────────

@dataclass
class VideoInfo:
    fps:          float
    total_frames: int
    width_px:     int
    height_px:    int
    duration_s:   float

    @property
    def aspect_ratio(self) -> float:
        return self.width_px / self.height_px


@dataclass
class PlaybackConfig:
    width:     Optional[int]
    use_color: bool
    skip:      int
    loop:      bool


@dataclass
class ExportConfig:
    folder:    str
    keep_mode: str            # "1" = mp4 only, "2" = mp4 + frames
    bg_color:  tuple[int, int, int]


# ── System Utilities ──────────────────────────────────────────────────────────

def enable_ansi_windows() -> None:
    """Enable ANSI escape codes on Windows terminals."""
    if os.name == "nt":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
        except Exception:
            pass


def clear_console() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def get_terminal_size() -> tuple[int, int]:
    """Returns (columns, lines) with safe fallback."""
    try:
        size = os.get_terminal_size()
        return size.columns, size.lines
    except OSError:
        return 80, 24


def prompt(label: str) -> str:
    """Styled input prompt."""
    return input(f"  {ANSI.BOLD}{ANSI.GREEN}»{ANSI.RESET} {label}").strip()


def is_yes(answer: str) -> bool:
    return answer.strip().lower() in ("y", "yes")


# ── Video Info ────────────────────────────────────────────────────────────────

def get_video_info(cap: cv2.VideoCapture) -> VideoInfo:
    fps = cap.get(cv2.CAP_PROP_FPS)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    return VideoInfo(
        fps          = fps,
        total_frames = total,
        width_px     = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
        height_px    = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        duration_s   = total / max(fps, 1),
    )


# ── ASCII Conversion ──────────────────────────────────────────────────────────

def _compute_ascii_height(frame_shape, width: int) -> int:
    return max(1, int(frame_shape[0] * width / frame_shape[1] / 2))


def frame_to_ascii_grayscale(frame, width: int) -> str:
    """Convert a BGR frame to a plain ASCII string."""
    h = _compute_ascii_height(frame.shape, width)
    gray = cv2.cvtColor(cv2.resize(frame, (width, h)), cv2.COLOR_BGR2GRAY)
    n = len(ASCII_CHARS) - 1
    return "\n".join(
        "".join(ASCII_CHARS[int(p / 255.0 * n)] for p in row)
        for row in gray
    )


def frame_to_ascii_color(frame, width: int) -> tuple[np.ndarray, np.ndarray]:
    """Convert a BGR frame to (char_map, rgb_map) arrays for colored output."""
    h = _compute_ascii_height(frame.shape, width)
    resized     = cv2.resize(frame, (width, h))
    rgb         = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
    brightness  = 0.299 * rgb[:, :, 0] + 0.587 * rgb[:, :, 1] + 0.114 * rgb[:, :, 2]
    indices     = np.clip(
        (brightness / 255.0 * (len(ASCII_CHARS) - 1)).astype(np.int32),
        0, len(ASCII_CHARS) - 1,
    )
    return _CHARS_ARRAY[indices], rgb


# ── Image Rendering (for export) ──────────────────────────────────────────────

def _load_monospace_font(size: int) -> ImageFont.FreeTypeFont:
    for name in ("consola.ttf", "cour.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def ascii_to_image(
    char_map: np.ndarray,
    rgb_map: Optional[np.ndarray],
    bg_color: tuple[int, int, int],
    font_size: int = FONT_SIZE,
) -> Image.Image:
    """Render a char_map (and optional rgb_map) into a PIL Image."""
    h, w       = char_map.shape
    char_w     = font_size * FONT_CHAR_W_RATIO
    char_h     = font_size
    img        = Image.new("RGB", (int(w * char_w), int(h * char_h)), bg_color)
    draw       = ImageDraw.Draw(img)
    font       = _load_monospace_font(font_size)

    for y in range(h):
        for x in range(w):
            color = tuple(rgb_map[y, x]) if rgb_map is not None else (255, 255, 255)
            draw.text((x * char_w, y * char_h), char_map[y, x], fill=color, font=font)

    return img


# ── Terminal Playback ─────────────────────────────────────────────────────────

def _build_colored_art(char_map: np.ndarray, rgb_map: np.ndarray) -> str:
    """Compose ANSI-colored ASCII art string from char and rgb arrays."""
    lines = []
    for row_chars, row_colors in zip(char_map, rgb_map):
        line = "".join(
            f"{ANSI.rgb(r, g, b)}{c}"
            for c, (r, g, b) in zip(row_chars, row_colors)
        ) + ANSI.RESET
        lines.append(line)
    return "\n".join(lines)


def _render_progress_bar(current: int, total: int, cols: int) -> str:
    bar_len = max(10, cols - 45)
    filled  = int(bar_len * current / total)
    bar     = "█" * filled + "░" * (bar_len - filled)
    return f"{ANSI.GRAY}[{bar}] {current}/{total} | Ctrl+C {ANSI.RESET}"


def _decode_frames(cap: cv2.VideoCapture, skip: int, q: Queue, stop: threading.Event) -> None:
    """Decoder thread: reads frames from cap and puts them on the queue."""
    idx = 0
    while not stop.is_set():
        ret, frame = cap.read()
        if not ret:
            break
        if skip > 1 and idx % skip != 0:
            idx += 1
            continue
        idx += 1
        while not stop.is_set():
            try:
                q.put(frame, timeout=0.1)
                break
            except Exception:
                pass
    q.put(None)  # sentinel


def play_engine(video_path: str, cfg: PlaybackConfig) -> None:
    """Main terminal playback loop."""
    cap  = cv2.VideoCapture(video_path)
    info = get_video_info(cap)
    fps  = info.fps if info.fps > 0 else DEFAULT_FPS
    delay = (1.0 / fps) * cfg.skip

    while True:
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        q    = Queue(maxsize=10)
        stop = threading.Event()
        t    = threading.Thread(target=_decode_frames, args=(cap, cfg.skip, q, stop), daemon=True)
        t.start()

        sys.stdout.write(ANSI.HIDE_CURSOR + ANSI.CLEAR_SCREEN)
        sys.stdout.flush()

        frame_count = 0
        total       = max(1, info.total_frames // cfg.skip)

        try:
            while True:
                tick  = time.perf_counter()
                frame = q.get(timeout=2.0)
                if frame is None:
                    break

                frame_count += 1
                cols, lines = get_terminal_size()
                width = cfg.width or min(cols, int((lines - 2) * info.aspect_ratio * 2.0))

                # Build ASCII art
                if cfg.use_color:
                    char_map, rgb_map = frame_to_ascii_color(frame, width)
                    art = _build_colored_art(char_map, rgb_map)
                else:
                    art = frame_to_ascii_grayscale(frame, width)

                # Draw frame + progress bar
                progress = _render_progress_bar(frame_count, total, cols)
                sys.stdout.write(ANSI.CURSOR_HOME + art)
                sys.stdout.write(ANSI.move_to(lines) + progress)
                sys.stdout.flush()

                # Pace to target FPS
                elapsed = time.perf_counter() - tick
                if delay > elapsed:
                    time.sleep(delay - elapsed)

        except KeyboardInterrupt:
            stop.set()
            break
        finally:
            stop.set()
            t.join(timeout=1.0)

        if not cfg.loop:
            break

    cap.release()
    sys.stdout.write(ANSI.SHOW_CURSOR + ANSI.RESET + f"\n\n{T['playback_finished']}\n")


# ── MP4 Export ────────────────────────────────────────────────────────────────

def _ask_export_config() -> Optional[ExportConfig]:
    """Gather export settings from the user. Returns None if aborted."""
    print(f"\n  {ANSI.BOLD}{ANSI.GREEN}» EXPORT TO MP4 «{ANSI.RESET}")

    folder = prompt(T["export_folder"]).strip('"')
    if not folder:
        return None

    keep_mode = prompt(T["export_mode_q"])

    bg_choice = prompt(T["export_bg"])
    bg_presets = {"1": (0, 0, 0), "2": (255, 255, 255), "3": (0, 0, 255)}

    if bg_choice in bg_presets:
        bg_color = bg_presets[bg_choice]
    elif bg_choice == "4":
        hex_str  = prompt("Hex (#RRGGBB): ").lstrip("#")
        bg_color = tuple(int(hex_str[i:i+2], 16) for i in (0, 2, 4))
    else:
        bg_color = (0, 0, 0)

    return ExportConfig(folder=folder, keep_mode=keep_mode, bg_color=bg_color)


def export_flow(video_path: str, use_color: bool, width: int) -> None:
    """Handle the full export-to-MP4 workflow."""
    clear_console()
    config = _ask_export_config()
    if config is None:
        return

    temp_dir = os.path.join(config.folder, "temp_ascii_frames")
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)
    os.makedirs(temp_dir)

    cap  = cv2.VideoCapture(video_path)
    info = get_video_info(cap)

    print(f"\n  {ANSI.YELLOW}{T['export_start']}{ANSI.RESET}")

    # Render every frame to PNG
    for i in range(1, info.total_frames + 1):
        ret, frame = cap.read()
        if not ret:
            break

        if use_color:
            char_map, rgb_map = frame_to_ascii_color(frame, width)
        else:
            text     = frame_to_ascii_grayscale(frame, width)
            char_map = np.array([list(line) for line in text.split("\n")])
            rgb_map  = None

        img = ascii_to_image(char_map, rgb_map, config.bg_color)
        img.save(os.path.join(temp_dir, f"f_{i:05d}.png"))

        if i % 10 == 0:
            sys.stdout.write(f"\r  {T['processing_frame'].format(i, info.total_frames)}")
            sys.stdout.flush()

    cap.release()

    # Compile PNG frames into MP4
    output_path = os.path.join(config.folder, "ASCII_Player_Output.mp4")
    sample      = cv2.imread(os.path.join(temp_dir, "f_00001.png"))
    out_size    = (sample.shape[1], sample.shape[0])
    writer      = cv2.VideoWriter(output_path, cv2.VideoWriter_fourcc(*"mp4v"), info.fps, out_size)

    for i in range(1, info.total_frames + 1):
        frame_path = os.path.join(temp_dir, f"f_{i:05d}.png")
        writer.write(cv2.imread(frame_path))
    writer.release()

    if config.keep_mode == "1":
        print(f"\n  {ANSI.GRAY}{T['cleaning_temp']}{ANSI.RESET}")
        shutil.rmtree(temp_dir)

    print(f"\n{ANSI.GREEN}{T['export_done']}{ANSI.RESET}{output_path}")


# ── User Prompts ──────────────────────────────────────────────────────────────

def ask_video_path() -> str:
    """Prompt until a valid video file path is provided."""
    while True:
        path = prompt(T["input_path"]).strip('"')
        if path and os.path.exists(path):
            return path
        print(f"  {ANSI.RED}{T['error_not_found'].format(path)}{ANSI.RESET}")
        time.sleep(1.5)


def ask_playback_config() -> PlaybackConfig:
    try:
        default_cols = os.get_terminal_size().columns
    except OSError:
        default_cols = 80

    use_color = is_yes(prompt(T["enable_color"]))

    w_input = prompt(T["output_width"].format(default_cols))
    width   = int(w_input) if w_input.isdigit() else None

    s_input = prompt(T["skip_n_frames"])
    skip    = int(s_input) if s_input.isdigit() else 1

    loop = is_yes(prompt(T["repeat_video"]))

    return PlaybackConfig(width=width, use_color=use_color, skip=skip, loop=loop)


# ── Application Entry Point ───────────────────────────────────────────────────

def show_logo() -> None:
    clear_console()
    print(LOGO)
    time.sleep(5)


def main() -> None:
    enable_ansi_windows()
    show_logo()

    while True:
        show_logo()
        print(f"  {ANSI.BOLD}{ANSI.YELLOW}» {T['app_name']} «{ANSI.RESET}\n")

        video_path = ask_video_path()
        cfg        = ask_playback_config()

        # Playback
        try:
            play_engine(video_path, cfg)
        except KeyboardInterrupt:
            pass

        # Optional export
        if is_yes(prompt(T["export_q"])):
            export_width = cfg.width or 120
            export_flow(video_path, cfg.use_color, export_width)

        # Loop or exit
        if not is_yes(prompt(T["try_again_q"])):
            break

    clear_console()


if __name__ == "__main__":
    main()