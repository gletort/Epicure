from qtpy.QtWidgets import QVBoxLayout, QWidget # type: ignore
from epicure.laptrack_centroids import LaptrackCentroids
laptrack_over = False
try:    
    from epicure.laptrack_overlaps import LaptrackOverlaps
    laptrack_over = True
except ImportError:
    print("Laptrack overlap not available in your laptrack version. Only the centroid option will be proposed. Update laptrack to 0.16 to have it")
    pass
from laptrack.data_conversion import convert_split_merge_df_to_napari_graph # type: ignore
from napari.utils import progress # type: ignore
from skimage.transform import warp
from skimage.registration import optical_flow_ilk
import pandas as pd
import numpy as np
import scipy.ndimage as ndi
import epicure.Utils as ut
import epicure.epiwidgets as wid
from joblib import Parallel, delayed

class Tracking(QWidget):
    """
        Handles tracking of cells, track operations with the Tracks layer
    """
    def __init__(self, napari_viewer, epic):
        super().__init__()
        self.viewer = napari_viewer
        self.epicure = epic
        self.graph = None      ## init 
        self.tracklayer = None      ## track layer with information (centroids, labels, tree..)
        self.track_data = None ## keep the updated data, and update the layer only from time to time (slow to do)
        self.tracklayer_name = "Tracks"  ## name of the layer containing tracks
        self.nframes = self.epicure.nframes
        self.properties = ["label", "centroid"]

        layout = QVBoxLayout()
        
        ## Add update track button 
        self.track_update = wid.add_button( "Update tracks display", self.update_track_layer, "Update the Track layer with the changements made since the last update" )
        layout.addWidget(self.track_update)
        
        ## Correct track button 
        #track_reset = wid.add_button( "Correct track data", self.reset_tracks, "Correct the track data after some track was lost" )
        #layout.addWidget(track_reset)

        ## Method specific
        track_method, self.track_choice = wid.list_line( "Tracking method", "Choose the tracking method to use and display its parameter", func=None )
        layout.addWidget(self.track_choice)
        
        self.track_choice.addItem("Laptrack-Centroids")
        self.create_laptrack_centroids()
        layout.addWidget(self.gLapCentroids)

        if laptrack_over: 
            self.track_choice.addItem("Laptrack-Overlaps")
            self.create_laptrack_overlap()
            layout.addWidget(self.gLapOverlap)
        else:
            self.min_iou = None
            self.split_cost = None
            self.merg_cost = None

        drift_layout, self.drift_correction, self.drift_radius = wid.check_value( check="With drift correction", checked=False, value=str(50), descr="Taking into account local drift in tracking calculations") 
        layout.addLayout( drift_layout )
        
        self.track_go = wid.add_button( "Track", self.do_tracking, "Launch the tracking with the current parameter. Can take time" )
        layout.addWidget(self.track_go)
        self.setLayout(layout)

        ## General tracking options
        frame_line, self.frame_range, self.range_group = wid.checkgroup_help( "Track only some frames", False, "Option to track only a given range of frames", None ) 
        self.frame_range.clicked.connect( self.show_frame_range )
        range_layout = QVBoxLayout()
        ntrack, self.start_frame = wid.ranged_value_line( "Track from frame:", 0, self.nframes-1, 1, 0, "Set first frame to begin tracking" )
        range_layout.addLayout(ntrack)
        
        entrack, self.end_frame = wid.ranged_value_line( "Until frame:", 1, self.nframes-1, 1, self.nframes-1, "Set the last frame unitl which to track" )
        range_layout.addLayout(entrack)
        self.start_frame.valueChanged.connect( self.changed_start )
        self.end_frame.valueChanged.connect( self.changed_end )
        
        self.range_group.setLayout( range_layout )
        layout.addWidget( self.frame_range )
        layout.addWidget( self.range_group )
        
        self.show_frame_range()
        self.show_trackoptions()
        self.track_choice.currentIndexChanged.connect(self.show_trackoptions)
        

    def show_frame_range( self ):
        """ Show/Hide frame range options """
        self.range_group.setVisible( self.frame_range.isChecked() )
        
    #### settings

    def get_current_settings( self ):
        """ Get current settings to save as preferences """
        settings = {}
        settings["Track method"] = self.track_choice.currentText() 
        settings["Add feat"] = self.check_penalties.isChecked()
        settings["Max distance"] = self.max_dist.text()
        settings["Splitting cost"] = self.splitting_cost.text()
        settings["Merging cutoff"] = self.merging_cost.text()
        settings["Min IOU"] = self.min_iou.text()
        settings["Over split"] = self.split_cost.text()
        settings["Over merge"] = self.merg_cost.text()
        return settings

    def apply_settings( self, settings ):
        """ Set the parameters/current display from the prefered settings """
        for setty, val in settings.items():
            if setty == "Track method":
                self.track_choice.setCurrentText( val )
            if setty == "Add feat":
                self.check_penalties.setChecked( val )
            if setty == "Max distance":
                self.max_dist.setText( val )
            if setty == "Splitting cost":
                self.splitting_cost.setText( val )
            if setty == "Merging cutoff":
                self.merging_cost.setText( val )
            if laptrack_over:
                if setty == "Min IOU":
                    self.min_iou.setText( val )
                if setty == "Over split":
                    self.split_cost.setText( val )
                if setty == "Over merge":
                    self.merg_cost.setText( val )
            
    ##########################################
    #### Tracks layer and function

    def reset( self ):
        """ Reset Tracks layer and data """
        self.graph = None
        self.track_data = None
        ut.remove_layer( self.viewer, "Tracks" )

    def init_tracks(self):
        """ Add a track layer with the new tracks """
        track_table, track_prop = self.create_tracks()
        
        ## plot tracks
        if len(track_table) > 0:
            self.clear_graph()
            self.viewer.add_tracks(
                track_table,
                graph=self.graph, 
                name=self.tracklayer_name,
                properties = track_prop,
                scale = self.viewer.layers["Segmentation"].scale,
                )
            self.viewer.layers[self.tracklayer_name].visible=True
            self.viewer.layers[self.tracklayer_name].color_by="track_id"
            ut.set_active_layer(self.viewer, "Segmentation")
            self.tracklayer = self.viewer.layers[self.tracklayer_name]
            self.track_data = self.tracklayer.data
            #self.track.display_id = True
            self.color_tracks_as_labels()

    def color_tracks_as_labels(self):
        """ Color the tracks the same as the label layer """
        ## must color it manually by getting the Label layer colors for each track_id
        cols = np.zeros((len(self.tracklayer.data[:,0]),4))
        for i, tr in enumerate(self.tracklayer.data[:,0]):
            cols[i] = (self.epicure.seglayer.get_color(tr))
        self.tracklayer._track_colors = cols
        self.tracklayer.events.color_by()
    
    def color_tracks_by_lineage(self):
        """ Color the tracks by their lineage (daughters same colors as parents) """
        ## must color it manually by getting the Label layer colors for each track_id
        cols = np.zeros((len(self.tracklayer.data[:,0]),4))
        for i, tr in enumerate(self.tracklayer.data[:,0]):
            ## find the parent cell,n going up the tree until no more parent
            while tr in self.graph.keys():
                tr = self.graph_parent( tr )
            cols[i] = (self.epicure.seglayer.get_color(tr))
        self.tracklayer._track_colors = cols
        self.tracklayer.events.color_by()

    def graph_parent( self, ind ):
        """ Get the value of the parent from the graph """
        if ind not in self.graph.keys():
            return None
        if isinstance(self.graph[ind], list):
            return self.graph[ind][0]
        return self.graph[ind]

    def replace_tracks(self, track_df):
        """ Replace all tracks based on the dataframe """
        if not self.undrifted and self.drift_correction.isChecked():
            ## recalculate the label centroids as it was corrected for drift
            track_table, track_prop = self.create_tracks()
        else:
            track_table, track_prop = self.build_tracks( track_df )
        self.tracklayer.data = track_table
        self.track_data = self.tracklayer.data
        self.tracklayer.properties = track_prop
        self.tracklayer.refresh()
        self.color_tracks_as_labels()

    def reset_tracks(self):
        """ Reset tracks and reload them from labels """
        ut.remove_layer(self.viewer, "Tracks")
        self.init_tracks()

    def update_track_layer(self):
        """ Update the track layer (slow) """
        self.viewer.window._status_bar._toggle_activity_dock(True)
        progress_bar = progress(total=1)
        progress_bar.set_description( "Updating track layer" )
        self.tracklayer.data = self.track_data
        progress_bar.close()
        self.color_tracks_as_labels()
        self.viewer.window._status_bar._toggle_activity_dock(False)

    def measure_intensity_features( self, feat, intimg=None, frames=None ):
        """ Measure mean value of a feature in a track """
        if ( intimg is not None ):
            if frames is None:
                tracks = self.get_track_list()
                seg = self.epicure.seg
                iimg = intimg
            else:
                tracks = self.get_tracks_list_frames( frames )
                seg = self.epicure.seg[frames]
                iimg = intimg[frames]
        if feat == "intensity_mean":
            mean_intensities = ndi.mean( iimg, seg, tracks )
            return tracks, mean_intensities
        if feat == "intensity_sum":
            sum_intensities = ndi.sum( iimg, seg, tracks )
            return tracks, sum_intensities
        if feat == "intensity_max":
            sum_intensities = ndi.maximum( iimg, seg, tracks )
            return tracks, sum_intensities
        if feat == "intensity_min":
            sum_intensities = ndi.minimum( iimg, seg, tracks )
            return tracks, sum_intensities
        if feat == "intensity_median":
            sum_intensities = ndi.median( iimg, seg, tracks )
            return tracks, sum_intensities
        print( "Mean feature on track not implemented" )
        return None

    def measure_track_features( self, track_id, scaling=False ):
        """ Measure features (length, total displacement...) of given track """
        features = {}
        track = self.get_track_data( track_id )
        if track.shape[0] == 0:
            return features
        track = track[track[:,1].argsort()]
        start = int(np.min(track[:,1]))
        end = int(np.max(track[:,1]))
        temp_unit = ""
        vel_unit = ""
        disp_unit = ""
        temp_scale = 1
        vel_scale = 1
        disp_scale = 1
        if scaling:
            temp_unit = "_"+self.epicure.epi_metadata["UnitT"]
            vel_unit = "_"+self.epicure.epi_metadata["UnitXY"]+"/"+self.epicure.epi_metadata["UnitT"]
            disp_unit = "_"+self.epicure.epi_metadata["UnitXY"]
            temp_scale = self.epicure.epi_metadata["ScaleT"]
            vel_scale = self.epicure.epi_metadata["ScaleXY"]/self.epicure.epi_metadata["ScaleT"]
            disp_scale = self.epicure.epi_metadata["ScaleXY"]
        features["Label"] = track_id
        features["TrackDuration"+temp_unit] = (end - start + 1)*temp_scale
        features["TrackStart"+temp_unit] = start * temp_scale
        features["TrackEnd"+temp_unit] = end * temp_scale
        features["NbGaps"] = end - start + 1 - len(track)
        if (end-start) == 0:
            ## only one frame
            features["TotalDisplacement"+disp_unit] = None
            features["NetDisplacement"+disp_unit] = None
            features["Straightness"] = None
            features["MeanVelocity"+vel_unit] = None
        else:
            features["TotalDisplacement"+disp_unit] = ut.total_distance( track[:,2:4] ) * disp_scale
            features["NetDisplacement"+disp_unit] = ut.net_distance( track[:,2:4] ) * disp_scale
            features["MeanVelocity"+vel_unit] = np.mean( ut.velocities( track[:,1:4] ) ) * vel_scale 
            if features["TotalDisplacement"+disp_unit] > 0:
                features["Straightness"] = features["NetDisplacement"+disp_unit]/features["TotalDisplacement"+disp_unit]
            else:
                features["Straightness"] = None
        return features

    def measure_speed( self, track_id ):
        """ Returns the velocities of the track """
        track = self.get_track_data( track_id )
        if track.shape[0] == 0:
            return None 
        track = track[track[:,1].argsort()]
        return ut.velocities( track[:,1:4] )

    def measure_features( self, track_id, features ):
        """ Measure features along all the track """
        mask = self.epicure.get_mask( track_id )
        res = {}
        for feat in features:
            res[feat] = []
        for frame in mask:
            props = ut.labels_properties( frame )
            if len(props) > 0:
                if "Area" in features:
                    res["Area"].append( props[0].area )
                if "Hull" in features:
                    res["Hull"].append( props[0].area_convex )
                if "Elongation" in features:
                    res["Elongation"].append( props[0].axis_major_length )
                if "Eccentricity" in features:
                    res["Eccentricity"].append( props[0].eccentricity )
                if "Perimeter" in features:
                    res["Perimeter"].append( props[0].perimeter )
                if "Solidity" in features:
                    res["Solidity"].append( props[0].solidity )
        return res

    def measure_specific_feature( self, track_id, featureName ):
        """ Measure some specific feature """
        if featureName == "Similarity":
            import skimage.metrics as imetrics
            movie = self.epicure.get_label_movie( track_id, extend=1.5 )
            sim_scores = []
            for i in range(0, len(movie)-1):
                score = imetrics.normalized_mutual_information( movie[i], movie[i+1] ) 
                sim_scores.append(score)
            return sim_scores

    def measure_labels(self, segimg):
        """ Get the dataframe of the labels in the segmented image """
        resdf = None
        for iframe, frame in progress(enumerate(segimg)):
            frame_table = ut.labels_to_table( frame, iframe )
            if resdf is None:
                resdf = pd.DataFrame(frame_table)
            else:
                resdf = pd.concat([resdf, pd.DataFrame(frame_table)])
        return resdf

    def add_track_frame(self, label, frame, centroid, tree=None, group=None):
        """ Add one frame to the track """
        new_frame = np.array([label, frame, centroid[0], centroid[1]])
        self.track_data = np.vstack((self.track_data, new_frame))
            
    def get_track_list(self):
        """ Get list of unique track_ids """
        return np.unique( self.track_data[:,0] )
    
    def get_tracks_list_frames( self, frames ):
        """ Return list of tracks present on list of frames """
        return np.unique( self.track_data[ np.isin( self.track_data[:,1], frames), 0] ) 
    
    def get_tracks_on_frame( self, tframe ):
        """ Return list of tracks present on given frame """
        return np.unique( self.track_data[ self.track_data[:,1]==tframe, 0] ) 

    def has_track(self, label):
        """ Test if track label is present """
        return label in self.track_data[:,0]
    
    def has_tracks(self, labels):
        """ Test if track labels are present """
        return np.isin( labels, self.track_data[:,0] )
    
    def nb_points(self):
        """ Number of points in the tracks """
        return self.track_data.shape[0]

    def nb_tracks(self):
        """ Return number of tracks """
        #return self.track._manager.__len__()
        return len(self.get_track_list())

    def gaped_track(self, track_id):
        """ Check if there is a gap (missing frame) in a track """
        indexes = self.get_track_indexes(track_id)
        if len(indexes) <= 0:
            return False
        track_frames = self.track_data[indexes,1]
        return ((np.max(track_frames)-np.min(track_frames)+1) > len(track_frames) )

    def gap_frames(self, track_id):
        """ Returns the frame(s) at which the gap(s) are """
        track_frames = self.get_track_column( track_id, "frame" )
        gaps = []
        if len( track_frames ) > 0:
            min_frame = int( np.min(track_frames) )
            max_frame = int( np.max(track_frames) )
            gaps = np.setdiff1d( np.arange(min_frame+1, max_frame), track_frames ).tolist()
            if len(gaps) > 0:
                gaps.sort()
        return gaps
            
    def check_gap(self, tracks=None, verbose=None):
        """ Check if there is a track with a gap, flag it if yes """
        if tracks is None:
            tracks = self.get_track_list()
        gaped = []
        for track in tracks:
            if self.gaped_track( track ):
                gaped.append(track)
        if verbose is None:
            verbose = self.epicure.verbose
        if verbose > 0 and len(gaped)>0:
            ut.show_warning("Gap in track(s) "+str(gaped)+"\n"
            +"Consider doing sanity_check in Editing onglet to fix it")
        return gaped

    def get_track_indexes(self, track_id):
        """ Get indexes of track_id tracks position in the arrays """
        if isinstance( track_id,  int ):
            return (np.flatnonzero( self.track_data[:,0] == track_id ) )
        return (np.flatnonzero( np.isin( self.track_data[:,0], track_id ) ) )
    
    def get_track_indexes_onframes( self, track_id, frames ):
        """ Get indexes of track_id tracks position in the arrays """
        if isinstance( frames, int ):
            frames = [frames]
        if isinstance( track_id,  int ):
            return (np.flatnonzero( (self.track_data[:,0] == track_id) * np.isin( self.track_data[:,1], frames) ) )
        return (np.flatnonzero( np.isin( self.track_data[:,0], track_id ) * np.isin( self.track_data[:,1], frames) ) )

    def get_track_indexes_from_frame(self, track_id, frame):
        """ Get indexes of track_id tracks position in the arrays from the given frame """
        if type(track_id) == int:
            return (np.argwhere( (self.track_data[:,0] == track_id)*(self.track_data[:,1]>= frame) )).flatten()
        return (np.argwhere( np.isin( self.track_data[:,0], track_id )*(self.track_data[:,1]>= frame) )).flatten()

    def get_index(self, track_id, frame ):
        """ Get index of track_id at given frame """
        if np.isscalar(track_id):
            track_id = [track_id]
        return np.argwhere( (np.isin(self.track_data[:,0], track_id))*(self.track_data[:,1] == frame) )

    def get_small_tracks(self, max_length=1):
        """ Get tracks smaller than the given threshold """
        labels = []
        lengths = []
        positions = []
        for lab in self.get_track_list():
            indexes = self.get_track_indexes(lab)
            length = len(indexes)
            if length <= max_length:
                pos = self.mean_position( indexes, only_first=False )
                labels.append(lab)
                lengths.append(length)
                positions.append(pos)
        return labels, lengths, positions

    def get_track_data(self, track_id):
        """ Return the data of track track_id """
        indexes = self.get_track_indexes( track_id )
        track = self.track_data[indexes,]
        return track
    
    def get_track_column( self, track_id, column ):
        """ Return the chosen column (frame, x, y, label) of track track_id """
        indexes = self.get_track_indexes( track_id )
        if column == "frame":
            return self.track_data[indexes, 1]
        if column == "label":
            return self.track_data[indexes, 0]
        if column == "pos":
            return self.track_data[indexes, 2:4]
        if column == "fullpos":
            return self.track_data[indexes, 1:4]
        track = self.track_data[indexes]
        return track

    def get_frame_data( self, track_id, ind ):
        """ Get ind-th data of track track_id """
        track = self.get_track_data( track_id )
        return track[ind]
    
    def get_middle_position( self, track_id, framea, frameb ):
        """ Get track position in middle of frame a and frame b """
        inda = self.get_index( track_id, framea ) 
        indb = self.get_index( track_id, frameb )
        return self.mean_position( np.ravel( np.vstack((inda, indb)) ), only_first=False )

    def get_position( self, track_id, frame ):
        """ Get position of the track at given frame """
        ind = self.get_index( track_id, frame )
        return [int(self.track_data[ind, 2]), int(self.track_data[ind,3])]

    def get_full_position( self, track_id, frame ):
        """ Get position of the track at given frame, with the frame itself """
        ind = self.get_index( track_id, frame )
        return [frame, int(self.track_data[ind, 2]), int(self.track_data[ind,3])]

    def mean_position(self, indexes, only_first=False):
        """ Mean positions of tracks at indexes """
        if len(indexes) <= 0:
            return None
        track = self.track_data[indexes,]
        ## keep only the first frame of the tracks
        if only_first:
            min_frame = np.min(track[:,1])
            track = track[track[:,1]==min_frame,]
        return ( int(np.mean(track[:,1])), int(np.mean(track[:,2])), int(np.mean(track[:,3])) )

    def get_first_frame(self, track_id):
        """ Returns first frame where track_id is present """
        track = self.get_track_data( track_id )
        if len(track) <= 0:
            return None
        return int( np.min(track[:,1]) )

    def is_in_frame( self, track_id, frame ):
        """ Returns if track_id is present at given frame """
        track = self.get_track_data( track_id )
        if len(track) > 0:
            return frame in track[:,1]
        return False
    
    def get_last_frame(self, track_id):
        """ Returns last frame where track_id is present """
        track = self.get_track_data( track_id )
        if len(track) > 0:
            return int(np.max(track[:,1]))
        return None
    
    def get_extreme_frames(self, track_id):
        """ Returns the first and last frames where track_id is present """
        track = self.get_track_data( track_id )
        if track.shape[0] > 0:
            return (int(np.min(track[:,1])), int(np.max(track[:,1])) )
        return None, None

    def get_mean_position(self, track_id, only_first=False):
        """ Get mean position of the track """
        indexes = self.get_track_indexes( track_id )
        return self.mean_position( indexes, only_first )

    def update_centroid(self, track_id, frame, ind=None, cx=None, cy=None):
        """ Update track at given frame """
        if ind is None:
            ind = self.get_index( track_id, frame )
        if cx is None:
            prop = ut.getPropLabel( self.epicure.seg[frame], track_id )
            self.track_data[ind, 2:4] = prop.centroid[1]
        else:
            self.track_data[ind, 2] = cx
            self.track_data[ind, 3] = cy

    def replace_on_frames( self, tids, new_tids, frames ):
        """ Replace the id tid by new_tid in all given frames """
        ind = self.get_track_indexes_onframes( tids, frames )
        cur_track = np.copy(self.track_data[ind])
        new_ids = np.repeat(-1, len(ind))
        for tid, new_tid in zip(tids, new_tids):
            self.update_graph_frames( tid, cur_track[cur_track[:,0]==tid,1] )
            new_ids[cur_track[:,0]==tid] = new_tid
        self.track_data[ind, 0] = new_ids
        
    def swap_frame_id(self, tid, otid, frame):
        """ Swap the ids of two tracks at frame """
        ind = int(self.get_index(tid, frame))
        oind = int(self.get_index(otid, frame))
        ## check if one of the label is an extreme of a track and potentially in the graph
        for track_index in [tid, otid]:
            min_frame, max_frame = self.get_extreme_frames( track_index )
            if (min_frame == frame) or (max_frame == frame):
                self.update_graph( track_index, frame )
        self.track_data[[ind, oind],0] = [otid, tid]

    def update_track_on_frame(self, track_ids, frame):
        """ Update (add or modify) tracks at given frame """
        frame_table = ut.labels_table( labimg = np.where(np.isin(self.epicure.seg[frame], track_ids), self.epicure.seg[frame], 0), properties=self.properties )
        for x, y, tid in zip(frame_table["centroid-0"], frame_table["centroid-1"], frame_table["label"]):
            index = self.get_index(tid, frame)
            if len(index) > 0:
                self.update_centroid( tid, frame, index, int(x), int(y) )
            else:
                cur_cell = np.array( [[tid, frame, int(x), int(y)]] )
                self.track_data = np.append(self.track_data, cur_cell, axis=0)

    def add_tracks_fromindices( self, indices, track_ids ):
        """ Add tracks of given track ids from the indices"""
        new_data = np.empty( (0,4), int )
        for tid in np.unique(track_ids):
            keep = track_ids == tid 
            for frame in np.unique( indices[0][keep] ):
                cent0 = np.mean( indices[1][keep] ) 
                cent1 = np.mean( indices[2][keep] ) 
                new_data = np.append( new_data, np.array([[tid, frame, int(cent0), int(cent1)]]), axis=0 )
        self.track_data = np.append( self.track_data, new_data, axis=0)
    
    def add_one_frame(self, track_ids, frame, refresh=True):
        """ Add one frame from track """
        for tid in track_ids:
            frame_table = ut.labels_table( np.uint8(self.epicure.seg[frame]==tid), properties=self.properties ) 
            cur_cell = np.array( [tid, frame, int(frame_table["centroid-0"]), int(frame_table["centroid-1"])], dtype=np.uint32 )
            cur_cell = np.expand_dims(cur_cell, axis=0)
            self.track_data = np.append(self.track_data, cur_cell, axis=0)

    def remove_one_frame( self, track_id, frame, handle_gaps=False, refresh=True ):
        """ 
        Remove one frame from track(s) 
        """
        inds = self.get_index( track_id, frame )
        if np.isscalar(track_id):
            track_id = [track_id]
        check_for_gaps = False
        for tid in track_id:
            ## removed frame is in the extremity of a track, can be in the graph
            first_frame, last_frame = self.get_extreme_frames( tid )
            if first_frame is None:
                continue
            if (first_frame == frame) or (last_frame == frame):
                self.update_graph( tid, frame )
            else:
                check_for_gaps = True
        self.track_data = np.delete( self.track_data, inds, axis=0 )
        ## gaps might have been created in the tracks, for now doesn't allow it so split the tracks
        if handle_gaps and check_for_gaps:
            gaped = self.check_gap( track_id, verbose=0 )
            if len(gaped) > 0:
                self.epicure.fix_gaps( gaped )
        
    def get_current_value(self, track_id, frame):
        ind = self.get_index(track_id, frame)
        centx, centy = self.track_data[ind, 2:4].astype(int).flatten()
        return self.epicure.seg[frame, centx, centy]

    def clear_graph( self ):
        """ Check the state of the graph and removes non existing keys or values """
        if self.graph is None:
            return
        keys = list(self.graph.keys())
        for key in keys:
            if key not in self.track_data[:,0]:
                del self.graph[key]
            else:
                vals = self.graph[key]
                if isinstance(vals, list):
                    for val in vals:
                        if val not in self.track_data[:,0]:
                            del self.graph[key]
                            break
                else:
                    if vals not in self.track_data[:,0]:
                        del self.graph[key]

    def update_graph_frames( self, track_id, frames ):
        """ Update graph when one label was deleted at given frames """
        fframe = np.min(frames)
        lframe = np.max(frames)
        self.update_graph( track_id, fframe )
        self.update_graph( track_id, lframe )

    def update_graph(self, track_id, frame):
        """ Update graph if deleted label was linked at that frame, assume keys are unique """
        if self.graph is not None:
            ## handles current node is last of his branch
            parents = self.last_in_graph( track_id, frame )
            current_label = self.get_current_value( track_id, frame )
            for parent in parents:
                if current_label == 0:
                    del self.graph[parent]
                else:
                    self.update_child( parent, track_id, current_label )
            ## handles when current track is first frame of a division
            if self.first_in_graph( track_id, frame ):
                if current_label == 0:
                    del self.graph[track_id]
                else:
                    self.update_key( track_id, current_label ) 

    def update_child(self, parent, prev_key, new_key):
        """ Change the value of a key in the graph """
        if isinstance(self.graph[parent], list):
            self.graph[parent] = [new_key if val == prev_key else val for val in self.graph[parent]]
        else:
            if self.graph[parent] == prev_key:
                self.graph[parent] = new_key

    def update_key(self, prev_key, new_key):
        """ Change the value of a key in the graph """
        self.graph[new_key] = self.graph.pop(prev_key)

    def is_parent( self, cur_id ):
        """ Return if the current id is in the graph (as a parent, so in values) """
        if self.graph is None:
            return False
        return any( cur_id in vals if isinstance(vals, list) else cur_id in [vals] for vals in self.graph.values() )

    def add_division( self, childa, childb, parent ):
        """ Add info of a division to the graph of divisions/merges """
        if self.graph is None:
            self.graph = {}
        self.graph.update({childa: [parent], childb: [parent]})

    def remove_division( self, parent ):
        """ Remove a division event from the graph """
        self.graph = {key: vals for key, vals in self.graph.items() if not ( self.graph_parent(key) == parent )  }

    def last_in_graph(self, track_id, frame=None, check_last=True):
        """ Check if given label and frame is the last of a branch, in the graph """
        if check_last:
            return [key for key, vals in self.graph.items() if track_id in (vals if isinstance(vals, list) else [vals]) and self.get_last_frame(track_id) == frame]
        return [key for key, vals in self.graph.items() if track_id in (vals if isinstance(vals, list) else [vals])]

    def first_in_graph(self, track_id, frame=None, check_first=True):
        """ Check if the given label and frame is the first in the branch so the node in the graph """
        if check_first:
            return track_id in self.graph and self.get_first_frame(track_id) == frame
        return track_id in self.graph

    def remove_on_frames( self, track_ids, frames ):
        """ Remove tracks with given id on specified frames """
        track_ids = track_ids.tolist()
        if 0 in track_ids:
            track_ids.remove(0)
        inds = self.get_track_indexes_onframes( track_ids, frames )
        for tid in track_ids:
            self.update_graph_frames( tid, frames )
        self.track_data = np.delete( self.track_data, inds, axis=0 )

    def remove_tracks(self, track_ids):
        """ Remove track with given id """
        inds = self.get_track_indexes(track_ids)
        self.track_data = np.delete(self.track_data, inds, axis=0)
        self.remove_ids_from_graph( track_ids )
    
    def remove_ids_from_graph( self, track_ids ):
        """ Remove all ids from the graph """
        track_ids_set = set( track_ids )
        self.graph = {
            key: vals for key, vals in self.graph.items()
            if (key not in track_ids_set) and ( not any( val in track_ids_set for val in (vals if isinstance(vals, list) else [vals])) )
        }
    
    def is_single_parent( self, cur_id ):
        """ Return if the current id is in the graph (as a single parent, not a merge) """
        if self.graph is None:
            return False
        return any( cur_id in [vals] if not isinstance(vals, list) else (cur_id in vals and len(vals)==1) for vals in self.graph.values() )

       
    def build_tracks(self, track_df):
        """ Create tracks from dataframe (after tracking) """
        track = track_df[["track_id", "frame", "centroid-0", "centroid-1"]]
        #frame_prop = frame_table[["tree_id", "label", "nframes", "group"]]
        return np.array(track, int), None #dict(frame_prop)

    def create_tracks(self):
        """ Create tracks from labels (without tracking) """
        #track_table = np.empty( (0,4), int )   
        labels = self.epicure.seg
        total = self.epicure.nframes
        if self.epicure.process_parallel:
            track_tables = Parallel( n_jobs=self.epicure.nparallel ) (
                delayed(ut.labels_to_table)(frame, iframe ) for iframe, frame in enumerate(labels)
            )
        else:
            track_tables = [ ut.labels_to_table( frame, iframe) for iframe, frame in progress(enumerate(labels), total=total) ]
        track_table = np.concatenate( track_tables, axis=0 )
        return track_table, None # track_prop

    def add_track_features(self, labels):
        """ Add features specific to tracks (eg nframes) """
        nframes = np.zeros(len(labels), int)
        if self.epicure.verbose > 2:
            print("REPLACE BY COUNT METHOD")
        for track_id in np.unique(labels):
            cur_track = np.argwhere(labels == track_id)
            nframes[ list(cur_track) ] = len(cur_track)
        return nframes
    

    ##########################################
    #### Tracking functions

    def changed_start(self, i):
        """ Ensures that end frame > start frame """
        if i > self.end_frame.value():
            self.end_frame.setValue(i+1)

    def changed_end(self, i):
        if i < self.start_frame.value():
            self.start_frame.setValue(i-1)

    def find_parents(self, labels, twoframes):
        """ Find in the first frame the parents of labels from second frame """
        
        if self.track_choice.currentText() == "Laptrack-Centroids":
            return self.laptrack_centroids_twoframes(labels, twoframes, loose=True)
        
        if self.track_choice.currentText() == "Laptrack-Overlaps":
            return self.laptrack_overlaps_twoframes(labels, twoframes, loose=True)
        

    def do_tracking(self):
        """ Start the tracking with the selected options """
        if self.frame_range.isChecked():
            start = self.start_frame.value()
            end = self.end_frame.value()
        else:
            start = 0
            end = self.nframes-1
        start_time = ut.start_time()
        self.viewer.window._status_bar._toggle_activity_dock(True)
        self.epicure.inspecting.reset_all_events()
        
        if self.track_choice.currentText() == "Laptrack-Centroids":
            if self.epicure.verbose > 1:
                print("Starting track with Laptrack-Centroids")
            self.laptrack_centroids( start, end )
            self.epicure.tracked = 1
        if self.track_choice.currentText() == "Laptrack-Overlaps":
            if self.epicure.verbose > 1:
                print("Starting track with Laptrack-Centroids")
            self.laptrack_overlaps( start, end )
            self.epicure.tracked = 1
        
        self.epicure.finish_update(contour=2)
        #self.epicure.reset_free_label()
        self.viewer.window._status_bar._toggle_activity_dock(False)
        if self.epicure.verbose > 0:
            ut.show_duration( start_time, header="Tracking done in " )

    def show_trackoptions(self):
        self.gLapCentroids.setVisible(self.track_choice.currentText() == "Laptrack-Centroids")
        if laptrack_over:
            self.gLapOverlap.setVisible(self.track_choice.currentText() == "Laptrack-Overlaps")

    def relabel_nonunique_labels(self, track_df):
        """ After tracking, some track can be splitted and get same label, fix that """
        inittids = np.unique(track_df["track_id"])
        labtracks = []
        saved_data = np.copy(self.epicure.seglayer.data)
        mframes = []
        tids = []
        used = np.unique( saved_data )
        all_labels = np.unique(track_df["label"])
        for tid in inittids:
            cdf = track_df[track_df["track_id"]==tid]
            #print(cdf)
            min_frame = np.min( cdf["frame"] )
            #labtrack = int( cdf["label"][cdf["frame"]==min_frame] )
            for lab in np.unique(cdf["label"]):
                labtracks.append(lab)
                mframes.append( min_frame )
                tids.append(tid)
        if len(labtracks) != len(np.unique(labtracks)):
            ## some labels are present several times
            used = used.tolist()
            for lab in all_labels :
                indexes = list(np.where(np.array(labtracks)==lab)[0])
                if len(indexes)>1:
                    minframes = [mframes[indy] for indy in range(len(labtracks)) if labtracks[indy]==lab]
                    indmin = indexes[ np.argmin( minframes ) ]
                    ## for the other(s), change the label
                    newvals = ut.get_free_labels( used, len(indexes) )
                    used = used + newvals
                    for i, ind in enumerate(indexes):
                        if ind != indmin:
                            tid = tids[ind]
                            newval = newvals[i]
                            track_df.loc[ (track_df["track_id"]==tid)  & (track_df["label"]==lab) , "label"] = newval
                            for frame in track_df["frame"][(track_df["track_id"]==tid) & (track_df["label"]==newval)]:
                                mask = (saved_data[frame]==lab)
                                self.epicure.seglayer.data[frame][mask] = newval
        

    def relabel_trackids(self, track_df, splitdf, mergedf):
        """ Change the trackids to take the first label of each track """
        start_time = ut.start_time()
        new_trackids = track_df['track_id'].copy()
        new_splitdf = splitdf.copy()
        new_mergedf = mergedf.copy()
        
        unique_track_ids = np.unique(track_df['track_id'])
        first_labels = track_df.groupby('track_id').apply(lambda x: x.loc[x['frame'].idxmin(), 'label']).to_dict()
        
        for tid in unique_track_ids:
            newval = first_labels[tid]
            if tid != newval:
                new_trackids[track_df['track_id'] == tid] = newval
                if not new_splitdf.empty:
                    new_splitdf.loc[splitdf["parent_track_id"] == tid, "parent_track_id"] = newval
                    new_splitdf.loc[splitdf["child_track_id"] == tid, "child_track_id"] = newval
                if not new_mergedf.empty:
                    new_mergedf.loc[mergedf["parent_track_id"] == tid, "parent_track_id"] = newval
                    new_mergedf.loc[mergedf["child_track_id"] == tid, "child_track_id"] = newval
        if self.epicure.verbose > 1:
            ut.show_duration( start_time, header="Relabeling done in " )            
        return new_trackids, new_splitdf, new_mergedf

    def change_labels(self, track_df):
        """ Change the labels at each frame according to tracks """
        for frame, frame_df in track_df.groupby("frame"):
            self.change_frame_labels(frame, frame_df)

    def change_frame_labels(self, frame, frame_df):
        """ Change the labels at given frame according to tracks """
        track_ids = frame_df['track_id'].astype(int).values
        old_labels = frame_df["label"].astype(int).values
        seglayer = np.copy(self.epicure.seglayer.data[frame])
        for old_lab, new_lab in zip(old_labels, track_ids):
            mask = (seglayer==old_lab)
            self.epicure.seglayer.data[frame][mask] = new_lab

    def label_to_dataframe( self, labimg, frame ):
        """ from label, get dataframe of centroids with properties """
        df = pd.DataFrame( ut.labels_table(labimg, properties=self.region_properties))
        df["frame"] = frame
        return df
    
    def optical_flow( self, img0, img1, radius ):
        """ Compute the optical flow between two images """
        v, u = optical_flow_ilk( img0, img1, radius=radius)
        return v, u
    
    def apply_flow( self, flowv, flowu, labimg ):
        """ Apply the calculated optical flow on a label image """
        nr, nc = labimg.shape
        rowc, colc = np.meshgrid( np.arange(nr), np.arange(nc), indexing="ij" )
        lab_reg = warp( labimg, np.array( [rowc+flowv, colc+flowu] ), order=0, mode="edge" )
        return lab_reg
    
    def labels_to_centroids( self, start_frame, end_frame ):
        """ Get centroids of each cell in dataframe """
        regionprops = [
            self.label_to_dataframe(self.epicure.seg[frame], frame)
            for frame in range(start_frame, end_frame + 1)
        ]
        return pd.concat(regionprops)
    
    def labels_to_centroids_flow(self, start_frame, end_frame):
        """ Get centroids of each cell in dataframe """
        regionprops = []    
        radius = float( self.drift_radius.text() )
        if self.epicure.verbose > 1:
            if self.drift_correction.isChecked():
                print( "Apply drift correction to tracking with optical flow of radius "+str(radius) )
        prev_movie = None
        flow_v = None
        for frame in range(start_frame, end_frame+1):
            if self.drift_correction.isChecked():
                cur_movie = self.epicure.img[frame]
                if frame > start_frame:
                    v, u = self.optical_flow( prev_movie, cur_movie, radius )
                    if flow_v is None:
                        flow_v = v
                        flow_u = u
                    else:
                        flow_v = flow_v + v
                        flow_u = flow_u + u
                prev_movie = cur_movie
            clabel = self.epicure.seg[frame]  
            df = self.label_to_dataframe( clabel, frame )
            if flow_v is not None:
                c0 = np.array( np.floor( df["centroid-0"] ), dtype="uint8" )
                c1 = np.array( np.floor( df["centroid-1"] ), dtype="uint8" )
                df["centroid-0"] = df["centroid-0"] - flow_v[c0,c1]
                df["centroid-1"] = df["centroid-1"] - flow_u[c0,c1]
            regionprops.append(df)
        regionprops_df = pd.concat(regionprops)
        return regionprops_df
    
    def labels_flow(self, start_frame, end_frame ):
        """ Get registered label image corrected for optical flow """
        radius = float( self.drift_radius.text() )
        flow_v = None
        prev_movie = None
        res_labels = []
        for frame in range(start_frame, end_frame+1):
            cur_movie = self.epicure.img[frame]
            if prev_movie is not None:
                v, u = self.optical_flow( prev_movie, cur_movie, radius )
                if flow_v is None:
                    flow_v = v
                    flow_u = u
                else:
                    flow_v = flow_v + v
                    flow_u = flow_u + u
            prev_movie = cur_movie
            clabel = np.copy( self.epicure.seg[frame] ) 
            if flow_v is not None:         
                clabel = self.apply_flow( flow_v, flow_u, clabel )
            res_labels.append( clabel )
        res_labels = np.array(res_labels)
        return res_labels

    def labels_ready(self, start_frame, end_frame, locked=True):
        """ Get labels of unlocked cells to track """
        if self.drift_correction.isChecked():
            return self.labels_flow( start_frame, end_frame )
        res_labels = self.epicure.seg[start_frame:end_frame+1] 
        return res_labels
    
    def label_frame_todf( self, frame ):
        """ For current frame, get label frame image then dataframe of centroids """
        clabel = self.epicure.seg[frame] #self.current_label_frame(frame)
        return self.label_to_dataframe( clabel, frame )
    
    def current_label_frame( self, frame ):
        """ For current frame, get label frame image """
        clabel = None
        #if self.track_only_in_roi.isChecked():
        #    clabel = self.epicure.only_current_roi(frame)
        if clabel is None:
            clabel = self.epicure.seg[frame]
        return clabel

    def after_tracking( self, track_df, split_df, merge_df, progress_bar, indprogress ):
        """ Steps after tracking: get/show the graph from the track_df """
        graph = None
        progress_bar.set_description( "Update labels and tracks" )
        ## shift all by 1 so that doesn't start at 0
        if len(split_df) > 0:
            split_df[["parent_track_id"]] += 1
            split_df[["child_track_id"]] += 1
        if len(merge_df) > 0:
            merge_df[["parent_track_id"]] += 1
            merge_df[["child_track_id"]] += 1
        track_df[["track_id"]] += 1
       
        ## relabel if some track have the same label
        self.relabel_nonunique_labels(track_df)
        ## relabel track ids so that they are equal to the first label of the track
        newtids, split_df, merge_df = self.relabel_trackids( track_df, split_df, merge_df )
        track_df["track_id"] = newtids
        self.change_labels( track_df )

        # create graph of division/merging
        self.graph = convert_split_merge_df_to_napari_graph(split_df, merge_df)

        progress_bar.update(indprogress+1)
        
        ## update display if active
        self.replace_tracks( track_df )

        progress_bar.update(indprogress+2)
        ## update the list of events, or others 
        self.epicure.updates_after_tracking()
        progress_bar.update(indprogress+3)
        return graph

