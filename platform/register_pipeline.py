import os
import time
import urllib.error
import urllib.request

PIPELINE = "/app/deploy/elastic/ingest-pipeline.json"


def endpoint(base: str) -> str:
    return f"{base.rstrip('/')}/_ingest/pipeline/fsl-geoip"


def main():
    url = endpoint(os.environ.get("ELASTIC_URL", "http://elasticsearch:9200"))
    try:
        body = open(PIPELINE, "rb").read()
    except OSError as exc:
        print(f"no pipeline file at {PIPELINE}: {exc}", flush=True)
        return

    for _ in range(30):
        request = urllib.request.Request(
            url, data=body, method="PUT",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as answer:
                if answer.status < 300:
                    print("fsl-geoip pipeline registered", flush=True)
                    return
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(2)

    print("could not register the fsl-geoip pipeline; ingest will not geolocate", flush=True)


if __name__ == "__main__":
    main()
