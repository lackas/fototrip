"""Download the frontend libraries into src/fototrip/assets/vendor/.

Run once, commit the result. The build never touches the network.
"""

import hashlib
import json
import urllib.request
from pathlib import Path

VENDOR_DIR = Path(__file__).resolve().parent.parent / "src" / "fototrip" / "assets" / "vendor"

FILES = {
    "leaflet/leaflet.js": "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js",
    "leaflet/leaflet.css": "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css",
    "leaflet/images/marker-icon.png": "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png",
    "leaflet/images/marker-shadow.png": "https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png",
    "markercluster/markercluster.js": "https://unpkg.com/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js",
    "markercluster/MarkerCluster.css": "https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.css",
    "photoswipe/photoswipe.esm.js": "https://unpkg.com/photoswipe@5.4.4/dist/photoswipe.esm.js",
    "photoswipe/photoswipe-lightbox.esm.js": "https://unpkg.com/photoswipe@5.4.4/dist/photoswipe-lightbox.esm.js",
    "photoswipe/photoswipe.css": "https://unpkg.com/photoswipe@5.4.4/dist/photoswipe.css",
}


def main() -> None:
    lock = {}
    for rel, url in FILES.items():
        target = VENDOR_DIR / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(url) as response:
            payload = response.read()
        target.write_bytes(payload)
        lock[rel] = {"url": url, "sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload)}
        print(f"{rel}  {len(payload):>9,} bytes")
    (VENDOR_DIR / "VENDOR.lock.json").write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n")
    print(f"\nwrote {len(lock)} files + VENDOR.lock.json")


if __name__ == "__main__":
    main()
