import numpy as np
import epicure.concatenate_movie as cm
import napari
import os
import epicure.epicuring as epi


def test_process_first_movie():
    main_dir = os.path.join(".", "data_test", "splitted")
    img = os.path.join( main_dir, "013-t1-t4.tif" )
    seg = os.path.join( main_dir, "013-t1-t4_epyseg.tif" )

    print("Open first movie")
    epic = epi.EpiCure()
    epic.load_movie( img )
    assert epic.img.shape == (4, 168, 219)
    assert epic.viewer is not None
    assert epic.nframes == 4

    print("Load epyseg segmentation")
    epic.go_epicure( "epics", seg )
    assert epic.tracked == 0
    assert epic.nlabels() == 494

    print("Remove border cells")
    epic.editing.remove_border()
    assert epic.nlabels() == 275
    print(epic.get_labels())

    print("Assign some cells to groups")
    epic.reset_groups()
    epic.cells_ingroup(17, "Bing")
    epic.cells_ingroup(42, "Bing")
    epic.cells_ingroup(142, "Bang")
    epic.cells_ingroup(143, "Bang")

    print("Do tracking with default parameters")
    epic.tracking.do_tracking()
    assert epic.nlabels() == 73

    print("Generate suspect list")
    epic.inspecting.inspect_tracks()
    assert len(epic.inspecting.events.data) == 4

    epic.save_epicures()
    assert os.path.exists(os.path.join( main_dir, "epics", "013-t1-t4_labels.tif") )
    assert os.path.exists(os.path.join( main_dir, "epics", "013-t1-t4_epidata.pkl") )

def test_process_second_movie():
    main_dir = os.path.join(".", "data_test", "splitted")
    img = os.path.join( main_dir, "013-t4-t6.tif" )
    seg = os.path.join( main_dir, "013-t4-t6_epyseg.tif" )
    
    print("Open second movie")
    epic = epi.EpiCure()
    epic.viewer = napari.Viewer(show=False)
    epic.load_movie( img )
    assert epic.img.shape == (3, 168, 219)
    assert epic.viewer is not None
    
    epic.go_epicure( "epics", seg )
    assert epic.tracked == 0
    assert epic.nlabels() == 371
    
    epic.tracking.do_tracking()
    epic.reset_groups()
    epic.cells_ingroup(21, "Bing")
    epic.cells_ingroup(22, "BAM")
    epic.save_epicures()
    assert os.path.exists(os.path.join( main_dir, "epics", "013-t4-t6_labels.tif") )
    assert os.path.exists(os.path.join( main_dir, "epics", "013-t4-t6_epidata.pkl") )


def test_merge_movies():
    main_dir = os.path.join(".", "data_test", "splitted")
    img1 = os.path.join( main_dir, "013-t1-t4.tif" )
    lab1 = os.path.join( main_dir, "epics", "013-t1-t4_labels.tif" )
    img2 = os.path.join( main_dir, "013-t4-t6.tif" )
    lab2 = os.path.join( main_dir, "epics", "013-t4-t6_labels.tif" )

    cm.merge_epicures( img1, lab1, img2, lab2, "together.tif")
    assert os.path.exists(os.path.join( main_dir, "together.tif") )
    assert os.path.exists(os.path.join( main_dir, "epics", "together_labels.tif") )
    assert os.path.exists(os.path.join( main_dir, "epics", "together_epidata.pkl") )
    
    img = os.path.join( main_dir, "together.tif" )
    seg = os.path.join( main_dir, "epics", "together_labels.tif" )
    epic = epi.EpiCure()
    epic.viewer = napari.Viewer(show=False)
    epic.load_movie( img )
    assert epic.img.shape == (6, 168, 219)

    epic.go_epicure( "epics", seg )
    assert len(epic.groups.keys()) == 3
    assert 142 in epic.groups["Bang"]
    assert 23 in epic.groups["Bing"]
    
    assert epic.tracked == 1
    epic.outputing.output_mode.setCurrentIndex(1)
    epic.outputing.show_trackfeature_table()
    assert "Label" in epic.outputing.trackTable.get_features_list()
    assert "TrackDuration" in epic.outputing.trackTable.get_features_list()
    headers = [epic.outputing.trackTable.wid_table.horizontalHeaderItem(ind).text() for ind in range(epic.outputing.trackTable.wid_table.columnCount()) ]
    durind = headers.index("TrackDuration")
    assert int(epic.outputing.trackTable.wid_table.item(20, durind).text()) == 6



#process_first_movie()
#process_second_movie()

#test_merge_movies()
