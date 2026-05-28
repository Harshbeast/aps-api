# ============================================
# CREATE APS SCHEDULE FUNCTION
# ============================================

import pandas as pd

from ortools.sat.python import cp_model

from datetime import datetime, timedelta



max_systems_per_day = 6
diversity_weight = 1
smoothness_weight = 1
max_products_per_day = 6

# ========================================
# PRODUCT-WISE MAX LIMITS
# ========================================

product_max = {

    "zen10": 2,
    "zen30": 1,
    "zen50": 2,
    "zen70": 2,
    "zen90": 2

}


def create_schedule(

    material_df,
    
    targets_df,
    
    start_date

):

    # ========================================
    # PRODUCTS
    # ========================================

    products = targets_df["Product"].tolist()

    # ========================================
    # GENERATE WORKING DATES
    # ========================================

    start_date_obj = datetime.strptime(
        start_date,
        "%d-%m-%y"
    )

    

# ========================================
# CALCULATE WORKING DAYS OF MONTH
# ========================================

    first_day = start_date_obj.replace(day=1)

    if first_day.month == 12:

        next_month = first_day.replace(
            year=first_day.year + 1,
            month=1,
            day=1
        )

    else:

        next_month = first_day.replace(
            month=first_day.month + 1,
            day=1
        )

    last_day = next_month - timedelta(days=1)

    working_dates = []

    current_date = first_day

    while current_date <= last_day:

        # Monday-Friday
        if current_date.weekday() < 5:

            working_dates.append(
                current_date.strftime("%d-%m-%y")
            )

        current_date += timedelta(days=1)

    working_days = len(working_dates)

    # ========================================
    # TARGET DICTIONARY
    # ========================================

    targets = {}

    for _, row in targets_df.iterrows():

        targets[row["Product"]] = int(
            row["Target_Qty"]
        )

    priorities = {}

    for _, row in targets_df.iterrows():

        priorities[row["Product"]] = int(
            row["Priority"]
        )

    # ========================================
    # MATERIAL DATA
    # ========================================

    materials = material_df["Material"].tolist()

    material_usage = {}

    material_stock = {}

    for _, row in material_df.iterrows():

        material = row["Material"]

        material_stock[material] = int(
            row["Available_Qty"]
        )

        material_usage[material] = {}

        for product in products:

            material_usage[material][product] = int(
                row[product]
            )


    
    # ========================================
    # ARRIVALS DICTIONARY
    # ========================================

    arrivals = {}

    for _, row in material_df.iterrows():

        incoming_qty = row["Incoming_Qty"]

        arrival_date = row["Date"]

        # SKIP EMPTY ARRIVALS
        if pd.isna(incoming_qty) or pd.isna(arrival_date):
            continue

        qty = int(incoming_qty)

        day = str(arrival_date)

        material = row["Material"]

        if day not in arrivals:

            arrivals[day] = {}

        arrivals[day][material] = (

            arrivals[day].get(material, 0)

            + qty
        )

    # ========================================
    # MATERIAL AVAILABILITY TIMELINE
    # ========================================

    material_available = {}

    for material in materials:

        material_available[material] = {}

        cumulative = material_stock[material]

        for day in working_dates:

            if (

                day in arrivals

                and material in arrivals[day]

            ):

                cumulative += arrivals[day][material]

            material_available[material][day] = cumulative

    # ========================================
    # CREATE MODEL
    # ========================================

    model = cp_model.CpModel()

    # ========================================
    # DECISION VARIABLES
    # ========================================

    x = {}

    for p in products:

        for d in working_dates:

            x[p, d] = model.NewIntVar(

                        0,

                        product_max[p],

                        f"x_{p}_{d}"
                    )

    # ========================================
    # BINARY VARIABLES
    # ========================================

    y = {}

    for p in products:

        for d in working_dates:

            y[p, d] = model.NewBoolVar(

                f"y_{p}_{d}"
            )

    # ========================================
    # LINK x AND y
    # ========================================

    for p in products:

        for d in working_dates:

            model.Add(

                x[p, d]

                <= product_max[p] * y[p, d]
                    )

            model.Add(

                x[p, d]

                >= y[p, d]
            )

    # ========================================
    # MONTHLY TARGET CONSTRAINTS
    # ========================================

    for p in products:

        model.Add(

            sum(

                x[p, d]

                for d in working_dates

            )

            <= targets[p]
        )

    # ========================================
    # DAILY FACTORY CAPACITY
    # ========================================

    for d in working_dates:

        model.Add(

            sum(

                x[p, d]

                for p in products

            )

            <= max_systems_per_day
        )

    # ========================================
    # MAX PRODUCTS PER DAY
    # ========================================

    for d in working_dates:

        model.Add(

            sum(

                y[p, d]

                for p in products

            )

            <= max_products_per_day
        )

    # ========================================
    # PRODUCT SMOOTHING
    # ========================================

    for p in products:

        for i in range(1, len(working_dates)):

            d1 = working_dates[i - 1]

            d2 = working_dates[i]

            model.Add(

                x[p, d2] - x[p, d1]

                <= 1
            )

            model.Add(

                x[p, d1] - x[p, d2]

                <= 1
            )

    # ========================================
    # MATERIAL CONSTRAINTS
    # ========================================

    for material in materials:

        for i, current_day in enumerate(working_dates):

            consumption_terms = []

            for product in products:

                usage = material_usage[material][product]

                if usage > 0:

                    for d in working_dates[:i + 1]:

                        consumption_terms.append(

                            x[product, d] * usage
                        )

            model.Add(

                sum(consumption_terms)

                <= material_available[material][current_day]
            )

    # ========================================
    # DAILY LOAD
    # ========================================

    daily_load = {}

    for d in working_dates:

        daily_load[d] = model.NewIntVar(

            0,

            max_systems_per_day,

            f"load_{d}"
        )

        model.Add(

            daily_load[d]

            == sum(

                x[p, d]

                for p in products
            )
        )

    # ========================================
    # LOAD SMOOTHNESS
    # ========================================

    diffs = []

    for i in range(1, len(working_dates)):

        d1 = working_dates[i - 1]

        d2 = working_dates[i]

        diff = model.NewIntVar(

            0,

            max_systems_per_day,

            f"diff_{i}"
        )

        model.AddAbsEquality(

            diff,

            daily_load[d2]

            - daily_load[d1]
        )

        diffs.append(diff)


    # ========================================
    # PRIORITY SCORE
    # ========================================

    priority_score = sum(

        x[p, d] * priorities[p]

        for p in products

        for d in working_dates
    )

    # ========================================
    # OBJECTIVE
    # ========================================

    total_production = sum(

        x[p, d]

        for p in products

        for d in working_dates
    )

    diversity_score = sum(

        y[p, d]

        for p in products

        for d in working_dates
    )

    model.Maximize(
        priority_score

        + total_production

        + diversity_weight * diversity_score

        - smoothness_weight * sum(diffs)
    )

    # ========================================
    # SOLVE
    # ========================================

    solver = cp_model.CpSolver()

    solver.parameters.num_search_workers = 2
    solver.parameters.random_seed = 4

    solver.parameters.max_time_in_seconds = 60

    status = solver.Solve(model)

    # ========================================
    # OUTPUT
    # ========================================

    if status not in [

        cp_model.OPTIMAL,

        cp_model.FEASIBLE
    ]:

        return None

    production_plan = []

    for d in working_dates:

        row = {
            "Date": d
        }

        total = 0

        for p in products:

            qty = solver.Value(
                x[p, d]
            )

            row[p] = qty

            total += qty

        row["Total"] = total

        production_plan.append(row)

    output_df = pd.DataFrame(
        production_plan
    )

    return output_df