import pandas as pand
import numpy as np
import roifile
from skimage.morphology import binary_erosion, disk
import os, time
import napari
from napari.utils import progress
import epicure.Utils as ut
import epicure.epiwidgets as wid
import plotly.express as px
from qtpy import QtCore
from qtpy.QtCore import Qt
QtCore.QCoreApplication.setAttribute(QtCore.Qt.AA_ShareOpenGLContexts, True)  ## for QtWebEngine import to work on some computers
from qtpy.QtWebEngineWidgets import QWebEngineView 
from qtpy.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget, QTableWidget, QTableWidgetItem, QGridLayout, QListWidget
from qtpy.QtWidgets import QAbstractItemView as aiv
from random import sample
from joblib import Parallel, delayed
    

class Outputing(QWidget):

    def __init__(self, napari_viewer, epic):
        super().__init__()
        self.viewer = napari_viewer
        self.epicure = epic
        self.table = None
        self.table_selection = None
        self.seglayer = self.viewer.layers["Segmentation"]
        self.movlayer = self.viewer.layers["Movie"]
        self.selection_choices = ["All cells", "Only selected cell"]
        self.output_options = ["", "Export to extern plugins", "Export segmentations", "Measure cell features", "Measure track features", "Export/Measure events", "Save screenshot movie"]
        self.tplots = None
        
        chanlist = ["Movie"]
        if self.epicure.others is not None:
            for chan in self.epicure.others_chanlist:
                chanlist.append( "MovieChannel_"+str(chan) )
        self.cell_features = CellFeatures( chanlist )
        self.event_classes = EventClass( self.epicure ) 
        
        all_layout = QVBoxLayout()
        self.scaled_unit = wid.add_check( "Measures in scaled units", False, check_func=None, descr="Scales the output measures in the given spatio-temporal units (µm, min..)" )
        all_layout.addWidget( self.scaled_unit )
        self.choose_output = wid.listbox() 
        all_layout.addWidget(self.choose_output)
        for option in self.output_options:
            self.choose_output.addItem(option)
        self.choose_output.currentIndexChanged.connect(self.show_output_option)
        
        ## Choice of active selection
        #layout = QVBoxLayout()
        selection_layout, self.output_mode = wid.list_line( "Apply on", descr="Choose on which cell(s) to do the action", func=None )
        for sel in self.selection_choices:
            self.output_mode.addItem(sel)
        all_layout.addLayout(selection_layout)
       
        ## Choice of interface
        self.export_group, export_layout = wid.group_layout( "Export to extern plugins" )
        griot_btn = wid.add_button( "Current frame to Griottes", self.to_griot, "Launch(in new window) Griottes plugin on current frame" )
        export_layout.addWidget(griot_btn)
        ncp_btn = wid.add_button( "Current frame to Cluster-Plotter", self.to_ncp, "Launch (in new window) cluster-plotter plugin on current frame" )
        export_layout.addWidget(ncp_btn)
        self.export_group.setLayout(export_layout)
        all_layout.addWidget(self.export_group)
        
        ## Option to export segmentation results
        self.export_seg_group, layout = wid.group_layout(self.output_options[2])
        save_line, self.save_choice = wid.button_list( "Save segmentation as", self.save_segmentation, "Save the current segmentation either as ROI, label image or skeleton" ) 
        self.save_choice.addItem( "labels" )
        self.save_choice.addItem( "ROI" )
        self.save_choice.addItem( "skeleton" )
        layout.addLayout( save_line )

        self.export_seg_group.setLayout(layout)
        all_layout.addWidget(self.export_seg_group)

        #### Features group
        self.feature_group, featlayout = wid.group_layout(self.output_options[3])
        
        self.choose_features_btn = wid.add_button( "Choose features...", self.choose_features, "Open a window to select the features to measure" )
        featlayout.addWidget(self.choose_features_btn)

        self.feature_table = wid.add_button( "Create features table", self.show_table, "Measure the selected features and display it as a clickable table" )
        featlayout.addWidget(self.feature_table)
        self.featTable = FeaturesTable(self.viewer, self.epicure)
        featlayout.addWidget(self.featTable)
        
        ######## Temporal option  
        self.temp_graph = wid.add_button( "Table to temporal graphs...", self.temporal_graphs, "Open a plot interface of measured features temporal evolution" )
        featlayout.addWidget(self.temp_graph)
        self.temp_graph.setEnabled(False)
       
        ######## Drawing option
        featmap, self.show_feature_map = wid.list_line( "Draw feature map:", descr="Add a layer with the cells colored by the selected feature value", func=self.show_feature )
        featlayout.addLayout(featmap)
        orienbtn = wid.add_button( "Draw cell orientation", self.draw_orientation, "Add a layer with each cell main axis orientation and length " )
        featlayout.addWidget( orienbtn )

        save_tab_line, self.save_format = wid.button_list( "Save features table", self.save_measure_features, "Save the current table in a .csv file" )
        self.save_format.addItem( "csv" )
        self.save_format.addItem( "xlsx" )
        featlayout.addLayout(save_tab_line)

        ## skrub table
        self.stat_table = wid.add_button( "Open statistiques table...", self.skrub_features, "Open interactive table with the features statistiques (skrub library)" )
        featlayout.addWidget(self.stat_table)
        
        self.feature_group.setLayout(featlayout)
        self.feature_group.hide()
        all_layout.addWidget(self.feature_group)

        ## Track features
        self.trackfeat_group, trackfeatlayout = wid.group_layout(self.output_options[4])
        self.trackfeat_table = wid.add_button( "Track features table", self.show_trackfeature_table, "Measure track-related feature and show a table by track" )
        trackfeatlayout.addWidget(self.trackfeat_table)
        self.trackTable = FeaturesTable(self.viewer, self.epicure)
        trackfeatlayout.addWidget(self.trackTable)
        self.save_table_track = wid.add_button( "Save track table", self.save_table_tracks, "Save the current table in a .csv file" )
        trackfeatlayout.addWidget(self.save_table_track)
        
        self.trackfeat_group.setLayout(trackfeatlayout)
        self.trackfeat_group.hide()
        all_layout.addWidget(self.trackfeat_group)

        ## Track features
        self.trackfeat_group, trackfeatlayout = wid.group_layout(self.output_options[4])
        self.trackfeat_table = wid.add_button( "Track features table", self.show_trackfeature_table, "Measure track-related feature and show a table by track" )
        trackfeatlayout.addWidget(self.trackfeat_table)
        self.trackTable = FeaturesTable(self.viewer, self.epicure)
        trackfeatlayout.addWidget(self.trackTable)
        self.save_table_track = wid.add_button( "Save track table", self.save_table_tracks, "Save the current table in a .csv file" )
        trackfeatlayout.addWidget(self.save_table_track)
        
        self.trackfeat_group.setLayout(trackfeatlayout)
        self.trackfeat_group.hide()
        all_layout.addWidget(self.trackfeat_group)

        ## Option to export/measure events (Fiji ROI or table), + graphs ?
        self.handle_event_group, elayout = wid.group_layout(self.output_options[5])
        self.choose_events_btn = wid.add_button( "Choose events...", self.choose_events, "Open a window to select the events to export/measure" )
        elayout.addWidget( self.choose_events_btn )
        save_evt_line, self.save_evt_choice = wid.button_list( "Export events as", self.export_events, "Save the checked events as Fiji ROIs or .csv table" ) 
        self.save_evt_choice.addItem( "Fiji ROI" )
        self.save_evt_choice.addItem( "CSV File" )
        elayout.addLayout( save_evt_line )
        count_evt_btn = wid.add_button( "Count events", self.temporal_graphs_events, descr="Create temporal plot of number of events" )
        elayout.addWidget( count_evt_btn )

        self.handle_event_group.setLayout( elayout )
        self.handle_event_group.hide()
        all_layout.addWidget( self.handle_event_group )
        
        ## Save screenshots option
        current_frame = ut.current_frame( self.epicure.viewer )
        self.screenshot_group, screenshot_layout = wid.group_layout( "Save screenshot movie" )
        self.show_scalebar = wid.add_check_tolayout( screenshot_layout, "With the scale bar", True, check_func=None, descr="Show the scale bar in the screenshots" )
        sframe_line, self.sframe = wid.slider_line( "From frame", 0, self.epicure.nframes, 1, value=current_frame, show_value=True, slidefunc=None, descr="Frame from which to start saving screenshots" )
        eframe_line, self.eframe = wid.slider_line( "To frame", 0, self.epicure.nframes, 1, value=current_frame+1, show_value=True, slidefunc=None, descr="Frame until which to save screenshots" )
        screenshot_layout.addLayout( sframe_line )
        screenshot_layout.addLayout( eframe_line )
        savescreen_btn = wid.add_button( "Save current view", self.screenshot_movie, "Save the current view (with current display parameters) for frame between the two specified frames in a movie" )

        screenshot_layout.addWidget(savescreen_btn)
        self.screenshot_group.setLayout(screenshot_layout)
        all_layout.addWidget(self.screenshot_group)
        self.screenshot_group.hide()
        

        
        ## Finished
        self.setLayout(all_layout)
        self.show_output_option()

    def get_current_settings( self ):
        """ Returns current settings of the widget """
        disp = {}
        disp["Apply on"] = self.output_mode.currentText() 
        disp["Current option"] = self.choose_output.currentText()
        disp["Show scalebar"] = self.show_scalebar.isChecked()
        disp = self.cell_features.get_current_settings( disp )
        disp = self.event_classes.get_current_settings( disp )
        return disp

    def apply_settings( self, settings ):
        """ Set the current state of the widget from preferences if any """
        for setting, val in settings.items():
            if setting == "Apply on":
                self.output_mode.setCurrentText( val )
            if setting == "Current option":
                self.choose_output.setCurrentText( val )
            if setting == "Show scalebar":
                self.show_scalebar.setChecked( val )
            
        self.cell_features.apply_settings( settings )
        self.event_classes.apply_settings( settings )

    def screenshot_movie( self ):
        """ Save screenshots of the current view """
        scale_visibility = self.viewer.scale_bar.visible
        current_frame = ut.current_frame( self.epicure.viewer )
        self.viewer.scale_bar.visible = self.show_scalebar.isChecked()
        start_frame = max( self.sframe.value(), 0 )
        end_frame = min( self.eframe.value(), self.epicure.nframes )
        outname = os.path.join( self.epicure.outdir, self.epicure.imgname+"_screenshots_f"+str(start_frame)+"-"+str(end_frame)+".tif" )
        if os.path.exists(outname):
            os.remove(outname)
        if start_frame > end_frame:
            ut.show_warning("From frame > to frame, no screenshot saved")
            return
        for frame in range(start_frame, end_frame+1):
            self.viewer.dims.set_point(0, frame)
            shot = self.viewer.screenshot( canvas_only=True, flash=False )
            ut.appendToTif( shot, outname )
        self.viewer.scale_bar.visible = scale_visibility
        self.viewer.dims.set_point(0, current_frame)
        ut.show_info( "Screenshot movie saved in "+outname )

    def events_select( self, event, check ):
        """ Check/Uncheck the event in event types list """
        if event in self.event_classes.evt_classes:
            self.event_classes.evt_classes[ event ][0].setChecked( check )
        else:
            print(event+" not found in possible event types to export")

    def show_output_option(self):
        """ Show selected output panel """
        cur_option = self.choose_output.currentText()
        self.export_group.setVisible( cur_option == "Export to extern plugins" )
        self.export_seg_group.setVisible( cur_option == "Export segmentations" )
        self.feature_group.setVisible( cur_option == "Measure cell features" )
        self.trackfeat_group.setVisible( cur_option == "Measure track features" )
        self.handle_event_group.setVisible( cur_option == "Export/Measure events" )
        self.screenshot_group.setVisible( cur_option == "Save screenshot movie" )

    def get_current_labels( self ):
        """ Get the cell labels to process according to current selection of apply on"""
        if self.output_mode.currentText() == "Only selected cell": 
            lab = self.epicure.seglayer.selected_label
            return [lab]
        if self.output_mode.currentText() == "All cells": 
            return self.epicure.get_labels()
        else:
            group = self.output_mode.currentText()
            label_group = self.epicure.groups[group]
            return label_group

            
    def get_selection_name(self):
        if self.output_mode.currentText() == "Only selected cell": 
            lab = self.epicure.seglayer.selected_label
            return "_cell_"+str(lab) 
        #if self.output_mode.currentText() == "Only checked cells":
        #    return "_checked_cells"
        if self.output_mode.currentText() == "All cells":
            return ""
        return "_"+self.output_mode.currentText()

    def skrub_features( self ):
        """ Open html table interactive and stats with skrub module """
        try:
            from skrub import TableReport
        except:
            ut.show_error( "Needs skrub library for this option. Install it (`pip install skrub`) before" )
            return
        if self.table is None:
            ut.show_warning( "Create/update the table before" )
            return
        report = TableReport( self.table )
        report.open()
        

    def save_measure_features(self):
        """ Save measures table to file whether it was created or not """
        if self.table is None or self.table_selection is None or self.selection_changed() :
            ut.show_warning("Create/update the table before")
            return
        ext = self.save_format.currentText()
        outfile = self.epicure.outname()+"_features"+self.get_selection_name()+"."+ext
        if ext == "xlsx":
            self.table.to_excel( outfile, sheet_name='EpiCureMeasures' )
        else:
            self.table.to_csv( outfile, index=False )
        if self.epicure.verbose > 0:
            ut.show_info("Measures saved in "+outfile)
    
    def save_table_tracks(self):
        """ Save tracks table to file whether it was created or not """
        if self.table is None or self.table_selection is None or self.selection_changed() :
            ut.show_warning("Create/update the table before")
            return
        outfile = self.epicure.outname()+"_trackfeatures"+self.get_selection_name()+".xlsx"
        self.table.to_excel( outfile, sheet_name='EpiCureTrackMeasures' )
        if self.epicure.verbose > 0:
            ut.show_info("Track measures saved in "+outfile)


    def save_one_roi(self, lab):
        """ Save the Rois of cell with label lab """
        keep = self.seglayer.data == lab
        rois = []
        if np.sum(keep) > 0:
            ## add 2D case
            for iframe, frame in enumerate(keep):
                if np.sum(frame) > 0:
                    contour = ut.get_contours(frame)
                    roi = self.create_roi(contour[0], iframe, lab)
                    rois.append(roi)

        roifile.roiwrite(self.epicure.outname()+"_rois_cell_"+str(lab)+".zip", rois, mode='w')

    def create_roi(self, contour, frame, label):
        croi = roifile.ImagejRoi()
        croi.version = 227
        croi.roitype = roifile.ROI_TYPE(0) ## polygon
        croi.n_coordinates = len(contour)
        croi.position = frame + 1
        croi.t_position = frame+1
        coords = []
        cent0 = 0
        cent1 = 0
        for cont in contour:
            coords.append([int(cont[1]), int(cont[0])])
            cent0 += cont[1]
            cent1 += cont[0]
        croi.integer_coordinates = np.array(coords)
        #croi.top = int(np.min(coords[0]))
        #croi.left = int(np.min(coords[1]))
        croi.name = str(frame+1).zfill(4)+'-'+str(int(cent0/len(contour))).zfill(4)+"-"+str(int(cent1/len(contour))).zfill(4)
        return croi
    
    def save_segmentation( self ):
        """ Save current segmentation in selected format """
        if self.output_mode.currentText() == "Only selected cell": 
            ## output only the selected cell
            lab = self.seglayer.selected_label
            if self.save_choice.currentText() == "ROI":
                self.save_one_roi(lab)
                if self.epicure.verbose > 0:
                    ut.show_info("Cell "+str(lab)+" saved to Fiji ROI")
                return
            else:
                tosave = np.zeros(self.seglayer.data.shape, dtype=self.epicure.dtype)
                if np.sum(self.seglayer.data==lab) > 0:
                    tosave[self.seglayer.data==lab] = lab
                endname = "_"+self.save_choice.currentText()+"_"+str(lab)+".tif"
        else:
            ## output all cells
            if self.output_mode.currentText() == "All cells":
                if self.save_choice.currentText() == "ROI":
                    self.save_all_rois()
                    return
                tosave = self.seglayer.data
                endname = "_"+self.save_choice.currentText()+".tif"
            else:
                ## or output only selected group
                group = self.output_mode.currentText()
                label_group = self.epicure.groups[group]
                if self.save_choice.currentText() == "ROI":
                    ncells = 0
                    for lab in label_group:
                        self.save_one_roi(lab)
                        ncells += 1
                    if self.epicure.verbose > 0:
                        ut.show_info(str(ncells)+" cells saved to Fiji ROIs")
                    return
                tosave = np.zeros(self.seglayer.data.shape, dtype=self.epicure.dtype)
                endname = "_"+self.save_choice.currentText()+"_"+self.output_mode.currentText()+".tif"
                for lab in label_group:
                    tosave[self.seglayer.data==lab] = lab
        
        ## save filled image (for label or skeleton) to file
        outname = os.path.join( self.epicure.outdir, self.epicure.imgname+endname )
        if self.save_choice.currentText() == "skeleton":
            parallel = 0
            if self.epicure.process_parallel:
                parallel = self.epicure.nparallel
            tosave = ut.get_skeleton( tosave, viewer=self.viewer, verbose=self.epicure.verbose, parallel=parallel )
            ut.writeTif( tosave, outname, self.epicure.epi_metadata["ScaleXY"], 'uint8', what="Skeleton" )
        else:
            ut.writeTif(tosave, outname, self.epicure.epi_metadata["ScaleXY"], 'float32', what="Segmentation")
                
    def save_all_rois( self ):
        """ Save all cells to ROI format """
        ncells = 0
        for lab in np.unique(self.epicure.seglayer.data):
            self.save_one_roi(lab)
            ncells += 1
        if self.epicure.verbose > 0:
            ut.show_info(str(ncells)+" cells saved to Fiji ROIs")

    def choose_features( self ):
        """ Pop-up widget to choose the features to measure """
        self.cell_features.choose()

    def measure_features(self):
        """ Measure features and put them to table """
        thick = self.epicure.thickness

        def intensity_junction_cytoplasm(regionmask, intensity):
            """ Measure the intensity only on the contour of regionmask """
            footprint = disk(radius=thick)
            inside = binary_erosion(regionmask, footprint)
            inside_intensity = ut.mean_nonzero(intensity*inside)
            periph_intensity = ut.mean_nonzero(intensity*(regionmask^inside))
            return inside_intensity, periph_intensity
        
        if self.epicure.verbose > 0:
            print("Measuring features")
        #self.viewer.window._status_bar._toggle_activity_dock(True)
        pb = ut.start_progress( self.viewer, total=2, descr="Measuring cells in all movie" )
        start_time = time.time()
        if self.output_mode.currentText() == "Only selected cell": 
            meas = np.zeros(self.epicure.seglayer.data.shape, self.epicure.dtype)
            lab = self.epicure.seglayer.selected_label
            meas[self.epicure.seglayer.data==lab] = lab
        else:
            if self.output_mode.currentText() == "All cells": 
                meas = self.epicure.seglayer.data
            else:
                group = self.output_mode.currentText()
                meas = np.zeros(self.epicure.seglayer.data.shape, self.epicure.dtype)
                label_group = self.epicure.groups[group]
                for lab in label_group:
                    meas[self.epicure.seglayer.data==lab] = lab
            
        properties, prop_extra, other_features, int_feat, int_extrafeat = self.cell_features.get_features()
        do_channels = self.cell_features.get_channels()
        extra_prop = []
        if "intensity_junction_cytoplasm" in int_extrafeat:
            extra_prop = extra_prop + [intensity_junction_cytoplasm]

        extra_properties = []
        if (do_channels is not None) and ("Movie" in do_channels):
            properties = properties + int_feat
            for extra in int_extrafeat:
                if extra == "intensity_junction_cytoplasm":
                    extra_properties = extra_properties + [intensity_junction_cytoplasm]
        
        pb.update()
        labgroups = self.epicure.group_of_labels()
        pb.total = self.epicure.nframes
        chan_dict = dict()
        if ( do_channels is not None ):
            for chan in do_channels:
                if chan == "Movie":
                    continue
                chan_dict[chan] = self.viewer.layers[chan].data
        seg = self.epicure.seg
        mov = self.movlayer.data
        
        def measure_one_frame_collect( img, frame ):
            """ Measure on one frame and return a list of dicts for each label """
            #pb.update()
            intimg = mov[frame]
            frame_table = pand.DataFrame( ut.labels_table(img, intensity_image=intimg, properties=properties, extra_properties=extra_properties) )
            if "group" in other_features:
                frame_table["group"] = frame_table["label"].map(labgroups).fillna("Ungrouped")
            frame_table["frame"] = frame
            
            # Boundary
            if "Boundary" in other_features:
                boundimg = seg[frame]
                bds = ut.get_boundary_cells(boundimg)
                frame_table["Boundary"] = frame_table["label"].isin(bds).astype(int)
            # Border
            if "Border" in other_features:
                bds = ut.get_border_cells(img)
                frame_table["Border"] = frame_table["label"].isin(bds).astype(int)
            
            # Intensity features in other channels
            for chan, intimg_chan in chan_dict:
                intimg_frame = intimg_chan[frame]
                frame_tab = ut.labels_table(img, intensity_image=intimg_frame, properties=int_feat, extra_properties=int_extrafeat)
                for add_prop in int_feat:
                    frame_table[add_prop+"_"+str(chan)] = frame_tab[add_prop]
                if "intensity_junction_cytoplasm-0" in frame_tab.keys():
                    frame_table["intensity_cytoplasm_"+str(chan)] = frame_tab["intensity_junction_cytoplasm-0"]
                    frame_table["intensity_junction_"+str(chan)] = frame_tab["intensity_junction_cytoplasm-1"]
            
            if prop_extra != []:
                if "shape_index" in prop_extra:
                    frame_table["shape_index"] = frame_table["perimeter"] / np.sqrt(frame_table["area"])
                if "roundness" in prop_extra:
                    frame_table["roundness"] = 4*frame_table["area"] /(np.pi * np.power(frame_table["axis_major_length"],2) )
                if "aspect_ratio" in prop_extra:
                    frame_table["aspect_ratio"] = frame_table["axis_major_length"] / frame_table["axis_minor_length"]

            # Neighbor features
            do_neighbor = "NbNeighbors" in other_features
            get_neighbor = "Neighbors" in other_features
            if do_neighbor or get_neighbor:
                nimg = seg[frame]
                graph = ut.get_neighbor_graph(nimg, distance=3)
                all_neighbors = {label: list(graph.adj[label]) for label in graph.nodes}
                frame_table["neighborlist"] = frame_table["label"].map(lambda l: all_neighbors.get(l, []))

            if do_neighbor:
                frame_table["NbNeighbors"] = frame_table["neighborlist"].apply(
                lambda x: len(x) if x else -1
                )
            if get_neighbor:
                frame_table["Neighbors"] = frame_table["neighborlist"].apply(
                lambda x: "&".join(map(str, x)) if x else ""
                )
            frame_table.drop(columns="neighborlist", inplace=True)
            return pand.DataFrame( frame_table.to_dict(orient="records") )

        if self.epicure.process_parallel:
            frame_tables = Parallel( n_jobs=self.epicure.nparallel ) ( 
                delayed( measure_one_frame_collect ) ( frame, iframe ) for iframe, frame in enumerate(meas) )
        else:
            frame_tables = [
                measure_one_frame_collect( frame, iframe )
                for iframe, frame in (enumerate(meas))
            ]
        self.table = pand.concat(frame_tables, ignore_index=True)

        if "intensity_junction_cytoplasm-0" in self.table.columns:
            self.table = self.table.rename(columns={"intensity_junction_cytoplasm-0": "intensity_cytoplasm", "intensity_junction_cytoplasm-1":"intensity_junction"})
        self.table_selection = self.selection_choices.index(self.output_mode.currentText())
        ut.close_progress( self.viewer, pb )
        #self.viewer.window._status_bar._toggle_activity_dock(False)
        if self.epicure.verbose > 0:
            ut.show_info("Features measured in "+"{:.3f}".format((time.time()-start_time)/60)+" min")

    def measure_one_frame(self, img, properties, extra_properties, other_features, channels, int_feat, int_extrafeat, frame, labgroups, prop_extra ):
        """ Measure on one frame """
        if frame is not None:
            intimg = self.movlayer.data[frame]
        else:
            intimg = self.movlayer.data
        first = "label" not in self.table.keys()
        nrows = len(self.table["label"]) if "label" in self.table.keys() else 0
        
        ## add the basic label measures
        frame_table = ut.labels_table( img, intensity_image=intimg, properties=properties, extra_properties=extra_properties )
        ndata = len(frame_table["label"])
        for key, value in frame_table.items():
            if first:
                self.table[key] = []
            self.table[key].extend(list(value))

        ## add the frame column
        if frame is not None:
            if first:
                self.table["frame"] = []
            self.table["frame"].extend([frame]*ndata)

        ## add info of the cell group
        if "group" in other_features:
            frame_group = [ labgroups[label] if label in labgroups.keys() else "Ungrouped" for label in frame_table["label"] ]
            if first:
                self.table["group"] = []
            self.table["group"].extend( frame_group )

        ## add the extra shape features
        if prop_extra != []:
            if "shape_index" in prop_extra:
                si = frame_table["perimeter"] /np.sqrt( frame_table["area"] ) 
                if first:
                    self.table["shape_index"] = []
                self.table["shape_index"].extend( si )
            if "roundness" in prop_extra:
                rou = 4*frame_table["area"] /(np.pi * np.power(frame_table["axis_major_length"],2) ) 
                if first:
                    self.table["roundness"] = []
                self.table["roundness"].extend( rou )
            if "aspect_ratio" in prop_extra:
                ar = list( np.array(frame_table["axis_major_length"])/np.array(frame_table["axis_minor_length"]) )
                if first:
                    self.table["aspect_ratio"] = []
                self.table["aspect_ratio"].extend( ar )

        ### Measure intensity features in other chanels if option is on
        if (channels is not None):
            for chan in channels:
                ## if it's movie, already measured in the general measure
                if chan == "Movie":
                    continue
                ## otherwise, do a new measure on the selected channels
                if frame is not None:
                    intimg = self.viewer.layers[chan].data[frame]
                else:
                    intimg = self.viewer.layers[chan].data
                frame_tab = ut.labels_table( img, intensity_image=intimg, properties=int_feat, extra_properties=int_extrafeat )
                for add_prop in int_feat:
                    if first:
                        self.table[add_prop+"_"+chan] = []
                    self.table[add_prop+"_"+chan].extend( list(frame_tab[add_prop]) )
                if "intensity_junction_cytoplasm-0" in frame_tab.keys():
                    if first:
                        self.table["intensity_cytoplasm_"+chan] = []
                        self.table["intensity_junction_"+str(chan)] = []
                    self.table["intensity_cytoplasm_"+chan].extend( list(frame_tab["intensity_junction_cytoplasm-0"]) )
                    self.table["intensity_junction_"+str(chan)].extend( list(frame_tab["intensity_junction_cytoplasm-1"]) )
                
            
        ## add features of neighbors relationship with graph
        do_neighbor = "NbNeighbors" in other_features
        get_neighbor = "Neighbors" in other_features
        if do_neighbor or get_neighbor:
            if frame is not None:
                nimg = self.epicure.seg[frame]
            else:
                nimg = self.epicure.seg
            #start_time = ut.start_time()
            graph = ut.get_neighbor_graph( nimg, distance=3 )
            
            if first:
                if do_neighbor:
                    self.table["NbNeighbors"] = []
                if get_neighbor:
                    self.table["Neighbors"] = []
            if do_neighbor:
                self.table["NbNeighbors"].extend( [-1]*ndata )
            if get_neighbor:
                self.table["Neighbors"].extend( [""]*ndata )

            for label in np.unique(frame_table["label"]):
                if label in graph.nodes:
                    rlabel = np.where( (frame_table["label"] == label) )[0]
                    nneighbor = len(graph.adj[label])
                    for ind in rlabel:
                        if do_neighbor:
                            self.table["NbNeighbors"][ind+nrows] = nneighbor
                        if get_neighbor:
                            self.table["Neighbors"][ind+nrows] = ""
                            sep = ""
                            for key in graph.adj[label].keys():
                                self.table["Neighbors"][ind+nrows] += sep + str(key)
                                sep = "&"
            #ut.show_duration( start_time, "Neighborhoods measured" )

        ## measure cells on boundary    
        if "Boundary" in other_features:
            if frame is not None:
                boundimg = self.epicure.seg[frame]
            else:
                boundimg = self.epicure.seg
            bounds = ut.get_boundary_cells( boundimg )
            if first:
                self.table["Boundary"] = []
            self.table["Boundary"].extend( [0]*ndata )
            for label in np.unique(frame_table["label"]):
                if label in bounds:
                    rlabel = np.where( (frame_table["label"] == label) )[0]
                    for ind in rlabel:
                        self.table["Boundary"][ind+nrows] = 1
        
        ## measure cells on border  
        if "Border" in other_features:
            bounds = ut.get_border_cells( img )
            if first:
                self.table["Border"] = []
            self.table["Border"].extend( [0]*ndata )
            for label in bounds:
                rlabel = np.where( (frame_table["label"] == label) )[0]
                for ind in rlabel:
                    self.table["Border"][ind+nrows] = 1

        
    def selection_changed(self):
        if self.table_selection is None:
            return True
        return self.output_mode.currentText() != self.selection_choices[self.table_selection]

    def update_selection_list(self):
        """ Update the possible selection from group cell list """
        self.selection_choices = ["Only selected cell", "All cells"]
        for group in self.epicure.groups.keys():
            self.selection_choices.append(group)
        self.output_mode.clear()
        for sel in self.selection_choices:
            self.output_mode.addItem(sel)

    def show_table(self):
        """ Show the measurement table """
        #disable automatic update (slow)
        #if self.table is None:
            ## create the table and connect action to update it automatically
            #self.output_mode.currentIndexChanged.connect(self.show_table)
            #self.measure_other_chanels_cbox.stateChanged.connect(self.show_table)
            #self.feature_graph_cbox.stateChanged.connect(self.show_table)
            #self.feature_intensity_cbox.stateChanged.connect(self.show_table)
            #self.feature_shape_cbox.stateChanged.connect(self.show_table)
        
        ut.set_active_layer( self.viewer, "Segmentation" )
        self.show_feature_map.clear()
        self.show_feature_map.addItem("")
        laynames = [lay.name for lay in self.viewer.layers]
        for lay in laynames:
            if lay.startswith("Map_"):
                ut.remove_layer(self.viewer, lay)
        self.measure_features()
        featlist = self.table.keys()
        ## Scaling the features
        if self.scaled_unit.isChecked():
            for feat in featlist:
                feat_scale, scaled = self.scale_feature( feat, self.table[feat] )
                if feat_scale is not None:
                    if (feat_scale[0:4] != "Time") and (feat_scale[0:9] != "centroid-"):
                        del self.table[feat]
                    self.table[feat_scale] = scaled
        featlist = self.table.keys()
        ## Adding the list to the feature maps
        for feat in featlist:
            self.show_feature_map.addItem(feat)
        self.featTable.set_table(self.table)
        self.temp_graph.setEnabled(True)
        if self.tplots is not None:
            self.tplots.update_table(self.table)

    def scale_feature( self, feat, featVals ):
        """ Scale if necessary the feature values """
        dist_feats = ["centroid-0", "centroid-1", "perimeter", "axis_major_length", "axis_minor_length", "feret_diameter_max", "equivalent_diameter_area" ]
        if feat in dist_feats:
            return feat+"_"+self.epicure.epi_metadata["UnitXY"], np.array(featVals)*self.epicure.epi_metadata["ScaleXY"]
        area_feats = ["area", "area_convex"]
        if feat in area_feats:
            return feat+"_"+self.epicure.epi_metadata["UnitXY"]+"²", np.array(featVals)*self.epicure.epi_metadata["ScaleXY"] * self.epicure.epi_metadata["ScaleXY"]
        if feat == "frame":
            return "Time_"+self.epicure.epi_metadata["UnitT"], np.array(featVals)*self.epicure.epi_metadata["ScaleT"]
        return None, None


    def show_feature(self):
        """ Add the image map of the selected feature """
        feat = self.show_feature_map.currentText()
        if (feat is not None) and (feat != ""):
            if feat in self.table.keys():
                values = list(self.table[feat])
                if feat == "group":
                    for i, val in enumerate(values):
                        if (val is None) or (val == 'None'):
                            values[i] = 0
                        else:
                            values[i] = list(self.epicure.groups.keys()).index(val) + 1
                labels = list(self.table["label"])
                frames = None
                if "frame" in self.table:
                    frames = list(self.table["frame"])
                self.draw_map(labels, values, frames, feat)

    def draw_map(self, labels, values, frames, featname):
        """ Add image layer of values by label """
        ## special feature: orientation, draw the axis instead
        self.viewer.window._status_bar._toggle_activity_dock(True)
        labels = np.array(labels)
        values = np.array(values)
        frames = np.array(frames)
        def map_frame( iframe, segframe ):
            """ Draw one frame of the map """
            mask = np.where(frames==iframe)[0]
            labs = labels[mask]
            vals = values[mask]
            mapping = np.zeros(segframe.max()+1)
            mapping[:] = np.nan
            mapping[labs] = vals 
            return mapping[segframe] 

        if frames is not None:
            ## Plotting a movie
            if self.epicure.process_parallel:
                mapfeat = Parallel( n_jobs=self.epicure.nparallel) (
                    delayed ( map_frame )(iframe, frame ) for iframe, frame in enumerate(self.seglayer.data)
                )
                mapfeat = np.array(mapfeat)
            else:
                mapfeat = np.empty(self.epicure.seg.shape, dtype="float16")
                mapfeat[:] = np.nan
                for iframe in np.unique(frames):
                    segdata = self.seglayer.data[iframe]
                    mapfeat[iframe] = map_frame( iframe, segdata )
        else:
            mapfeat = np.empty(self.epicure.seg.shape, dtype="float16")
            mapfeat[:] = np.nan
            for lab, val in progress(zip(labels, values)):
                cell = self.seglayer.data==lab
                mapfeat[cell] = val
        ut.remove_layer(self.viewer, "Map_"+featname)
        self.viewer.add_image(mapfeat, name="Map_"+featname, scale=self.viewer.layers["Segmentation"].scale )
        self.viewer.window._status_bar._toggle_activity_dock(False)

    def draw_orientation( self ):
        """ Display the cells orientation axis in a new layer """
        ## check that necessary features are measured
        ut.remove_layer( self.viewer, "CellOrientation" )
        feats = ["centroid-0", "centroid-1", "orientation"]
        if self.table is None:
            print("Features centroid and orientation necessary to draw orientation, but are not measured yet")
            return
        for feat in feats:
            if feat not in self.table.keys():
                print("Feature "+feat+" necessary to draw orientation, but was not measured")
                return
        ## ok, can work now
        self.viewer.window._status_bar._toggle_activity_dock(True)

        ## get the coordinates of the axis lines by getting the cell centroid, main orientation
        xs = np.array( self.table["centroid-0"] )
        ys = np.array( self.table["centroid-1"] )
        angles = np.array( self.table["orientation"] )
        lens = np.array( [10]*len(angles) )
        oriens = np.zeros( (self.epicure.seg.shape), dtype="uint8" )

        ## draw axis length depending on the eccentricity
        if "eccentricity" in self.table.keys():
            lens = np.array(self.table["eccentricity"]*16)             
        
        if "frame" in self.table:
            frames = np.array( self.table["frame"] ).astype(int)
        else:
            frames = np.array( [0]*len(angles) )

        ## draw the lines in between the two extreme points (using Shape layer is too slow on display for big movies)
        npts = 30
        xmax = oriens.shape[1]-1
        ymax = oriens.shape[2]-1
        for i in range(npts):
            xas = np.clip(xs - lens/2 * np.cos( angles ) * i/float(npts), 0, xmax).astype(int)
            xbs = np.clip(xs + lens/2 * np.cos( angles ) * i/float(npts), 0, xmax).astype(int)
            yas = np.clip(ys - lens/2 * np.sin( angles ) * i/float(npts), 0, ymax).astype(int)
            ybs = np.clip(ys + lens/2 * np.sin( angles ) * i/float(npts), 0, ymax).astype(int)
            oriens[ (frames, xas, yas) ] = 255
            oriens[ (frames, xbs, ybs) ] = 255
        
        self.viewer.add_image( oriens, name="CellOrientation", blending="additive", opacity=1, scale=self.viewer.layers["Segmentation"].scale )
        self.viewer.window._status_bar._toggle_activity_dock(False)

    ################### Export to other plugins

    def to_griot(self):
        """ Export current frame to new viewer and makes it ready for Griotte plugin """
        try:
            from napari_griottes import make_graph
        except:
            ut.show_error("Plugin napari-griottes is not installed")
            return
        gview = napari.Viewer()
        tframe = ut.current_frame(self.viewer)
        segt = self.epicure.seglayer.data[tframe]
        touching_frame = self.touching_labels(segt)
        gview.add_labels(touching_frame, name="TouchingCells", opacity=1)
        gview.window.add_dock_widget(make_graph(), name="Griottes")

    def touching_labels(self, labs):
        """ Dilate labels so that they all touch """
        from skimage.segmentation import find_boundaries
        from skimage.morphology import skeletonize
        from skimage.morphology import binary_closing, binary_opening
        if self.epicure.verbose > 0:
            print("********** Generate touching labels image ***********")

        ## skeletonize it
        skel = skeletonize( binary_closing( find_boundaries(labs), footprint=np.ones((10,10)) ) )
        ext = np.zeros(labs.shape, dtype="uint8")
        ext[labs==0] = 1
        ext = binary_opening(ext, footprint=np.ones((2,2)))
        newimg = ut.touching_labels(labs, expand=4)
        newimg[ext>0] = 0
        return newimg
    
    def to_ncp(self):
        """ Export current frame to new viewer and makes it ready for napari-cluster-plots plugin """
        try:
            import napari_skimage_regionprops as nsr
        except:
            ut.show_error("Plugin napari-skimage-regionprops is not installed")
            return
        gview = napari.Viewer()
        tframe = ut.current_frame(self.viewer)
        segt = self.epicure.seglayer.data[tframe]
        moviet = self.epicure.viewer.layers["Movie"].data[tframe]
        lab = gview.add_labels(segt, name="Segmentation[t="+str(tframe)+"]", blending="additive")
        im = gview.add_image(moviet, name="Movie[t="+str(tframe)+"]", blending="additive")
        if self.epicure.verbose > 0:
            print("Measure features with napari-skimage-regionprops plugin...")
        nsr.regionprops_table(im.data, lab.data, size=True, intensity=True, perimeter=True, shape=True, position=True, moments=True, napari_viewer=gview)
        try:
            import napari_clusters_plotter as ncp
        except:
            ut.show_error("Plugin napari-clusters-plotter is not installed")
            return
        gview.window.add_dock_widget( ncp.ClusteringWidget(gview) )
        gview.window.add_dock_widget( ncp.PlotterWidget(gview) )

    ################### Temporal graphs
    def temporal_graphs_events( self ):
        """ New window with temporal graph of event counts """
        if self.tplots is not None:
            self.tplots.close()
        self.tplots = TemporalPlots( self.viewer, self.epicure )
        evt_table = self.count_events()
        self.tplots.setTable( evt_table )
        self.tplots.show()
        self.viewer.dims.events.current_step.connect(self.position_verticalline)


    def temporal_graphs(self):
        """ New window with temporal graph of the current table selection """
        #self.temporal_viewer = napari.Viewer()
        self.tplots = TemporalPlots( self.viewer, self.epicure )
        self.tplots.setTable(self.table)
        self.tplots.show()
        #self.plot_wid = self.viewer.window.add_dock_widget( self.tplots, name="Plots" )
        self.viewer.dims.events.current_step.connect(self.position_verticalline)
    
    def on_close_viewer(self):
        """ Temporal plots window is closed """
        if self.epicure.verbose > 1:
            print("Closed viewer")
        self.viewer.dims.events.current_step.disconnect(self.position_verticalline)
        self.temporal_viewer = None
        self.tplots = None

    def position_verticalline(self):
        """ Place the vertical line in the temporal graph to the current frame """
        #try:
        #    wid = self.tplots
        #except:
        #    self.on_close_viewer()
        if self.tplots is not None:
            self.tplots.move_framepos(self.viewer.dims.current_step[0])

    ############### track features 

    def show_trackfeature_table(self):
        """ Show the measurement of tracks table """
        self.measure_track_features()
        self.trackTable.set_table( self.table )
    
    def measure_track_features(self):
        """ Measure track features and put them to table """
        if self.epicure.verbose > 0:
            print("Measuring track features")
        self.viewer.window._status_bar._toggle_activity_dock(True)
        start_time = time.time()

        if self.output_mode.currentText() == "Only selected cell": 
            track_ids = self.epicure.seglayer.selected_label
        else:
            if self.output_mode.currentText() == "All cells": 
                track_ids = self.epicure.tracking.get_track_list()
            else:
                group = self.output_mode.currentText()
                track_ids = []
                label_group = self.epicure.groups[group]
                for lab in label_group:
                    track_ids.append(lab)
            
        properties = ["label", "area", "centroid"]
        self.table = None

        if type(track_ids) == np.ndarray or type(track_ids)==np.array:
            track_ids = track_ids.tolist()
        if not type(track_ids) == list:
            track_ids = [track_ids]

        labgroups = self.epicure.group_of_labels()
        frame_group = [ labgroups[label] if label in labgroups.keys() else "Ungrouped" for label in track_ids ]
        for itrack, track_id in progress(enumerate(track_ids)):
            track_frame = self.measure_one_track( track_id )
            track_frame["Group"] = frame_group[itrack]
            if self.table is None:
                self.table = pand.DataFrame([track_frame])
            else:
                self.table = pand.concat([self.table, pand.DataFrame([track_frame])])

        self.table_selection = self.selection_choices.index(self.output_mode.currentText())
        self.viewer.window._status_bar._toggle_activity_dock(False)
        if self.epicure.verbose > 0:
            ut.show_info("Features measured in "+"{:.3f}".format((time.time()-start_time)/60)+" min")

    def measure_one_track( self, track_id ):
        """ Measure features of one track """
        track_features = self.epicure.tracking.measure_track_features( track_id, self.scaled_unit.isChecked() )
        return track_features

    ############## Events functions

    def choose_events( self ):
        """ Pop-up widget to choose the event types to measure/export """
        self.event_classes.choose()

    def count_events( self ):
        """ Count events of selected types """
        evt_types = self.event_classes.get_evt_classes()
        if self.epicure.verbose > 2:
            print("Counting events of type "+str(evt_types)+" " )
        
        ## keep only events related to selected cells
        labels = self.get_current_labels()
        ## count each type of event
        table = np.zeros(  (self.epicure.nframes,len(evt_types)), dtype="uint8" )        
        for itype, evt_type in enumerate( evt_types ):
            evts = self.epicure.inspecting.get_events_from_type( evt_type )
            if len( evts ) > 0:
                for evt_sid in evts:
                        pos, label = self.epicure.inspecting.get_event_infos( evt_sid )
                        if label in labels:
                            table[ pos[0], itype ] += 1
        df = pand.DataFrame( data=table, columns=evt_types )
        df["frame"] = range(len(df))
        df["label"] = [0]*len(df)
        return df          

    def export_events( self ):
        """ Export events of selected types """
        evt_types = self.event_classes.get_evt_classes()
        export_type = self.save_evt_choice.currentText()
        if self.epicure.verbose > 2:
            print("Exporting events of type "+str(evt_types)+" to "+export_type )
        self.export_events_type_format( evt_types, export_type )
        
    def export_events_type_format( self, evt_types, export_type ):
        """ Export events of selected types in selected format """
        ## keep only events related to selected cells
        labels = self.get_current_labels()
        groups = self.epicure.get_groups( labels )
        if export_type == "CSV File":
            res = pand.DataFrame( columns=["label", "frame", "posY", "posX", "EventClass", "Group"] )  
        ## export each type of event in separate files
        for itype, evt_type in enumerate( evt_types ):
            evts = self.epicure.inspecting.get_events_from_type( evt_type )
            if len( evts ) > 0:
                rois = [] 
                for evt_sid in evts:
                    pos, label = self.epicure.inspecting.get_event_infos( evt_sid )
                    ind_lab = np.where( labels==label )
                    if len( ind_lab[0] ) > 0:
                        grp = groups[ int(ind_lab[0][0]) ]
                        if export_type == "Fiji ROI":
                            roi = self.create_point_roi( pos, itype )
                            rois.append( roi )
                        if export_type == "CSV File":
                            new_event = pand.DataFrame( [[label, pos[0], pos[1], pos[2], evt_type, grp ]], columns=res.columns )
                            res = pand.concat( [res, new_event], ignore_index=True )
                if export_type == "Fiji ROI":            
                    outfile = self.epicure.outname()+"_rois_"+evt_type +""+self.get_selection_name()+".zip" 
                    roifile.roiwrite(outfile, rois, mode='w')
                    if self.epicure.verbose > 0:
                        print( "Events "+str( evt_type )+" saved in ROI file: "+outfile )
            ## dont save anything if empty, just print info to user
            else:
                if self.epicure.verbose > 0:
                    print( "No events of type "+str(evt_type)+"" )
        
        if export_type == "CSV File":            
            outfile = self.epicure.outname()+"_events"+self.get_selection_name()+".csv" 
            res.to_csv( outfile,  sep='\t', header=True, index=False )
            if self.epicure.verbose > 0:
                print( "Events data "+" saved in CSV file: "+outfile )


    def create_point_roi( self, pos, cat=0 ):
        """ Create a point Fiji ROI """
        croi = roifile.ImagejRoi()
        croi.version = 227
        croi.roitype = roifile.ROI_TYPE(10)
        croi.name = str(pos[0]+1).zfill(4)+'-'+str(pos[1]).zfill(4)+"-"+str(pos[2]).zfill(4)
        croi.n_coordinates = 1
        croi.left = int(pos[2])
        croi.top = int(pos[1])
        croi.z_position = 1
        croi.t_position = pos[0]+1
        croi.c_position = 1
        croi.integer_coordinates = np.array( [[0,0]] )
        croi.stroke_width=3
        ncolors = 3
        if cat%ncolors == 0:  ## color type 0
            croi.stroke_color = b'\xff\x00\x00\xff'
        if cat%ncolors == 1:  ## color type 1
            croi.stroke_color = b'\xff\x00\xff\x00'
        if cat%ncolors == 2:  ## color type 2
            croi.stroke_color = b'\xff\xff\x00\x00'
        return croi


