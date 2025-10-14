import numpy as np
import os
import epicure.epicuring as epi

def test_track_methods():

    test_img = os.path.join(".", "data_test", "003_crop.tif")
    test_seg = os.path.join(".", "data_test", "003_crop_epyseg.tif")

    ## load and initialize
    epic = epi.EpiCure()
    epic.load_movie(test_img)
    epic.go_epicure("test_epics", test_seg)
    
    assert epic.tracked == 0
    assert epic.nlabels() == 2842

    track = epic.tracking
    # default tracking
    track.do_tracking()
    assert epic.nlabels() == 347
    assert epic.nlabels() == track.nb_tracks()
    assert track.graph is not None
    assert 1170 in track.graph.keys()
    assert track.graph[855] == [80, 83]
    assert not track.check_gap()

    track.track_choice.setCurrentText("Laptrack-Overlaps")
    track.do_tracking()
    assert epic.nlabels() == track.nb_tracks()
    assert track.graph is not None
    assert epic.nlabels() == 309
    assert not track.check_gap()

    track.reset_tracks()
    assert epic.nlabels() == 309
    assert epic.nlabels() == track.nb_tracks()

    ## check one track validity
    track_id = track.get_track_list()[20]
    assert track_id == 21
    assert track.get_first_frame( track_id ) == 0
    feats = track.measure_track_features( track_id )
    assert feats["TrackDuration"] == 8

    last = track.get_last_frame(track_id)
    track.remove_one_frame( track_id, last )
    newlast = track.get_last_frame(track_id)
    assert last == newlast+1

    ## create a gap in the middle of the track, then fix it (split the track)
    midle = track.get_first_frame(track_id) + 2
    track.remove_one_frame( track_id, midle )
    gaped = track.check_gap()
    ## gaps are allowed now
    assert len(gaped) > 0
    epic.handle_gaps( None )
    assert track.nb_tracks() == 310

#track_methods()
#test_track_methods()