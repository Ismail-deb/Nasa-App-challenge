"""Download the processed data files from this repo's GitHub Release (no NASA account needed).

    python fetch_data.py                 # all files from release tag data-v1
    python fetch_data.py --tag data-v2

Files go to data/processed/. Files already present with the same size are skipped.
To publish data (on the machine that ran pull_data.py), see README "Moving data between machines".
"""
import argparse
import json
import urllib.request

from common import PROCESSED_DIR

REPO = "Ismail-deb/Nasa-App-challenge"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="data-v1")
    ap.add_argument("--repo", default=REPO)
    args = ap.parse_args()

    url = f"https://api.github.com/repos/{args.repo}/releases/tags/{args.tag}"
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                               "User-Agent": "trend-detective-fetch"})
    try:
        release = json.load(urllib.request.urlopen(req))
    except Exception as ex:
        raise SystemExit(f"Could not read release {args.tag} of {args.repo}: {ex}")

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    for a in release["assets"]:
        if not a["name"].endswith(".nc"):
            continue
        dest = PROCESSED_DIR / a["name"]
        if dest.exists() and dest.stat().st_size == a["size"]:
            print(f"have  {a['name']}")
            continue
        print(f"fetch {a['name']}  ({a['size'] / 1e6:.0f} MB)")
        tmp = dest.with_suffix(".part")
        urllib.request.urlretrieve(a["browser_download_url"], tmp)
        if tmp.stat().st_size != a["size"]:
            raise SystemExit(f"Size mismatch for {a['name']}; try again.")
        tmp.replace(dest)
    print("done")


if __name__ == "__main__":
    main()