class CellFeatures(QWidget):
    """ Choice of features to measure """
    def __init__(self, chanlist):
        super().__init__()
        layout = QVBoxLayout()
        
        self.required = ["label"]
        self.features = {}
        self.chan_list = None
        
        other_list = ["group", "NbNeighbors", "Neighbors", "Boundary", "Border"]
        feat_layout = self.add_feature_group( other_list, "other" )
        layout.addLayout( feat_layout )
        sel_all_b = wid.add_button( "Select spatial features", lambda: self.select_all("other"), "Select all spatial features" )
        desel_all_b = wid.add_button( "Deselect spatial features", lambda: self.deselect_all("other"), "Deselect all spatial features" )
        sel_line_b = wid.hlayout()
        sel_line_b.addWidget( sel_all_b )
        sel_line_b.addWidget( desel_all_b )
        layout.addLayout( sel_line_b )


        ## Add shape features
        shape_list = ["centroid", "area", "area_convex", "axis_major_length", "axis_minor_length", "feret_diameter_max", "equivalent_diameter_area", "eccentricity", "orientation", "perimeter", "solidity"]
        other_shape_list = ["shape_index", "roundness", "aspect_ratio"]
        feat_layout = self.add_feature_group( shape_list, "prop" )
        feat_extra_layout = self.add_feature_group( other_shape_list, "prop_extra" )
        layout.addLayout( feat_layout )
        layout.addLayout( feat_extra_layout )
        sel_all = wid.add_button( "Select morphology features", lambda: self.select_all("props"), "Select all morphology features" )
        desel_all = wid.add_button( "Deselect morphology features", lambda: self.deselect_all("props"), "Deselect all morphology features" )
        sel_line = wid.hlayout()
        sel_line.addWidget( sel_all )
        sel_line.addWidget( desel_all )
        layout.addLayout( sel_line )

        int_lab = wid.label_line( "Intensity features:")
        layout.addWidget( int_lab )
        intensity_list = ["intensity_mean", "intensity_min", "intensity_max"]
        extra_list = ["intensity_junction_cytoplasm"]
        feat_layout = self.add_feature_group( intensity_list, "intensity_prop" )
        layout.addLayout( feat_layout )
        feat_layout = self.add_feature_group( extra_list, "intensity_extra" )
        layout.addLayout( feat_layout )
        if len(chanlist) > 1:
            chan_lab = wid.label_line( "Measure intensity in channels:" )
            layout.addWidget( chan_lab )
            self.chan_list = QListWidget()
            self.chan_list.addItems( chanlist )
            self.chan_list.setSelectionMode(aiv.MultiSelection)
            self.chan_list.item(0).setSelected(True)
            layout.addWidget( self.chan_list )
        
        sel_all_int = wid.add_button( "Select intensity features", lambda: self.select_all("intensity"), "Select all spatial features" )
        desel_all_int = wid.add_button( "Deselect intensity features", lambda: self.deselect_all("intensity"), "Deselect all spatial features" )
        sel_line_int = wid.hlayout()
        sel_line_int.addWidget( sel_all_int )
        sel_line_int.addWidget( desel_all_int )
        layout.addLayout( sel_line_int )

        bye = wid.add_button( "Ok", self.close, "Close the window" )
        layout.addWidget( bye )
        self.setLayout( layout )

    def select_all( self, feat ):
        """ Select all features of type feat """
        if feat == "intensity":
            self.select_all( "intensity_prop" )
            self.select_all( "intensity_extra" )
            return
        if feat == "props":
            self.select_all( "prop" )
            self.select_all( "prop_extra" )
            return
        for featy, feat_val in self.features.items():
            if feat_val[1] == feat:
                feat_val[0].setChecked( True )
    
    def deselect_all( self, feat ):
        """ Deselect all features of type feat """
        if feat == "intensity":
            self.deselect_all( "intensity_prop" )
            self.deselect_all( "intensity_extra" )
            return
        if feat == "props":
            self.deselect_all( "prop" )
            self.deselect_all( "prop_extra" )
            return
        for featy, feat_val in self.features.items():
            if feat_val[1] == feat:
                feat_val[0].setChecked( False )


    def add_feature_group( self, feat_list, feat_type ):
        """ Add features to the GUI """
        layout = QVBoxLayout()
        ncols = 3
        for i, feat in enumerate(feat_list):
            if i%ncols == 0:
                line = QHBoxLayout()
            feature_check = wid.add_check( ""+feat, True, None, descr="" )
            line.addWidget(feature_check)
            self.features[ feat ] = [feature_check, feat_type]
            if i%ncols == (ncols-1):
                layout.addLayout( line )
                line = None
        if line is not None:
            layout.addLayout( line )
        return layout


    def close( self ):
        """ Close the pop-up window """
        self.hide()

    def choose( self ):
        """ Show the interface to select the choices """
        self.show()

    def get_current_settings( self, setting ):
        """ Get current settings of check or not of features """
        for feat, feat_cbox in self.features.items():
            setting[feat] = feat_cbox[0].isChecked()
        return setting

    def apply_settings( self, settings ):
        """ Set the checkboxes from preferenced settings """
        for feat, checked in settings.items():
            if feat in self.features.keys():
                self.features[feat][0].setChecked( checked )
        
    def get_features( self ):
        """ Returns the list of features to measure """
        feats = self.required
        feats_extra = []
        int_extra_feats = []
        int_feats = []
        other_feats = []
        self.do_intensity = False
        for feat, feat_cbox in self.features.items():
            if feat_cbox[0].isChecked():
                if feat_cbox[1] == "prop":
                    feats.append( feat )
                if feat_cbox[1] == "prop_extra":
                    feats_extra.append( feat )
                    if feat == "shape_index":
                        if "perimeter" not in feats:
                            feats.append("perimeter")
                        if "area" not in feats:
                            feats.append("area")
                    if feat == "roundness":
                        if "area" not in feats:
                            feats.append("area")
                        if "axis_major_length" not in feats:
                            feats.append("axis_major_length")
                    if feat == "aspect_ratio":
                        if "axis_major_length" not in feats:
                            feats.append("axis_major_length")
                        if "axis_minor_length" not in feats:
                            feats.append("axis_minor_length")
                if feat_cbox[1] == "other":
                    other_feats.append( feat )
                if feat_cbox[1] == "intensity_prop":
                    int_feats.append( feat )
                    self.do_intensity = True
                if feat_cbox[1] == "intensity_extra":
                    int_extra_feats.append( feat )
                    self.do_intensity = True
        return feats, feats_extra, other_feats, int_feats, int_extra_feats

    def get_channels( self ):
        """ Returns the list of channels to measure """
        if self.do_intensity:
            if self.chan_list is not None:
                wid_channels = self.chan_list.selectedItems()
                channels = []
                for chan in wid_channels:
                    channels.append( chan.text() )
            else:
                channels = ["Movie"]
            return channels
        return None

