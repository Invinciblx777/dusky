#!/usr/bin/env python3
# ==============================================================================
# Description: Advanced TUI for Hyprland 0.55+ Lua Keybinds
#              - Clean UI: Hides raw Lua syntax on the front page for readability
#              - Lexically perfect parser (supports [=[ Lua long brackets ]=])
#              - Safely modifies dotfiles (resolves symlinks before atomic write)
#              - Native hl.unbind() generation to prevent zombie source keys
#              - Smart UI Deduplication (Hides backend unbind shields)
#              - Complete submap awareness
#              - XDG Base Directory Specification compliant
# ==============================================================================

from __future__ import annotations

import atexit
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

try:
    import readline
except ImportError:
    pass

# ──────────────────────────────────────────────────────────────────────────────
# ANSI Colours & Formatting
# ──────────────────────────────────────────────────────────────────────────────
BLUE         = '\033[0;34m'
GREEN        = '\033[0;32m'
YELLOW       = '\033[0;33m'
RED          = '\033[0;31m'
CYAN         = '\033[0;36m'
PURPLE       = '\033[0;35m'
GREY         = '\033[0;90m'
BOLD         = '\033[1m'
RESET        = '\033[0m'
DIM          = '\033[2m'

# ──────────────────────────────────────────────────────────────────────────────
# Paths (XDG Compliant)
# ──────────────────────────────────────────────────────────────────────────────
HOME = Path.home()
XDG_CONFIG_HOME = Path(os.environ.get('XDG_CONFIG_HOME', HOME / '.config'))

SOURCE_LUA = XDG_CONFIG_HOME / 'hypr/source/keybinds.lua'
CUSTOM_LUA = XDG_CONFIG_HOME / 'hypr/edit_here/source/keybinds.lua'

# ──────────────────────────────────────────────────────────────────────────────
# Runtime globals & Templates
# ──────────────────────────────────────────────────────────────────────────────
VIEW_ONLY = False
_in_alt   = False

EMPTY_TEMPLATE = 'hl.bind("SUPER + ", hl.dsp.exec_cmd(""), { description = "" })'

# ==============================================================================
# Data Structures
# ==============================================================================

@dataclass
class Bind:
    """Represents one parsed hl.bind() or hl.unbind() call."""
    key_str:     str   
    norm_mods:   str   
    norm_key:    str   
    dispatcher:  str   
    options:     str   
    description: str   
    submap:      str   
    raw_call:    str   
    origin:      str   
    char_start:  int   
    char_end:    int   
    is_unbind:   bool = False

# ==============================================================================
# System Utilities
# ==============================================================================

def enter_alt_screen() -> None:
    global _in_alt
    os.system('tput smcup 2>/dev/null')
    _in_alt = True

def leave_alt_screen() -> None:
    global _in_alt
    if _in_alt:
        os.system('tput rmcup 2>/dev/null')
        _in_alt = False

def cleanup() -> None:
    leave_alt_screen()

def die(msg: str) -> None:
    print(f'{RED}[FATAL]{RESET} {msg}', file=sys.stderr)
    cleanup()
    sys.exit(1)

atexit.register(cleanup)

def atomic_write(content: str, path: Path) -> None:
    real = path.resolve()
    real.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=real.parent, prefix='.keybinds_write_')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as fh:
            fh.write(content)
        try:
            if real.exists():
                os.chmod(tmp, real.stat().st_mode)
        except FileNotFoundError:
            pass
        os.replace(tmp, real)
    except Exception:
        try:
            os.unlink(tmp)
        except Exception:
            pass
        raise

def reload_hyprland() -> None:
    if not os.environ.get('HYPRLAND_INSTANCE_SIGNATURE'):
        print(f'{DIM}Not running under Hyprland; skipping reload.{RESET}')
        return
    if not shutil.which('hyprctl'): return
    result = subprocess.run(['hyprctl', 'reload'], capture_output=True, text=True)
    if result.returncode == 0:
        print(f'{GREEN}Hyprland configuration reloaded.{RESET}')
    else:
        out = (result.stdout or result.stderr or '').strip()
        print(f'{YELLOW}[WARNING]{RESET} Hyprland reload issue: {out}')
        print('  Keybind was saved. Reload manually or restart Hyprland.')

