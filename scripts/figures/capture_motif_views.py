"""Capture 40 vues 3D top-down des sols exemples (motifs de bord h8).

Strategie :
  1. Pour chaque sample, on construit une mini-page HTML autonome qui :
     - charge 3Dmol.js depuis CDN
     - injecte directement le contenu XYZ recupere depuis /file?path=
     - alignе la camera top-down sur le plan principal d'inertie (PCA via 3Dmol)
     - rend en bonds-style stick
     - colore les atomes selon le cycle de plus petite taille auquel ils
       appartiennent (rouge=pent, gris=hex, bleu=hept) en utilisant /api/mol3d
  2. Playwright headless ouvre cette page locale, attend que window.RENDER_DONE
     soit true, screenshot le canvas.
  3. Sortie : doc/captures/motif_<w>_<cat>_<motif>.png

Prerequis : serveur Flask sur 127.0.0.1:8780 actif (pour /file et /api/mol3d).
"""

import asyncio
import base64
import json
import os
import sys
import time
import urllib.request
from pathlib import Path


SERVER_URL = "http://127.0.0.1:8780"
OUTPUT_DIR = Path("doc/captures")
HTML_TEMPLATE_PATH = Path("tmp/capture_template.html")


def http_get(url):
    with urllib.request.urlopen(url, timeout=30) as r:
        return r.read().decode("utf-8")


def fetch_xyz(xyz_rel):
    return http_get(f"{SERVER_URL}/file?path={xyz_rel}")


def fetch_mol3d(xyz_rel):
    raw = http_get(f"{SERVER_URL}/api/mol3d?path={xyz_rel}")
    return json.loads(raw)


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>capture</title>
<style>
  html, body { margin: 0; padding: 0; background: white; overflow: hidden; }
  #viewer { width: 700px; height: 700px; position: relative; }
</style>
<script src="https://3Dmol.org/build/3Dmol-min.js"></script>
</head>
<body>
<div id="viewer"></div>
<script>
window.RENDER_DONE = false;
window.ERR = null;

const XYZ_TEXT = __XYZ__;
const MOL3D_DATA = __MOL3D__;
const HIGHLIGHT_CYCLES = __HL__;

function principalAxes(coords) {
  const n = coords.length;
  let cx = 0, cy = 0, cz = 0;
  for (const c of coords) { cx += c.x; cy += c.y; cz += c.z; }
  cx /= n; cy /= n; cz /= n;
  let sxx = 0, syy = 0, szz = 0, sxy = 0, sxz = 0, syz = 0;
  for (const c of coords) {
    const dx = c.x - cx, dy = c.y - cy, dz = c.z - cz;
    sxx += dx*dx; syy += dy*dy; szz += dz*dz;
    sxy += dx*dy; sxz += dx*dz; syz += dy*dz;
  }
  // Matrice de covariance (Inverse de la matrice d'inertie scale-free)
  // On veut le vecteur propre associe a la PLUS PETITE valeur propre (axe
  // normal a la molecule = la direction de moindre etalement).
  // Pour 3 vp on resout le polynome caracteristique. Plus simple : iteration
  // de Jacobi (n=3 c'est petit).
  const A = [[sxx, sxy, sxz], [sxy, syy, syz], [sxz, syz, szz]];
  // Jacobi
  let V = [[1,0,0],[0,1,0],[0,0,1]];
  for (let iter = 0; iter < 50; iter++) {
    // Trouve l'element off-diagonal le plus grand
    let p = 0, q = 1, maxOff = Math.abs(A[0][1]);
    if (Math.abs(A[0][2]) > maxOff) { p = 0; q = 2; maxOff = Math.abs(A[0][2]); }
    if (Math.abs(A[1][2]) > maxOff) { p = 1; q = 2; maxOff = Math.abs(A[1][2]); }
    if (maxOff < 1e-10) break;
    const theta = (A[q][q] - A[p][p]) / (2 * A[p][q]);
    const t = Math.sign(theta) / (Math.abs(theta) + Math.sqrt(1 + theta*theta));
    const c = 1 / Math.sqrt(1 + t*t);
    const s = t * c;
    const App = A[p][p], Aqq = A[q][q], Apq = A[p][q];
    A[p][p] = App - t * Apq;
    A[q][q] = Aqq + t * Apq;
    A[p][q] = 0; A[q][p] = 0;
    for (let i = 0; i < 3; i++) {
      if (i !== p && i !== q) {
        const Aip = A[i][p], Aiq = A[i][q];
        A[i][p] = c * Aip - s * Aiq;
        A[p][i] = A[i][p];
        A[i][q] = s * Aip + c * Aiq;
        A[q][i] = A[i][q];
      }
    }
    for (let i = 0; i < 3; i++) {
      const Vip = V[i][p], Viq = V[i][q];
      V[i][p] = c * Vip - s * Viq;
      V[i][q] = s * Vip + c * Viq;
    }
  }
  // Eigenvalues : A[0][0], A[1][1], A[2][2]
  // L'axe normal = vp associe a la PLUS PETITE valeur
  let imin = 0;
  if (A[1][1] < A[imin][imin]) imin = 1;
  if (A[2][2] < A[imin][imin]) imin = 2;
  const normal = [V[0][imin], V[1][imin], V[2][imin]];
  return { center: {x: cx, y: cy, z: cz}, normal };
}

