import pandas as pd
from ortools.sat.python import cp_model
from datetime import datetime, timedelta

max_systems_per_day = 6
diversity_weight = 1
smoothness_weight = 1
max_products_per_day = 6

product_max = {
    "zen10": 2, "zen30": 1, "zen50": 2, "zen70": 2, "zen90": 2
}


def create_schedule(material_df, targets_df, start_date):
    products = targets_df["Product"].tolist()

    # Parse target month
    start_date_obj = datetime.strptime(start_date, "%d-%m-%y")
    first_day_of_month = start_date_obj.replace(day=1)

    # Planning Period: 28th Prev Month → 27th Current Month
    if first_day_of_month.month == 1:
        planning_start = first_day_of_month.replace(year=first_day_of_month.year - 1, month=12, day=28)
    else:
        planning_start = first_day_of_month.replace(month=first_day_of_month.month - 1, day=28)

    planning_end = first_day_of_month.replace(day=27)

    # Generate working dates (Mon-Fri)
    working_dates = []
    current = planning_start
    while current <= planning_end:
        if current.weekday() < 5:
            working_dates.append(current.strftime("%d-%m-%y"))
        current += timedelta(days=1)

    # ========================================
    # Rest of your data preparation (targets, materials, arrivals...)
    # ========================================
    targets = {row["Product"]: int(row["Target_Qty"]) for _, row in targets_df.iterrows()}
    priorities = {row["Product"]: int(row["Priority"]) for _, row in targets_df.iterrows()}

    materials = material_df["Material"].tolist()
    material_stock = {row["Material"]: int(row["Available_Qty"]) for _, row in material_df.iterrows()}
    material_usage = {row["Material"]: {p: int(row[p]) for p in products} for _, row in material_df.iterrows()}

    arrivals = {}
    for _, row in material_df.iterrows():
        if pd.isna(row["Incoming_Qty"]) or pd.isna(row["Date"]):
            continue
        day = str(row["Date"])
        mat = row["Material"]
        qty = int(row["Incoming_Qty"])
        arrivals.setdefault(day, {})[mat] = arrivals.get(day, {}).get(mat, 0) + qty

    # Material Availability
    material_available = {}
    for mat in materials:
        material_available[mat] = {}
        cum = material_stock[mat]
        for day in working_dates:
            if day in arrivals and mat in arrivals[day]:
                cum += arrivals[day][mat]
            material_available[mat][day] = cum

    # ========================================
    # CP MODEL (same as before)
    # ========================================
    model = cp_model.CpModel()

    x = {(p, d): model.NewIntVar(0, product_max[p], f"x_{p}_{d}") for p in products for d in working_dates}
    y = {(p, d): model.NewBoolVar(f"y_{p}_{d}") for p in products for d in working_dates}

    for p in products:
        for d in working_dates:
            model.Add(x[p, d] <= product_max[p] * y[p, d])
            model.Add(x[p, d] >= y[p, d])

    for p in products:
        model.Add(sum(x[p, d] for d in working_dates) <= targets[p])

    for d in working_dates:
        model.Add(sum(x[p, d] for p in products) <= max_systems_per_day)
        model.Add(sum(y[p, d] for p in products) <= max_products_per_day)

    for p in products:
        for i in range(1, len(working_dates)):
            d1, d2 = working_dates[i-1], working_dates[i]
            model.Add(x[p, d2] - x[p, d1] <= 1)
            model.Add(x[p, d1] - x[p, d2] <= 1)

    for mat in materials:
        for i, day in enumerate(working_dates):
            consumption = [
                x[prod, d] * material_usage[mat][prod]
                for prod in products
                if material_usage[mat][prod] > 0
                for d in working_dates[:i+1]
            ]
            model.Add(sum(consumption) <= material_available[mat][day])

    daily_load = {d: model.NewIntVar(0, max_systems_per_day, f"load_{d}") for d in working_dates}
    for d in working_dates:
        model.Add(daily_load[d] == sum(x[p, d] for p in products))

    diffs = []
    for i in range(1, len(working_dates)):
        d1, d2 = working_dates[i-1], working_dates[i]
        diff = model.NewIntVar(0, max_systems_per_day, f"diff_{i}")
        model.AddAbsEquality(diff, daily_load[d2] - daily_load[d1])
        diffs.append(diff)

    # Objective
    model.Maximize(
        sum(x[p, d] * priorities[p] for p in products for d in working_dates) +
        sum(x[p, d] for p in products for d in working_dates) +
        diversity_weight * sum(y[p, d] for p in products for d in working_dates) -
        smoothness_weight * sum(diffs)
    )

    # Solve
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 2
    solver.parameters.random_seed = 4
    solver.parameters.max_time_in_seconds = 60

    status = solver.Solve(model)

    if status not in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        return None

    # ========================================
    # CREATE OUTPUT WITH PROPER SORTING
    # ========================================
    production_plan = []
    for d in working_dates:          # This is already in correct chronological order
        row = {"Date": d}
        total = 0
        for p in products:
            qty = solver.Value(x[p, d])
            row[p] = qty
            total += qty
        row["Total"] = total
        production_plan.append(row)

    df = pd.DataFrame(production_plan)

    # === IMPORTANT: Convert to datetime and sort ===
    df['Date_dt'] = pd.to_datetime(df['Date'], format="%d-%m-%y")
    df = df.sort_values('Date_dt').drop(columns=['Date_dt'])

    return df