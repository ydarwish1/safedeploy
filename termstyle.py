#!/usr/bin/env python3
"""
SafeDeploy - terminal styling for the demo surfaces.

One tiny place for ANSI color so inject.py, chaos.py, and watcher.py read
beautifully on camera. Color turns itself off when output is not a TTY (so
piped logs and CI stay clean) or when NO_COLOR is set. Pure presentation:
nothing here touches logic, devices, or exit codes.
"""

import os
import sys

_ON = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None

_C = {"reset":"\033[0m","bold":"\033[1m","dim":"\033[2m",
      "green":"\033[38;5;42m","red":"\033[38;5;204m","yellow":"\033[38;5;221m",
      "cyan":"\033[38;5;44m","violet":"\033[38;5;105m","grey":"\033[38;5;245m"}


def c(text, *styles):
    """Wrap text in ANSI styles (no-op when color is off)."""
    if not _ON or not styles:
        return str(text)
    return "".join(_C[s] for s in styles) + str(text) + _C["reset"]


def banner(title, subtitle=""):
    """A boxed header for the start of a demo."""
    width = max(len(title), len(subtitle)) + 6
    top = "╔" + "═" * width + "╗"
    bot = "╚" + "═" * width + "╝"
    print(c(top, "violet"))
    print(c("║", "violet") + c(title.center(width), "bold") + c("║", "violet"))
    if subtitle:
        print(c("║", "violet") + c(subtitle.center(width), "grey") + c("║", "violet"))
    print(c(bot, "violet"))


def step(tag, msg):
    """A labeled progress line: [tag] message."""
    print(c(f"[{tag}]", "cyan", "bold") + " " + msg)


def good(msg):
    print(c("✔ ", "green", "bold") + c(msg, "green"))


def bad(msg):
    print(c("✘ ", "red", "bold") + c(msg, "red"))


def verdict(v):
    """Color a SAFE/UNSAFE/WARN verdict word."""
    style = {"SAFE":"green","UNSAFE":"red"}.get(v, "yellow")
    return c(v, style, "bold")
