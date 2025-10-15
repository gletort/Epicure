
from datetime import datetime
from xml.dom import minidom
import xml.etree.ElementTree as ET

# TODO: implement
def get_nb_spots(epic):
    """ Return the number of spots detected by EpiCure."""
    return 0

def build_model_tag(epic):
    """ Build the Model tag for TrackMate XML. """
    model = ET.Element("Model")
    model.set("spatialunits", epic.epi_metadata.get("UnitXY", "pixel"))
    model.set("timeunits", epic.epi_metadata.get("UnitT", "frame"))
    feat_declarations = ET.SubElement(model, "FeatureDeclarations")
    spot_feats = ET.SubElement(feat_declarations, "SpotFeatures")
    edge_feats = ET.SubElement(feat_declarations, "EdgeFeatures")
    track_feats = ET.SubElement(feat_declarations, "TrackFeatures")
    all_spots = ET.SubElement(model, "AllSpots", {"nspots": str(get_nb_spots(epic))})
    all_tracks = ET.SubElement(model, "AllTracks")
    filtered_tracks = ET.SubElement(model, "FilteredTracks")
    return model

def pretty_print_xml(element):
    """Pretty print an XML element."""
    rough_string = ET.tostring(element, encoding="utf-8")
    parsed = minidom.parseString(rough_string)
    return parsed.toprettyxml(indent="  ")

def save_trackmate_xml(epic, outname):
    """ Save a TrackMate XML file. """
    root = ET.Element("TrackMate", {"version": "unknown"})
    log = ET.SubElement(root, "Log")
    now = datetime.now()
    log.text = f"Created by EpiCure on {now.strftime('%Y-%m-%d %H:%M:%S')}"
    model = build_model_tag(epic)
    root.append(model)
    # tree = ET.ElementTree(root)

    
    pretty_xml = pretty_print_xml(root)
    # TODO: check if ET.indent is better or more efficient than pretty_print_xml
    # for Python 3.9+
    # Pretty formatting - ET.indent is available from Python 3.9+
    # try:
    #     ET.indent(tree, space="  ", level=0)
    # except AttributeError:
    #     # Fallback for Python < 3.9
    #     pass
    with open(outname, 'w', encoding="utf-8") as f:
        f.write(pretty_xml)
