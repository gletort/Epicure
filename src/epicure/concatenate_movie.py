import napari
from napari import current_viewer
from magicgui import magicgui
from napari.utils.history import get_save_history, update_save_history 
import pathlib
import epicure.Utils as ut
import numpy as np
import os
import pandas as pd
from epicure.laptrack_centroids import LaptrackCentroids
from skimage.measure import regionprops_table

from epicure.epicuring import EpiCure
from epicure.tracking import Tracking


"""
    Concatenate temporally two epicured movies (the intensity movie and the labels).
    The last frame of the first movie should be the same as the first frame of the second movie.
"""
    
def merge_epicures( first_movie, first_labels, second_movie, second_labels, fullname="fullmovie.tif" ):
    """ Do the concatenation """

    ## open the two intensity movies
    ut.show_info("Reading and concatenating the intensity movies...")
    
    print("Reading first movie and EpiCure files")
    ## open the first movie and epicure data
    first_epicure = EpiCure()
    first_epicure.viewer = napari.Viewer(show=False)
    first_epicure.load_movie( first_movie )
    first_epicure.go_epicure( "epics", first_labels )

    ## open the second movie
    print("Reading second movie and EpiCure files")
    second_epicure = EpiCure()
    second_epicure.viewer = napari.Viewer(show=False)
    second_epicure.load_movie( second_movie )
    second_epicure.go_epicure( "epics", second_labels )
    
    ## check that the last frame of first movie and first frame of second are the same
    if np.sum(first_epicure.img[first_epicure.nframes-1] - second_epicure.img[0]) != 0:
        ut.show_error("Error: the last frame of first movie is not the same of the first frame of the second movie, I cannot concatenate them.")
        return
    
    ## create the full movie
    full_mov = np.concatenate( (first_epicure.img, second_epicure.img[1:]), axis=0 )
    full_movie_name = os.path.join(os.path.dirname(first_epicure.imgpath), fullname) 
    ut.writeTif( full_mov, full_movie_name, first_epicure.epi_metadata["ScaleXY"], first_epicure.img.dtype, what="Full movie") 
    print("Full movie created")

    ###### Read and merge the EpiCure data and merge the movie labels
    ut.show_info("Reading and concatenating the Epicured results...")

    ### Create new EpiCure instance with the full movie
    epic = EpiCure()
    epic.viewer = napari.current_viewer()
    epic.load_movie(full_movie_name)
    epic.verbose = 1
    epic.set_names( "epics" )
    
    ## initialize groups to first movie groups
    epic.groups = first_epicure.groups
    
    ## initialize tracks to first movie tracks
    epic.tracking = Tracking(epic.viewer, epic)
    epic.tracking.track_data = first_epicure.tracking.track_data

    ## initialize track graph to first movie graph
    if first_epicure.tracking.graph is not None:
        epic.tracking.graph = first_epicure.tracking.graph
    else:
        epic.tracking.graph = {}

    ### Now, work on the labels
        
    ## track between last and first frame to associate the labels (can be a little different if corrections were done)
    parent_labels, labels = ut.match_labels( first_epicure.seg[first_epicure.nframes-1], second_epicure.seg[0] )
        
    #### Update all the labels in the second movie to match with the first movie
    nextlabels = first_epicure.get_free_labels(20)  ## prepare a list of unused labels
    used_labels = first_epicure.get_labels()
    used_labels = used_labels + nextlabels
    seconds = np.copy(second_epicure.seg)
    seconds_lab = np.unique(seconds)
    #second_tracks = np.copy(second_epicure.tracking.track_data)
    if second_epicure.tracking.graph is None:
        second_epicure.tracking.graph = {}
    second_graph = second_epicure.tracking.graph.copy()
    ## shift all values and keys in the graph, to be sure it's never the same
    shift = np.max(second_epicure.seg)+1
    keys = list(second_graph.keys())
    for key in keys:
        val = second_graph.pop(key)
        shift_val = []
        for v in val:
            shift_val.append(v+shift)
        second_graph[key+shift] = shift_val

    for lab in seconds_lab:
        if lab > 0:
            newlab = None
            if lab in labels:
                newlab = parent_labels[labels.index(lab)]
                #track_indexes = second_epicure.tracking.get_track_indexes( lab )
                ## Label from second movie has been associated to one from first movie
                if newlab is not None:
                    ### If the label is in one group in first or second movie, update its info in full movie
                    fullmovie_group( epic, newlab, lab, second_epicure )
                    np.place(second_epicure.seg, seconds==lab, newlab)
                    #second_tracks[track_indexes, 0] = newlab
            if newlab is None:
                ## Label is a new cell (not present in first movie)
                nextlabel = nextlabels.pop(0)
                np.place(second_epicure.seg, seconds==lab, nextlabel)
                newlab = nextlabel
                #second_tracks[track_indexes, 0] = nextlabel
                ### add group information if there is one
                if second_epicure.groups is not None:
                    second = second_epicure.find_group( lab )
                    if second is not None:
                        epic.cells_ingroup( [nextlabel], second )
                if len(nextlabels) <= 0:
                    ## the list of unused labels has been completly used, regenerates
                    nextlabels = ut.get_free_labels( used_labels, 20 )
                    used_labels = used_labels + nextlabels

            # add division or merge if lab is in second movie graph
            if (shift+lab) in second_graph.keys():
                second_graph[newlab] = second_graph[shift+lab]
            for key, vals in second_graph.items():
                new_vals = []
                for val in vals:
                    if (shift+lab) == val:
                        new_vals.append( newlab )
                    else:
                        new_vals.append( val )
                second_graph[key] = new_vals

    ### merge the two graphs
    for key, vals in second_graph.items():
        if key not in epic.tracking.graph.keys():
            epic.tracking.graph[key] = vals
        else:
            print("Key "+str(key)+" present in both graph, something might be wrong ")

    ### Ok, save the results
    full_lab = np.concatenate( (first_epicure.seg, second_epicure.seg[1:]), axis=0 )
    epic.seg = full_lab
    epic.save_epicures()
    print("Movie and EpiCure files merged; Suspects/Events (if any) are not merged, use inspect tracks on merged movie to generate them")

