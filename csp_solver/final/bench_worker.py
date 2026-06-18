"""Worker du bench ACE vs Choco. Tourne sur 1 noeud cluster (ou local).

Recoit JSON via stdin :
  {"timeout_s": 300,
   "items": [{"h": 9, "config_name": "Ctopo", "graph_content": "..."}, ...]}

Renvoie JSON via stdout :
  {"results": [{"h": ..., "config": ..., "graph_name": ..., "result": {...}}, ...]}

IMPORTANT : sys.argv est cleané AVANT l'import pycsp3 (sinon il
intercepte argv et tente de lire le 'fichier' -c, --help, etc.).
"""
import json
import socket
import sys
import tempfile
import traceback
from pathlib import Path


def main():
    # 1. Read stdin
    payload = json.load(sys.stdin)
    timeout_s = int(payload.get("timeout_s", 300))
    items = payload.get("items", [])

    # 2. Clean sys.argv AVANT d'importer pycsp3 (via solver_bench)
    sys.argv = [sys.argv[0]]

    # 3. Setup imports
    here = Path(__file__).resolve().parent
    csp_root = here.parent
    if str(csp_root) not in sys.path:
        sys.path.insert(0, str(csp_root))
    if str(csp_root.parent) not in sys.path:
        sys.path.insert(0, str(csp_root.parent))

    from utils.solver_bench import benchmark_one
    from csp_solver.final.configs import get_config

    # Ctopo n'est pas dans final/configs.py (=> on construit manuellement)
    CTOPO_CFG = {
        "K_pb": 1, "adj_57": True, "tau_gb": 0, "radius_gb": 2,
        "ctopo_filter": True, "ctopo_min_n_peri": 4,
        "freeze_b2": False, "no_table": False,
    }

    def _get_config(name):
        if name == "Ctopo":
            return dict(CTOPO_CFG)
        return get_config(name)

    hostname = socket.gethostname()
    tmpdir = tempfile.mkdtemp(prefix=f"bench_{hostname}_")
    results = []

    for it in items:
        h = int(it["h"])
        cfg_name = it["config"]
        graph_name = it["graph_name"]
        graph_content = it["graph_content"]

        # Ecrit le .graph dans un fichier temporaire
        gp = Path(tmpdir) / f"{graph_name}.graph"
        gp.write_text(graph_content, encoding="utf-8")

        try:
            cfg = _get_config(cfg_name)
            r = benchmark_one(str(gp), cfg, timeout_s=timeout_s, tmp_dir=tmpdir)
            results.append({"h": h, "config": cfg_name, "graph_name": graph_name,
                            "result": r})
        except Exception as e:
            results.append({"h": h, "config": cfg_name, "graph_name": graph_name,
                            "result": {"error": f"{type(e).__name__}: {e}",
                                       "trace": traceback.format_exc()[-1500:]}})

    # Cleanup
    try:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)
    except Exception:
        pass

    print(json.dumps({"hostname": hostname, "results": results}))


if __name__ == "__main__":
    main()
