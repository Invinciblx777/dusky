mod apply;
mod cache;
mod color;
mod config;
mod favorites;
mod scanner;
mod theme;
mod ui;

use config::Config;
use std::env;
use ui::WallpaperSelectorApp;

fn print_help() {
    println!("Dusky Wallpaper Selector (Rust/Iced)");
    println!("Usage: wallpaper_selector [OPTIONS]\n");
    println!("Options:");
    println!("  --next-fav       Cycle to next favorite wallpaper and exit");
    println!("  --prev-fav       Cycle to previous favorite wallpaper and exit");
    println!("  --random         Select and apply a random wallpaper and exit");
    println!("  --build-cache    Generate only missing or outdated thumbnails and exit");
    println!("  --update-cache   Alias for --build-cache");
    println!("  --rebuild-cache  Force-regenerate every thumbnail and exit");
    println!("  --version, -v, -V Show version information and exit");
    println!("  --help, -h       Show this help message");
}

fn cycle_favorite(direction_next: bool, config: &Config) -> bool {
    let favorites_set = match favorites::load_favorites(&config.fav_file) {
        Ok(favorites) => favorites,
        Err(error) => {
            eprintln!("Could not read favorites: {error}");
            return false;
        }
    };
    let active_id = favorites::read_active_wallpaper(&config.theme_dir);

    let all = match scanner::scan_wallpapers(
        &config.wallpaper_dir,
        &config.thumb_dir,
        &favorites_set,
        active_id.as_deref(),
    ) {
        Ok(items) => items,
        Err(error) => {
            eprintln!("{error}");
            return false;
        }
    };

    let fav_items: Vec<_> = all.into_iter().filter(|w| w.is_favorite).collect();

    if fav_items.is_empty() {
        println!("No favorites found in {}", config.fav_file.display());
        let _ = std::process::Command::new("notify-send")
            .args([
                "-a",
                "dusky-wallpaper",
                "No Favorites",
                "No favorite wallpapers found.",
            ])
            .spawn();
        return false;
    }

    let current_index = fav_items.iter().position(|item| item.is_active);

    let next_index = if direction_next {
        current_index.map_or(0, |index| (index + 1) % fav_items.len())
    } else {
        current_index.map_or(fav_items.len() - 1, |index| {
            (index + fav_items.len() - 1) % fav_items.len()
        })
    };

    let target = &fav_items[next_index];
    apply::apply_wallpaper(&target.path, &config.theme_ctl, true)
        .map_err(|e| eprintln!("Failed to apply wallpaper: {e}"))
        .is_ok()
}

fn apply_random(config: &Config) -> bool {
    let favorites_set = match favorites::load_favorites(&config.fav_file) {
        Ok(favorites) => favorites,
        Err(error) => {
            eprintln!("Could not read favorites: {error}");
            return false;
        }
    };
    let all = match scanner::scan_wallpapers(
        &config.wallpaper_dir,
        &config.thumb_dir,
        &favorites_set,
        None,
    ) {
        Ok(items) => items,
        Err(error) => {
            eprintln!("{error}");
            return false;
        }
    };

    if all.is_empty() {
        eprintln!("No wallpapers found in {}", config.wallpaper_dir.display());
        return false;
    }

    let choice = &all[fastrand::usize(..all.len())];

    apply::apply_wallpaper(&choice.path, &config.theme_ctl, true)
        .map_err(|e| eprintln!("Failed to apply wallpaper: {e}"))
        .is_ok()
}

