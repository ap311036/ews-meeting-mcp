#!/usr/bin/env python3
from __future__ import annotations

import argparse
import math
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "demo"
FRAMES_DIR = OUT_DIR / ".frames"
MP4_PATH = OUT_DIR / "ews-meeting-mcp-demo.mp4"
GIF_PATH = OUT_DIR / "ews-meeting-mcp-demo.gif"

WIDTH = 1280
HEIGHT = 720
FPS = 12
DURATION = 60
TOTAL_FRAMES = FPS * DURATION

FONT_TEXT = "/System/Library/Fonts/SFNS.ttf"
FONT_MONO = "/System/Library/Fonts/SFNSMono.ttf"
FONT_BOLD = "/System/Library/Fonts/HelveticaNeue.ttc"

COLORS = {
    "bg": (9, 14, 24),
    "panel": (18, 26, 40),
    "panel2": (24, 36, 54),
    "line": (52, 70, 96),
    "text": (229, 236, 246),
    "muted": (145, 160, 180),
    "green": (88, 221, 153),
    "blue": (94, 169, 255),
    "amber": (255, 200, 102),
    "red": (255, 114, 114),
    "purple": (176, 139, 255),
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Render the EWS Meeting MCP demo video.")
    parser.add_argument("--frames-only", action="store_true", help="Only render PNG frames.")
    parser.add_argument("--keep-frames", action="store_true", help="Keep generated PNG frames after rendering.")
    args = parser.parse_args()

    OUT_DIR.mkdir(exist_ok=True)
    FRAMES_DIR.mkdir(exist_ok=True)
    for path in FRAMES_DIR.glob("*.png"):
        path.unlink()

    fonts = Fonts()
    for index in range(TOTAL_FRAMES):
        seconds = index / FPS
        frame = render_frame(seconds, fonts)
        frame.save(FRAMES_DIR / f"{index:04d}.png")

    if args.frames_only:
        print(FRAMES_DIR)
        return

    render_mp4()
    render_gif()
    if not args.keep_frames:
        shutil.rmtree(FRAMES_DIR)
    print(MP4_PATH)
    print(GIF_PATH)


class Fonts:
    def __init__(self) -> None:
        self.title = ImageFont.truetype(FONT_BOLD, 48)
        self.subtitle = ImageFont.truetype(FONT_TEXT, 25)
        self.h2 = ImageFont.truetype(FONT_BOLD, 28)
        self.body = ImageFont.truetype(FONT_TEXT, 21)
        self.small = ImageFont.truetype(FONT_TEXT, 17)
        self.mono = ImageFont.truetype(FONT_MONO, 18)
        self.mono_small = ImageFont.truetype(FONT_MONO, 15)


def render_frame(seconds: float, fonts: Fonts) -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT), COLORS["bg"])
    draw = ImageDraw.Draw(image)

    draw_background(draw)
    draw_header(draw, fonts)
    draw_left_story(draw, fonts, seconds)
    draw_terminal(draw, fonts, seconds)
    draw_footer(draw, fonts, seconds)
    return image


def draw_background(draw: ImageDraw.ImageDraw) -> None:
    for y in range(HEIGHT):
        mix = y / HEIGHT
        color = (
            int(9 + 10 * mix),
            int(14 + 10 * mix),
            int(24 + 18 * mix),
        )
        draw.line([(0, y), (WIDTH, y)], fill=color)

    draw.rounded_rectangle((42, 42, 1238, 678), radius=28, fill=(12, 18, 30), outline=(34, 50, 76), width=2)


def draw_header(draw: ImageDraw.ImageDraw, fonts: Fonts) -> None:
    draw.text((76, 70), "EWS Meeting MCP", font=fonts.title, fill=COLORS["text"])
    draw.text(
        (76, 126),
        "The MCP server for safely scheduling Outlook meetings on on-prem Exchange EWS.",
        font=fonts.subtitle,
        fill=COLORS["blue"],
    )
    pill(draw, (925, 72, 1165, 112), "npx ews-meeting-mcp", COLORS["panel2"], COLORS["green"], fonts.mono_small)


