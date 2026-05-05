from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .service_takers import ServiceTaker
from .timeutils import TimeRange, default_timerange, parse_time_input


@dataclass(frozen=True)
class UserSelection:
    taker_number: int
    mode: int
    time_range: TimeRange
    dynamic_start: bool
    dynamic_end: bool
    initial_load_hours: int


def ask_selection(takers: list[ServiceTaker], *, default_initial_load_hours: int = 0) -> UserSelection:
    print("=== VISUALIZADOR DE RAIOS (GOES-19 GLM) ===")
    print("Tomadores disponíveis:")
    for t in takers:
        print(f"  {t.idx:2d} - {t.unidade} ({t.municipio})")

    while True:
        raw = input("\nSelecione tomador (1-40): ").strip()
        try:
            n = int(raw)
            if 1 <= n <= 40:
                break
        except ValueError:
            pass
        print("Valor inválido.")

    print("\nModo de plotagem:")
    print("  1 - Flashes (markers coloridos por tempo) [default]")
    print("  2 - Flashes (densidade)")
    print("  3 - Eventos (espacialização cinza)")
    print("  4 - Eventos (densidade)")
    raw_mode = input("Escolha (1-4) [1]: ").strip() or "1"
    mode = int(raw_mode) if raw_mode.isdigit() else 1
    mode = mode if mode in (1, 2, 3, 4) else 1

    tr = default_timerange()
    print("\nTempo (local):")
    print(f"  Início padrão: {tr.start_local:%Y-%m-%d %H:%M:%S}")
    print(f"  Fim padrão:    {tr.end_local:%Y-%m-%d %H:%M:%S}")
    start_txt = input("Início (HH:MM:SS ou YYYY-MM-DD HH:MM:SS) [00:00:00]: ").strip()
    end_txt = input("Fim    (HH:MM:SS ou YYYY-MM-DD HH:MM:SS) [agora]: ").strip()

    dynamic_start = (start_txt == "")
    dynamic_end = (end_txt == "")

    base_start = tr.start_local
    base_end = tr.end_local
    start = parse_time_input(start_txt, base_date_local=base_start)
    end = parse_time_input(end_txt, base_date_local=base_end)
    if end < start:
        start, end = end, start

    raw_init = input(f"Carga inicial (horas; 0=desativado) [{default_initial_load_hours}]: ").strip()
    if raw_init == "":
        initial_load_hours = int(default_initial_load_hours)
    else:
        try:
            initial_load_hours = int(raw_init)
        except ValueError:
            initial_load_hours = int(default_initial_load_hours)
    if initial_load_hours < 0:
        initial_load_hours = 0

    return UserSelection(
        taker_number=n,
        mode=mode,
        time_range=TimeRange(start_local=start, end_local=end),
        dynamic_start=dynamic_start,
        dynamic_end=dynamic_end,
        initial_load_hours=initial_load_hours,
    )
