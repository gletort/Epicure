from datetime import datetime
from xml.dom import minidom
import xml.etree.ElementTree as ET

import pandas as pd

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


def build_spots_df(epic):
    """Build a DataFrame representing the spots table for TrackMate XML."""
    df_spots = pd.DataFrame(epic.tracking.track_data, columns=["label", "FRAME", "pos_x", "pos_y"])
    df_spots["ID"] = df_spots.index
    df_spots["name"] = df_spots.apply(lambda row: f"LABEL{row['label']}_FRAME{row['FRAME']}", axis=1)
    df_spots["POSITION_X"] = df_spots["pos_x"] * epic.epi_metadata.get("ScaleXY", 1)
    df_spots["POSITION_Y"] = df_spots["pos_y"] * epic.epi_metadata.get("ScaleXY", 1)
    df_spots["POSITION_T"] = df_spots["FRAME"] * epic.epi_metadata.get("ScaleT", 1)
    df_spots["VISIBILITY"] = 1
    df_spots.drop(columns=["pos_x", "pos_y"], inplace=True)
    # TODO: ROI_N_POINTS is missing

    return df_spots


def build_all_spots_tag(df_spots):
    """Build the AllSpots tag for TrackMate XML."""
    all_spots = ET.Element("AllSpots", {"nspots": str(len(df_spots))})

    frames = df_spots["FRAME"].unique()
    for frame in frames:
        spots_in_frame = df_spots[df_spots["FRAME"] == frame]
        frame_tag = ET.SubElement(all_spots, "SpotsInFrame", {"frame": str(frame)})
        for _, spot in spots_in_frame.iterrows():
            spot_attrib = {
                "ID": str(spot["ID"]),
                "name": spot["name"],
                "POSITION_X": str(spot["POSITION_X"]),
                "POSITION_Y": str(spot["POSITION_Y"]),
                "POSITION_T": str(spot["POSITION_T"]),
                "FRAME": str(spot["FRAME"]),
                "VISIBILITY": str(spot["VISIBILITY"]),
            }
            ET.SubElement(frame_tag, "Spot", spot_attrib)

    print(df_spots.head())

    return all_spots


def assign_track_ids(epic, df_spots):
    """Assign track IDs to spots based on their labels and divisions."""

    return df_spots


def build_all_tracks_tag(epic, df_spots):
    """Build the AllTracks tag for TrackMate XML."""
    all_tracks = ET.Element("AllTracks")
    divisions = epic.tracking.graph  # dict of {daughter: mother}
    print(divisions)
    edges_data = [{"daughter": daughter, "mother": mother} for daughter, mothers in divisions.items() for mother in mothers]
    df_edges = pd.DataFrame(edges_data)
    # Labels stay the same until there is a division. But spots ID are unique.
    # It means that in df_spots, labels appears multiple times. Because of this
    # we cannot easily map between df_spots and df_edges. So we create intermediary
    # columns to ease the mapping.
    df_spots["first_frame"] = df_spots.groupby("label")["FRAME"].transform("min")
    df_spots["last_frame"] = df_spots.groupby("label")["FRAME"].transform("max")
    # A daughter appears at the first frame of its label.
    df_spots["daughter"] = df_spots["first_frame"] == df_spots["FRAME"]
    df_spots["mother"] = df_spots["last_frame"] == df_spots["FRAME"]
    df_spots.drop(columns=["first_frame", "last_frame"], inplace=True)
    # Now we can map between df_spots and df_edges.
    # The SPOT_SOURCE_ID is the spot ID of the matching label that is a mother.
    df_edges["SPOT_SOURCE_ID"] = df_edges["mother"].map(df_spots[df_spots["mother"]].set_index("label")["ID"])
    # The SPOT_TARGET_ID is the spot ID of the matching label that is a daughter.
    df_edges["SPOT_TARGET_ID"] = df_edges["daughter"].map(df_spots[df_spots["daughter"]].set_index("label")["ID"])
    df_edges.drop(columns=["daughter", "mother"], inplace=True)
    # We can have NaN if a label has no mother (appears at first frame)
    # or no daughter (disappears at last frame). We drop these edges.
    df_edges.dropna(inplace=True)
    # Convert to int in case of NaN.
    df_edges["SPOT_SOURCE_ID"] = df_edges["SPOT_SOURCE_ID"].astype(int)
    df_edges["SPOT_TARGET_ID"] = df_edges["SPOT_TARGET_ID"].astype(int)

    print(df_edges.head())

    return all_tracks


def build_model_tag(epic):
    """Build the Model tag for TrackMate XML."""
    model = ET.Element("model")
    model.set("spatialunits", epic.epi_metadata.get("UnitXY", "pixel"))
    model.set("timeunits", epic.epi_metadata.get("UnitT", "frame"))
    model.append(build_feat_declaration_tag())

    print("Tracked?", epic.tracked)
    df_spots = build_spots_df(epic)
    model.append(build_all_spots_tag(df_spots))
    model.append(build_all_tracks_tag(epic, df_spots))
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
