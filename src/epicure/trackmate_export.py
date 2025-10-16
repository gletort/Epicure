from datetime import datetime
from xml.dom import minidom
import xml.etree.ElementTree as ET

SPOT_FEATS = [
    {"feature": "POSITION_X", "name": "X", "shortname": "X", "dimension": "POSITION", "isint": "false"},
    {"feature": "POSITION_Y", "name": "Y", "shortname": "Y", "dimension": "POSITION", "isint": "false"},
    {"feature": "POSITION_T", "name": "T", "shortname": "T", "dimension": "TIME", "isint": "false"},
    {"feature": "FRAME", "name": "Frame", "shortname": "Frame", "dimension": "NONE", "isint": "true"},
    {"feature": "VISIBILITY", "name": "Visibility", "shortname": "Visibility", "dimension": "NONE", "isint": "true"},
    {"feature": "MANUAL_SPOT_COLOR", "name": "Manual spot color", "shortname": "Spot color", "dimension": "NONE", "isint": "true"},
]

EDGE_FEATS = [
    {"feature": "SPOT_SOURCE_ID", "name": "Source spot ID", "shortname": "Source ID", "dimension": "NONE", "isint": "true"},
    {"feature": "SPOT_TARGET_ID", "name": "Target spot ID", "shortname": "Target ID", "dimension": "NONE", "isint": "true"},
]

TRACK_FEATS = [
    {"feature": "TRACK_INDEX", "name": "Track index", "shortname": "Index", "dimension": "NONE", "isint": "true"},
    {"feature": "TRACK_ID", "name": "Track ID", "shortname": "ID", "dimension": "NONE", "isint": "true"},
]


def build_feat_declaration_tag():
    """Build the FeatureDeclarations tag for TrackMate XML."""
    feat_declarations = ET.Element("FeatureDeclarations")
    spot_feats = ET.SubElement(feat_declarations, "SpotFeatures")
    for feat in SPOT_FEATS:
        ET.SubElement(spot_feats, "Feature", feat)
    edge_feats = ET.SubElement(feat_declarations, "EdgeFeatures")
    for feat in EDGE_FEATS:
        ET.SubElement(edge_feats, "Feature", feat)
    track_feats = ET.SubElement(feat_declarations, "TrackFeatures")
    for feat in TRACK_FEATS:
        ET.SubElement(track_feats, "Feature", feat)
    return feat_declarations


def build_model_tag(epic):
    """Build the Model tag for TrackMate XML."""
    model = ET.Element("model")
    model.set("spatialunits", epic.epi_metadata.get("UnitXY", "pixel"))
    model.set("timeunits", epic.epi_metadata.get("UnitT", "frame"))
    model.append(build_feat_declaration_tag())

    print("Tracked?", epic.tracked)
    # Numpy array with columns: label, pos_t, pos_x, pos_y
    track_data = epic.tracking.track_data
    print("Track data:", track_data)
    print(len(track_data), "spots tracked")

    all_spots = ET.SubElement(model, "AllSpots", {"nspots": str(len(track_data))})
    all_tracks = ET.SubElement(model, "AllTracks")
    filtered_tracks = ET.SubElement(model, "FilteredTracks")
    return model


def pretty_print_xml(element):
    """Pretty print an XML element."""
    rough_string = ET.tostring(element, encoding="utf-8")
    parsed = minidom.parseString(rough_string)
    return parsed.toprettyxml(indent="  ")


def save_trackmate_xml(epic, outname):
    """Save a TrackMate XML file."""
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
    with open(outname, "w", encoding="utf-8") as f:
        f.write(pretty_xml)
