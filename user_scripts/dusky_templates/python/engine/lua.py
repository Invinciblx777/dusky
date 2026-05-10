#!/usr/bin/env python3
import os
import stat
import json
import subprocess
import tempfile
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Dict, Tuple, List

from textual.app import App, ComposeResult
from textual.widgets import OptionList, Input, Label, Header, RichLog
from textual.widgets.option_list import Option
from textual.containers import Vertical

# =============================================================================
# [ BLOCK 1: THE ENGINE ]
# Armored with Python Raw Strings (r"") to prevent Python from parsing
# Lua escape sequences, completely neutralizing syntax corruption.
# Optimized with Atomic Commit/Rollback integrity.
# =============================================================================

class HyprlandLuaEngine:
    def __init__(self, config_path: str = "~/Documents/hyprland.lua"):
        self.config_path = Path(config_path).expanduser().resolve()
        self.config_dir = self.config_path.parent
        self.lua_bin = self._find_lua()
        self.cache: Dict[str, Any] = {}
        self.loaded_files: List[str] = []
        self.file_mtimes: Dict[str, float] = {}

    def _find_lua(self) -> str:
        for cmd in ["lua5.4", "lua54", "lua"]:
            try:
                res = subprocess.run([cmd, "-e", "assert(_VERSION:match('5%.[4-9]'))"], capture_output=True, text=True)
                if res.returncode == 0: return cmd
            except FileNotFoundError: continue
        raise RuntimeError("Lua 5.4+ not found.")

    def _is_safe_path(self, target_path: str) -> bool:
        """Jail constraint: Only allow .lua files within the config directory hierarchy."""
        try:
            resolved = Path(target_path).resolve()
            return resolved.suffix == '.lua' and self.config_dir in resolved.parents
        except Exception:
            return False

    def load_state(self) -> Dict[str, Any]:
        if not self.config_path.exists(): 
            return {}

        self.file_mtimes[str(self.config_path)] = self.config_path.stat().st_mtime

        lua_evaluator = r"""
        local main_path = arg[1]
        local config_root = {}
        local loaded_files = {main_path}
        
        local function deep_merge(dst, src) 
            for k, v in pairs(src) do 
                if type(v) == "table" then 
                    if type(dst[k]) ~= "table" then dst[k] = {} end 
                    deep_merge(dst[k], v) 
                else dst[k] = v end 
            end 
            return dst 
        end
        
        local inert_proxy
        local proxy_mt = {
            __index = function() return inert_proxy end,
            __newindex = function() end,
            __call = function() return inert_proxy end,
            __tostring = function() return "" end,
            __concat = function() return "" end,
            __len = function() return 0 end,
        }
        inert_proxy = setmetatable({}, proxy_mt)
        
        local hl = setmetatable({}, { __index = function() return inert_proxy end })
        hl.config = function(tbl) if type(tbl) == "table" then deep_merge(config_root, tbl) end end

        local safe_env = { 
            hl = hl, math = math, string = string, table = table, type = type, 
            pairs = pairs, ipairs = ipairs, tostring = tostring, tonumber = tonumber, 
            os = {getenv = function() return nil end}, 
            io = {
                open = function(path, mode)
                    if mode and mode:match("w") then return nil end
                    if path:match("^/dev/") then return nil end
                    return io.open(path, "r")
                end
            }, 
            print = function(...) 
                local args = {...}
                for i, v in ipairs(args) do io.stderr:write(tostring(v) .. "\t") end
                io.stderr:write("\n")
            end 
        }
        safe_env._G = safe_env
        
        safe_env.dofile = function(path) 
            if not path:match("%.lua$") then return nil end
            table.insert(loaded_files, path)
            local chunk = loadfile(path, "t", safe_env)
            if chunk then return chunk() end 
        end
        
        safe_env.require = function(path) return safe_env.dofile(path .. ".lua") end
        
        local chunk = loadfile(main_path, "t", safe_env)
        if chunk then pcall(chunk) end
        
        local out_state = {}
        local function escape_str(s) 
            s = s:gsub('\\', '\\\\'):gsub('"', '\\"'):gsub('\n', '\\n'):gsub('\r', '\\r'):gsub('\t', '\\t')
            s = s:gsub('[%c]', function(c) return string.format('\\u%04x', string.byte(c)) end)
            return '"' .. s .. '"' 
        end

        local function walk(t, scope) 
            for k, v in pairs(t) do 
                if type(k) == "string" then 
                    local new_scope = scope == "" and k or (scope .. "/" .. k)
                    if type(v) == "table" then walk(v, new_scope) 
                    else table.insert(out_state, escape_str(new_scope)..":"..escape_str(tostring(v))) end 
                end 
            end 
        end
        walk(config_root, "")
        
        local out_files = {}
        for _, f in ipairs(loaded_files) do table.insert(out_files, escape_str(f)) end
        
        io.stdout:write('{"state": {' .. table.concat(out_state, ",") .. '}, "files": [' .. table.concat(out_files, ",") .. ']}')
        """
        
        try:
            res = subprocess.run([self.lua_bin, "-", str(self.config_path)], input=lua_evaluator, text=True, encoding='utf-8', capture_output=True, timeout=3)
            if res.returncode == 0 and res.stdout.strip():
                data = json.loads(res.stdout)
                self.cache = data.get("state", {})
                
                raw_files = data.get("files", [str(self.config_path)])
                self.loaded_files = [f for f in raw_files if self._is_safe_path(f)]
                
                for f in self.loaded_files:
                    path_obj = Path(f)
                    if path_obj.exists():
                        self.file_mtimes[f] = path_obj.stat().st_mtime
                        
                return self.cache
            else:
                print(f"Load Error (Return Code {res.returncode}): {res.stderr}")
        except Exception as e: 
            print(f"Load Exception: {e}")
        return {}

    def _is_raw_lua_val(self, val: str) -> bool:
        if val in ["true", "false", "nil", "__DELETE__"]: return True
        try: float(val); return True
        except ValueError: pass
        if val.startswith("0x") and len(val) > 2 and all(c in "0123456789abcdefABCDEF" for c in val[2:]):
            return True
        return False

    def write_value(self, target_key: str, target_scope: str, new_value: str) -> Tuple[bool, str, str]:
        if not self.loaded_files: self.loaded_files = [str(self.config_path)]
        
        if self._is_raw_lua_val(new_value):
            val_str = new_value
        else:
            val_str = json.dumps(new_value, ensure_ascii=False)
            
        # Concurrency guard: verify MTime before starting mutation
        for src_file in self.loaded_files:
            target_path = Path(src_file)
            if target_path.exists():
                cached_mtime = self.file_mtimes.get(src_file)
                if cached_mtime and target_path.stat().st_mtime > cached_mtime:
                    return False, f"File {src_file} modified externally. Reload required.", ""

        val_path = ""
        success = False
        status_msg = "Failed"
        debug_output = ""
        
        pending_replacements: List[Tuple[str, Path, str]] = []
        temp_files_created: List[str] = []

        try:
            with tempfile.NamedTemporaryFile(mode='w', delete=False, encoding='utf-8') as vf:
                val_path = vf.name
                vf.write(val_str)

            lua_mutator = r"""
            local src_path = assert(arg[1], "missing source")
            local target_key = assert(arg[2], "missing key")
            local target_scope = assert(arg[3], "missing scope")
            local val_path = assert(arg[4], "missing value file")
            local out_path = assert(arg[5], "missing out file")

            local function read_file(path)
                local f = io.open(path, "rb")
                if not f then os.exit(4) end
                local s = f:read("*a"); f:close()
                return s
            end

            local text = read_file(src_path)
            local new_value = read_file(val_path)
            local len = #text
            local tokens = {}
            local pos = 1

            local function is_alpha(c) return c:match("^[A-Za-z_]$") ~= nil end
            local function is_alnum(c) return c:match("^[A-Za-z0-9_]$") ~= nil end
            local function is_space(c) return c == " " or c == "\t" or c == "\r" or c == "\n" or c == "\v" or c == "\f" end
            local function add(tp, val, s, e) tokens[#tokens + 1] = { type = tp, val = val, s = s, e = e } end

            local function long_bracket_end_at(p)
                if text:sub(p, p) ~= "[" then return nil end
                local q = p + 1
                while q <= len and text:sub(q, q) == "=" do q = q + 1 end
                if text:sub(q, q) ~= "[" then return nil end
                local eqs = text:sub(p + 1, q - 1)
                local close = "]" .. eqs .. "]"
                local found = text:find(close, q + 1, true)
                return found and (found + #close - 1) or nil
            end

            while pos <= len do
                local c = text:sub(pos, pos)
                if is_space(c) then pos = pos + 1
                elseif c == "-" and text:sub(pos + 1, pos + 1) == "-" then
                    pos = pos + 2
                    local lb_end = long_bracket_end_at(pos)
                    if lb_end then pos = lb_end + 1
                    else
                        local nl = text:find("\n", pos, true)
                        if nl then pos = nl + 1 else pos = len + 1 end
                    end
                elseif c == "'" or c == '"' then
                    local quote = c; local s = pos; pos = pos + 1
                    while pos <= len do
                        local ch = text:sub(pos, pos)
                        if ch == "\\" then pos = pos + 2
                        elseif ch == quote then pos = pos + 1; break
                        else pos = pos + 1 end
                    end
                    add("STRING", text:sub(s, pos - 1), s, pos - 1)
                elseif c == "[" then
                    local lb_end = long_bracket_end_at(pos)
                    if lb_end then add("STRING", text:sub(pos, lb_end), pos, lb_end); pos = lb_end + 1
                    else add("LBRACK", c, pos, pos); pos = pos + 1 end
                elseif is_alpha(c) then
                    local s = pos; pos = pos + 1
                    while pos <= len and is_alnum(text:sub(pos, pos)) do pos = pos + 1 end
                    add("IDENT", text:sub(s, pos - 1), s, pos - 1)
                elseif c:match("^[0-9]$") or (c == "." and text:sub(pos + 1, pos + 1):match("^[0-9]$")) then
                    local s = pos; pos = pos + 1
                    while pos <= len do
                        local nc = text:sub(pos, pos)
                        if nc:match("^[A-Za-z0-9_%.]$") then
                            pos = pos + 1
                        elseif (nc == "+" or nc == "-") and text:sub(pos - 1, pos - 1):match("^[eE]$") then
                            pos = pos + 1
                        else
                            break
                        end
                    end
                    add("NUMBER", text:sub(s, pos - 1), s, pos - 1)
                else
                    local map = { ["{"]="LBRACE", ["}"]="RBRACE", ["("]="LPAREN", [")"]="RPAREN", ["["]="LBRACK", ["]"]="RBRACK", ["="]="EQUALS", [","]="COMMA", [";"]="SEMI", ["."]="DOT", [":"]="COLON" }
                    add(map[c] or "OTHER", c, pos, pos); pos = pos + 1
                end
            end

            local function classify_raw(raw)
                local t = raw:gsub("^%s+", ""):gsub("%s+$", "")
                if t == "true" or t == "false" or t == "nil" then return "bool" end
                if t:find("^%[=*%[") or t:find("^['\"]") then return "string" end
                if tonumber(t) ~= nil then return "number" end
                return "expr"
            end

            local function format_replacement(old_raw)
                if new_value == "__DELETE__" then return "nil" end
                local kind = classify_raw(old_raw)
                if kind == "bool" then
                    if new_value == "true" or new_value == "false" or new_value == "nil" then return new_value end
                    return new_value == "0" and "false" or "true"
                elseif kind == "number" then
                    return new_value
                elseif kind == "string" then
                    local t = old_raw:gsub("^%s+", ""):gsub("%s+$", "")
                    if t:sub(1,1) == "[" then
                        local stripped_val = new_value:gsub('^"', ''):gsub('"$', '')
                        local open_bracket = t:match("^(%[=*%[)")
                        if open_bracket then
                            local close_bracket = open_bracket:gsub("%[", "%]")
                            if stripped_val:find(close_bracket, 1, true) then
                                return new_value
                            end
                            return open_bracket .. stripped_val .. close_bracket
                        end
                    end
                    return new_value
                end
                error("Target value is a complex expression: [" .. tostring(old_raw) .. "]")
            end

            local matches = {}
            local function scope_string(parts) return table.concat(parts, "/") end

            local parse_table
            local function find_rhs_end(i)
                local j = i; local depth = 0; local block_depth = 0; local rhs_end = i
                while j <= #tokens do
                    local tp = tokens[j].type; local val = tokens[j].val
                    if tp == "IDENT" and (val == "function" or val == "if" or val == "do" or val == "repeat") then 
                        block_depth = block_depth + 1
                    elseif tp == "IDENT" and (val == "end" or val == "until") and block_depth > 0 then 
                        block_depth = block_depth - 1 
                    end
                    if block_depth == 0 then
                        if tp == "LBRACE" or tp == "LPAREN" or tp == "LBRACK" then depth = depth + 1
                        elseif tp == "RBRACE" or tp == "RPAREN" or tp == "RBRACK" then if depth == 0 then break end; depth = depth - 1
                        elseif depth == 0 and (tp == "COMMA" or tp == "SEMI") then break end
                    end
                    rhs_end = j; j = j + 1
                end
                return rhs_end, j
            end

            local function key_at(i)
                local tok = tokens[i]
                if not tok then return nil, i end
                if tok.type == "IDENT" and tokens[i + 1] and tokens[i + 1].type == "EQUALS" then 
                    return tok.val, i + 2 
                end
                if tok.type == "LBRACK" and tokens[i + 1] and tokens[i + 1].type == "STRING" and tokens[i + 2] and tokens[i + 2].type == "RBRACK" and tokens[i + 3] and tokens[i + 3].type == "EQUALS" then
                    local str_val = tokens[i + 1].val
                    local clean_key = str_val:match("^['\"](.-)['\"]$")
                    if not clean_key then clean_key = str_val:match("^%[=*%[(.-)%]=*%]$") end
                    return clean_key or str_val, i + 4
                end
                return nil, i
            end

            parse_table = function(i, scope_parts)
                if not tokens[i] or tokens[i].type ~= "LBRACE" then return i end
                i = i + 1
                while i <= #tokens do
                    if tokens[i].type == "RBRACE" then return i + 1 end
                    if tokens[i].type == "COMMA" or tokens[i].type == "SEMI" then i = i + 1 goto continue end

                    local key, rhs = key_at(i)
                    if key then
                        local rhs_end, next_i = find_rhs_end(rhs)
                        if tokens[rhs] and tokens[rhs].type == "LBRACE" then
                            scope_parts[#scope_parts + 1] = key
                            parse_table(rhs, scope_parts)
                            scope_parts[#scope_parts] = nil
                        else
                            local curr_scope = scope_string(scope_parts)
                            if key == target_key and curr_scope == target_scope then
                                local raw = text:sub(tokens[rhs].s, tokens[rhs_end].e)
                                matches[#matches + 1] = { s = tokens[rhs].s, e = tokens[rhs_end].e, raw = raw }
                            end
                        end
                        i = next_i
                    else
                        local _, next_i = find_rhs_end(i)
                        if next_i <= i then next_i = i + 1 end
                        i = next_i
                    end
                    ::continue::
                end
                return i
            end

            local function config_arg_index(i)
                if tokens[i] and tokens[i].type == "IDENT" and tokens[i].val == "hl" and tokens[i+1] and tokens[i+1].type == "DOT" and tokens[i+2] and tokens[i+2].type == "IDENT" and tokens[i+2].val == "config" then
                    if tokens[i+3] and tokens[i+3].type == "LPAREN" then return i+4 end
                    if tokens[i+3] and tokens[i+3].type == "LBRACE" then return i+3 end
                end
                return nil
            end

            local i = 1
            while i <= #tokens do
                local arg = config_arg_index(i)
                if arg and tokens[arg] and tokens[arg].type == "LBRACE" then parse_table(arg, {}) end
                i = i + 1
            end

            io.stderr:write("[Telemetry] Found " .. #matches .. " match(es) for scope '" .. target_scope .. "/" .. target_key .. "'.\n")

            if #matches == 0 then os.exit(1) end
            
            for j = #matches, 1, -1 do
                local m = matches[j]
                io.stderr:write("[Telemetry] Processing match " .. j .. ": " .. m.raw .. "\n")
                local ok, repl_or_err = pcall(format_replacement, m.raw)
                if not ok then
                    io.stderr:write(tostring(repl_or_err), "\n")
                    os.exit(3)
                end
                text = text:sub(1, m.s - 1) .. repl_or_err .. text:sub(m.e + 1)
            end
            
            local out_f = io.open(out_path, "wb")
            if not out_f then os.exit(5) end
            out_f:write(text)
            out_f:close()
            os.exit(0)
            """
            
            for src_file in self.loaded_files:
                target_path = Path(src_file)
                if not target_path.exists() or not target_path.is_file(): continue
                
                out_fd, out_path = tempfile.mkstemp(dir=target_path.parent, text=True)
                os.close(out_fd)
                temp_files_created.append(out_path)

                # POSIX Permission synchronization
                try:
                    os.chmod(out_path, stat.S_IMODE(target_path.stat().st_mode))
                except OSError:
                    pass

                res = subprocess.run(
                    [self.lua_bin, "-", str(target_path), target_key, target_scope, val_path, out_path], 
                    input=lua_mutator, text=True, encoding='utf-8', capture_output=True, timeout=3
                )
                
                debug_output += res.stderr
                
                if res.returncode == 0:
                    pending_replacements.append((out_path, target_path, src_file))
                else:
                    if res.returncode != 1:
                        status_msg = f"Lua Error {res.returncode} in {src_file}"
                    break
            else:
                # Execution finishes clean if no break was hit
                if pending_replacements:
                    success = True

        except Exception as e:
            success = False
            status_msg = f"Execution Error: {e}"
            
        finally:
            if success:
                try:
                    for tmp_out, trg_path, src_f in pending_replacements:
                        os.replace(tmp_out, trg_path)
                        self.file_mtimes[src_f] = trg_path.stat().st_mtime
                    status_msg = f"Write Successful ({len(pending_replacements)} file(s) updated)"
                except OSError as e:
                    success = False
                    status_msg = f"Transaction Commit Error: {e}"

            # Post-transaction guaranteed garbage collection
            for tmp_file in temp_files_created:
                if os.path.exists(tmp_file):
                    try: os.unlink(tmp_file)
                    except OSError: pass
                    
            if val_path and os.path.exists(val_path):
                try: os.unlink(val_path)
                except OSError: pass

        if success:
            return True, status_msg, debug_output
            
        if not pending_replacements and status_msg == "Failed":
            return False, "No matches found in configuration tree", debug_output
            
        return False, status_msg, debug_output

