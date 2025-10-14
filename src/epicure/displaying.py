import numpy as np
from math import ceil
from qtpy.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget, QComboBox
from qtpy.QtCore import Qt
from magicgui.widgets import TextEdit
import epicure.Utils as ut
import epicure.epiwidgets as wid


class Displaying(QWidget):
    """ Propose some visualization options """

    def __init__(self, napari_viewer, epic):
        """ Create displaying widget instance """
        super().__init__()
        self.viewer = napari_viewer
        self.epicure = epic
        self.seglayer = self.viewer.layers["Segmentation"]
        self.gmode = 0  ## view only movie mode on/off
        self.dmode = 0  ## view with light segmentation on/off
        self.grid_color = [0.6, 0.7, 0.7, 0.7]  ## default grid color
        self.shapelayer_name = "ROIs"

        layout = QVBoxLayout()
        
        ## Show a text window with some summary of the file
        show_summary = wid.add_button( "Show summary", self.show_summary_window, "Pops-up a summary of the movie and segmentation informations" )
        layout.addWidget(show_summary)

        ## Draw and measure length of a line
        measure_line = wid.add_button( "Measure length", self.measure_line_length, "Draw a line and measure its length" )
        layout.addWidget(measure_line)

        ## Option show segmentation skeleton
        self.show_skeleton = wid.add_check( "Show segmentation skeleton", False, self.show_skeleton_segmentation, "Add a layer with the segmentation skeleton (not automatically updated)" )
        layout.addWidget(self.show_skeleton)
        
        ## Option to show the movie and seg side by side
        show_sides = QHBoxLayout()
        self.show_side = wid.add_check( "Side by side view", False, self.show_side_side, "View the movie and the other layers side by side" )
        show_sides.addWidget( self.show_side )
        self.directions = QComboBox()
        self.directions.addItem( "Horizontal" )
        self.directions.addItem( "Vertical" )
        show_sides.addWidget( self.directions )
        self.directions.currentIndexChanged.connect( self.show_side_side )
        layout.addLayout( show_sides )
        
        ## Option show shifted segmentation
        self.show_shifted = wid.add_check( "Overlay previous segmentation", False, self.show_shifted_segmentation, "Overlay the (frame-1) segmentation on the current segmentation")
        layout.addWidget(self.show_shifted)
        
        ## Option show shifted movie (previous or next)
        show_prevmovie_line = QHBoxLayout()
        self.show_previous_movie = wid.add_check( "Overlay previous movie", False, self.show_shifted_previous_movie, "Overlay the (frame-1) of the movie on the current movie" )
        layout.addWidget(self.show_previous_movie)
        self.show_next_movie = wid.add_check( "Overlay next movie", False, self.show_shifted_next_movie, "Overlay (frame+1) of the movie on the current frame" )
        layout.addWidget(self.show_next_movie)
        
        ## Option create/show grid
        grid_line, self.show_grid_options, self.group_grid = wid.checkgroup_help( "Grid options", True, "Show/hide subpanel to control grid view", "Display#grid-options", self.epicure.display_colors, groupnb="group" )
        self.grid_parameters()
        layout.addWidget(self.show_grid_options)
        layout.addWidget(self.group_grid)
        
        save_pref = wid.add_button( "Set current settings as default", self.save_current_display, "Save the current settings so that EpiCure will open in the same state next time" )
        layout.addWidget(save_pref)
        
        self.add_display_overlay_message()
        self.key_bindings()        ## activate shortcuts for display options
        self.setLayout(layout)
        ut.set_active_layer( self.viewer, "Segmentation" )
    
    ### set current display as defaut
    def save_current_display( self ):
        """ Set current display parameters as defaut display """
        self.epicure.update_settings()
        self.epicure.pref.save()

    def get_current_settings( self ):
        """ Returns current display settings """
        disp = {}
        disp["Layers"] = {}
        for layer in self.viewer.layers:
            disp["Layers"][layer.name] = layer.visible
        disp["Show Grid"] = self.show_grid_options.isChecked()
        disp["Grid nrows"] = self.nrows.text()
        disp["Grid ncols"] = self.ncols.text()
        disp["Grid width"] = self.gwidth.text()
        disp["Grid color"] = self.grid_color
        disp["Show side on"] = self.show_side.isChecked()
        disp["Side direction"] = self.directions.currentText()
        if "EpicGrid" in self.viewer.layers:
            disp["Grid text"] = self.viewer.layers["EpicGrid"].text.visible
            disp["Grid color"] = self.viewer.layers["EpicGrid"].edge_color[0]
        return disp
    
    def apply_settings( self, settings ):
        """ Set current display to prefered settings """
        add_grid = False
        show_text = False
        ## read the settings and apply them
        for setty, val in settings.items():
            if setty == "Layers":
                for layname, layvis in val.items():
                    if layname in self.viewer.layers:
                        self.viewer.layers[layname].visible = layvis
                    else:
                        if layname == "EpicGrid":
                            add_grid = layvis 
                continue
            if setty == "Show Grid":
                self.show_grid_options.setChecked( val )
                continue
            if setty == "Grid nrows":
                self.nrows.setText( val )
                continue
            if setty == "Grid ncols":
                self.ncols.setText( val )
                continue
            if setty == "Grid width":
                self.gwidth.setText( val )
                continue
            if setty == "Grid text":
                show_text = val
                continue
            if setty == "Grid color":
                self.grid_color = val
                continue
            if setty == "Show side on":
                self.show_side.setChecked( val )
            if setty == "Side direction":
                self.directions.setCurrentText( val )
            
        ## if grid should be added, do it at the end when all values are updated
        if add_grid:
            self.add_grid()
            self.viewer.layers["EpicGrid"].text.visible = show_text



    ######### overlay message
    def add_display_overlay_message(self):
        """ Shortcut list for display options """
        disptext = "--- Display options --- \n"
        sdisp = self.epicure.shortcuts["Display"]
        disptext += ut.print_shortcuts( sdisp )
        self.epicure.overtext["Display"] = disptext
        sinfo = self.epicure.shortcuts["Info"]
        self.epicure.overtext["info"] = "---- Info options --- \n"
        self.epicure.overtext["info"] += ut.print_shortcuts( sinfo )



    ################  Key binging for display options
    def key_bindings(self):
        sdisp = self.epicure.shortcuts["Display"]
        sinfo = self.epicure.shortcuts["Info"]
        
        @self.seglayer.bind_key( sdisp["vis. segmentation"]["key"], overwrite=True )
        def see_segmentlayer(seglayer):
            seglayer.visible = not seglayer.visible
        
        @self.seglayer.bind_key( sdisp["vis. movie"]["key"], overwrite=True )
        def see_movielayer(seglayer):
            ut.inv_visibility(self.viewer, "Movie")
        
        @self.seglayer.bind_key( sdisp["vis. event"]["key"], overwrite=True )
        def see_eventslayer(seglayer):
            evlayer = self.viewer.layers["Events"]
            evlayer.visible = not evlayer.visible
        
        @self.epicure.seglayer.bind_key( sinfo["measure length"]["key"], overwrite=True )
        def measure_length(layer):
            """ 
            Draw a line and measure its length 
            """
            self.measure_line_length( layer )
        
        @self.seglayer.bind_key( sdisp["skeleton"]["key"], overwrite=True )
        def show_skeleton(seglayer):
            """ On/Off show skeleton """
            if self.show_skeleton.isChecked():
                self.show_skeleton.setChecked(False)
            else:
                self.show_skeleton.setChecked(True)
        
        @self.seglayer.bind_key( sdisp["show side"]["key"], overwrite=True )
        def show_byside(seglayer):
            self.show_side.setChecked( not self.show_side.isChecked() )
            self.show_side_side()

        @self.seglayer.bind_key( sdisp["increase"]["key"], overwrite=True )
        def contour_increase(seglayer):
            if seglayer is not None:
                seglayer.contour = seglayer.contour + 1
        
        @self.seglayer.bind_key( sdisp["decrease"]["key"], overwrite=True )
        def contour_decrease(seglayer):
            if seglayer is not None:
                if seglayer.contour > 0:
                    seglayer.contour = seglayer.contour - 1
        
        @self.seglayer.bind_key( sdisp["only movie"]["key"], overwrite=True )
        def see_onlymovielayer(seglayer):
            """ if in "g" mode, show only movie, else put back to previous views """
            if self.gmode == 0:
                self.lay_view = []
                for lay in self.viewer.layers:
                    self.lay_view.append( (lay, lay.visible) )
                    lay.visible = False
                ut.inv_visibility(self.viewer, "Movie")
                self.gmode = 1
            else:
                for lay, vis in self.lay_view:
                    lay.visible = vis
                self.gmode = 0

        @self.seglayer.bind_key( sdisp["light view"]["key"], overwrite=True )
        def segmentation_lightmode(seglayer):
            """ if in "d" mode, show only movie and light segmentation, else put back to previous views """
            if self.dmode == 0:
                self.light_view = []
                for lay in self.viewer.layers:
                    self.light_view.append( (lay, lay.visible) )
                    lay.visible = False
                ut.inv_visibility(self.viewer, "Movie")
                ut.inv_visibility(self.viewer, "Segmentation")
                self.unlight_contour = self.seglayer.contour
                self.unlight_opacity = self.seglayer.opacity
                self.seglayer.contour = 1
                self.seglayer.opacity = 0.2
                self.dmode = 1
            else:
                for lay, vis in self.light_view:
                    lay.visible = vis
                self.seglayer.contour = self.unlight_contour
                self.seglayer.opacity = self.unlight_opacity
                self.dmode = 0
        
        @self.seglayer.bind_key( sdisp["grid"]["key"], overwrite=True )
        def show_grid(seglayer):
            """ show/hide the grid to have a repere in space """
            self.show_grid()

    ### Info options
    def measure_line_length(self, layer=None):
        """ 
        Draw a line and measure its length 
        """
        self.old_mouse_drag, self.old_key_map = ut.clear_bindings( self.epicure.seglayer )
        ut.show_info("Draw line to measure.")
        if self.shapelayer_name not in self.viewer.layers:
            self.create_shapelayer()
        shape_lay = self.viewer.layers[self.shapelayer_name]
        shape_lay.mode = "add_line"
        shape_lay.visible = True
        ut.set_active_layer( self.viewer, self.shapelayer_name)

        @shape_lay.mouse_drag_callbacks.append
        def click(layer, event):
            if (event.type == "mouse_press") and (len(event.modifiers)==0) and (event.button==1):
                ## dragg click to draw line
                start_pos = event.position
                yield
                while event.type == 'mouse_move':
                    #print( event.position)
                    yield
                end_pos = event.position
                self.draw_line(shape_lay, start_pos, end_pos)
                self.end_measure_mode()
            else:
                self.end_measure_mode()

    def end_measure_mode(self):
        """ Finish measuring mode """
        if self.old_mouse_drag is not None:
            if self.shapelayer_name in self.viewer.layers:
                shape_lay = self.viewer.layers[self.shapelayer_name]
                shape_lay.visible = False
            ut.reactive_bindings( self.epicure.seglayer, self.old_mouse_drag, self.old_key_map )
            ut.show_info("End measure")
        ut.set_active_layer( self.viewer, "Segmentation" )
    
    def draw_line( self, shape_lay, start_position, end_position ):
        """ Draw a line in the shape layer """
        #shape_lay.data = np.array( [start_position, end_position] )
        #shape_lay.features = { "length": np.linalg.norm(np.array(end_position[1:3]) - np.array(start_position[1:3])) }
        length = np.linalg.norm(np.array(end_position[1:3]) - np.array(start_position[1:3])) 
        ut.setOverlayText( self.viewer, "Length: "+str(round(length,1))+" µm" )
        #shape_lay.text.string = "length"
        #shape_lay.text.visible = True
        shape_lay.data = shape_lay.data[:-1]  ## remove last line drawn
        shape_lay.refresh()

    
    def show_summary_window(self):
        """ Show a text window with some infos """
        summwin = TextEdit()
        summwin.name = "Epicure summary"
        summwin.value = self.epicure.get_summary()
        summwin.show()

    ### Display options
    def show_skeleton_segmentation(self):
        """ Show/hide/update skeleton """
        if "Skeleton" in self.viewer.layers:
            ut.remove_layer(self.viewer, "Skeleton")
        if self.show_skeleton.isChecked():
            self.epicure.add_skeleton()
            ut.set_active_layer( self.viewer, "Segmentation" )

    def show_side_side( self ):
        """ Show the layers side by side """
        layout_grid = self.viewer.grid
        if self.show_side.isChecked():
            stride =  len( self.viewer.layers ) - 1
            layout_grid.stride = stride
            layout_grid.shape = (2,1)
            if self.directions.currentText() == "Horizontal":
                layout_grid.shape = (1,2)
            layout_grid.enabled = True
        else:
            layout_grid.enabled = False


    def show_shifted_segmentation(self):
        """ Show/Hide temporally shifted segmentation on top of current one """
        if ("PrevSegmentation" in self.viewer.layers):
            if (not self.show_shifted.isChecked()):
                ut.remove_layer(self.viewer, "PrevSegmentation")
            else:
                lay = self.viewer.layers["PrevSegmentation"]
                lay.refresh()

        if ("PrevSegmentation" not in self.viewer.layers) and (self.show_shifted.isChecked()):
            if self.epicure.nframes > 1:
                layer = self.viewer.add_labels( self.seglayer.data, name="PrevSegmentation", blending="additive", opacity=0.4 )
                layer.contour = 2
                layer.translate = [1, 0, 0]
                self.seglayer.contour = 2
                self.seglayer.opacity = 0.6
            else:
                ut.show_warning("Still image, cannot show previous frames")

        ut.set_active_layer( self.viewer, "Segmentation" )
    
    def show_shifted_previous_movie(self):
        """ Show/Hide temporally shifted movie previous frame on top of current one """
        self.show_shifted_movie("PrevMovie", "red", 1)
    
    def show_shifted_next_movie(self):
        """ Show/Hide temporally shifted movie next frame on top of current one """
        self.show_shifted_movie("NextMovie", "green", -1)
    
    def show_shifted_movie(self, layname, color, translation):
        """ Show/Hide temporally shifted movie on top of current one """
        if (layname in self.viewer.layers):
            if (not self.show_previous_movie.isChecked()):
                ut.remove_layer(self.viewer, layname)
            else:
                lay = self.viewer.layers[layname]
                lay.refresh()

        if (layname not in self.viewer.layers) and (self.show_previous_movie.isChecked()):
            if self.epicure.nframes > 1:
                movlay = self.viewer.layers["Movie"]
                arr = movlay.data
                if translation == -1:
                    arr = movlay.data[1:,]
                layer = self.viewer.add_image( arr, name=layname, blending="additive", opacity=0.6, colormap=color )
                if translation == 1:
                    layer.translate = [translation, 0, 0]
                layer.contrast_limits=self.epicure.quantiles()
                layer.gamma=0.94
            else:
                ut.show_warning("Still image, cannot show previous frames")

        ut.set_active_layer( self.viewer, "Segmentation" )

    #### Show/load a grid to have a repere in space
    def grid_parameters(self):
        """ Interface to get grid parameters """
        grid_layout = QVBoxLayout()
        ## nrows
        rows_line, self.nrows = wid.value_line( "Nb rows", "4", "Number of rows of the grid" )
        grid_layout.addLayout(rows_line)
        ## ncols
        cols_line, self.ncols = wid.value_line( "Nb columns:", "4", "Number of columns in the grid" )
        grid_layout.addLayout(cols_line)
        ## grid edges width
        width_line, self.gwidth = wid.value_line( "Grid width:", "3", "Width of the grid displayed lines/columns" )
        grid_layout.addLayout(width_line)
       ## go for grid
        btn_add_grid = wid.add_button( "Add grid", self.add_grid, "Add a grid overlay to the main view" )
        grid_layout.addWidget(btn_add_grid)
        self.group_grid.setLayout(grid_layout)

    def add_grid(self):
        """ Create/Load a new grid and add it """
        ut.remove_layer(self.viewer, "EpicGrid")
        imshape = self.epicure.imgshape2D
        if imshape is None:
            ut.show_error("Load the image first")
            return
        nrows = int(self.nrows.text())
        ncols = int(self.ncols.text())
        wid = ceil(imshape[0]/nrows)
        hei = ceil(imshape[1]/ncols)
        rects = []
        rects_names = []
        gwidth = int(self.gwidth.text())
        for x in range(nrows):
            for y in range(ncols):
                rect = np.array([[x*wid, y*hei], [(x+1)*wid, (y+1)*hei]])
                rects.append(rect)
                rects_names.append(chr(65+x)+"_"+str(y))
        self.viewer.add_shapes(rects, name="EpicGrid", text=rects_names, face_color=[1,0,0,0], edge_color=self.grid_color, edge_width=gwidth, opacity=0.7, scale=self.viewer.layers["Segmentation"].scale[1:])
        self.viewer.layers["EpicGrid"].text.visible = False
        ut.set_active_layer( self.viewer, "Segmentation" )

    def show_grid(self):
        """ Interface to create/load a grid for repere """
        if "EpicGrid" not in self.viewer.layers:
            self.add_grid()
        else:
            gridlay = self.viewer.layers["EpicGrid"]
            gridlay.visible = not gridlay.visible
            gridlay.edge_color = self.grid_color
