import numpy as np
import edt # type: ignore
from skimage.segmentation import watershed, clear_border, find_boundaries, random_walker
from skimage.measure import label, points_in_poly
from skimage.morphology import binary_closing, binary_opening, binary_dilation, binary_erosion, disk
from qtpy.QtWidgets import QWidget # type: ignore
from scipy.ndimage import binary_fill_holes, distance_transform_edt, generate_binary_structure
from scipy.ndimage import label as ndlabel 
from napari.layers.labels._labels_utils import sphere_indices # type: ignore
from napari.layers.labels._labels_utils import interpolate_coordinates # type: ignore
from napari.utils import progress # type: ignore
from napari.qt.threading import thread_worker # type: ignore
import epicure.Utils as ut
import epicure.epiwidgets as wid

class Editing( QWidget ):
    """ Handle user interaction to edit the segmentation """

    def __init__(self, napari_viewer, epic):
        super().__init__()
        self.viewer = napari_viewer
        self.epicure = epic
        self.old_mouse_drag = None
        self.tracklayer_name = "Tracks"
        self.shapelayer_name = "ROIs"
        self.grouplayer_name = "Groups"
        self.updated_labels = None   ## keep which labels are being edited
        self.seed_active = False ## if place seed option is on

        layout = wid.vlayout()
        
        ## Option to use default napari painting options
        #self.napari_painting = wid.add_check( "Default Napari painting tools (no checks)", checked=False, check_func=self.painting_tools, descr="Use the label painting of Napari instead of customized EpiCure ones (will not perform any sanity check)" )
        #layout.addWidget( self.napari_painting )

        ## Option to remove all border cells
        clean_line, self.clean_vis, self.gCleaned = wid.checkgroup_help( name="Cleaning options", checked=False, descr="Show/hide options to clean the segmentation", help_link="Edit#cleaning-options", display_settings=self.epicure.display_colors, groupnb="group" )
        layout.addLayout(clean_line)
        self.create_cleaningBlock()
        layout.addWidget(self.gCleaned)
        self.gCleaned.hide()

        ## handle grouping cells into categories
        group_line, self.group_vis, self.gGroup = wid.checkgroup_help( name="Cell group options", checked=False, descr="Show/hide options to define cell groups", help_link="Edit#group-options", display_settings=self.epicure.display_colors, groupnb="group2"  )
        layout.addLayout(group_line)
        self.create_groupCellsBlock()
        layout.addWidget(self.gGroup)
        self.gGroup.hide()
        
        ## Selection option: crop, remove cells
        select_line, self.select_vis, self.gSelect = wid.checkgroup_help( name="ROI options", checked=False, descr="Show/hide options to work on Regions", help_link="Edit#roi-options", display_settings=self.epicure.display_colors, groupnb="group3" )
        layout.addLayout(select_line)
        self.create_selectBlock()
        layout.addWidget(self.gSelect)
        self.gSelect.hide()
        
        ## Put seeds and do watershed from it
        seed_line, self.seed_vis, self.gSeed = wid.checkgroup_help( name="Seeds options", checked=False, descr="Show/hide options to segment from seeds", help_link="Edit#seeds-options", display_settings=self.epicure.display_colors, groupnb="group4" )
        layout.addLayout(seed_line)
        self.create_seedsBlock()
        layout.addWidget(self.gSeed)
        self.gSeed.hide()
        
        self.setLayout(layout)
        
        ## interface done, ready to work 
        self.create_shapelayer()
        self.modify_cells()
        self.key_tracking_binding()
        self.add_overlay_message()

        ## catch filling/painting operations
        self.napari_fill = self.epicure.seglayer.fill
        self.epicure.seglayer.fill = self.epicure_fill
        self.napari_paint = self.epicure.seglayer.paint
        self.epicure.seglayer.paint = self.lazy #self.epicure_paint
        ### scale and radius for paiting
        self.paint_scale = np.array([self.epicure.seglayer.scale[i+1] for i in range(2)], dtype=float)
        self.epicure.seglayer.events.brush_size.connect( self.paint_radius )
        self.paint_radius()
        self.disk_one = disk(radius=1)
        self.classif = ClassifyIntensity( self )
        self.classif_event = ClassifyEvent( self )
        self.scalexy = self.epicure.epi_metadata["ScaleXY"]

    def painting_tools( self ):
        """ Choose which painting tools should be activated """
        if self.napari_painting.isChecked():
            self.epicure.seglayer.fill = self.napari_fill
            self.epicure.seglayer.paint = self.napari_paint
        else:
            self.epicure.seglayer.fill = self.epicure_fill
            self.epicure.seglayer.paint = self.lazy


    def apply_settings( self, settings ):
        """ Load the prefered settings for Edit panel """
        for setting, val in settings.items():
            if setting == "Show group option":
                self.group_vis.setChecked( val )
            if setting == "Show clean option":
                self.clean_vis.setChecked( val )
            if setting ==  "Show ROI option":
                self.select_vis.setChecked( val )
            if setting == "Show seed option":
                self.seed_vis.setChecked( val )
            if setting == "Show groups":
                self.group_show.setChecked( val )
            if setting == "Border size":
                self.border_size.setText( val )
            if setting == "Seed method":
                self.seed_method.setCurrentText( val )
            if setting == "Seed max cell":
                self.max_distance.setText( val )
           

    def get_current_settings( self ):
        """ Returns the current state of the Edit widget """
        setting = {}
        setting["Show group option"] = self.group_vis.isChecked()
        setting["Show clean option"] = self.clean_vis.isChecked()
        setting["Show ROI option"] = self.select_vis.isChecked()
        setting["Show seed option"] = self.seed_vis.isChecked()
        setting["Show groups"] = self.group_show.isChecked()
        setting["Border size"] = self.border_size.text()
        setting["Seed method"] = self.seed_method.currentText()
        setting["Seed max cell"] = self.max_distance.text()
        return setting
   
    def paint_radius( self ):
        """ Update painitng radius with brush size """
        self.radius = np.floor(self.epicure.seglayer.brush_size / 2) + 0.5
        self.brush_indices = sphere_indices(self.radius, tuple(self.paint_scale)) 

    def setParent(self, epy):
        self.epicure = epy

    def get_filename(self, endname):
        return ut.get_filename(self.epicure.outdir, self.epicure.imgname+endname )
        
    def get_values(self, coord):
        """ Get the label value under coord, the current frame, prepare the coords """
        int_coord = tuple(np.round(coord).astype(int))
        tframe = int(coord[0])
        segdata = self.epicure.seglayer.data[tframe]
        int_coord = int_coord[1:3]
        # get value of the label that will be painted over
        prev_label = int(segdata[int_coord])
        return int_coord, tframe, segdata, prev_label

    ### Get fill or paint action and assure compatibility with structure
    def epicure_fill(self, coord, new_label, refresh=True):
        """ Check if the filled cell is already registered """
        if new_label == 0:
            if self.epicure.verbose > 0:
                ut.show_warning("Fill with 0 (background) not allowed \n Use Eraser tool (press <1>) to erase")
                return
        int_coord, tframe, segdata, prev_label = self.get_values( coord )

        hascell = self.epicure.has_label( new_label )
        if hascell:
            ## already present, check that it is at the same place
            ## label before
            mask_before = segdata==new_label
            if np.sum(mask_before) <= 0:
                ut.show_warning("Label "+str(new_label)+" is already used in other frames. Choose another label")
                return
        
        ## if try to fill an empty zone, ensure that it doesn't fill the skeletons
        if prev_label == 0:
            skel = ut.frame_to_skeleton( segdata )
            skel_fill = max(np.max(segdata)+2, new_label+1)
            segdata[skel] = skel_fill
            skel = None
            
        if hascell:
            # if contiguous replace only selected connected component, calculate how it would be changed
            matches = (segdata == prev_label)
            labeled_matches, num_features = label(matches, return_num=True)
            if num_features != 1:
                match_label = labeled_matches[int_coord]
                matches = np.logical_and( matches, labeled_matches == match_label )
           
            # check if touch the already present cell
            ok = self.touching_masks(mask_before, matches)
            if not ok:
                ut.show_warning("Label "+str(new_label)+" added do not touch already present cell. Choose another label or draw contiguously")
                ## reset if necessary
                if prev_label == 0:
                    segdata[segdata==skel_fill] = 0  ## put skeleton back to 0
                return
            ut.setNewLabel( self.epicure.seglayer, (np.argwhere(matches)).tolist(), new_label, add_frame=tframe )
            if prev_label == 0:
                segdata[skel] = 0  ## put skeleton back to 0
        else:
            ## new cell, add it to the tracks list
            self.napari_fill(coord, new_label, refresh=True)
            if prev_label == 0:
                segdata[segdata==skel_fill] = 0  ## put skeleton back to 0
                ut.remove_boundaries(segdata)
            self.epicure.add_label(new_label, tframe)
        
        ## Finish filling step to ensure everything's fine
        self.epicure.seglayer.refresh()
        ## put the active mode of the layer back to the zoom one
        self.epicure.seglayer.mode = "pan_zoom"
        if prev_label != 0: 
            self.epicure.tracking.remove_one_frame( [prev_label], tframe, handle_gaps=self.epicure.forbid_gaps )

    def lazy( self, coord, new_label, refresh=True ):
        return

    def epicure_paint( self, coords, new_label, tframe, hascell ):
        """ Edit a label with paint tool, with several pixels at once """
        mask_indices = None
        ## convert the coords with brush size, check that is fully inside
        for coord in coords:
            int_coord = np.array( np.round(coord).astype(int)[1:3] ) 
            for brush in self.brush_indices:
                pt = int_coord + brush
                if ut.inside_bounds( pt, self.epicure.imgshape2D ):
                    if mask_indices is None:
                        mask_indices = pt
                    else:
                        mask_indices = np.vstack( ( mask_indices, pt ) )
        
        ## crop around part of the image to update
        bbox = ut.getBBoxFromPts( mask_indices, extend=0, imshape=self.epicure.imgshape2D )
        if hascell:
            ## extend around points a lot if the label is there already to avoid cutting it
            extend = 4
        else:
            extend = 1.5
        bbox = ut.extendBBox2D( bbox, extend_factor=extend, imshape=self.epicure.imgshape2D )
        cropdata = ut.cropBBox2D( self.epicure.seglayer.data[tframe], bbox )
        crop_indices = ut.positions2DIn2DBBox( mask_indices, bbox )
        
        ## get previous data before painting
        prev_labels = np.unique( cropdata[ tuple(np.array(crop_indices).T) ] ).tolist()
        if 0 in prev_labels:
            prev_labels.remove(0)

        if new_label > 0:    
            if hascell:
                ## check that label is in current frame
                mask_before = cropdata==new_label
                if not np.isin(1, mask_before):
                    ut.show_warning("Label "+str(new_label)+" is already used in other frames. Choose another label")
                    return

                ## already present, check that it is at the same place
                #### Test if painting touch previous label
                mask_after = np.zeros(cropdata.shape)
                mask_after[ tuple(np.array(crop_indices).T) ] = 1
                ok = self.touching_masks(mask_before, mask_after)
                if not ok:
                    ut.show_warning("Label "+str(new_label)+" added do not touch already present cell. Choose another label or draw contiguously")
                    return
            else:
                ## drawing new cell, fill it at the end
                if self.epicure.verbose > 2:
                    print("Painting a new cell")

        ## Paint and update everything    
        painted = np.copy(cropdata)
        painted[ tuple(np.array(crop_indices).T) ] = new_label
        if new_label > 0:
            if self.epicure.seglayer.preserve_labels:
                painted = painted*(np.isin( cropdata, [0, new_label] ))
                painted = binary_fill_holes( (painted==new_label) )
                ## remove one-pixel thick lines
                painted = binary_opening( painted )
                crop_indices = np.argwhere( (painted>0) )
            else:
                painted = binary_fill_holes( painted==new_label )
                crop_indices = np.argwhere(painted>0)    
        ### if preseve label is on, there can be nothing left to paint
        if len(crop_indices) <= 0:
            return
        mask_indices = ut.toFullMoviePos( crop_indices, bbox, tframe )
        new_labels = np.repeat(new_label, len(mask_indices)).tolist()

        ## Update label boundaries if necessary
        cind_bound = ut.ind_boundaries( painted )
        if self.epicure.seglayer.preserve_labels:
            ind_bound = [ ind for ind in cind_bound if (cropdata[tuple(ind)] == new_label) ]
        else:
            ind_bound = [ ind for ind in cind_bound if cropdata[tuple(ind)] in prev_labels ]
        if (new_label>0) and (len( ind_bound ) > 0):
            bound_ind = ut.toFullMoviePos( ind_bound, bbox, tframe )
            bound_labels = np.repeat(0, len(bound_ind)).tolist()
            mask_indices = np.vstack( (mask_indices, bound_ind) )
            new_labels = new_labels + bound_labels

        ## Go, apply the change, and update the tracks
        self.epicure.change_labels( mask_indices, new_labels )

    def create_cell_from_line( self, tframe, positions ):
        """ Create new cell(s) from drawn line (junction) """
        bbox = ut.getBBox2DFromPts( positions, extend=0, imshape=self.epicure.imgshape2D )
        bbox = ut.extendBBox2D( bbox, extend_factor=2, imshape=self.epicure.imgshape2D )

        segt = self.epicure.seglayer.data[tframe]
        cropt = ut.cropBBox2D( segt, bbox )
        crop_positions = ut.positionsIn2DBBox( positions, bbox )

        line = np.zeros(cropt.shape, dtype="uint8")
        ## fill the already filled pixels by other labels
        line[ cropt > 0 ] = 1
        ## expand from one pixel to fill the junction
        line = binary_dilation( line )
        ## fill the interpolated line
        for i, pos in enumerate(crop_positions):
            if cropt[round(pos[0]), round(pos[1])] == 0:
                line[round(pos[0]), round(pos[1])] = 1
            if (i > 0):
                prev = (crop_positions[i-1][0], crop_positions[i-1][1])
                cur = (pos[0], pos[1])
                interp_coords = interpolate_coordinates(prev, cur, 1)
                for ic in interp_coords:
                    line[tuple(np.round(ic).astype(int))] = 1
        
        ## close the junction gaps, and the line eventually
        line = binary_closing( line )
        new_cells, nlabels = label( line, background=1, return_num=True, connectivity=1 )
        ## no new cell to create
        if nlabels <= 0:
            return
        ## get the new labels to relabel and add as new cells
        labels = list( set( new_cells.flatten() ) )
        if 0 in labels:
            labels.remove(0)
       
        ## try to get new cell labels from previous and next slices
        parents = [None]*len(labels)
        if tframe > 0:
            twoframes = ut.crop_twoframes( self.epicure.seglayer.data, bbox, tframe )
            twoframes[1] = new_cells
            twoframes = self.keep_orphans( twoframes, tframe )
            parents = self.get_parents( twoframes, labels )
        childs = [None]*len(labels)
        if tframe < (self.epicure.nframes-1):
            twoframes = np.copy( ut.cropBBox2D(self.epicure.seglayer.data[tframe+1], bbox) )
            twoframes = np.stack( (twoframes, np.copy(new_cells)) )
            twoframes = self.keep_orphans( twoframes, tframe )
            childs = self.get_parents( twoframes, labels )
        
        free_labels = self.epicure.get_free_labels( nlabels )  
        torelink = []
        for i in range( len(labels) ):
            if (parents[i] is not None) and (childs[i] is not None):
                free_labels[i] = parents[i]
                if self.epicure.verbose > 0:
                    print("Link new cell with previous/next "+str(free_labels[i]))
                #if childs[i] != parents[i]:
                #    torelink.append( [free_labels[i], childs[i]] )
            ## only one link found, take it
            if (parents[i] is not None) and (childs[i] is None):
                free_labels[i] = parents[i]
                if self.epicure.verbose > 0:
                    print("Link new cell with previous/next "+str(free_labels[i]))
            if (parents[i] is None) and (childs[i] is not None):
                free_labels[i] = childs[i]
                if self.epicure.verbose > 0:
                    print("Link new cell with previous/next "+str(free_labels[i]))

        print("Added cells "+str(free_labels))

        ## get the new indices and labels to draw
        new_labels = []
        indices = None
        for i, lab in enumerate( labels ):
            curindices = np.argwhere( new_cells == lab )
            if indices is None:
                indices = curindices
            else:
                indices = np.vstack((indices, curindices))
            new_labels = new_labels + ([free_labels[i]]*curindices.shape[0])    
        
        ## add the label boundary
        indbound = ut.ind_boundaries( new_cells )
        indices = np.vstack( (indices, indbound) )
        new_labels = new_labels + np.repeat( 0, len(indbound) ).tolist()
        indices = ut.toFullMoviePos( indices, bbox, tframe )
        self.epicure.change_labels( indices, new_labels )

        ## relink child tracks if necessary
        #for relink in torelink:
        #    self.epicure.replace_label( relink[1], relink[0], tframe )
        
    def touching_masks(self, maska, maskb):
        """ Check if the two mask touch """
        maska = binary_dilation(maska, footprint=self.disk_one)
        return np.sum(np.logical_and(maska, maskb))>0
    
    def touching_indices(self, maska, indices):
        """ Check if the indices touch the mask """
        maska = binary_dilation(maska, footprint=self.disk_one)
        return np.isin(1, maska[indices]) > 0


    ## Merging/splitting cells functions
    def modify_cells(self):
        sl = self.epicure.shortcuts["Labels"]
        self.epicure.overtext["labels"] = "---- Labels editing ---- \n"
        self.epicure.overtext["labels"] += ut.print_shortcuts( sl )
        
        sgroup = self.epicure.shortcuts["Groups"]
        self.epicure.overtext["grouped"] = "---- Group cells ---- \n"
        self.epicure.overtext["grouped"] += ut.print_shortcuts( sgroup )
        
        sseed = self.epicure.shortcuts["Seeds"]
        self.epicure.overtext["seed"] = "---- Seed options --- \n"
        self.epicure.overtext["seed"] += ut.print_shortcuts( sseed )

        @self.epicure.seglayer.mouse_drag_callbacks.append
        def set_checked(layer, event):
            if event.type == "mouse_press":
                if (event.button == 1) and (len(event.modifiers) == 0):
                    if layer.mode == "paint": 
                        #and not self.napari_painting.isChecked():
                        ### Overwrite the painting to check that everything stays within EpiCure constraints
                        if self.shapelayer_name not in self.viewer.layers:
                            self.create_shapelayer()
                        shape_lay = self.viewer.layers[self.shapelayer_name]
                        shape_lay.mode = "add_path"
                        shape_lay.visible = True
                        @thread_worker
                        def refresh_image():                       
                            shape_lay.refresh()
                            return
                        pos = np.array( [shape_lay.world_to_data(event.position)] )
                        yield
                        ## record all the successives position of the mouse while clicked
                        iter = 0
                        while (event.type == 'mouse_move'): # and (len(pos)<200):
                            pos = np.vstack( (pos, np.array(shape_lay.world_to_data(event.position))) )
                            if iter == 5:
                                shape_lay.data = pos
                                shape_lay.shape_type = "path"
                                refresh_image()
                                #shape_lay.refresh()
                                iter = 0
                            iter = iter + 1
                            yield
                        pos = np.vstack( (pos, np.array(shape_lay.world_to_data(event.position))) )    
                        tframe = int( pos[0][0] )
                        ## painting a new or extending a cell
                        new_label = layer.selected_label
                        hascell = None
                        if new_label > 0:
                            hascell = self.epicure.has_label( new_label )
                        ## paint the selected pixels following EpiCure constraints
                        self.epicure_paint( pos, new_label, tframe, hascell )
                        shape_lay.data = []
                        shape_lay.refresh()
                        shape_lay.visible = False

        @self.epicure.seglayer.mouse_drag_callbacks.append
        def set_checked(layer, event):
            if event.type == "mouse_press":
                if ut.shortcut_click_match( sgroup["add group"], event ):
                    if self.group_choice.currentText() == "":
                        ut.show_warning("Write a group name before")
                        return
                    if self.epicure.verbose > 0:
                        print("Mark cell in group "+self.group_choice.currentText())
                    self.add_cell_to_group(event)
                    return
                
                if ut.shortcut_click_match( sgroup["remove group"], event ):
                    if self.epicure.verbose > 0:
                        print("Remove cell from its group")
                    self.remove_cell_group(event)
                    return

        @self.epicure.seglayer.bind_key("Control-z", overwrite=False)
        def undo_operations(seglayer):
            if self.epicure.verbose > 0:
                print("Undo previous action")
            img_before = np.copy(self.epicure.seg)
            self.epicure.seglayer.undo()
            self.epicure.update_changed_labels_img( img_before, self.epicure.seglayer.data )

        @self.epicure.seglayer.bind_key( sl["unused paint"]["key"], overwrite=True )
        def set_nextlabel(layer):
            lab = self.epicure.get_free_label()
            ut.show_info( "Unused label "+": "+str(lab) )
            ut.set_label(layer, lab)
        
        @self.epicure.seglayer.bind_key( sl["unused fill"]["key"], overwrite=True )
        def set_nextlabel_paint(layer):
            lab = self.epicure.get_free_label()
            ut.show_info( "Unused label "+": "+str(lab) )
            ut.set_label(layer, lab)
            layer.mode = "FILL"
        
        @self.epicure.seglayer.bind_key( sl["swap mode"]["key"], overwrite=True )
        def key_swap(layer):
            """ Active key bindings for label swapping options """
            ut.show_info("Begin swap mode: Control and click to swap two labels")
            self.old_mouse_drag, self.old_key_map = ut.clear_bindings( self.epicure.seglayer )

            @self.epicure.seglayer.mouse_drag_callbacks.append
            def click(layer, event):
                """ Swap the labels from first to last position of the pressed mouse """
                if event.type == "mouse_press":
                    if len(event.modifiers) > 0:
                        start_label = self.epicure.seglayer.get_value(position=event.position, view_direction = event.view_direction, dims_displayed=event.dims_displayed, world=True)
                        start_pos = event.position
                        yield
                        while event.type == 'mouse_move':
                            yield
                        end_label = self.epicure.seglayer.get_value(position=event.position, view_direction = event.view_direction, dims_displayed=event.dims_displayed, world=True)
                        end_pos = event.position
                        tframe = int(event.position[0])
                    
                        if start_label == 0 or end_label == 0:
                            if self.epicure.verbose > 0:
                                print("One position is not a cell, do nothing")
                            return

                        if (event.button == 1) and ("Control" in event.modifiers):
                            # Left-click: swap labels at each end of the click
                            if self.epicure.verbose > 0:
                                print("Swap cell "+str(start_label)+" and "+str(end_label))
                            self.swap_labels(tframe, start_label, end_label)
                    
                ut.reactive_bindings( self.epicure.seglayer, self.old_mouse_drag, self.old_key_map )
                ut.show_info("End swap")
        
        @self.epicure.seglayer.bind_key( sseed["new seed"]["key"], overwrite=True )
        def place_seed(layer):
            if self.seed_active:
                ## if option is currently on, stop it
                self.end_place_seed()
                return
            if "Seeds" not in self.viewer.layers:
                self.create_seedlayer()
                ut.set_active_layer( self.viewer, "Segmentation" )
            ## desactivate other click-binding
            self.old_mouse_drag = self.epicure.seglayer.mouse_drag_callbacks.copy()
            self.epicure.seglayer.mouse_drag_callbacks = []
            self.seed_active = True
            ut.show_info("Left-click to place a new seed")

            @self.epicure.seglayer.mouse_drag_callbacks.append
            def click(layer, event):
                if (event.type == "mouse_press") and (len(event.modifiers)==0) and (event.button==1):
                    ## single left-click place a seed
                    if "Seeds" not in self.viewer.layers:
                        self.reset_seeds()
                    self.place_seed(event.position)
                else:
                    self.end_place_seed()

        @self.epicure.seglayer.bind_key( sl["draw junction mode"]["key"], overwrite=True )
        def manual_junction(layer):
            """ Launch the manual drawing junction mode """
            self.drawing_junction_mode()

        @self.epicure.seglayer.mouse_drag_callbacks.append
        def click(layer, event):
            if event.type == "mouse_press":
                ## erase cell option
                if ut.shortcut_click_match( sl["erase"], event ):
                    # single right-click: erase the cell
                    tframe = ut.current_frame(self.viewer)
                    erased = ut.setLabelValue(self.epicure.seglayer, self.epicure.seglayer, event, 0, tframe, tframe)
                    ## delete also in track data
                    if erased is not None:
                        self.epicure.delete_track( erased, tframe )
                    return
                        
                merging = ut.shortcut_click_match( sl["merge"], event )
                splitting = ut.shortcut_click_match( sl["split accross"], event )
                if merging or splitting:
                    # get the start and last labels
                    start_label = self.epicure.seglayer.get_value(position=event.position, view_direction = event.view_direction, dims_displayed=event.dims_displayed, world=True)
                    start_pos = self.epicure.seglayer.world_to_data( event.position )
                    yield
                    while event.type == 'mouse_move':
                        yield
                    end_label = self.epicure.seglayer.get_value(position=event.position, view_direction = event.view_direction, dims_displayed=event.dims_displayed, world=True)
                    end_pos = self.epicure.seglayer.world_to_data( event.position )
                    tframe = int(end_pos[0])
                    
                    if start_label == 0 or end_label == 0:
                        if self.epicure.verbose > 0:
                            print("One position is not a cell, do nothing")
                        return

                    if merging:
                        ## Merge labels at each end of the click
                        if start_label != end_label:
                            if self.epicure.verbose > 0:
                                print("Merge cell "+str(start_label)+" with "+str(end_label))
                            self.merge_labels(tframe, start_label, end_label)
                            return
                    
                    if splitting:
                        ## split label at each end of the click
                        if start_label == end_label:
                            if self.epicure.verbose > 0:
                                print("Split cell "+str(start_label))
                            self.split_label(tframe, start_label, start_pos, end_pos)
                        else:
                            if self.epicure.verbose > 0:
                                print("Not the same cell already, do nothing")
                    return

                drawing_split = ut.shortcut_click_match( sl["split draw"], event )
                redrawing = ut.shortcut_click_match( sl["redraw junction"], event )
                if drawing_split or redrawing:
                    if self.shapelayer_name not in self.viewer.layers:
                        self.create_shapelayer()
                    shape_lay = self.viewer.layers[self.shapelayer_name]
                    shape_lay.mode = "add_path"
                    shape_lay.visible = True
                    shape_lay.data = []
                    scaled_pos = shape_lay.world_to_data(event.position)
                    pos = [scaled_pos]
                    yield
                    ## record all the successives position of the mouse while clicked
                    while event.type == 'mouse_move':
                        scaled_pos = shape_lay.world_to_data(event.position)
                        pos.append( scaled_pos )
                        shape_lay.data = np.array( pos )
                        shape_lay.shape_type = "path"
                        shape_lay.refresh()
                        yield
                    scaled_pos = shape_lay.world_to_data(event.position)
                    pos.append( scaled_pos )
                    ut.set_active_layer(self.viewer, "Segmentation")
                    tframe = int(event.position[0])
                    if redrawing:
                        ##  modify junction along the drawn line
                        if self.epicure.verbose > 0:
                            print("Correct junction with the drawn line ")
                        self.redraw_along_line(tframe, pos)
                        shape_lay.data = []
                        shape_lay.refresh()
                        shape_lay.visible = False
                        return
                    if drawing_split:
                        ## split labels along the drawn line
                        if self.epicure.verbose > 0:
                            print("Split cell along the drawn line ")
                        self.split_along_line(tframe, pos)
                        shape_lay.data = []
                        shape_lay.refresh()
                        shape_lay.visible = False
                        return
        
    def drawing_junction_mode( self ):
        """ Active mouse bindings for manually drawing the junction, and try to fill defined area """
            
        sl = self.epicure.shortcuts["Labels"]
        ut.show_info("Begin drawing junction: Control-Left-click to draw the junction and create new cell(s) from it")
        self.old_mouse_drag, self.old_key_map = ut.clear_bindings( self.epicure.seglayer )
        
        @self.epicure.seglayer.bind_key( sl["draw junction mode"]["key"], overwrite=True )
        def stop_draw_junction_mode( layer ):
            ut.reactive_bindings( self.epicure.seglayer, self.old_mouse_drag, self.old_key_map )
            ut.show_info("End drawing mode")
        
        @self.epicure.seglayer.mouse_drag_callbacks.append
        def click(layer, event):
            if ut.shortcut_click_match( sl["drawing junction"], event ):
                shape_lay = self.viewer.layers[self.shapelayer_name]
                shape_lay.mode = "add_path"
                shape_lay.visible = True
                scaled_position = shape_lay.world_to_data( event.position )
                pos = [scaled_position]
                yield
                ## record all the successives position of the mouse while clicked
                i = 0
                while event.type == 'mouse_move':
                    scaled_position = shape_lay.world_to_data( event.position )
                    pos.append( scaled_position )
                    if i%5 == 0:
                        # refresh display every n steps
                        shape_lay.data = np.array( pos ) 
                        shape_lay.shape_type = "path"
                        shape_lay.refresh()
                    i = i + 1
                    yield
                scaled_position = shape_lay.world_to_data( event.position )
                pos.append(scaled_position)
                ut.set_active_layer(self.viewer, "Segmentation")
                tframe = int(event.position[0])
                self.create_cell_from_line( tframe, pos )        
                shape_lay.data = []
                shape_lay.refresh()
                shape_lay.visible = False
                ut.reactive_bindings( self.epicure.seglayer, self.old_mouse_drag, self.old_key_map )
                ut.show_info("End drawing mode")

    def split_label(self, tframe, startlab, start_pos, end_pos):
        """ Split the label in two cells based on the two seeds """
        segt = self.epicure.seglayer.data[tframe]
        labelBB = ut.getBBox2D(segt, startlab)
        labelBB = ut.extendBBox2D( labelBB, extend_factor=1.25, imshape=self.epicure.imgshape2D )

        mov = self.viewer.layers["Movie"].data[tframe]
        imgBB = ut.cropBBox2D(mov, labelBB)
        segBB = ut.cropBBox2D(segt, labelBB)
        maskBB = np.zeros(segBB.shape, dtype="uint8")
        maskBB[segBB==startlab] = 1
        spos = ut.positionIn2DBBox( start_pos, labelBB )
        epos = ut.positionIn2DBBox( end_pos, labelBB )

        markers = np.zeros(maskBB.shape, dtype=self.epicure.dtype)
        markers[spos] = startlab
        markers[epos] = self.epicure.get_free_label()
        splitted = watershed( imgBB, markers=markers, mask=maskBB )
        if (np.sum(splitted==startlab) < self.epicure.minsize) or (np.sum(splitted==markers[epos]) < self.epicure.minsize):
            if self.epicure.verbose > 0:
                print("Sorry, split failed, one cell smaller than "+str(self.epicure.minsize)+" pixels")
        else:
            if len(np.unique(splitted)) > 2:
                curframe = np.zeros(segBB.shape, dtype="uint8")
                labels = []
                for i, splitlab in enumerate(np.unique(splitted)):
                    if splitlab > 0:
                        curframe[splitted==splitlab] = i+1
                        labels.append(i+1)

                curframe = ut.remove_boundaries(curframe)
                ## apply the split and propagate the label to descendant label
                self.propagate_label_change( curframe, labels, labelBB, tframe, [startlab] )
            else:
                if self.epicure.verbose > 0:
                    print("Split failed, no boundary in pixel intensities found")


    def redraw_along_line(self, tframe, positions):
        """ Redraw the two labels separated by a line drawn manually """
        bbox = ut.getBBox2DFromPts( positions, extend=0, imshape=self.epicure.imgshape2D )
        #bbox = ut.extendBBox2D( bbox, extend_factor=1.25, imshape=self.epicure.imgshape2D )

        segt = self.epicure.seglayer.data[tframe]
        cropt = ut.cropBBox2D( segt, bbox )
        crop_positions = ut.positionsIn2DBBox( positions, bbox )

        # get the value of the cells to update (most frequent label along the line)
        curlabels = []
        prev_pos = None
        # Find closest zero elements in the inverted image (same as closest non-zero for image)
        
        crop_zeros = distance_transform_edt(cropt, return_distances=False, return_indices=True)

        for pos in crop_positions:
            if (prev_pos is None) or ((round(pos[0]) != round(prev_pos[0])) and (round(pos[1]) != round(prev_pos[1]) )):
                ## find closest pixel that is 0 (on a junction)
                juncpoint = crop_zeros[:, round(pos[0]), round(pos[1])]
                labs = np.unique( cropt[ (juncpoint[0]-2):(juncpoint[0]+2), (juncpoint[1]-2):(juncpoint[1]+2) ] )
                for clab in labs:
                    if clab > 0:
                        curlabels.append(clab)
                prev_pos = pos
                
        sort_curlabel = sorted(set(curlabels), key=curlabels.count)
        ## external junction: only one cell
        if len(sort_curlabel) < 2:
            if self.epicure.verbose > 0:
                print("Only one cell along the junction: can't do it")
                return
        flabel = sort_curlabel[-1]
        slabel = sort_curlabel[-2]
        if self.epicure.verbose > 0:
            print("Cells to update: "+str(flabel)+" "+str(slabel))
        
        ## crop around selected label
        bbox, _ = ut.getBBox2DMerge( segt, flabel, slabel )
        bbox = ut.extendBBox2D( bbox, extend_factor=1.25, imshape=self.epicure.imgshape2D )
        init_cropt = ut.cropBBox2D( segt, bbox )
        curlabel = flabel
        ## merge the two labels together
        binlab = np.isin( init_cropt, [flabel, slabel] )*1
        footprint = disk(radius=2)
        cropt = flabel*binary_closing(binlab, footprint)
        crop_positions = ut.positionsIn2DBBox( positions, bbox )

        # draw the line only in the cell to split
        line = np.zeros(cropt.shape, dtype="uint8")
        for i, pos in enumerate(crop_positions):
            if cropt[round(pos[0]), round(pos[1])] == curlabel:
                line[round(pos[0]), round(pos[1])] = 1
            if (i > 0):
                prev = (crop_positions[i-1][0], crop_positions[i-1][1])
                cur = (pos[0], pos[1])
                interp_coords = interpolate_coordinates(prev, cur, 1)
                for ic in interp_coords:
                    line[tuple(np.round(ic).astype(int))] = 1
        self.move_in_crop( curlabel, init_cropt, cropt, crop_positions, line, bbox, tframe, retry=0)
    
    def move_in_crop(self, curlabel, init_cropt, cropt, crop_positions, line, bbox, frame, retry):
        """ Move the junction in the cropped region """
        dis = retry
        footprint = disk(radius=dis)
        dilline = binary_dilation(line, footprint=footprint)

        # get the two splitted regions and relabel one of them
        clab = np.zeros(cropt.shape, dtype="uint8")
        clab[cropt==curlabel] = 1
        clab[dilline] = 0
        labels = label(clab, background=0, connectivity=1)
        if (np.max(labels) == 2) & (np.sum(labels==1)>self.epicure.minsize) & (np.sum(labels==2)>self.epicure.minsize):
            ## get new image with the 2 cells to retrack
            labels = ut.touching_labels(labels, expand=dis+1)
            indmodif = []
            newlabels = []
            for i in range(2):
                imodif = ( (labels==(i+1)) & (cropt==curlabel) )
                val, counts = np.unique( init_cropt[ imodif ], return_counts=True) 
                init_label = val[np.argmax(counts)]
                imodif = np.argwhere(imodif).tolist()
                indmodif = indmodif + imodif
                newlabels = newlabels + np.repeat( init_label, len(imodif) ).tolist()
            
            indmodif = ut.toFullMoviePos( indmodif, bbox, frame )
            
            # remove the boundary between the two updated labels only
            cind_bound = ut.ind_boundaries( labels )
            ind_bound = [ ind for ind in cind_bound if cropt[tuple(ind)]==curlabel ]
            ind_bound = ut.toFullMoviePos( ind_bound, bbox, frame )
            indmodif = np.vstack((indmodif, ind_bound))
            newlabels = newlabels + np.repeat(0, len(ind_bound)).tolist()
            
            self.epicure.change_labels( indmodif, newlabels )
            ## udpate the centroid of the modified labels
            #for clabel in np.unique(newlabels):
            #    if clabel > 0:
            #        self.epicure.update_centroid( clabel, frame )
        else:
            if (retry > 6) :
                if self.epicure.verbose > 0:
                    print("Update failed "+str(np.max(labels)))
                return
            retry = retry + 1
            self.move_in_crop(curlabel, init_cropt, cropt, crop_positions, line, bbox, frame, retry=retry)

    def split_along_line(self, tframe, positions):
        """ Split a label along a line drawn manually """
        bbox = ut.getBBox2DFromPts( positions, extend=0, imshape=self.epicure.imgshape2D )
        bbox = ut.extendBBox2D( bbox, extend_factor=1.25, imshape=self.epicure.imgshape2D )

        segt = self.epicure.seglayer.data[tframe]
        cropt = ut.cropBBox2D( segt, bbox )
        crop_positions = ut.positionsIn2DBBox( positions, bbox )

        # get the value of the cell to split (most frequent label along the line)
        curlabels = []
        prev_pos = None
        for pos in crop_positions:
            if (prev_pos is None) or ((round(pos[0]) != round(prev_pos[0])) and (round(pos[1]) != round(prev_pos[1]) )):
                clab = cropt[round(pos[0]), round(pos[1])]
                curlabels.append(clab)
                prev_pos = pos
                
        curlabel = max(set(curlabels), key=curlabels.count)
        if self.epicure.verbose > 0:
            print("Cell to split: "+str(curlabel))
        if curlabel == 0:
            if self.epicure.verbose > 0:
                print("Refusing to split background")
            return               
                        
        ## crop around selected label
        bbox = ut.getBBox2D(segt, curlabel)
        bbox = ut.extendBBox2D( bbox, extend_factor=1.5, imshape=self.epicure.imgshape2D )
        cropt = ut.cropBBox2D( segt, bbox )
        crop_positions = ut.positionsIn2DBBox( positions, bbox )

        # draw the line only in the cell to split
        line = np.zeros(cropt.shape, dtype="uint8")
        for i, pos in enumerate(crop_positions):
            if cropt[round(pos[0]), round(pos[1])] == curlabel:
                line[round(pos[0]), round(pos[1])] = 1
            if (i > 0):
                prev = (crop_positions[i-1][0], crop_positions[i-1][1])
                cur = (pos[0], pos[1])
                interp_coords = interpolate_coordinates(prev, cur, 1)
                for ic in interp_coords:
                    line[tuple(np.round(ic).astype(int))] = 1
        self.split_in_crop( curlabel, cropt, crop_positions, line, bbox, tframe, retry=0)

    def split_in_crop(self, curlabel, cropt, crop_positions, line, bbox, frame, retry):
        """ Find the split to do in the cropped region """
        dis = retry
        footprint = disk(radius=dis)
        dilline = binary_dilation(line, footprint=footprint)

        # get the two splitted regions and relabel one of them
        clab = np.zeros(cropt.shape, dtype="uint8")
        clab[cropt==curlabel] = 1
        clab[dilline] = 0
        labels = label(clab, background=0, connectivity=1)
        if (np.max(labels) == 2) & (np.sum(labels==1)>self.epicure.minsize) & (np.sum(labels==2)>self.epicure.minsize):
            ## get new image with the 2 cells to retrack
            labels = ut.touching_labels(labels, expand=dis+1)
            curframe = np.zeros( cropt.shape, dtype="uint8" )
            for i in range(2):
                curframe[ (labels==(i+1)) & (cropt==curlabel) ] = i+1
            
            curframe = ut.remove_boundaries(curframe)
            self.propagate_label_change( curframe, [1,2], bbox, frame, [curlabel] )

        else:
            if (retry > 6) :
                if self.epicure.verbose > 0:
                    print("Split failed "+str(np.max(labels)))
                return
            retry = retry + 1
            self.split_in_crop(curlabel, cropt, crop_positions, line, bbox, frame, retry=retry)

    def merge_labels(self, tframe, startlab, endlab, extend_factor=1.25):
        """ Merge the two given labels """
        start_time = ut.start_time()
        segt = self.epicure.seglayer.data[tframe]
        
        ## Crop around labels to work on smaller field of view
        bbox, merged = ut.getBBox2DMerge( segt, startlab, endlab )
        
        ## keep only the region of interest
        bbox = ut.extendBBox2D( bbox, extend_factor, self.epicure.imgshape2D )
        segt_crop = ut.cropBBox2D( segt, bbox )

        ## check that labels can be merged
        touch = ut.checkTouchingLabels( segt_crop, startlab, endlab )
        if not touch:
            ut.show_warning("Labels not touching, I refuse to merge them")
            return

        ## merge the two labels together
        joinlab = ut.cropBBox2D( merged, bbox )
        footprint = disk(radius=2)
        joinlab = endlab * binary_closing(joinlab, footprint)
        
        if self.epicure.verbose > 1:
            ut.show_duration(start_time, "Merged in ")

        ## update and propagate the change
        self.propagate_label_change(joinlab, [endlab], bbox, tframe, [startlab, endlab])
        if self.epicure.verbose > 1:
            ut.show_duration(start_time, "Merged and propagated in ")

    def touching_labels(self, img, lab, olab):
        """ Check if the two labels are neighbors or not """
        flab = find_boundaries(img==lab)
        folab = find_boundaries(img==olab)
        return np.sum(np.logical_and(flab, folab))>0
    
    def swap_labels(self, tframe, lab, olab):
        """ Swap two labels """
        segt = self.epicure.seglayer.data[tframe]
        ## Get the two labels position to swap
        modiflab = np.argwhere(segt==lab).tolist()
        modifolab = np.argwhere(segt==olab).tolist()
        newlabs = np.repeat(olab, len(modiflab)).tolist() + np.repeat(lab, len(modifolab)).tolist()
        ## Change the labels
        ut.setNewLabel( self.epicure.seglayer, modiflab+modifolab, newlabs, add_frame=tframe )
        ## Update the tracks and graph with swap
        self.epicure.swap_labels( lab, olab, tframe )
        self.epicure.seglayer.refresh()


    ######################
    ## Erase border cells
    def remove_border(self):
        """ Remove all cells that touch the border """
        start_time = ut.start_time()
        self.viewer.window._status_bar._toggle_activity_dock(True)
        size = int(self.border_size.text())
        if size == 0:
            for i in progress(range(0, self.epicure.nframes)):
                img = np.copy( self.epicure.seglayer.data[i] )
                resimg = clear_border( img )
                self.epicure.seglayer.data[i] = resimg
                self.epicure.removed_labels( img, resimg, i )
        else:
            maxx = self.epicure.imgshape2D[0] - size - 1
            maxy = self.epicure.imgshape2D[1] - size - 1
            for i in progress(range(0, self.epicure.nframes)):
                frame = self.epicure.seglayer.data[i]
                img = np.copy( frame ) 
                crop_img = img[ size:maxx, size:maxy ]
                crop_img = clear_border( crop_img )
                frame[0:size, :] = 0
                frame[:, 0:size] = 0
                frame[maxx:, :] = 0
                frame[:, maxy:] = 0
                frame[size:maxx, size:maxy] = crop_img
                ## update the tracks after the potential disappearance of some cells
                self.epicure.removed_labels( img, frame, i )
        
        self.viewer.window._status_bar._toggle_activity_dock(False)
        self.epicure.seglayer.refresh()
        if self.epicure.verbose > 0:
            ut.show_duration( start_time, "Border cells removed in ")

               

    def remove_smalls( self ):
        """ Remove all cells smaller than given area (in nb pixels) """
        start_time = ut.start_time()
        self.viewer.window._status_bar._toggle_activity_dock(True)
        for i in progress(range(0, self.epicure.nframes)):
            self.remove_small_cells( np.copy(self.epicure.seglayer.data[i]), i)
        self.viewer.window._status_bar._toggle_activity_dock(False)
        if self.epicure.verbose > 0:
            ut.show_duration( start_time, "Small cells removed in ")

    def remove_small_cells(self, img, frame):
        """ Remove if few the cell is only few pixels """
        #init_labels = set(np.unique(img))
        minarea = int(self.small_size.text())
        props = ut.labels_properties( img )
        resimg = np.copy( img )
        for prop in props:
            if prop.area < minarea:
                (resimg[prop.slice])[prop.image] = 0
        ## update the tracks after the potential disappearance of some cells
        self.epicure.seglayer.data[frame] = resimg
        self.epicure.removed_labels( img, resimg, frame )
    
    def merge_inside_cells( self ):
        """ Merge cell that falls inside another cell with ut """
        start_time = ut.start_time()
        self.viewer.window._status_bar._toggle_activity_dock(True)
        for i in progress(range(0, self.epicure.nframes)):
            self.merge_inside_cell(self.epicure.seglayer.data[i], i)
        self.viewer.window._status_bar._toggle_activity_dock(False)
        if self.epicure.verbose > 0:
            ut.show_duration( start_time, "Inside cells merged in ")

    def merge_inside_cell( self, img, frame ):
        """ Merge cells that fits inside the convex hull of a cell with it """
        graph = ut.connectivity_graph( img, distance=3)
        adj_bg = []
        
        nodes = list(graph.nodes)
        for label in nodes:
            nneighbor = len(graph.adj[label])
            if nneighbor == 1:
                neigh_label = graph.adj[label]
                for lab in neigh_label.keys():
                    nlabel = int( lab )
                # both labels are still present in the current frame
                if nlabel>0 and sum( np.isin( [label, nlabel], self.epicure.seglayer.data[frame] ) ) == 2:
                    self.merge_labels( frame, label, nlabel, 1.05 )
                    if self.epicure.verbose > 0:
                        print( "Merged label "+str(label)+" into label "+str(nlabel)+" at frame "+str(frame) )

    ###############
    ## Shapes functions
    def create_shapelayer( self ):
        """ Create the layer that handle temporary drawings """
        shapes = []
        shap = self.viewer.add_shapes( shapes, name=self.shapelayer_name, ndim=3, blending="additive", opacity=1, edge_width=2, scale=self.viewer.layers["Segmentation"].scale )
        shap.text.visible = False
        shap.visible = False

    ######################################"
    ## Seeds and watershed functions
    def show_hide_seedMapBlock(self):
        self.gSeed.setVisible(not self.gSeed.isVisible())
        if not self.gSeed.isVisible():
            ut.remove_layer(self.viewer, "Seeds")
    
    def create_seedsBlock(self):
        seed_layout = wid.vlayout()
        reset_color = self.epicure.get_resetbtn_color()
        seed_createbtn = wid.add_button( btn="Create seeds layer", btn_func=self.reset_seeds, descr="Create/reset the layer to add seeds", color=reset_color )
        seed_layout.addWidget(seed_createbtn)
        seed_loadbtn = wid.add_button( btn="Load seeds from previous time point", btn_func=self.get_seeds_from_prev, descr="Place seeds in background area where cells are in previous time point" )
        seed_layout.addWidget(seed_loadbtn)
        
        ## choose method and segment from seeds
        gseg, gseg_layout = wid.group_layout( "Seed based segmentation" )
        seed_btn = wid.add_button( btn="Segment cells from seeds", btn_func=self.segment_from_points, descr="Segment new cells from placed seeds" )
        gseg_layout.addWidget(seed_btn)
        method_line, self.seed_method = wid.list_line( label="Method", descr="Seed based segmentation method to segment some cells" )
        self.seed_method.addItem("Intensity-based (watershed)")
        self.seed_method.addItem("Distance-based")
        self.seed_method.addItem("Diffusion-based")
        gseg_layout.addLayout( method_line )
        maxdist, self.max_distance = wid.value_line( label="Max cell radius", default_value="100.0", descr="Max cell radius allowed in new cell creation" )
        gseg_layout.addLayout(maxdist)
        gseg.setLayout(gseg_layout)
        
        seed_layout.addWidget(gseg)
        self.gSeed.setLayout(seed_layout)

    def create_seedlayer(self):
        pts = []
        ## handle change of parameter name in napari versions
        if ut.version_napari_above("0.4.19"):
            self.viewer.add_points( np.array(pts), face_color="blue", size = 7,  border_width=0, name="Seeds", scale=self.viewer.layers["Segmentation"].scale )
        else:
            self.viewer.add_points( np.array(pts), face_color="blue", size = 7,  edge_width=0, name="Seeds", scale=self.viewer.layers["Segmentation"].scale )

    def reset_seeds(self):
        ut.remove_layer(self.viewer, "Seeds")
        self.create_seedlayer()

    def get_seeds_from_prev(self):
        #self.reset_seeds()
        if "Seeds" not in self.viewer.layers:
            self.create_seedlayer()
        tframe = int(self.viewer.cursor.position[0])
        segt = self.epicure.seglayer.data[tframe]
        if tframe > 0:
            pts = self.viewer.layers["Seeds"].data
            segp = self.epicure.seglayer.data[tframe-1]
            props = ut.labels_properties(segp)
            for prop in props:
                cent = prop.centroid
                ## create a seed in the centroid only in empty spaces
                if int(segt[int(cent[0]), int(cent[1])]) == 0:
                    pts = np.append(pts, [[tframe, cent[0], cent[1]]], axis=0)
            self.viewer.layers["Seeds"].data = pts
            self.viewer.layers["Seeds"].refresh()
        
    def end_place_seed(self):
        """ Finish placing seeds mode """
        if not self.seed_active:
            return
        if self.old_mouse_drag is not None:
            self.epicure.seglayer.mouse_drag_callbacks = self.old_mouse_drag
            self.seed_active = False
            ut.show_info("End seed")
        ut.set_active_layer( self.viewer, "Segmentation" )

    def place_seed(self, event_pos):
        """ Add a seed under the cursor """
        tframe = int(self.viewer.cursor.position[0])
        segt = self.epicure.seglayer.data[tframe]
        pts = self.viewer.layers["Seeds"].data
        cent = self.viewer.layers["Seeds"].world_to_data( event_pos )
        ## create a seed in the centroid only in empty spaces
        if int(segt[int(cent[1]), int(cent[2])]) == 0:
            pts = np.append(pts, [[tframe, cent[1], cent[2]]], axis=0)
            self.viewer.layers["Seeds"].data = pts
            self.viewer.layers["Seeds"].refresh()
        ut.set_active_layer( self.viewer, "Segmentation" )


    def segment_from_points(self):
        """ Do cells segmentation from seed points """
        if not "Seeds" in self.viewer.layers:
            ut.show_warning("No seeds placed")
            return
        self.end_place_seed()
        if len(self.viewer.layers["Seeds"].data) <= 0:
            ut.show_warning("No seeds placed")
            return

        ## get crop of the image around seeds
        tframe = ut.current_frame(self.viewer)
        segBB, markers, maskBB, labelBB = self.crop_around_seeds( tframe )
        ## save current labels to compare afterwards
        before_seeding = np.copy(segBB)

        ## segment current seeds from points with selected method
        if self.seed_method.currentText() == "Intensity-based (watershed)":
            self.watershed_from_points( tframe, segBB, markers, maskBB, labelBB )
        if self.seed_method.currentText() == "Distance-based":
            self.distance_from_points( tframe, segBB, markers, maskBB, labelBB )
        if self.seed_method.currentText() == "Diffusion-based":
            self.diffusion_from_points( tframe, segBB, markers, maskBB, labelBB )

        ## finish segmentation: thin to have one pixel boundaries, update all
        skelBB = ut.frame_to_skeleton( segBB, connectivity=1 )
        segBB[ skelBB>0 ] = 0
        self.reset_seeds()
        ## update the list of tracks with the potential new cells
        self.epicure.added_labels_oneframe( tframe, before_seeding, segBB )
        #self.end_place_seed()
        ut.set_active_layer( self.viewer, "Segmentation" )
        self.epicure.seglayer.refresh()

    def crop_around_seeds( self, tframe ):
        """ Get cropped image around the seeds """
        ## crop around the seeds, with a margin
        seeds = self.viewer.layers["Seeds"].data
        segt = self.epicure.seglayer.data[tframe]
        extend = int(float(self.max_distance.text())*1.1)
        labelBB = ut.getBBox2DFromPts( seeds, extend, segt.shape )
        segBB = ut.cropBBox2D(segt, labelBB)
        ## mask where there are cells
        maskBB = np.copy(segBB)
        maskBB = 1*(maskBB==0)
        maskBB = np.uint8(maskBB)
        ## fill the borders
        maskBB = binary_erosion(maskBB, footprint=self.disk_one)
        ## place labels in the seed positions
        pos = ut.positionsIn2DBBox( seeds, labelBB )
        markers = np.zeros(maskBB.shape, dtype="int32")
        freelabs = self.epicure.get_free_labels( len(pos) )
        for freelab, p in zip(freelabs, pos):
            markers[p] = freelab
        return segBB, markers, maskBB, labelBB
    
    def diffusion_from_points(self, tframe, segBB, markers, maskBB, labelBB):
        """ Segment from seeds with a diffusion based method (gradient intensity slows it) """
        movt = self.viewer.layers["Movie"].data[tframe]
        imgBB = ut.cropBBox2D(movt, labelBB)
        markers[maskBB==0] = -1 ## block filled area 
        ## fill from seeds with diffusion method
        splitted = random_walker( imgBB, labels=markers, beta=700, tol=0.01 )
        new_labels = list(np.unique(markers))
        new_labels.remove(-1)
        new_labels.remove(0)
        i = 0
        lablist = set( splitted.flatten() )
        #print(lablist)
        #print(new_labels)
        for lab in lablist:
            if lab > 0:
                mask = (splitted == lab)
                labels_mask = label(mask)                       
                ## keep only biggest region if the label is splitted
                regions = ut.labels_properties(labels_mask)
                if len(regions) > 2:
                    regions.sort(key=lambda x: x.area, reverse=True)
                    if len(regions) > 1:
                        for rg in regions[1:]:
                            splitted[rg.coords[:,0], rg.coords[:,1]] = 0
                splitted[splitted==lab] = new_labels[i]
                i = i + 1
        segBB[(maskBB>0)*(splitted>0)] = splitted[(maskBB>0)*(splitted>0)]
        return segBB

    def watershed_from_points(self, tframe, segBB, markers, maskBB, labelBB):
        """ Performs watershed from the seed points """
        movt = self.viewer.layers["Movie"].data[tframe] 
        imgBB = ut.cropBBox2D(movt, labelBB)
        splitted = watershed( imgBB, markers=markers, mask=maskBB )
        segBB[splitted>0] = splitted[splitted>0]
        return segBB
    
    def distance_from_points(self, tframe, segBB, markers, maskBB, labelBB):
        """ Segment cells from seed points with Voronoi method """
        # iteratif to block when meet other fixed labels 
        maxdist = float(self.max_distance.text())
        dist = 0
        while dist <= maxdist:
            markers = ut.touching_labels( markers, expand=1 )
            markers[maskBB==0] = 0
            dist = dist + 1
        segBB[(maskBB>0) * (markers>0)] = markers[(maskBB>0) * (markers>0)]
        return segBB
        

    ######################################
    ## Cleaning options

    def create_cleaningBlock(self):
        """ GUI for cleaning segmentation """
        clean_layout = wid.vlayout()
        ## cells on border
        border_line, self.border_size = wid.button_parameter_line( btn="Remove border cells", btn_func=self.remove_border, value="1", descr_btn="Remove all cell at a distance <= value (in pixels)", descr_value="Distance of the cells to be removed (in pixels)" )
        clean_layout.addLayout(border_line)
        
        ## too small cells
        small_line, self.small_size = wid.button_parameter_line( btn="Remove mini cells", btn_func=self.remove_smalls, value="4", descr_btn="Remove all cells smaller than given value (in pixels^2)", descr_value="Minimal cell area (in pixels^2)" )
        clean_layout.addLayout(small_line)

        ## Cell inside another cell
        inside_btn = wid.add_button( btn="Cell inside another: merge", btn_func=self.merge_inside_cells, descr="Merge all small cells fully contained inside another cell to this cell" )
        clean_layout.addWidget(inside_btn)

        ## sanity check
        sanity_btn = wid.add_button( btn="Sanity check", btn_func=self.sanity_check, descr="Check that labels and tracks are consistent with EpiCure restrictions, and try to fix some errors" )
        clean_layout.addWidget(sanity_btn)

        ## reset labels
        reset_color = self.epicure.get_resetbtn_color()
        reset_btn = wid.add_button( btn="Reset all", btn_func=self.reset_all, descr="Reset all tracks, groups, suspects..", color=reset_color )
        clean_layout.addWidget(reset_btn)

        self.gCleaned.setLayout(clean_layout)

    ####################################
    ## Sanity check/correction options
    def sanity_check(self):
        """ Check if everything looks okayish, in case some bug or weird editions broke things """
        self.viewer.window._status_bar._toggle_activity_dock(True)
        progress_bar = progress(total=6)
        progress_bar.set_description("Sanity check:")
        progress_bar.update(0)
        ## check layers presence
        ut.show_info("Check and reopen if necessary EpiCure layers")
        self.epicure.check_layers()
        ## check that each label is unique
        progress_bar.update(1)
        progress_bar.set_description("Sanity check: label unicity")
        label_list = np.unique(self.epicure.seglayer.data)
        if self.epicure.verbose > 0:
            print("Checking label unicity...")
        self.check_unique_labels( label_list, progress_bar )
        ## check and update if necessary tracks 
        progress_bar.update(2)
        if self.epicure.forbid_gaps:
            progress_bar.set_description("Sanity check: track gaps")
            ut.show_info("Check if some tracks contain gaps")
            gaped = self.epicure.handle_gaps( track_list=None )
        ## check that labels and tracks correspond
        progress_bar.set_description("Sanity check: label-track")
        progress_bar.update(3)
        if self.epicure.verbose > 0:
            print("Checking labels-tracks correspondance...")
        track_list = self.epicure.tracking.get_track_list()
        untracked = list(set(label_list) - set(track_list))
        if 0 in untracked:
            untracked.remove(0)
        if len(untracked) > 0:
            ut.show_warning("! Labels "+str(untracked)+" not in Tracks -- Adding it now")
            for untrack in untracked:
                self.epicure.add_one_label_to_track( untrack )
        
        ## update label list with changes that might have been done
        label_list = np.unique(self.epicure.seglayer.data)
        track_list = self.epicure.tracking.get_track_list()
        ## check if all tracks have associated labels in the image
        phantom_tracks = list(set(track_list) - set(label_list))
        if len(phantom_tracks) > 0:
            print("! Phantom tracks "+str(phantom_tracks)+" found")
            self.epicure.delete_tracks(phantom_tracks)
            print("-> Phantom tracks deleted from Tracks")
        
        ## checking events
        progress_bar.set_description("Sanity check: extrusions")
        progress_bar.update(5)
        if self.epicure.verbose > 0:
            print("Checking extrusion = end of track...")
        self.epicure.check_extrusions_sanity()
        
        ## finished
        if self.epicure.verbose > 0:
            print("Checking finished")
        progress_bar.close()
        self.viewer.window._status_bar._toggle_activity_dock(False)

    def check_unique_labels(self, label_list, progress_bar):
        """ Check that all labels are contiguous and not present several times (only by frame) """
        found = 0
        s = generate_binary_structure(2,2)
        pbtmp = progress(total=len(label_list), desc="Check labels", nest_under=progress_bar)
        for i, lab in enumerate(label_list):
            pbtmp.update(i)
            if lab > 0:
                for frame in self.epicure.seglayer.data:
                    if lab in frame:
                        labs, num_objects = ndlabel(binary_dilation(frame==lab, footprint=s), structure=s)
                        if num_objects > 1:
                            ut.show_warning("! Problem, label "+str(lab)+" found several times")
                            found = found + 1
                            continue
        pbtmp.close()
        if found <= 0:
            ut.show_info("Labels unicity ok")

    ###############
    ## Resetting

    def reset_all( self ):
        """ Reset labels through skeletonization, reset tracks, suspects, groups """
        if self.epicure.verbose > 0:
            ut.show_info( "Resetting everything ")
        self.viewer.window._status_bar._toggle_activity_dock(True)
        progress_bar = progress(total=5)
        ## get skeleton and relabel (ensure label unicity)
        progress_bar.update(1)
        progress_bar.set_description("Reset: relabel")
        self.epicure.reset_data()
        self.epicure.tracking.reset()
        self.epicure.reset_labels()
        progress_bar.update(2)
        progress_bar.set_description("Reset: reinit tracks")
        self.epicure.tracked = 0
        self.epicure.load_tracks(progress_bar)
        if self.epicure.verbose > 0:
            print("Resetting done")
        progress_bar.close()
        self.viewer.window._status_bar._toggle_activity_dock(False)



    ######################################
    ## Selection options

    def create_selectBlock(self):
        """ GUI for handling selection with shapes """
        select_layout = wid.vlayout()
        ## create/select the ROI
        draw_btn = wid.add_button( btn="Draw/Select ROI", btn_func=self.draw_shape, descr="Draw or select a ROI to apply region action on" )
        select_layout.addWidget(draw_btn)
        remove_sel_btn = wid.add_button( btn="Remove cells inside ROI", btn_func=self.remove_cells_inside, descr="Remove all cells inside the selected/first ROI" )
        select_layout.addWidget(remove_sel_btn)
        remove_line, self.keep_new_cells = wid.button_check_line( btn="Remove cells outside ROI", btn_func=self.remove_cells_outside, check="Keep new cells", checked=True, checkfunc=None, descr_btn="Remove all cells outside the current ROI", descr_check="Keep new cells tah appear in the ROI in later frames" )
        select_layout.addLayout(remove_line)

        self.gSelect.setLayout(select_layout)

    def draw_shape(self):
        """ Draw/select a shape in the Shapes layer """
        if self.shapelayer_name not in self.viewer.layers:
            self.create_shapelayer()
        ut.set_active_layer(self.viewer, self.shapelayer_name)
        lay = self.viewer.layers[self.shapelayer_name]
        lay.visible = True
        lay.opacity = 0.5

    def get_selection(self):
        """ Get the active (or first) selection """
        if self.shapelayer_name not in self.viewer.layers:
            return None
        lay = self.viewer.layers[self.shapelayer_name]
        selected = lay.selected_data
        if len(selected) == 0:
            if len(lay.shape_type) == 1:
                if self.epicure.verbose > 1:
                    print("No shape selected, use the only one present")
                lay.selected_data.add(0)
                selected = lay.selected_data
            else:
                ut.show_warning("No shape selected, do nothing")
                return None
        return lay.data[list(selected)[0]] 

    def get_labels_inside(self):
        """ Get the list of labels inside the current ROI """
        current_shape = self.get_selection()
        if current_shape is None:
            return None
        self.current_bbox = ut.getBBox2DFromPts(current_shape, 30, self.epicure.imgshape2D)
        self.current_cropshape = ut.positionsIn2DBBox(current_shape, self.current_bbox )
        tframe = ut.current_frame(self.viewer)
        segt = self.epicure.seglayer.data[tframe]
        croped = ut.cropBBox2D(segt, self.current_bbox)
        labprops = ut.labels_properties(croped)
        inside = points_in_poly( [lab.centroid for lab in labprops], self.current_cropshape )
        toedit = [lab.label for i, lab in enumerate(labprops) if inside[i] ]
        return toedit

    def remove_cells_outside(self):
        """ Remove all labels centroids outside the selected ROI """
        tokeep = self.get_labels_inside()
        if self.keep_new_cells.isChecked():
            tframe = ut.current_frame(self.viewer)
            segt = self.epicure.seglayer.data[tframe]
            toremove = set(np.unique(segt).flatten()) - set(tokeep)
            self.epicure.remove_labels(list(toremove))
        else:
            self.epicure.keep_labels(tokeep)
        lay = self.viewer.layers[self.shapelayer_name]
        lay.remove_selected()
        self.epicure.finish_update()

    def remove_cells_inside(self):
        """ Remove all labels centroids inside the selected ROI """
        toremove = self.get_labels_inside()
        self.epicure.remove_labels(toremove)
        lay = self.viewer.layers[self.shapelayer_name]
        lay.remove_selected()
        self.epicure.finish_update()

    def lock_cells_inside(self):
        """ Check all cells inside the selected ROI into current group """
        tocheck = self.get_labels_inside()
        for lab in tocheck:
            self.check_label(lab)
        if self.epicure.verbose > 0:
            print(str(len(tocheck))+" cells checked in group "+str(self.check_group.text()))
        lay = self.viewer.layers[self.shapelayer_name]
        lay.remove_selected()
        self.epicure.finish_update()

    def group_classify_intensity( self ):
        """ Calls the interface to classify cells by intensity """
        self.classif.update()
        self.classif.show()
    
    def group_classify_event( self ):
        """ Calls the interface to classify cells by event interaction """
        self.classif_event.update()
        self.classif_event.show()

    def group_event_cells( self, event_type ):
        """ Classify the cells that finished with the selected event into the event group """
        events = self.epicure.inspecting.get_events_from_type( event_type )
        if len( events ) > 0:
            tids = []
            for evt_sid in events:
                pos, label = self.epicure.inspecting.get_event_infos( evt_sid )
                if label not in tids:
                    tids.append(label)
            group_name = "Cells_"+event_type
            if event_type == "extrusion":
                group_name = "Extruding"
            if event_type == "division":    
                group_name = "Dividing"
            self.group_choice.setCurrentText(group_name)
            self.epicure.reset_group( group_name ) 
            self.redraw_clear_group( group_name )
            self.group_labels( tids )


    def group_positive_cells( self, layer_name, meth, min_frame, max_frame, threshold ):
        """ Classify the cells with mean intensity in the given frame range above threshold into the current group """
        if self.group_choice.currentText() == "":
            ut.show_warning("Write a group name before")
            return
        layer = self.viewer.layers[layer_name]
        frames = np.arange(min_frame, max_frame+1)
        if (min_frame == 0) and (max_frame == self.epicure.nframes-1):
            frames = None
        tracks, mean_int = self.epicure.tracking.measure_intensity_features( "intensity_"+meth, intimg=layer.data, frames=frames )
        tids = tracks[ mean_int > threshold ]
        self.redraw_clear_group( group=None )
        self.group_labels( tids )

    def group_cells_inside(self):
        """ Put all cells inside the selected ROI into current group """
        if self.group_choice.currentText() == "":
            ut.show_warning("Write a group name before")
            return
        tocheck = self.get_labels_inside()
        if tocheck is None:
            if self.epicure.verbose > 0:
                print("No cell to add to group")
            return
        self.group_labels( tocheck )
        if self.epicure.verbose > 0:
            print(str(len(tocheck))+" cells assigend to group "+str(self.group_choice.currentText()))
        lay = self.viewer.layers[self.shapelayer_name]
        lay.remove_selected()
        self.epicure.finish_update()


    ######################################
    ## Group cells functions
    def create_groupCellsBlock(self):
        """ Create subpanel of Cell group options """
        group_layout = wid.vlayout()
        groupgr, self.group_choice = wid.list_line( label="Group name", descr="Choose/Set the current group name" )
        group_layout.addLayout(groupgr)
        self.group_choice.setEditable(True)

        self.group_show = wid.add_check( check="Show groups", checked=False, check_func=self.see_groups, descr="Add a layer with the cells colored by group" )
        group_layout.addWidget(self.group_show)

        reset_line, self.reset_list = wid.button_list( btn="Reset group", func=self.reset_group, descr="Remove chosen group (or all) and cell assignation to this group" )
        group_layout.addLayout( reset_line )
        self.update_group_lists()
        group_sel_btn = wid.add_button( btn="Cells inside ROI to group", btn_func=self.group_cells_inside, descr="Add all cells inside ROI to the current group" )
        group_layout.addWidget(group_sel_btn)

        ## add button for intensity classifier interface
        group_class_btn = wid.add_button( btn="Group from track intensity..", btn_func=self.group_classify_intensity, descr="Open interface to group cells based on their mean intensity" )
        group_layout.addWidget( group_class_btn )
        
        ## add button for events classifier interface
        group_event_btn = wid.add_button( btn="Group from events..", btn_func=self.group_classify_event, descr="Open interface to group cells according to if they are related to an event (dividing cell, extruding cell..)" )
        group_layout.addWidget( group_event_btn )

        self.gGroup.setLayout(group_layout)

    def load_checked(self):
        cfile = self.get_filename("_checked.txt")
        with open(cfile) as infile:
            labels = infile.read().split(";")
        for lab in labels:
            self.check_load_label(lab)
        ut.show_info("Checked cells loaded")

    def reset_group( self ):
        gr = self.reset_list.currentText()
        if gr != "All":
            self.redraw_clear_group( gr )
        self.epicure.reset_group( gr )
        if gr == "All":
            self.see_groups()
    
    def update_group_choice( self, group ):
        """ Check if group has been added in the list choices of group """
        if self.group_choice.findText( group ) < 0:
            ## not added yet. If user is typing the name and did not press enter, it can be still in edition mode, so not added
            self.group_choice.addItem( group )
    
    def update_group_lists( self ):
        """ Update list of groups for reset button """
        curchoice = self.group_choice.currentText()
        curreset = self.reset_list.currentText()
        self.group_choice.clear()
        self.reset_list.clear()
        self.reset_list.addItem("All")
        for group in self.epicure.groups.keys():
            self.update_group_choice( group )
            self.reset_list.addItem( group )
        self.reset_list.setCurrentText("All")
        if self.reset_list.findText( curreset ) >= 0:
            self.reset_list.setCurrentText(curreset)
        if self.group_choice.findText( curchoice ) >= 0:
            self.group_choice.setCurrentText( curchoice )

    def save_groups(self):
        groupfile = self.get_filename("_groups.txt")
        with open(groupfile, 'w') as out:
            out.write(";".join(group.write_group() for group in self.epicure.groups))
        ut.show_info("Cell groups saved in "+groupfile)

    def see_groups(self):
        if self.group_show.isChecked():
            ut.remove_layer(self.viewer, self.grouplayer_name)
            grouped = self.epicure.draw_groups()
            self.viewer.add_labels(grouped, name=self.grouplayer_name, opacity=0.75, blending="additive", scale=self.viewer.layers["Segmentation"].scale)
            ut.set_active_layer(self.viewer, "Segmentation")
        else:
            ut.remove_layer(self.viewer, self.grouplayer_name)
            ut.set_active_layer(self.viewer, "Segmentation")
    
    def group_labels( self, labels ):
        """ Add label(s) to group """
        if self.group_choice.currentText() == "":
            ut.show_warning("Write group name before")
            return
        group = self.group_choice.currentText()
        self.group_ingroup( labels, group )
       
    def check_label(self, label):
        """ Mark label as checked """
        group = self.check_group.text()
        self.check_ingroup(label, group)

        
    def group_ingroup(self, labels, group):
        """ Add the given label to chosen group """
        self.epicure.cells_ingroup( labels, group )
        if self.grouplayer_name in self.viewer.layers:
            self.redraw_label_group( labels, group )
       
    def check_load_label(self, labelstr):
        """ Read the label to check from file """
        res = labelstr.split("-")
        cellgroup = res[0]
        celllabel = int(res[1])
        self.check_ingroup(celllabel, cellgroup)
        
    def add_cell_to_group(self, event):
        """ Add cell under click to the current group """
        label = ut.getCellValue( self.epicure.seglayer, event ) 
        self.group_labels( [label] )

    def remove_cell_group(self, event):
        """ Remove the cell from the group it's in if any """
        label = ut.getCellValue( self.epicure.seglayer, event ) 
        self.epicure.cell_removegroup( label )
        if self.grouplayer_name in self.viewer.layers:
            self.redraw_label_group( [label], 0 )

    def redraw_clear_group( self, group=None ):
        """ Clear all the cells from group in the current group layer """
        if group is None:
            if self.group_choice.currentText() == "":
                ut.show_warning("Write group name before")
                return
            group = self.group_choice.currentText()
        if self.grouplayer_name in self.viewer.layers:
            lay = self.viewer.layers[self.grouplayer_name]
            igroup = self.epicure.get_group_index(group) + 1
            if igroup == 0:
                ## the group was not present, igroup is -1
                return
            lay.data[lay.data == igroup] = 0
            lay.refresh()
            ut.set_active_layer(self.viewer, "Segmentation")

    def redraw_label_group(self, labels, group):
        """ Update the Group layer for label """
        lay = self.viewer.layers[self.grouplayer_name]
        if group == 0:
            lay.data[ np.isin( self.epicure.seg, labels ) ] = 0
        else:
            igroup = self.epicure.get_group_index(group) + 1
            lay.data[ np.isin( self.epicure.seg, labels)  ] = igroup
        lay.refresh()

    ######### overlay message
    def add_overlay_message(self):
        text = self.epicure.text + "\n"
        ut.setOverlayText(self.viewer, text, size=10)

    ################## Events editing functions
    def add_extrusion( self, labela, frame ):
        """ Add an extrusion event, given the label and frame """

        if (frame != self.epicure.tracking.get_last_frame( labela )):
            if self.epicure.verbose > 0:
                print("Clicked label is not the last of the track, don't add extrusion")
                return

        ## add extrusion to event list (if active)
        self.epicure.inspecting.add_extrusion( labela, frame )

    def add_division( self, labela, labelb, frame ):
        """ Add a division event, given the labels of the two daughter cells """
        if frame == 0:
            if self.epicure.verbose > 0:
                print("Cannot define a division before the first frame")
            return False

        if (frame != self.epicure.tracking.get_first_frame( labela )) or (frame != self.epicure.tracking.get_first_frame(labelb) ):
            if self.epicure.verbose > 0:
                print("One daughter track is not starting at current frame, don't add division")
                return False

        ## merge the two labels to find their parent
        bbox, merge = ut.getBBox2DMerge( self.epicure.seglayer.data[frame], labela, labelb )
        twoframes = ut.crop_twoframes( self.epicure.seglayer.data, bbox, frame )
        crop_merge = ut.cropBBox2D( merge, bbox )
        twoframes[1] = crop_merge # merge of the labels and 0 outside
            
        ## keep only parent labels that stop at the previous frame
        twoframes = self.keep_orphans(twoframes, frame)
        ## do mini-tracking to assign most likely parent
        parent = self.get_parents( twoframes, [1] )
        if self.epicure.verbose > 0:
            print( "Found parent "+str(parent[0])+" to clicked cells "+str(labela)+" and "+str(labelb) )
        ## add division to graph
        if parent is not None and parent[0] is not None:
            self.epicure.tracking.add_division( labela, labelb, parent[0] )
            ## add division to event list (if active)
            self.epicure.inspecting.add_division( labela, labelb, parent[0], frame )
            return True
        return False
            
    ################## Track editing functions
    def key_tracking_binding(self):
        """ active key bindings for tracking options """
        self.epicure.overtext["trackedit"] = "---- Track editing ---- \n"
        strack = self.epicure.shortcuts["Tracks"]
        etrack = self.epicure.shortcuts["Events"]
        self.epicure.overtext["trackedit"] += ut.print_shortcuts( strack )
        
        @self.epicure.seglayer.mouse_drag_callbacks.append
        def manual_add_extrusion(layer, event):
            ### add an event of an extrusion under the click
            if ut.shortcut_click_match( etrack["add extrusion"], event ):
                # get the start and last labels
                labela = self.epicure.seglayer.get_value(position=event.position, view_direction = event.view_direction, dims_displayed=event.dims_displayed, world=True)
                tframe = int(event.position[0])
                    
                if labela == 0:
                    if self.epicure.verbose > 0:
                        print("Clicked position is not a cell, do nothing")
                    return
                self.add_extrusion( labela, tframe )
        
        @self.epicure.seglayer.mouse_drag_callbacks.append
        def manual_add_division(layer, event):
            ### add an event of a division, selecting the two daughter cells
            if ut.shortcut_click_match( etrack["add division"], event ):
                # get the start and last labels
                labela = self.epicure.seglayer.get_value(position=event.position, view_direction = event.view_direction, dims_displayed=event.dims_displayed, world=True)
                start_pos = event.position
                yield
                while event.type == 'mouse_move':
                    yield
                labelb = self.epicure.seglayer.get_value(position=event.position, view_direction = event.view_direction, dims_displayed=event.dims_displayed, world=True)
                end_pos = event.position
                tframe = int(event.position[0])
                    
                if labela == 0 or labelb == 0:
                    if self.epicure.verbose > 0:
                        print("One position is not a cell, do nothing")
                    return
                self.add_division( labela, labelb, tframe )
        
        @self.epicure.seglayer.bind_key( strack["lineage color"]["key"], overwrite=True )
        def color_tracks_lineage(seglayer):
            if self.tracklayer_name in self.viewer.layers:
                self.epicure.tracking.color_tracks_by_lineage()
        
        @self.epicure.seglayer.bind_key( strack["show"]["key"], overwrite=True )
        def see_tracks(seglayer):
            if self.tracklayer_name in self.viewer.layers:
                tlayer = self.viewer.layers[self.tracklayer_name]
                tlayer.visible = not tlayer.visible

        @self.epicure.seglayer.bind_key( strack["mode"]["key"], overwrite=True)
        def edit_track(layer):
            self.label_tr = None 
            self.start_label = None
            self.interp_labela = None
            self.interp_labelb = None
            ut.show_info("Tracks editing mode")
            self.old_mouse_drag, self.old_key_map = ut.clear_bindings(self.epicure.seglayer)

            @self.epicure.seglayer.mouse_drag_callbacks.append
            def click(layer, event):
                """ Edit tracking """
                if event.type == "mouse_press":
                  
                    """ Merge two tracks, spatially or temporally: left click, select the first label """
                    if ut.shortcut_click_match( strack["merge first"], event ):
                        self.start_label = self.epicure.seglayer.get_value(position=event.position, view_direction = event.view_direction, dims_displayed=event.dims_displayed, world=True)
                        self.start_pos = event.position
                        # move one frame after for next cell to link
                        #ut.set_frame( self.epicure.viewer, event.position[0]+1 )
                        return
                    """ Merge two tracks, spatially or temporally: right click, select the second label """
                    if ut.shortcut_click_match( strack["merge second"], event ):
                        if self.start_label is None:
                            if self.epicure.verbose > 0:
                                print("No left click done before right click, don't merge anything")
                            return
                        end_label = self.epicure.seglayer.get_value(position=event.position, view_direction = event.view_direction, dims_displayed=event.dims_displayed, world=True)
                        end_pos = event.position
                        if self.epicure.verbose > 0:
                            print("Merging track "+str(self.start_label)+" with track "+str(end_label))
                        
                        if self.start_label is None or self.start_label == 0 or end_label == 0:
                            if self.epicure.verbose > 0:
                                print("One position is not a cell, do nothing")
                            return
                        ## ready, merge
                        self.merge_tracks( self.start_label, self.start_pos, end_label, end_pos )
                        self.end_track_edit()
                        return

                    ### Split the track in 2: new label for the next frames 
                    if ut.shortcut_click_match( strack["split track"], event ):
                        start_frame = int(event.position[0])
                        label = ut.getCellValue(self.epicure.seglayer, event) 
                        self.epicure.split_track( label, start_frame )
                        self.end_track_edit()
                        return
                        
                    ### Swap the two track from the current frame 
                    if ut.shortcut_click_match( strack["swap"], event ):
                        start_frame = int(event.position[0])
                        label = ut.getCellValue(self.epicure.seglayer, event) 
                        yield
                        while event.type == 'mouse_move':
                            yield
                        end_label = self.epicure.seglayer.get_value(position=event.position, view_direction = event.view_direction, dims_displayed=event.dims_displayed, world=True)                           
                            
                        if label == 0 or end_label == 0:
                            if self.epicure.verbose > 0:
                                print("One position is not a cell, do nothing")
                            return

                        self.epicure.swap_tracks( label, end_label, start_frame )
                            
                        if self.epicure.verbose > 0:
                            ut.show_info("Swapped track "+str(label)+" with track "+str(end_label)+" from frame "+str(start_frame))
                        self.end_track_edit()
                        return

                    # Manual tracking: get a new label and spread it to clicked cells on next frames
                    if ut.shortcut_click_match( strack["start manual"], event ):
                        zpos = int(event.position[0])
                        if self.label_tr is None:
                            ## first click: get the track label
                            self.label_tr = ut.getCellValue(self.epicure.seglayer, event) 
                        else:
                            old_label = ut.setCellValue(self.epicure.seglayer, self.epicure.seglayer, event, self.label_tr, layer_frame=zpos, label_frame=zpos)
                            self.epicure.tracking.remove_one_frame( old_label, zpos, handle_gaps=self.epicure.forbid_gaps )
                            self.epicure.add_label( [self.label_tr], zpos )
                        ## advance to next frame, ready for a click
                        self.viewer.dims.set_point(0, zpos+1)
                        ## if reach the end, stops here for this track
                        if (zpos+1) >= self.epicure.seglayer.data.shape[0]:
                            self.end_track_edit()
                        return
                    
                    ## Finish manual tracking
                    if ut.shortcut_click_match( strack["end manual"], event ):
                        self.end_track_edit()
                        return
                   
                    ## Interpolate between two labels: get first label
                    if ut.shortcut_click_match( strack["interpolate first"], event ):
                        ## left click, first cell
                        self.interp_labela = ut.getCellValue(self.epicure.seglayer, event) 
                        self.interp_framea = int(event.position[0])
                        return
                    
                    ## Interpolate between two labels: get second label and interpolate
                    if ut.shortcut_click_match( strack["interpolate second"], event ):
                        ## right click, second cell
                        labelb = ut.getCellValue(self.epicure.seglayer, event) 
                        interp_frameb = int(event.position[0])
                        if self.interp_labela is not None:
                            if abs(self.interp_framea - interp_frameb) <= 1:
                                print("No frames to interpolate, exit")
                                self.end_track_edit()
                                return
                            if self.interp_framea < interp_frameb:
                                self.interpolate_labels(self.interp_labela, self.interp_framea, labelb, interp_frameb)
                            else:
                                self.interpolate_labels(labelb, interp_frameb, self.interp_labela, self.interp_framea )
                            self.end_track_edit()
                            return
                        else:
                            print("No cell selected with left click before. Exit mode")
                            self.end_track_edit()
                            return
                        
                    ## Delete all the labels of the track until its end
                    if ut.shortcut_click_match( strack["delete"], event ):
                        tframe = int(event.position[0])
                        label = ut.getCellValue(self.epicure.seglayer, event)
                        if label > 0:
                            self.epicure.replace_label( label, 0, tframe )
                            if self.epicure.verbose > 0:
                                print("Track "+str(label)+" deleted from frame "+str(tframe))
                        self.end_track_edit()
                        return

                ## A right click or other click stops it
                self.end_track_edit()

            #@self.epicure.seglayer.mouse_double_click_callbacks.append
            #def double_click(layer, event):
            #    """ Edit tracking : double click options """
            #    if event.type == "mouse_double_click":      
                    
        
            @self.epicure.seglayer.bind_key( strack["mode"]["key"], overwrite=True )
            def end_edit_track(layer):
                self.end_track_edit()

    def end_track_edit(self):
        self.start_label = None
        self.interp_labela = None
        self.interp_labelb = None
        ut.reactive_bindings( self.epicure.seglayer, self.old_mouse_drag, self.old_key_map )
        ut.show_info("End track edit mode")

    def merge_tracks(self, labela, posa, labelb, posb):
        """ 
            Merge track with label a with track of label b, temporally or spatially 
        """
        if labela == labelb:
            if self.epicure.verbose > 0:
                print("Already the same track" )
                return
        if int(posb[0]) == int(posa[0]):
            self.tracks_spatial_merging( labela, posa, labelb )
        else:
            self.tracks_temporal_merging( labela, posa, labelb, posb )

    def tracks_spatial_merging( self, labela, posa, labelb ):
        """ Merge spatially two tracks: labels have to be touching all along the common frames """
        start_time = ut.start_time()
        ## get last common frame
        lasta = self.epicure.tracking.get_last_frame( labela )
        lastb = self.epicure.tracking.get_last_frame( labelb )
        lastcommon = min(lasta, lastb)

        ## if longer than the last common, split the label(s) that continue
        if lasta > lastcommon:
            if self.epicure.tracking.get_first_frame( labela ) < int(posa[0]):
                self.epicure.split_track( labela, lastcommon+1 )
        if lastb > lastcommon:
            if self.epicure.tracking.get_first_frame( labelb ) < int(posa[0]):
                self.epicure.split_track( labelb, lastcommon+1 )

        ## Looks, ok, create a new track and merge the two tracks in it
        new_label = self.epicure.get_free_label()
        new_labels = []
        ind_tomodif = None
        footprint = disk(radius=3)
        for frame in range( int(posa[0]), lastcommon+1 ):
            bbox, merged = ut.getBBox2DMerge( self.epicure.seg[frame], labela, labelb )
            bbox = ut.extendBBox2D( bbox, 1.05, self.epicure.imgshape2D )
            
            ## check if labels are touching at each frame
            segt_crop = ut.cropBBox2D( self.epicure.seg[frame], bbox )
            touched = ut.checkTouchingLabels( segt_crop, labela, labelb )
            if not touched:
                print("Labels "+str(labela)+" and "+str(labelb)+" are not always touching. Refusing to merge them")
                return 
            
            ## merge the two labels together
            joinlab = ut.cropBBox2D( merged, bbox )
            joinlab = new_label * binary_closing(joinlab, footprint)
           
            ## get the index and new values to change
            indmodif = ut.ind_boundaries( joinlab )
            #indmodif = ut.toFullMoviePos( indmodif, bbox, frame )
            new_labels = new_labels + [0]*len(indmodif)
            curmodif = np.transpose( np.nonzero( joinlab == new_label ) )
            new_labels = new_labels + [new_label]*len(curmodif)
            indmodif = np.vstack((indmodif, curmodif))
            indmodif = ut.toFullMoviePos( indmodif, bbox, frame )
            if ind_tomodif is None:
                ind_tomodif = indmodif
            else:
                ind_tomodif = np.vstack((ind_tomodif, indmodif))
            #ind_tomodif = np.vstack((ind_tomodif, curmodif))
        
        ## update the labels and the tracks
        self.epicure.change_labels_frommerge( ind_tomodif, new_labels, remove_labels=[labela, labelb] )
        if self.epicure.verbose > 0:
            ut.show_info("Merged spatially "+str(labela)+" with "+str(labelb)+" from frame "+str(int(posa[0]))+" to frame "+str(lastcommon)+"\n New track label is "+str(new_label))
        if self.epicure.verbose > 1:
            ut.show_duration(start_time, "Merging spatially tracks in ")


    def tracks_temporal_merging( self, labela, posa, labelb, posb ):
        """ 
        Merge track with label a with track of label b if consecutives frames. 
        It does not check if label are close in distance, assume it is.
        """

        if self.epicure.forbid_gaps:
            if abs(int(posb[0]) - int(posa[0])) != 1:
                if self.epicure.verbose > 0:
                    print("Frames to merge are not consecutives, refused")
                return

        ## If frame b is before frame a, swap so that a is first 
        if posa[0] > posb[0]:
            posc = np.copy(posa)
            posa = posb
            posb = posc
            labelc = labela
            labela = labelb
            labelb = labelc

        ## Check that posa is last frame of label a and pos b first frame of label b
        if int(posa[0]) != self.epicure.tracking.get_last_frame( labela ):
            if self.epicure.verbose > 0:
                print("Clicked label "+str(labela)+" at frame "+str(posa[0])+" was not the last frame of the track -> splitting it")
            self.epicure.split_track( labela, int(posa[0])+1 )

        if posb[0] != self.epicure.tracking.get_first_frame( labelb ):
            if self.epicure.verbose > 0:
                print("Clicked label "+str(labelb)+" at frame "+str(posb[0])+" is not the first frame of the track -> splitting it")
            labelb = self.epicure.split_track( labelb, int(posb[0]) )

        self.epicure.replace_label( labelb, labela, int(posb[0]) )
        

    def get_parents(self, twoframes, labels):
        """ Get parent of all labels """
        return self.epicure.tracking.find_parents( labels, twoframes )
    
    def get_position_label_2D(self, img, labels, parent_labels):
        """ Get position of each label to update with parent label """
        indmodif = None
        new_labels = []
        ## get possible free labels, to be sure that it will not take the same ones
        free_labels = self.epicure.get_free_labels(len(labels))
        for i, lab in enumerate(labels):
            parent_label = parent_labels[i]
            if parent_label is None:
                parent_label = free_labels[i]
                parent_labels[i] = parent_label
            curmodif = np.argwhere( img==lab )
            if indmodif is None:
                indmodif = curmodif
            else:
                indmodif = np.vstack((indmodif, curmodif))
            new_labels = new_labels + ([parent_label]*curmodif.shape[0])
        return indmodif, new_labels, parent_labels

    def keep_orphans( self, img, frame, keep_labels=[]):
        """ Keep only labels that doesn't have a follower (track is finishing at that frame) """
        ## remove the labels to track
        labs = np.unique(img[0]).tolist() #np.setdiff1d( img[0], labels ).tolist()
        if 0 in labs:
            labs.remove(0)
        ## Check that it's not present at current frame
        torem = [ lab for lab in labs if (lab not in keep_labels) and (self.epicure.tracking.is_in_frame( lab, frame ) ) ]
        if len(torem) == 0:
            return img
        mask = np.isin(img[0], torem)
        img[0][mask] = 0
        return img

    def inherit_parent_labels(self, myframe, labels, bbox, frame, keep_labels):
        """ Get parent labels if any and indices to modify with it """
        if ( self.epicure.tracked == 0 ) or (frame<=0):
            parent_labels = [None]*len(labels)
            indmodif, new_labels, parent_labels = self.get_position_label_2D(myframe, labels, parent_labels)
        else:
            twoframes = ut.crop_twoframes( self.epicure.seglayer.data, bbox, frame )
            twoframes[1] = np.copy(myframe) # merge of the labels and 0 outside
            twoframes = self.keep_orphans( twoframes, frame, keep_labels=keep_labels)
            
            parent_labels = self.get_parents( twoframes, labels )
        
            indmodif, new_labels, parent_labels = self.get_position_label_2D(twoframes[1], labels, parent_labels)

        if self.epicure.verbose > 0:
            print("Set value (from parent or new): "+str(np.unique(new_labels)))
        ## back to movie position
        indmodif = ut.toFullMoviePos( indmodif, bbox, frame )
        return indmodif, new_labels, parent_labels
    
    def inherit_child_labels(self, myframe, labels, bbox, frame, parent_labels, keep_labels):
        """ Get child labels if any and indices to modify with it """
        if (self.epicure.tracked == 0 ) or (frame>=self.epicure.nframes-1):
            return [], []
        else:
            twoframes = np.copy( ut.cropBBox2D(self.epicure.seglayer.data[frame+1], bbox) )
            ## check if the new value to set is present in the following frame, in that case don't do any propagation
            for par in parent_labels:
                if np.any( twoframes==par ):
                    if self.epicure.verbose > 1:
                        print("Propagating: not because new value present in labels: "+str(par))
                    return [], []

            twoframes = np.stack( (twoframes, np.copy(myframe)) )
            twoframes = self.keep_orphans(twoframes, frame, keep_labels=keep_labels)
            child_labels = self.get_parents( twoframes, labels )
            
            if self.epicure.verbose > 0:
                print("Propagate  the new value to: "+str(child_labels))
            if child_labels is None:
                return [], []
        
        # get position of each child label to update with current label
        indmodif = []
        new_labels = []
        for i, lab in enumerate(child_labels):
            if lab is not None:
                if lab == parent_labels[i]:
                    ## going to propagate to itself, no need
                    continue
                after_frame = frame+1
                last_frame = self.epicure.tracking.get_last_frame( parent_labels[i] )
                if (last_frame is not None) and (last_frame >= after_frame):
                    ## the label to propagate is present somewhere after the current frame
                    self.epicure.split_track( parent_labels[i], after_frame )
                inds = self.epicure.get_label_indexes( lab, after_frame )
                if len(indmodif) == 0:
                    indmodif = inds
                else:
                    indmodif = np.vstack((indmodif, inds))
                new_labels = new_labels + np.repeat(parent_labels[i], len(inds)).tolist()
        return indmodif, new_labels

    def propagate_label_change(self, myframe, labels, bbox, frame, keep_labels):
        """ Propagate the new labelling to match parent/child labels """
        start_time = ut.start_time()
        indmodif = ut.ind_boundaries( myframe )
        indmodif = ut.toFullMoviePos( indmodif, bbox, frame )
        #ut.show_info("Boundaries in "+"{:.3f}".format((time.time()-start_time)/60)+" min")
        new_labels = np.repeat(0, len(indmodif)).tolist()

        ## get parent labels if any for each label
        indmodif2, new_labels2, parent_labels = self.inherit_parent_labels(myframe, labels, bbox, frame, keep_labels)
        if indmodif2 is not None:
            indmodif = np.vstack((indmodif, indmodif2))
            new_labels = new_labels+new_labels2
        if self.epicure.verbose > 1:
            ut.show_duration(start_time, "Propagation, parents found, ")

        ## propagate the change: get child labels if any for each label
        indmodif_child, new_labels_child = self.inherit_child_labels(myframe, labels, bbox, frame, parent_labels, keep_labels)
        if len(indmodif_child) > 0:
            indmodif = np.vstack((indmodif, indmodif_child))
            new_labels = new_labels + new_labels_child
        if self.epicure.verbose > 1:
            ut.show_duration(start_time, "Propagation, childs found, ")
        
        ## go, do the update
        self.epicure.change_labels(indmodif, new_labels)

    ############# Test
    def interpolate_labels( self, labela, framea, labelb, frameb ):
        """ 
            Interpolate the label shape in between two labels 
            Based on signed distance transform, like Fiji ROIs interpolation
        """
        if self.epicure.verbose > 1:
            print("Interpolating between "+str(labela)+" and "+str(labelb))
            print("From frame "+str(framea)+" to frame "+str(frameb))
            start_time = ut.start_time()
        
        sega = self.epicure.seglayer.data[framea]
        maska = np.isin( sega, [labela] )
        segb = self.epicure.seglayer.data[frameb]
        maskb = np.isin( segb, [labelb] )

        ## get merged bounding box, and crop around it
        mask = maska | maskb
        props = ut.labels_properties(mask*1)
        bbox = ut.extendBBox2D( props[0].bbox, extend_factor=1.2, imshape=mask.shape )

        maska = ut.cropBBox2D( maska, bbox )
        maskb = ut.cropBBox2D( maskb, bbox )

        ## get signed distance transform of each label
        dista = edt.sdf( maska )
        distb = edt.sdf( maskb )

        inds = None
        new_labels = []
        for frame in range(framea+1, frameb):
            p = (frame-framea)/(frameb-framea)
            dist = (1-p) * dista + p * distb
            ## change only pixels that are 0
            frame_crop = ut.cropBBox2D( self.epicure.seglayer.data[frame], bbox )
            tochange = binary_dilation(dist>0, footprint=disk(radius=2)) * (frame_crop<=0)   # expand to touch neighbor label
            
            ## indexes and new values to change
            indmodif = np.argwhere( tochange > 0 ).tolist()
            indmodif = ut.toFullMoviePos( indmodif, bbox, frame )
            if inds is None:
                inds = indmodif
            else:
                inds = np.vstack( (inds, indmodif) )
            new_labels = new_labels + [labela]*len(indmodif)

            ## be sure to remove the boundaries with neighbor labels
            bound_ind = ut.ind_boundaries( tochange )
            new_labels = new_labels + [0]*len(bound_ind)
            bound_ind = ut.toFullMoviePos( bound_ind, bbox, frame )
            inds = np.vstack( (inds, bound_ind) )

        ## Go, apply the changes
        self.epicure.change_labels( inds, new_labels )
        ## change the second track to first track value
        self.epicure.replace_label( labelb, labela, frameb )
        if self.epicure.verbose > 1:
            ut.show_duration( start_time, "Interpolation took " )
        if self.epicure.verbose > 0:
            ut.show_info( "Interpolated label "+str(labela)+" from frame "+str(framea+1)+" to "+str(frameb-1) )

        



