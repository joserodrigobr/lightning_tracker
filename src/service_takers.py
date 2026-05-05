from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd


@dataclass(frozen=True)
class ServiceTaker:
    idx: int
    municipio: str
    unidade: str
    latitude: float
    longitude: float


def load_service_takers(csv_path: Path) -> list[ServiceTaker]:
    df = pd.read_csv(
        csv_path,
        sep=";",
        decimal=",",
        encoding="utf-8",
        dtype=str,
        keep_default_na=False,
    )

    # Drop completely empty trailing rows
    df = df[df["N"].astype(str).str.strip().ne("")].copy()

    def to_int(v: str) -> int:
        return int(str(v).strip())

    def to_float(v: str) -> float:
        return float(str(v).strip().replace(",", "."))

    takers: list[ServiceTaker] = []
    for _, row in df.iterrows():
        takers.append(
            ServiceTaker(
                idx=to_int(row["N"]),
                municipio=str(row.get("MUNICIPIO", "")).strip(),
                unidade=str(row.get("UNIDADE TOMADORA DE SERVIÇO", "")).strip(),
                latitude=to_float(row.get("Latitude", "")),
                longitude=to_float(row.get("Longitude", "")),
            )
        )
    return takers


def get_taker_by_number(takers: list[ServiceTaker], number: int) -> ServiceTaker:
    for t in takers:
        if t.idx == number:
            return t
    raise ValueError(f"Tomador {number} não encontrado")
