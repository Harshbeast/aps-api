import pandas as pd
from ortools.sat.python import cp_model
from datetime import datetime, timedelta
from collections import defaultdict

max_systems_per_day = 5
diversity_weight = 2
preferred_daily = 5
smoothness_weight = 1
max_products_per_day = 5
target_daily_weight = 1
earliness_weight = 12

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

    # ========================================
    # ARRIVALS - Robust handling of comma-separated values
    # ========================================
    
    # ========================================
    # ARRIVALS - Robust Date Parsing (Fixed)
    # ========================================
    arrivals = defaultdict(lambda: defaultdict(int))

    for _, row in material_df.iterrows():
        mat = str(row["Material"]).strip()
        if not mat:
            continue
            
        qty_str = str(row.get("Incoming_Qty", "")).strip()
        date_str = str(row.get("Date", "")).strip()
        
        if qty_str in ["", "0", "nan", "NaN", "0.0"] or date_str in ["", "nan", "NaN"]:
            continue
        
        date_list = [d.strip() for d in date_str.split(",") if d.strip()]
        qty_list = [q.strip() for q in qty_str.split(",") if q.strip()]
        
        for d_text, q_text in zip(date_list, qty_list):
            try:
                qty = int(float(q_text))   # handles cases like 5.0
                if qty <= 0:
                    continue
                    
                # Try multiple common date formats
                parsed = False
                for fmt in ["%d-%m-%y", "%d-%m-%Y", "%d/%m/%y", "%d/%m/%Y", "%d.%m.%y", "%d.%m.%Y"]:
                    try:
                        dt = datetime.strptime(d_text, fmt)
                        standardized_day = dt.strftime("%d-%m-%y")   # Must match working_dates format
                        arrivals[standardized_day][mat] += qty
                        parsed = True
                        break
                    except ValueError:
                        continue
                        
                if not parsed:
                    print(f"Warning: Could not parse date '{d_text}' for material '{mat}'")
                    
            except Exception as e:
                print(f"Warning: Error parsing arrival for {mat} on '{d_text}': {e}")

    # ========================================
    # MATERIAL AVAILABILITY (Cumulative)
    # ========================================

    # ========================================
    # MATERIAL AVAILABILITY (Cumulative + Weekend Handling)
    # ========================================
    material_available = {}

    # Create a full calendar date list (including weekends) for proper cumulative stock
    full_calendar = []
    current = planning_start
    while current <= planning_end:
        full_calendar.append(current.strftime("%d-%m-%y"))
        current += timedelta(days=1)

    # Build cumulative availability considering ALL days (including weekends)
    for mat in materials:
        material_available[mat] = {}
        cum = material_stock.get(mat, 0)
        
        # Track last working day
        last_working_day = None
        
        for day_str in full_calendar:
            # Add arrival if any (even on weekends)
            if day_str in arrivals and mat in arrivals[day_str]:
                cum += arrivals[day_str][mat]
            
            # If this is a working day, record the current cumulative stock
            dt = datetime.strptime(day_str, "%d-%m-%y")
            if dt.weekday() < 5:   # Monday to Friday
                material_available[mat][day_str] = cum
                last_working_day = day_str
        
        # Fill any missing working days (edge case safety)
        for wd in working_dates:
            if wd not in material_available[mat]:
                material_available[mat][wd] = cum
    # material_available = {}

    # for mat in materials:
    #     material_available[mat] = {}
    #     cum = material_stock.get(mat, 0)
        
    #     for day in working_dates:
    #         if day in arrivals and mat in arrivals[day]:
    #             cum += arrivals[day][mat]
    #         material_available[mat][day] = cum
    # arrivals = {}
    # for _, row in material_df.iterrows():
    #     if pd.isna(row["Incoming_Qty"]) or pd.isna(row["Date"]):
    #         continue
    #     day = str(row["Date"])
    #     mat = row["Material"]
    #     qty = int(row["Incoming_Qty"])
    #     arrivals.setdefault(day, {})[mat] = arrivals.get(day, {}).get(mat, 0) + qty



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

    is_good_day = {d: model.NewBoolVar(f"good_{d}") for d in working_dates}
    for d in working_dates:
        # is_good_day = 1 if daily_load[d] >= preferred_daily
        model.Add(daily_load[d] >= preferred_daily).OnlyEnforceIf(is_good_day[d])
        model.Add(daily_load[d] < preferred_daily).OnlyEnforceIf(is_good_day[d].Not())

    diffs = []
    for i in range(1, len(working_dates)):
        d1, d2 = working_dates[i-1], working_dates[i]
        diff = model.NewIntVar(0, max_systems_per_day, f"diff_{i}")
        model.AddAbsEquality(diff, daily_load[d2] - daily_load[d1])
        diffs.append(diff)

    # Objective
    total_production = sum(x[p, d] for p in products for d in working_dates)
    total_priority = sum(x[p, d] * priorities[p] for p in products for d in working_dates)
    diversity = sum(y[p, d] for p in products for d in working_dates)
    good_days = sum(is_good_day[d] for d in working_dates)
    daily_capacity_score = sum(daily_load[d] for d in working_dates)
    # Create decreasing weight for each day (earlier days = higher weight)
    day_weights = {}
    n_days = len(working_dates)
    for i, d in enumerate(working_dates):
        # Linear decreasing weight: first day gets highest, last day gets lowest
        weight = n_days - i                    # e.g., 25, 24, ..., 1
        day_weights[d] = weight

    earliness_bonus = sum(
        x[p, d] * day_weights[d] for p in products for d in working_dates
    )

    model.Maximize(
        # daily_capacity_score*2 +
        # target_daily_weight * preferred_daily +           
        total_priority  +
        total_production +
        diversity_weight * diversity 
        + earliness_weight * earliness_bonus
         - smoothness_weight * sum(diffs)
    )

    # Solve
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 4
    solver.parameters.random_seed = 4
    solver.parameters.max_time_in_seconds = 90

    status = solver.Solve(model)

    if status not in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        return None

    # ========================================
    # CREATE OUTPUT WITH PROPER SORTING
    # ========================================
    production_plan = []
    for d in working_dates:          
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

    # return df

    # ========================================
    # MATERIAL STATUS
    # ========================================
    material_status = []
    for material in materials:
        total_used = sum(df[p].sum() * material_usage[material][p] for p in products)
        final_available = material_available[material][working_dates[-1]] if working_dates else 0
        remaining = final_available - total_used

        material_status.append({
            "Material": material,
            "Available": final_available,
            "Used": total_used,
            "Remaining": remaining
        })

    material_df_output = pd.DataFrame(material_status)

    # ========================================
    # TARGET STATUS
    # ========================================
    target_status = []
    for p in products:
        planned = df[p].sum()
        target_status.append({
            "Product": p,
            "Target": targets[p],
            "Planned": planned,
            "Remaining": targets[p] - planned
        })

    target_df = pd.DataFrame(target_status)

    return df, material_df_output, target_df   # Note: returning 3 values now