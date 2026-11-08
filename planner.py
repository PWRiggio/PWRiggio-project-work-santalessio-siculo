#!/usr/bin/env python3
"""Pianificazione esatta di cinque consegne con uno oppure due veicoli.

Il programma usa esclusivamente la libreria standard di Python. Ogni ordine
di visita e ogni taglio in due giri vengono esaminati: non impiega euristiche
né solutori. L'obiettivo primario è la distanza totale della matrice fornita;
a parità di distanza si minimizza il tempo di guida totale, quindi si sceglie
la rappresentazione lessicograficamente più piccola per rendere l'esito stabile.
"""

import argparse
import itertools
import json
import math
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path


class InvalidInstanceError(ValueError):
    """Dati mancanti, incoerenti o non conformi al modello."""


class InfeasibleScenarioError(ValueError):
    """Nessun insieme di percorsi soddisfa tutti i vincoli."""


def number(value, name, *, minimum=0, strictly_positive=False):
    """Legge un numero finito senza accettare booleani o stringhe."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InvalidInstanceError(f"{name}: occorre un numero.")
    if not math.isfinite(value):
        raise InvalidInstanceError(f"{name}: il valore deve essere finito.")
    if value < minimum or (strictly_positive and value <= 0):
        raise InvalidInstanceError(f"{name}: valore fuori dall'intervallo ammesso.")
    return value


def tenths(value, name):
    """Converte metri o secondi in decimi interi senza errori binari."""
    number(value, name)
    scaled = Decimal(str(value)) * 10
    if scaled != scaled.to_integral_value():
        raise InvalidInstanceError(f"{name}: sono ammessi al massimo i decimi.")
    return int(scaled)


def matrix_tenths(matrix, name, size):
    if not isinstance(matrix, list) or len(matrix) != size:
        raise InvalidInstanceError(f"{name}: la matrice deve essere {size} x {size}.")
    result = []
    for i, row in enumerate(matrix):
        if not isinstance(row, list) or len(row) != size:
            raise InvalidInstanceError(f"{name}: riga {i} di dimensione errata.")
        result.append([])
        for j, value in enumerate(row):
            result[-1].append(tenths(value, f"{name}[{i}][{j}]"))
            if i == j and value != 0:
                raise InvalidInstanceError(f"{name}: la diagonale deve essere nulla.")
            if i != j and value <= 0:
                raise InvalidInstanceError(f"{name}: gli archi tra nodi distinti devono essere positivi.")
    return result


def validate_instance(instance):
    """Controlla l'istanza e restituisce matrici esatte in dm e decimi di s."""
    if not isinstance(instance, dict):
        raise InvalidInstanceError("L'istanza deve essere un oggetto JSON.")
    try:
        nodes = instance["nodes"]
        if not isinstance(nodes, list) or len(nodes) != 6:
            raise InvalidInstanceError("Sono necessari un deposito e cinque clienti.")
        if instance.get("depot_id", 0) != 0:
            raise InvalidInstanceError("Il deposito deve avere indice 0.")
        for i, node in enumerate(nodes):
            if not isinstance(node, dict) or isinstance(node.get("id"), bool) or node.get("id") != i:
                raise InvalidInstanceError("I nodi devono avere indici consecutivi da 0 a 5.")
            if not isinstance(node.get("name"), str) or not node["name"].strip():
                raise InvalidInstanceError(f"Il nodo {i} non ha un nome valido.")
            demand = number(node["demand_kg"], f"Domanda nodo {i}")
            if not isinstance(demand, int):
                raise InvalidInstanceError("Le domande sono espresse in kg interi.")
            if (i == 0 and demand != 0) or (i != 0 and demand <= 0):
                raise InvalidInstanceError("Il deposito ha domanda nulla e ogni cliente domanda positiva.")
        distances = matrix_tenths(instance["distances_m"], "distances_m", 6)
        durations = matrix_tenths(instance["durations_s"], "durations_s", 6)
        for vehicle_type, expected_count in (("large", 1), ("small", 2)):
            config = instance["vehicles"][vehicle_type]
            if isinstance(config["count"], bool) or config["count"] != expected_count:
                raise InvalidInstanceError(f"Numero di veicoli errato per {vehicle_type}.")
            number(config["capacity_kg"], "Capacità", strictly_positive=True)
            number(config["fixed_cost_eur"], "Noleggio")
            number(config["variable_cost_eur_km"], "Costo chilometrico")
        operations = instance["operations"]
        for key in ("driver_eur_hour", "service_minutes_client", "preparation_minutes_vehicle"):
            number(operations[key], key)
        for key in ("service_minutes_client", "preparation_minutes_vehicle"):
            tenths(operations[key] * 60, key)
        sensitivity = instance["sensitivity"]
        if sensitivity["parameter"] != "large_vehicle_fixed_cost_eur":
            raise InvalidInstanceError("La sensibilità riguarda il noleggio del veicolo grande.")
        number(sensitivity["min_eur"], "Sensibilità minimo")
        number(sensitivity["max_eur"], "Sensibilità massimo")
        number(sensitivity["step_eur"], "Sensibilità passo", strictly_positive=True)
        if sensitivity["max_eur"] <= sensitivity["min_eur"]:
            raise InvalidInstanceError("L'intervallo di sensibilità deve essere crescente.")
        if (sensitivity["max_eur"] - sensitivity["min_eur"]) / sensitivity["step_eur"] > 10000:
            raise InvalidInstanceError("Il passo di sensibilità produce più di 10001 punti.")
    except KeyError as exc:
        raise InvalidInstanceError(f"Campo obbligatorio mancante: {exc.args[0]}.") from exc
    total_load = sum(node["demand_kg"] for node in nodes)
    if total_load > instance["vehicles"]["large"]["capacity_kg"]:
        raise InfeasibleScenarioError("Il veicolo grande non può trasportare la domanda totale.")
    small_capacity = instance["vehicles"]["small"]["capacity_kg"]
    if total_load <= small_capacity:
        raise InvalidInstanceError("La domanda deve rendere necessario l'impiego di entrambi i mezzi piccoli.")
    if total_load > 2 * small_capacity or any(node["demand_kg"] > small_capacity for node in nodes[1:]):
        raise InfeasibleScenarioError("Le capacità dei mezzi piccoli non consentono il servizio.")
    return distances, durations


