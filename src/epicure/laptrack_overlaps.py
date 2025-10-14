"""
Tracking with laptrack package

Inspired from example https://github.com/yfukai/laptrack/blob/main/docs/examples/cell_segmentation.ipynb
"""

import numpy as np
import pandas as pd
from skimage.measure import regionprops_table
import laptrack
from laptrack import OverLapTrack
#from laptrack import datasets
import epicure.Utils as ut
from packaging.version import Version


class LaptrackOverlaps():

    def __init__(self, track, epic):
        self.splitting_cost = 1
        self.cost_cutoff = 0.9
        self.merging_cost = 1
        self.track = track
        self.epicure = epic
        self.inspecting = False
        self.suggesting = False
        ## to handle difference in laptrack versions
        self.version_over = Version(laptrack.__version__) >= Version("0.17.0")
        

    def twoframes_track(self, img_labels, labels):
        """ Do track between two frames, only track label """
        #start_time = time.time()
        track_df, split_df, merge_df = self.perform_track( img_labels )
        #show_info("Performed in "+"{:.3f}".format((time.time()-start_time)/60)+" min")
        
        track_ids = [None]*len(labels)
        ## look for track id associated with label
        for i, row in track_df.iterrows():
            frame = int(row["frame"])
            if frame == 1:
                tid = int(row["track_id"])
                curlabel = int(row["label"])
                ind = labels.index(curlabel)
                track_ids[ind] = tid

        tracklabels = [None]*len(labels)
        ## look for cell label associated with track_id in the first frame, if any
        for i, row in track_df.iterrows():
            frame = int(row["frame"])
            tid = int(row["track_id"])
            if (tid in track_ids) and (frame==0):
                ind = track_ids.index(tid)
                label = int(row["label"])
                tracklabels[ind] = label 
        #show_info("Finished in "+"{:.3f}".format((time.time()-start_time)/60)+" min")
        return tracklabels


    def perform_track(self, labels):
        """ Do tracking with laptrack module """
        if self.version_over:
            ol = OverLapTrack(
                cutoff=self.cost_cutoff,
                metric_coefs=(1.0, 0.0, -1.0, 0.0, 0.0),
                #gap_closing_metric_coefs=(1.0, -1.0, 0.0, 0.0, 0.0),
                #gap_closing_max_frame_count=1,
                gap_closing_cutoff=False,
                merging_cutoff=self.merging_cost,
                merging_metric_coefs=(1.0, 0.0, 0.0, -1.0, 0.0),
                splitting_cutoff=self.splitting_cost,
                splitting_metric_coefs=(1.0, 0.0, 0.0, 0.0, -1.0),
            )
        else:
            ol = OverLapTrack(
                track_cost_cutoff=self.cost_cutoff,
                track_dist_metric_coefs=(1.0, 0.0, -1.0, 0.0, 0.0),
                #gap_closing_dist_metric_coefs=(1.0, -1.0, 0.0, 0.0, 0.0),
                #gap_closing_max_frame_count=1,
                gap_closing_cost_cutoff=False,
                merging_cost_cutoff=self.merging_cost,
                merging_dist_metric_coefs=(1.0, 0.0, 0.0, -1.0, 0.0),
                splitting_cost_cutoff=self.splitting_cost,
                splitting_dist_metric_coefs=(1.0, 0.0, 0.0, 0.0, -1.0),
            )
        
        track_df, split_df, merge_df = ol.predict_overlap_dataframe(labels)
        track_df = track_df.reset_index()
        return track_df, split_df, merge_df

    def track_overlaps(self, labels):
        """ Track all movie with laptrack overlap method """
        ut.napari_info("Starting tracking with laptrack Overlap...")
        return self.perform_track( labels )


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