# ==============================================================================
# Robust Lua Lexical Parsing
# ==============================================================================

def get_long_bracket_end(code: str, start_idx: int) -> int:
    q = start_idx + 1
    while q < len(code) and code[q] == '=':
        q += 1
    if q < len(code) and code[q] == '[':
        eq_count = q - start_idx - 1
        end_seq = ']' + ('=' * eq_count) + ']'
        end_idx = code.find(end_seq, q + 1)
        if end_idx != -1:
            return end_idx + len(end_seq)
    return -1

def build_active_code_mask(code: str) -> list[bool]:
    mask = [True] * len(code)
    i = 0
    n = len(code)

    while i < n:
        ch = code[i]
        if ch in ('"', "'"):
            mask[i] = False
            quote = ch
            i += 1
            while i < n:
                mask[i] = False
                if code[i] == '\\':
                    i += 1
                    if i < n: mask[i] = False
                elif code[i] == quote:
                    i += 1
                    break
                i += 1
        elif ch == '-' and i + 1 < n and code[i+1] == '-':
            mask[i] = False
            mask[i+1] = False
            i += 2
            if i < n and code[i] == '[':
                lb_end = get_long_bracket_end(code, i)
                if lb_end != -1:
                    while i < lb_end:
                        mask[i] = False
                        i += 1
                    continue
            while i < n and code[i] != '\n':
                mask[i] = False
                i += 1
        elif ch == '[':
            lb_end = get_long_bracket_end(code, i)
            if lb_end != -1:
                while i < lb_end:
                    mask[i] = False
                    i += 1
                continue
            i += 1
        else:
            i += 1
    return mask

def find_balanced_end(text: str, open_pos: int, mask: list[bool]) -> int:
    depth = 0
    for i in range(open_pos, len(text)):
        if not mask[i]: continue
        if text[i] == '(':
            depth += 1
        elif text[i] == ')':
            depth -= 1
            if depth == 0:
                return i + 1
    return len(text)

