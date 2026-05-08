"""
Fetch real Hong Kong traffic data from Transport Department
Usage: python collect_td_traffic.py --output data/raw/td_traffic.csv
"""
import requests
import xml.etree.ElementTree as ET
import pandas as pd
from datetime import datetime
import argparse
import os


def fetch_td_traffic():
    """Fetch traffic detector data from TD API"""
    url = "https://resource.data.one.gov.hk/td/traffic-data-strategic-major-roads.xml"

    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()

        # Parse XML
        root = ET.fromstring(response.content)

        records = []
        for detector in root.findall('.//detector'):
            detector_id = detector.findtext('detector_id') or detector.findtext('id') or ""
            location = detector.findtext('location') or ""
            vol = detector.findtext('volume')
            spd = detector.findtext('speed')
            occ = detector.findtext('occupancy')
            try:
                volume = int(vol) if vol and vol.strip() != "" else -1
            except Exception:
                volume = -1
            try:
                speed = int(spd) if spd and spd.strip() != "" else -1
            except Exception:
                speed = -1
            try:
                occupancy = float(occ) if occ and occ.strip() != "" else -1.0
            except Exception:
                occupancy = -1.0

            records.append({
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'detector_id': detector_id,
                'location': location,
                'volume': volume,
                'speed': speed,
                'occupancy': occupancy
            })

        return pd.DataFrame(records)

    except Exception as e:
        print(f"Error fetching TD traffic data: {e}")
        return pd.DataFrame()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default='data/raw/td_traffic.csv')
    args = parser.parse_args()

    out_dir = os.path.dirname(args.output) or '.'
    os.makedirs(out_dir, exist_ok=True)

    df = fetch_td_traffic()
    if not df.empty:
        df.to_csv(args.output, index=False)
        print(f"✓ Fetched {len(df)} detector records → {args.output}")
    else:
        print("✗ Failed to fetch data")