class EventClass( QWidget ):
    """ Choice of event types to export/measure """
    def __init__( self, epicure ):
        super().__init__()
        layout = QVBoxLayout()
        
        self.evt_classes = {}
        possible_classes = epicure.event_class
        event_layout = self.add_events( possible_classes )
        layout.addLayout( event_layout )

        bye = wid.add_button( "Ok", self.close, "Close the window" )
        layout.addWidget( bye )
        self.setLayout( layout )

    def add_events( self, event_list ):
        """ Add events to the GUI """
        layout = QVBoxLayout()
        ncols = 3
        for i, event in enumerate( event_list ):
            if i%ncols == 0:
                line = QHBoxLayout()
            event_check = wid.add_check_tolayout( line, ""+event, checked=True, descr="")
            self.evt_classes[ event ] = [ event_check ]
            if i%ncols == (ncols-1):
                layout.addLayout( line )
                line = None
        if line is not None:
            layout.addLayout( line )
        return layout


    def close( self ):
        """ Close the pop-up window """
        self.hide()

    def choose( self ):
        """ Show the interface to select the choices """
        self.show()

    def get_current_settings( self, setting ):
        """ Get current settings of check or not of features """
        for event, event_cbox in self.evt_classes.items():
            setting[event] = event_cbox[0].isChecked()
        return setting

    def apply_settings( self, settings ):
        """ Set the checkboxes from preferenced settings """
        for evt, checked in settings.items():
            if evt in self.evt_classes.keys():
                self.evt_classes[evt][0].setChecked( checked )
        
    def get_evt_classes( self ):
        """ Returns the list of events to measure """
        events = []
        for evt, evt_cbox in self.evt_classes.items():
            if evt_cbox[0].isChecked():
                events.append( evt )
        return events