def route_metrics(order, instance, distances_dm, durations_ds):
    """Un giro chiuso parte dal deposito e lo raggiunge dopo l'ultimo cliente."""
    node_ids = (0,) + tuple(order) + (0,)
    edges = tuple(zip(node_ids, node_ids[1:]))
    distance_dm = sum(distances_dm[i][j] for i, j in edges)
    driving_ds = sum(durations_ds[i][j] for i, j in edges)
    return {
        "order": tuple(order),
        "distance_dm": distance_dm,
        "driving_ds": driving_ds,
        "load_kg": sum(instance["nodes"][i]["demand_kg"] for i in order),
    }


def decimal_output(value, places=6):
    """Numero JSON leggibile; i calcoli monetari precedenti restano Decimal."""
    return float(round(Decimal(value), places))


def cost_values(distance_dm, driver_ds, vehicle_count, vehicle, operations, fixed_override=None):
    fixed_unit = Decimal(str(vehicle["fixed_cost_eur"] if fixed_override is None else fixed_override))
    distance_rate = Decimal(str(vehicle["variable_cost_eur_km"]))
    wage = Decimal(str(operations["driver_eur_hour"]))
    fixed = vehicle_count * fixed_unit
    distance = Decimal(distance_dm) * distance_rate / 10000
    driver = Decimal(driver_ds) * wage / 36000
    return {"fixed_eur": fixed, "distance_eur": distance, "driver_eur": driver, "total_eur": fixed + distance + driver}


