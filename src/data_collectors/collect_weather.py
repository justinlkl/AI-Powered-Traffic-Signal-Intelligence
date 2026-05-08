"""
Fetch Hong Kong weather data from HKO API
Usage: python collect_weather.py --output data/raw/weather.csv
"""
import requests
import pandas as pd
from datetime import datetime
import argparse
import os


def fetch_hko_weather():
    """Fetch weather from Hong Kong Observatory"""
    url = "https://data.weather.gov.hk/weatherAPI/opendata/weather.php?dataType=rhrread&lang=en"

    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()

        # Extract rainfall at Central (best-effort)
        rainfall_data = data.get('rainfall', {}).get('data', [])
        central_rainfall = next((r for r in rainfall_data if r.get('place') == 'Central' or r.get('station') == 'Central'), {})

        record = {
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'location': 'Central',
            'rainfall_mm': central_rainfall.get('max', 0.0),
            'temp_c': data.get('temperature', {}).get('data', [{}])[0].get('value', -999),
            'weather_binary': 1 if (central_rainfall.get('max', 0.0) and float(central_rainfall.get('max', 0.0)) >= 1.0) else 0
        }

        return pd.DataFrame([record])

    except Exception as e:
        print(f"Error fetching weather: {e}")
        return pd.DataFrame()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default='data/raw/weather.csv')
    args = parser.parse_args()

    out_dir = os.path.dirname(args.output) or '.'
    os.makedirs(out_dir, exist_ok=True)

    df = fetch_hko_weather()
    if not df.empty:
        exists = os.path.exists(args.output)
        df.to_csv(args.output, index=False, mode='a', header=not exists)
        print(f"✓ Weather data saved → {args.output}")
    else:
        print("✗ Failed to fetch weather")
