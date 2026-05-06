import os
mol_dir = "csp_solver/experiments/output/h8/no-freeze_no-table/1-9-10-19-20-29-30-39"
sol_root = os.path.join(mol_dir, "solutions")
sols = sorted(d for d in os.listdir(sol_root) if os.path.isdir(os.path.join(sol_root, d)))
print(f"n sol_dirs: {len(sols)}")

n_with_final = 0
n_with_meta = 0
n_with_traj = 0
n_with_source = 0
missing_final = []
for s in sols:
    p = os.path.join(sol_root, s)
    final_xyz = os.path.join(p, "md_validation", "md_final_opt.xyz")
    meta = os.path.join(p, "md_validation", "md_meta.json")
    traj = os.path.join(p, "md_validation", "md_traj.xyz")
    src = os.path.join(p, "source.xyz")
    if os.path.isfile(final_xyz) and os.path.getsize(final_xyz) > 0:
        n_with_final += 1
    else:
        missing_final.append(s)
    if os.path.isfile(meta):
        n_with_meta += 1
    if os.path.isfile(traj):
        n_with_traj += 1
    if os.path.isfile(src):
        n_with_source += 1

print(f"  with source.xyz             : {n_with_source}/{len(sols)}")
print(f"  with md_final_opt.xyz       : {n_with_final}/{len(sols)}")
print(f"  with md_traj.xyz            : {n_with_traj}/{len(sols)}")
print(f"  with md_meta.json           : {n_with_meta}/{len(sols)}")
if missing_final:
    print(f"  [{len(missing_final)}] missing md_final_opt.xyz, examples:")
    for s in missing_final[:5]:
        print(f"    - {s}")