def exported_route(metric, instance, distances_dm, durations_ds, route_id):
    node_ids = (0,) + metric["order"] + (0,)
    nodes = instance["nodes"]
    operations = instance["operations"]
    service_ds = len(metric["order"]) * tenths(operations["service_minutes_client"] * 60, "Servizio")
    preparation_ds = tenths(operations["preparation_minutes_vehicle"] * 60, "Preparazione")
    total_ds = metric["driving_ds"] + service_ds + preparation_ds
    arcs = [
        {
            "from_id": i, "to_id": j,
            "from_name": nodes[i]["name"], "to_name": nodes[j]["name"],
            "distance_m": distances_dm[i][j] / 10,
            "distance_km": distances_dm[i][j] / 10000,
            "driving_seconds": durations_ds[i][j] / 10,
        }
        for i, j in zip(node_ids, node_ids[1:])
    ]
    return {
        "route_id": route_id,
        "node_ids": list(node_ids),
        "node_names": [nodes[i]["name"] for i in node_ids],
        "arcs": arcs,
        "load_kg": metric["load_kg"],
        "distance_dm": metric["distance_dm"],
        "distance_m": metric["distance_dm"] / 10,
        "distance_km": metric["distance_dm"] / 10000,
        "driving_ds": metric["driving_ds"],
        "driving_seconds": metric["driving_ds"] / 10,
        "driving_minutes": metric["driving_ds"] / 600,
        "service_seconds": service_ds / 10,
        "preparation_seconds": preparation_ds / 10,
        "total_ds": total_ds,
        "total_seconds": total_ds / 10,
        "total_minutes": total_ds / 600,
    }


def enumerate_scenario(instance, distances_dm, durations_ds, vehicle_type):
    """Esamina 120 ordini o 120 x 4 coppie ordinate, conservando i duplicati."""
    vehicle = instance["vehicles"][vehicle_type]
    count = vehicle["count"]
    generated = 0
    candidates = []
    for order in itertools.permutations(range(1, 6)):
        # Un solo taglio artificiale per TSP; quattro tagli non vuoti per VRP.
        cuts = (None,) if count == 1 else range(1, 5)
        for cut in cuts:
            orders = (order,) if cut is None else (order[:cut], order[cut:])
            generated += 1
            metrics = tuple(route_metrics(route, instance, distances_dm, durations_ds) for route in orders)
            if any(route["load_kg"] > vehicle["capacity_kg"] for route in metrics):
                continue
            candidates.append({
                "orders": orders,
                "metrics": metrics,
                "distance_dm": sum(route["distance_dm"] for route in metrics),
                "driving_ds": sum(route["driving_ds"] for route in metrics),
            })
    if not candidates:
        raise InfeasibleScenarioError("Non esiste una partizione dei clienti compatibile con due veicoli piccoli.")
    minimum_distance = min(item["distance_dm"] for item in candidates)
    primary_optima = [item for item in candidates if item["distance_dm"] == minimum_distance]
    minimum_driving = min(item["driving_ds"] for item in primary_optima)
    optima = [item for item in primary_optima if item["driving_ds"] == minimum_driving]
    best = min(optima, key=lambda item: item["orders"])
    # La deduplicazione è applicata soltanto al resoconto degli ottimi, non alla ricerca.
    unique_optima = sorted({tuple(sorted(item["orders"])) for item in optima})
    unique_feasible = {tuple(sorted(item["orders"])) for item in candidates}
    unique_primary = {tuple(sorted(item["orders"])) for item in primary_optima}
    routes = [exported_route(metric, instance, distances_dm, durations_ds, i + 1) for i, metric in enumerate(best["metrics"])]
    visits = [client for route in routes for client in route["node_ids"][1:-1]]
    constraint_checks = {
        "all_customers_served_once": sorted(visits) == list(range(1, 6)),
        "all_routes_start_and_end_at_depot": all(route["node_ids"][0] == 0 and route["node_ids"][-1] == 0 for route in routes),
        "capacity_respected": all(route["load_kg"] <= vehicle["capacity_kg"] for route in routes),
        "all_routes_nonempty": all(len(route["node_ids"]) >= 3 for route in routes),
        "required_vehicle_count": len(routes) == count,
    }
    if not all(constraint_checks.values()):
        raise RuntimeError("Errore interno: il percorso generato viola un vincolo.")
    driver_ds = sum(route["total_ds"] for route in routes)
    costs = cost_values(best["distance_dm"], driver_ds, count, vehicle, instance["operations"])
    totals = {
        "vehicle_count": count,
        "load_kg": sum(route["load_kg"] for route in routes),
        "capacity_kg": count * vehicle["capacity_kg"],
        "distance_dm": best["distance_dm"],
        "distance_m": best["distance_dm"] / 10,
        "distance_km": best["distance_dm"] / 10000,
        "driving_ds": best["driving_ds"],
        "driving_seconds": best["driving_ds"] / 10,
        "driving_hours": best["driving_ds"] / 36000,
        "service_seconds": sum(route["service_seconds"] for route in routes),
        "preparation_seconds": sum(route["preparation_seconds"] for route in routes),
        "driver_ds": driver_ds,
        "driver_seconds": driver_ds / 10,
        "driver_hours": driver_ds / 36000,
        "completion_seconds": max(route["total_seconds"] for route in routes),
        "completion_minutes": max(route["total_minutes"] for route in routes),
    }
    return {
        "label": f"Un veicolo da {vehicle['capacity_kg']:g} kg" if count == 1 else f"Due veicoli da {vehicle['capacity_kg']:g} kg",
        "vehicle_type": vehicle_type,
        "vehicle_parameters": vehicle,
        "constraint_checks": constraint_checks,
        "routes": routes,
        "totals": totals,
        "costs": {key: decimal_output(value) for key, value in costs.items()},
        "enumeration": {
            "permutations": math.factorial(5),
            "cuts_per_permutation": 1 if count == 1 else 4,
            "candidates_generated": generated,
            "feasible_candidates": len(candidates),
            "discarded_for_capacity": generated - len(candidates),
            "feasible_unique_vehicle_exchange": len(unique_feasible),
            "optimal_distance_candidates": len(primary_optima),
            "optimal_distance_unique_vehicle_exchange": len(unique_primary),
            "optimal_distance_and_time_candidates": len(optima),
            "optimal_unique_vehicle_exchange": len(unique_optima),
        },
        "optimal_solutions": [
            {"routes_node_ids": [[0, *route, 0] for route in solution]}
            for solution in unique_optima
        ],
    }


