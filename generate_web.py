#!/usr/bin/env python3
"""Prepara i dati per la pagina HTML, utilizzabile anche con apertura file://.

Eseguire prima planner.py. Il generatore non ricalcola i percorsi ottimi:
legge instance.json e results.json, verifica le informazioni essenziali e
incorpora i dati in dist/data.js. Non sono necessarie librerie esterne.
"""

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path


def read_json(path):
    """Carica un file UTF-8 e lascia al chiamante la gestione degli errori."""
    return json.loads(path.read_text(encoding="utf-8"))


def validate_results(instance, results):
    """Evita di unire risultati vecchi con un'istanza modificata."""
    if results.get("nodes") != instance.get("nodes"):
        raise ValueError("I nodi di results.json differiscono dall’istanza; rieseguire planner.py.")
    if results.get("operations") != instance.get("operations"):
        raise ValueError("I tempi o i prezzi operativi differiscono; rieseguire planner.py.")
    for scenario_key, vehicle_key in (("single_vehicle", "large"), ("two_vehicles", "small")):
        scenario = results["scenarios"][scenario_key]
        if scenario["vehicle_parameters"] != instance["vehicles"][vehicle_key]:
            raise ValueError("I parametri dei veicoli differiscono; rieseguire planner.py.")
        if scenario["enumeration"]["candidates_generated"] != (120 if vehicle_key == "large" else 480):
            raise ValueError("Conteggio dei candidati non valido per il caso a cinque clienti.")
        seen = []
        for route in scenario["routes"]:
            if route["node_ids"][0] != 0 or route["node_ids"][-1] != 0:
                raise ValueError("Ogni giro deve partire dal deposito e ritornarvi.")
            seen.extend(route["node_ids"][1:-1])
            for arc in route["arcs"]:
                i, j = arc["from_id"], arc["to_id"]
                if arc["distance_m"] != instance["distances_m"][i][j]:
                    raise ValueError("Distanze dei risultati non aggiornate; rieseguire planner.py.")
                if arc["driving_seconds"] != instance["durations_s"][i][j]:
                    raise ValueError("Tempi dei risultati non aggiornati; rieseguire planner.py.")
        if sorted(seen) != [1, 2, 3, 4, 5]:
            raise ValueError("I cinque clienti devono comparire esattamente una volta.")
    sensitivity = instance["sensitivity"]
    for key in ("parameter", "min_eur", "max_eur", "step_eur"):
        if results["sensitivity"][key] != sensitivity[key]:
            raise ValueError("Intervallo di sensibilità non aggiornato; rieseguire planner.py.")


def main(argv=None):
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instance", type=Path, default=root / "instance.json")
    parser.add_argument("--results", type=Path, default=root / "results.json")
    parser.add_argument("--output-dir", type=Path, default=root / "dist")
    args = parser.parse_args(argv)
    try:
        instance = read_json(args.instance)
        results = read_json(args.results)
        validate_results(instance, results)
        for filename in ("index.html", "styles.css", "app.js"):
            if not (args.output_dir / filename).is_file():
                raise ValueError(f"File frontend mancante: {args.output_dir / filename}")
        data = {"instance": instance, "results": results}
        serialized = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        # Non vengono eseguite richieste fetch: i dati restano disponibili offline.
        # Le sostituzioni mantengono sicura anche un'eventuale inclusione inline.
        serialized = serialized.replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
        (args.output_dir / "data.js").write_text(
            "// Generato da generate_web.py a partire da instance.json e results.json.\n"
            f"window.PW_DATA = {serialized};\n",
            encoding="utf-8",
        )
        downloads = args.output_dir / "downloads"
        downloads.mkdir(parents=True, exist_ok=True)
        for source, destination in ((args.instance, "instance.json"), (args.results, "results.json")):
            shutil.copyfile(source, downloads / destination)
        raw_relative = instance.get("source", {}).get("raw_response_file", "data/osrm_table_response.json")
        metadata_relative = instance.get("source", {}).get("details_file", "data/road_distances.json")
        raw_path = root / raw_relative
        metadata_path = root / metadata_relative
        if not raw_path.is_file() or not metadata_path.is_file():
            raise ValueError("Sono necessari risposta OSRM originale e metadati del routing.")
        expected_hash = instance.get("source", {}).get("raw_response_sha256")
        if expected_hash and hashlib.sha256(raw_path.read_bytes()).hexdigest() != expected_hash:
            raise ValueError("La risposta OSRM non corrisponde all’hash registrato nell’istanza.")
        shutil.copyfile(raw_path, downloads / "osrm_table_response.json")
        shutil.copyfile(metadata_path, downloads / "routing_metadata.json")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"Errore nella generazione HTML: {exc}", file=sys.stderr)
        return 2
    print(f"Dati incorporati in {args.output_dir / 'data.js'}")
    print(f"Pagina pronta: {args.output_dir / 'index.html'}")
    print("Aprire index.html nel browser; non è necessario avviare un server.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
