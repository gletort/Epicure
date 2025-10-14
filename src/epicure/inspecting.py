import numpy as np
from skimage import filters
from skimage.measure import regionprops
from skimage.morphology import binary_erosion, binary_dilation, disk
from qtpy.QtWidgets import QVBoxLayout, QWidget, QLabel
from napari.utils import progress
import epicure.Utils as ut
import epicure.epiwidgets as wid
import time
from joblib import Parallel, delayed

"""
    EpiCure - Inspection interface
    Handle supects, events detection layer
"""

class Inspecting(QWidget):
    
    def __init__(self, napari_viewer, epic):
        super().__init__()
        self.viewer = napari_viewer
        self.epicure = epic
        self.seglayer = self.viewer.layers["Segmentation"]
        self.border_cells = None    ## list of cells that are on the image border
        self.boundary_cells = None    ## list of cells that are on the boundary (touch the background)
        self.eventlayer_name = "Events"
        self.events = None
        self.win_size = 10
        self.event_class = self.epicure.event_class

        ## Print the current number of events
        self.nevents_print = QLabel("")
        self.update_nevents_display()
        
        self.create_eventlayer()
        layout = QVBoxLayout()
        layout.addWidget( self.nevents_print )
        
        ## Reset or update some events
        update_events_choice = wid.add_button( btn="Reset/Update some events...", btn_func=self.reset_events_choice, descr="Pops up an interface to choose which event(s) to remove or update" )
        layout.addWidget( update_events_choice )
        layout.addWidget( wid.separation() )
        
        
        ## choose events to display
        show_label = wid.label_line( "Show events:" )
        layout.addWidget( show_label )
        show_line = wid.hlayout()
        self.show_class = []
        for i, eclass in enumerate(self.event_class) :
            check = wid.add_check_tolayout( show_line, eclass, True, None, "Show/hide the "+eclass )
            check.stateChanged.connect( lambda state, i=i, eclass=eclass: self.show_hide_events(i, eclass) )
            self.show_class.append( check )
        layout.addLayout( show_line )

        ## Visualisation options
        disp_line, self.event_disp, self.displayevent = wid.checkgroup_help( "Display options", False, "Show/hide event display options panel", "event#visualisation", self.epicure.display_colors, "group3" )
        self.create_displayeventBlock() 
        layout.addLayout( disp_line )
        layout.addWidget(self.displayevent)
        
        layout.addWidget( wid.separation() )
        ## Error suggestions based on cell features
        outlier_line, self.outlier_vis, self.featOutliers = wid.checkgroup_help( "Outlier options", False, "Show/Hide outlier options panel", "event#frame-based-events", self.epicure.display_colors, "group" )
        layout.addLayout( outlier_line )
        self.create_outliersBlock() 
        layout.addWidget(self.featOutliers)
        
        ## Error suggestions based on tracks
        track_line, self.track_vis, self.eventTrack = wid.checkgroup_help( "Track options", True, "Show/hide track options", "event#track-based-events", self.epicure.display_colors, "group2" )
        self.create_tracksBlock() 
        layout.addLayout( track_line )
        layout.addWidget(self.eventTrack)
        
        self.setLayout(layout)
        self.key_binding()

    def key_binding(self):
        """ active key bindings for events options """
        sevents = self.epicure.shortcuts["Events"]
        self.epicure.overtext["events"] = "---- Events editing ---- \n"
        self.epicure.overtext["events"] += ut.print_shortcuts( sevents )
   
        @self.epicure.seglayer.mouse_drag_callbacks.append
        def handle_event(seglayer, event):
            if event.type == "mouse_press":
                ## remove a event
                if ut.shortcut_click_match( sevents["delete"], event ):
                    ind = ut.getCellValue( self.events, event ) 
                    if self.epicure.verbose > 1:
                        print("Removing clicked event, at index "+str(ind))
                    if ind is None:
                        ## click was not on a event
                        return
                    sid = self.events.properties["id"][ind]
                    if sid is not None:
                        self.exonerate_one(ind, remove_division=True)
                        self.update_nevents_display()
                    else:
                        if self.epicure.verbose > 1:
                            print("event with id "+str(sid)+" not found")
                    self.events.refresh()
                    return

                ## zoom on a event
                if ut.shortcut_click_match( sevents["zoom"], event ):
                    ind = ut.getCellValue( self.events, event ) 
                    if "id" not in self.events.properties.keys():
                        print("No event under click")
                        return
                    sid = self.events.properties["id"][ind]
                    if self.epicure.verbose > 1:
                        print("Zoom on event with id "+str(sid)+"")
                    self.zoom_on_event( event.position, sid )
                    return

        @self.epicure.seglayer.bind_key( sevents["next"]["key"], overwrite=True )
        def go_next(seglayer):
            """ Select next suspect event and zoom on it """
            num_event = int(self.event_num.value())
            nevents = self.nb_events()
            if num_event < 0:
                if self.nb_events( only_suspect=True ) == 0:
                    if self.epicure.verbose > 0:
                        print("No more suspect event")
                    return  
                else:
                    self.event_num.setValue(0)
            else:
                self.event_num.setValue( (num_event+1)%nevents )
            self.skip_nonselected_event( nevents, min(nevents,3000) )
            self.go_to_event()       

    def skip_nonselected_event( self, nevents, left ):
        """ Skip next event if not a selected one (show event is not checked) """
        if left < 0:
            return 0
        
        index = int(self.event_num.value())
        nothing_showed = True
        for i, curclass in enumerate(self.show_class):
            if curclass.isChecked():
                nothing_showed = False
                break
        if nothing_showed:
            ## nothing is shown, then go through all events
            self.event_num.setValue( index )
            return index
        
        event_class = self.get_event_class( index )
        ## Show only if show event class is selected
        if self.show_class[ event_class ].isChecked():
            self.event_num.setValue( index )
            return index
        ## else go to next event
        index = (index + 1)%nevents
        self.event_num.setValue( index )
        return self.skip_nonselected_event( nevents, left-1 )
    

    def create_eventlayer(self):
        """ Create a point layer that contains the events """
        features = {}
        pts = []
        self.events = self.viewer.add_points( np.array(pts), properties=features, face_color="red", size = 10, symbol='x', name=self.eventlayer_name, scale=self.viewer.layers["Segmentation"].scale )
        self.event_types = {}
        self.update_nevents_display()
        self.epicure.finish_update()

    def load_events(self, pts, features, event_types):
        """ Load events data from file and reinitialize layer with it"""
        ut.remove_layer(self.viewer, self.eventlayer_name)
        symbols = np.repeat("x", len(pts))
        colors = np.repeat("white", len(pts))
        self.events = self.viewer.add_points( np.array(pts), properties=features, face_color=colors, size = 10, symbol=symbols, name=self.eventlayer_name, scale=self.viewer.layers["Segmentation"].scale )
        self.event_types = event_types

        ## set the display of division events
        self.events.selected_data = {}
        self.select_feature_event( "division" ) 
        self.events.current_symbol = "o"
        self.events.current_face_color = "#0055ffff"
        self.events.selected_data = {}
        self.select_feature_event( "extrusion" ) 
        self.events.current_symbol = "diamond"
        self.events.current_face_color = "red"
        self.events.refresh()
        self.update_nevents_display()
        self.show_hide_events()
        self.epicure.finish_update()

        
    ############### Display event options
    def get_event_types( self ):
        """ Returns the list of possible event types """
        return list( self.event_types.keys() )

    def update_nevents_display( self ):
        """ Update the display of number of event"""
        text = str(self.nb_events(only_suspect=True))+" suspects | " 
        text += str(self.nb_type("division"))+" divisions | "
        text += str(self.nb_type("extrusion"))+" extrusions"  
        self.nevents_print.setText( text )

    def nb_events( self, only_suspect=False ):
        """ Returns current number of events """
        if self.events is None:
            return 0
        if self.events.properties is None:
            return 0
        if "score" not in self.events.properties:
            return 0
        if not only_suspect:
            return len(self.events.properties["score"])
        return ( len(self.events.properties["score"]) - self.nb_type("division") - self.nb_type("extrusion") )

    def get_events_from_type( self, feature ):
        """ Return the list of events of a given type """
        if feature == "suspect":
            sub_features = self.suspect_subtypes()
            evts_id = []
            for feat in sub_features:
                evts_id.extend( eid for eid in self.event_types[ feat ] if eid not in evts_id )
            return list( evts_id )
        if feature in self.event_types:
            return self.event_types[ feature ]
        return []

    def nb_type( self, feature ):
        """ Return nb of event of given type """
        if self.events is None:
            return 0
        if (self.event_types is None) or (feature not in self.event_types):
            return 0
        return len(self.event_types[feature])

    def create_displayeventBlock(self):
        ''' Block interface of displaying event layer options '''
        disp_layout = QVBoxLayout()
        
        ## Color mode
        colorlay, self.color_choice = wid.list_line( "Color by:", "Choose color to display the events", self.color_events )
        self.color_choice.addItem("None")
        self.color_choice.addItem("score")
        self.color_choice.addItem("track-2->1")
        self.color_choice.addItem("track-1-2-*")
        self.color_choice.addItem("track-length")
        self.color_choice.addItem("track-gap")
        self.color_choice.addItem("track-jump")
        self.color_choice.addItem("division")
        self.color_choice.addItem("area")
        self.color_choice.addItem("solidity")
        self.color_choice.addItem("intensity")
        self.color_choice.addItem("tubeness")
        disp_layout.addLayout(colorlay)

        esize = int(self.epicure.reference_size/70+10)
        msize = 100
        if esize > 70:
            msize = 200
        esize = min( esize, 100 )
        sizelay, self.event_size = wid.slider_line( "Point size:", minval=0, maxval=msize, step=1, value=esize, show_value=True, slidefunc=self.display_event_size, descr="Choose the current point size display" ) 
        disp_layout.addLayout(sizelay)

        ### Interface to select a event and zoom on it
        chooselay, self.event_num = wid.ranged_value_line( label="event n°", minval=0, maxval=1000000, step=1, val=0, descr="Choose current event to display/remove" )
        disp_layout.addLayout(chooselay)
        go_event_btn = wid.add_button( "Go to event", self.go_to_event, "Zoom and display current event" )
        disp_layout.addWidget(go_event_btn)
        clear_event_btn = wid.add_button( "Remove current event", self.clear_event, "Delete current event from the list of events" )
        disp_layout.addWidget(clear_event_btn)
        
        ## all features
        self.displayevent.setLayout(disp_layout)
        self.displayevent.setVisible( self.event_disp.isChecked() )
       
    #####
    def reset_event_range(self):
        """ Reset the max num of event """
        nsus = len(self.events.data)-1
        if self.event_num.value() > nsus:
            self.event_num.setValue(0)
        self.event_num.setMaximum(nsus)

    def go_to_event(self):
        """ Zoom on the currently selected event """
        num_event = int(self.event_num.value())
        ## if reached the end of possible events
        if num_event >= self.nb_events():
            num_event = 0
            self.event_num.setValue(0)
        if num_event < 0:
            if self.nb_events() == 0:
                if self.epicure.verbose > 0:
                    print("No more event")
                return  
            else:
                self.event_num.setValue(0)
                num_event = 0      
        pos = self.events.data[num_event]
        event_id = self.events.properties["id"][num_event]
        self.zoom_on_event( pos, event_id )

    def get_event_infos( self, sid ):
        """ Get the properties of the event of given id """
        index = self.index_from_id( sid )
        pos = self.events.data[ index ]
        label = self.events.properties[ "label" ][index]
        return pos, label

    def zoom_on_event( self, event_pos, event_id ):
        """ Zoom on chose event at given position """
        evt_lay = self.viewer.layers[self.eventlayer_name]
        epos = evt_lay.data_to_world(event_pos) 
        #pos = event_pos
        #print(epos)
        self.viewer.camera.center = tuple(epos)
        self.viewer.camera.zoom = 5/self.epicure.epi_metadata["ScaleXY"]
        ut.set_frame( self.viewer, int(epos[0]) )
        crimes = self.get_crimes(event_id)
        if self.epicure.verbose > 0:
            print("Suspected because of: "+str(crimes))

    def color_events(self):
        """ Color points by the selected mode """
        color_mode = self.color_choice.currentText()
        self.events.refresh_colors()
        if color_mode == "None":
            self.events.face_color = "white"
        elif color_mode == "score":
            self.set_colors_from_properties("score")
        else:
            self.set_colors_from_event_type(color_mode)
        self.events.refresh_colors()

    def suspect_subtypes( self ):
        """ Return the list of suspect-related event types """
        features = list( self.event_types.keys() )
        if "division" in features:
            features.remove( "division" )
        if "extrusion" in features:
            features.remove( "extrusion" )
        return features

    def show_subset_event( self, feature, show=True ):
        """ Show/hide a subset (type) of event """
        tmp_size = int(self.event_size.value())
        size = 0.1
        if show:
            size = tmp_size
        ## select the events of corresponding type
        self.events.selected_data = {}
        if not isinstance( feature, list ):
            features = [feature]
        else:
            features = feature
        if "suspect" in features:
            ## take all possible features except non-suspect ones (division, extrusion..)
            features.remove( "suspect" )
            features = features + self.suspect_subtypes()

        posids = []
        for feat in features:
            if feat in self.event_types:
                posid = self.event_types[feat]
                posids = posids + posid
        nfound = len(posids)
        if nfound <= 0:
            return
        for ind, cid in enumerate( self.events.properties["id"] ):
            if cid in posids:
                self.events._size[ind] = size
                nfound = nfound - 1
                ## finished, all updated
                if nfound == 0:
                    break 
        ## reset selection and default size
        self.events.selected_data = {}
        self.events.current_size = tmp_size
        self.events.refresh()

    def select_feature_event( self, feature ):
        """ Add all event of given feature to currently selected data """
        if feature not in self.event_types:
            return
        posid = self.event_types[feature]
        nfound = len(posid)
        for ind, cid in enumerate(self.events.properties["id"]):
            if cid in posid:
                self.events.selected_data.add( ind )
                nfound = nfound - 1
                ## stop if found all of them
                if nfound == 0:
                    return

    def set_colors_from_event_type(self, feature):
        """ Set colors from given event_type feature (eg area, tracking..) """
        if self.event_types.get(feature) is None:
            self.events.face_color="white"
            return
        posid = self.event_types[feature]
        colors = ["white"]*len(self.events.data)
        ## change the color of all the positive events for the chosen feature
        for sid in posid:
            ind = self.index_from_id(sid)
            if ind is not None:
                colors[ind] = (0.8,0.1,0.1)
        self.events.face_color = colors

    def set_colors_from_properties(self, feature):
        """ Set colors from given propertie (eg score, label) """
        ncols = (np.max(self.events.properties[feature]))
        color_cycle = []
        for i in range(ncols):
            color_cycle.append( (0.25+float(i/ncols*0.75), float(i/ncols*0.85), float(i/ncols*0.75)) )
        self.events.face_color_cycle = color_cycle
        self.events.face_color = feature
    
    def update_display(self):
        self.events.refresh()
        self.color_events()

    def get_current_settings(self):
        """ Returns current event widget parameters """
        disp = {}
        disp["Point size"] = int(self.event_size.value())
        disp["Outliers ON"] = self.outlier_vis.isChecked()
        disp["Track ON"] = self.track_vis.isChecked()
        disp["EventDisp ON"] = self.event_disp.isChecked()
        for i, eclass in enumerate(self.event_class):
            disp["Show "+eclass] = self.show_class[i].isChecked()
        disp["Ignore border"] = self.ignore_borders.isChecked()
        disp["Ignore boundaries"] = self.ignore_boundaries.isChecked()
        disp["Flag length"] = self.check_length.isChecked()
        disp["Flag jump"] = self.check_jump.isChecked()
        disp["length"] = self.min_length.text()
        disp["Check size"] = self.check_size.isChecked()
        disp["Check shape"] = self.check_shape.isChecked()
        disp["Get merging"] = self.get_merge.isChecked()
        disp["Get apparitions"] = self.get_apparition.isChecked()
        disp["Get divisions"] = self.get_division.isChecked()
        disp["Get disparitions"] = self.get_disparition.isChecked()
        disp["Get extrusions"] = self.get_extrusions.isChecked()
        disp["Get gaps"] = self.get_gaps.isChecked()
        disp["threshold disparition"] = self.threshold_disparition.text()
        disp["Min gap"] = self.min_gaps.text()
        disp["Min area"] = self.min_area.text()
        disp["Max area"] = self.max_area.text()
        disp["Current frame"] = self.feat_onframe.isChecked()
        return disp

    def apply_settings( self, settings ):
        """ Set the current state (display, widget) from preferences if any """
        for setting, val in settings.items():
            if setting == "Outliers ON":
                self.outlier_vis.setChecked( val ) 
            if setting == "Track ON":
                self.track_vis.setChecked( val ) 
            if setting =="EventDisp ON":
                self.event_disp.setChecked( val ) 
            if setting == "Point size":
                self.event_size.setValue( int(val) )
                #self.display_event_size()
            for i, eclass in enumerate(self.event_class):
                if setting == "Show "+eclass:
                    self.show_class[i].setChecked( val )
            #self.show_hide_events()
            if setting == "Ignore border":
                self.ignore_borders.setChecked( val )
            if setting == "Ignore boundaries":
                self.ignore_boundaries.setChecked( val )
            if setting == "Flag length":
                self.check_length.setChecked( val )
            if setting == "Flag jump":
                self.check_jump.setChecked( val )
            if setting == "length":
                self.min_length.setText( val )
            if setting == "Check size":
                self.check_size.setChecked( val )
            if setting == "Check shape":
                self.check_shape.setChecked( val )
            if setting == "Get merging":
                self.get_merge.setChecked( val )
            if setting == "Get apparitions":
                self.get_apparition.setChecked( val )
            if setting == "Get divisions":
                self.get_division.setChecked( val )
            if setting == "Get disparitions":
                self.get_disparition.setChecked( val )
            if setting == "Get extrusions":
                self.get_extrusions.setChecked( val )
            if setting == "Get gaps":
                self.get_gaps.setChecked( val )    
            if setting == "Threshold disparition":
                self.threshold_disparition.setText( val )
            if setting == "Min gap":
                self.min_gaps.setText( val )
            if setting == "Min area":
                self.min_area.setText( val )
            if setting == "Max area":
                self.max_area.setText( val )
            if setting == "Current frame":
                self.feat_onframe.setChecked( val )
 

    def display_event_size(self):
        """ Change the size of the point display """
        size = int(self.event_size.value())
        self.events.size = size
        self.events.refresh()
        #### Depend on event type, to update

    ############### eventing functions
    def get_crimes(self, sid):
        """ For a given event, get its event_type(s) """
        crimes = []
        for feat in self.event_types.keys():
            if sid in self.event_types.get(feat):
                crimes.append(feat)
        return crimes

    def add_event_type(self, ind, sid, feature):
        """ Add 1 to the event_type score for given feature """
        #print(self.event_types)
        if self.event_types.get(feature) is None:
            self.event_types[feature] = []
        self.event_types[feature].append(sid)
        self.events.properties["score"][ind] = self.events.properties["score"][ind] + 1

    def first_event(self, pos, label, featurename):
        """ Addition of the first event (initialize all) """
        ut.remove_layer(self.viewer, "Events")
        features = {}
        sid = self.new_event_id()
        features["id"] = np.array([sid], dtype="uint16")
        features["label"] = np.array([label], dtype=self.epicure.dtype)
        features["score"] = np.array([0], dtype="uint8")
        pts = [pos]
        self.events = self.viewer.add_points( np.array(pts), properties=features, face_color="score", size = int( self.event_size.value() ), symbol="x", name="Events", scale=self.viewer.layers["Segmentation"].scale )
        self.add_event_type(0, sid, featurename)
        self.events.refresh()
        self.update_nevents_display()

    def add_event(self, pos, label, reason, symb="x", color="white", force=False, refresh=True):
        """ Add a event to the list, evented by a feature """
        if (not force) and (self.ignore_borders.isChecked()) and (self.border_cells is not None):
            tframe = int(pos[0])
            if label in self.border_cells[tframe]:
                return
        
        if (not force) and (self.ignore_boundaries.isChecked()) and (self.boundary_cells is not None):
            tframe = int(pos[0])
            if label in self.boundary_cells[tframe]:
                return

        ## initialise if necessary
        if len(self.events.data) <= 0:
            self.first_event(pos, label, reason)
            return
        
        self.events.selected_data = []
       
       ## look if already evented, then add the charge
        num, sid = self.find_event(pos[0], label)
        if num is not None:
            ## event already in the list. For same crime ?
            if self.event_types.get(reason) is not None:
                if sid not in self.event_types[reason]:
                    self.add_event_type(num, sid, reason)
            else:
                self.add_event_type(num, sid, reason)
        else:
            ## new event, add to the Point layer
            ind = len(self.events.data)
            sid = self.new_event_id()
            self.events.add(pos)
            self.events.properties["label"][ind] = label
            self.events.properties["id"][ind] = sid
            self.events.properties["score"][ind] = 0
            self.add_event_type(ind, sid, reason)

        self.events.symbol.flags.writeable = True
        self.events.current_symbol = symb
        self.events.current_face_color = color
        if refresh:
            self.refresh_events()

    def refresh_events( self ):
        """ Refresh event view and text """
        self.events.refresh()
        self.update_nevents_display()
        self.reset_event_range()
        self.epicure.finish_update()

    def new_event_id(self):
        """ Find the first unused id """
        sid = 0
        if self.events.properties.get("id") is None:
            return 0
        while sid in self.events.properties["id"]:
            sid = sid + 1
        return sid
    
    def reset_events_choice( self ):
        """ Interface to choose event(s) to reset/update """

        class ResetChoice( QWidget ):
            """ Choices of event(s) and update or reset """
            def __init__( self, insp ):
                super().__init__()
                self.insp = insp
                poplayout = wid.vlayout()
        
                ## Handle division events
                update_div_btn = wid.add_button( btn="Update divisions from graph", btn_func=self.insp.get_divisions, descr="Update the list of division events from the track graph" )
                poplayout.addWidget(update_div_btn)
                poplayout.addWidget( wid.separation() )

                ### Reset: delete all events
                reset_color = self.insp.epicure.get_resetbtn_color()
                reset_event_btn = wid.add_button( btn="Reset all events", btn_func=self.insp.reset_all_events, descr="Delete all current events", color=reset_color )
                poplayout.addWidget( reset_event_btn )

                ## Reset: specific events
                reset_line = wid.hlayout()
                for i, eclass in enumerate( self.insp.event_class ):
                    go_btn = wid.add_button( btn="Reset "+eclass, btn_func=None, descr="Reset "+eclass+" events only", color=reset_color )
                    go_btn.clicked.connect( lambda i=i, eclass=eclass: self.insp.reset_event_type( eclass, frame=None ) )
                    reset_line.addWidget( go_btn )
                poplayout.addLayout( reset_line )

                poplayout.addWidget( wid.separation() )
                ## Remove events on border
                bord_lab = wid.label_line( "Remove if on BORDER:")
                bord_line = wid.hlayout()
                for i, eclass in enumerate( self.insp.event_class ):
                    if eclass != "suspect":
                        go_btn = wid.add_button( btn=""+eclass, btn_func=None, descr="Remove "+eclass+" events if they are on border" ) 
                        go_btn.clicked.connect( lambda i=i, eclass=eclass: self.insp.remove_event_border( eclass ) )
                        bord_line.addWidget( go_btn )
                poplayout.addWidget( bord_lab )
                poplayout.addLayout( bord_line )
                
                ## Remove events on boundaries
                bound_lab = wid.label_line( "Remove if on BOUNDARY:")
                bound_line = wid.hlayout()
                for i, eclass in enumerate( self.insp.event_class ):
                    if eclass != "suspect":
                        go_btn = wid.add_button( btn=""+eclass, btn_func=None, descr="Remove "+eclass+" events if they are on boundary" )
                        go_btn.clicked.connect( lambda i=i, eclass=eclass: self.insp.remove_event_boundary( eclass ) )
                        bound_line.addWidget( go_btn )
                poplayout.addWidget( bound_lab )
                poplayout.addLayout( bound_line )
                poplayout.addWidget( wid.separation() )


                self.setLayout( poplayout )
    
            #def close( self ):
            #    """ Close the pop-up window """
            #    self.hide()
        rc = ResetChoice( self )
        rc.show()
    

    def remove_event_border( self, evt_type ):
        """ Remove events of given types if they are on border cells """
        if self.event_types.get( evt_type ) is None:
            return
        
        pbar = ut.start_progress( self.viewer, total=self.epicure.nframes+1, descr="Detecting border cells" )
        ## get/update the list of border cells
        self.get_border_cells() 

        ## check all event_type events if they are on border cells
        idlist = self.event_types[ evt_type ].copy()
        for sid in idlist:
            ind = self.index_from_id(sid)
            if ind is not None:
                ## get the event cell label and frame
                lab = self.events.properties["label"][ind]
                frame = self.events.data[ind][0]
                if evt_type == "division":
                    frame = frame - 1
                if frame is not None:
                    if lab in self.border_cells[ frame ]:
                        ## event is on border, remove it
                        self.event_types[ evt_type ].remove( sid )
                        self.decrease_score( ind )

        ## update displays
        ut.close_progress( self.viewer, pbar )
        self.events.refresh()
        self.update_nevents_display()
    
    def remove_event_boundary( self, evt_type ):
        """ Remove events of given types if they are on boundary cells """
        if self.event_types.get( evt_type ) is None:
            return

        pbar = ut.start_progress( self.viewer, total=self.epicure.nframes+1, descr="Detecting boundary cells" ) 
        ## get/update the list of border cells
        self.get_boundaries_cells( pbar ) 

        ## check all event_type events if they are on border cells
        idlist = self.event_types[ evt_type ].copy()
        for sid in idlist:
            ind = self.index_from_id(sid)
            if ind is not None:
                ## get the event cell label and frame
                lab = self.events.properties["label"][ind]
                frame = self.events.data[ind][0]
                if evt_type == "division":
                    frame = frame - 1
                if frame is not None:
                    if lab in self.boundary_cells[ frame ]:
                        ## event is on border, remove it
                        self.event_types[ evt_type ].remove( sid )
                        self.decrease_score( ind )

        ## update displays
        ut.close_progress( self.viewer, pbar )
        self.events.refresh()
        self.update_nevents_display()

    def reset_all_events(self):
        """ Remove all event_types """
        features = {}
        pts = []
        ut.remove_layer(self.viewer, "Events")
        self.events = self.viewer.add_points( np.array(pts), properties=features, face_color="red", size = 10, symbol='x', name="Events", scale=self.viewer.layers["Segmentation"].scale )
        self.event_types = {}
        self.update_nevents_display()
        #self.update_nevents_display()
        self.epicure.finish_update()

    def reset_event_type(self, feature, frame ):
        """ Remove all event_types of given feature, for current frame or all if frame is None """
        if self.event_types.get(feature) is None:
            return
        idlist = self.event_types[feature].copy()
        for sid in idlist:
            ind = self.index_from_id(sid)
            if ind is not None:
                if frame is not None:
                    if int(self.events.data[ind][0]) == frame:
                        self.event_types[feature].remove(sid)
                        self.decrease_score(ind)
                else:
                    self.event_types[feature].remove(sid)
                    self.decrease_score(ind)
        self.events.refresh()
        self.update_nevents_display()

    def remove_event_types(self, sid):
        """ Remove all event_types of given event id """
        for listval in self.event_types.values():
            if sid in listval:
                listval.remove(sid)

    def decrease_score(self, ind):
        """ Decrease by one score of event at index ind. Delete it if reach 0"""
        self.events.properties["score"][ind] = self.events.properties["score"][ind] - 1
        if self.events.properties["score"][ind] == 0:
            self.exonerate_one( ind, remove_division=False )
            self.update_nevents_display()

    def index_from_id(self, sid):
        """ From event id, find the corresponding index in the properties array """
        for ind, cid in enumerate(self.events.properties["id"]):
            if cid == sid:
                return ind
        return None

    def id_from_index( self, ind ):
        """ From event index, returns it id """
        return self.events.properties["id"][ind]

    def find_event(self, frame, label):
        """ Find if there is already a event at given frame and label """
        events = self.events.data
        events_lab = self.events.properties["label"]
        for i, lab in enumerate(events_lab):
            if lab == label:
                if events[i][0] == frame:
                    return i, self.events.properties["id"][i]
        return None, None

    def init_suggestion(self):
        """ Initialize the layer that will contains propostion of tracks/segmentations """
        suggestion = np.zeros(self.seglayer.data.shape, dtype="uint16")
        self.suggestion = self.viewer.add_labels(suggestion, blending="additive", name="Suggestion")
        
        @self.seglayer.mouse_drag_callbacks.append
        def click(layer, event):
            if event.type == "mouse_press":
                if 'Alt' in event.modifiers:
                    if event.button == 1:
                        pos = event.position
                        # alt+left click accept suggestion under the mouse pointer (in all frames)
                        self.accept_suggestion(pos)
    
    def accept_suggestion(self, pos):
        """ Accept the modifications of the label at position pos (all the label) """
        seglayer = self.viewer.layers["Segmentation"]
        label = self.suggestion.data[tuple(map(int, pos))]
        found = self.suggestion.data==label
        self.exonerate( found, seglayer ) 
        indices = np.argwhere( found )
        ut.setNewLabel( seglayer, indices, label, add_frame=None )
        self.suggestion.data[self.suggestion.data==label] = 0
        self.suggestion.refresh()
        self.update_nevents_display()
    
    def remove_one_event( self, event_id ):
        """ Remove the given event from its id """
        if self.events is None:
            return
        ind = self.index_from_id(event_id)
        if ind is not None:
            self.exonerate_one( ind )
            self.update_nevents_display()
            self.events.refresh()

    def exonerate_one(self, ind, remove_division=True):
        """ Remove one event at index ind """
        self.events.selected_data = [ind]
        sid = self.events.properties["id"][ind]
        if (remove_division) and ("division" in self.event_types.keys()) and (ind in self.event_types["division"]):
            self.epicure.tracking.remove_division( self.events.properties["label"][ind] )
        self.events.remove_selected()
        self.remove_event_types(sid)
        
    def clear_event(self):
        """ Remove the current event """
        num_event = int(self.event_num.value())
        self.exonerate_one( num_event, remove_division=True )
        self.update_nevents_display()

    def exonerate_from_event(self, event):
        """ Remove all events in the corresponding cell of position """
        label = ut.getCellValue( self.seglayer, event )
        if len(self.events.data) > 0:
            for ind, lab in enumerate(self.events.properties["label"]):
                if lab == label:
                    if self.events.data[ind][0] == event.position[0]:      
                        self.exonerate_one(ind, remove_division=True) 
        self.update_nevents_display()

    def exonerate(self, indices, seglayer):
        """ Remove events that have been corrected/cleared """
        seglabels = np.unique(seglayer.data[indices])
        selected = []
        if self.events.properties.get("label") is None:
            return
        for ind, lab in enumerate(self.events.properties["label"]):
            if lab in seglabels:
                ## label to remove from event list
                selected.append(ind)
        if len(selected) > 0:
            self.events.selected_data = selected
            self.events.remove_selected()
            self.update_nevents_display()
                

    #######################################"
    ## Outliers suggestion functions
    def show_outlierBlock(self):
        self.featOutliers.setVisible( self.outlier_vis.isChecked() )

    def create_outliersBlock(self):
        ''' Block interface of functions for error suggestions based on cell features '''
        feat_layout = QVBoxLayout()
        
        self.feat_onframe = wid.add_check( check="Only current frame", checked=True, check_func=None, descr="Search for outliers only in current frame" )
        feat_layout.addWidget(self.feat_onframe)
        
        ## area widget
        tarea_layout, self.min_area, self.max_area = wid.min_button_max( btn="< Area (pix^2) <", btn_func=self.event_area_threshold, min_val="0", max_val="2000", descr="Look for cell which size is outside the given area range" )
        feat_layout.addLayout( tarea_layout )
        
        ## solid widget
        feat_solid_line, self.fsolid_out = wid.button_parameter_line( btn="Solidity outliers", btn_func=self.event_solidity, value="3.0", descr_btn="Search for outliers in solidity value", descr_value="Inter-quartiles range factor to consider outlier" )
        feat_layout.addLayout( feat_solid_line )
        
        ## intensity widget
        feat_inten_line, self.fintensity_out = wid.button_parameter_line( btn="Intensity cytoplasm/junction", btn_func=self.event_intensity, value="1.0", descr_btn="Search for outliers in intensity ratio", descr_value="Ratio of intensity above which the cell looks suspect" )
        feat_layout.addLayout( feat_inten_line )
        
        ## tubeness widget
        feat_tub_line, self.ftub_out = wid.button_parameter_line( btn="Tubeness cytoplasm/junction", btn_func=self.event_tubeness, value="1.0", descr_btn="Search for outliers in tubeness ratio", descr_value="Ratio of tubeness above which the cell looks suspect" )
        feat_layout.addLayout( feat_tub_line )
        
        ## all features
        self.featOutliers.setLayout(feat_layout)
        self.featOutliers.setVisible( self.outlier_vis.isChecked() )
    
    def event_feature(self, featname, funcname ):
        """ event in one frame or all frames the given feature """
        onframe = self.feat_onframe.isChecked()
        if onframe:
            tframe = ut.current_frame(self.viewer)
            self.reset_event_type(featname, tframe)
            funcname(tframe)
        else:
            self.reset_event_type(featname, None)
            for frame in range(self.seglayer.data.shape[0]):
                funcname(frame)
        self.update_display()
        ut.set_active_layer( self.viewer, "Segmentation" )
    
    def inspect_outliers(self, tab, props, tuk, frame, feature):
        q1 = np.quantile(tab, 0.25)
        q3 = np.quantile(tab, 0.75)
        qtuk = tuk * (q3-q1)
        for sign in [1, -1]:
            #thresh = np.mean(tab) + sign * np.std(tab)*tuk
            if sign > 0:
                thresh = q3 + qtuk
            else:
                thresh = q1 - qtuk
            for i in np.where((tab-thresh)*sign>0)[0]:
                position = ut.prop_to_pos( props[i], frame )
                self.add_event( position, props[i].label, feature )
    
    def event_area_threshold(self):
        """ Look for cell's area below/above a threshold """
        self.event_feature( "area", self.event_area_threshold_oneframe )

    def event_area_threshold_oneframe( self, tframe ):
        """ Check if area is above/below given threshold """
        minarea = int(self.min_area.text())
        maxarea = int(self.max_area.text())
        frame_props = self.epicure.get_frame_features( tframe )
        for prop in frame_props:
            if (prop.area < minarea) or (prop.area > maxarea):
                position = ut.prop_to_pos( prop, tframe )
                self.add_event( position, prop.label, "area" )


    def event_area(self, state):
        """ Look for outliers in term of cell area """
        self.event_feature( "area", self.event_area_oneframe )
    
    def event_area_oneframe(self, frame):
        seglayer = self.seglayer.data[frame]
        props = regionprops(seglayer)
        ncell = len(props)
        areas = np.zeros((ncell,1), dtype="float")
        for i, prop in enumerate(props):
            if prop.label > 0:
                areas[i] = prop.area
        tuk = self.farea_out.value()
        self.inspect_outliers(areas, props, tuk, frame, "area")

    def event_solidity(self, state):
        """ Look for outliers in term ofz cell solidity """
        self.event_feature( "solidity", self.event_solidity_oneframe )

    def event_solidity_oneframe(self, frame):
        seglayer = self.seglayer.data[frame]
        props = regionprops(seglayer)
        ncell = len(props)
        sols = np.zeros((ncell,1), dtype="float")
        for i, prop in enumerate(props):
            if prop.label > 0:
                sols[i] = prop.solidity
        tuk = float(self.fsolid_out.text())
        self.inspect_outliers(sols, props, tuk, frame, "solidity")
    
    def event_intensity(self, state):
        """ Look for abnormal intensity inside/periph ratio """
        self.event_feature( "intensity", self.event_intensity_oneframe )
    
    def event_intensity_oneframe(self, frame):
        seglayer = self.seglayer.data[frame]
        intlayer = self.viewer.layers["Movie"].data[frame] 
        props = regionprops(seglayer)
        for i, prop in enumerate(props):
            if prop.label > 0:
                self.test_intensity( intlayer, prop, frame )
    
    def test_intensity(self, inten, prop, frame):
        """ Test if intensity inside is much smaller than at periphery """
        bbox = prop.bbox
        intbb = inten[bbox[0]:bbox[2], bbox[1]:bbox[3]]
        footprint = disk(radius=self.epicure.thickness)
        inside = binary_erosion(prop.image, footprint)
        ininten = np.mean(intbb*inside)
        dil_img = binary_dilation(prop.image, footprint)
        periph = dil_img^inside
        periphint = np.mean(intbb*periph)
        if (periphint<=0) or (ininten/periphint > float(self.fintensity_out.text())):
            position = ( frame, int(prop.centroid[0]), int(prop.centroid[1]) )
            self.add_event( position, prop.label, "intensity" )
    
    def event_tubeness(self, state):
        """ Look for abnormal tubeness inside vs periph """
        self.event_feature( "tubeness", self.event_tubeness_oneframe )
    
    def event_tubeness_oneframe(self, frame):
        seglayer = self.seglayer.data[frame]
        mov = self.viewer.layers["Movie"].data[frame]
        sated = np.copy(mov)
        sated = filters.sato(sated, black_ridges=False)
        props = regionprops(seglayer)
        for i, prop in enumerate(props):
            if prop.label > 0:
                self.test_tubeness( sated, prop, frame )

    def test_tubeness(self, sated, prop, frame):
        """ Test if tubeness inside is much smaller than tubeness on periph """
        bbox = prop.bbox
        satbb = sated[bbox[0]:bbox[2], bbox[1]:bbox[3]]
        footprint = disk(radius=self.epicure.thickness)
        inside = binary_erosion(prop.image, footprint)
        intub = np.mean(satbb*inside)
        periph = prop.image^inside
        periphtub = np.mean(satbb*periph)
        if periphtub <= 0:
            position = ( frame, int(prop.centroid[0]), int(prop.centroid[1]) )
            self.add_event( position, prop.label, "tubeness" )
        else:
            if intub/periphtub > float(self.ftub_out.text()):
                position = ( frame, int(prop.centroid[0]), int(prop.centroid[1]) )
                self.add_event( position, prop.label, "tubeness" )