def solve(instance):
    """Calcola percorsi ottimi e sensibilità dei costi, senza cambiare i giri."""
    distances_dm, durations_ds = validate_instance(instance)
    single = enumerate_scenario(instance, distances_dm, durations_ds, "large")
    double = enumerate_scenario(instance, distances_dm, durations_ds, "small")
    large_costs = cost_values(single["totals"]["distance_dm"], single["totals"]["driver_ds"], 1, instance["vehicles"]["large"], instance["operations"])
    small_costs = cost_values(double["totals"]["distance_dm"], double["totals"]["driver_ds"], 2, instance["vehicles"]["small"], instance["operations"])
    threshold = small_costs["total_eur"] - large_costs["distance_eur"] - large_costs["driver_eur"]
    difference = small_costs["total_eur"] - large_costs["total_eur"]
    sensitivity_config = instance["sensitivity"]
    start = Decimal(str(sensitivity_config["min_eur"]))
    stop = Decimal(str(sensitivity_config["max_eur"]))
    step = Decimal(str(sensitivity_config["step_eur"]))
    values = set()
    value = start
    while value <= stop:
        values.add(value)
        value += step
    values.add(stop)
    if start <= threshold <= stop:
        values.add(threshold)
    points = []
    for value in sorted(values):
        cost_one = value + large_costs["distance_eur"] + large_costs["driver_eur"]
        cost_two = small_costs["total_eur"]
        points.append({
            "large_fixed_cost_eur": decimal_output(value),
            "single_vehicle_eur": decimal_output(cost_one),
            "two_vehicles_eur": decimal_output(cost_two),
            "cheaper_scenario": "tie" if cost_one == cost_two else ("single_vehicle" if cost_one < cost_two else "two_vehicles"),
        })
    return {
        "schema_version": "1.0",
        "title": instance.get("title", "Pianificazione delle consegne agroalimentari"),
        "method": {
            "algorithm": "enumerazione completa",
            "objective": "minima distanza complessiva sulla matrice stradale fornita",
            "tie_break": ["minimo tempo di guida complessivo", "ordine lessicografico dei percorsi"],
            "distance_internal_unit": "decimetro intero",
            "time_internal_unit": "decimo di secondo intero",
            "directed_matrix": True,
            "note": "Gli scenari sono ottimizzati per distanza; i costi e la sensibilità sono calcolati sui percorsi così ottenuti.",
        },
        "nodes": instance["nodes"],
        "operations": instance["operations"],
        "source": instance.get("source", {}),
        "scenarios": {"single_vehicle": single, "two_vehicles": double},
        "comparison": {
            "baseline_cheaper_scenario": "tie" if difference == 0 else ("single_vehicle" if difference > 0 else "two_vehicles"),
            "baseline_savings_eur": decimal_output(abs(difference)),
            "two_minus_one_cost_eur": decimal_output(difference),
            "additional_distance_two_vehicles_km": (double["totals"]["distance_dm"] - single["totals"]["distance_dm"]) / 10000,
            "additional_driver_hours_two_vehicles": (double["totals"]["driver_ds"] - single["totals"]["driver_ds"]) / 36000,
            "completion_reduction_minutes": (single["totals"]["completion_seconds"] - double["totals"]["completion_seconds"]) / 60,
            "threshold_large_fixed_cost_eur": decimal_output(threshold),
            "threshold_formula": "F_grande* = 2 F_piccolo + k_piccolo D_due - k_grande D_uno + w (H_due - H_uno)",
            "threshold_interpretation": "Sotto la soglia conviene un veicolo; sopra la soglia convengono due veicoli; alla soglia i costi coincidono.",
        },
        "sensitivity": {
            **sensitivity_config,
            "fixed_routes": True,
            "threshold_eur": decimal_output(threshold),
            "threshold_inside_interval": start <= threshold <= stop,
            "single_vehicle_cost_min_eur": min(point["single_vehicle_eur"] for point in points),
            "single_vehicle_cost_max_eur": max(point["single_vehicle_eur"] for point in points),
            "two_vehicles_cost_min_eur": min(point["two_vehicles_eur"] for point in points),
            "two_vehicles_cost_max_eur": max(point["two_vehicles_eur"] for point in points),
            "points": points,
        },
    }