class ClassifyIntensity( QWidget ):
    """ Interface to group cells based on their mean intensity """
    def __init__( self, edit ):
        super().__init__()
        self.edit = edit
        poplayout = wid.vlayout()

        ## Show in which group cells will be added
        self.group_name = wid.label_line( "Positive cells will be added to group: "+str(self.edit.group_choice.currentText() ) )
        poplayout.addWidget( self.group_name )

        ## Choose the intensity layer
        line, self.layer_choice = wid.list_line( label="Measure intensity from: ", descr="Choose the layer to use for intensity classification" )
        for lay in self.edit.viewer.layers:
            if lay.name in [ "Events", "Tracks", "ROIs" ]:
                continue
            self.layer_choice.addItem( lay.name )
            print(lay.name)
        poplayout.addLayout( line )

        ## Choose the method to use for intensity measurement
        method_line, self.method_choice = wid.list_line( label="Method to measure intensity along track: ", descr="Choose the method to measure intensity" )
        meths = ["mean", "median", "max", "min", "sum"]
        for meth in meths:
            self.method_choice.addItem( meth)        
        poplayout.addLayout( method_line )

        ## Choose frames to use for classification 
        frame_lab = wid.label_line( "Measure intensity on frame(s):" )
        min_frame_line, self.min_frame = wid.ranged_value_line( label="From frame: ", descr="First frame to use for classification", minval=0, maxval=self.edit.epicure.nframes-1, step=1, val=0 )
        poplayout.addLayout( min_frame_line )
        max_frame_line, self.max_frame = wid.ranged_value_line( label="To frame: ", descr="Last frame to use for classification", minval=0, maxval=self.edit.epicure.nframes-1, step=1, val=self.edit.epicure.nframes-1 )
        poplayout.addLayout( max_frame_line )

        ## Choose the threshold for classification
        thres_line, self.threshold = wid.value_line( label="Track intensity threshold: ", default_value="100", descr="Threshold of measured intensity of a track to be considered as positive" )
        poplayout.addLayout( thres_line )

        go_btn = wid.add_button( "Add positive cells to group", self.classify, "Start the classification of positive cells" )
        poplayout.addWidget( go_btn )

        self.setLayout( poplayout )

    def update( self ):
        """ Update the parameters with current GUI state """
        self.group_name.setText( "Positive cells will be added to group: "+str(self.edit.group_choice.currentText() ) )
        self.layer_choice.clear()
        for lay in self.edit.viewer.layers:
            if lay.name in [ "Events", "Tracks", "ROIs" ]:
                continue
            self.layer_choice.addItem( lay.name )

    def classify( self ):
        self.edit.group_positive_cells( self.layer_choice.currentText(), self.method_choice.currentText(), self.min_frame.value(), self.max_frame.value(), float(self.threshold.text()) )

class ClassifyEvent( QWidget ):
    """ Interface to group cells based on their interaction with an event (dividing or extruding cells) """

    def __init__( self, edit ):
        super().__init__()
        self.edit = edit
        poplayout = wid.vlayout()

        ## Choose the event to use
        line, self.event_choice = wid.list_line( label="Select cells that ends with: ", descr="Choose the event to use to select the cells" )
        for evt in self.edit.epicure.event_class:
            self.event_choice.addItem( evt )
        poplayout.addLayout( line )

        go_btn = wid.add_button( "Add selected cells to new group", self.classify, "Start the classification of cells" )
        poplayout.addWidget( go_btn )

        self.setLayout( poplayout )

    def classify( self ):
        """ Add all the cell that finish with the selected event to the group """
        self.edit.group_event_cells( self.event_choice.currentText() )


