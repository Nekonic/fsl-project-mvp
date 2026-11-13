import json, sys, os, requests
url = os.environ.get("ELASTIC_URL", "http://elasticsearch:9200")
index, start, end = sys.argv[1:4]
body = {"size": 5000, "sort": [{"@timestamp": "asc"}, {"_doc": "asc"}],
        "query": {"range": {"@timestamp": {"gte": start, "lte": end}}},
        "_source": {"excludes": ["message", "event.original"]}}
after = None
n = 0
while True:
    if after: body["search_after"] = after
    r = requests.post(f"{url}/{index}/_search", json=body, timeout=60); r.raise_for_status()
    hits = r.json()["hits"]["hits"]
    if not hits: break
    for h in hits:
        sys.stdout.write(json.dumps([h["_id"], h["_source"]]) + "\n"); n += 1
    after = hits[-1]["sort"]
sys.stderr.write(f"{n} docs\n")