def draw_left_story(draw: ImageDraw.ImageDraw, fonts: Fonts, seconds: float) -> None:
    x1, y1, x2, y2 = 76, 176, 530, 610
    draw.rounded_rectangle((x1, y1, x2, y2), radius=18, fill=COLORS["panel"], outline=COLORS["line"], width=1)

    scene_title, lines, badge = story_for_time(seconds)
    draw.text((x1 + 28, y1 + 26), scene_title, font=fonts.h2, fill=COLORS["text"])
    draw_wrapped(draw, lines, (x1 + 28, y1 + 74), 395, fonts.body, COLORS["muted"], line_gap=10)

    by = y2 - 126
    for idx, (label, color) in enumerate(badge):
        pill(draw, (x1 + 28, by + idx * 42, x1 + 398, by + 32 + idx * 42), label, COLORS["panel2"], color, fonts.small)


def story_for_time(seconds: float) -> tuple[str, str, list[tuple[str, tuple[int, int, int]]]]:
    if seconds < 8:
        return (
            "Enterprise-safe scheduling",
            "AI agents can help schedule meetings, but strict companies cannot hand broad calendar permissions to a cloud tool.",
            [
                ("on-prem Exchange EWS", COLORS["blue"]),
                ("local credentials", COLORS["green"]),
                ("human-confirmed writes", COLORS["amber"]),
            ],
        )
    if seconds < 21:
        return (
            "Reads can be automated",
            "The agent checks setup, resolves attendees, discovers rooms, and finds available slots through structured MCP tools.",
            [
                ("resolve people", COLORS["blue"]),
                ("find rooms", COLORS["purple"]),
                ("suggest slots", COLORS["green"]),
            ],
        )
    if seconds < 43:
        return (
            "Writes require a checkpoint",
            "Before Exchange is changed, the server returns an exact preview with attendees, room, time, subject, and confirmation id.",
            [
                ("no invite sent yet", COLORS["amber"]),
                ("confirmation_id required", COLORS["blue"]),
                ("duplicate-send protection", COLORS["green"]),
            ],
        )
    return (
        "Auditable lifecycle",
        "Only after explicit confirmation does the tool create, verify, and record the meeting lifecycle result.",
        [
            ("verified calendar item", COLORS["green"]),
            ("local audit trail", COLORS["blue"]),
            ("strict enterprise boundary", COLORS["amber"]),
        ],
    )


def draw_terminal(draw: ImageDraw.ImageDraw, fonts: Fonts, seconds: float) -> None:
    x1, y1, x2, y2 = 560, 176, 1204, 610
    draw.rounded_rectangle((x1, y1, x2, y2), radius=18, fill=(5, 10, 18), outline=COLORS["line"], width=1)
    draw.rounded_rectangle((x1, y1, x2, y1 + 42), radius=18, fill=(24, 34, 52))
    draw.rectangle((x1, y1 + 22, x2, y1 + 42), fill=(24, 34, 52))
    draw.ellipse((x1 + 18, y1 + 15, x1 + 30, y1 + 27), fill=COLORS["red"])
    draw.ellipse((x1 + 40, y1 + 15, x1 + 52, y1 + 27), fill=COLORS["amber"])
    draw.ellipse((x1 + 62, y1 + 15, x1 + 74, y1 + 27), fill=COLORS["green"])
    draw.text((x1 + 96, y1 + 13), "safe fake MCP flow - no real EWS calls", font=fonts.mono_small, fill=COLORS["muted"])

    lines = terminal_lines(seconds)
    visible = reveal_count(seconds, lines)
    y = y1 + 64
    for line, color in lines[:visible][-14:]:
        draw.text((x1 + 24, y), line, font=fonts.mono, fill=color)
        y += 23

    if int(seconds * 2) % 2 == 0:
        draw.rectangle((x1 + 24, y + 3, x1 + 34, y + 20), fill=COLORS["green"])


