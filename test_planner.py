"""Verifiche indipendenti dei vincoli, dell'enumerazione e del confronto."""

import copy
import hashlib
import itertools
import json
import unittest
from decimal import Decimal
from pathlib import Path

from planner import InvalidInstanceError, InfeasibleScenarioError, solve


def uniform_instance():
    """Grafo con archi uniformi: consente risultati chiusi, senza altro solver."""
    return {
        "depot_id": 0,
        "nodes": [
            {"id": i, "name": f"Nodo {i}", "demand_kg": demand}
            for i, demand in enumerate((0, 80, 40, 50, 35, 55))
        ],
        "distances_m": [[0 if i == j else 1000 for j in range(6)] for i in range(6)],
        "durations_s": [[0 if i == j else 60 for j in range(6)] for i in range(6)],
        "vehicles": {
            "large": {"count": 1, "capacity_kg": 300, "fixed_cost_eur": 95, "variable_cost_eur_km": 0.48},
            "small": {"count": 2, "capacity_kg": 150, "fixed_cost_eur": 55, "variable_cost_eur_km": 0.38},
        },
        "operations": {"driver_eur_hour": 18, "service_minutes_client": 10, "preparation_minutes_vehicle": 15},
        "sensitivity": {"parameter": "large_vehicle_fixed_cost_eur", "min_eur": 60, "max_eur": 180, "step_eur": 5},
    }


