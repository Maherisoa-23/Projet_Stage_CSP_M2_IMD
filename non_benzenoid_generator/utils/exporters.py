"""Exportateurs de formats moléculaires (CML, XYZ)"""

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