async function main() {
  try {
    const viewer = $3Dmol.createViewer("viewer", {
      backgroundColor: "white",
      antialias: true,
    });
    viewer.addModel(XYZ_TEXT, "xyz");
    // Sticks tout en gris, mais on va recolorer par cycle
    viewer.setStyle({}, { stick: { radius: 0.10, colorscheme: "Jmol" } });

    // Coloration : pour chaque cycle, dessiner un polygone semi-transparent
    // base sur les coords des atomes du cycle. C'est ce que fait le viewer
    // existant via addCustom().
    const atoms = MOL3D_DATA.atoms;
    const cycles = MOL3D_DATA.cycles;

    function vecSub(a, b) { return [a[0]-b[0], a[1]-b[1], a[2]-b[2]]; }
    function vecCross(a, b) {
      return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]];
    }
    function vecNorm(a) {
      const n = Math.sqrt(a[0]*a[0]+a[1]*a[1]+a[2]*a[2]);
      return n > 1e-9 ? [a[0]/n, a[1]/n, a[2]/n] : [0,0,1];
    }

    for (let ci = 0; ci < cycles.length; ci++) {
      const cyc = cycles[ci];
      const size = cyc.size;
      const isHL = HIGHLIGHT_CYCLES.includes(ci);
      let color;
      if (size === 5) color = isHL ? 0xfca5a5 : 0xfee2e2;
      else if (size === 7) color = isHL ? 0x93b3ff : 0xe2ebfe;
      else color = isHL ? 0xc8c8c8 : 0xf0f0f0;
      // Centroide
      let cx=0,cy=0,cz=0;
      for (const ai of cyc.atoms) {
        cx += atoms[ai].x; cy += atoms[ai].y; cz += atoms[ai].z;
      }
      cx /= cyc.atoms.length; cy /= cyc.atoms.length; cz /= cyc.atoms.length;
      // Triangulation en eventail
      const verts = []; const faces = [];
      verts.push({x:cx, y:cy, z:cz});  // 0 = centre
      for (const ai of cyc.atoms) verts.push({x:atoms[ai].x, y:atoms[ai].y, z:atoms[ai].z});
      for (let i = 1; i <= cyc.atoms.length; i++) {
        const j = (i % cyc.atoms.length) + 1;
        faces.push(0, i, j);
      }
      viewer.addCustom({
        vertexArr: verts,
        faceArr: faces,
        color: color,
        opacity: isHL ? 0.85 : 0.55,
      });
    }

    // Camera top-down : aligner sur axe principal d'inertie (minimum d'etalement)
    const coords = atoms.map(a => ({x:a.x, y:a.y, z:a.z}));
    const { center, normal } = principalAxes(coords);

    viewer.zoomTo();
    // Setup la camera : on regarde depuis center + 50 * normal vers center
    // 3Dmol n'expose pas directement setCameraPosition, mais on peut utiliser
    // setView avec une matrice de rotation construite a la main.
    // Approche pragmatique : on utilise rotate pour aligner normal sur Z.
    // Calcule l'angle entre normal et axe Z.
    const z = [0,0,1];
    const dot = normal[0]*0 + normal[1]*0 + normal[2]*1;
    const cross = vecCross(normal, z);
    const sinTheta = Math.sqrt(cross[0]*cross[0]+cross[1]*cross[1]+cross[2]*cross[2]);
    const angleDeg = Math.atan2(sinTheta, dot) * 180 / Math.PI;
    if (sinTheta > 1e-6) {
      const axis = vecNorm(cross);
      viewer.rotate(angleDeg, {x: axis[0], y: axis[1], z: axis[2]});
    }
    viewer.zoomTo();
    viewer.zoom(1.1);  // un poil zoom in
    viewer.render();

    // Marqueur DOM pour Playwright
    await new Promise(r => setTimeout(r, 200));
    window.RENDER_DONE = true;
  } catch (e) {
    window.ERR = e.toString();
    document.body.innerHTML = "<pre>ERR: " + e.toString() + "</pre>";
  }
}

