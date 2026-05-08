#!/usr/bin/env python3
import os
import sys
import re
import subprocess
from urllib.parse import urlparse
from pathlib import Path

# =============================================================================
# ▼ DEPENDENCY BOOTSTRAP ▼
# =============================================================================
# Attempt to load 'rich'. If it fails, automatically elevate to install it via pacman,
# then seamlessly restart the script. This ensures sudo is ONLY called if missing.
try:
    import rich
except ImportError:
    print("\n[!] The 'rich' UI library is missing.")
    print("[*] Automatically installing 'python-rich' via pacman...")
    try:
        # Request sudo privileges only when installation is strictly necessary
        subprocess.run(
            ['sudo', 'pacman', '-S', 'python-rich', '--needed', '--noconfirm'], 
            check=True
        )
        print("[+] Installation successful! Initializing UI...\n")
        
        # Restart the script seamlessly so Python recognizes the newly installed system package
        os.execv(sys.executable, ['python3'] + sys.argv)
    except subprocess.CalledProcessError:
        print("\n[!] Failed to install python-rich automatically. Please install it manually:")
        print("    sudo pacman -S python-rich")
        sys.exit(1)
    except FileNotFoundError:
        print("\n[!] Error: 'pacman' not found. Are you on Arch Linux?")
        sys.exit(1)

# Now that we guarantee 'rich' is installed, we can safely import it.
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.prompt import Prompt, Confirm

# =============================================================================
# ▼ CORE SCRIPT ▼
# =============================================================================

console = Console()

# Semantic mapping
ROLES = {
    "1": {"name": "Main Background", "prop": "background-color", "var": "var(--surface)"},
    "2": {"name": "Sidebar / Navigation Background", "prop": "background-color", "var": "var(--surface_container_low)"},
    "3": {"name": "Panel/Card Background", "prop": "background-color", "var": "var(--surface_container)"},
    "4": {"name": "Input Field / Search Bar", "prop": "background-color", "var": "var(--surface_container_highest)"},
    "5": {"name": "Primary Text (Headings/Body)", "prop": "color", "var": "var(--on_surface)"},
    "6": {"name": "Muted Text (Subtitles/Dates)", "prop": "color", "var": "var(--on_surface_variant)"},
    "7": {"name": "Borders & Dividers", "prop": "border-color", "var": "var(--outline)"},
    "8": {"name": "Accent Element (Buttons/Links)", "prop": "background-color", "var": "var(--primary)"},
    "9": {"name": "Text on Accent Button", "prop": "color", "var": "var(--on_primary)"},
    "10": {"name": "Error/Warning Alert", "prop": "background-color", "var": "var(--error)"}
}

# High-contrast palette for visual debugging in the Stylus preview
DEBUG_COLORS = [
    "red", "teal", "dodgerblue", "blueviolet", "lime", 
    "magenta", "yellow", "cyan", "darkorange", "hotpink"
]

def print_menu() -> None:
    """Uses Rich to print a beautiful, styled table instead of plain text."""
    table = Table(show_header=True, header_style="bold magenta", border_style="dim")
    table.add_column("Key", style="cyan", justify="center")
    table.add_column("Role / Element", style="white")
    
    for key, data in ROLES.items():
        table.add_row(f"[{key}]", data['name'])
        
    console.print(table)

def extract_domain(raw_input: str) -> str:
    raw_input = raw_input.strip()
    if not raw_input.startswith(('http://', 'https://')):
        raw_input = 'https://' + raw_input
        
    parsed = urlparse(raw_input)
    domain = parsed.netloc.split(':')[0]
    domain = re.sub(r'[^\w.-]', '', domain)
    
    if domain.startswith('www.'):
        domain = domain[4:]
        
    return domain

def generate_css(domain: str, rules: list[dict[str, str]], mode: str = "production") -> str:
    css_parts = [f'@-moz-document domain("{domain}") {{\n\n']
    
    for idx, rule in enumerate(rules):
        role_data = ROLES[rule['role']]
        css_value = DEBUG_COLORS[idx % len(DEBUG_COLORS)] if mode == "preview" else role_data['var']
        
        css_parts.append(f"    /* {role_data['name']} */\n")
        css_parts.append(f"    {rule['selector']} {{\n")
        css_parts.append(f"        {role_data['prop']}: {css_value} !important;\n")
        css_parts.append("    }\n\n")
        
    css_parts.append("}\n")
    return "".join(css_parts)