def terminal_lines(seconds: float) -> list[tuple[str, tuple[int, int, int]]]:
    all_lines = [
        ("$ user: Find 30 min for Alice and Bob, with a 6-person room", COLORS["text"]),
        ("$ mcp.call ews_setup_check", COLORS["green"]),
        ('  ready: true | credential_source: "macOS Keychain"', COLORS["muted"]),
        ("  password_returned: false", COLORS["muted"]),
        ("$ mcp.call ews_resolve_attendees", COLORS["green"]),
        ("  Alice -> alice@example.com", COLORS["blue"]),
        ("  Bob   -> bob@example.com", COLORS["blue"]),
        ("$ mcp.call ews_list_rooms", COLORS["green"]),
        ("  3-1 Meeting Room(12P) available", COLORS["purple"]),
        ("  3-2 Meeting Room(6P) available", COLORS["purple"]),
        ("$ mcp.call ews_suggest_slots", COLORS["green"]),
        ("  2026-06-15 11:00-11:30 | 3-2 Meeting Room", COLORS["text"]),
        ("  2026-06-16 15:30-16:00 | 3-1 Meeting Room", COLORS["text"]),
        ("$ mcp.call ews_create_meeting_preview", COLORS["amber"]),
        ("  action: dry_run", COLORS["amber"]),
        ("  will_send_invites: false", COLORS["amber"]),
        ("  confirmation_id: demo-8f0c1c4d", COLORS["blue"]),
        ("$ user confirms exact invite", COLORS["text"]),
        ("$ mcp.call ews_create_meeting_confirmed", COLORS["green"]),
        ("  confirm: true | duplicate_guard: recorded", COLORS["green"]),
        ("$ mcp.call ews_verify_meeting", COLORS["green"]),
        ("  organizer_item: verified", COLORS["green"]),
        ("  room_response_status: pending", COLORS["muted"]),
        ("$ result: local credentials, confirmed write, audit-friendly", COLORS["blue"]),
    ]
    return all_lines


def reveal_count(seconds: float, lines: list[tuple[str, tuple[int, int, int]]]) -> int:
    if seconds < 4:
        return 1
    progress = min(1.0, max(0.0, (seconds - 4) / 52))
    eased = 1 - math.pow(1 - progress, 2.2)
    return max(1, min(len(lines), int(1 + eased * (len(lines) - 1))))


def draw_footer(draw: ImageDraw.ImageDraw, fonts: Fonts, seconds: float) -> None:
    text = "Credentials stay local. Writes require confirmation. Built for strict enterprise Exchange environments."
    alpha_color = COLORS["text"] if seconds > 45 else COLORS["muted"]
    draw.text((76, 632), text, font=fonts.subtitle, fill=alpha_color)


def pill(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    text: str,
    fill: tuple[int, int, int],
    accent: tuple[int, int, int],
    font: ImageFont.FreeTypeFont,
) -> None:
    draw.rounded_rectangle(box, radius=16, fill=fill, outline=(52, 70, 96), width=1)
    draw.ellipse((box[0] + 12, box[1] + 11, box[0] + 22, box[1] + 21), fill=accent)
    draw.text((box[0] + 34, box[1] + 8), text, font=font, fill=COLORS["text"])


def draw_wrapped(
    draw: ImageDraw.ImageDraw,
    text: str,
    xy: tuple[int, int],
    max_width: int,
    font: ImageFont.FreeTypeFont,
    fill: tuple[int, int, int],
    line_gap: int = 6,
) -> None:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = word if not current else f"{current} {word}"
        if draw.textlength(candidate, font=font) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)

    x, y = xy
    for line in lines:
        draw.text((x, y), line, font=font, fill=fill)
        y += font.size + line_gap


def render_mp4() -> None:
    run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-framerate",
            str(FPS),
            "-i",
            str(FRAMES_DIR / "%04d.png"),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(MP4_PATH),
        ]
    )


def render_gif() -> None:
    palette = OUT_DIR / "palette.png"
    run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(MP4_PATH),
            "-vf",
            "fps=8,scale=960:-1:flags=lanczos,palettegen",
            str(palette),
        ]
    )
    run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(MP4_PATH),
            "-i",
            str(palette),
            "-lavfi",
            "fps=8,scale=960:-1:flags=lanczos[x];[x][1:v]paletteuse",
            str(GIF_PATH),
        ]
    )
    palette.unlink(missing_ok=True)


def run(command: list[str]) -> None:
    subprocess.run(command, check=True)


if __name__ == "__main__":
    main()
