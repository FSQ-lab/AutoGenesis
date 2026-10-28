"""Secret-free configuration tools; input signatures are the legacy contract."""

from autogenesis_agent_contract import public_view
from typing import Optional



def register_config_tools(mcp, config_manager):
    @mcp.tool()
    def reload_config() -> dict:
        """
        Manually reload the configuration from file.

        This tool forces an immediate reload of the appium configuration file.
        Useful when you want to apply configuration changes immediately without
        waiting for the automatic file watcher to detect changes.

        Returns:
            dict: Status of the reload operation with configuration details
        """
        success = config_manager.reload_config()
        return {
            "success": success,
            "message": "Configuration reloaded successfully" if success else "Configuration reload failed",
            "platforms": sorted(config_manager.get_config()),
        }

    @mcp.tool()
    def get_current_config(platform: Optional[str] = None) -> dict:
        """
        Get the current configuration.

        Args:
            platform: Optional platform name (ios/android/mac). If not specified, returns all configs.

        Returns:
            dict: Current configuration for the specified platform or all platforms
        """
        if platform is not None:
            if platform not in {"ios", "android", "mac"}:
                return {"success": False, "message": "Unknown platform"}
            config = config_manager.get_platform_config(platform)
            if config is None:
                return {"success": False, "message": "Platform is not configured"}
            return {"success": True, "platform": platform, "config": public_view(config)}
        config = config_manager.get_config()
        return {"success": True, "platforms": sorted(config), "config": public_view(config)}
