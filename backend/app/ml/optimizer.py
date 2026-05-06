# backend/app/ml/optimizer.py
#
# OR-Tools Capacitated Vehicle Routing Problem (CVRP) solver.
# Called by POST /events/{event_id}/allocate after XGBoost scoring.
#
# WHY OR-Tools for routing and not just "sort by score and drive"?
# A coordinator with 3 trucks and 8 barangays can't naively visit
# them in score order — Mambaling (rank #1) might be 45 minutes
# north while Duljo-Fatima (rank #2) is 5 minutes south. OR-Tools
# finds the shortest total travel distance while still prioritizing
# high-score barangays by weighting their demand higher.
#
# Architecture:
#   solve_cvrp()       — main entry point, called from allocations.py
#   _haversine_km()    — great-circle distance between two GPS coords
#   _build_distance_matrix() — pairwise distances: depot + all barangays
#   _extract_routes()  — parse OR-Tools solution into ordered stop lists
#
# Simplifications for OJT scope (production would need):
#   - Real road distances via OSRM instead of straight-line Haversine
#   - Truck capacity constraints per goods type (not just total weight)
#   - Time windows per barangay (e.g. only accessible 6AM-6PM)
#   - Multiple depots (one per supply source warehouse)
#
# For now: one depot (first warehouse in supplies), N trucks = 3,
# capacity = sum of all goods / N per truck (equal split as ceiling).
# The routing order is what matters — quantities stay proportional.

import math
from ortools.constraint_solver import routing_enums_pb2, pywrapcp

# ── Constants ─────────────────────────────────────────────────────────────────

# Number of trucks available for dispatch.
# In a real deployment this would come from the LGU's vehicle registry.
# 3 is a realistic number for a mid-sized Cebu City operation.
NUM_TRUCKS = 3

# OR-Tools search time limit in seconds.
# 10 seconds is more than enough for 8-20 barangays.
# Increase to 30 if you add more barangays or time windows.
SOLVER_TIME_LIMIT_SECONDS = 10