def fullmovie_group( epic, first_label, second_label, second_epicure ):
    """ Check if second_label is in a group, and add it to full movie groups if relevant """
    first_group = epic.find_group( first_label )
    second = None
    if second_epicure.groups is not None:
        second = second_epicure.find_group( second_label )
    if (first_group is not None) and (second is not None):
        ### label is present in the two movie groups
        if first_group != second:
            print("Label "+str(first_label)+" classified in group "+(first_group)+" in the first movie and in group "+second+" in the second movie")
            print("Keep only the first movie group: "+first_group)
    else:
        if second is not None:
            epic.cells_ingroup( [first_label], second )

def concatenate_movies():
    hist = get_save_history()
    cdir = hist[0]
    viewer = current_viewer()

    def choose_first_movie():
        """ First movie is chosen, suggest default labels file """
        first = get_files.first_movie.value
        imgname, imgdir, out = ut.extract_names( first, "epics", mkdir=False )
        get_files.first_labels.value = pathlib.Path(out)
        labname = ut.suggest_segfile(out, imgname)
        if labname is not None:
            get_files.first_labels.value = pathlib.Path(labname)
    
    def choose_second_movie():
        """ Second movie is chosen, suggest default labels file """
        second = get_files.second_movie.value
        imgname, imgdir, out = ut.extract_names( second, "epics", mkdir=False )
        get_files.second_labels.value = pathlib.Path(out)
        labname = ut.suggest_segfile(out, imgname)
        if labname is not None:
            get_files.second_labels.value = pathlib.Path(labname)
    
    @magicgui(call_button="Concatenate",)
    def get_files(
            first_movie = pathlib.Path(cdir),
            first_labels = pathlib.Path(cdir),
            second_movie = pathlib.Path(cdir),
            second_labels = pathlib.Path(cdir),
            merged_movie_name = "fullmovie.tif"
            ):
        merge_epicures( first_movie, first_labels, second_movie, second_labels, merged_movie_name)
        return
    
    get_files.first_movie.changed.connect(choose_first_movie)
    get_files.second_movie.changed.connect(choose_second_movie)
    return get_files