class PlannerTests(unittest.TestCase):
    def test_counts_and_equivalences_have_independent_closed_form(self):
        results = solve(uniform_instance())
        single = results["scenarios"]["single_vehicle"]
        double = results["scenarios"]["two_vehicles"]
        self.assertEqual(single["enumeration"]["candidates_generated"], 120)
        self.assertEqual(single["enumeration"]["feasible_candidates"], 120)
        self.assertEqual(double["enumeration"]["candidates_generated"], 480)
        # Solo quattro partizioni 2+3 sono ammissibili; ognuna ha
        # 2! * 3! ordinamenti e due scambi tra i mezzi: 4*12*2 = 96.
        self.assertEqual(double["enumeration"]["feasible_candidates"], 96)
        self.assertEqual(double["enumeration"]["feasible_unique_vehicle_exchange"], 48)
        self.assertEqual(double["enumeration"]["optimal_distance_and_time_candidates"], 96)
        self.assertEqual(double["enumeration"]["optimal_unique_vehicle_exchange"], 48)
        self.assertEqual(single["totals"]["distance_km"], 6)
        self.assertEqual(double["totals"]["distance_km"], 7)
        self.assertEqual(single["routes"][0]["node_ids"], [0, 1, 2, 3, 4, 5, 0])

    def test_asymmetric_arcs_and_distance_priority_over_time(self):
        instance = uniform_instance()
        instance["durations_s"] = [[0 if i == j else 1 for j in range(6)] for i in range(6)]
        for i, j in zip((0, 1, 2, 3, 4, 5), (1, 2, 3, 4, 5, 0)):
            instance["distances_m"][i][j] = 100
            instance["durations_s"][i][j] = 100
            instance["distances_m"][j][i] = 101
        result = solve(instance)["scenarios"]["single_vehicle"]
        self.assertEqual(result["routes"][0]["node_ids"], [0, 1, 2, 3, 4, 5, 0])
        self.assertEqual(result["totals"]["distance_m"], 600)
        self.assertEqual(result["totals"]["driving_seconds"], 600)
        # Il giro inverso richiederebbe solo 6 s, ma sarebbe lungo 606 m.
        self.assertEqual(result["enumeration"]["optimal_distance_candidates"], 1)

    def test_time_breaks_a_distance_tie(self):
        instance = uniform_instance()
        for i, j in zip((0, 5, 4, 3, 2, 1), (5, 4, 3, 2, 1, 0)):
            instance["durations_s"][i][j] = 1
        result = solve(instance)["scenarios"]["single_vehicle"]
        self.assertEqual(result["routes"][0]["node_ids"], [0, 5, 4, 3, 2, 1, 0])
        self.assertEqual(result["enumeration"]["optimal_distance_candidates"], 120)
        self.assertEqual(result["enumeration"]["optimal_distance_and_time_candidates"], 1)

    def test_aggregate_capacity_does_not_imply_a_feasible_partition(self):
        instance = uniform_instance()
        for node, demand in zip(instance["nodes"], (0, 6, 6, 6, 1, 1)):
            node["demand_kg"] = demand
        instance["vehicles"]["large"]["capacity_kg"] = 20
        instance["vehicles"]["small"]["capacity_kg"] = 10
        # Ogni domanda è <=10 e la somma è 20, ma tre carichi da6 non
        # possono essere ripartiti su due mezzi da10 senza dividere ordini.
        with self.assertRaises(InfeasibleScenarioError):
            solve(instance)

    def test_invalid_data_are_reported_before_optimization(self):
        cases = []
        bad = uniform_instance(); bad["distances_m"][1].pop(); cases.append(bad)
        bad = uniform_instance(); bad["distances_m"][1][2] = None; cases.append(bad)
        bad = uniform_instance(); bad["durations_s"][1][2] = -1; cases.append(bad)
        bad = uniform_instance(); bad["distances_m"][0][0] = 1; cases.append(bad)
        bad = uniform_instance(); bad["nodes"][1]["demand_kg"] = True; cases.append(bad)
        bad = uniform_instance(); bad["nodes"][1]["id"] = 3; cases.append(bad)
        bad = uniform_instance(); bad["operations"]["driver_eur_hour"] = float("nan"); cases.append(bad)
        bad = uniform_instance(); bad["sensitivity"]["step_eur"] = 0; cases.append(bad)
        bad = uniform_instance(); del bad["vehicles"]["small"]["fixed_cost_eur"]; cases.append(bad)
        for index, bad in enumerate(cases):
            with self.subTest(index=index):
                with self.assertRaises(InvalidInstanceError):
                    solve(bad)

    def test_driver_cost_uses_sum_of_durations_and_not_makespan(self):
        result = solve(uniform_instance())["scenarios"]["two_vehicles"]
        self.assertEqual(result["totals"]["driver_seconds"], 5220)
        self.assertEqual(result["totals"]["completion_seconds"], 2940)
        self.assertEqual(result["costs"]["driver_eur"], 26.1)
        self.assertEqual(result["costs"]["total_eur"], 138.76)
        self.assertGreater(result["totals"]["driver_seconds"], result["totals"]["completion_seconds"])

    def test_break_even_reverses_the_economic_choice(self):
        instance = uniform_instance()
        base = solve(instance)
        threshold = base["comparison"]["threshold_large_fixed_cost_eur"]
        self.assertAlmostEqual(threshold, 114.58, places=6)
        for shift, expected in ((-1, "single_vehicle"), (0, "tie"), (1, "two_vehicles")):
            modified = copy.deepcopy(instance)
            modified["vehicles"]["large"]["fixed_cost_eur"] = threshold + shift
            result = solve(modified)
            self.assertEqual(result["comparison"]["baseline_cheaper_scenario"], expected)
            self.assertEqual(result["scenarios"]["single_vehicle"]["routes"], base["scenarios"]["single_vehicle"]["routes"])
        point = next(point for point in base["sensitivity"]["points"] if point["cheaper_scenario"] == "tie")
        self.assertEqual(point["single_vehicle_eur"], point["two_vehicles_eur"])

    def test_real_instance_coverage_arcs_costs_and_frozen_results(self):
        instance = json.loads((Path(__file__).parent / "instance.json").read_text(encoding="utf-8"))
        results = solve(instance)
        expected = {
            "single_vehicle": {"routes": [[0, 4, 5, 3, 2, 1, 0]], "km": 41.3993, "eur": 148.776664},
            "two_vehicles": {"routes": [[0, 2, 1, 0], [0, 4, 5, 3, 0]], "km": 53.4281, "eur": 172.299678},
        }
        for key, scenario in results["scenarios"].items():
            visits = []
            distance = Decimal(0)
            driving = Decimal(0)
            vehicle = instance["vehicles"][scenario["vehicle_type"]]
            for route in scenario["routes"]:
                ids = route["node_ids"]
                self.assertEqual(ids[0], 0)
                self.assertEqual(ids[-1], 0)
                self.assertGreaterEqual(len(ids), 3)
                visits.extend(ids[1:-1])
                self.assertLessEqual(sum(instance["nodes"][i]["demand_kg"] for i in ids[1:-1]), vehicle["capacity_kg"])
                distance += sum((Decimal(str(instance["distances_m"][i][j])) for i, j in zip(ids, ids[1:])), Decimal(0))
                driving += sum((Decimal(str(instance["durations_s"][i][j])) for i, j in zip(ids, ids[1:])), Decimal(0))
            self.assertEqual(sorted(visits), [1, 2, 3, 4, 5])
            self.assertEqual(float(distance), scenario["totals"]["distance_m"])
            self.assertEqual(float(driving), scenario["totals"]["driving_seconds"])
            count = len(scenario["routes"])
            hours = (driving + 5 * 600 + count * 900) / 3600
            cost = count * Decimal(str(vehicle["fixed_cost_eur"])) + distance / 1000 * Decimal(str(vehicle["variable_cost_eur_km"])) + hours * 18
            self.assertAlmostEqual(float(cost), scenario["costs"]["total_eur"], places=6)
            self.assertEqual([route["node_ids"] for route in scenario["routes"]], expected[key]["routes"])
            self.assertAlmostEqual(scenario["totals"]["distance_km"], expected[key]["km"], places=6)
            self.assertAlmostEqual(scenario["costs"]["total_eur"], expected[key]["eur"], places=6)
        self.assertAlmostEqual(results["comparison"]["threshold_large_fixed_cost_eur"], 118.523014, places=6)

    def test_santalessio_optimum_with_independent_subset_decomposition(self):
        """Controlla il VRP dividendo prima i clienti, anziché tagliare gli ordini."""
        folder = Path(__file__).parent
        instance = json.loads((folder / "instance.json").read_text(encoding="utf-8"))
        customers = tuple(range(1, 6))
        capacity = instance["vehicles"]["small"]["capacity_kg"]

        def route_value(order):
            closed = (0, *order, 0)
            distance = sum((Decimal(str(instance["distances_m"][a][b])) for a, b in zip(closed, closed[1:])), Decimal(0))
            driving = sum((Decimal(str(instance["durations_s"][a][b])) for a, b in zip(closed, closed[1:])), Decimal(0))
            return int(distance * 10), int(driving * 10), order

        candidates = []
        feasible_partitions = 0
        for size in range(1, 5):
            for first in itertools.combinations(customers, size):
                if 1 not in first:
                    continue  # Un rappresentante per lo scambio dei due mezzi.
                second = tuple(node for node in customers if node not in first)
                if any(sum(instance["nodes"][node]["demand_kg"] for node in group) > capacity for group in (first, second)):
                    continue
                feasible_partitions += 1
                best_first = min(route_value(order) for order in itertools.permutations(first))
                best_second = min(route_value(order) for order in itertools.permutations(second))
                candidates.append((best_first[0] + best_second[0], best_first[1] + best_second[1]))
        self.assertEqual(feasible_partitions, 4)
        optimum = min(candidates)
        computed = solve(instance)["scenarios"]["two_vehicles"]["totals"]
        self.assertEqual((computed["distance_dm"], computed["driving_ds"]), optimum)

    def test_frozen_source_matches_instance_and_coordinates(self):
        folder = Path(__file__).parent
        instance = json.loads((folder / "instance.json").read_text(encoding="utf-8"))
        source = instance["source"]
        raw_bytes = (folder / source["raw_response_file"]).read_bytes()
        raw = json.loads(raw_bytes)
        details = json.loads((folder / source["details_file"]).read_text(encoding="utf-8"))
        self.assertEqual(hashlib.sha256(raw_bytes).hexdigest(), source["raw_response_sha256"])
        self.assertEqual(raw["code"], "Ok")
        self.assertEqual(instance["distances_m"], raw["distances"])
        self.assertEqual(instance["durations_s"], raw["durations"])
        self.assertEqual(instance["distances_m"], details["distances_m"])
        self.assertEqual([node["name"] for node in instance["nodes"]], ["Sant’Alessio Siculo", "Santa Teresa di Riva", "Furci Siculo", "Roccalumera", "Letojanni", "Taormina"])
        for node, waypoint in zip(instance["nodes"], raw["sources"]):
            self.assertEqual([node["lon"], node["lat"]], waypoint["location"])
        self.assertTrue(any(instance["distances_m"][i][j] != instance["distances_m"][j][i] for i in range(6) for j in range(i)))
        references = json.loads((folder / source["coordinate_sources_file"]).read_text(encoding="utf-8"))
        self.assertEqual(len(references), 6)
        for node, reference in zip(instance["nodes"], references):
            coordinate_bytes = (folder / reference["raw_response_file"]).read_bytes()
            self.assertEqual(hashlib.sha256(coordinate_bytes).hexdigest(), reference["raw_response_sha256"])
            point = json.loads(coordinate_bytes)[0]
            self.assertEqual(node["requested_lat"], float(point["lat"]))
            self.assertEqual(node["requested_lon"], float(point["lon"]))
            self.assertEqual(point["address"]["county"], "Messina")
            self.assertEqual(point["address"]["country_code"], "it")


if __name__ == "__main__":
    unittest.main()
