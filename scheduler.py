# ============================================
# scheduler.py
# INDUSTRIAL APS REPLANNING ENGINE
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

    "zen10": 2,
    "zen30": 1,
    "zen50": 2,
    "zen70": 2,
    "zen90": 1

}


# ============================================
# GENERATE WORKING DATES
# INCLUDE EXTRA WORKING DAYS
# ============================================

# ============================================
# GENERATE APS CALENDAR
# ============================================

def generate_working_dates(

    start_date,

    actual_df=None,

    previous_plan_df=None
):

    start_date_obj = datetime.strptime(
        start_date,
        "%d-%m-%y"
    )

    first_of_month = start_date_obj.replace(
        day=1
    )

    # ========================================
    # FIND LAST DAY OF MONTH
    # ========================================

    if first_of_month.month == 12:

        next_month = first_of_month.replace(

            year=first_of_month.year + 1,

            month=1,

            day=1
        )

    else:

        next_month = first_of_month.replace(

            month=first_of_month.month + 1,

            day=1
        )

    last_of_month = next_month - timedelta(
        days=1
    )

    # ========================================
    # NORMAL WEEKDAYS
    # ========================================

    working_dates = []

    current_date = first_of_month

    while current_date <= last_of_month:

        if current_date.weekday() < 5:

            working_dates.append(

                current_date.strftime(
                    "%d-%m-%y"
                )
            )

        current_date += timedelta(days=1)

    # ========================================
    # ADD EXTRA ACTUAL DATES
    # ========================================

    if (
        actual_df is not None
        and
        not actual_df.empty
    ):

        for d in actual_df["Date"]:

            if d not in working_dates:

                working_dates.append(d)

    # ========================================
    # ADD EXTRA PLAN DATES
    # ========================================

    if (
        previous_plan_df is not None
        and
        not previous_plan_df.empty
    ):

        for d in previous_plan_df["Date"]:

            if d not in working_dates:

                working_dates.append(d)

    # ========================================
    # SORT
    # ========================================

    working_dates = sorted(

        list(set(working_dates)),

        key=lambda x: datetime.strptime(
            x,
            "%d-%m-%y"
        )
    )

    return working_dates

# ============================================
# EMPTY CHECK
# ============================================

def is_empty(df):

    if df is None:
        return True

    if len(df) == 0:
        return True

    return False


# ============================================
# MAIN APS FUNCTION
# ============================================

def run_scheduler(

    material_df,

    targets_df,

    actual_df,

    previous_plan_df,

    start_date,

    replan_date

):

    # ========================================
    # PRODUCTS
    # ========================================

    products = targets_df[
        "Product"
    ].tolist()

    # ========================================
    # WORKING DATES
    # ========================================

    working_dates = generate_working_dates(

        start_date,

        actual_df,

        previous_plan_df

    )

    # ========================================
    # PAST + FUTURE DATES
    # ========================================

    past_dates = []

    future_dates = []

    for d in working_dates:
        datetime.strptime(d, "%d-%m-%y")

        if d < replan_date:

            past_dates.append(d)

        else:

            future_dates.append(d)

    # ========================================
    # TARGETS
    # ========================================

    targets = {}

    for _, row in targets_df.iterrows():

        targets[row["Product"]] = int(
            row["Target_Qty"]
        )


    # ========================================
