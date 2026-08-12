import cloudscraper
import pandas as pd
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import time
from collections import Counter

def get_clean_maa_data():
    url = "https://chennaiinternationalairport.com/api/flightsroute/getflightfeed"
    
    # Calculate the 24-hour lookback window in milliseconds
    current_time_ms = int(time.time() * 1000)
    start_time_ms = current_time_ms - (12 * 60 * 60 * 1000)
    
    params = {
        "appname": "maa",
        "starttime": str(start_time_ms),
        "endtime": str(current_time_ms)
    }
    
    print("Initiating Cloudscraper to bypass MAA firewall...")
    # Create a scraper that mimics a standard Windows Chrome browser
    scraper = cloudscraper.create_scraper(
        browser={
            'browser': 'chrome',
            'platform': 'windows',
            'desktop': True
        }
    )
    
    response = scraper.get(url, params=params)
    print(f"MAA API Response Status: {response.status_code}")
    
    if response.status_code != 200: 
        print(f"Error: Firewall block may still be active. Response: {response.text[:150]}")
        return pd.DataFrame()
    
    try:
        raw_json = response.json()
    except Exception:
        print("Failed to decode JSON. The firewall returned a challenge page instead of data.")
        return pd.DataFrame()
        
    flight_list = raw_json.get("flights", [])
    print(f"Raw flights retrieved from MAA feed: {len(flight_list)}")
    
    clean_data = []
    ist_zone = ZoneInfo("Asia/Kolkata")
    
    status_counts = Counter()
    drop_reasons = Counter()
    
    for flight in flight_list:
        raw_status = str(flight.get("status", "")).strip()
        status_counts[raw_status] += 1
        
        # 1. Flexible Status Check (Case-insensitive)
        if not any(k in raw_status.upper() for k in ["ARRIVED", "LANDED"]):
            drop_reasons["status_not_arrived"] += 1
            continue
            
        sched_str = flight.get("scheduleDate")
        est_str = flight.get("estimatedDate")
        
        # 2. Gatekeeper: Ensure timing strings exist
        if not sched_str or not est_str:
            drop_reasons["missing_date_string"] += 1
            continue
            
        try:
            # 3. Robust ISO Parsing (Handles trailing 'Z' and varying decimal lengths)
            sched_dt = datetime.fromisoformat(sched_str.replace("Z", "+00:00")).astimezone(ist_zone)
            est_dt = datetime.fromisoformat(est_str.replace("Z", "+00:00")).astimezone(ist_zone)
            
            delta_minutes = int((est_dt - sched_dt).total_seconds() / 60)
            
            airline_name = flight.get("airlineName")
            flight_name = flight.get("flightName", "")
            
            # Clean up missing or undefined airline names
            if not airline_name or str(airline_name).lower() in ["undefined", "none", "null"]:
                airline_name = "IndiGo" if "6E" in str(flight_name) else "Other"
            else:
                airline_name = "IndiGo" if str(airline_name).lower() == "indigo" else str(airline_name).title()

            clean_data.append({
                "date": sched_dt.strftime("%Y-%m-%d"),
                "airport_code": "MAA",
                "airline": airline_name,
                "origin_city": flight.get("originmap", "Unknown"),
                "flight_number": flight_name,
                "scheduled_time": sched_dt.strftime("%H:%M"),
                "actual_time": est_dt.strftime("%H:%M"),
                "delta_minutes": delta_minutes,
                "status": "Arrived"
            })
            
        except Exception:
            drop_reasons["date_parse_error"] += 1
            continue

    print("\n--- MAA DIAGNOSTIC SUMMARY ---")
    print(f"Raw Status Breakdown: {dict(status_counts)}")
    print(f"Drop Reasons Breakdown: {dict(drop_reasons)}")
    print(f"Clean Records Processed: {len(clean_data)}")
    print("-------------------------------\n")
            
    return pd.DataFrame(clean_data)

def update_csv_master_file(new_df, filepath="data/flights_data_maa.csv"):
    if new_df.empty:
        print("No new valid records to append.")
        return
        
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    
    if os.path.exists(filepath):
        existing_df = pd.read_csv(filepath)
        # Deduplicate to prevent double-counting flights across overlapping cron runs
        combined_df = pd.concat([existing_df, new_df]).drop_duplicates(subset=['date', 'flight_number'], keep='last')
    else:
        combined_df = new_df
        
    combined_df.to_csv(filepath, index=False)
    print(f"Data saved! Master MAA CSV now contains {len(combined_df)} clean records.")

if __name__ == "__main__":
    df = get_clean_maa_data()
    if not df.empty: 
        update_csv_master_file(df)