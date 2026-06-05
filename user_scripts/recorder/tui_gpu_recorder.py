#!/usr/bin/env python3
"""
===============================================================================
DUSKY TUI: GPU SCREEN RECORDER SCHEMA (NATIVE INI)
===============================================================================
"""

from python.frontend.core_types import ConfigItem

# =============================================================================
# 1. CORE APPLICATION ROUTING
# =============================================================================
ENGINE_TYPE = "ini"
TARGET_FILE = "~/.config/gsr-tui/config.conf"
APP_TITLE   = "GPU Screen Recorder"

# =============================================================================
# 2. UI & ENVIRONMENT BEHAVIOR
# =============================================================================
# Set to "auto" so the TUI immediately writes to the INI file on change.
# This eliminates the need for the intermediate "build_scripts.sh" step.
DEFAULT_MODE        = "auto"
THEME_FILE          = "~/.config/matugen/generated/dusky_tui.json"
ENABLE_USER_PRESETS = True
USER_PRESETS_TAB    = "Profiles"

# =============================================================================
# 3. TABS (STRICTLY ONE WORD)
# =============================================================================
TABS = [
    "Capture",
    "Video",
    "Audio",
    "Replay",
    "Profiles"
]

# =============================================================================
# 4. SCHEMA DEFINITION
# =============================================================================
SCHEMA = {

    # -------------------------------------------------------------------------
    # TAB 0: CAPTURE
    # -------------------------------------------------------------------------
    0: [
        ConfigItem(
            label="Source",
            key="window",
            scope="DEFAULT",
            type_="cycle",
            default="screen",
            options=["screen", "portal", "region", "focused"],
            group="Target",
            extended_help="**Capture Target** (`-w`)\n\n`screen` captures the primary monitor. `portal` uses the native Wayland picker. `region` captures a specific coordinate box. `focused` records the currently active window."
        ),
        ConfigItem(
            label="Region",
            key="region",
            scope="DEFAULT",
            type_="string",
            default="",
            group="Target",
            extended_help="**Region String**\n\nSpecify the exact coordinates (e.g., `1280x720+100+50`) when Source is set to `region`. If executing via slurp natively, leave this blank."
        ),
        ConfigItem(
            label="FPS",
            key="fps",
            scope="DEFAULT",
            type_="int",
            default=60,
            min_val=1,
            max_val=360,
            step=5,
            group="Playback",
            extended_help="**Frame Rate** (`-f`)\n\nTarget maximum frames per second for the recording."
        ),
        ConfigItem(
            label="Cursor",
            key="cursor",
            scope="DEFAULT",
            type_="cycle",
            default="yes",
            options=["yes", "no"],
            group="Playback",
            extended_help="**Show Cursor** (`-cursor`)\n\nToggle whether the mouse cursor is visible in the final video output."
        ),
    ],

    # -------------------------------------------------------------------------
    # TAB 1: VIDEO (ENCODING & FORMATS)
    # -------------------------------------------------------------------------
    1: [
        ConfigItem(
            label="Encoder",
            key="encoder",
            scope="DEFAULT",
            type_="cycle",
            default="gpu",
            options=["gpu", "cpu"],
            group="Hardware",
            extended_help="**Encoder Device** (`-encoder`)\n\n`gpu` uses NVENC/VAAPI/AMF for zero-overhead capture. `cpu` forces software encoding (only compatible with H264)."
        ),
        ConfigItem(
            label="Codec",
            key="codec",
            scope="DEFAULT",
            type_="picker",
            default="auto",
            options=[
                "auto", "h264", "hevc", "av1", "vp8", "vp9",
                "hevc_hdr", "av1_hdr", "hevc_10bit", "av1_10bit",
                "h264_vulkan", "hevc_vulkan", "av1_vulkan", 
                "hevc_10bit_vulkan", "av1_10bit_vulkan"
            ],
            hints=[
                "Automatic", "Broadest compatibility", "H.265 (High Efficiency)", "AV1 (Best Compression)", "Open WebM", "Open WebM High",
                "HEVC + HDR", "AV1 + HDR", "HEVC 10-bit", "AV1 10-bit",
                "Fixes Nvidia downclock", "Vulkan HEVC", "Vulkan AV1",
                "Vulkan HEVC 10-bit", "Vulkan AV1 10-bit"
            ],
            group="Format",
            extended_help="**Video Codec** (`-k`)\n\nVulkan codecs are highly recommended for NVIDIA users to prevent the 'cuda p2 state' bug where the GPU is heavily downclocked during gaming."
        ),
        ConfigItem(
            label="Quality",
            key="quality",
            scope="DEFAULT",
            type_="cycle",
            default="very_high",
            options=["ultra", "very_high", "high", "medium", "low"],
            group="Format",
            extended_help="**Quality Preset** (`-q`)\n\nSets the visual fidelity target."
        ),
        ConfigItem(
            label="Bitrate",
            key="bitrate_mode",
            scope="DEFAULT",
            type_="cycle",
            default="auto",
            options=["auto", "qp", "vbr", "cbr"],
            group="Format",
            extended_help="**Bitrate Mode** (`-bm`)\n\nCBR (Constant Bitrate) is strongly recommended when using the Replay Buffer to maintain predictable RAM usage."
        ),
        ConfigItem(
            label="Timing",
            key="frame_mode",
            scope="DEFAULT",
            type_="cycle",
            default="vfr",
            options=["vfr", "cfr", "content"],
            group="Format",
            extended_help="**Frame Rate Mode** (`-fm`)\n\n`content` syncs the video to captured content updates, which is highly recommended for Wayland to minimize idle resource usage."
        ),
        ConfigItem(
            label="Container",
            key="container",
            scope="DEFAULT",
            type_="cycle",
            default="mp4",
            options=["mp4", "mkv", "flv", "webm"],
            group="Output",
            extended_help="**Container Format** (`-c`)\n\nMKV is safer against crashes/corruption. MP4 has broader compatibility."
        ),
        ConfigItem(
            label="Directory",
            key="output_dir",
            scope="DEFAULT",
            type_="string",
            default="~/Videos",
            group="Output",
            extended_help="**Output Directory** (`-o` / `-ro`)\n\nDestination folder for the final saved video files."
        ),
    ],

    # -------------------------------------------------------------------------
    # TAB 2: AUDIO
    # -------------------------------------------------------------------------
    2: [
        ConfigItem(
            label="Input",
            key="audio",
            scope="DEFAULT",
            type_="string",
            default="default_output",
            options=["default_output", "default_input", "default_output|default_input", "none"],
            group="Source",
            extended_help="**Audio Input** (`-a`)\n\nUse `default_output` for desktop audio, or `default_input` for microphone. You can pipe them together (`default_output|default_input`) for multitrack recording, or specify an application natively (e.g., `app:firefox`)."
        ),
        ConfigItem(
            label="Codec",
            key="audio_codec",
            scope="DEFAULT",
            type_="cycle",
            default="opus",
            options=["opus", "aac", "flac"],
            group="Encoding",
            extended_help="**Audio Codec** (`-ac`)\n\nOpus is the default and most efficient codec for MP4/MKV containers."
        ),
        ConfigItem(
            label="Kbps",
            key="audio_bitrate",
            scope="DEFAULT",
            type_="string",
            default="128",
            group="Encoding",
            extended_help="**Audio Bitrate** (`-ab`)\n\nBitrate in kbps. Use `0` for automatic."
        ),
    ],

    # -------------------------------------------------------------------------
    # TAB 3: REPLAY (HYBRID FOLDER IMPLEMENTATION)
    # -------------------------------------------------------------------------
    3: [
        ConfigItem(
            label="Duration",
            key="replay_buffer",
            scope="DEFAULT",
            type_="int",
            default=0,
            min_val=0,
            max_val=86400,
            step=10,
            is_parent=True,
            expanded=True,
            group="Buffer",
            extended_help="**Replay Buffer Size** (`-r`)\n\nRolling buffer duration in seconds. Set to `0` to disable Instant Replay."
        ),
        ConfigItem(
            label="Storage",
            key="replay_storage",
            scope="DEFAULT",
            type_="cycle",
            default="ram",
            options=["ram", "disk"],
            parent_ref="replay_buffer",
            extended_help="**Storage Medium** (`-replay-storage`)\n\nStoring in RAM is faster but consumes system memory. Storing on disk saves RAM but constantly writes to your SSD."
        ),
        ConfigItem(
            label="Restart",
            key="restart_replay",
            scope="DEFAULT",
            type_="cycle",
            default="no",
            options=["yes", "no"],
            parent_ref="replay_buffer",
            extended_help="**Restart On Save** (`-restart-replay-on-save`)\n\nIf 'yes', clears the rolling buffer immediately after a clip is saved."
        ),
        ConfigItem(
            label="Folders",
            key="dark_frame",
            scope="DEFAULT",
            type_="cycle",
            default="no",
            options=["yes", "no"],
            parent_ref="replay_buffer",
            extended_help="**Organize By Date** (`-df`)\n\nPlaces saved replays into date-based subdirectories."
        ),
    ],

    # -------------------------------------------------------------------------
    # TAB 4: PROFILES
    # -------------------------------------------------------------------------
    4: [
        ConfigItem(
            label="Vulkan",
            key="preset_vulkan",
            scope="DEFAULT",
            type_="preset",
            default=None,
            group="System",
            preset_payload={
                "encoder": "gpu",
                "codec": "hevc_vulkan",
                "quality": "very_high",
                "bitrate_mode": "auto",
                "frame_mode": "vfr"
            },
            extended_help="**Vulkan Override**\n\nInstantly configures the settings to use the experimental Vulkan HEVC codec, circumventing the NVIDIA CUDA downclocking bug."
        ),
        ConfigItem(
            label="Reset",
            key="preset_factory_reset",
            scope="DEFAULT",
            type_="preset",
            default=None,
            group="System",
            confirm_message="Are you sure you want to reset all GPU Screen Recorder settings back to default?",
            preset_payload={
                "__ALL_DEFAULTS__": True
            },
            extended_help="**Factory Reset**\n\nReverts all modifications and restores default values across all tabs."
        ),
    ]
}
