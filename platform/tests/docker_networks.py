def inspected(wargame="board", database="board-db", front="board"):
    return [
        {"Name": f"{wargame}_backend", "Internal": True, "IPAM": {"Config": [{"Subnet": "172.18.0.0/16"}]},
         "Containers": {
             "c1": {"Name": database, "MacAddress": "02:42:AC:12:00:02", "IPv4Address": "172.18.0.2/16"},
             "c2": {"Name": front, "MacAddress": "02:42:ac:12:00:03", "IPv4Address": "172.18.0.3/16"},
         }},
        {"Name": f"{wargame}_front", "Internal": False, "IPAM": {"Config": [{"Subnet": "172.19.0.0/16"}]},
         "Containers": {"c3": {"Name": front, "MacAddress": "02:42:ac:13:00:02", "IPv4Address": "172.19.0.2/16"}}},
        {"Name": "bridge", "Internal": False, "IPAM": {"Config": [{"Subnet": "172.17.0.0/16"}]}, "Containers": {}},
    ]