fn build_cache(config: &Config, force: bool) -> bool {
    println!("Scanning {}...", config.wallpaper_dir.display());
    let favs = match favorites::load_favorites(&config.fav_file) {
        Ok(favorites) => favorites,
        Err(error) => {
            eprintln!("Could not read favorites: {error}");
            return false;
        }
    };
    let all = match scanner::scan_wallpapers(&config.wallpaper_dir, &config.thumb_dir, &favs, None)
    {
        Ok(items) => items,
        Err(error) => {
            eprintln!("{error}");
            return false;
        }
    };
    println!("Checking {} wallpapers...", all.len());
    let stats = cache::batch_generate_thumbs(&all, force);
    println!(
        "Cache result: generated={}, cached={}, failed={}",
        stats.generated, stats.cached, stats.failed
    );
    if stats.failed > 0 {
        eprintln!(
            "Failed to generate {} of {} thumbnails",
            stats.failed,
            all.len()
        );
        false
    } else {
        match cache::prune_thumbnails(&all, &config.thumb_dir) {
            Ok(removed) if removed > 0 => println!("Removed {removed} obsolete thumbnails"),
            Err(error) => {
                eprintln!("Could not prune obsolete thumbnails: {error}");
                return false;
            }
            _ => {}
        }
        println!("Indexing wallpaper colors...");
        let (colors, _, saved) = color::ensure_color_cache(&all, &config.colors_file);
        if let Err(error) = saved {
            eprintln!("Could not save wallpaper color index: {error}");
            return false;
        }
        if colors.len() != all.len() {
            eprintln!(
                "Could not index colors for {} wallpapers",
                all.len() - colors.len()
            );
            return false;
        }
        println!("Color index ready: {} wallpapers indexed", colors.len());
        println!("Cache generation complete!");
        true
    }
}

struct SingleInstanceGuard {
    _lock: std::fs::File,
}

impl SingleInstanceGuard {
    pub fn acquire() -> Result<Option<Self>, String> {
        let runtime_dir = std::env::var_os("XDG_RUNTIME_DIR")
            .map(std::path::PathBuf::from)
            .ok_or("XDG_RUNTIME_DIR is not set")?;
        let path = runtime_dir.join("dusky_wallpaper_selector.lock");
        let file = std::fs::File::create(&path)
            .map_err(|e| format!("Could not open {}: {e}", path.display()))?;
        match file.try_lock() {
            Ok(()) => Ok(Some(Self { _lock: file })),
            Err(std::fs::TryLockError::WouldBlock) => Ok(None),
            Err(error) => Err(format!("Could not lock {}: {error}", path.display())),
        }
    }
}

fn hyprctl_json(command: &str) -> Option<serde_json::Value> {
    let output = std::process::Command::new("hyprctl")
        .args([command, "-j"])
        .output()
        .ok()?;
    output
        .status
        .success()
        .then(|| serde_json::from_slice(&output.stdout).ok())?
}

fn reveal_existing_window() -> Result<(), String> {
    let workspace = hyprctl_json("activeworkspace")
        .and_then(|value| value["name"].as_str().map(str::to_owned))
        .ok_or("Could not determine the current Hyprland workspace")?;
    let clients = hyprctl_json("clients").ok_or("Could not query Hyprland windows")?;
    let window = clients
        .as_array()
        .and_then(|clients| {
            clients
                .iter()
                .find(|client| client["class"].as_str() == Some("dusky-wallpaper-selector-rust"))
        })
        .ok_or("Could not find the running wallpaper selector window")?;
    let address = window["address"]
        .as_str()
        .ok_or("Hyprland did not report a window address")?;
    let window_address = format!("address:{address}");

    if window["workspace"]["name"].as_str() != Some(workspace.as_str()) {
        let expression = format!(
            "hl.dsp.window.move({{ window = {}, workspace = {}, follow = false }})",
            serde_json::to_string(&window_address).map_err(|e| e.to_string())?,
            serde_json::to_string(&workspace).map_err(|e| e.to_string())?,
        );
        let result = std::process::Command::new("hyprctl")
            .args(["dispatch", &expression])
            .output()
            .map_err(|e| format!("Could not move the selector: {e}"))?;
        if !result.status.success() {
            return Err(String::from_utf8_lossy(&result.stderr).trim().to_owned());
        }
    }

    let expression = format!(
        "hl.dsp.focus({{ window = {} }})",
        serde_json::to_string(&window_address).map_err(|e| e.to_string())?,
    );
    let result = std::process::Command::new("hyprctl")
        .args(["dispatch", &expression])
        .output()
        .map_err(|e| format!("Could not focus the selector: {e}"))?;
    if !result.status.success() {
        return Err(String::from_utf8_lossy(&result.stderr).trim().to_owned());
    }
    Ok(())
}

