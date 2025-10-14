import numpy as np
import os
import epicure.epicuring as epi
import epicure.Utils as ut
from unittest.mock import Mock
import napari
from vispy import keys

def test_epicuring_bindings():
    test_img = os.path.join(".", "data_test", "003_crop.tif")
    test_seg = os.path.join(".", "data_test", "003_crop_epyseg.tif")
    viewer = napari.Viewer(show=False)
    epic = epi.EpiCure(viewer)
    epic.load_movie(test_img)
    epic.go_epicure("test_epics", test_seg)
    assert epic.viewer is not None
    ut.set_active_layer(epic.viewer, "Segmentation")
    view = epic.viewer.window.qt_viewer
    view.canvas.events.key_press(key=keys.Key("b"), modifiers=[])
    assert epic.viewer.layers["Segmentation"].visible == False
    view.canvas.events.key_press(key=keys.Key("b"), modifiers=[])
    assert epic.viewer.layers["Segmentation"].visible == True
    view.canvas.events.key_press(key=keys.Key("v"), modifiers=[])
    assert epic.viewer.layers["Movie"].visible == False
    view.canvas.events.key_press(key=keys.Key("v"), modifiers=[])
    assert epic.viewer.layers["Movie"].visible == True
    view.canvas.events.key_press(key=keys.Key("c"), modifiers=[])
    assert epic.viewer.layers["Movie"].visible == True
    assert epic.viewer.layers["Segmentation"].visible == False
    view.canvas.events.key_press(key=keys.Key("g"), modifiers=[])
    assert "EpicGrid" in epic.viewer.layers
    
def test_merge():
    test_img = os.path.join(".", "data_test", "003_crop.tif")
    test_seg = os.path.join(".", "data_test", "003_crop_epyseg.tif")
    viewer = napari.Viewer(show=False)
    epic = epi.EpiCure(viewer)
    epic.load_movie(test_img)
    epic.load_segmentation(test_seg)
    epic.go_epicure("test_epics", test_seg)
    assert epic.viewer is not None

    segedit = epic.editing
    assert segedit is not None
    val = epic.seglayer.data[0,93,167]
    assert val == 111
    ## check that not touching labels do not merge
    segedit.merge_labels( 0, 111, 134 )
    val = epic.seglayer.data[0,93,167]
    assert val == 111
    segedit.merge_labels( 0, 111, 102 )
    val = epic.seglayer.data[0,93,167]
    ## new label because no propagation
    assert val == 2844
    

def test_group():
    test_img = os.path.join(".", "data_test", "003_crop.tif")
    test_seg = os.path.join(".", "data_test", "003_crop_epyseg.tif")
    viewer = napari.Viewer(show=False)
    epic = epi.EpiCure(viewer)
    epic.load_movie(test_img)
    epic.go_epicure("test_epics", test_seg)
    imname, imdir, outdir = ut.extract_names( test_img, "epics" )
    assert epic.viewer is not None
    layer = epic.viewer.layers["Segmentation"]
    
    epic.cells_ingroup( 111, "Test" )
    assert "Test" in epic.groups

    segedit = epic.editing
    event = napari.utils.events.Event("mouse_press") #viewer.window.qt_viewer.canvas.events.mouse_press(pos=(1, 2), modifiers=('Shift'), button=1)
    event.position = [0,10,20]
    event.view_direction = None
    event.dims_displayed = [0,1, 1] 
    assert "GroupTest" not in epic.groups
    segedit.group_choice.setCurrentText("GroupTest")
    segedit.add_cell_to_group(event)
    assert "GroupTest" in epic.groups
    


