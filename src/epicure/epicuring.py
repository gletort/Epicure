import numpy as np
import os, time, pickle
import napari
import math
from qtpy.QtWidgets import QPushButton, QVBoxLayout, QTabWidget, QWidget
from napari.utils import progress
from skimage.morphology import skeletonize 
from skimage.measure import regionprops 
from joblib import Parallel, delayed

import epicure.Utils as ut
from epicure.editing import Editing
from epicure.tracking import Tracking
from epicure.inspecting import Inspecting
from epicure.outputing import Outputing
from epicure.displaying import Displaying
from epicure.preferences import Preferences

"""
    EpiCure main
    Open and initialize the files
    Launch the main widget composed of the segmentation and tracking editing features
"""

class EpiCure():
    
    def __init__(self, viewer=None):
        self.viewer = viewer
        if self.viewer is None:
            self.viewer = napari.Viewer(show=False)
        self.viewer.title = "Napari - EpiCure"
        self.init_epicure_metadata()   ## initialize metadata variables (scalings, channels)
        self.img = None
        self.inspecting = None
        self.others = None
        self.imgshape2D = None    ## width, height of the image
        self.nframes = None       ## Number of time frames
        self.thickness = 4 ## thickness of junctions, wider
        self.minsize = 4   ## smallest number of pixels in a cell
        self.verbose = 1  ## level of printing messages (None/few, normal, debug mode)
        self.event_class = ["division", "extrusion", "suspect"] ## list of possible events
        
        self.overtext = dict()
        self.help_index = 1   ## current display index of help overlay
        self.blabla = None    ## help window
        self.groups = {}
        self.tracked = 0 ## has done a tracking
        self.process_parallel = False ## Do some operations in parallel (n frames in parallel)
        self.nparallel = 4      ## number of parallel threads
        self.dtype = np.uint32  ## label type, default 32 but if less labels, reduce it
        self.outputing = None   ## non initialized yet
        
        self.forbid_gaps = False  ## allow gaps in track or not

        self.pref = Preferences()
        self.shortcuts = self.pref.get_shortcuts() ## user specific shortcuts
        self.settings = self.pref.get_settings() ## user specific preferences
        ## display settings
        self.display_colors = None  ## settings for changing some display colors
        if "Display" in self.settings:
            if "Colors" in self.settings["Display"]:
                self.display_colors = self.settings["Display"]["Colors"]

    def init_epicure_metadata( self ):
        """ Returns metadata to save """
        ## scalings and unit names
        self.epi_metadata = {}
        self.epi_metadata["ScaleXY"] = 1
        self.epi_metadata["UnitXY"] = "um"
        self.epi_metadata["ScaleT"] = 1
        self.epi_metadata["UnitT"] = "min"
        self.epi_metadata["MainChannel"] = 0
        self.epi_metadata["Allow gaps"] = True
        self.epi_metadata["Verbose"] = 1
        self.epi_metadata["Scale bar"] = True
        self.epi_metadata["MovieFile"] = ""
        self.epi_metadata["SegmentationFile"] = ""
        self.epi_metadata["EpithelialCells"] = True  ## epithelial (packed) cells
        self.epi_metadata["Reloading"] = False   ## Never been epiCured yet

    def get_resetbtn_color( self ):
        """ Returns the color of Reset buttons if defined """
        if "Display" in self.settings:
            if "Colors" in self.settings["Display"]:
                if "Reset button" in self.settings["Display"]["Colors"]:
                    return self.settings["Display"]["Colors"]["Reset button"]
        return None

    def set_thickness( self, thick ):
        """ Thickness of junctions (half thickness) """
        self.thickness = thick

    def load_movie(self, imgpath):
        """ Load the intensity movie, and get metadata """
        self.epi_metadata["MovieFile"] = imgpath
        self.img, nchan, self.epi_metadata["ScaleXY"], self.epi_metadata["UnitXY"], self.epi_metadata["ScaleT"], self.epi_metadata["UnitT"] = ut.opentif( self.epi_metadata["MovieFile"], verbose=self.verbose>1 )
        ## transform static image to movie (add temporal dimension)
        if len(self.img.shape) == 2:
            self.img = np.expand_dims(self.img, axis=0)
        caxis = None
        cval = 0
        if nchan>0 or len(self.img.shape) > 3:
            if nchan > 0 and len(self.img.shape) > 3:
                ## multiple chanels and multiple slices, order axis should be TCXY
                caxis = 1
                cval = nchan
            else:
                ## image has multiple chanels
                minshape = min(self.img.shape)
                caxis = self.img.shape.index(minshape)
                cval = minshape
            self.mov = self.img

        ## display the movie
        ut.remove_layer(self.viewer, "Movie")
        mview = self.viewer.add_image( self.img, name="Movie", blending="additive", colormap="gray" )
        mview.contrast_limits = self.quantiles()
        mview.gamma = 0.95
        
        self.imgshape = self.viewer.layers["Movie"].data.shape
        self.imgshape2D = self.imgshape[1:3]
        self.nframes = self.imgshape[0]
        return caxis, cval

    def quantiles(self):
        return tuple(np.quantile(self.img, [0.01, 0.9999]))

    def set_verbose( self, verbose ):
        """ Set verbose level """
        self.verbose = verbose
        self.epi_metadata["Verbose"] = verbose

    def set_gaps_option( self, allow_gap ):
        """ Set the mode for gap allowing/forbid in tracks """
        self.epi_metadata["Allow gaps"] = allow_gap
        self.forbid_gaps = not allow_gap

    def set_epithelia( self, epithelia ):
        """ Set the mode for cell packing (touching or not especially) """
        self.epi_metadata["EpithelialCells"] = epithelia

    def set_scalebar( self, show_scalebar ):
        """ Show or not the scale bar """
        self.epi_metadata["Scale bar"] = show_scalebar
        if self.viewer is not None:
            self.viewer.scale_bar.visible = show_scalebar
            self.viewer.scale_bar.unit = self.epi_metadata["UnitXY"]
            for lay in self.viewer.layers:
                lay.scale = [1, self.epi_metadata["ScaleXY"], self.epi_metadata["ScaleXY"]]
            self.viewer.reset_view()

    def set_scales( self, scalexy, scalet, unitxy, unitt ):
        """ Set the scaling units for outputs """
        self.epi_metadata["ScaleXY"] = scalexy
        self.epi_metadata["ScaleT"] = scalet
        self.epi_metadata["UnitXY"] = unitxy
        self.epi_metadata["UnitT"] = unitt
        if self.viewer is not None:
            self.viewer
        if self.verbose > 0:
            ut.show_info( "Movie scales set to "+str(self.epi_metadata["ScaleXY"])+" "+self.epi_metadata["UnitXY"]+" and "+str(self.epi_metadata["ScaleT"])+" "+self.epi_metadata["UnitT"] )

    def set_chanel( self, chan, chanaxis ):
        """ Update the movie to the correct chanel """
        self.img = np.rollaxis(np.copy(self.mov), chanaxis, 0)[chan]
        self.main_channel = chan
        if self.viewer is not None:
            mview = self.viewer.layers["Movie"]
            mview.data = self.img
            mview.contrast_limits=self.quantiles()
            mview.gamma=0.95
            mview.refresh()

    def add_other_chanels(self, chan, chanaxis): 
        """ Open other channels if option selected """
        self.others = np.delete(self.mov, chan, axis=chanaxis)
        self.others_chanlist = []
        if self.others is not None:
            self.others = np.rollaxis(self.others, chanaxis, 0)
            for ochan in range(self.others.shape[0]):
                purechan = ochan
                if purechan >= chan:
                    purechan = purechan + 1
                self.others_chanlist.append(purechan)
                mview = self.viewer.add_image( self.others[ochan], name="MovieChannel_"+str(purechan), blending="additive", colormap="gray" )
                mview.contrast_limits=tuple(np.quantile(self.others[ochan],[0.01, 0.9999]))
                mview.gamma=0.95
                mview.visible = False
        
    def load_segmentation(self, segpath):
        """ Load the segmentation file """
        start_time = ut.start_time()
        self.epi_metadata["SegmentationFile"] = segpath
        self.seg,_, _,_,_,_ = ut.opentif( segpath, verbose=self.verbose>1 )
        self.seg = np.uint32(self.seg)
        ## transform static image to movie (add temporal dimension)
        if len(self.seg.shape) == 2:
            self.seg = np.expand_dims(self.seg, axis=0)
        ## ensure that the shapes are correctly set
        self.imgshape = self.seg.shape
        self.imgshape2D = self.seg.shape[1:3]
        self.nframes = self.seg.shape[0]
        ## if the segmentation is a junction file, transform it to a label image 
        if ut.is_binary(self.seg):
            self.junctions_to_label()
            self.tracked = 0
        else:
            self.has_been_tracked()
            self.prepare_labels()

        ## define a reference size of the movie to scale default parameters
        self.reference_size = np.max( self.imgshape2D )
        ## define the average cell radius
        #self.cell_avg_radius = int( math.sqrt( ut.average_area( self.seg[0])/math.pi ) )
        # on cell area ut.summary_labels( self.seg[0] )
        #if self.verbose > 1:
        #    print("Reference size of the movie: "+str(self.reference_size))

        self.epi_metadata["Reloading"] = True ## has been formatted to EpiCure format

        # display the segmentation file movie
        if self.viewer is not None:
            self.seglayer = self.viewer.add_labels( self.seg, name="Segmentation", blending="additive", opacity=0.5, scale=self.viewer.layers["Movie"].scale )
            self.viewer.dims.set_point(0,0)
            self.seglayer.brush_size = 4 ## default label pencil drawing size 
        if self.verbose > 0:
            ut.show_duration(start_time, header="Segmentation loaded in ")

    def load_tracks( self, progress_bar ):
        """ From the segmentation, get all the metadata """
        tracked = "tracked"
        self.tracking.init_tracks()
        if self.tracked == 0:
            tracked = "untracked"
        else:
            if self.forbid_gaps:
                progress_bar.set_description( "check and fix track gaps" )
                self.handle_gaps( track_list=None, verbose=1 )
        ut.show_info(""+str(len(self.tracking.get_track_list()))+" "+tracked+" cells loaded")

    def has_been_tracked(self):
        """ Look if has been tracked already (some labels are in several frames) """
        nb = 0
        for frame in range(self.seg.shape[0]):
            if frame > 0:
                inter = np.intersect1d(np.unique(self.seg[frame-1]), np.unique(self.seg[frame]))
                if len(inter)>1:
                    self.tracked = 1 
                    return
        self.tracked = 0
        return

    def suggest_segfile(self, outdir):
        """ Check if a segmentation file from EpiCure already exists """
        if (self.epi_metadata["SegmentationFile"] != "") and ut.found_segfile(self.epi_metadata["SegmentationFile"]):
            return self.epi_metadata["SegmentationFile"]
        imgname, imgdir, out = ut.extract_names( self.epi_metadata["MovieFile"], outdir, mkdir=False )
        return ut.suggest_segfile(out, imgname)

    def outname(self):
        return os.path.join(self.outdir, self.imgname)

    def set_names(self, outdir):
        """ Extract default names from imgpath """
        self.imgname, self.imgdir, self.outdir = ut.extract_names( self.epi_metadata["MovieFile"], outdir, mkdir=True )

    def go_epicure( self, outdir="epics", segmentation_file=None ):
        """ Initialize everything and start the main widget """
        self.set_names( outdir )
        if segmentation_file is None:
            segmentation_file = self.suggest_segfile( outdir )
        self.viewer.window._status_bar._toggle_activity_dock(True)
        progress_bar = progress(total=5)
        progress_bar.set_description( "Reading segmented image" )
        ## load the segmentation
        self.load_segmentation( segmentation_file )
        self.epi_metadata["SegmentationFile"] = segmentation_file
        progress_bar.update(1)
        ut.set_active_layer( self.viewer, "Segmentation" )
        
        ## setup the main interface and shortcuts
        start_time = ut.start_time()
        progress_bar.set_description( "Active EpiCure shortcuts" )
        self.key_bindings()
        progress_bar.update(2)
        progress_bar.set_description( "Prepare widget" )
        self.main_widget()
        progress_bar.update(3)
        progress_bar.set_description( "Load tracks" )
        self.load_tracks( progress_bar )
        progress_bar.update(4)

        ## load graph if it exists
        epiname = os.path.join( self.outdir, self.imgname+"_epidata.pkl" )
        if os.path.exists(epiname):
            progress_bar.set_description( "Load EpiCure informations" )
            self.load_epicure_data(epiname)
        if self.verbose > 0:
            ut.show_duration(start_time, header="Tracks and graph loaded in ")
        progress_bar.update(5)
        self.apply_settings()
        progress_bar.close()
        self.viewer.window._status_bar._toggle_activity_dock(False)

