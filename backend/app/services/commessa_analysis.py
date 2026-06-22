"""Classificazione preliminare dei pezzi della commessa."""
from __future__ import annotations

from collections import defaultdict

from backend.app.services.distinta import normalize_profile


def classify_commessa_materials(items: list) -> dict:
    """Raggruppa i pezzi fisici per profilo e materiale, senza validare i profili."""
    groups: dict[tuple[str, str, str], list[Any]] = defaultdict(list)
    for item in items:
        if not item.description:
            continue
        tipo = "PEZZI"
        profile = normalize_profile(item.description)
        quality = (item.material_code or "").upper().strip()
        groups[(tipo, profile, quality)].append(item)

    results = []
    for (tipo, profile, quality), group_items in sorted(groups.items()):
        results.append({
            "tipo": tipo,
            "profilo": profile,
            "qualita": quality or None,
            "n_pezzi": len(group_items),
            "n_codici_pezzo": len({item.part_number for item in group_items if item.part_number}),
        })

    type_rows: dict[str, dict] = {}
    for row in results:
        summary = type_rows.setdefault(row["tipo"], {
            "tipo": row["tipo"],
            "n_pezzi": 0,
            "n_codici_pezzo": 0,
            "n_gruppi": 0,
        })
        summary["n_pezzi"] += row["n_pezzi"]
        summary["n_codici_pezzo"] += row["n_codici_pezzo"]
        summary["n_gruppi"] += 1

    return {
        "groups": results,
        "types": sorted(type_rows.values(), key=lambda row: (-row["n_pezzi"], row["tipo"])),
        "n_gruppi": len(results),
        "n_pezzi": len(items),
        "sola_classificazione": True,
    }
