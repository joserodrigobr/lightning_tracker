from __future__ import annotations

import argparse
import csv
import sqlite3
from pathlib import Path
from typing import Iterable


def _parse_float(text: str) -> float:
    s = (text or "").strip()
    s = s.replace(",", ".")
    return float(s)


def load_takers_from_csv(csv_path: Path) -> list[dict[str, object]]:
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV não encontrado: {csv_path}")

    takers: list[dict[str, object]] = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            id_text = (row.get("N") or "").strip()
            if not id_text:
                continue
            try:
                tid = int(id_text)
            except ValueError:
                continue

            municipality = (row.get("MUNICIPIO") or "").strip()
            unit = (row.get("UNIDADE TOMADORA DE SERVIÇO") or "").strip()
            name = unit or municipality or f"Tomador {tid}"

            lat_text = (row.get("Latitude") or "").strip()
            lon_text = (row.get("Longitude") or "").strip()
            if not lat_text or not lon_text:
                continue
            try:
                lat = _parse_float(lat_text)
                lon = _parse_float(lon_text)
            except ValueError:
                continue

            takers.append({"id": tid, "nome_plataforma": name, "latitude": lat, "longitude": lon})

    takers.sort(key=lambda t: int(t["id"]))

    # Enforce unique names to satisfy the unique index.
    seen: dict[str, int] = {}
    for t in takers:
        name = str(t["nome_plataforma"]).strip()
        tid = int(t["id"])  # type: ignore[arg-type]
        if name in seen and seen[name] != tid:
            t["nome_plataforma"] = f"{name} ({tid})"
        else:
            t["nome_plataforma"] = name
            seen[name] = tid

    return takers


def _ensure_parent_dir(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        create table if not exists tomadores_servico (
            id integer primary key,
            nome_plataforma text not null,
            latitude real not null,
            longitude real not null
        )
        """
    )
    conn.execute(
        "create unique index if not exists ux_tomadores_servico_nome on tomadores_servico(nome_plataforma)"
    )


def _upsert_tomadores(conn: sqlite3.Connection, takers: Iterable[dict[str, object]]) -> None:
    conn.executemany(
        """
        insert into tomadores_servico (id, nome_plataforma, latitude, longitude)
        values (:id, :nome_plataforma, :latitude, :longitude)
        on conflict(id) do update set
            nome_plataforma = excluded.nome_plataforma,
            latitude = excluded.latitude,
            longitude = excluded.longitude
        """,
        list(takers),
    )


def create_database(db_path: Path, takers: list[dict[str, object]]) -> None:
    _ensure_parent_dir(db_path)
    with sqlite3.connect(db_path) as conn:
        _create_schema(conn)
        conn.execute("delete from tomadores_servico")
        _upsert_tomadores(conn, takers)
        conn.commit()


def main() -> int:
    parser = argparse.ArgumentParser(description="Create and populate the local service takers SQLite database.")
    parser.add_argument("--db-path", default="webapp/backend/db/service_takers.sqlite", help="SQLite database path")
    parser.add_argument(
        "--csv-path",
        default="Tomadores_de_servico_latlon.csv",
        help="CSV source (delimiter ';' with columns N/MUNICIPIO/UNIDADE TOMADORA DE SERVIÇO/Latitude/Longitude)",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]

    db_path = Path(args.db_path)
    if not db_path.is_absolute():
        db_path = repo_root / db_path
    db_path = db_path.resolve()

    csv_path = Path(args.csv_path)
    if not csv_path.is_absolute():
        csv_path = repo_root / csv_path
    csv_path = csv_path.resolve()

    takers = load_takers_from_csv(csv_path)
    create_database(db_path, takers)
    print(f"Created {db_path} with {len(takers)} tomadores de serviço from {csv_path}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
