-- -------------------------------------------------------------------------------------------------
-- APPEARANCE, DECORATION & RENDERING
-- -------------------------------------------------------------------------------------------------

hl.config({
    -- ==========================================
    -- GENERAL (Borders, Gaps, Colors)
    -- ==========================================
    general = {
        border_size = 1, -- Size of the border around windows
        gaps_in = 4, -- Gaps between windows
        gaps_out = 8, -- Gaps between windows and monitor edges
        float_gaps = 0, -- Gaps for floating windows (-1 means default)
        gaps_workspaces = 0, -- Gaps between workspaces (stacks with gaps_out)

        ["col.inactive_border"] = inverse_on_surface, -- Border color for inactive windows
        ["col.active_border"] = primary, -- Border color for the active window
        ["col.nogroup_border"] = inverse_on_surface, -- Inactive border color for window that cannot be added to a group
        ["col.nogroup_border_active"] = secondary, -- Active border color for window that cannot be added to a group

        resize_on_border = true, -- Enables resizing windows by clicking and dragging on borders and gaps
        extend_border_grab_area = 15, -- Extends click/drag area around the border (needs resize_on_border)
        hover_icon_on_border = true, -- Shows cursor icon when hovering over borders (needs resize_on_border)
        allow_tearing = true, -- Master switch for allowing tearing to occur
        resize_corner = 0 -- Forces floating windows to use specific corner when resized (1-4, 0 to disable)
    },

    -- ==========================================
    -- DECORATION (Rounding, Blur, Shadows)
    -- ==========================================
    decoration = {
        rounding = 10, -- Rounded corners' radius (in layout px)
        rounding_power = 2.5, -- Curve used for rounding (2.0 is circle, 4.0 squircle, 1.0 triangular)
        active_opacity = 0.85, -- Opacity of active windows [0.0 - 1.0]
        inactive_opacity = 0.85, -- Opacity of inactive windows [0.0 - 1.0]
        fullscreen_opacity = 1.0, -- Opacity of fullscreen windows [0.0 - 1.0]
        dim_modal = true, -- Enables dimming of parents of modal windows
        dim_inactive = true, -- Enables dimming of inactive windows
        dim_strength = 0.3, -- How much inactive windows should be dimmed [0.0 - 1.0]
        dim_special = 0.8, -- How much to dim screen when special workspace is open [0.0 - 1.0]
        dim_around = 0.4, -- How much the dim_around window rule should dim by [0.0 - 1.0]
        screen_shader = "", -- Path to custom shader applied at the end of rendering
        border_part_of_window = true, -- Whether the window border should be a part of the window

        blur = {
            enabled = true, -- Enable kawase window background blur
            size = 10, -- Blur size (distance)
            passes = 2, -- Amount of passes to perform
            ignore_opacity = true, -- Make the blur layer ignore the opacity of the window
            new_optimizations = true, -- Enable further optimizations (massively improves performance)
            xray = false, -- Floating windows ignore tiled windows in blur (reduces overhead)
            noise = 0.0117, -- How much noise to apply [0.0 - 1.0]
            contrast = 0.8916, -- Contrast modulation for blur [0.0 - 2.0]
            brightness = 0.8172, -- Brightness modulation for blur [0.0 - 2.0]
            vibrancy = 0.1696, -- Increase saturation of blurred colors [0.0 - 1.0]
            vibrancy_darkness = 0.0, -- How strong vibrancy effect is on dark areas [0.0 - 1.0]
            special = false, -- Whether to blur behind special workspace (expensive)
            popups = false, -- Whether to blur popups (e.g. right-click menus)
            popups_ignorealpha = 0.2, -- If pixel opacity is below this, will not blur popups [0.0 - 1.0]
            input_methods = false, -- Whether to blur input methods (e.g. fcitx5)
            input_methods_ignorealpha = 0.2 -- If pixel opacity is below this, will not blur input methods [0.0 - 1.0]
        },

        shadow = {
            enabled = true, -- Enable drop shadows on windows
            range = 10, -- Shadow range ("size") in layout px
            render_power = 1, -- Falloff power (more power = faster falloff) [1 - 4]
            sharp = false, -- Make shadows sharp, akin to infinite render power
            color = "rgba(1a1a1aee)", -- Shadow's color. Alpha dictates opacity
            offset = {0, 0}, -- Shadow's rendering offset
            scale = 1.0 -- Shadow's scale [0.0 - 1.0]
        },

        glow = {
            enabled = false, -- Enable inner glow on windows
            range = 10, -- Glow range ("size") in layout px
            render_power = 3, -- Falloff power [1 - 4]
            color = primary_container -- Glow's color. Alpha dictates opacity
        }
    },

    -- ==========================================
    -- ANIMATIONS
    -- ==========================================
    animations = {
        workspace_wraparound = false -- Directional workspace animations animate as if first/last are adjacent
    },

    -- ==========================================
    -- GROUP UI (Colors & Groupbars)
    -- ==========================================
    group = {
        ["col.border_active"] = primary, -- Active group border color
        ["col.border_inactive"] = inverse_on_surface, -- Inactive group border color
        ["col.border_locked_active"] = tertiary, -- Active locked group border color
        ["col.border_locked_inactive"] = tertiary_container, -- Inactive locked group border color

        groupbar = {
            enabled = true, -- Enables groupbars
            font_family = "", -- Font for groupbar titles (falls back to misc.font_family)
            font_size = 8, -- Font size of title
            font_weight_active = "normal", -- Font weight of active title
            font_weight_inactive = "normal", -- Font weight of inactive title
            gradients = false, -- Enables gradients
            height = 14, -- Height of groupbar
            indicator_gap = 0, -- Gap between indicator and title
            indicator_height = 3, -- Height of indicator
            stacked = false, -- Render as vertical stack
            priority = 3, -- Decoration priority
            render_titles = true, -- Render titles in decoration
            text_offset = 0, -- Vertical position adjust for titles
            text_padding = 0, -- Horizontal padding for titles
            rounding = 1, -- Round indicator
            rounding_power = 2.0, -- Curve used for rounding indicator
            gradient_rounding = 2, -- Round gradients
            gradient_rounding_power = 2.0, -- Curve used for rounding gradients
            round_only_edges = true, -- Round only indicator edges
            gradient_round_only_edges = true, -- Round only gradient edges
            text_color = on_surface, -- Title color
            ["col.active"] = primary, -- Active background color
            ["col.inactive"] = inverse_on_surface, -- Inactive background color
            ["col.locked_active"] = tertiary, -- Active locked background color
            ["col.locked_inactive"] = tertiary_container, -- Inactive locked background color
            gaps_in = 2, -- Gap between gradients
            gaps_out = 2, -- Gap between gradients and window
            keep_upper_gap = true, -- Add/remove upper gap
            blur = false -- Apply blur to indicators and gradients
        }
    },

    -- ==========================================
    -- MISC VISUALS & UI
    -- ==========================================
    misc = {
        disable_hyprland_logo = true, -- Disables random anime girl background
        disable_splash_rendering = true, -- Disables splash rendering
        font_family = "Sans", -- Default font for debug/error text
        splash_font_family = "", -- Font for splash text
        force_default_wallpaper = 1, -- Enforce default wallpapers (-1 random, 0/1 disables anime)
        animate_manual_resizes = false, -- Animate manual window resizes/moves
        animate_mouse_windowdragging = false, -- Animate windows being dragged by mouse
        background_color = background, -- Custom background color
        render_unfocused_fps = 5, -- Max FPS limit for unfocused background windows
        enable_anr_dialog = true -- Enable "App Not Responding" dialog
    },

    -- ==========================================
    -- RENDER PIPELINE & XWAYLAND SCALING
    -- ==========================================
    xwayland = {
        use_nearest_neighbor = true, -- Nearest neighbor filtering (pixelated vs blurry)
        force_zero_scaling = false -- Force scale of 1 on xwayland windows on scaled displays
    },

    opengl = {
        nvidia_anti_flicker = true -- Reduces flickering on nvidia (ignored on others)
    },

    render = {
        direct_scanout = 0, -- Attempt to reduce lag for single fullscreen app [0=off, 1=on, 2=auto]
        expand_undersized_textures = true, -- Expand undersized textures vs stretching entire texture
        xp_mode = false, -- Disables back buffer and bottom layer rendering
        ctm_animation = 2, -- Fade animation for CTM changes (2=auto disables on Nvidia)
        use_shader_blur_blend = false -- Blurred bg blending
    },

    -- ==========================================
    -- DEBUG VISUALS
    -- ==========================================
    debug = {
        overlay = false, -- Print debug performance overlay
        damage_blink = false, -- Flash areas updated with damage tracking
        colored_stdout_logs = true -- Colors in stdout logs
    }
})

-- -------------------------------------------------------------------------------------------------
--  ANIMATIONS
-- -------------------------------------------------------------------------------------------------

-- Sourcing active animations
require("source.animations.active.active")