fn read_card_vendor_driver(card_name: &str) -> Option<(String, String)> {
    let sys_base = format!("/sys/class/drm/{card_name}/device");
    let vendor_path = format!("{sys_base}/vendor");
    let vendor = std::fs::read_to_string(&vendor_path)
        .ok()?
        .trim()
        .to_ascii_lowercase();

    let driver = std::fs::read_link(format!("{sys_base}/driver"))
        .ok()
        .and_then(|p| p.file_name().map(|f| f.to_string_lossy().to_string()))
        .unwrap_or_default()
        .to_ascii_lowercase();

    Some((vendor, driver))
}

fn detect_primary_gpu_vendor() -> Option<(String, String)> {
    // 1. Check AQ_DRM_DEVICES (set by Hyprland via gpu.lua, ordered with primary card first)
    if let Ok(aq_devices) = env::var("AQ_DRM_DEVICES") {
        if let Some(first) = aq_devices.split(':').next() {
            let p = std::path::Path::new(first.trim());
            if let Ok(real) = std::fs::canonicalize(p) {
                if let Some(name) = real.file_name().and_then(|s| s.to_str()) {
                    if name.starts_with("card") {
                        if let Some(pair) = read_card_vendor_driver(name) {
                            return Some(pair);
                        }
                    }
                }
            }
        }
    }

    // 2. Scan /sys/class/drm/card* directly for the boot_vga device (KMS primary display)
    let mut first_card: Option<String> = None;
    if let Ok(entries) = std::fs::read_dir("/sys/class/drm") {
        let mut card_names: Vec<String> = entries
            .filter_map(|e| e.ok())
            .map(|e| e.file_name().to_string_lossy().to_string())
            .filter(|name| name.starts_with("card") && !name.contains('-'))
            .collect();
        card_names.sort();

        for name in &card_names {
            if first_card.is_none() {
                first_card = Some(name.clone());
            }
            let boot_vga_path = format!("/sys/class/drm/{name}/device/boot_vga");
            if let Ok(content) = std::fs::read_to_string(&boot_vga_path) {
                if content.trim() == "1" {
                    if let Some(pair) = read_card_vendor_driver(name) {
                        return Some(pair);
                    }
                }
            }
        }
    }

    if let Some(name) = first_card {
        return read_card_vendor_driver(&name);
    }

    None
}

fn optimize_gpu_environment() {
    // 1. If user explicitly provided driver files, don't override
    if env::var_os("VK_DRIVER_FILES").is_some() {
        return;
    }

    let Some((vendor, driver)) = detect_primary_gpu_vendor() else {
        return;
    };

    // 2. Determine matching Vulkan ICD candidates based on the actual primary GPU
    let (candidates, power_pref): (&[&str], &str) = match vendor.as_str() {
        // Intel (Iris Xe, UHD, Arc)
        "0x8086" => (
            &[
                "/usr/share/vulkan/icd.d/intel_icd.x86_64.json",
                "/usr/share/vulkan/icd.d/intel_icd.json",
                "/usr/share/vulkan/icd.d/intel_hasvk_icd.x86_64.json",
                "/usr/share/vulkan/icd.d/intel_hasvk_icd.json",
            ],
            "low",
        ),
        // AMD (Radeon, Ryzen iGPU, Radeon dGPU)
        "0x1002" => (
            &[
                "/usr/share/vulkan/icd.d/radeon_icd.x86_64.json",
                "/usr/share/vulkan/icd.d/radeon_icd.json",
            ],
            "low",
        ),
        // NVIDIA (Desktop discrete GPU or single-GPU system)
        "0x10de" => {
            if driver == "nouveau" {
                (
                    &[
                        "/usr/share/vulkan/icd.d/nouveau_icd.x86_64.json",
                        "/usr/share/vulkan/icd.d/nouveau_icd.json",
                    ],
                    "high",
                )
            } else {
                (
                    &[
                        "/usr/share/vulkan/icd.d/nvidia_icd.x86_64.json",
                        "/usr/share/vulkan/icd.d/nvidia_icd.json",
                    ],
                    "high",
                )
            }
        }
        // Generic / Virtual Machines (QEMU, VirtIO, VMware, etc.)
        _ => return,
    };

    // 3. Set power preference so wgpu aligns with primary GPU
    if env::var_os("WGPU_POWER_PREF").is_none() {
        unsafe { env::set_var("WGPU_POWER_PREF", power_pref) };
    }

    // 4. Pin Vulkan to the primary GPU's driver to prevent waking up secondary sleeping GPUs
    for candidate in candidates {
        if std::path::Path::new(candidate).exists() {
            unsafe {
                env::set_var("VK_DRIVER_FILES", candidate);
            }
            break;
        }
    }
}