# ── Haversine distance ────────────────────────────────────────────────────────


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Great-circle distance between two GPS coordinates in kilometers.

    WHY Haversine and not Euclidean?
    Euclidean distance treats lat/lon as a flat grid — accurate near
    the equator but breaks down at larger scales. The Philippines spans
    ~1800km north-south; Haversine handles spherical Earth correctly.
    Error vs actual road distance: ~15-25% (roads aren't straight lines),
    but this is acceptable for routing order — we're optimizing sequence,
    not predicting exact travel time.
    """
    R = 6371.0  # Earth radius in km
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ── Distance matrix ───────────────────────────────────────────────────────────


def _build_distance_matrix(
    depot_lat: float,
    depot_lon: float,
    barangay_coords: list[tuple[float, float]],
) -> list[list[int]]:
    """
    Build pairwise distance matrix for OR-Tools.

    OR-Tools requires integer distances (it uses integer arithmetic internally).
    We multiply km by 100 and round to get decameters — preserves 10m precision
    without overflow on realistic Philippine distances (max ~200km).

    Index 0 = depot (warehouse). Indices 1..N = barangays in priority order.
    Matrix is symmetric: distance(A→B) == distance(B→A).
    """
    coords = [(depot_lat, depot_lon)] + list(barangay_coords)
    n = len(coords)
    matrix = []

    for i in range(n):
        row = []
        for j in range(n):
            if i == j:
                row.append(0)
            else:
                km = _haversine_km(
                    coords[i][0],
                    coords[i][1],
                    coords[j][0],
                    coords[j][1],
                )
                # Convert to integer decameters (10m precision)
                row.append(int(km * 100))
        matrix.append(row)

    return matrix


# ── Route extraction ──────────────────────────────────────────────────────────


def _extract_routes(
    solution,
    routing,
    manager,
    num_trucks: int,
    barangay_ids: list,
) -> list[list]:
    """
    Parse OR-Tools solution into per-truck stop lists.

    Returns list of lists: each inner list is one truck's barangay IDs
    in the order they should be visited. Depot (index 0) is excluded
    from the returned lists — it's implicit start/end for each truck.
    """
    routes = []
    for truck_idx in range(num_trucks):
        route = []
        index = routing.Start(truck_idx)
        while not routing.IsEnd(index):
            node = manager.IndexToNode(index)
            if node != 0:  # skip depot
                # node - 1 because index 0 is depot, index 1 is barangay_ids[0]
                route.append(barangay_ids[node - 1])
            index = solution.Value(routing.NextVar(index))
        if route:
            routes.append(route)
    return routes


# ── Main solver ───────────────────────────────────────────────────────────────


def solve_cvrp(
    depot_lat: float,
    depot_lon: float,
    scored_barangays: list[dict],
) -> list[dict]:
    """
    Run OR-Tools CVRP and return scored_barangays with delivery_order added.

    Input:  scored_barangays — output from predictor.score_barangays(),
            each dict has barangay_id, latitude, longitude, priority_rank.

    Output: same list with two new fields per barangay:
            - delivery_order (int): global visit sequence across all trucks
            - truck_id (int): which truck (0-indexed) visits this barangay

    If OR-Tools fails to find a solution (shouldn't happen for <20 nodes),
    falls back to priority_rank order — coordinator can still work with that.

    WHY return delivery_order instead of restructuring by truck?
    The frontend allocation table is barangay-centric, not truck-centric.
    The coordinator sees "Mambaling — Truck 1, Stop 2" in the barangay row,
    not a separate truck schedule. Keeps the AllocationResponse schema unchanged.
    """
    if not scored_barangays:
        return scored_barangays

    # Extract barangay coordinates in priority_rank order
    # (highest priority first — OR-Tools will optimize from there)
    ordered = sorted(scored_barangays, key=lambda x: x["priority_rank"])
    barangay_ids = [b["barangay_id"] for b in ordered]
    barangay_coords = [(float(b["latitude"]), float(b["longitude"])) for b in ordered]

    n_locations = len(barangay_ids) + 1  # +1 for depot

    # ── Fallback: if only 1 barangay, no routing needed ──────────────────────
    if len(barangay_ids) == 1:
        scored_barangays[0]["delivery_order"] = 1
        scored_barangays[0]["truck_id"] = 0
        return scored_barangays

    # ── Build distance matrix ─────────────────────────────────────────────────
    distance_matrix = _build_distance_matrix(depot_lat, depot_lon, barangay_coords)

    # ── OR-Tools setup ────────────────────────────────────────────────────────
    # RoutingIndexManager: maps between node indices and location indices
    # num_vehicles = NUM_TRUCKS, depot = index 0
    manager = pywrapcp.RoutingIndexManager(n_locations, NUM_TRUCKS, 0)
    routing = pywrapcp.RoutingModel(manager)

    # Distance callback — OR-Tools calls this to get cost between any two nodes
    def distance_callback(from_index, to_index):
        from_node = manager.IndexToNode(from_index)
        to_node = manager.IndexToNode(to_index)
        return distance_matrix[from_node][to_node]

    transit_callback_index = routing.RegisterTransitCallback(distance_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)

    # ── Demand and capacity constraints ──────────────────────────────────────
    # We use priority_score as a proxy for "demand weight".
    # Higher score = more goods needed = counts more toward truck capacity.
    # This ensures high-priority barangays aren't all assigned to one truck.
    #
    # Capacity = total demand / NUM_TRUCKS (equal theoretical max per truck).
    # Multiply by 1.2 for slack — perfect equal split is rarely feasible
    # given road network constraints.

    # Convert priority scores to integer demands (OR-Tools needs integers)
    demands = [0]  # depot has 0 demand
    for b in ordered:
        demands.append(max(1, int(b["priority_score"])))

    total_demand = sum(demands)
    truck_capacity = max(1, int((total_demand / NUM_TRUCKS) * 1.2))

    def demand_callback(from_index):
        from_node = manager.IndexToNode(from_index)
        return demands[from_node]

    demand_callback_index = routing.RegisterUnaryTransitCallback(demand_callback)
    routing.AddDimensionWithVehicleCapacity(
        demand_callback_index,
        0,  # null slack
        [truck_capacity] * NUM_TRUCKS,  # capacity per truck
        True,  # start cumul at zero
        "Capacity",
    )

    # ── Search parameters ─────────────────────────────────────────────────────
    search_params = pywrapcp.DefaultRoutingSearchParameters()
    search_params.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    )
    search_params.local_search_metaheuristic = (
        routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    )
    search_params.time_limit.seconds = SOLVER_TIME_LIMIT_SECONDS

    # ── Solve ─────────────────────────────────────────────────────────────────
    solution = routing.SolveWithParameters(search_params)

    if not solution:
        # Fallback: no solution found, return input unchanged with default order
        # This shouldn't happen for realistic barangay counts (<30)
        for i, b in enumerate(scored_barangays):
            b["delivery_order"] = b["priority_rank"]
            b["truck_id"] = i % NUM_TRUCKS
        return scored_barangays

    # ── Extract routes and annotate barangays ─────────────────────────────────
    routes = _extract_routes(solution, routing, manager, NUM_TRUCKS, barangay_ids)

    # Build lookup: barangay_id → (truck_id, stop_number_within_truck)
    stop_lookup: dict = {}
    global_order = 1
    for truck_idx, route in enumerate(routes):
        for stop_idx, barangay_id in enumerate(route):
            stop_lookup[str(barangay_id)] = {
                "truck_id": truck_idx,
                "delivery_order": global_order,
            }
            global_order += 1

    # Annotate original scored_barangays list (preserves priority_rank order)
    for b in scored_barangays:
        key = str(b["barangay_id"])
        if key in stop_lookup:
            b["delivery_order"] = stop_lookup[key]["delivery_order"]
            b["truck_id"] = stop_lookup[key]["truck_id"]
        else:
            # Barangay wasn't assigned to any truck (shouldn't happen)
            b["delivery_order"] = b["priority_rank"]
            b["truck_id"] = 0

    return scored_barangays