def split_top_args(text: str, start_idx: int, end_idx: int, mask: list[bool]) -> list[str]:
    args = []
    buf = []
    depth = 0
    for i in range(start_idx, end_idx):
        ch = text[i]
        if not mask[i]:
            buf.append(ch)
            continue
        if ch in ('(', '[', '{'):
            depth += 1
            buf.append(ch)
        elif ch in (')', ']', '}'):
            depth -= 1
            buf.append(ch)
        elif ch == ',' and depth == 0:
            args.append(''.join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    if buf:
        args.append(''.join(buf).strip())
    return args

def strip_quotes(arg: str) -> str:
    arg = arg.strip()
    if arg.startswith('"') and arg.endswith('"'): return arg[1:-1]
    if arg.startswith("'") and arg.endswith("'"): return arg[1:-1]
    m = re.match(r'^\[(=*)\[(.*)\]\1\]$', arg, re.DOTALL)
    if m: return m.group(2)
    return arg

def extract_local_vars(text: str, mask: list[bool]) -> dict[str, str]:
    result = {}
    for m in re.finditer(r'local\s+(\w+)\s*=\s*"([^"]*)"', text):
        if mask[m.start()]: result[m.group(1)] = m.group(2)
    for m in re.finditer(r"local\s+(\w+)\s*=\s*'([^']*)'", text):
        if mask[m.start()]: result[m.group(1)] = m.group(2)
    return result

def resolve_key_arg(arg: str, local_vars: dict[str, str]) -> str:
    if '..' in arg:
        parts = [p.strip() for p in arg.split('..')]
        pieces = []
        for part in parts:
            if part.startswith('"') or part.startswith("'") or part.startswith('['):
                pieces.append(strip_quotes(part))
            elif part in local_vars:
                pieces.append(local_vars[part])
            else:
                pieces.append('SUPER')
        return ''.join(pieces)
    if not (arg.startswith('"') or arg.startswith("'") or arg.startswith('[')):
        return local_vars.get(arg, arg)
    return strip_quotes(arg)

def extract_description(options: str) -> str:
    for m in (re.search(r'description\s*=\s*"([^"]*)"', options),
              re.search(r"description\s*=\s*'([^']*)'", options)):
        if m: return m.group(1)
    return ''

_MOD_ALIASES = {
    'ctrl_l': 'ctrl',   'ctrl_r': 'ctrl',   'control': 'ctrl',
    'super_l': 'super', 'super_r': 'super', 'mod4': 'super',
    'alt_l': 'alt',     'alt_r': 'alt',     'mod1': 'alt',
    'shift_l': 'shift', 'shift_r': 'shift',
}

def normalize_key(key_str: str) -> tuple[str, str]:
    if '+' not in key_str:
        return '', key_str.strip().lower()
    
    parts = key_str.split('+')
    clean_parts = [p.strip().lower() for p in parts]
    
    if len(clean_parts) >= 2 and clean_parts[-1] == '':
        clean_parts = clean_parts[:-2] + ['+']
        
    clean_parts = [_MOD_ALIASES.get(p, p) for p in clean_parts if p]
    
    if not clean_parts: return '', ''
    if len(clean_parts) == 1: return '', clean_parts[0]
        
    mods = sorted(set(clean_parts[:-1]))
    key = clean_parts[-1]
    return '+'.join(mods), key

# ==============================================================================
# Engine API
# ==============================================================================

def find_submap_regions(text: str, mask: list[bool]) -> list[tuple[int, int, str]]:
    regions = []
    for m in re.finditer(r'hl\.define_submap\s*\(', text):
        start = m.start()
        if not mask[start]: continue
        paren_pos = text.find('(', start)
        end = find_balanced_end(text, paren_pos, mask)
        inner_start = paren_pos + 1
        inner_end = end - 1
        args = split_top_args(text, inner_start, inner_end, mask)
        if args:
            regions.append((start, end, strip_quotes(args[0])))
    return regions

def parse_lua_file_content(text: str, origin: str) -> list[Bind]:
    mask = build_active_code_mask(text)
    submap_regions = find_submap_regions(text, mask)
    local_vars = extract_local_vars(text, mask)
    binds = []

    for m in re.finditer(r'hl\.(bind|unbind)\s*\(', text):
        start = m.start()
        if not mask[start]: continue

        is_unbind = (m.group(1) == 'unbind')
        paren_pos = text.find('(', start)
        end = find_balanced_end(text, paren_pos, mask)
        
        args = split_top_args(text, paren_pos + 1, end - 1, mask)
        if not args: continue

        key_arg = resolve_key_arg(args[0], local_vars)
        
        if is_unbind:
            dispatcher = "UNBIND"
            options = ""
            description = "Source Bind Disabled"
        else:
            if len(args) < 2: continue
            dispatcher = args[1].strip()
            options = args[2].strip() if len(args) > 2 else ''
            description = extract_description(options)
        
        norm_mods, norm_key = normalize_key(key_arg)

        submap = ''
        for s, e, name in submap_regions:
            if s < start < e:
                submap = name
                break

        binds.append(Bind(
            key_str=key_arg,
            norm_mods=norm_mods,
            norm_key=norm_key,
            dispatcher=dispatcher,
            options=options,
            description=description,
            submap=submap,
            raw_call=text[start:end],
            origin=origin,
            char_start=start,
            char_end=end,
            is_unbind=is_unbind
        ))
    return binds

def _preceding_comment_start(text: str, block_start: int) -> int:
    line_start = text.rfind('\n', 0, block_start) + 1
    if line_start > 0:
        prev_nl = text.rfind('\n', 0, line_start - 1)
        prev_start = prev_nl + 1
        prev_line = text[prev_start: line_start - 1].strip()
        if re.match(r'^--\s*\[\d{4}-\d{2}-\d{2}', prev_line):
            return prev_start
    return line_start

def filter_out_bind_from_text(text: str, norm_mods: str, norm_key: str, submap: str) -> str:
    binds = parse_lua_file_content(text, "CUST")
    to_remove = []
    
    for b in binds:
        if b.norm_mods == norm_mods and b.norm_key == norm_key and b.submap == submap:
            blk_start = _preceding_comment_start(text, b.char_start)
            blk_end = b.char_end
            if blk_end < len(text) and text[blk_end] == '\n':
                blk_end += 1
            to_remove.append((blk_start, blk_end))

    if not to_remove: return text
    
    to_remove.sort(reverse=True)
    for start, end in to_remove:
        text = text[:start] + text[end:]
    return text

# ==============================================================================
# Dynamic UI Drawing System (Bulletproof Text Wrapping)
# ==============================================================================

def visible_len(text: str) -> int:
    """Returns the visual length of a string, ignoring ANSI color codes."""
    return len(re.sub(r'\x1b\[[0-9;]*m', '', text))

def print_main_header(subtitle: str, width: int = 80) -> None:
    """Draws the main unified branding header (Dusky Binds)."""
    brand = " Dusky Binds "
    left_len = (width - 2 - len(brand)) // 2
    right_len = width - 2 - len(brand) - left_len
    
    print(f'{PURPLE}╭{"─" * left_len}{RESET}{BOLD}{YELLOW}{brand}{RESET}{PURPLE}{"─" * right_len}╮{RESET}')
    
    pad_left = (width - 2 - visible_len(subtitle)) // 2
    pad_right = width - 2 - visible_len(subtitle) - pad_left
    print(f'{PURPLE}│{RESET}{" " * pad_left}{subtitle}{" " * pad_right}{PURPLE}│{RESET}')
    print(f'{PURPLE}╰{"─" * (width - 2)}╯{RESET}')

def draw_box_row(label: str, text: str, label_color: str, text_color: str, width: int = 80, border_color: str = BLUE) -> list[str]:
    """Dynamically wraps text inside a perfectly aligned bounding box."""
    # 1(bord) + 2(spc) + 10(lbl) + 3( : ) + 1(bord) = 17 physical characters reserved
    max_text_len = width - 17
    
    lines = textwrap.wrap(text, width=max_text_len)
    if not lines:
        lines = [""]
        
    rows = []
    for i, line in enumerate(lines):
        lbl_text = label if i == 0 else ""
        lbl = f"{label_color}{lbl_text:<10}{RESET}"
        val = f"{text_color}{line}{RESET}"
        pad = max_text_len - len(line)
        separator = " : " if i == 0 else "   "
        
        rows.append(f"{border_color}│{RESET}  {lbl}{separator}{val}{' ' * pad}{border_color}│{RESET}")
    return rows

def print_binding_info_box(bind: Bind, raw_text: str, width: int = 80) -> None:
    print(f'{BLUE}╭─ [ CURRENT BINDING INFO ] {"─" * (width - 29)}╮{RESET}')
    
    for row in draw_box_row("Key Comb", bind.key_str, BOLD, GREEN, width, BLUE): print(row)
    if bind.submap:
        for row in draw_box_row("Submap", bind.submap, BOLD, PURPLE, width, BLUE): print(row)
        
    for row in draw_box_row("Action", bind.dispatcher, BOLD, CYAN, width, BLUE): print(row)
    
    # Empty separator line for semantic spacing
    print(f'{BLUE}│{RESET}{" " * (width - 2)}{BLUE}│{RESET}')
    
    for row in draw_box_row("Raw Lua", raw_text, BOLD, DIM, width, BLUE): print(row)
    
    print(f'{BLUE}╰{"─" * (width - 2)}╯{RESET}')

def draw_help_box(width: int = 80) -> None:
    print(f'{YELLOW}╭─ [ QUICK INSTRUCTIONS ] {"─" * (width - 27)}╮{RESET}')
    for row in draw_box_row("Syntax", 'hl.bind("MODS + KEY", DISPATCHER[, OPTIONS])', BOLD, GREEN, width, YELLOW): print(row)
    for row in draw_box_row("Example", 'hl.bind("SUPER + Q", hl.dsp.exec_cmd("kitty"))', BOLD, DIM, width, YELLOW): print(row)
    print(f'{YELLOW}╰{"─" * (width - 2)}╯{RESET}')

def format_display(b: Bind) -> str:
    submap_pfx = f'{PURPLE}[{b.submap}]{RESET} ' if b.submap else ''
    ui_key = b.key_str[:32].ljust(32).replace('\n', ' ').replace('\t', ' ')

    if b.is_unbind:
        tag = f'{RED}[UNB]{RESET}'
        ui_desc = f'{DIM}Source Bind Disabled (Delete this to restore){RESET}'
        return f'{tag}  {submap_pfx}{RED}{ui_key}{RESET} {GREY}│{RESET} {ui_desc}'

    tag = f'{GREEN}[CUST]{RESET}' if b.origin == 'CUST' else f'{BLUE}[SRC] {RESET}'
    ui_desc = (b.description if b.description else "No Description").replace('\n', ' ').replace('\t', ' ')
    
    return f'{tag}  {submap_pfx}{BOLD}{ui_key}{RESET} {GREY}│{RESET} {ui_desc}'

def generate_bind_rows(source_binds: list[Bind], custom_binds: list[Bind]) -> tuple[list[str], list[Bind]]:
    custom_active = {(b.norm_mods, b.norm_key, b.submap) for b in custom_binds if not b.is_unbind}
    custom_ovr = {(b.norm_mods, b.norm_key, b.submap) for b in custom_binds}
    
    displayed = []
    
    for b in sorted(custom_binds, key=lambda x: f'{x.submap}|{x.norm_mods}|{x.norm_key}'):
        if b.is_unbind and (b.norm_mods, b.norm_key, b.submap) in custom_active:
            continue
        displayed.append(b)
        
    for b in sorted(source_binds, key=lambda x: f'{x.submap}|{x.norm_mods}|{x.norm_key}'):
        if (b.norm_mods, b.norm_key, b.submap) not in custom_ovr:
            displayed.append(b)

    rows = [f'{format_display(b)}\t{idx}' for idx, b in enumerate(displayed)]
    return rows, displayed

def rlinput(prompt: str, prefill: str = '') -> str:
    """Prompt for input with prefill support safely avoiding readline segfaults."""
    if 'readline' in sys.modules:
        safe_prompt = re.sub(r'(\033\[[0-9;]*m)', '\x01\\1\x02', prompt)
        def _hook():
            readline.insert_text(prefill)
        readline.set_startup_hook(_hook)
        try:
            return input(safe_prompt)
        finally:
            readline.set_startup_hook(None)
    else:
        print(f"{DIM}(Prefill not supported on this terminal. Original: {prefill}){RESET}")
        return input(prompt)

# ==============================================================================
# Core Flow Operations
# ==============================================================================

def edit_loop(bind: Optional[Bind], source_binds: list[Bind], custom_binds: list[Bind]) -> bool:
    origin = bind.origin if bind else 'NEW'
    raw_old = bind.raw_call.replace('\n', ' ').replace('\t', '  ').strip() if bind else EMPTY_TEMPLATE
    bind_submap = bind.submap if bind else ''
    orig_mods = bind.norm_mods if bind else ''
    orig_key = bind.norm_key if bind else ''

    current_input = raw_old
    BW = 80 # Box Width

    mode_title = f"[ {origin} EDIT ]" if origin != 'NEW' else "[ CREATE NEW KEYBIND ]"

    while True:
        enter_alt_screen()
        os.system('tput clear 2>/dev/null || clear')
        
        # ─── BRANDING HEADER ───
        print_main_header(f"{BOLD}{mode_title}{RESET}", BW)
        print()

        # ─── TARGET INFO BOX ───
        if bind and origin != 'NEW':
            print_binding_info_box(bind, raw_old, BW)
            print()

        # ─── HELP BOX ───
        draw_help_box(BW)
        print()

        # ─── INPUT PROMPT ───
        print(f'{BOLD}Update hl.bind() call  {DIM}("b" = back · "q" = quit){RESET}:')
        try:
            user_line = rlinput(f'{PURPLE}❯ {RESET}', current_input).strip()
        except (EOFError, KeyboardInterrupt):
            leave_alt_screen()
            return False

        if user_line.lower() in ('b', 'back'):
            leave_alt_screen()
            return False
        if user_line.lower() in ('q', 'quit'):
            die("Exiting...")
        if not user_line or user_line == EMPTY_TEMPLATE:
            continue

        temp_binds = parse_lua_file_content(user_line, "TMP")
        if not temp_binds:
            leave_alt_screen()
            print(f'\n{RED}Error:{RESET} Input must be a valid hl.bind(...) call.')
            input('Press Enter to continue...')
            current_input = user_line
            continue

        new_b = temp_binds[0]
        new_mods, new_key = new_b.norm_mods, new_b.norm_key

        leave_alt_screen()
        print(f'\n{CYAN}Checking for conflicts...{RESET} ', end='', flush=True)

        conflict_cust = next((b for b in custom_binds if b.norm_mods == new_mods and b.norm_key == new_key and b.submap == bind_submap and (orig_mods != new_mods or orig_key != new_key)), None)
        conflict_src = next((b for b in source_binds if b.norm_mods == new_mods and b.norm_key == new_key and b.submap == bind_submap), None)

        if conflict_cust:
            print(f'{RED}CONFLICT (Custom)!{RESET}\n  {conflict_cust.raw_call.replace(chr(10)," ")[:80]}')
            print(f'\n{YELLOW}[y] Overwrite existing  [n] Retry  [b] Back{RESET}')
            ch = input('Select > ').strip().lower()
            if ch.startswith('b'): return False
            if not ch.startswith('y'):
                current_input = user_line
                continue
        elif conflict_src:
            print(f'{YELLOW}CONFLICT (Source){RESET}\n  {conflict_src.raw_call.replace(chr(10)," ")[:80]}')
            print(f'  {DIM}Your custom bind will take precedence.{RESET}')
        else:
            print(f'{GREEN}None{RESET}')

        # ─── CONFIRMATION BOX ───
        print(f'\n{CYAN}┌─ [ CONFIRM CHANGES ] {"─" * (BW - 24)}┐{RESET}')
        for row in draw_box_row("Action", "SAVE", BOLD, RESET, BW, CYAN): print(row)
        
        if bind_submap:
            for row in draw_box_row("Submap", bind_submap, BOLD, PURPLE, BW, CYAN): print(row)
            
        if raw_old and raw_old != EMPTY_TEMPLATE and origin != 'NEW':
            for row in draw_box_row("OLD", raw_old, RED, DIM, BW, CYAN): print(row)
            
        new_clean = user_line.replace('\n', ' ').replace('\t', '  ')
        for row in draw_box_row("NEW", new_clean, GREEN, RESET, BW, CYAN): print(row)
        print(f'{CYAN}└{"─" * (BW - 2)}┘{RESET}')

        print(f'\n{YELLOW}[y] Confirm  [n] Go Back{RESET}')
        if not input('Select > ').strip().lower().startswith('y'):
            current_input = user_line
            continue

        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M')
        try:
            text = CUSTOM_LUA.read_text(encoding='utf-8')
        except FileNotFoundError:
            text = ''

        if orig_mods or orig_key:
            text = filter_out_bind_from_text(text, orig_mods, orig_key, bind_submap)

        key_changed = (orig_mods != new_mods) or (orig_key != new_key)
        
        if key_changed and bind:
            src_conflict_old = next((b for b in source_binds if b.norm_mods == orig_mods and b.norm_key == orig_key and b.submap == bind_submap), None)
            if src_conflict_old:
                unbind_stmt = f'hl.unbind("{src_conflict_old.key_str}")'
                cmt = f'-- [{timestamp}] UNBIND (Moved away from SRC key)'
                if bind_submap:
                    unbind_block = f'\n{cmt}\nhl.define_submap("{bind_submap}", function()\n    {unbind_stmt}\nend)\n'
                else:
                    unbind_block = f'\n{cmt}\n{unbind_stmt}\n'
                text = text.rstrip('\n') + '\n' + unbind_block

        if conflict_cust:
            text = filter_out_bind_from_text(text, new_mods, new_key, bind_submap)

        comment = f'-- [{timestamp}] {origin}'
        
        unbind_prefix = ""
        if conflict_src:
            if bind_submap:
                unbind_prefix = f'hl.unbind("{conflict_src.key_str}")\n    '
            else:
                unbind_prefix = f'hl.unbind("{conflict_src.key_str}")\n'

        if bind_submap:
            new_block = f'\n{comment}\nhl.define_submap("{bind_submap}", function()\n    {unbind_prefix}{user_line}\nend)\n'
        else:
            new_block = f'\n{comment}\n{unbind_prefix}{user_line}\n'

        text = text.rstrip('\n') + '\n' + new_block
        atomic_write(text, CUSTOM_LUA)

        print(f'\n{GREEN}[SUCCESS]{RESET} Saved to {CUSTOM_LUA}')
        reload_hyprland()
        return True

def delete_flow(bind: Bind) -> bool:
    BW = 80
    raw_preview = bind.raw_call.replace('\n', ' ').replace('\t', '  ')
    
    os.system('tput clear 2>/dev/null || clear')
    print_main_header(f"{BOLD}[ DELETE KEYBIND ]{RESET}", BW)
    print()
    
    print(f'{CYAN}┌─ [ CONFIRM DELETION ] {"─" * (BW - 25)}┐{RESET}')
    
    if bind.submap: 
        for row in draw_box_row("Submap", bind.submap, BOLD, PURPLE, BW, CYAN): print(row)
    
    if bind.origin == 'SRC':
        for row in draw_box_row("Action", "DISABLE SOURCE BIND", BOLD, RESET, BW, CYAN): print(row)
        for row in draw_box_row("Target", raw_preview, RED, RESET, BW, CYAN): print(row)
        for row in draw_box_row("Info", "(This dynamically appends hl.unbind() to custom config)", DIM, DIM, BW, CYAN): print(row)
    else:
        act_text = "RESTORE SOURCE BIND" if bind.is_unbind else "DELETE FROM CUSTOM FILE"
        for row in draw_box_row("Action", act_text, BOLD, RESET, BW, CYAN): print(row)
        for row in draw_box_row("Target", raw_preview, RED, RESET, BW, CYAN): print(row)

    print(f'{CYAN}└{"─" * (BW - 2)}┘{RESET}')
    
    print(f'\n{YELLOW}[y] Confirm  [n] Go Back{RESET}')
    if not input('Select > ').strip().lower().startswith('y'): return False

    try:
        text = CUSTOM_LUA.read_text(encoding='utf-8')
    except FileNotFoundError:
        text = ''

    if bind.origin == 'SRC':
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M')
        
        text = filter_out_bind_from_text(text, bind.norm_mods, bind.norm_key, bind.submap)
        
        comment = f'-- [{timestamp}] UNBIND SRC'
        if bind.submap:
            new_block = f'\n{comment}\nhl.define_submap("{bind.submap}", function()\n    hl.unbind("{bind.key_str}")\nend)\n'
        else:
            new_block = f'\n{comment}\nhl.unbind("{bind.key_str}")\n'

        text = text.rstrip('\n') + '\n' + new_block
        atomic_write(text, CUSTOM_LUA)
        print(f'\n{GREEN}[SUCCESS]{RESET} Source bind disabled.')
    else:
        new_text = filter_out_bind_from_text(text, bind.norm_mods, bind.norm_key, bind.submap)
        atomic_write(new_text, CUSTOM_LUA)
        if bind.is_unbind:
            print(f'\n{GREEN}[SUCCESS]{RESET} Source bind restored.')
        else:
            print(f'\n{GREEN}[SUCCESS]{RESET} Keybind removed.')

    reload_hyprland()
    return True

# ==============================================================================
# Main Execution
# ==============================================================================

def main() -> None:
    global VIEW_ONLY
    if '--view' in sys.argv: VIEW_ONLY = True

    if not shutil.which('fzf'): die("'fzf' is required but not installed.")
    CUSTOM_LUA.parent.mkdir(parents=True, exist_ok=True)
    if not CUSTOM_LUA.exists():
        CUSTOM_LUA.write_text('-- Custom Hyprland Keybinds Override File\n\n', encoding='utf-8')

    while True:
        leave_alt_screen()
        
        try:
            src_text = SOURCE_LUA.read_text(encoding='utf-8')
        except FileNotFoundError:
            src_text = ""
            
        try:
            cust_text = CUSTOM_LUA.read_text(encoding='utf-8')
        except FileNotFoundError:
            cust_text = ""

        source_binds = parse_lua_file_content(src_text, 'SRC')
        custom_binds = parse_lua_file_content(cust_text, 'CUST')

        rows, displayed = generate_bind_rows(source_binds, custom_binds)
        
        # Build the FZF Branded Header
        brand = " Dusky Binds "
        bl = (80 - len(brand)) // 2
        br = 80 - len(brand) - bl
        fzf_brand = f"\033[0;35m{'─' * bl}\033[0m\033[1m\033[0;33m{brand}\033[0m\033[0;35m{'─' * br}\033[0m"
        
        fzf_header = f'{fzf_brand}\n  SELECT KEYBIND  │  SRC = Default  │  CUST = Your Override  │  [UNB] = Disabled Source Bind\n  Type to search · Enter = select · Esc = quit'

        if VIEW_ONLY:
            res = subprocess.run(['fzf', '--ansi', '--delimiter=\t', '--with-nth=1', f'--header=[VIEW MODE]\n{fzf_header}', '--info=inline', '--layout=reverse', '--border', '--prompt=Search > '], input='\n'.join(rows), capture_output=True, text=True)
            if res.returncode != 0: sys.exit(0)
            
            try:
                idx = int(res.stdout.strip().rsplit('\t', 1)[-1]) if res.stdout.strip() else -1
            except (ValueError, IndexError):
                idx = -1
                
            if 0 <= idx < len(displayed):
                print(f'\n{BOLD}{displayed[idx].raw_call}{RESET}')
            input('Press Enter to continue...')
            continue

        create_row = f'{BOLD}[+] Create New Keybind{RESET}\t-1'
        fzf_input = create_row + '\n' + '\n'.join(rows)

        res = subprocess.run(['fzf', '--ansi', '--delimiter=\t', '--with-nth=1', f'--header={fzf_header}', '--info=inline', '--layout=reverse', '--border', '--prompt=Search > '], input=fzf_input, capture_output=True, text=True)
        if res.returncode != 0: sys.exit(0)

        selected = res.stdout.strip()
        if not selected: continue

        try:
            idx = int(selected.rsplit('\t', 1)[-1])
        except (ValueError, IndexError):
            continue

        if idx == -1:
            edit_loop(None, source_binds, custom_binds)
            continue

        if 0 <= idx < len(displayed):
            selected_bind = displayed[idx]
            raw_clean = selected_bind.raw_call.replace('\n', ' ').replace('\t', '  ')
            
            print() # Visual Spacer
            print_binding_info_box(selected_bind, raw_clean, 80)
            
            print(f'\n{YELLOW}[e] Edit  [d] Delete  [b] Back  [q] Quit{RESET}')
            ch = input('Select > ').strip().lower()

            if ch.startswith('q'): sys.exit(0)
            elif ch.startswith('d'):
                delete_flow(selected_bind)
                input('Press Enter to continue...')
            elif ch.startswith('e'):
                if getattr(selected_bind, 'is_unbind', False):
                    print(f'\n{YELLOW}[NOTE]{RESET} Cannot directly edit an Unbind directive. Delete it to restore the source bind, or select "Create New Keybind".')
                    input('Press Enter to continue...')
                    continue
                
                changed = edit_loop(selected_bind, source_binds, custom_binds)
                if changed:
                    print(f'\n{YELLOW}[Enter] Edit another  [q] Quit{RESET}')
                    if input('Select > ').strip().lower().startswith('q'): sys.exit(0)

if __name__ == '__main__':
    main()