###### Settings (preferences) save and load
    def apply_settings( self ):
        """ Apply all default or prefered settings """
        for sety, val in self.settings.items():
            if sety=="Display":
                self.display.apply_settings( val )
                if "Show help" in val:
                    index = int( val["Show help"] )
                    self.switchOverlayText( index )
                if "Contour" in val:
                    contour = int( val["Contour"] )
                    self.seglayer.contour = contour
                    self.seglayer.refresh()
                if "Colors" in val:
                    color = val["Colors"]["button"]
                    check_color = val["Colors"]["checkbox"]
                    line_edit_color = val["Colors"]["line edit"]
                    group_color = val["Colors"]["group"]
                    self.main_gui.setStyleSheet( 'QPushButton {background-color: '+color+'} QCheckBox::indicator {background-color: '+check_color+'} QLineEdit {background-color: '+line_edit_color+'} QGroupBox {color: grey; background-color: '+group_color+'} ')
                    self.display_colors = val["Colors"]
            if sety == "events":
                self.inspecting.apply_settings( val )
            if sety == "Output":
                self.outputing.apply_settings( val )
            if sety == "Track":
                self.tracking.apply_settings( val )
            if sety == "Edit":
                self.editing.apply_settings( val )
            #case _:
            #       continue
            ## match is not compatible with python 3.9

    def update_settings( self ):
        """ Returns all the prefered settings """
        disp = self.settings
        ## load display current settings (layers visibility)
        disp["Display"] = self.display.get_current_settings()
        disp["Display"]["Show help"] = self.help_index
        disp["Display"]["Contour"] = self.seglayer.contour
        ## load suspect current settings
        disp["events"] = self.inspecting.get_current_settings()
        ## get outputs current settings
        disp["Output"] = self.outputing.get_current_settings()
        disp["Track"] = self.tracking.get_current_settings()
        disp["Edit"] = self.editing.get_current_settings()