############ Laptrack centroids option
    
    def create_laptrack_centroids(self):
        """ GUI of the laptrack option """
        self.gLapCentroids, glap_layout = wid.group_layout( "Laptrack-Centroids" )
        mdist, self.max_dist = wid.value_line( "Max distance", "15.0", "Maximal distance between two labels in consecutive frames to link them (in pixels)" )
        glap_layout.addLayout(mdist)
        ## splitting ~ cell division
        scost, self.splitting_cost = wid.value_line( "Splitting cutoff", "1", "Weight to split a track in two (increasing it favors division)" )
        glap_layout.addLayout(scost)
        ## merging ~ error ?
        mcost, self.merging_cost = wid.value_line( "Merging cutoff", "0", "Weight to merge to labels together" )
        glap_layout.addLayout(mcost)

        add_feat, self.check_penalties, self.bpenalties = wid.checkgroup_help( "Add features cost", True, "Add cell features in the tracking calculation", None )
        self.create_penalties()
        glap_layout.addWidget(self.check_penalties)
        glap_layout.addWidget(self.bpenalties)
        self.gLapCentroids.setLayout(glap_layout)

    def show_penalties(self):
        self.bpenalties.setVisible(not self.bpenalties.isVisible())

    def create_penalties(self):
        pen_layout = QVBoxLayout()
        areaCost, self.area_cost = wid.value_line( "Area difference", "2", "Weight of the difference of area between two labels to link them (0 to ignore)" )
        pen_layout.addLayout(areaCost)
        solidCost, self.solidity_cost = wid.value_line( "Solidity difference", "0", "Weight of the difference of solidity between two labels to link them (0 to ignore)" )
        pen_layout.addLayout(solidCost)
        self.bpenalties.setLayout(pen_layout)

    def laptrack_centroids_twoframes(self, labels, twoframes, loose=False):
        """ Perform tracking of two frames with strict parameters """
        laptrack = LaptrackCentroids(self, self.epicure)
        laptrack.max_distance = float(self.max_dist.text()) 
        if loose:
            laptrack.max_distance = min(50, laptrack.max_distance) ## more probable to find a parent
        self.region_properties = ["label", "centroid"]
        #if self.check_penalties.isChecked():
        #    self.region_properties.append("area")
        #    self.region_properties.append("solidity")
        #    laptrack.penal_area = float(self.area_cost.text())
        #    laptrack.penal_solidity = float(self.solidity_cost.text())
        #laptrack.set_region_properties(with_extra=self.check_penalties.isChecked())
        laptrack.set_region_properties(with_extra=False)
            
        df = self.twoframes_centroid(twoframes)
        if set(np.unique(df["label"])) == set(labels):
            ## no other labels
            return [None]*len(labels) 
        laptrack.splitting_cost = False ## disable splitting option
        laptrack.merging_cost = False ## disable merging option
        parent_labels = laptrack.twoframes_track(df, labels)
        return parent_labels
    
    def twoframes_centroid(self, img):
        """ Get centroids of first frame only """
        df0 = self.label_to_dataframe( img[0], 0 )
        df1 = self.label_to_dataframe( img[1], 1 )
        return pd.concat([df0, df1])
    
    def laptrack_centroids(self, start, end):
        """ Perform track with laptrack option and chosen parameters """
        ## Laptrack tracker
        laptrack = LaptrackCentroids(self, self.epicure)
        laptrack.max_distance = float(self.max_dist.text())
        laptrack.splitting_cost = float(self.splitting_cost.text())
        laptrack.merging_cost = float(self.merging_cost.text())
        self.region_properties = ["label", "centroid"]
        if self.check_penalties.isChecked():
            self.region_properties.append("area")
            self.region_properties.append("solidity")
            laptrack.penal_area = float(self.area_cost.text())
            laptrack.penal_solidity = float(self.solidity_cost.text())
        laptrack.set_region_properties(with_extra=self.check_penalties.isChecked())

        progress_bar = progress(total=7)
        progress_bar.set_description( "Prepare tracking" )
        if self.epicure.verbose > 1:
            print("Convert labels to centroids: use track info ?")
        self.undrifted = False
        if self.drift_correction.isChecked():
            df = self.labels_to_centroids_flow( start, end )
        else:
            df = self.labels_to_centroids( start, end )
        progress_bar.update(1)
        if self.epicure.verbose > 1:
            print("GO tracking")
        progress_bar.set_description( "Do tracking with LapTrack Centroids" )
        track_df, split_df, merge_df = laptrack.track_centroids(df)
        progress_bar.update(2)
        if self.epicure.verbose > 1:
            print("After tracking, update everything")
        self.after_tracking(track_df, split_df, merge_df, progress_bar, 2)
        progress_bar.update(6)
        progress_bar.close()
    
