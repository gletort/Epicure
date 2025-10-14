import numpy as np
import os
import epicure.epicuring as epi
import epicure.Utils as ut
from unittest.mock import Mock
import napari
from vispy import keys


def test_suspect_frame():
    test_img = os.path.join(".", "data_test", "area3_t100-101.tif")
    test_seg = os.path.join(".", "data_test", "area3_epyseg-t100-101.tif")
    viewer = napari.Viewer(show=False)
    epic = epi.EpiCure(viewer)
    resaxis, resval = epic.load_movie(test_img)
    epic.set_chanel(1, 1)
    assert epic.viewer is not None
    epic.go_epicure("test_epics", test_seg)
    
    segedit = epic.inspecting
    assert segedit is not None
    segedit.min_area.setText("50")
    segedit.event_area_threshold()
    assert "Events" in epic.viewer.layers
    outlier = epic.viewer.layers["Events"]
    assert len(outlier.data)>=10
    assert outlier.data[1][0] == 0
    
    nsus = len(outlier.data)
    segedit.fintensity_out.setText("0.5")
    segedit.event_intensity(True)
    assert len(outlier.data) > (nsus+5)

def test_suspect_track():
    test_img = os.path.join(".", "data_test", "003_crop.tif")
    test_seg = os.path.join(".", "data_test", "003_crop_epyseg.tif")

    ## load and initialize
    epic = epi.EpiCure()
    epic.load_movie(test_img)
    epic.go_epicure("test_epics", test_seg)
    
    track = epic.tracking
    
    # default tracking
    susp = epic.inspecting
    assert susp.nb_events() == 0
    track.do_tracking()
    ## test basics
    assert susp.nb_events() == susp.nb_type("division")
    nev = susp.nb_events()
    susp.add_event( (5,50,50), 10, "test" )
    assert susp.nb_events() == (nev+1)
    ## test default parameter inspection
    susp.check_size.setChecked( False )
    susp.check_length.setChecked( False )
    susp.inspect_tracks()
    assert susp.nb_events() > 50
    assert susp.nb_events() < 100
    ## test minimum track length inspection
    susp.check_length.setChecked( True )
    susp.min_length.setText("5")
    nmin_prev =  susp.nb_events()
    susp.inspect_tracks()
    nmin =  susp.nb_events()
    assert nmin > nmin_prev
    assert nmin > 100 
    ## test reset all
    susp.reset_all_events()
    assert susp.nb_events() == 0
    ## Test reloading the divisions from the track graph
    susp.get_divisions()
    assert susp.nb_events() == nev
    ## Track feature change test
    susp.check_size.setChecked( True )
    susp.inspect_tracks()
    assert susp.nb_events() > nmin

def test_boundaries():
    test_img = os.path.join(".", "data_test", "003_crop.tif")
    test_seg = os.path.join(".", "data_test", "003_crop_epyseg.tif")

    ## load and initialize
    epic = epi.EpiCure()
    epic.load_movie(test_img)
    epic.go_epicure("test_epics", test_seg)

    ## check that doesn't find any boundary cells (touching background)
    epic.inspecting.get_boundaries_cells()
    assert len(epic.inspecting.boundary_cells[0]) == 0

    ## remove the border cells, so now should find boundary cells
    epic.editing.remove_border()
    epic.inspecting.get_boundaries_cells()
    assert len(epic.inspecting.boundary_cells[0]) > 20

#test_suspect_track()
#test_boundaries()