def main(argv=None):
    folder = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instance", type=Path, default=folder / "instance.json", help="File JSON dell'istanza")
    parser.add_argument("--output", type=Path, default=folder / "results.json", help="File JSON dei risultati")
    args = parser.parse_args(argv)
    try:
        instance = json.loads(args.instance.read_text(encoding="utf-8"))
        results = solve(instance)
        args.output.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (OSError, json.JSONDecodeError, InvalidInstanceError, InfeasibleScenarioError, InvalidOperation) as exc:
        print(f"Errore: {exc}", file=sys.stderr)
        return 2
    for key in ("single_vehicle", "two_vehicles"):
        scenario = results["scenarios"][key]
        print(scenario["label"])
        for route in scenario["routes"]:
            print(f"  {' > '.join(route['node_names'])} | {route['load_kg']} kg | {route['distance_km']:.4f} km")
        print(f"  Totale: {scenario['totals']['distance_km']:.4f} km; {scenario['totals']['driver_hours']:.4f} ore autista; {scenario['costs']['total_eur']:.2f} euro")
        counts = scenario["enumeration"]
        print(f"  Candidati: {counts['candidates_generated']}; ammissibili: {counts['feasible_candidates']}")
    print(f"Soglia noleggio mezzo grande: {results['comparison']['threshold_large_fixed_cost_eur']:.6f} euro/giorno")
    print(f"Risultati scritti in {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