############ Laptrack overlap option

    def create_laptrack_overlap(self):
        """ GUI of the laptrack overlap option """
        self.gLapOverlap, glap_layout = wid.group_layout( "Laptrack-Overlaps" )
        miou, self.min_iou = wid.value_line( "Min IOU", "0.1", "Minimum Intersection Over Union score to link to labels together" )
        glap_layout.addLayout(miou)
        
        scost, self.split_cost = wid.value_line( "Splitting cost", "0.2", "Weight of linking a parent label with two labels (increasing it for more divisions)" )
        glap_layout.addLayout(scost)
        
        mcost, self.merg_cost = wid.value_line( "Merging cost", "0", "Weight of merging two parent labels into one" )
        glap_layout.addLayout(mcost)

        self.gLapOverlap.setLayout(glap_layout)

    def laptrack_overlaps(self, start, end):
        """ Perform track with laptrack overlap option and chosen parameters """
        ## Laptrack tracker
        laptrack = LaptrackOverlaps(self, self.epicure)
        miniou = float(self.min_iou.text())
        if miniou >= 1.0:
            miniou = 1.0
        laptrack.cost_cutoff = 1.0 - miniou
        laptrack.splitting_cost = float(self.split_cost.text())
        laptrack.merging_cost = float(self.merg_cost.text())
        self.region_properties = ["label", "centroid"]

        progress_bar = progress(total=6)
        progress_bar.set_description( "Prepare tracking" )
        labels = self.labels_ready( start, end )
        self.undrifted = False
        progress_bar.update(1)
        progress_bar.set_description( "Do tracking with LapTrack Overlaps" )
        track_df, split_df, merge_df = laptrack.track_overlaps( labels )
        progress_bar.update(2)
        
        ## get dataframe of coordinates to create the graph 
        df = self.labels_to_centroids( start, end )
        self.undrifted = True
        progress_bar.update(3)
        coordinate_df = df.set_index(["frame", "label"])
        tdf = track_df.set_index(["frame", "label"])
        track_df2 = pd.merge( tdf, coordinate_df, right_index=True, left_index=True).reset_index()
        self.after_tracking( track_df2, split_df, merge_df, progress_bar, 3 )
        progress_bar.update(6)
        progress_bar.close()
    
    def laptrack_overlaps_twoframes(self, labels, twoframes, loose=False):
        """ Perform tracking of two frames with strict parameters """
        laptrack = LaptrackOverlaps(self, self.epicure)
        miniou = min( float(self.min_iou.text()), 0.9999 ) ## ensure that miniou is < 1
        laptrack.cost_cutoff = 1.0 - miniou
        if loose:
            laptrack.cost_cutoff = 0.95 ## more probable to find a parent/child
        self.region_properties = ["label", "centroid"]

        laptrack.splitting_cost = False ## disable splitting option
        laptrack.merging_cost = False ## disable merging option
        parent_labels = laptrack.twoframes_track(twoframes, labels)
        return parent_labels


