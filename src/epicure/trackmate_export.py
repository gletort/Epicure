from datetime import datetime
from fileinput import filename
from pathlib import Path
from typing import Dict, List
from xml.dom import minidom
import xml.etree.ElementTree as ET

import pandas as pd
from scipy.cluster.hierarchy import DisjointSet

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

    return all_spots


def create_label_to_track_mapping(divisions: Dict[int, List[int]], unique_labels: List[int]) -> Dict[int, int]:
    """
    Create a mapping from labels to track IDs using scipy's DisjointSet for efficient track grouping.

    Args:
        divisions: dict of {daughter_label: [mother_labels]} from epic.tracking.graph
        unique_labels: list of unique labels present in the tracking data

    Returns:
        dict: {label: track_id} - mapping from each label to its track ID
    """
    if not divisions:
        # No divisions - each unique label is its own track.
        return {label: label for label in unique_labels}

    ds = DisjointSet(unique_labels)

    # Union connected labels based on mother-daughter relationships.
    for daughter, mothers in divisions.items():
        if daughter not in unique_labels:  # weirdly, this can happen
            continue
        for mother in mothers:
            if mother in unique_labels:
                ds.merge(daughter, mother)

    # A connected component is a TrackMate track. We use the root as track ID.
    # Create a mapping from label to track_id (root).
    label_to_track_id = {}
    for label in unique_labels:
        root = ds[label]
        label_to_track_id[label] = root

    return label_to_track_id


def build_all_tracks_data(epic, df_spots):
    """"""
    divisions = epic.tracking.graph  # dict of {daughter: mother}
    print(f"Divisions: {divisions}")

    # Generate and assign TRACK_IDs.
    labels = df_spots["label"].unique()
    label_to_track_id = create_label_to_track_mapping(divisions, labels)
    df_spots["TRACK_ID"] = df_spots["label"].map(label_to_track_id)

    # Division edges: for each daughter-mother pair, create an edge.
    edges_data = [{"daughter": daughter, "mother": mother} for daughter, mothers in divisions.items() for mother in mothers]
    df_edges = pd.DataFrame(edges_data)
    # Labels stay the same until there is a division. But spots ID are unique.
    # It means that in df_spots, labels appears multiple times. Because of this
    # we cannot easily map between df_spots and df_edges. So we create intermediary
    # columns to ease the mapping.
    df_spots["first_frame"] = df_spots.groupby("label")["FRAME"].transform("min")
    df_spots["last_frame"] = df_spots.groupby("label")["FRAME"].transform("max")
    # A daughter is at the first frame of its label, a mother at the last frame of its label.
    df_spots["daughter"] = df_spots["first_frame"] == df_spots["FRAME"]
    df_spots["mother"] = df_spots["last_frame"] == df_spots["FRAME"]
    df_spots.drop(columns=["first_frame", "last_frame"], inplace=True)
    # Now we can map between df_spots and df_edges.
    # The SPOT_SOURCE_ID is the spot ID of the matching label that is a mother,
    # and the SPOT_TARGET_ID is the spot ID of the matching label that is a daughter.
    df_edges["SPOT_SOURCE_ID"] = df_edges["mother"].map(df_spots[df_spots["mother"]].set_index("label")["ID"])
    df_edges["SPOT_TARGET_ID"] = df_edges["daughter"].map(df_spots[df_spots["daughter"]].set_index("label")["ID"])
    df_spots.drop(columns=["daughter", "mother"], inplace=True)

    # Add TRACK_ID to division edges (needed for XML).
    if not df_edges.empty:
        df_edges["TRACK_ID"] = df_edges["mother"].map(label_to_track_id)
        df_edges.drop(columns=["daughter", "mother"], inplace=True)

    # Non-division edges: for each track, connect consecutive spots.
    non_division_edges = []
    for track_id in df_spots["TRACK_ID"].unique():
        track_spots = df_spots[df_spots["TRACK_ID"] == track_id].sort_values("FRAME")
        for i in range(len(track_spots) - 1):
            current_spot = track_spots.iloc[i]
            next_spot = track_spots.iloc[i + 1]
            non_division_edges.append({"SPOT_SOURCE_ID": current_spot["ID"], "SPOT_TARGET_ID": next_spot["ID"], "TRACK_ID": track_id})

    # Combine division and non-division edges.
    df_non_division_edges = pd.DataFrame(non_division_edges)
    if not df_edges.empty and not df_non_division_edges.empty:
        # Make sure both dataframes have the same columns.
        df_edges = df_edges[["SPOT_SOURCE_ID", "SPOT_TARGET_ID", "TRACK_ID"]]
        df_edges = pd.concat([df_edges, df_non_division_edges], ignore_index=True)
    elif not df_non_division_edges.empty:
        df_edges = df_non_division_edges

    # Final cleanup and type conversion.
    if not df_edges.empty:
        # Remove duplicate edges (division edges that are also consecutive in time).
        df_edges = df_edges.drop_duplicates(subset=["SPOT_SOURCE_ID", "SPOT_TARGET_ID"], keep="first")
        # We can have NaN if a label has no mother (appears at first frame)
        # or no daughter (disappears at last frame).
        df_edges.dropna(inplace=True)
        # Convert to int in case of NaN.
        df_edges["SPOT_SOURCE_ID"] = df_edges["SPOT_SOURCE_ID"].astype(int)
        df_edges["SPOT_TARGET_ID"] = df_edges["SPOT_TARGET_ID"].astype(int)
        df_edges["TRACK_ID"] = df_edges["TRACK_ID"].astype(int)

    return df_edges


