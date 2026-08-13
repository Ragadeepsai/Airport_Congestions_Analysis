import requests
import pandas as pd
import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from collections import Counter
from dotenv import load_dotenv

# Load the API key from your local .env file
load_dotenv()
API_KEY = os.getenv("RAPIDAPI_KEY")
HOST = "aerodatabox.p.rapidapi.com"

# Add this temporary debug line:
print(f"DEBUG - API Key being used: '{API_KEY}'")

if not API_KEY:
    raise ValueError("API Key not found! Please check your .env file.")

def fetch_mumbai_arrivals(lookback_hours=12):
    """
    Fetches arrivals from Mumbai (VABB) using an overlapping lookback window.
    """
    url = "https://aerodatabox.p.rapidapi.com/flights/airports/icao/VABB"
    
    now_utc = datetime.now(timezone.utc)
    start_utc = now_utc - timedelta(hours=lookback_hours) 
    
    params = {
        "timeFrom": start_utc.strftime("%Y-%m-%dT%H:%M"),
        "timeTo": now_utc.strftime("%Y-%m-%dT%H:%M"),
        "withFlightNumberOnly": "true"
    }
    
    headers = {
        "x-rapidapi-key": API_KEY,
        "x-rapidapi-host": HOST
    }
    
    print(f"Requesting BOM arrivals from {params['timeFrom']} to {params['timeTo']} (UTC)...")
    response = requests.get(url, headers=headers, params=params)
    
    if response.status_code != 200:
        print(f"API Failed with status {response.status_code}: {response.text}")
        return pd.DataFrame()
        
    raw_arrivals = response.json().get("arrivals", [])
    print(f"Successfully pulled {len(raw_arrivals)} raw flight records.")
    
    return process_flight_data(raw_arrivals)


def process_flight_data(raw_arrivals):
    """
    Cleans, parses, calculates delays, and logs diagnostic drop reasons.
    """
    clean_data = []
    ist_tz = ZoneInfo("Asia/Kolkata")
    
    # Diagnostics Counters
    status_counts = Counter()
    drop_reasons = Counter()
    
    for flight in raw_arrivals:
        status = flight.get("status", "Unknown")
        status_counts[status] += 1
        
        # 1. Gatekeeper: Only accept completed flights
        if status not in ["Arrived", "Landed"]:
            drop_reasons["status_not_final"] += 1
            continue
            
        movement = flight.get("movement", {})
        
        sched_utc_str = movement.get("scheduledTime", {}).get("utc")
        act_utc_str = (
            movement.get("revisedTime", {}).get("utc") or
            movement.get("actualTime", {}).get("utc") or
            movement.get("estimatedTime", {}).get("utc")
        )
        
        # 2. Gatekeeper: No-Fallback Rule
        if not sched_utc_str or not act_utc_str:
            drop_reasons["missing_time_data"] += 1
            continue
            
        try:
            sched_dt_utc = datetime.strptime(sched_utc_str, "%Y-%m-%d %H:%MZ").replace(tzinfo=timezone.utc)
            act_dt_utc = datetime.strptime(act_utc_str, "%Y-%m-%d %H:%MZ").replace(tzinfo=timezone.utc)
            
            delta_minutes = int((act_dt_utc - sched_dt_utc).total_seconds() / 60)
            
            # --- Midnight Crossing Bug Fix ---
            # If a flight lands early the night before, the API accidentally adds 24 hours
            if delta_minutes > 1000:
                delta_minutes -= 1440
            elif delta_minutes < -1000:
                delta_minutes += 1440
            
            sched_dt_ist = sched_dt_utc.astimezone(ist_tz)
            act_dt_ist = act_dt_utc.astimezone(ist_tz)
            
            clean_data.append({
                "date": sched_dt_ist.strftime("%Y-%m-%d"),
                "airport_code": "BOM",
                "airline": flight.get("airline", {}).get("name", "Unknown"),
                "origin_city": movement.get("airport", {}).get("name", "Unknown"),
                "flight_number": flight.get("number", "Unknown"),
                "scheduled_time": sched_dt_ist.strftime("%H:%M"),
                "actual_time": act_dt_ist.strftime("%H:%M"),
                "delta_minutes": delta_minutes,
                "status": status
            })
            
        except ValueError:
            drop_reasons["malformed_timestamp"] += 1
            continue

    # Diagnostic Output Summary
    print("\n--- DIAGNOSTIC SUMMARY ---")
    print(f"Raw Status Breakdown: {dict(status_counts)}")
    print(f"Drop Reasons Breakdown: {dict(drop_reasons)}")
    print(f"Clean Records Processed: {len(clean_data)}")
    print("---------------------------\n")
            
    return pd.DataFrame(clean_data)


def update_master_csv(new_df, filepath="data/flights_data_bom_adb.csv"):
    if new_df.empty:
        print("No valid, completed flights to append in this window.")
        return
        
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    
    if os.path.exists(filepath):
        existing_df = pd.read_csv(filepath)
        # Key: keep='last' updates the flight status if it changed from expected -> arrived
        combined_df = pd.concat([existing_df, new_df]).drop_duplicates(
            subset=['date', 'flight_number'], keep='last'
        )
    else:
        combined_df = new_df
        
    combined_df.to_csv(filepath, index=False)
    print(f"Data saved! Master CSV now contains {len(combined_df)} clean records.")


if __name__ == "__main__":
    df = fetch_mumbai_arrivals(lookback_hours=12)
    update_master_csv(df)