# =============================================================================
# [ BLOCK 2: MICRO-UI / SANDBOX TESTER ]
# =============================================================================

@dataclass
class TestItem:
    label: str; key: str; scope: str;

TEST_SCHEMA = [
    TestItem("Border Size (Int)", "border_size", "general"),
    TestItem("Gaps Out (Int - Duplicate Test)", "gaps_out", "general"),
    TestItem("Rounding (Int)", "rounding", "decoration"),
    TestItem("Blur Enabled (Bool)", "enabled", "decoration/blur"),
    TestItem("Vibrancy (Float)", "vibrancy", "decoration/blur"),
    TestItem("Inactive Border (Hex Color)", "inactive_border", "general/col"),
    TestItem("Shadow Color (RGBA String)", "color", "decoration/shadow"),
    TestItem("Keyboard Layout (String)", "kb_layout", "input"),
    TestItem("Natural Scroll (Bool)", "natural_scroll", "input/touchpad"),
    TestItem("Disable Logo (Bool)", "disable_hyprland_logo", "misc"),
]

class EngineTestApp(App):
    CSS = """
    #main { height: 1fr; }
    #list { height: 1fr; }
    #debug-log { height: 12; border-top: solid $primary; background: $surface; }
    """

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="main", classes="container"):
            yield Label("Select an item to edit:", id="status")
            yield OptionList(id="list")
            yield Input(placeholder="Type new value (true/false/number/string) and press Enter...", id="input", disabled=True)
            yield RichLog(id="debug-log", highlight=True, markup=True)

    def on_mount(self) -> None:
        self.engine = HyprlandLuaEngine()
        self.state = self.engine.load_state()
        self.selected_item = None
        self.log_panel = self.query_one("#debug-log", RichLog)
        self.log_panel.write("[bold cyan]--- Lua Telemetry Engine Initialized ---[/]")
        self._refresh_list()

    def _refresh_list(self) -> None:
        ol = self.query_one(OptionList)
        ol.clear_options()
        for item in TEST_SCHEMA:
            cache_key = f"{item.scope}/{item.key}" if item.scope else item.key
            current_val = self.state.get(cache_key, "UNSET")
            ol.add_option(Option(f"{item.label}  -->  {current_val}"))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.selected_item = TEST_SCHEMA[event.option_index]
        inp = self.query_one(Input)
        inp.disabled = False
        inp.focus()
        self.query_one("#status", Label).update(f"Editing: {self.selected_item.label}")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if not self.selected_item: return
        new_val = event.value
        
        self.log_panel.write(f"\n[bold yellow]Target:[/] {self.selected_item.scope}/{self.selected_item.key}  [bold yellow]New Value:[/] {new_val}")
        
        success, msg, debug_out = self.engine.write_value(self.selected_item.key, self.selected_item.scope, new_val)
        
        if debug_out:
            self.log_panel.write(f"[dim]{debug_out.strip()}[/]")
            
        if success:
            self.log_panel.write(f"[bold green]SUCCESS:[/] {msg}")
            self.query_one("#status", Label).update(f"[green]{msg}[/] -> Wrote {new_val}")
            self.state = self.engine.load_state() 
            self._refresh_list()
        else:
            self.log_panel.write(f"[bold red]FAILED:[/] {msg}")
            self.query_one("#status", Label).update(f"[red]{msg}[/]")
            
        inp = self.query_one(Input)
        inp.value = ""
        inp.disabled = True
        self.query_one(OptionList).focus()

if __name__ == "__main__":
    app = EngineTestApp()
    app.run()
