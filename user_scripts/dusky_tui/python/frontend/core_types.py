#!/usr/bin/env python3
from dataclasses import dataclass, field
from typing import Any, Literal
from abc import ABC, abstractmethod

# Preserving your exact Python 3.12+ type alias syntax from the original ui.py
type ConfigType = Literal["bool", "int", "float", "string", "cycle", "action", "menu", "picker", "color"]

@dataclass(kw_only=True)
class ConfigItem:
    label: str
    key: str
    scope: str = "DEFAULT"
    type_: ConfigType
    default: Any
    options: list[str] = field(default_factory=list)
    hints: list[str] = field(default_factory=list)
    min_val: float | None = None
    max_val: float | None = None
    step: float | None = None
    value: Any = None

    def __post_init__(self) -> None:
        if self.value is None:
            self.value = self.default

class BaseEngine(ABC):
    """Abstract Base Class enforcing the strict mutator contract for the IoC architecture."""
    
    @property
    @abstractmethod
    def target_path(self) -> str:
        """
        Returns the primary target file path (e.g., ~/.config/hypr/hyprland.conf).
        Used by the UI to render the FileLink component and manage edit events.
        """
        pass

    @abstractmethod
    def load_state(self) -> dict[str, Any]:
        """
        Loads and returns a flattened dictionary of the current parsed state.
        Keys should follow the 'scope/key' or 'key' convention to map to ConfigItems.
        """
        pass

    @abstractmethod
    def write_value(self, target_key: str, target_scope: str, new_value: str) -> tuple[bool, str, str]:
        """
        Commits a value change to the configuration backend.
        
        Args:
            target_key: The configuration key to mutate.
            target_scope: The structural scope/category of the key.
            new_value: The stringified new value to inject.
            
        Returns:
            tuple[bool, str, str]: (Success boolean, Status/Error message, Debug/Telemetry output)
        """
        pass
