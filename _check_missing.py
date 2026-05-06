import json, os
configs = [
    "no-freeze_no-table","adj-57_no-freeze_no-table",
    "no-freeze","adj-57_no-freeze",
    "no-table","adj-57_no-table",
    "default","adj-57",
]
for h in ("h7", "h8"):
    print(f"=== {h} ===")
    for cfg in configs:
        base = f"csp_solver/experiments/output/{h}/{cfg}"
        if not os.path.isdir(base):
            continue
        on_disk = set(d for d in os.listdir(base) if os.path.isdir(os.path.join(base, d)))
        djson = os.path.join(base, "data.json")
        if not os.path.isfile(djson):
            print(f"  {cfg}: data.json MISSING")
            continue
        with open(djson, encoding="utf-8") as f:
            data = json.load(f)
        in_json = set(data.get("molecules", {}).keys())
        missing = on_disk - in_json
        extra = in_json - on_disk
        flag = " ← MISSING" if missing else ""
        print(f"  {cfg}: disk={len(on_disk)} json={len(in_json)} missing={len(missing)} extra={len(extra)}{flag}")
        for m in sorted(missing):
            print(f"      [missing] {m}")
