"""Exportateurs de formats moleculaires (CML, MOL V2000)"""

import xml.etree.ElementTree as ET
from xml.dom import minidom
from core.topology import MolecularGraph

class CMLExporter:
    """Exporte vers Chemical Markup Language"""
    
    @staticmethod
    def export(graph: MolecularGraph, filename: str, comment: str = ""):
        """Exporte le graphe vers un fichier CML"""
        root = ET.Element('molecule')
        if comment:
            root.set('title', comment)
        
        # AtomArray
        atom_array = ET.SubElement(root, 'atomArray')
        atoms_data, bonds_data = graph.to_cml_data()
        
        for atom_data in atoms_data:
            atom_el = ET.SubElement(atom_array, 'atom')
            for key, val in atom_data.items():
                atom_el.set(key, val)
        
        # BondArray
        bond_array = ET.SubElement(root, 'bondArray')
        for bond_data in bonds_data:
            bond_el = ET.SubElement(bond_array, 'bond')
            for key, val in bond_data.items():
                bond_el.set(key, val)
        
        # Pretty print
        xml_str = ET.tostring(root, encoding='unicode')
        reparsed = minidom.parseString(xml_str)
        pretty_xml = reparsed.toprettyxml(indent="  ")
        
        # Nettoyer les lignes vides, garder la declaration XML
        lines = [line for line in pretty_xml.split('\n') if line.strip()]

        with open(filename, 'w') as f:
            f.write('\n'.join(lines))


class MOLExporter:
    """Exporte vers MDL MOL V2000 (liaisons explicites, lisible par Open Babel)"""

    @staticmethod
    def export(graph: MolecularGraph, filename: str, title: str = ""):
        """
        Exporte le graphe au format MOL V2000.

        Le format MOL contient explicitement les atomes, leurs coordonnees,
        et les liaisons avec leurs ordres. Open Babel n'a donc pas besoin
        de deviner les liaisons (contrairement au format XYZ).
        """
        # Construire une table d'index continu 1..N
        id_to_idx = {}
        atoms_ordered = []
        for i, (vid, v) in enumerate(sorted(graph.vertices.items()), 1):
            id_to_idx[vid] = i
            atoms_ordered.append(v)

        # Collecter les liaisons (sans doublons)
        bonds = []
        seen = set()
        for v in graph.vertices.values():
            for other_id, order in v.bonds:
                key = tuple(sorted([v.id, other_id]))
                if key not in seen:
                    bonds.append((id_to_idx[key[0]], id_to_idx[key[1]], order))
                    seen.add(key)

        n_atoms = len(atoms_ordered)
        n_bonds = len(bonds)

        lines = []
        # Header (3 lignes)
        lines.append(title if title else filename)
        lines.append("  NonBenzGen  3D")
        lines.append("")
        # Counts line
        lines.append(f"{n_atoms:3d}{n_bonds:3d}  0  0  0  0  0  0  0  0999 V2000")
        # Atom block
        for v in atoms_ordered:
            lines.append(
                f"{v.x:10.4f}{v.y:10.4f}{v.z:10.4f} {v.element:<3s} 0  0  0  0  0  0  0  0  0  0  0  0"
            )
        # Bond block
        for a1, a2, order in bonds:
            lines.append(f"{a1:3d}{a2:3d}{order:3d}  0  0  0  0")
        # End
        lines.append("M  END")

        with open(filename, 'w') as f:
            f.write('\n'.join(lines) + '\n')