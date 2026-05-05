from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd


@dataclass
class HourlyArchiver:
    enabled: bool
    screenshots_root: Path
    tables_root: Path
    save_on_hour_change: bool = True
    last_saved_hour: datetime | None = None

    def _hour_bucket(self, dt_local: datetime) -> datetime:
        return dt_local.replace(minute=0, second=0, microsecond=0)

    def _mkdir_hour(self, root: Path, bucket: datetime) -> Path:
        path = root / f"{bucket:%Y}" / f"{bucket:%m}" / f"{bucket:%d}" / f"{bucket:%H}"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def export_table_csv(self, table_4x24, hours_labels: list[str], radii_labels: list[str], csv_path: Path) -> None:
        df = pd.DataFrame(table_4x24, index=radii_labels, columns=hours_labels)
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(csv_path, sep=";", encoding="utf-8")

    def save_table_csv(self, table_4x24, *, dt_local: datetime, taker_slug: str,
                       hours_labels: list[str], radii_labels: list[str]) -> Path:
        bucket = self._hour_bucket(dt_local)
        tables_dir = self._mkdir_hour(self.tables_root, bucket)

        ts = dt_local.strftime("%Y-%m-%d_%H-%M-%S")
        csv_path = tables_dir / f"{taker_slug}_table_{ts}.csv"
        self.export_table_csv(table_4x24, hours_labels, radii_labels, csv_path)
        return csv_path

    def save_snapshot(self, fig, table_4x24, *, dt_local: datetime, taker_slug: str, mode: int,
                      hours_labels: list[str], radii_labels: list[str], dpi: int = 120) -> tuple[Path, Path]:
        bucket = self._hour_bucket(dt_local)
        shots_dir = self._mkdir_hour(self.screenshots_root, bucket)
        tables_dir = self._mkdir_hour(self.tables_root, bucket)

        ts = dt_local.strftime("%Y-%m-%d_%H-%M-%S")
        png_path = shots_dir / f"{taker_slug}_mode{mode}_{ts}.png"
        csv_path = tables_dir / f"{taker_slug}_table_{ts}.csv"

        fig.savefig(png_path, dpi=dpi, bbox_inches="tight")
        self.export_table_csv(table_4x24, hours_labels, radii_labels, csv_path)
        return png_path, csv_path

    def maybe_save_hourly(self, fig, table_4x24, *, dt_local: datetime, taker_slug: str, mode: int,
                          hours_labels: list[str], radii_labels: list[str], dpi: int = 120) -> tuple[Path, Path] | None:
        if not self.enabled:
            return None
        hour = self._hour_bucket(dt_local)
        if self.last_saved_hour is None:
            # Initialize without saving; next hour change will trigger a save.
            self.last_saved_hour = hour
            return None

        if self.save_on_hour_change and hour != self.last_saved_hour:
            self.last_saved_hour = hour
            return self.save_snapshot(
                fig,
                table_4x24,
                dt_local=dt_local,
                taker_slug=taker_slug,
                mode=mode,
                hours_labels=hours_labels,
                radii_labels=radii_labels,
                dpi=dpi,
            )
        return None
