
import xml.etree.ElementTree as ET



def save_trackmate_xml(epic, outname):
    """ Save a TrackMate XML file. """

    root = ET.Element("TrackMate", {"version": "unknown"})
    log = ET.SubElement(root, "Log")
    model = ET.SubElement(root, "Model")
    tree = ET.ElementTree(root)
    
    # Pretty formatting - ET.indent is available from Python 3.9+
    try:
        ET.indent(tree, space="  ", level=0)
    except AttributeError:
        # Fallback for Python < 3.9
        pass
    
    # Write to file with proper resource management
    with open(outname, 'wb') as f:
        tree.write(f, encoding="utf-8", xml_declaration=True)
