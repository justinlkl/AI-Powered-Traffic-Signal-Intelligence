"""
Use real TD traffic data to calibrate CityFlow flow.json arrival rates
Usage: python calibrate_flow.py --input data/raw/td_traffic.csv
"""
import pandas as pd
import json
import argparse
import os


def calibrate_cityflow_rates(td_data_path, output_path='data/raw/flow_calibrated.json'):
    """
    Read TD detector volumes and compute realistic arrival rates for CityFlow
    """
    # Read TD traffic data
    df = pd.read_csv(td_data_path)

    # Filter Nathan Road detectors (example); fallback to full set if none
    df_filtered = df[df['location'].str.contains('Nathan', na=False)]
    if df_filtered.empty:
        df_filtered = df

    # Compute average volume per hour
    avg_volume = df_filtered['volume'].mean() if not df_filtered.empty else 0.0

    # Convert to CityFlow interval (seconds between vehicles)
    if avg_volume > 0:
        interval = 3600.0 / avg_volume  # seconds per vehicle
    else:
        interval = 3.0  # fallback

    # Create CityFlow flow.json (simple single-route example)
    flow_config = [{
        "vehicle": [{
            "route": ["road_N", "junction_1", "road_S"],
            "interval": interval,
            "startTime": 0,
            "endTime": 300
        }]
    }]

    out_dir = os.path.dirname(output_path) or '.'
    os.makedirs(out_dir, exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump(flow_config, f, indent=2)

    print(f"✓ Calibrated flow.json with interval={interval:.2f}s → {output_path}")
    print(f"  (Based on {len(df_filtered)} TD detectors, avg {avg_volume:.0f} veh/hr)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', required=True, help='Path to td_traffic.csv')
    parser.add_argument('--output', default='data/raw/flow_calibrated.json')
    args = parser.parse_args()

    calibrate_cityflow_rates(args.input, args.output)