############# event based on track

    def show_tracksBlock(self):
        self.eventTrack.setVisible( self.track_vis.isChecked() )

    def create_tracksBlock(self):
        ''' Block interface of functions for error suggestions based on tracks '''
        track_layout = QVBoxLayout()
        
        hign = wid.hlayout()
        ignore_label = wid.label_line( "Ignore cells on:")
        hign.addWidget( ignore_label )
        vign = wid.vlayout()
        self.ignore_borders = wid.add_check( "border (of image)", False, None, "When adding suspect, don't add it if the cell is touching the border of the image" )
        vign.addWidget(self.ignore_borders)
        
        self.ignore_boundaries = wid.add_check( "tissue boundaries", False, None, "When adding suspect, don't add it if the cell is on the tissu boundaries (no neighbor in one side)" )
        vign.addWidget(self.ignore_boundaries)
        hign.addLayout( vign )
        track_layout.addLayout( hign )
        
        ## Look for merging tracks
        self.get_merge = wid.add_check( "Flag track merging", True, None, "Add a suspect if two track merge in one" )
        track_layout.addWidget(self.get_merge)
        
        ## Look for sudden appearance of tracks
        self.get_apparition = wid.add_check( "Flag track apparition", True, None, "Add a suspect if a track appears in the middle of the movie (not on border)" )
        track_layout.addWidget(self.get_apparition)
        
        self.get_division = wid.add_check( "Get divisions", False, None, "Add a division if two touching track appears while a potential parent track disappear" )
        track_layout.addWidget(self.get_division)
       
        ## Look for sudden disappearance of tracks
        dsp_layout = wid.hlayout()
        self.get_disparition = wid.add_check( check="Flag track disparition", checked=True, check_func=None, descr="Add a suspect if a track disappears (not last frame, not border)" )
        disp_line, self.threshold_disparition = wid.value_line( label="cell area threshold", default_value="200", descr="Flag cell if cell area is above threshold" )
        self.get_extrusions = wid.add_check( "Get extrusions", True, None, "Add extrusions events when a track is disappearing normally (below cell area threshold)" )
        vlay = wid.vlayout()
        vlay.addWidget( self.get_disparition )
        vlay.addWidget( self.get_extrusions )
        dsp_layout.addLayout( vlay )
        dsp_layout.addLayout( disp_line )
        track_layout.addLayout( dsp_layout )

        ## Look for temporal gaps in tracks
        gap_line, self.get_gaps, self.min_gaps = wid.check_value( check="Flag track gaps", checkfunc=None, checked=True, value="1", descr="Add a suspect if a track has gaps longer than threshold (in nb of frames)", label="if gap above" )
        track_layout.addLayout( gap_line )

        ## track length event_types
        ilengthlay, self.check_length, self.min_length = wid.check_value( check="Flag tracks smaller than", checkfunc=None, checked=True, value="1", descr="Add a suspect event for each track smaller than chosen value (in number of frames)" )
        track_layout.addLayout(ilengthlay)
        
        ## track sudden jump in position
        ijumplay, self.check_jump, self.jump_factor = wid.check_value( check="Flag jump in track position", checkfunc=None, checked=True, value="3.0", descr="Add a suspect event for when the position of cell centroid moves suddenly a lot compared to the rest of the track" )
        track_layout.addLayout(ijumplay)
        
        ## Variability in feature event_type
        sizevar_line, self.check_size, self.size_variability = wid.check_value( check="Size variation", checkfunc=None, checked=False, value="3", descr="Add a suspect if the size of the cell varies suddenly in the track" )
        track_layout.addLayout( sizevar_line )
        shapevar_line, self.check_shape, self.shape_variability = wid.check_value( check="Shape variation", checkfunc=None, checked=False, value="3.0", descr="Add a suspect if the shape of the cell varies suddenly in the track" )
        track_layout.addLayout( shapevar_line )

        ## merge/split combinaisons 
        track_btn = wid.add_button( btn="Inspect track", btn_func=self.inspect_tracks, descr="Start track analysis to look for suspects based on selected features" )
        track_layout.addWidget(track_btn)
        
        ## all features
        self.eventTrack.setLayout(track_layout)
        self.eventTrack.setVisible( self.track_vis.isChecked() )

    def reset_tracking_event(self):
        """ Remove events from tracking """
        self.reset_event_type("track-1-2-*", None)
        self.reset_event_type("track-2->1", None)
        self.reset_event_type("track-length", None)
        self.reset_event_type("track-jump", None)
        self.reset_event_type("track-size", None)
        self.reset_event_type("track-shape", None)
        self.reset_event_type("track-apparition", None)
        self.reset_event_type("track-disparition", None)
        self.reset_event_type("track-gap", None)
        if self.get_extrusions.isChecked():
            self.reset_event_type("extrusion", None)
        self.reset_event_range()

    def track_length(self):
        """ Find all cells that are only in one frame """
        max_len = int(self.min_length.text())
        labels, lengths, positions = self.epicure.tracking.get_small_tracks( max_len )
        ## remove track from first and last frame
        first_tracks = self.epicure.tracking.get_tracks_on_frame( 0 )
        last_tracks = self.epicure.tracking.get_tracks_on_frame( self.epicure.nframes-1 ) 
        for label, nframe, pos in zip(labels, lengths, positions):
            if label in first_tracks or label in last_tracks:
                ## present in the first or last track, don't check it
                continue
            if self.epicure.verbose > 2:
                print("event track length "+str(nframe)+": "+str(label)+" frame "+str(pos[0]) )
            self.add_event(pos, label, "track-length", refresh=False)
        self.refresh_events()
    
    def inspect_tracks( self, subprogress=True ):
        """ Look for suspicious tracks """
        ut.set_visibility( self.viewer, "Events", True )
        progress_bar = ut.start_progress( self.viewer, total=10 )
        if subprogress:
            ## show subprogress bars in sub functions (doesn't work on notebook without interface)
            pb = progress_bar
        else:
            pb= None
        progress_bar.update(0)
        self.reset_tracking_event()
        progress_bar.update(1)
        if self.ignore_borders.isChecked() or self.ignore_boundaries.isChecked():
            progress_bar.set_description("Identifying border and/or boundaries cells")
            self.get_outside_cells()
        progress_bar.update(2)
        tracks = self.epicure.tracking.get_track_list()
        if self.check_length.isChecked():
            progress_bar.set_description("Identifying too small tracks")
            self.track_length()
        progress_bar.update(3)
        if self.get_merge.isChecked():
            progress_bar.set_description("Inspect tracks 2->1")
            self.track_21()
        progress_bar.update(4)
        if (self.check_size.isChecked()) or self.check_shape.isChecked():
            progress_bar.set_description("Inspect track features")
            self.track_features()
        progress_bar.update(5)
        if self.get_apparition.isChecked() or self.get_division.isChecked():
            progress_bar.set_description("Check new track apparition and/or division")
            self.track_apparition( tracks )
        progress_bar.update(6)
        if self.get_disparition.isChecked() or self.get_extrusions.isChecked():
            progress_bar.set_description("Check track disparition and/or extrusion")
            self.track_disparition( tracks, pb )
        progress_bar.update(7)
        if self.get_gaps.isChecked():
            progress_bar.set_description("Check temporal gaps in tracks")
            self.track_gaps( tracks, pb )
        progress_bar.update(8)
        if self.check_jump.isChecked():
            progress_bar.set_description("Check position jump in tracks")
            self.track_position_jump( tracks, pb )
        progress_bar.update(9)
        ut.close_progress( self.viewer, progress_bar )
        ut.set_active_layer( self.viewer, "Segmentation" )

    def track_apparition( self, tracks ):
        """ Check if some track appears suddenly (in the middle of the movie and not by division) """
        start_time = time.time()
        ## remove track on first frame
        ctracks = list( set(tracks) - set( self.epicure.tracking.get_tracks_on_frame( 0 ) ) )
        graph = self.epicure.tracking.graph
        do_divisions = self.get_division.isChecked()
        do_apparition = self.get_apparition.isChecked()
        apparitions = {}
        for i, track_id in enumerate( ctracks) :
            fframe = self.epicure.tracking.get_first_frame( track_id )
            ## If on the border, ignore
            #outside = self.epicure.cell_on_border( track_id, fframe )
            #if outside:
            #    continue
            ## Not on border, check if potential division
            if (graph is not None) and (track_id in graph.keys()):
                continue
            ## event apparition
            if (not do_divisions) and do_apparition:
                self.add_apparition( fframe, track_id )
            else:
                if fframe not in apparitions:
                    apparitions[fframe] = [track_id]
                else:
                    apparitions[fframe].append(track_id)
        if do_divisions:
            self.apparition_or_division( apparitions, do_apparition )
        self.refresh_events()
        if self.epicure.verbose > 1:
            ut.show_duration( start_time, "Tracks apparition took " )

    def add_apparition( self, frame, trackid ):
        """ Add a suspect apparition to events """
        posxy = self.epicure.tracking.get_position( trackid, frame )
        if posxy is not None:
            pos = [ frame, posxy[0], posxy[1] ]
            if self.epicure.verbose > 2:
                print("Appearing track: "+str(trackid)+" at frame "+str(frame) )
            self.add_event(pos, trackid, "track-apparition", refresh=False)

    def apparition_or_division( self, apevents, do_apparition ):
        """ Check if detected events are apparitions or divisions """
        for frame, tracks in apevents.items():
            if len(tracks) == 1:
                ## only one event, apparition
                if do_apparition:
                    self.add_apparition( frame, tracks[0] )
            else:
                # look for potential neighbors for each apparition at this frame
                ind = 0
                while ind < len(tracks):
                    ctrack = tracks[ind]
                    ## already treated
                    if ctrack < 0:
                        ind = ind + 1
                        continue
                    dind = ind + 1
                    found = False
                    while dind < len(tracks):
                        ## skip if already done
                        if tracks[dind] < 0:
                            dind = dind + 1
                            continue
                        ## check if labels are touching at the appearing frame
                        bbox, merged = ut.getBBox2DMerge( self.epicure.seg[frame], ctrack, tracks[dind] )
                        bbox = ut.extendBBox2D( bbox, 1.05, self.epicure.imgshape2D )
                        segt_crop = ut.cropBBox2D( self.epicure.seg[frame], bbox )
                        touched = ut.checkTouchingLabels( segt_crop, ctrack, tracks[dind] )
                        if touched: 
                            ## found neighbor, potential division
                            found = True
                            if self.epicure.editing.add_division( ctrack, tracks[dind], frame ):
                                ## division added successfully
                                tracks[dind] = -1 ## track done
                                break
                            else:
                                ## failed to add a division, so mark it as apparition
                                if do_apparition:
                                    self.add_apparition( frame, ctrack )
                            break
                        else:
                            dind = dind + 1
                    # no neighbor found, so mark this as an apparition
                    if (not found) and do_apparition:
                        if ctrack > 0:
                            self.add_apparition( frame, ctrack )
                    ind = ind + 1
        #print(self.epicure.tracking.graph)
        

                
    def track_disparition( self, tracks, progress_bar ):
        """ Check if some track disappears suddenly (in the middle of the movie and not by division) """
        start_time = ut.start_time()
        ## Track disappears in the movie, not last frame
        ctracks = list( set(tracks) - set( self.epicure.tracking.get_tracks_on_frame( self.epicure.nframes-1 ) ) )
        threshold_area = float(self.threshold_disparition.text())
        if progress_bar is not None:
            sub_bar = progress( total = len( ctracks ), desc="Check non last frame tracks", nest_under = progress_bar )
        for i, track_id in enumerate( ctracks ):
            if progress_bar is not None:
                sub_bar.update( i )
            lframe = self.epicure.tracking.get_last_frame( track_id )
            ## If on the border, ignore
            #outside = self.epicure.cell_on_border( track_id, lframe )
            #if outside:
            #    continue
            ## Not on border, check if potential division
            if self.epicure.tracking.is_single_parent( track_id ):
                continue
       
            ## check if the cell area is below the threshold, then considered as ok (likely extrusion)
            if (threshold_area > 0):
                cell_area = self.epicure.cell_area( track_id, lframe )
                if cell_area < threshold_area:
                    if self.get_extrusions.isChecked():
                        fframe = self.epicure.tracking.get_first_frame( track_id )
                        if fframe == lframe:
                            ## track is only one frame, don't flag as extrusion
                            continue
                        ## event extrusion
                        posxy = self.epicure.tracking.get_position( track_id, lframe )
                        if posxy is not None:
                            pos = [ lframe, posxy[0], posxy[1] ]
                        if self.epicure.verbose > 2:
                            print("Add extrusion: "+str(track_id)+" at frame "+str(lframe) )
                        self.add_event( pos, track_id, "extrusion", symb="diamond", color="red", refresh=False )
                    continue
                if not self.get_disparition.isChecked():
                    continue

            ## event disparition
            posxy = self.epicure.tracking.get_position( track_id, lframe )
            if posxy is not None:
                pos = [ lframe, posxy[0], posxy[1] ]
                if self.epicure.verbose > 2:
                    print("Disappearing track: "+str(track_id)+" at frame "+str(lframe) )
                self.add_event(pos, track_id, "track-disparition", refresh=False)
        if progress_bar is not None:
            sub_bar.close()
        self.refresh_events()
        if self.epicure.verbose > 1:
            ut.show_duration( start_time, "Tracks disparition took " )


    def track_gaps( self, tracks, progress_bar ):
        """ Check if some track have temporal gaps above a given threshold of frames """
        start_time = time.time()
        ## Track disappears in the movie, not last frame
        ctracks = tracks
        min_gaps = int(self.min_gaps.text())
        if progress_bar is not None:
            sub_bar = progress( total = len( ctracks ), desc="Check gaps in tracks", nest_under = progress_bar )
        gaped = self.epicure.tracking.check_gap( ctracks, verbose=0 )
        if len( gaped ) > 0:
            for i, track_id in enumerate( gaped ):
                if progress_bar is not None:
                    sub_bar.update( i )
                gap_frames = self.epicure.tracking.gap_frames( track_id )
                if len( gap_frames ) > 0:
                    gaps = ut.get_consecutives( gap_frames )
                    if self.epicure.verbose > 1:
                        print("Found gaps in track "+str(track_id)+" : "+str(gaps) )
                    for gapy in gaps:
                        if (gapy[1]-gapy[0]+1) >= min_gaps:
                            ## flag gap as it's long enough
                            poszxy = self.epicure.tracking.get_middle_position( track_id, gapy[0]-1, gapy[1]+1 )
                            if poszxy is not None:
                                if self.epicure.verbose > 2:
                                    print("Gap in track: "+str(track_id)+" at frame "+str(poszxy[0]) )
                                self.add_event(poszxy, track_id, "track-gap", refresh=False)
        if progress_bar is not None:
            sub_bar.close()
        self.refresh_events()
        if self.epicure.verbose > 1:
            ut.show_duration( start_time, "Tracks gaps took " )

    def track_21(self):
        """ Look for event track: 2->1 """
        if self.epicure.tracking.tracklayer is None:
            ut.show_error("No tracking done yet!")
            return

        graph = self.epicure.tracking.graph
        if graph is not None:
            for child, parent in graph.items():
                ## 2->1, merge, event
                if isinstance(parent, list) and len(parent) == 2:
                    onetwoone = False
                    ## was it only one before ?
                    if (parent[0] in graph.keys()) and (parent[1] in graph.keys()):
                        if graph[parent[0]][0] == graph[parent[1]][0]:
                            pos = self.epicure.tracking.get_mean_position([parent[0], parent[1]])
                            if pos is not None:
                                if self.epicure.verbose > 1:
                                    print("event 1->2->1 track: "+str(graph[parent[0]][0])+"-"+str(parent)+"-"+str(child)+" frame "+str(pos[0]) )
                                self.add_event(pos, parent[0], "track-1-2-*", refresh=False)
                                onetwoone = True
                
                    if not onetwoone:
                        pos = self.epicure.tracking.get_mean_position(child, only_first=True)     
                        if pos is not None:
                            if self.epicure.verbose > 2:
                                print("event 2->1 track: "+str(parent)+"-"+str(child)+" frame "+str(int(pos[0])) )
                            self.add_event(pos, parent[0], "track-2->1", refresh=False)
                        else:
                            if self.epicure.verbose > 1:
                                print("Something weird, "+str(child)+" mean position")

        self.refresh_events()

    def get_outside_cells( self ):
        """ Get list of cells on tissu boundaries and/or on border of the movie """
        self.boundary_cells = dict()
        self.border_cells = dict()
        check_border = self.ignore_borders.isChecked()
        check_bound = self.ignore_boundaries.isChecked()
        def get_cells( img ):
            """ For parallel processing, task of one thread (one frame) """
            bounds, borders = None, None
            if check_bound:
                bounds = ut.get_boundary_cells( img )
            if check_border:
                borders = ut.get_border_cells( img )
            return (bounds, borders)
        
        if self.epicure.process_parallel:
            # Process in parallel, putting all in temp list and then filling the local dict
            cell_list = Parallel(n_jobs=self.epicure.nparallel)(
                delayed(get_cells)(frame) for frame in self.epicure.seg
            )
            for tframe in range(self.epicure.nframes):
                if check_bound:
                    self.boundary_cells[tframe] = cell_list[tframe][0]
                if check_border:
                    self.border_cells[tframe] = cell_list[tframe][1]
        else:
            ## simple sequential processing
            for tframe in range(self.epicure.nframes):
                img = self.epicure.seg[tframe]
                if check_bound:
                    self.boundary_cells[tframe] = ut.get_boundary_cells( img )
                if check_border:
                    self.border_cells[tframe] = ut.get_border_cells( img )      
    
    def get_boundaries_cells(self, pbar=None):
        """ Return list of cells that are at the tissu boundaries (touching background) """
        self.boundary_cells = dict()
        for tframe in range(self.epicure.nframes):
            if pbar is not None:
                pbar.update( tframe)
            self.boundary_cells[tframe] = ut.get_boundary_cells( self.epicure.seg[tframe] )
    
    def get_border_cells(self, pbar=None):
        """ Return list of cells that are at the border of the movie """
        self.border_cells = dict()
        for tframe in range(self.epicure.nframes):
            if pbar is not None:
                pbar.update( tframe)
            img = self.epicure.seg[tframe]
            self.border_cells[tframe] = ut.get_border_cells(img)      

    def get_divisions( self ):
        """ Get and add divisions from the tracking graph """
        self.reset_event_type( "division", frame=None )
        graph = self.epicure.tracking.graph
        divisions = {}
        ## Go through the graph and fill all division by parents
        if graph is not None:
            for child, parent in graph.items():
                ## 1 parent, potential division
                if (isinstance(parent, int)) or (len(parent) == 1):
                    if isinstance( parent, list ):
                        par = parent[0]
                    else:
                        par = parent
                    if par not in divisions:
                        divisions[par] = [child]
                    else:
                        divisions[par].append(child)

        ## Add all the divisions in the event list
        for parent, childs in divisions.items():
            indexes = self.epicure.tracking.get_track_indexes(childs)
            if len(indexes) <= 0:
                ## something wrong in the graph or in the tracks, ignore for now
                continue
            ## get the average first position of the childs just after division
            pos = self.epicure.tracking.mean_position(indexes, only_first=True)     
            self.add_event(pos, parent, "division", symb="o", color="#0055ffff", force=True, refresh=False)
        ## Update display to show/hide the divisions
        self.show_hide_divisions()
        self.refresh_events()

    def show_hide_events( self, i=None, eclass=None ):
        """ Update which type of events to show or hide """
        if i is None:
            ## update all events display
            tmp_size = int(self.event_size.value())
            self.events.size = tmp_size
            hide_events = []
            for i, eclass in enumerate( self.event_class ):
                if not self.show_class[i].isChecked():
                    hide_events.append( eclass )
            self.show_subset_event( hide_events, True )
        else:
            ## update only the triggered one
            self.show_subset_event( eclass, self.show_class[i].isChecked() )

    def show_hide_divisions( self ):
        """ Show or hide division events """
        self.show_subset_event( "division", self.show_class[0].isChecked() )

    def show_hide_suspects( self ):
        """ Show or hide suspect events """
        self.show_subset_event( "suspect", self.show_class[2].isChecked() )

    def add_extrusion( self, label, frame ):
        """ Mark given label at specified frame as an extrusion """
        pos = self.epicure.tracking.get_full_position( label, frame )
        self.events.selected_data = {}
        if self.show_class[1].isChecked():
            self.events.current_size = int(self.event_size.value())
        else:
            self.events.current_size = 0.1
        self.add_event( pos, label, "extrusion", symb="diamond", color="red", force=True )
        self.events.selected_data = {}
        self.events.current_size = int(self.event_size.value())
        self.update_nevents_display()

    def add_division( self, labela, labelb, parent, frame ):
        """ Add a division event given the two daughter labels, the parent one and frame of division """
        indexes = self.epicure.tracking.get_index( [labela, labelb], frame )
        indexes = indexes.flatten()
        pos = self.epicure.tracking.mean_position( indexes )
        self.events.selected_data = {}
        if self.show_class[0].isChecked():
            self.events.current_size = int(self.event_size.value())
        else:
            self.events.current_size = 0.1
        self.add_event( pos, parent, "division", symb="o", color="#0055ffff", force=True )
        self.events.selected_data = {}
        self.events.current_size = int(self.event_size.value())
        ## check if there are suspect events to remove, cleared by the division
        if parent is not None:
            ## check eventual parent event
            num, sid = self.find_event(  pos[0]-1, parent )
            if num is not None:
                if self.is_end_event( sid ):
                    ## the parent event correspond to a potential end of track, remove it
                    ind = self.index_from_id( sid )
                    self.exonerate_one( ind, remove_division=False )
                    if self.epicure.verbose > 0:
                        print( "Removed suspect event of parent cell "+str(parent)+" cleared by the division flag" )
            ## check each child suspect if cleared by the new division 
            for child in [labela, labelb]:
                num, sid = self.find_event( pos[0], child )
                if num is not None:
                    if self.is_begin_event( sid ):
                        ## the child event correspond to a potential begin of track, remove it
                        ind = self.index_from_id( sid )
                        self.exonerate_one( ind, remove_division=False )
                        if self.epicure.verbose > 0:
                            print( "Removed suspect event of daughter cell "+str(child)+" cleared by the division flag" )
            self.update_nevents_display()

    def get_event_class( self, ind ):
        """ Return the class of event of index ind """
        if self.is_division( ind ):
            return 0
        if self.is_extrusion( ind ):
            return 1
        return 2

    def is_extrusion( self, ind ):
        """ Return if the event of current index is a division """
        return ("extrusion" in self.event_types) and (self.id_from_index(ind) in self.event_types["extrusion"])
    

    def is_division( self, ind ):
        """ Return if the event of current index is a division """
        return ("division" in self.event_types) and (self.id_from_index(ind) in self.event_types["division"])
    
    def is_suspect( self, ind ):
        """ Return if the event of current index is a suspect event """
        return not self.is_division( ind )

    def is_begin_event( self, sid ):
        """ Return True if the event has a type corresponding to begin of a track (too small or appearing) """
        beg_events = ["track-apparition", "track-length"]
        for event in beg_events:
            if event in self.event_types:
                if sid in self.event_types[event]:
                    return True
        return False

    def is_end_event( self, sid ):
        """ Return True if the event has a type corresponding to end of a track (too small or disappearing) """
        end_events = ["track-disparition", "track-length"]
        for event in end_events:
            if event in self.event_types:
                if sid in self.event_types[event]:
                    return True
        return False
    
    def track_position_jump( self, track_ids, progress_bar ):
        """ Look at jump in the track position """
        factor = float( self.jump_factor.text() )
        if progress_bar is not None:
            sub_bar = progress( total = len( track_ids ), desc="Check position jump in tracks", nest_under = progress_bar )
        for i, tid in enumerate(track_ids):
            if progress_bar is not None:
                sub_bar.update(i)
            track_indexes = self.epicure.tracking.get_track_indexes( tid )
            ## track should be long enough to make sense to look for outlier
            if len(track_indexes) > 3:
                track_velo = self.epicure.tracking.measure_speed( tid )
                jumps = self.find_jump( track_velo, factor=factor, min_value=5 )
                for tind in jumps:
                    tdata = self.epicure.tracking.get_frame_data( tid, tind )
                    if self.epicure.verbose > 1:
                        print("event track jump: "+str(tdata[0])+" "+" frame "+str(tdata[1]) )
                    self.add_event( tdata[1:4], tid, "track-jump", refresh=False )
        if progress_bar is not None:
            sub_bar.close()
        self.refresh_events()

        
    def track_features(self):
        """ Look at outliers in track features """
        track_ids = self.epicure.tracking.get_track_list()
        features = []
        featType = {}
        if self.check_size.isChecked():
            features = features + ["Area", "Perimeter"]
            featType["Area"] = "size"
            featType["Perimeter"] = "size"
            size_factor = float(self.size_variability.text())
        if self.check_shape.isChecked():
            features = features + ["Eccentricity", "Solidity"]
            featType["Eccentricity"] = "shape"
            featType["Solidity"] = "shape"
            shape_factor = float(self.shape_variability.text())
        for tid in track_ids:
            track_indexes = self.epicure.tracking.get_track_indexes( tid )
            ## track should be long enough to make sense to look for outlier
            if len(track_indexes) > 3:
                track_feats = self.epicure.tracking.measure_features( tid, features )
                for feature, values in track_feats.items():
                    if featType[feature] == "size":
                        factor = size_factor
                    if featType[feature] == "shape":
                        factor = shape_factor
                    outliers = self.find_jump( values, factor=factor )
                    for out in outliers:
                        tdata = self.epicure.tracking.get_frame_data( tid, out )
                        if self.epicure.verbose > 1:
                            print("event track "+feature+": "+str(tdata[0])+" "+" frame "+str(tdata[1]) )
                        self.add_event(tdata[1:4], tid, "track_"+featType[feature], refresh=False)
        self.refresh_events()

    def find_jump( self, tab, factor=1, min_value=None ):
        """ Detect brutal jump in the values """
        jumps = []
        tab = np.array(tab)
        diff = np.diff( tab, n=2, prepend=tab[0], append=tab[-1] )
        ## get local average
        if len(tab) <= 10:
            avg = np.mean( tab )
        else:
            kernel = np.repeat (1.0/10.0, 10 )
            avg = np.convolve( tab, kernel, mode="same")
        ## normalize the difference by the average value
        eps = 0.0000001
        diff = np.array(diff, dtype=np.float32)
        avg = np.array(avg, dtype=np.float32)
        diff = abs(diff+eps)/(avg+eps)
        ## keep only local max above threshold
        local_max = (np.diff( np.sign(np.diff(diff)) )<0).nonzero()[0] + 1
        if min_value is None:
            jumps = [i for i in local_max if diff[i] > factor]
        else:
            jumps = [ i for i in local_max if (diff[i] > factor) and (tab[i] > min_value) ]
        return jumps

    def find_outliers_tuk( self, tab, factor=3, below=True, above=True ):
        """ Returns index of outliers from Tukey's like test """
        q1 = np.quantile(tab, 0.2)
        q3 = np.quantile(tab, 0.8)
        qtuk = factor * (q3-q1)
        outliers = []
        if below:
            outliers = outliers + (np.where((tab-q1+qtuk)<0)[0]).tolist()
        if above:
            outliers = outliers + (np.where((tab-q3-qtuk)>0)[0]).tolist()
        return outliers

    def weirdo_area(self):
        """ look at area trajectory for outliers """
        track_df = self.epicure.tracking.track_df
        for tid in np.unique(track_df["track_id"]):
            rows = track_df[track_df["track_id"]==tid].copy()
            if len(rows) >= 3:
                rows["smooth"] = rows.area.rolling(self.win_size, min_periods=1).mean()
                rows["diff"] = (rows["area"] - rows["smooth"]).abs()
                rows["diff"] = rows["diff"].div(rows["smooth"])
                if self.epicure.verbose > 2:
                    print(rows)


