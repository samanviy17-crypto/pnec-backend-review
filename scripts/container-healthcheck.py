"""Readiness probe inside the container; fixed loopback target, no private data."""
import json
from urllib.request import urlopen

def main():
    try:
        with urlopen('http://127.0.0.1:8475/api/ready',timeout=3) as response:
            return 0 if response.status==200 and json.load(response).get('status')=='ready' else 1
    except Exception:
        return 1

if __name__=='__main__':raise SystemExit(main())