#### Main widget that contains the tabs of the sub widgets
    
    def main_widget(self):
        """ Open the main widget interface """
        self.main_gui = QWidget()
        
        layout = QVBoxLayout()
        tabs = QTabWidget()
        tabs.setObjectName("main")
        layout.addWidget(tabs)
        self.main_gui.setLayout(layout)
        
        self.editing = Editing(self.viewer, self)
        tabs.addTab( self.editing, "Edit" )
        self.inspecting = Inspecting(self.viewer, self)
        tabs.addTab( self.inspecting, "Inspect" )
        self.tracking = Tracking(self.viewer, self)
        tabs.addTab( self.tracking, "Track" )
        self.outputing = Outputing(self.viewer, self)
        tabs.addTab( self.outputing, "Output" )
        self.display = Displaying(self.viewer, self)
        tabs.addTab( self.display, "Display" )
        self.main_gui.setStyleSheet('QPushButton {background-color: rgb(40, 60, 75)} QCheckBox::indicator {background-color: rgb(40,52,65)}')

        self.viewer.window.add_dock_widget( self.main_gui, name="Main" )

    def key_bindings(self):
        """ Activate shortcuts """
        self.text = "-------------- ShortCuts -------------- \n "
        self.text += "!! Shortcuts work if Segmentation layer is active !! \n"
        #for sctype, scvals in self.shortcuts.items():
        self.text += "\n---"+"General"+" options---\n"
        sg = self.shortcuts["General"]
        self.text += ut.print_shortcuts( sg )
        self.text = self.text + "\n"
        
        if self.verbose > 0:
            print("Activating key shortcuts on segmentation layer")
            print("Press <" + str(sg["show help"]["key"]) + "> to show/hide the main shortcuts")
            print("Press <" + str(sg["show all"]["key"]) + "> to show ALL shortcuts")
        ut.setOverlayText(self.viewer, self.text, size=10)
        
        @self.seglayer.bind_key( sg["show help"]["key"], overwrite=True )
        def switch_shortcuts(seglayer):
            #index = (self.help_index+1)%(len(self.overtext.keys())+1)
            #self.switchOverlayText(index)
            index = (self.help_index+1)%2
            self.switchOverlayText( index )
        
        @self.seglayer.bind_key( sg["show all"]["key"], overwrite=True )
        def list_all_shortcuts(seglayer):
            self.switchOverlayText(0)   ## hide display message in main window
            text = "**************** EPICURE *********************** \n"
            text += "\n"
            text += self.text
            text += "\n"
            text += ut.napari_shortcuts()
            for key, val in self.overtext.items():
                text += "\n"
                text += val
            self.update_text_window(text) 
        
        @self.seglayer.bind_key( sg["save segmentation"]["key"], overwrite=True )
        def save_seglayer(seglayer):
            self.save_epicures()
        
        @self.viewer.bind_key( sg["save movie"]["key"], overwrite=True )
        def save_movie(seglayer):
            endname = "_frames.tif"
            outname = os.path.join( self.outdir, self.imgname+endname )
            self.save_movie(outname)

########### Texts 

    def switchOverlayText(self, index):
        """ Switch overlay display text to index """
        self.help_index = index
        if index == 0:
            ut.showOverlayText(self.viewer, vis=False)
            return
        else:
            ut.showOverlayText(self.viewer, vis=True)
        #self.setCurrentOverlayText()
        self.setGeneralOverlayText()

    def init_text_window( self ):
        """ Creates and opens a pop-up window with shortcut list """
        self.blabla = ut.create_text_window( "EpiCure shortcuts" )

    def update_text_window(self, message):
        """ Update message in separate window """
        self.init_text_window()
        self.blabla.value = message

    def setGeneralOverlayText(self):
        """ set overlay help message to general message """
        text = self.text
        ut.setOverlayText(self.viewer, text, size=10)

    def setCurrentOverlayText(self):
        """ Set overlay help text message to current selected options list """
        text = self.text
        dispkey = list(self.overtext.keys())[self.help_index-1]
        text += self.overtext[dispkey]
        ut.setOverlayText(self.viewer, text, size=10)
    
    def get_summary(self):
        """ Get a summary of the infos of the movie """
        summ = "----------- EpiCure summary ----------- \n"
        summ += "--- Image infos \n"
        summ += "Movie name: "+str(self.epi_metadata["MovieFile"])+"\n"
        summ += "Movie size (x,y): "+str(self.imgshape2D)+"\n"
        if self.nframes is not None:
            summ += "Nb frames: "+str(self.nframes)+"\n"
        summ += "\n"
        summ += "--- Segmentation infos \n"
        summ += "Segmentation file: "+str(self.epi_metadata["SegmentationFile"])+"\n"
        summ += "Nb tracks: "+str(len(self.tracking.get_track_list()))+"\n"
        tracked = "yes"
        if self.tracked == 0:
            tracked = "no"
        summ += "Tracked: "+tracked+"\n"
        nb_labels, mean_duration, mean_area = ut.summary_labels( self.seg )
        summ += "Nb cells: "+str( nb_labels )+"\n"
        summ += "Average track lengths: "+str(mean_duration)+" frames\n"
        summ += "Average cell area: "+str(mean_area)+" pixels^2\n"
        summ += "Nb suspect events: "+str(self.inspecting.nb_events(only_suspect=True))+"\n"
        summ += "Nb divisions: "+str(self.inspecting.nb_type("division"))+"\n"
        summ += "Nb extrusions: "+str(self.inspecting.nb_type("extrusion"))+"\n"
        summ += "\n"
        summ += "--- Parameter infos \n"
        summ += "Junction thickness: "+str(self.thickness)+"\n"
        return summ

    def set_contour( self, width ):
        self.seglayer.contour = width

