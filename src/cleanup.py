from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone, timedelta
import logging


class FileCleanupManager:
    """Manage cleanup of raw GLM files and background cache files."""

    def __init__(self, logger: logging.Logger | None = None):
        self.logger = logger or logging.getLogger(__name__)

    def cleanup_raw_files(self, root: Path, older_than_hours: int) -> int:
        """Delete .nc files older than N hours from root directory.

        Args:
            root: Root directory to search for .nc files
            older_than_hours: Delete files older than this many hours

        Returns:
            Number of files deleted
        """
        if not root.exists():
            return 0

        deleted = 0
        cutoff = datetime.now(timezone.utc) - timedelta(hours=older_than_hours)

        for nc_file in root.rglob("*.nc"):
            try:
                mtime = datetime.fromtimestamp(nc_file.stat().st_mtime, tz=timezone.utc)
                if mtime < cutoff:
                    nc_file.unlink()
                    deleted += 1
                    self.logger.info(f"Deleted raw file: {nc_file.name}")
            except Exception as e:
                self.logger.warning(f"Failed to delete {nc_file.name}: {e}")

        return deleted

    def cleanup_background_cache(self, cache_dir: Path, older_than_days: int) -> int:
        """Delete .nc files older than N days from background cache directory.

        Args:
            cache_dir: Background cache directory to clean
            older_than_days: Delete files older than this many days

        Returns:
            Number of files deleted
        """
        if not cache_dir.exists():
            return 0

        deleted = 0
        cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)

        for nc_file in cache_dir.rglob("*.nc"):
            try:
                mtime = datetime.fromtimestamp(nc_file.stat().st_mtime, tz=timezone.utc)
                if mtime < cutoff:
                    nc_file.unlink()
                    deleted += 1
                    self.logger.info(f"Deleted background cache: {nc_file.name}")
            except Exception as e:
                self.logger.warning(f"Failed to delete {nc_file.name}: {e}")

        return deleted
