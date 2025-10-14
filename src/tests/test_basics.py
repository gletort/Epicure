import numpy as np
import os
import epicure.epicuring as epi

def test_load_movie():
    test_img = os.path.join(".", "data_test", "003_crop.tif")
    epic = epi.EpiCure()
    epic.load_movie(test_img)
    assert epic.img.shape == (11,208,426)

def test_load_movie_with_chanel():
    test_img = os.path.join(".", "data_test", "area3_t100-101.tif")
    test_seg = os.path.join(".", "data_test", "area3_epyseg-t100-101.tif")
    epic = epi.EpiCure()
    resaxis, resval = epic.load_movie(test_img)
    assert epic.img.shape == (2,2,384,394)
    assert resaxis == 1
    assert resval == 2
    assert np.mean(epic.img)>=268
    epic.set_chanel(1, 1)
    assert np.mean(epic.img)<268
    assert np.mean(epic.img)>100

def test_load_segmentation():
    test_seg = os.path.join(".", "data_test", "003_crop_epyseg.tif")
    epic = epi.EpiCure()
    epic.load_segmentation(test_seg)
    assert epic.seg.shape == (11,208,426)
    assert np.max(epic.seg) == 2842

def test_suggest():
    test_img = os.path.join(".", "data_test", "003_crop.tif")
    epic = epi.EpiCure()
    epic.load_movie(test_img)
    segfile = epic.suggest_segfile("epics")
    assert segfile is None
    test_img = os.path.join(".", "data_test", "170119_crop.tif")
    epic.load_movie(test_img)
    segfile = epic.suggest_segfile("epics")
    assert segfile == os.path.join(".", "data_test", "epics", "170119_crop_labels.tif")

def test_init_epic():
    epic = epi.EpiCure()
    assert epic.img is None

#if __name__ == "__main__":
#    test_init_epic()
#    print("********* Test cure completed ***********")

#test_load_movie_with_chanel()