def copy_to_clipboard(text: str) -> None:
    """Attempts to copy text to the clipboard targeting Wayland, X11, or macOS."""
    try:
        # Wayland targeting (Hyprland)
        subprocess.run(['wl-copy'], input=text, text=True, check=True, capture_output=True)
        console.print("[bold green]📋 Hot Preview automatically copied to clipboard! (via wl-copy)[/]")
        return
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass

    try:
        # X11 Fallback
        subprocess.run(['xclip', '-selection', 'clipboard'], input=text, text=True, check=True, capture_output=True)
        console.print("[bold green]📋 Hot Preview automatically copied to clipboard! (via xclip)[/]")
        return
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass

    console.print("[bold yellow]⚠️ Could not automatically copy. Please install `wl-clipboard` or `xclip`.[/]")

def main() -> None:
    console.clear()
    console.print(Panel.fit("=== Dusky Dynamic Theme Builder ===", style="bold magenta"))
    
    raw_domain = Prompt.ask("[bold cyan]Enter the website domain or paste the URL[/] [dim](e.g., https://x.com/)[/]").strip()
    domain = extract_domain(raw_domain)
    
    if not domain:
        console.print("[bold red]Valid domain is required. Exiting.[/]")
        return
        
    console.print(f"[*] Targeting domain: [bold green]{domain}[/]\n")

    collected_rules: list[dict[str, str]] = []
    
    while True:
        console.print("[dim]" + "━"*40 + "[/]")
        selector = Prompt.ask("[bold cyan]Paste the CSS selector[/] [dim](or press Enter to finish)[/]").strip()
        
        if not selector:
            break
            
        print_menu()
        role_choice = Prompt.ask("[bold cyan]Select the role[/]", choices=list(ROLES.keys()))
        
        if role_choice in ROLES:
            collected_rules.append({
                "selector": selector,
                "role": role_choice
            })
            console.print(f"[bold green]✔ Added rule for {ROLES[role_choice]['name']}[/]")
        else:
            console.print("[bold red]✖ Invalid choice. Rule skipped.[/]")

    if not collected_rules:
        console.print("\n[bold yellow]No rules collected. Exiting.[/]")
        return

    production_css = generate_css(domain, collected_rules, mode="production")
    preview_css = generate_css(domain, collected_rules, mode="preview")

    # Render Preview
    console.print("\n")
    preview_panel = Panel(
        f"[bold white]{preview_css}[/]", 
        title="[bold yellow]🎨 HOT PREVIEW TEMPLATE (For Stylus Debugging)[/]", 
        border_style="yellow",
        subtitle="[dim]Your targeted elements will light up in distinct colors[/]"
    )
    console.print(preview_panel)
    
    # Auto-Copy to Clipboard
    copy_to_clipboard(preview_css)

    # Ask to save Production Template
    console.print("\n[dim]Your Managing/Production Template cleanly uses dynamic var(--...) variables.[/]")
    save = Confirm.ask(f"Do you want to automatically save the Production template to [bold]~/.cache/dusky_themer/{domain}.css[/]?")

    if not save:
        console.print("\n[bold cyan]Here is your Production Code to copy manually:[/]\n")
        console.print(production_css)
    else:
        cache_dir = Path.home() / ".cache" / "dusky_themer"
        cache_dir.mkdir(parents=True, exist_ok=True)
        file_path = cache_dir / f"{domain}.css"
        
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(production_css)
            console.print(f"\n[bold green]✔ Success! Production template saved to:[/] {file_path}")
            console.print("[bold cyan]You can now open your Dusky TUI Manager to enable and deploy it.[/]")
        except OSError as e:
            console.print(f"\n[bold red]✖ Error saving file: {e}[/]")
            console.print("[bold cyan]Here is your Production Code instead:[/]\n")
            console.print(production_css)

if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        # We handle this gracefully using standard prints in case rich isn't loaded properly during an abrupt exit
        print("\n\nExiting Theme Builder. Goodbye!")
        sys.exit(0)
