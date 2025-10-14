"""
Tracking with laptrack package

Inspired from example https://github.com/yfukai/laptrack/blob/main/docs/examples/cell_segmentation.ipynb
"""

import numpy as np
import pandas as pd

import laptrack
from laptrack import LapTrack
import epicure.Utils as ut
from packaging.version import Version
    

def squared_difference(a1, a2):
    """ Squared difference, normalized """
    return ((a1-a2)**2)/(max(a1, a2)**2)

def squared_distance(x1, y1, x2, y2):
    """ Return squared distance """
    return (x1-x2)**2 + (y1-y2)**2


class LaptrackCentroids():

    def __init__(self, track, epic):
        self.max_distance = 15
        self.splitting_cost = 1
        self.merging_cost = 1
        self.penal_area = 0
        self.penal_solidity = 0
        self.track = track
        self.epicure = epic
        self.inspecting = False
        self.suggesting = False
        self.region_properties = ["label", "frame", "centroid-0", "centroid-1", "area", "solidity"]
        ## to handle difference in laptrack versions
        self.version_over = Version(laptrack.__version__) >= Version("0.17.0")

        if self.version_over:
            self.lt = LapTrack( metric=self.tracking_metric,
                                cutoff=1, 
                                splitting_metric=self.tracking_nofeat_metric, 
                                splitting_cutoff=self.splitting_cost, 
                                merging_metric=self.tracking_nofeat_metric,
                                merging_cutoff=self.merging_cost, )
        else:
            self.lt = LapTrack( track_dist_metric=self.tracking_metric,
                                track_cost_cutoff=1, 
                                splitting_dist_metric=self.tracking_nofeat_metric, 
                                splitting_cost_cutoff=self.splitting_cost, 
                                merging_dist_metric=self.tracking_nofeat_metric,
                                merging_cost_cutoff=self.merging_cost, )
        
    def set_region_properties(self, with_extra=False):
        """ define the region properties used in the tracker """
        if with_extra:
            self.region_properties = ["label", "frame", "centroid-0", "centroid-1", "area", "solidity"]
        else:
            self.region_properties = ["label", "frame", "centroid-0", "centroid-1" ]

    def twoframes_track(self, df, labels):
        """ Do track between two frames, only track label """
        #start_time = time.time()
        track_df, split_df, merge_df = self.perform_track( df )
        #show_info("Performed in "+"{:.3f}".format((time.time()-start_time)/60)+" min")
        
        track_ids = [None]*len(labels)
        ## look for track id associated with label
        frame_df = track_df[track_df["frame"] == 1]
        label_to_tid = {int(row["label"]): int(row["track_id"]) for i, row in frame_df.iterrows()}
        for i, curlabel in enumerate(labels):
            track_ids[i] = label_to_tid.get(curlabel, None)

        tracklabels = [None]*len(labels)
        ## look for cell label associated with track_id in the first frame, if any
        frame_df = track_df[track_df["frame"]==0]
        frame_df = frame_df[frame_df["track_id"].isin(track_ids)]
        label_to_tid = {int(row["track_id"]): int(row["label"]) for i, row in frame_df.iterrows()}
        for i, tid in enumerate(track_ids):
            tracklabels[i] = label_to_tid.get(tid, None)
        #show_info("Finished in "+"{:.3f}".format((time.time()-start_time)/60)+" min")
        return tracklabels

    def tracking_metric(self, c1, c2):
        """ Tracking cost metric: distance + feature penalties """
        dist = squared_distance(c1[2], c1[3], c2[2], c2[3])
        if dist > self.max_distance**2:
            return dist
        ## normalize all distances to combine them
        dist = dist / (self.max_distance**2)
        if self.penal_area > 0:
            dist += self.penal_area * squared_difference(c1[4], c2[4])
        if self.penal_solidity > 0:
            dist += self.penal_solidity * squared_difference(c1[5], c2[5])
        return dist
    
    def tracking_nofeat_metric(self, c1, c2):
        """ Tracking cost metric: distance, no penalties """
        dist = squared_distance(c1[2], c1[3], c2[2], c2[3])
        if dist > self.max_distance**2:
            return dist
        ## normalize all distances to combine them
        dist = dist / (self.max_distance**2)
        return dist

    def perform_track(self, regionprops_df):
        """ Do tracking with laptrack module """
        split_cost = False
        merg_cost = False
        #from laptrack import ParallelBackend
        #self.lt.parallel_backend = ParallelBackend.ray
        if self.splitting_cost > 0:
            split_cost = self.splitting_cost**2
        if self.version_over:
            self.lt.splitting_cutoff = split_cost
        else:
            self.lt.splitting_cost_cutoff = split_cost
        if self.merging_cost > 0:
            merg_cost = self.merging_cost**2
        if self.version_over:
            self.lt.merging_cutoff = merg_cost
        else:
            self.lt.merging_cost_cutoff = merg_cost
        track_df, split_df, merge_df = self.lt.predict_dataframe(
            regionprops_df,
            coordinate_cols=self.region_properties,
            only_coordinate_cols=False,
        )    
        track_df = track_df.reset_index()
        return track_df, split_df, merge_df

    def track_centroids(self, regionprops_df):
        """ Track cells based on their centroids positions + features penalties """
        ut.napari_info("Starting tracking with LapTrack centroids metrics...")
        return self.perform_track( regionprops_df )

    def inspect_oneframe(self, graph, trackdf):
        for track in np.unique(trackdf["track_id"]):
            tr = trackdf[trackdf["track_id"] == track]
            ## track is only on one frame, suspect
            if len(np.unique(tr["frame"])) == 1:
                # trackid + 1 as trackid starts as 0
                pos = (tr.iloc[0]["frame"], int(tr.iloc[0]["centroid-0"]), int(tr.iloc[0]["centroid-1"]))
                self.epicure.inspecting.add_event( pos, track+1, "tracking" )
                if self.track.suggesting:
                    if track in graph.keys():
                        sisters = []
                        refval = graph[track][0]
                        for key, val in graph.items():
                            if val[0] == refval:
                                sisters.append( key )
                        if len(sisters) == 2:
                            for sis in sisters:
                                self.epicure.add_suggestion( sis+1, refval+1 )

