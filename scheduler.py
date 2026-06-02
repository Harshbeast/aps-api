
# ============================================
# scheduler.py
# ============================================

import pandas as pd
from ortools.sat.python import cp_model
from datetime import datetime, timedelta

# ============================================
# CONFIGURATION
# ============================================

MAX_SYSTEMS_PER_DAY = 6
MAX_PRODUCTS_PER_DAY = 6
DIVERSITY_WEIGHT = 2
SMOOTHNESS_WEIGHT = 1
STABILITY_WEIGHT = 1

product_max = {
    "zen10": 2, "zen30": 1, "zen50": 2, "zen70": 2, "zen90": 1
}


def generate_working_dates(start_date, actual_df=None, previous_plan_df=None):
    start_date_obj = datetime.strptime(start_date, "%d-%m-%y")
    first_day_of_month = start_date_obj.replace(day=1)

    # Planning Period: 28th Prev Month → 27th Current Month
    if first_day_of_month.month == 1:
        planning_start = first_day_of_month.replace(year=first_day_of_month.year - 1, month=12, day=28)
    else:
        planning_start = first_day_of_month.replace(month=first_day_of_month.month - 1, day=28)

    planning_end = first_day_of_month.replace(day=27)

    working_dates = []
    current = planning_start
    while current <= planning_end:
        if current.weekday() < 5:
            working_dates.append(current.strftime("%d-%m-%y"))
        current += timedelta(days=1)

    # Add dates from actual and previous plan
    extra = set()
    if actual_df is not None and not actual_df.empty:
        extra.update(actual_df["Date"].astype(str).tolist())
    if previous_plan_df is not None and not previous_plan_df.empty:
        extra.update(previous_plan_df["Date"].astype(str).tolist())

    working_dates.extend([d for d in extra if d not in working_dates])

    # Sort chronologically
    working_dates = sorted(list(set(working_dates)), 
                          key=lambda x: datetime.strptime(x, "%d-%m-%y"))
    return working_dates


def is_empty(df):
    return df is None or df.empty