class FeaturesTable(QWidget):
    """ Widget to visualize and interact with the measurement table """

    def __init__(self, napari_viewer, epicure):
        super().__init__()
        self.viewer = napari_viewer
        self.epicure = epicure
        self.wid_table = QTableWidget()
        self.wid_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.setLayout(QGridLayout())
        self.layout().addWidget(self.wid_table)
        self.wid_table.clicked.connect(self.show_label)
        self.wid_table.setSortingEnabled(True)

    def show_label(self):
        """ When click on the table, show selected cell """
        if self.wid_table is not None:
            row = self.wid_table.currentRow()
            self.epicure.seglayer.show_selected_label = False
            headers = [self.wid_table.horizontalHeaderItem(ind).text() for ind in range(self.wid_table.columnCount()) ]
            labelind = None
            if "label" in headers:
                labelind = headers.index("label") 
            if "Label" in headers:
                labelind = headers.index("Label") 
            frameind = None
            if "frame" in headers:
                frameind = headers.index("frame") 
            if labelind is not None and labelind >= 0:
                lab = int(self.wid_table.item(row, labelind).text())
                if frameind is not None:
                    ## set current frame to the selected row
                    frame = int(self.wid_table.item(row, frameind).text())
                    ut.set_frame(self.viewer, frame)
                else:
                    ## set current frame to the first frame where label or track is present
                    frame = self.epicure.tracking.get_first_frame( lab )
                    if frame is not None:
                        ut.set_frame(self.viewer, frame)
                self.epicure.seglayer.selected_label = lab
                self.epicure.seglayer.show_selected_label = True


    def get_features_list(self):
        """ Return list of measured features """
        return [ self.wid_table.horizontalHeaderItem(ind).text() for ind in range(self.wid_table.columnCount()) ]

    def set_table(self, table):
        self.wid_table.clear()
        self.wid_table.setRowCount(table.shape[0])
        self.wid_table.setColumnCount(table.shape[1])

        for c, column in enumerate(table.keys()):
            column_name = column
            self.wid_table.setHorizontalHeaderItem(c, QTableWidgetItem(column_name))
            for r, value in enumerate(table.get(column)):
                item = QTableWidgetItem()
                item.setData( Qt.EditRole, value)
                self.wid_table.setItem(r, c, item)