fn main() -> iced::Result {
    let config = Config::load();
    let args: Vec<String> = env::args().collect();

    if args.len() > 2 {
        eprintln!("Expected at most one option; use --help for usage");
        std::process::exit(2);
    }
    let option = args.get(1).map(String::as_str);

    if matches!(option, Some("--help" | "-h")) {
        print_help();
        return Ok(());
    }

    if matches!(option, Some("--version" | "-v" | "-V")) {
        println!("wallpaper_selector {}", env!("CARGO_PKG_VERSION"));
        return Ok(());
    }

    if option == Some("--next-fav") {
        if !cycle_favorite(true, &config) {
            std::process::exit(1);
        }
        return Ok(());
    }

    if option == Some("--prev-fav") {
        if !cycle_favorite(false, &config) {
            std::process::exit(1);
        }
        return Ok(());
    }

    if option == Some("--random") {
        if !apply_random(&config) {
            std::process::exit(1);
        }
        return Ok(());
    }

    if matches!(
        option,
        Some("--build-cache" | "--update-cache" | "--rebuild-cache")
    ) {
        if !build_cache(&config, option == Some("--rebuild-cache")) {
            std::process::exit(1);
        }
        return Ok(());
    }
    if let Some(unknown) = option {
        eprintln!("Unknown option: {unknown}; use --help for usage");
        std::process::exit(2);
    }

    // Single-instance guard prevents duplicate instances and CPU thrashing
    let _guard = match SingleInstanceGuard::acquire() {
        Ok(Some(g)) => g,
        Ok(None) => {
            if let Err(error) = reveal_existing_window() {
                eprintln!("Could not show the running wallpaper selector: {error}");
            }
            return Ok(());
        }
        Err(error) => {
            eprintln!("Could not start wallpaper selector: {error}");
            std::process::exit(1);
        }
    };

    optimize_gpu_environment();
    // Launch GUI in transparent overlay mode (matching skwd-wall overlay)
    let window_settings = iced::window::Settings {
        decorations: false,
        transparent: true,
        platform_specific: iced::window::settings::PlatformSpecific {
            application_id: "dusky-wallpaper-selector-rust".to_string(),
            ..Default::default()
        },
        ..Default::default()
    };

    let app_config = config.clone();
    iced::application(
        move || WallpaperSelectorApp::new(app_config.clone()),
        WallpaperSelectorApp::update,
        WallpaperSelectorApp::view,
    )
    .window(window_settings)
    .subscription(WallpaperSelectorApp::subscription)
    .theme(theme)
    .style(style)
    .title(title)
    .run()
}

fn style(_: &WallpaperSelectorApp, theme: &iced::Theme) -> iced::theme::Style {
    iced::theme::Style {
        background_color: iced::Color::TRANSPARENT,
        text_color: theme.palette().text,
    }
}

fn title(_: &WallpaperSelectorApp) -> String {
    "Wallpaper Selector".to_string()
}

fn theme(_: &WallpaperSelectorApp) -> iced::Theme {
    iced::Theme::Dark
}