############ Layers

    def check_layers(self):
        """ Check that the necessary layers are present """
        if self.editing.shapelayer_name not in self.viewer.layers:
            if self.verbose > 0:
                print("Reput shape layer")
            self.editing.create_shapelayer()
        if self.inspecting.eventlayer_name not in self.viewer.layers:
            if self.verbose > 0:
                print("Reput event layer")
            self.inspecting.create_eventlayer()
        if "Movie" not in self.viewer.layers:
            if self.verbose > 0:
                print("Reput movie layer")
            mview = self.viewer.add_image( self.img, name="Movie", blending="additive", colormap="gray", scale=[1, self.epi_metadata["ScaleXY"], self.epi_metadata["ScaleXY"]])
            #mview.reset_contrast_limits()
            mview.contrast_limits=self.quantiles()
            mview.gamma=0.95
        if "Segmentation" not in self.viewer.layers:
            if self.verbose > 0:
                print("Reput segmentation")
            self.seglayer = self.viewer.add_labels( self.seg, name="Segmentation", blending="additive", opacity=0.5, scale=self.viewer.layers["Movie"].scale )

        self.finish_update()


    def finish_update(self, contour=None):
        if contour is not None:
            self.seglayer.contour = contour
        ut.set_active_layer( self.viewer, "Segmentation" )
        self.seglayer.refresh()
        duplayers = ["PrevSegmentation"]
        for dlay in duplayers:
            if dlay in self.viewer.layers:
                (self.viewer.layers[dlay]).refresh()
    
    def read_epicure_metadata( self ):
        """ Load saved infos from file """
        epiname = self.outname() + "_epidata.pkl" 
        if os.path.exists( epiname ):
            infile = open(epiname, "rb")
            try:
                epidata = pickle.load( infile )
                if "EpiMetaData" in epidata.keys():
                    for key, vals in epidata["EpiMetaData"].items():
                        self.epi_metadata[key] = vals
                infile.close()
            except:
                ut.show_warning( "Could not read EpiCure data file "+epiname )


    def save_epicures( self, imtype="float32" ):
        outname = os.path.join( self.outdir, self.imgname+"_labels.tif" )
        ut.writeTif(self.seg, outname, self.epi_metadata["ScaleXY"], imtype, what="Segmentation")
        epiname = os.path.join( self.outdir, self.imgname+"_epidata.pkl" )
        outfile = open(epiname, "wb")
        epidata = {}
        epidata["EpiMetaData"] = self.epi_metadata
        if self.groups is not None:
            epidata["Group"] = self.groups
        if self.tracking.graph is not None:
            epidata["Graph"] = self.tracking.graph
        if self.inspecting is not None and self.inspecting.events is not None:
            epidata["Events"] = {}
            if self.inspecting.events.data is not None:
                epidata["Events"]["Points"] = self.inspecting.events.data
                epidata["Events"]["Props"] = self.inspecting.events.properties
                epidata["Events"]["Types"] = self.inspecting.event_types
                #epidata["Events"]["Symbols"] = self.inspecting.events.symbol
                #epidata["Events"]["Colors"] = self.inspecting.events.face_color
        pickle.dump( epidata, outfile )
        outfile.close()
    
    def read_group_data( self, groups ):
        """ Read the group EpiCure data from opened file """
        if self.verbose > 0:
            print( "Loaded cell groups info: "+str(list(groups.keys())) )
            if self.verbose > 2:
                print( "Cell groups: "+str(groups) )
        return groups
        
    def read_graph_data( self, infile ):
        """ Read the graph EpiCure data from opened file """
        try:
            graph = pickle.load(infile)
            if self.verbose > 0:
                print("Graph (lineage) loaded")
            return graph
        except:
            if self.verbose > 1:
                print("No graph infos found")
            return None

    def read_events_data(self, infile):
        """ Read info of EpiCure events (suspects, divisions) from opened file """
        try:
            events_pts = pickle.load(infile)
            if events_pts is not None:
                events_props = pickle.load(infile)
                events_type = pickle.load(infile)
                try:
                    symbols = pickle.load(infile)
                    colors = pickle.load(infile)
                except: 
                    if self.verbose > 1:
                        print("No events display info found")
                    symbols = None
                    colors = None
                return events_pts, events_props, events_type
            else:
                return None, None, None
        except:
            if self.verbose > 1:
                print("events info not complete")
            return None, None, None

    def load_epicure_data(self, epiname):
        """ Load saved infos from file """
        infile = open(epiname, "rb")
        try:
            epidata = pickle.load( infile )
            if "EpiMetaData" in epidata.keys():
                # version of epicure file after Epicure 0.2.0
                self.read_epidata( epidata )
                infile.close()
            else:
                # version anterior of Epicure 0.2.0
                self.load_epicure_data_old( epidata, infile )
        except:
            ut.show_warning( "Could not read EpiCure data file "+epiname )

    def read_epidata( self, epidata ):
        """ Read the dict of saved state and initialize all instances with it """
        for key, vals in epidata.items():
            if key == "EpiMetaData":
                ## image data is read on the previous step
                continue
            if key == "Group":
                ## Load groups information
                self.groups = self.read_group_data( vals )
                self.update_group_lists()
            if key == "Graph":
                ## Load graph (lineage) informations
                self.tracking.graph = vals
                if self.tracking.graph is not None:
                    self.tracking.tracklayer.refresh()
            if key == "Events":
                ## Load events information
                if "Points" in vals.keys():
                    pts = vals["Points"]
                if "Props" in vals.keys():
                    props = vals["Props"]
                if "Types" in vals.keys():
                    event_types = vals["Types"]
                #if "Symbols" in vals.keys():
                #    symbols = vals["Symbols"]
                #if "Colors" in vals.keys():
                #    colors = vals["Colors"] 
                if pts is not None:
                    if len(pts) > 0:
                        self.inspecting.load_events(pts, props, event_types)
                    if len(pts) > 0 and self.verbose > 0:
                        print("events loaded")
                    ut.show_info("Loaded "+str(len(pts))+" events")     
               

    def load_epicure_data_old( self, groups, infile ):
        """ Load saved infos from file """
        ## Load groups information
        self.groups = self.read_group_data( groups )
        for group in self.groups.keys():
            self.editing.update_group_list( group )
        self.outputing.update_selection_list()
        ## Load graph (lineage) informations
        self.tracking.graph = self.read_graph_data( infile )
        if self.tracking.graph is not None:
            self.tracking.tracklayer.refresh()
        ## Load events information 
        pts, props, event_types = self.read_events_data( infile )
        if pts is not None:
            if len(pts) > 0:
                self.inspecting.load_events(pts, props, event_types)
                if len(pts) > 0 and self.verbose > 0:
                    print("events loaded")
                    ut.show_info("Loaded "+str(len(pts))+" events")
        infile.close()

    def save_movie(self, outname):
        """ Save movie with current display parameters, except zoom """
        save_view = self.viewer.camera.copy()
        save_frame = ut.current_frame(self.viewer)
        ## place the view to see the whole image
        self.viewer.reset_view()
        #self.viewer.camera.zoom = 1
        sizex = (self.imgshape2D[0]*self.viewer.camera.zoom)/2
        sizey = (self.imgshape2D[1]*self.viewer.camera.zoom)/2
        if os.path.exists(outname):
            os.remove(outname)

        ## take a screenshot of each frame
        for frame in range(self.nframes):
            self.viewer.dims.set_point(0, frame)
            shot = self.viewer.window.screenshot(canvas_only=True, flash=False)
            ## remove border: movie is at the center
            centx = int(shot.shape[0]/2)+1
            centy = int(shot.shape[1]/2)+1
            shot = shot[int(centx-sizex):int(centx+sizex), int(centy-sizey):int(centy+sizey),]
            ut.appendToTif(shot, outname)
        self.viewer.camera.update(save_view)
        if save_frame is not None:
            self.viewer.dims.set_point(0, save_frame)
        ut.show_info("Movie "+outname+" saved")

    def reset_data( self ):
        """ Reset EpiCure data (group, suspect, graph) """
        self.inspecting.reset_all_events()
        self.reset_groups()
        self.tracking.graph = None

    def junctions_to_label(self):
        """ convert epyseg/skeleton result (junctions) to labels map """
        ## ensure that skeleton is thin enough
        for z in range(self.seg.shape[0]):
            self.skel_one_frame(z)
        self.seg = ut.reset_labels( self.seg, closing=True )
    
    def skel_one_frame(self, z):
        """ From segmentation of junctions of one frame, get it as a correct skeleton """
        skel = skeletonize( self.seg[z]/np.max(self.seg[z] ))
        skel = ut.copy_border( skel, self.seg[z] )
        self.seg[z] = np.invert(skel)

    def reset_labels( self ):
        """ Reset all labels, ensure unicity """
        if self.epi_metadata["EpithelialCells"]:
            ### packed (contiguous cells), ensure that they are separated by one pixel only
            skel = self.get_skeleton()
            skel = np.uint32( skel )
            self.seg = skel
            self.seglayer.data = skel
            self.junctions_to_label()
            self.seglayer.data = self.seg      
        else:
            self.get_cells()

    def check_extrusions_sanity( self ):
        """ Check that extrusions seem to be correct (last of tracks )"""
        extrusions = self.inspecting.get_events_from_type( "extrusion" )
        nrem = 0
        if (extrusions is not None) and (extrusions != []):
            for extr_id in extrusions:
                pos, label = self.inspecting.get_event_infos( extr_id )
                last_frame = self.tracking.get_last_frame( label)
                if pos[0] != last_frame:
                    if self.verbose > 1:
                        print("Extrusion "+str(extr_id)+" at frame "+str(pos[0])+" not at the end of track "+str(label))
                        print("Removing it")
                    self.inspecting.remove_one_event( extr_id )
                    nrem = nrem + 1
            print("Removed "+str(nrem)+" extrusions that dit not correspond to the end of tracks")
        
    def prepare_labels(self):
        """ Process the labels to be in a correct Epicurable format """
        if self.epi_metadata["EpithelialCells"]:
            if self.epi_metadata["Reloading"]:
                ## if opening an already EpiCured movie, assume it's in correct format
                return
            ### packed (contiguous cells), ensure that they are separated by one pixel only
            self.thin_boundaries()
        else:
            self.get_cells()

    def get_cells( self ):
        """ Non jointive cells: check label unicity """
        for frame in self.seg:
            if ut.non_unique_labels( frame ):
                self.seg = ut.reset_labels( self.seg, closing=True )
                return
    
    def thin_boundaries(self):
        """" Assure that all boundaries are only 1 pixel thick """
        if self.process_parallel:
            self.seg = Parallel( n_jobs = self.nparallel ) (
                delayed( ut.thin_seg_one_frame )(zframe) for zframe in self.seg 
                )
            self.seg = np.array( self.seg )
        else:
            for z in range(self.seg.shape[0]):
                self.seg[z] = ut.thin_seg_one_frame( self.seg[z] )


    def add_skeleton(self):
        """ add a layer containing the skeleton movie of the segmentation """
        # display the segmentation file movie
        if self.viewer is not None:
            skel = np.zeros(self.seg.shape, dtype="uint8")
            skel[self.seg==0] = 1
            skel = self.get_skeleton( viewer=self.viewer )
            ut.remove_layer(self.viewer, "Skeleton")
            skellayer = self.viewer.add_image( skel, name="Skeleton", blending="additive", opacity=1, scale=self.viewer.layers["Movie"].scale )
            skellayer.reset_contrast_limits()
            skellayer.contrast_limits = (0,1)
    
    def get_skeleton(self, viewer=None):
        """ convert labels movie to skeleton (thin boundaries) """
        if self.seg is None:
            return None
        parallel = 0
        if self.process_parallel:
            parallel = self.nparallel
        return ut.get_skeleton( self.seg, viewer = viewer, verbose = self.verbose, parallel = parallel )


    ############ Label functions

    def get_free_labels(self, nlab):
        """ Get the nlab smallest unused labels """
        used = set(self.tracking.get_track_list())
        return ut.get_free_labels( used, nlab )

    def get_free_label(self):
        """ Return the first free label """
        return self.get_free_labels(1)[0]

    def has_label(self, label):
        """ Check if label is present in the tracks """
        return self.tracking.has_track(label)
    
    def has_labels(self, labels):
        """ Check if labels are present in the tracks """
        return self.tracking.has_tracks( labels )

    def nlabels(self):
        """ Number of unique tracks """
        return self.tracking.nb_tracks()

    def get_labels(self):
        """ Return list of labels in tracks """
        return list(self.tracking.get_track_list())

    ########## Edit tracks
    def delete_tracks(self, tracks):
        """ Remove all the tracks from the Track layer """
        self.tracking.remove_tracks( tracks )

    def delete_track(self, label, frame=None):
        """ Remove (part of) the track """
        if frame is None:
            self.tracking.remove_track(label)
        else:
            self.tracking.remove_one_frame(label, frame, handle_gaps=self.forbid_gaps )

    def update_centroid(self, label, frame):
        """ Track label has been change at given frame """
        if label not in self.tracking.has_track(label):
            if self.verbose > 1:
                print("Track "+str(label)+" not found")
            return
        self.tracking.update_centroid(label, frame)

    ########## Edit label
    def get_label_indexes (self, label, start_frame=0 ):
        """ Returns the indexes where label is present in segmentation, starting from start_frame """
        indmodif = []
        if self.verbose > 2:
            start_time = ut.start_time()
        pos = self.tracking.get_track_column( track_id=label, column="fullpos" )
        pos = pos[pos[:,0]>=start_frame]
        ## if nothing in pos, pb with track data
        if pos is None or len(pos)==0: 
            ut.show_warning("Something wrong in the track data. Resetting track data (can take time)")
            self.tracking.reset_tracks()
            self.get_label_indexes( label, start_frame )

        indmodif = np.argwhere( self.seg[pos[:,0]] == label )
        indmodif = ut.shiftFrames( indmodif, pos[:,0] )
        if self.verbose > 2:
            ut.show_duration(start_time, header="Label indexes found in ")
        return indmodif

    def replace_label( self, label, new_label, start_frame=0 ):
        """ Replace label with new_label from start_frame - Relabelling only """
        indmodif = self.get_label_indexes( label, start_frame )
        new_labels = [new_label]*len(indmodif)
        self.change_labels( indmodif, new_labels, replacing=True )
    
    def change_labels_frommerge(self, indmodif, new_labels, remove_labels ):
        """ Change the value at pixels indmodif to new_labels and update tracks/graph. Full remove of the two merged labels """
        if len(indmodif)>0:
            ## get effectively changed labels
            indmodif, new_labels, _ = ut.setNewLabel( self.seglayer, indmodif, new_labels, add_frame=None, return_old=False )
            if len(new_labels) > 0:
                self.update_added_labels( indmodif, new_labels )
                self.update_removed_labels( indmodif, remove_labels )
        self.seglayer.refresh()
    
    def change_labels(self, indmodif, new_labels, replacing=False):
        """ Change the value at pixels indmodif to new_labels and update tracks/graph 
    
            Assume that only label at current frame can have its shape modified. Other changed label is only relabelling at frames > current frame (child propagation)
        """
        if len(indmodif)>0:
            ## get effectively changed labels
            indmodif, new_labels, old_labels = ut.setNewLabel( self.seglayer, indmodif, new_labels, add_frame=None )
            if len(new_labels) > 0:
                if replacing:
                    self.update_replaced_labels( indmodif, new_labels, old_labels )
                else:
                    ## the only label to change are the current frame (smaller one), the other are only relabelling (propagation)
                    cur_frame = np.min( indmodif[0] )
                    to_reshape = (indmodif[0] == cur_frame)
                    self.update_changed_labels( (indmodif[0][to_reshape], indmodif[1][to_reshape], indmodif[2][to_reshape]), new_labels[to_reshape], old_labels[to_reshape] )
                    to_relab = np.invert(to_reshape)
                    self.update_replaced_labels( (indmodif[0][to_relab], indmodif[1][to_relab], indmodif[2][to_relab]), new_labels[to_relab], old_labels[to_relab] )
        self.seglayer.refresh()

    def get_mask( self, label, start=None, end=None ):
        """ Get mask of label from frame start to frame end """
        if (start is None) or (end is None):
            start, end = self.tracking.get_extreme_frames( label )
        crop = self.seg[start:(end+1)]
        mask = np.isin( crop, [label] )*1
        return mask

    def get_label_movie( self, label, extend=1.25 ):
        """ Get movie centered on label """
        start, end = self.tracking.get_extreme_frames( label )
        mask = self.get_mask( label, start, end )
        boxes = []
        centers = []
        max_box = 0
        for frame in mask:
            props = regionprops( frame )
            bbox = props[0].bbox
            boxes.append(bbox)
            centers.append(props[0].centroid)
            for i in range(2):
                max_box = max( max_box, bbox[i+2]-bbox[i] )
        
        box_size = int(max_box*extend)
        movie = np.zeros((end-start+1, box_size, box_size))
        for i, frame in enumerate(range(start, end+1)):
            xmin = int(centers[i][0] - box_size/2)
            xminshift=0
            if xmin < 0:
                xminshift = -xmin
                xmin = 0
            xmax = xmin + box_size - xminshift
            xmaxshift = box_size
            if xmax > self.imgshape2D[0]:
                xmaxshift = self.imgshape2D[0] - xmax
                xmax = self.imgshape2D[0]

            ymin = int(centers[i][1] - max_box/2)
            yminshift=0
            if ymin < 0:
                yminshift = -ymin
                ymin = 0
            ymax = ymin + box_size - yminshift
            ymaxshift = box_size
            if ymax > self.imgshape2D[1]:
                ymaxshift = self.imgshape2D[1] - ymax
                ymax = self.imgshape2D[1]

            movie[ i, xminshift:xmaxshift, yminshift:ymaxshift ] = self.img[ frame, xmin:xmax, ymin:ymax ]
        return movie 


    ### Check individual cell features
    def cell_radius( self, label, frame ):
        """ Approximate the cell radius at given frame """
        area = np.sum( self.seg[frame] == label )
        radius = math.sqrt(area/math.pi)
        return radius
    
    def cell_area( self, label, frame ):
        """ Approximate the cell radius at given frame """
        area = np.sum( self.seg[frame] == label )
        return area 

    def cell_on_border( self, label, frame ):
        """ Check if a given cell is on border of the image """
        bbox = ut.getBBox2D( self.seg[frame], label )
        out = ut.outerBBox2D( bbox, self.imgshape2D, margin=3 )
        return out

    ###### Synchronize tracks whith labels changed
    def add_label( self, labels, frame=None ):
        """ Add a label to the tracks """
        if frame is not None:
            if np.isscalar(labels):
                labels = [labels]
            self.tracking.add_one_frame( labels, frame, refresh=True )
        else:
            if self.verbose > 1:
                print("TODO add label no frame")
    
    def add_one_label_to_track( self, label ):
        """ Add the track data of a given label if missing """
        iframe = 0
        while (iframe < self.nframes) and (label not in self.seg[iframe]):
            iframe = iframe + 1
        while (iframe < self.nframes) and (label in self.seg[iframe]):
            self.tracking.add_one_frame( [label], iframe )
            iframe = iframe + 1

    def update_label(self, label, frame):
        """ Update the given label at given frame """
        self.tracking.update_track_on_frame([label], frame)
    
    def update_changed_labels( self, indmodif, new_labels, old_labels, full=False ):
        """ Check what had been modified, and update tracks from it, looking frame by frame """
        ## check all the old_labels if still present or not
        if self.verbose > 1:
            start_time = time.time()
        frames = np.unique( indmodif[0] ) 
        all_deleted = []
        debug_verb = self.verbose > 2
        if debug_verb:
            print( "Updating labels in frames "+str(frames) )
        for frame in frames:
            keep = indmodif[0] == frame
            ## check old labels if totally removed or not
            deleted = np.setdiff1d( old_labels[keep], self.seg[frame] )
            left = np.setdiff1d( old_labels[keep], deleted )
            if deleted.shape[0] > 0:
                self.tracking.remove_one_frame( deleted, frame, handle_gaps=False, refresh=False )
                if self.forbid_gaps:
                    all_deleted = all_deleted + list(set(deleted) - set(all_deleted))
            if left.shape[0] > 0:
                self.tracking.update_track_on_frame( left, frame )
            ## now check new labels
            nlabels = np.unique( new_labels[keep] )
            if nlabels.shape[0] > 0:
                self.tracking.update_track_on_frame( nlabels, frame )
            if debug_verb:
                print("Labels deleted at frame "+str(frame)+" "+str(deleted)+" or added "+str(nlabels))
    
    def update_added_labels( self, indmodif, new_labels ):
        """ Update tracks of labels that have been fully added """
        if self.verbose > 1:
            start_time = time.time()
        
        ## Deleted labels
        frames = np.unique( indmodif[0] )
        self.tracking.add_tracks_fromindices( indmodif, new_labels )
        if self.forbid_gaps:
            ## Check if some gaps has been created in tracks (remove middle(s) frame(s))
            added = list(set(new_labels))
            if len(added) > 0:
                self.handle_gaps( added, verbose=0 )

        if self.verbose > 1:
            ut.show_duration(start_time, "updated added tracks in ")

    def update_removed_labels( self, indmodif, old_labels ):
        """ Update tracks of labels that have been fully removed """
        if self.verbose > 1:
            start_time = time.time()
        
        ## Deleted labels
        frames = np.unique( indmodif[0] )
        self.tracking.remove_on_frames( np.unique(old_labels), frames )
        if self.forbid_gaps:
            ## Check if some gaps has been created in tracks (remove middle(s) frame(s))
            deleted = list(set(old_labels))
            if len(deleted) > 0:
                self.handle_gaps( deleted, verbose=0 )

        if self.verbose > 1:
            ut.show_duration(start_time, "updated removed tracks in ")

    def update_replaced_labels( self, indmodif, new_labels, old_labels ):
        """ Old_labels were fully replaced by new_labels on some frames, update tracks from it """
        if self.verbose > 1:
            start_time = time.time()
        
        ## Deleted labels
        frames = np.unique( indmodif[0] )
        self.tracking.replace_on_frames( np.unique(old_labels), np.unique(new_labels), frames )
        if self.forbid_gaps:
            ## Check if some gaps has been created in tracks (remove middle(s) frame(s))
            deleted = list(set(old_labels))
            if len(deleted) > 0:
                self.handle_gaps( deleted, verbose=0 )

        if self.verbose > 1:
            ut.show_duration(start_time, "updated replaced tracks in ")

    def handle_gaps(self, track_list, verbose=None):
        """ Check and fix gaps in tracks """
        if verbose is None:
            verbose = self.verbose
        gaped = self.tracking.check_gap( track_list, verbose=verbose )
        if len(gaped) > 0:
            if self.verbose > 0:
                print("Relabelling tracks with gaps")
            self.fix_gaps(gaped)
            
    def fix_gaps(self, gaps):
        """ Fix when some gaps has been created in tracks """
        for gap in gaps:
            gap_frames = self.tracking.gap_frames( gap )
            cur_gap = gap
            for gapy in gap_frames:
                new_value = self.get_free_label()
                self.replace_label( cur_gap, new_value, gapy )
                cur_gap = new_value

    def swap_labels( self, lab, olab, frame ):
        """ Exchange two labels """
        self.tracking.swap_frame_id(lab, olab, frame)

    def swap_tracks( self, lab, olab, start_frame ):
        """ Exchange two tracks """
        ## split the two labels to unused value
        tmp_labels = self.get_free_labels( 2 )
        for i, laby in enumerate([lab, olab]):
            self.replace_label( laby, tmp_labels[i], start_frame )
            
        ## replace the two initial labels, in inversed order
        self.replace_label( tmp_labels[0], olab, start_frame )
        self.replace_label( tmp_labels[1], lab, start_frame )

    def split_track( self, label, frame ):
        """ Split a track at given frame """
        new_label = self.get_free_label()
        self.replace_label( label, new_label, frame )
        if self.verbose > 0:
            ut.show_info("Split track "+str(label)+" from frame "+str(frame))
        return new_label

    def update_changed_labels_img( self, img_before, img_after, added=True, removed=True ):
        """ Update tracks from changes between the two labelled images """
        if self.verbose > 1:
            print("Updating changed labels from images")
        indmodif = np.argwhere( img_before != img_after ).tolist()
        if len(indmodif) <= 0:
            return
        indmodif = tuple( np.array(indmodif).T )
        new_labels = img_after[indmodif]
        old_labels = img_before[indmodif]
        self.update_changed_labels( indmodif, new_labels, old_labels )

    
    def added_labels_oneframe( self, frame, img_before, img_after ):
        """ Update added tracks between the two labelled images at frame """
        ## Look for added labels
        added_labels = np.setdiff1d( img_after, img_before )
        self.tracking.add_one_frame( added_labels, frame, refresh=True )
    
    def removed_labels( self, img_before, img_after, frame=None ):
        """ Update removed tracks between the two labelled images """
        ## Look for added labels
        deleted_labels = np.setdiff1d( img_before, img_after )
        if frame is None:
            self.tracking.remove_tracks( deleted_labels )
        else:
            self.tracking.remove_one_frame( track_id=deleted_labels.tolist(), frame=frame, handle_gaps=self.forbid_gaps )

    def remove_label(self, label, force=False):
        """ Remove a given label if allowed """
        ut.changeLabel(self.seglayer, label, 0)
        self.tracking.remove_tracks(label)
        self.seglayer.refresh()

    def remove_labels(self, labels, force=False):
        """ Remove all allowed labels """
        inds = []
        for lab in labels:
            #if (force) or (not self.locked_label(label)):
            inds = inds + ut.getLabelIndexes(self.seglayer.data, lab, None)
        ut.setNewLabel(self.seglayer, inds, 0)
        self.tracking.remove_tracks(labels)
    
    def keep_labels(self, labels, force=True):
        """ Remove all other labels that are not in labels """
        inds = []
        toremove = list( set(self.tracking.get_track_list()) - set(labels) )
        #for lab in self.tracking.get_track_list():
        #    if lab not in labels:
                #if (force) or (not self.locked_label(label)):
        for lab in toremove:
            inds = inds + ut.getLabelIndexes(self.seglayer.data, lab, None)
        #        toremove.append(lab)
        ut.setNewLabel(self.seglayer, inds, 0)
        self.tracking.remove_tracks(toremove)

    def get_frame_features( self, frame ):
        """ Measure the label properties of given frame """
        return regionprops( self.seg[frame] )

    def updates_after_tracking( self ):
        """ When tracking has been done, update events, others """
        self.inspecting.get_divisions()

    #######################
    ## Classified cells options
    def get_all_groups(self, numeric=False):
        """ Add all groups info """
        if numeric:
            groups = [0]*self.nlabels()
        else:
            groups = ["None"]*self.nlabels()
        for igroup, gr in self.groups.keys():
            indexes = self.tracking.get_track_indexes(self.groups[gr])
            if numeric:
                groups[indexes] = igroup + 1
            else:
                groups[indexes] = gr
        return groups 
    
    def get_groups(self, labels, numeric=False):
        """ Add the group info of the given labels (repeated) """
        if numeric:
            groups = [0]*len(labels)
        else:
            groups = ["Ungrouped"]*len(labels)
        for lab in np.unique(labels):
            gr = self.find_group( lab )
            if gr is None:
                continue
            if numeric:
                gr = self.groups.keys().index() + 1
            indexes = (np.argwhere(labels==lab)).flatten()
            for ind in indexes:
                groups[ind] = gr
        return groups 
    
    def cells_ingroup(self, labels, group):
        """ Put the cell "label" in group group, add it if new group """
        presents = self.has_labels( labels )
        labels = np.array(labels)[ presents ]
        if group not in self.groups.keys():
            self.groups[group] = []
            self.update_group_lists()
        ## add only non present label(s)
        grlabels = self.groups[ group ]
        self.groups[ group ] = list( set( grlabels + labels.tolist()) )

    def group_of_labels( self ):
        """ List the group of each label """
        res = {}
        for group, labels in self.groups.items():
            for label in labels:
                res[label] = group
        return res

    def find_group(self, label):
        """ Find in which group the label is """
        for gr, labs in self.groups.items():
            if label in labs:
                return gr
        return None

    def cell_removegroup(self, label):
        """ Detach the cell from its group """
        if not self.has_label(label):
            if self.verbose > 1:
                print("Cell "+str(label)+" missing")
        group = self.find_group(label)
        if group is not None:
            self.groups[group].remove(label)
            if len(self.groups[group]) <= 0:
                del self.groups[group]
                self.update_group_lists()
    
    def update_group_lists( self ):
        """ Update all the lists depending on the group names """
        if self.outputing is not None:
            self.outputing.update_selection_list()
        if self.editing is not None:
            self.editing.update_group_lists()

    def reset_group( self, group_name ):
        """ Reset/remove a given group """
        if group_name == "All":
            self.reset_groups()
            return
        if group_name in self.groups.keys():
            del self.groups[group_name]
            self.update_group_lists()

    def reset_groups(self):
        """ Remove all group information for all cells """
        self.groups = {} 
        self.update_group_lists()

    def draw_groups(self):
        """ Draw all the epicells colored by their group """
        grouped = np.zeros( self.seg.shape, np.uint8 ) 
        if (self.groups is None) or len(self.groups.keys()) == 0:
            return grouped
        for group, labels in self.groups.items():
            igroup = self.get_group_index(group) + 1
            np.place( grouped, np.isin( self.seg, labels ), igroup )
        return grouped

    def get_group_index(self, group):
        """ Get the index of group in the list of groups """
        if group in list(self.groups.keys()):
            igroup = list(self.groups.keys()).index(group)
            return igroup
        return -1
    
    ######### ROI
    def only_current_roi(self, frame):
        """ Put 0 everywhere outside the current ROI """
        roi_labels = self.editing.get_labels_inside()
        if roi_labels is None:
            return None
        # remove all other labels that are not in roi_labels
        roilab = np.copy(self.seg[frame])
        np.place(roilab, np.isin(roilab, roi_labels, invert=True), 0) 
        return roilab