class TemporalPlots(QWidget):
    """ Widget to visualize and interact with temporal plots """

    def __init__(self, napari_viewer, epicure):
        super().__init__()
        self.viewer = napari_viewer
        self.epicure = epicure
        self.features_list = ["frame"]
        self.parameter_gui()
        self.vline = None
        self.ymin = None
        #self.viewer.window.add_dock_widget( self.plot_wid, name="Temporal plot" )
   
    def parameter_gui(self):
        """ add widget to choose plotting parameters """
        
        layout = QVBoxLayout()

        ## choice of feature to plot
        feat_choice, self.feature_choice = wid.list_line( label="Plot feature", descr="Choose the feature to plot", func=self.plot_feature )
        layout.addLayout(feat_choice)
        ## option to average by group
        ck_line, self.avg_group, self.smooth = wid.double_check( "Average by groups", False, self.plot_feature, "Show a line by cell or a line by group", "Smooth lines", False, self.plot_feature, "Smooth temporally (moving average) the plotted lines" )
        layout.addLayout(ck_line)
        ## show the plot
        self.plot_wid = self.create_plotwidget()
        layout.addWidget(self.plot_wid)
        ## save plot or save data of the plot
        line = wid.double_button( "Save plot image", self.save_plot_image, "Save the grapic in a PNG file", "Save plot data", self.save_plot_data, "Save the value used for the plot in .csv file" )
        self.by_label = wid.add_check( "Arranged data by label", False, None, "Save the data with one column by label" )
        line.addWidget( self.by_label )
        layout.addLayout( line )
        self.setLayout(layout)
        self.resize(1000,800)

    def setTable(self, table):
        """ Data table to plot """
        self.table = table
        self.features_list = self.table.keys()
        self.update_feature_list()

    def update_table(self, table):
        """ Update the current plot with the updated table """
        self.table = table
        curchoice = self.feature_choice.currentText()
        self.features_list = self.table.keys()
        self.update_feature_list()
        if curchoice in self.features_list:
            ind = list(self.features_list).index(curchoice)
            self.feature_choice.setCurrentIndex(ind)
        self.plot_feature()

    def update_feature_list(self):
        """ Update the list of feature in the GUI """
        self.feature_choice.clear()
        for feat in self.features_list:
            self.feature_choice.addItem(feat)
        if "division" in self.features_list and "extrusion" in self.features_list:
            self.feature_choice.addItem( "division&extrusion" )
    
    def plot_feature(self):
        """ Plot the selected feature in the temporal graph """
        feat = self.feature_choice.currentText()
        if feat == "label":
            return
        if feat == "":
            return
        if feat == "division&extrusion":
            feat = ["division", "extrusion"]
        else:
            feat = [feat]
        
        tab = list( zip(self.table["frame"]) )
        labname = []
        for ft in feat:
            tab = [ (*t, v) for t, v in zip( tab, self.table[ft]) ]
        tab = [ (*t, v) for t, v in zip( tab, self.table["label"]) ]
        labname.append("label")
        if "group" in self.table:
            tab = [ (*t, v) for t, v in zip( tab, self.table["group"]) ]
            labname.append("group")

        self.df = pand.DataFrame( tab, columns=["frame"] + feat + labname )
        shape = "linear"
        if self.smooth.isChecked():
            shape = "spline"
        if "group" in self.table and self.avg_group.isChecked():
            self.dfmean = self.df.groupby(['group', 'frame'])[feat].mean().reset_index()
            self.df.columns.name = 'group'
            self.fig = px.line( self.dfmean, x='frame', y=feat, color='group', labels={'frame': 'Time (frame)'}, line_shape=shape, render_mode="svg" )
        else:
            if len( np.unique(self.df["label"]) ) > 1000:
                ut.show_warning( "Too many lines to plot; Using a random subset instead" )
                subset = sample( np.unique(self.df["label"]).tolist(), 1000)
                subdf = self.df[self.df["label"].isin(subset)]
                self.fig = px.line( subdf, x="frame", y=feat[0], color="label", labels={'frame': 'Time (frame)'}, line_shape = shape, render_mode="svg")
                if len(feat) > 1:
                    addfig = px.line(subdf, x="frame", y=feat[1], color="label", line_shape = shape )
                    addfig.update_traces( patch={"line": {"dash":"dot"}} )
                    self.fig.add_trace( addfig.data[0] )
            else:
                self.fig = px.line( self.df, x="frame", y=feat[0], color="label", labels={'frame': 'Time (frame)'}, line_shape = shape, render_mode="svg")
                if len(feat) > 1:
                    addfig = px.line(self.df, x="frame", y=feat[1], color="label", line_shape = shape )
                    addfig.update_traces( patch={"line": {"dash":"dot"}} )
                    self.fig.add_trace( addfig.data[0] )
    
        self.browser.setHtml( self.fig.to_html(include_plotlyjs='cdn'))

    def smooth_df( self, df ):
        """ Smooth temporally the dataframe by label or by group """
        rollsize = 20
        ## average on a smaller scale if only few frames
        if np.max( self.table["frame"] ) <= 20:
            rollsize = 5    
        if feat+"_smooth" in self.df.columns:
            feat = feat+"_smooth"
        else:
            self.df[feat+"_smooth"] = self.df[feat].rolling(rollsize, center=True).mean()
            print(self.df)
            feat = feat+"_smooth"

    def save_plot_image( self ):
        """ Save current plot graphic to PNG image """
        feat = self.feature_choice.currentText()
        outfile = self.epicure.outname()+"_plot_"+feat+".png"
        if self.fig is not None:
            self.fig.write_image( outfile )
        if self.epicure.verbose > 0:
            ut.show_info("Measures saved in "+outfile)

    def save_plot_data( self ):
        """ Save the raw data to redraw the current plot to csv file """
        feat = self.feature_choice.currentText()
        outfile = self.epicure.outname()+"_time_"+feat+".csv"
        if self.avg_group.isChecked():
            data = self.dfmean.reset_index()[["frame", "group", feat]]
            if self.by_label.isChecked():
                df = pand.pivot_table( data, columns="label", index="frame", values=feat )
                df.to_csv( outfile,  sep='\t', header=True, index=True )
            else:
                data[["frame", "group", feat]].to_csv( outfile,  sep='\t', header=True, index=False )
        else:
            data = self.df.reset_index()[["frame", "label", feat]]
            if self.by_label.isChecked():
                df = pand.pivot_table( data, columns="label", index="frame", values=feat )
                df.to_csv( outfile,  sep='\t', header=True, index=True )
            else:
                data[["frame", "label", feat]].to_csv( outfile,  sep='\t', header=True, index=False )

    def move_framepos(self, frame):
        """ Move the vertical line showing the current frame position in the main window """
        return
        #if self.fig is not None:
        #    self.fig.add_vline( x=frame, line_dash="dash", line_color="gray" )
        #    self.browser.setHtml( self.fig.to_html(include_plotlyjs='cdn'))

    def create_plotwidget(self):
        """ Create plot window """
        self.browser = QWebEngineView(self)
        return self.browser

    