def run_scheduler(material_df, targets_df, actual_df, previous_plan_df, start_date, replan_date):
    products = targets_df["Product"].tolist()

    working_dates = generate_working_dates(start_date, actual_df, previous_plan_df)

    # === CRITICAL FIX: Strict Past / Future Split ===
    replan_dt = datetime.strptime(replan_date, "%d-%m-%y")
    
    past_dates = []
    future_dates = []
    for d in working_dates:
        d_dt = datetime.strptime(d, "%d-%m-%y")
        if d_dt < replan_dt:
            past_dates.append(d)
        else:
            future_dates.append(d)

    # Targets & Priorities
    targets = {row["Product"]: int(row["Target_Qty"]) for _, row in targets_df.iterrows()}
    priorities = {row["Product"]: int(row["Priority"]) for _, row in targets_df.iterrows()}

    # Materials
    materials = material_df["Material"].tolist()
    material_stock = {row["Material"]: int(row["Available_Qty"]) for _, row in material_df.iterrows()}
    material_usage = {row["Material"]: {p: int(row[p]) for p in products} 
                      for _, row in material_df.iterrows()}

    # Actual Production Dictionary
    actual_dict = {}
    if not is_empty(actual_df):
        for _, row in actual_df.iterrows():
            date = str(row["Date"])
            actual_dict[date] = {p: int(row[p]) for p in products}

    # Previous Plan
    previous_plan = {}
    if not is_empty(previous_plan_df):
        for _, row in previous_plan_df.iterrows():
            date = str(row["Date"])
            previous_plan[date] = {p: int(row[p]) for p in products}

    # Arrivals
    arrivals = {}
    for _, row in material_df.iterrows():
        if pd.isna(row.get("Incoming_Qty")) or pd.isna(row.get("Date")):
            continue
        day = str(row["Date"])
        mat = row["Material"]
        qty = int(row["Incoming_Qty"])
        arrivals.setdefault(day, {})[mat] = arrivals.get(day, {}).get(mat, 0) + qty

    # Apply Actual Consumption (Past)
    for d in past_dates:
        if d in actual_dict:
            for p in products:
                qty = actual_dict[d][p]
                for mat in materials:
                    material_stock[mat] -= qty * material_usage[mat][p]

    # Apply Past Arrivals
    for day in list(arrivals.keys()):
        if datetime.strptime(day, "%d-%m-%y") < replan_dt:
            for mat in arrivals[day]:
                material_stock[mat] += arrivals[day][mat]

    # Remaining Targets
    remaining_targets = {}
    for p in products:
        done = sum(actual_dict.get(d, {}).get(p, 0) for d in past_dates)
        remaining_targets[p] = max(0, targets[p] - done)

    # Material Availability for Future Dates
    material_available = {}
    for mat in materials:
        material_available[mat] = {}
        cum = material_stock[mat]
        for d in future_dates:
            if d in arrivals and mat in arrivals[d]:
                cum += arrivals[d][mat]
            material_available[mat][d] = cum

    # ========================================
    # CP MODEL
    # ========================================
    model = cp_model.CpModel()

    x = {(p, d): model.NewIntVar(0, product_max[p], f"x_{p}_{d}") 
         for p in products for d in future_dates}
    y = {(p, d): model.NewBoolVar(f"y_{p}_{d}") 
         for p in products for d in future_dates}

    for p in products:
        for d in future_dates:
            model.Add(x[p, d] <= product_max[p] * y[p, d])
            model.Add(x[p, d] >= y[p, d])

    # Stability
    schedule_changes = []
    if not is_empty(previous_plan_df):
        for p in products:
            for d in future_dates:
                if d in previous_plan:
                    old = previous_plan[d][p]
                    change = model.NewIntVar(0, product_max[p], f"ch_{p}_{d}")
                    model.AddAbsEquality(change, x[p, d] - old)
                    schedule_changes.append(change)

    # Targets
    for p in products:
        model.Add(sum(x[p, d] for d in future_dates) <= remaining_targets[p])

    # Daily Constraints
    for d in future_dates:
        model.Add(sum(x[p, d] for p in products) <= MAX_SYSTEMS_PER_DAY)
        model.Add(sum(y[p, d] for p in products) <= MAX_PRODUCTS_PER_DAY)

    # Smoothing
    for p in products:
        for i in range(1, len(future_dates)):
            d1, d2 = future_dates[i-1], future_dates[i]
            model.Add(x[p, d2] - x[p, d1] <= 1)
            model.Add(x[p, d1] - x[p, d2] <= 1)

    # Material Constraints
    for mat in materials:
        for i, day in enumerate(future_dates):
            consumption = [
                x[prod, d] * material_usage[mat][prod]
                for prod in products if material_usage[mat][prod] > 0
                for d in future_dates[:i+1]
            ]
            model.Add(sum(consumption) <= material_available[mat][day])

    # Load & Smoothness
    daily_load = {d: model.NewIntVar(0, MAX_SYSTEMS_PER_DAY, f"load_{d}") for d in future_dates}
    for d in future_dates:
        model.Add(daily_load[d] == sum(x[p, d] for p in products))

    diffs = []
    for i in range(1, len(future_dates)):
        d1, d2 = future_dates[i-1], future_dates[i]
        diff = model.NewIntVar(0, MAX_SYSTEMS_PER_DAY, f"diff_{i}")
        model.AddAbsEquality(diff, daily_load[d2] - daily_load[d1])
        diffs.append(diff)

    # Objective
    model.Maximize(
        sum(x[p, d] * priorities[p] for p in products for d in future_dates) * 10 +
        sum(x[p, d] for p in products for d in future_dates) +
        DIVERSITY_WEIGHT * sum(y[p, d] for p in products for d in future_dates) -
        SMOOTHNESS_WEIGHT * sum(diffs) -
        STABILITY_WEIGHT * sum(schedule_changes)
    )

    solver = cp_model.CpSolver()
    solver.parameters.random_seed = 4
    solver.parameters.max_time_in_seconds = 60
    solver.parameters.num_search_workers = 4

    status = solver.Solve(model)

    if status not in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        return None, None, None

    # ========================================
    # BUILD OUTPUT
    # ========================================
    final_schedule = []

    # Past Dates → Use Actuals (MUST be fixed)
    for d in past_dates:
        row = {"Date": d}
        total = 0
        if d in actual_dict:
            for p in products:
                qty = actual_dict[d][p]
                row[p] = qty
                total += qty
        else:
            for p in products:
                row[p] = 0
        row["Total"] = total
        final_schedule.append(row)

    # Future Dates → Optimized Plan
    for d in future_dates:
        row = {"Date": d}
        total = 0
        for p in products:
            qty = solver.Value(x[p, d])
            row[p] = qty
            total += qty
        row["Total"] = total
        final_schedule.append(row)

    schedule_df = pd.DataFrame(final_schedule)

    # Ensure correct order
    schedule_df['Date_dt'] = pd.to_datetime(schedule_df['Date'], format="%d-%m-%y")
    schedule_df = schedule_df.sort_values('Date_dt').drop(columns=['Date_dt']).reset_index(drop=True)

    return schedule_df  # if you are new developer you can expand material/target status it is base code used for scheduling from 28 to 27