# PRIORITIES
# ========================================

    

    priorities = {}

    for _, row in targets_df.iterrows():

        priorities[row["Product"]] = int(
            row["Priority"]
        )

    # ========================================
    # MATERIALS
    # ========================================

    materials = material_df[
        "Material"
    ].tolist()

    material_usage = {}

    material_stock = {}

    for _, row in material_df.iterrows():

        material = row["Material"]

        material_stock[material] = int(
            row["Available_Qty"]
        )

        material_usage[material] = {}

        for p in products:

            material_usage[material][p] = int(
                row[p]
            )

    # ========================================
    # ACTUAL PRODUCTION
    # ========================================

    actual_dict = {}

    if not is_empty(actual_df):

        for _, row in actual_df.iterrows():

            date = row["Date"]

            actual_dict[date] = {}

            for p in products:

                actual_dict[date][p] = int(
                    row[p]
                )

    # ========================================
    # PREVIOUS PLAN
    # ========================================

    previous_plan = {}

    if not is_empty(previous_plan_df):

        for _, row in previous_plan_df.iterrows():

            date = row["Date"]

            previous_plan[date] = {}

            for p in products:

                previous_plan[date][p] = int(
                    row[p]
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
    # APPLY ACTUAL CONSUMPTION
    # ========================================

    for d in past_dates:

        if d not in actual_dict:
            continue

        for p in products:

            qty = actual_dict[d][p]

            for material in materials:

                usage = material_usage[
                    material
                ][p]

                material_stock[material] -= (

                    qty * usage

                )

    # ========================================
    # APPLY PAST ARRIVALS
    # ========================================

    for arrival_date in arrivals:

        if arrival_date >= replan_date:
            continue

        for material in arrivals[arrival_date]:

            material_stock[material] += (

                arrivals[arrival_date][material]

            )

    # ========================================
    # REMAINING TARGETS
    # ========================================

    remaining_targets = {}

    for p in products:

        actual_done = 0

        for d in past_dates:

            if d in actual_dict:

                actual_done += (
                    actual_dict[d][p]
                )

        remaining_targets[p] = max(

            0,

            targets[p] - actual_done

        )

    # ========================================
    # MATERIAL AVAILABILITY
    # ========================================

    material_available = {}

    for material in materials:

        material_available[material] = {}

        cumulative = material_stock[
            material
        ]

        for d in future_dates:

            if (

                d in arrivals

                and material in arrivals[d]

            ):

                cumulative += (
                    arrivals[d][material]
                )

            material_available[
                material
            ][d] = cumulative

    # ========================================
    # CREATE MODEL
    # ========================================

    model = cp_model.CpModel()

    # ========================================
    # VARIABLES
    # ========================================

    x = {}

    for p in products:

        for d in future_dates:

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

        for d in future_dates:

            y[p, d] = model.NewBoolVar(
                f"y_{p}_{d}"
            )

    # ========================================
    # LINK x AND y
    # ========================================

    for p in products:

        for d in future_dates:

            model.Add(

                x[p, d]

                <= product_max[p] * y[p, d]
            )

            model.Add(

                x[p, d]

                >= y[p, d]

            )

    # ========================================
    # STABILITY
    # ========================================

    schedule_changes = []

    if not is_empty(previous_plan_df):

        for p in products:

            for d in future_dates:

                if d not in previous_plan:
                    continue

                old_qty = previous_plan[d][p]

                change = model.NewIntVar(

                        0,

                        product_max[p],

                        f"change_{p}_{d}"

                        )

                model.AddAbsEquality(

                    change,

                    x[p, d] - old_qty

                )

                schedule_changes.append(
                    change
                )

    # ========================================
    # TARGET CONSTRAINTS
    # ========================================

    for p in products:

        model.Add(

            sum(

                x[p, d]

                for d in future_dates

            )

            <= remaining_targets[p]

        )

    # ========================================
    # DAILY CAPACITY
    # ========================================

    for d in future_dates:

        model.Add(

            sum(

                x[p, d]

                for p in products

            )

            <= MAX_SYSTEMS_PER_DAY

        )

    # ========================================
    # PRODUCT DIVERSITY
    # ========================================

    for d in future_dates:

        model.Add(

            sum(

                y[p, d]

                for p in products

            )

            <= MAX_PRODUCTS_PER_DAY

        )

    # ========================================
    # PRODUCT SMOOTHING
    # ========================================

    for p in products:

        for i in range(
            1,
            len(future_dates)
        ):

            d1 = future_dates[i - 1]

            d2 = future_dates[i]

            model.Add(

                x[p, d2]
                - x[p, d1]

                <= 1

            )

            model.Add(

                x[p, d1]
                - x[p, d2]

                <= 1

            )

    # ========================================
    # MATERIAL CONSTRAINTS
    # ========================================

    for material in materials:

        for i, current_day in enumerate(
            future_dates
        ):

            consumption_terms = []

            for p in products:

                usage = material_usage[
                    material
                ][p]

                if usage > 0:

                    for d in future_dates[
                        :i + 1
                    ]:

                        consumption_terms.append(

                            x[p, d] * usage

                        )

            model.Add(

                sum(consumption_terms)

                <= material_available[
                    material
                ][current_day]

            )

    # ========================================
    # DAILY LOAD
    # ========================================

    daily_load = {}

    for d in future_dates:

        daily_load[d] = model.NewIntVar(

            0,

            MAX_SYSTEMS_PER_DAY,

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

    for i in range(
        1,
        len(future_dates)
    ):

        d1 = future_dates[i - 1]

        d2 = future_dates[i]

        diff = model.NewIntVar(

            0,

            MAX_SYSTEMS_PER_DAY,

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

        for d in future_dates
    )

    # ========================================
    # OBJECTIVE
    # ========================================

    total_production = sum(

        x[p, d]

        for p in products

        for d in future_dates

    )

    diversity_score = sum(

        y[p, d]

        for p in products

        for d in future_dates

    )

    model.Maximize(

          priority_score * 10

        + total_production

        + DIVERSITY_WEIGHT
        * diversity_score

        - SMOOTHNESS_WEIGHT
        * sum(diffs)

        - STABILITY_WEIGHT
        * sum(schedule_changes)

    )

    # ========================================
    # SOLVE
    # ========================================

    solver = cp_model.CpSolver()

    solver.parameters.random_seed = 4

    solver.parameters.max_time_in_seconds = 60

    solver.parameters.num_search_workers = 4

    status = solver.Solve(model)

    # ========================================
    # NO SOLUTION
    # ========================================

    if status not in [

        cp_model.OPTIMAL,

        cp_model.FEASIBLE

    ]:

        return None, None, None

    # ========================================
    # FINAL PLAN
    # ========================================
    
    final_schedule = []

    # PAST ACTUALS

    for d in past_dates:

        row = {
            "Date": d
        }

        total = 0

        if d in actual_dict:

            for p in products:

                qty = actual_dict[d][p]

                row[p] = qty

                total += qty

        row["Total"] = total

        final_schedule.append(row)

    # FUTURE PLAN

    for d in future_dates:

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

        final_schedule.append(row)

    schedule_df = pd.DataFrame(
        final_schedule
    )

    



    # ========================================
    # MATERIAL STATUS
    # ========================================

    material_status = []

    for material in materials:

        total_used = 0

        for p in products:

            usage = material_usage[
                material
            ][p]

            produced_qty = schedule_df[
                p
            ].sum()

            total_used += (
                produced_qty * usage
            )

        final_available = (
            material_available[
                material
            ][future_dates[-1]]
        )

        remaining = (
            final_available
            - total_used
        )

        material_status.append({

            "Material": material,

            "Available": final_available,

            "Used": total_used,

            "Remaining": remaining

        })

    material_df_output = pd.DataFrame(
        material_status
    )

    # ========================================
    # TARGET STATUS
    # ========================================

    target_status = []

    for p in products:

        planned = schedule_df[p].sum()

        remaining = (
            targets[p]
            - planned
        )

        target_status.append({

            "Product": p,

            "Target": targets[p],

            "Planned": planned,

            "Remaining": remaining

        })

    target_df = pd.DataFrame(
        target_status
    )

    return schedule_df

        
def check_csv(df):
    # read_csv will raise an EmptyDataError if the file is completely blank (0 bytes)
        
    if df.empty:
        return True  # File has headers but no data rows
    else:
        return False  # File has data
    
        