def build_all_tracks_tag(df_edges):
    """Build the AllTracks tag for TrackMate XML."""
    all_tracks = ET.Element("AllTracks")
    track_ids = df_edges["TRACK_ID"].unique()
    track_ids.sort()
    track_id_to_index = {track_id: index for index, track_id in enumerate(track_ids)}

    for track_id in track_ids:
        track = ET.SubElement(all_tracks, "Track")
        track.set("name", f"Track_{track_id}")
        track.set("TRACK_ID", str(track_id))
        track.set("TRACK_INDEX", str(track_id_to_index[track_id]))

        track_edges = df_edges[df_edges["TRACK_ID"] == track_id]
        for _, edge in track_edges.iterrows():
            edge_attrib = {
                "SPOT_SOURCE_ID": str(edge["SPOT_SOURCE_ID"]),
                "SPOT_TARGET_ID": str(edge["SPOT_TARGET_ID"]),
            }
            ET.SubElement(track, "Edge", edge_attrib)

    return all_tracks


def build_model_tag(epic):
    """Build the Model tag for TrackMate XML."""
    model = ET.Element("Model")
    model.set("spatialunits", epic.epi_metadata.get("UnitXY", "pixel"))
    model.set("timeunits", epic.epi_metadata.get("UnitT", "frame"))
    model.append(build_feat_declaration_tag())

    print("Tracked?", epic.tracked)
    df_spots = build_spots_df(epic)
    model.append(build_all_spots_tag(df_spots))
    df_edges = build_all_tracks_data(epic, df_spots)
    model.append(build_all_tracks_tag(df_edges))
    ET.SubElement(model, "FilteredTracks")

    return model


def build_settings_tag(epic):
    """Build the Settings tag for TrackMate XML."""
    settings = ET.Element("Settings")
    img_path = Path(epic.epi_metadata["MovieFile"])
    ET.SubElement(
        settings,
        "ImageData",
        {
            "filename": img_path.name,
            "folder": str(img_path.parent),
            "width": str(epic.imgshape2D[1]),
            "height": str(epic.imgshape2D[0]),
            "nslices": "1",
            "nframes": str(epic.nframes),
            "pixelwidth": str(epic.epi_metadata.get("ScaleXY", 1)),
            "pixelheight": str(epic.epi_metadata.get("ScaleXY", 1)),
            "voxeldepth": "1",
            "timeinterval": str(epic.epi_metadata.get("ScaleT", 1)),
        },
    )
    ET.SubElement(settings, "InitialSpotFilter")
    ET.SubElement(settings, "SpotFilterCollection")
    ET.SubElement(settings, "TrackFilterCollection")
    return settings


def build_gui_state_tag():
    """Build the GUIState tag for TrackMate XML."""
    gui_state = ET.Element()
    return gui_state


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
    settings = build_settings_tag(epic)
    root.append(settings)
    ET.SubElement(root, "GUIState", {"state": "ConfigureViews"})
    ET.SubElement(root, "DisplaySettings")
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
