import numpy as np
import os
import epicure.epicuring as epi

def test_get_free_label():
    ## test from a skeletonized movie
    test_mov = os.path.join(".", "data_test", "003_crop.tif")
    test_seg = os.path.join(".", "data_test", "003_crop_epyseg.tif")
    epic = epi.EpiCure()
    epic.load_movie(test_mov)
    #epic.viewer = napari.Viewer(show=False)
    epic.go_epicure("epics", test_seg)
    assert len(epic.get_free_labels(5)) == 5
    assert len(epic.get_free_labels(15)) == 15
    epic = None
    
    ## test from a label image
    test_img = os.path.join(".", "data_test", "170119_crop.tif")
    test_seg = os.path.join(".", "data_test", "170119_crop_mask.tif")
    epic = epi.EpiCure()
    epic.load_movie(test_img)
    epic.go_epicure("epics", test_seg)
    assert (5 == epic.get_free_labels(5)[0])
    assert 5 == epic.get_free_labels(1)[0]
    assert len(epic.get_free_labels(5)) == 5
    assert len(epic.get_free_labels(15)) == 15
    epic = None