main();
</script>
</body>
</html>
"""


def find_motif_window_cycles(mol3d_data, motif_str):
    """A partir des cycles du mol3d et de la sequence de bord externe,
    trouve l'indice des cycles correspondant a la fenetre du motif.

    On parse les cycles, on reconstruit la suite cyclique, on cherche.
    Cette logique duplique celle de extract_boundary_motifs_h8.py.
    """
    from collections import defaultdict
    cycles = mol3d_data["cycles"]
    motif = tuple(int(x) for x in motif_str.split("-"))

    # Construire les aretes par cycle (depuis l'ordre cyclique d'atoms)
    edges_by_cycle = []
    for cyc in cycles:
        atoms = cyc["atoms"]
        edges = [tuple(sorted([atoms[i], atoms[(i+1) % len(atoms)]])) for i in range(len(atoms))]
        edges_by_cycle.append(edges)

    edge_cycles = defaultdict(list)
    for ci, edges in enumerate(edges_by_cycle):
        for e in edges:
            edge_cycles[e].append(ci)
    boundary_edges = {e for e, cyc in edge_cycles.items() if len(cyc) == 1}
    if not boundary_edges:
        return []

    bd_neighbors = defaultdict(list)
    bd_edge_cycle = {}
    for e in boundary_edges:
        a, b = e
        bd_neighbors[a].append(b)
        bd_neighbors[b].append(a)
        bd_edge_cycle[e] = edge_cycles[e][0]
    if not bd_neighbors:
        return []

    start = next(iter(bd_neighbors))
    seq = []
    cur = start; prev = None
    while True:
        nbrs = bd_neighbors[cur]
        nxt = None
        for n in nbrs:
            if n != prev:
                nxt = n; break
        if nxt is None: break
        edge = tuple(sorted([cur, nxt]))
        seq.append(bd_edge_cycle[edge])
        if nxt == start: break
        prev = cur; cur = nxt

    # Dedup consecutif (cyclique)
    if not seq: return []
    ddup = [seq[0]]
    for x in seq[1:]:
        if x != ddup[-1]: ddup.append(x)
    if len(ddup) > 1 and ddup[-1] == ddup[0]: ddup.pop()

    sizes = [cycles[c]["size"] for c in ddup]
    L = len(ddup)
    k = len(motif)

    def canonical(w): return min(w, tuple(reversed(w)))
    target = canonical(motif)
    for i in range(L):
        win = tuple(sizes[(i+j) % L] for j in range(k))
        if canonical(win) == target:
            return [ddup[(i+j) % L] for j in range(k)]
    return []


async def capture_one(page, sample, idx, total):
    xyz = fetch_xyz(sample["xyz_rel_path"])
    mol3d = fetch_mol3d(sample["xyz_rel_path"])
    if "error" in mol3d:
        print(f"  [{idx}/{total}] ERR mol3d for {sample['motif']}: {mol3d['error']}")
        return None
    hl = find_motif_window_cycles(mol3d, sample["motif"])

    # Compose la page HTML
    html = (HTML_TEMPLATE
            .replace("__XYZ__", json.dumps(xyz))
            .replace("__MOL3D__", json.dumps(mol3d))
            .replace("__HL__", json.dumps(hl)))
    tmp_html = Path(f"tmp/_cap_{idx}.html")
    tmp_html.write_text(html, encoding="utf-8")

    out_name = f"motif_w{sample['w']}_{sample['category']}_{sample['motif']}.png"
    out_path = OUTPUT_DIR / out_name

    await page.goto(f"file:///{tmp_html.resolve().as_posix()}")
    try:
        await page.wait_for_function("window.RENDER_DONE === true || window.ERR !== null", timeout=30000)
    except Exception:
        print(f"  [{idx}/{total}] TIMEOUT {sample['motif']}")
        return None
    err = await page.evaluate("window.ERR")
    if err:
        print(f"  [{idx}/{total}] JS ERR {sample['motif']}: {err}")
        return None
    elem = await page.query_selector("#viewer")
    await elem.screenshot(path=str(out_path))
    tmp_html.unlink(missing_ok=True)
    print(f"  [{idx}/{total}] OK {sample['motif']} -> {out_name}")
    return out_path


async def main():
    sys.stdout.reconfigure(encoding="utf-8")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    samples = json.load(open("tmp/motif_samples.json"))["samples"]
    print(f"=== Capture {len(samples)} samples ===")

    from playwright.async_api import async_playwright
    t0 = time.perf_counter()
    n_ok = 0
    async with async_playwright() as p:
        # Un seul browser + une seule page reutilises
        browser = await p.chromium.launch()
        context = await browser.new_context(viewport={"width": 720, "height": 720})
        page = await context.new_page()
        try:
            for i, s in enumerate(samples, 1):
                r = await capture_one(page, s, i, len(samples))
                if r: n_ok += 1
        finally:
            await browser.close()
    print(f"=== Done : {n_ok}/{len(samples)} captures en {time.perf_counter()-t0:.1f}s ===")


if __name__ == "__main__":
    asyncio.run(main())
