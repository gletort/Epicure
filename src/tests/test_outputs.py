import numpy as np
import os
import epicure.epicuring as epi
import epicure.Utils as ut
from unittest.mock import Mock
import napari
from vispy import keys


def test_output_selected():
    test_img = os.path.join(".", "data_test", "area3_t100-101.tif")
    test_seg = os.path.join(".", "data_test", "area3_epyseg-t100-101.tif")
    viewer = napari.Viewer(show=False)
    epic = epi.EpiCure(viewer)
    resaxis, resval = epic.load_movie(test_img)
    epic.set_chanel(1, 1)
    assert epic.viewer is not None
    epic.go_epicure("test_epics", test_seg)

    output = epic.outputing
    assert output is not None
    sel = output.get_selection_name()
    assert sel == ""
    output.output_mode.setCurrentText("All cells")
    sel = output.get_selection_name()
    assert sel == ""
    output.output_mode.setCurrentText("Only selected cell")
    sel = output.get_selection_name()
    assert sel == "_cell_1"
    roi_file = os.path.join(".", "data_test", "test_epics", "area3_t100-101_rois_cell_1.zip")
    if os.path.exists(roi_file):
        os.remove(roi_file)
    ## TO UPDATE WITH NEW VERSION
    #output.roi_out()
    #assert os.path.exists(roi_file)

#test_output_selected()
