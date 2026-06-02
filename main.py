from fastapi import FastAPI
import pandas as pd
import numpy as np
from creater import create_schedule
from scheduler import run_scheduler
from datetime import datetime, timedelta
import traceback

app = FastAPI()

@app.post("/run_aps")
async def run_aps(data: dict):
    try:
        # ====================================
        # RECEIVE DATA
        # ====================================

        material_df = pd.DataFrame(data.get("materials", []))
        material_df = material_df.rename(columns={
            "Title": "Material",
            "field_1": "zen10",
            "field_2": "zen30",
            "field_3": "zen50",
            "field_4": "zen70",
            "field_5": "zen90",
            "field_6": "Available_Qty",
            "field_7": "required_Qty",
            "field_8": "Incoming_Qty",
            "field_9": "Date"
        })

        targets_df = pd.DataFrame(data.get("targets", []))
        targets_df = targets_df.rename(columns={
            "Title": "Product",
            "field_1": "Target_Qty",
            "field_2": "Priority"
        })

        # ====================================
        # HANDLE actuals & plan (Fixed)
        # ====================================
        def get_list_from_section(section):
            if isinstance(section, dict):
                return section.get("value", [])
            elif isinstance(section, list):
                return section
            else:
                return []

        actual_list = get_list_from_section(data.get("actuals"))
        plan_list = get_list_from_section(data.get("plan"))

        actual_df = pd.DataFrame(actual_list)
        plan_df = pd.DataFrame(plan_list)

        actual_df = actual_df.rename(columns={
            "Title": "Date",
            "field_1": "zen10",
            "field_2": "zen30",
            "field_3": "zen50",
            "field_4": "zen70",
            "field_5": "zen90",
            "field_6": "Total"
        }) if not actual_df.empty else pd.DataFrame()

        plan_df = plan_df.rename(columns={
            "Title": "Date",
            "field_1": "zen10",
            "field_2": "zen30",
            "field_3": "zen50",
            "field_4": "zen70",
            "field_5": "zen90",
            "field_6": "Total"
        }) if not plan_df.empty else pd.DataFrame()

        backup_df = pd.DataFrame(data.get("backup", []))
        backup_df = backup_df.rename(columns={
            "Title": "Material",
            "field_1": "zen10",
            "field_2": "zen30",
            "field_3": "zen50",
            "field_4": "zen70",
            "field_5": "zen90",
            "field_6": "Available_Qty",
            "field_7": "required_Qty",
            "field_8": "Incoming_Qty",
            "field_9": "Date"
        })

        # ====================================
        # REVERSE COLUMN MAPPING
        # ====================================
        reverse_material_columns = {
            "Material": "Title",
            "zen10": "field_1",
            "zen30": "field_2",
            "zen50": "field_3",
            "zen70": "field_4",
            "zen90": "field_5",
            "Available_Qty": "field_6",
            "required_Qty": "field_7",
            "Incoming_Qty": "field_8",
            "Date": "field_9"
        }

        reverse_schedule_columns = {
            "Date": "Title","zen10": "field_1","zen30": "field_2","zen50": "field_3","zen70": "field_4","zen90": "field_5"
        }

        # ====================================
        # CLEAN DATA FUNCTION
        # ====================================
        def clean_dataframe(df):
            if df.empty:
                return df
            df = df.replace([np.inf, -np.inf], '0')
            df = df.fillna('0')
            return df

        # ====================================
        # VALIDATION
        # ====================================
        if targets_df.empty:
            return {"status": "error", "message": "Targets list empty"}

        if material_df.empty:
            return {"status": "error", "message": "Material list empty"}

        # ====================================
        # DATES
        # ====================================
        start_date = datetime.today().replace(day=1).strftime("%d-%m-%y")
        today_str = datetime.today().strftime("%d-%m-%y")
        tomorrow_str = (datetime.today() + timedelta(days=1)).strftime("%d-%m-%y")


        # ====================================
        # INITIAL PLAN (No previous plan)
        # ====================================
        if plan_df.empty:
            output_df = create_schedule(
                material_df=material_df,
                targets_df=targets_df,
                start_date=start_date
            )

            schedule_output = output_df.rename(columns=reverse_schedule_columns)
            backup_output = material_df.rename(columns=reverse_material_columns)

            schedule_output = clean_dataframe(schedule_output)
            backup_output = clean_dataframe(backup_output)

            return {
                "status": "success",
                "type": "no_changes",
                "schedule": schedule_output.to_dict(orient="records"),
                "backup": backup_output.to_dict(orient="records")
            }

        # ====================================
        # CHECK DEVIATION
        # ====================================
        deviation_found = False

        if not actual_df.empty:
            for _, actual_row in actual_df.iterrows():
                actual_date = actual_row["Date"]
                plan_row = plan_df[plan_df["Date"] == actual_date]

                if plan_row.empty:
                    deviation_found = True
                    break

                plan_row = plan_row.iloc[0]

                for product in targets_df["Product"]:
                    if product not in actual_row or product not in plan_row:
                        continue
                    actual_qty = int(actual_row[product])
                    planned_qty = int(plan_row[product])

                    if actual_qty != planned_qty:
                        deviation_found = True
                        break
                if deviation_found:
                    break

        # ====================================
        # CHECK ARRIVAL CHANGES
        # ====================================
        arrival_changed = not material_df.equals(backup_df)

        # ====================================
        # REPLANNING
        # ====================================
        if deviation_found or arrival_changed:
            replanned_df = run_scheduler(
                material_df=material_df,
                targets_df=targets_df,
                actual_df=actual_df,
                previous_plan_df=plan_df,
                start_date=start_date,
                replan_date=tomorrow_str
            )

            schedule_output = replanned_df.rename(columns=reverse_schedule_columns)
            backup_output = material_df.rename(columns=reverse_material_columns)

            schedule_output = clean_dataframe(schedule_output)
            backup_output = clean_dataframe(backup_output)

            return {
                "status": "success",
                "type": "replanned",
                "schedule": schedule_output.to_dict(orient="records"),
                "backup": backup_output.to_dict(orient="records")
            }

        # No changes
        return {
            "status": "success",
            "type": "no_changes",
            "schedule": plan_df.to_dict(orient="records")
        }

    except Exception as e:
        error_detail = traceback.format_exc()
        print("Error in /run_aps:", error_detail)  # For server logs
        return {
            "status": "error",
            "message": str(e)
        }
