from qtpy.QtWidgets import QPushButton, QVBoxLayout, QTabWidget, QWidget, QComboBox, QLabel, QLineEdit, QGroupBox, QHBoxLayout, QColorDialog
#from qtpy.QtGui import QColor
import napari
import epicure.Utils as ut
from pathlib import Path
import os, pickle

def edit_preferences():
    """ Launch preferences edition interface"""
    viewer = napari.current_viewer()
    prefgui = PreferencesGUI( viewer )
    return prefgui

class PreferencesGUI( QWidget ):
    """ Handles user preferences for shortcuts, default widget state """

    def __init__(self, napari_viewer):
        """ Initialize the tab with the different widgets """
        super().__init__()
        
        ## preferences (shortcuts, plugin state) object
        self.pref = Preferences()
        
        layout = QVBoxLayout()
        tabs = QTabWidget()
        tabs.setObjectName("Preferences")
        
        ## shortcut and plugin state preferences tabs
        self.shortcuts = ShortCut( napari_viewer, self.pref )
        tabs.addTab( self.shortcuts, "Shortcuts Config." )
        self.displays = DisplaySettings( napari_viewer, self.pref )
        tabs.addTab( self.displays, "Display Config." )
        layout.addWidget(tabs)

        ## save option
        self.save_pref = QPushButton("Save preferences", parent=self)
        layout.addWidget( self.save_pref )
        self.save_pref.clicked.connect( self.save )

        ## add to main interface
        self.setLayout( layout )
        #napari_viewer.window.add_dock_widget( main_widget, name="Preferences" )

    def save( self ):
        """ Save current preferences: update them and save to default file """
        self.shortcuts.update_pref()
        self.pref.save()
        

class Preferences():
    """ Handles user-specific preferences (shortcuts, widgets states) """
    
    def __init__( self ):
        """ Initialise file path, load current preferences"""
        self.build_preferences_path()

        self.load_default_shortcuts()
        self.load_default_settings()
        if os.path.exists( self.preference_path ):
            self.load()

    def build_preferences_path( self ):
        """ Build (create directories if necessary) preference path """
        home_dir = Path.home()
        self.preference_path = os.path.join( home_dir, ".napari" )
        if not os.path.exists( self.preference_path ):
            os.mkdir( self.preference_path )
        self.preference_path = os.path.join( self.preference_path, "epicure_preferences.pkl" )

    def save( self ):
        """ Save the current preferences to the preference files in user home """
        outfile = open( self.preference_path, "wb" )
        pickle.dump( self.shortcuts, outfile )
        pickle.dump( self.settings, outfile )
        outfile.close()
        print( "Preferences saved in file "+self.preference_path )

    def set_preferences( self, default_prefs, prefs ):
        """ Merge (recursively) the preferences with the default ones """
        for key, vals in prefs.items():
            if key in default_prefs.keys():
                if isinstance( vals, dict ):
                    self.set_preferences( default_prefs[key], vals )
                else:
                    default_prefs[key] = vals
            else:
                default_prefs[key] = vals

    def load( self ):
       """ Load the current preferences to the preference files in user home """
       infile = open( self.preference_path, "rb" )
       shortcuts = pickle.load( infile )
       self.set_preferences( self.shortcuts, shortcuts )
       try:
           settings = pickle.load( infile )
           #print(settings)
           self.set_preferences( self.settings, settings )
           #print(self.settings)
       except:
           self.load_default_settings()
       #print(self.shortcuts)
       infile.close()
       #print( "Preferences loaded from file "+self.preference_path )

    def get_settings( self ):
        """ Return the dict of prefered settings (widget state) """
        return self.settings

    def get_shortcuts( self ):
        """ Return the dict of shortcuts """
        return self.shortcuts

    def add_key_shortcut( self, main_type, shortname, fulltext, key ):
        """ Add a keyboard shortcut """
        if main_type not in self.shortcuts.keys():
            self.shortcuts[ main_type ] = {}
        ## initialize the new shortcut object
        self.shortcuts[ main_type ][ shortname ] = {}
        sc = self.shortcuts[ main_type ][ shortname ]
        sc["type"] = "key"
        sc["text"] = fulltext
        sc["key"] = key
    
    def add_click_shortcut( self, main_type, shortname, fulltext, button, modifiers=None ):
        """ Add a keyboard shortcut """
        if main_type not in self.shortcuts.keys():
            self.shortcuts[ main_type ] = {}
        ## initialize the new shortcut object
        self.shortcuts[ main_type ][ shortname ] = {}
        sc = self.shortcuts[ main_type ][ shortname ]
        sc["type"] = "click"
        sc["text"] = fulltext
        sc["button"] = button
        if modifiers is not None:
            sc["modifiers"] = modifiers

    def load_default_shortcuts( self ):
        """ Load all default shortcuts """

        self.shortcuts = {}

        ## General shortcuts
        self.add_key_shortcut( "General", shortname="show help", fulltext="show/hide overlay help message", key="h" )
        self.add_key_shortcut( "General", shortname="show all", fulltext="show all shortcuts in a separate window", key="a" )
        self.add_key_shortcut( "General", shortname="save segmentation", fulltext="save the segmentation and epicure files", key="s" )
        self.add_key_shortcut( "General", shortname="save movie", fulltext="save the movie with current display", key="Shift-s" )

        ## Labels edition (static) shortcuts
        self.add_key_shortcut( "Labels", shortname="unused paint", fulltext="set the current label to unused value and go to paint mode", key="n" )
        self.add_key_shortcut( "Labels", shortname="unused fill", fulltext="set the current label to unused value and go to fill mode", key="Shift-n" )
        self.add_key_shortcut( "Labels", shortname="swap mode", fulltext="then <Control>+Left click on one cell to another to swap their values", key="w" )

        self.add_click_shortcut( "Labels", shortname="erase", fulltext="erase the cell under the click", button="Right", modifiers=None )
        self.add_click_shortcut( "Labels", shortname="merge", fulltext="drag-click from one cell to another to merge them", button="Left", modifiers=["Control"] )
        self.add_click_shortcut( "Labels", shortname="split accross", fulltext="drag-click in the cell to split into 2 cells ", button="Right", modifiers=["Control"] )
        self.add_click_shortcut( "Labels", shortname="split draw", fulltext="drag-click draw a junction to split in 2 cells", button="Right", modifiers=["Alt"] )
        self.add_click_shortcut( "Labels", shortname="redraw junction", fulltext="drag-click draw a junction to correct it", button="Left", modifiers=["Alt"] )
        self.add_key_shortcut( "Labels", shortname="draw junction mode", fulltext="Draw junction(s) mode ON", key="j" )
        self.add_click_shortcut( "Labels", shortname="drawing junction", fulltext="Draw junction mode ON. Drag-click draw a junction to create new cell(s)", button="Left", modifiers=["Control"] )
        
        ## Seeds (manual segmentation) shortcuts
        self.add_key_shortcut( "Seeds", shortname="new seed", fulltext="<key shortcut> then left-click to place a seed", key="e" )
        
        ## Groups shortcuts
        self.add_click_shortcut( "Groups", shortname="add group", fulltext="add the clicked cell to the current group", button="Left", modifiers=["Shift"] )
        self.add_click_shortcut( "Groups", shortname="remove group", fulltext="remove the clicked cell from the group", button="Right", modifiers=["Shift"] )
        
        ## events edition shortcuts
        self.add_key_shortcut( "Events", shortname="next", fulltext="zoom on next event", key="Space" )
        self.add_click_shortcut( "Events", shortname="zoom", fulltext="Zoom on the clicked event", button="Left", modifiers=["Control", "Alt"] )
        self.add_click_shortcut( "Events", shortname="delete", fulltext="Remove the clicked event", button="Right", modifiers=["Control", "Alt"] )
        self.add_click_shortcut( "Events", shortname="add division", fulltext="add a division: drag-click from first to second daugther", button="Left", modifiers=["Control", "Shift"] )
        self.add_click_shortcut( "Events", shortname="add extrusion", fulltext="add an extrusion: click on the last cell of the track", button="Right", modifiers=["Control", "Shift"] )

        ## Tracks edition shortcuts
        self.add_key_shortcut( "Tracks", shortname="show", fulltext="show/hide the tracks", key="r" )
        self.add_key_shortcut( "Tracks", shortname="lineage color", fulltext="color the tracks by lineage", key="l" )
        self.add_key_shortcut( "Tracks", shortname="mode", fulltext="on/off track editing mode", key="t" )
        self.add_click_shortcut( "Tracks", shortname="merge first", fulltext="+track mode ON. Merge tracks: select the first", button="Left" )
        self.add_click_shortcut( "Tracks", shortname="merge second", fulltext="+trackmode ON. Merge tracks: selec the second", button="Right" )
        self.add_click_shortcut( "Tracks", shortname="split track", fulltext="+trackmode ON. Split the track temporally in 2", button="Right", modifiers=["Shift"] )
        self.add_click_shortcut( "Tracks", shortname="start manual", fulltext="+trackmode ON. Start manual tracking, clicking on cells", button="Left", modifiers=["Control"] )
        self.add_click_shortcut( "Tracks", shortname="end manual", fulltext="+trackmode ON. Finish manual tracking", button="Right", modifiers=["Control"] )
        self.add_click_shortcut( "Tracks", shortname="interpolate first", fulltext="+trackmode ON. Interpolate temporally labels: select first", button="Left", modifiers=["Alt"] )
        self.add_click_shortcut( "Tracks", shortname="interpolate second", fulltext="+trackmode ON. Interpolate temporally labels: select second", button="Right", modifiers=["Alt"] )
        self.add_click_shortcut( "Tracks", shortname="swap", fulltext="+trackmode ON. Drag click to swap 2 tracks from current frame", button="Left", modifiers=["Shift"] )
        self.add_click_shortcut( "Tracks", shortname="delete", fulltext="+trackmode ON. Delete all the track from current frame", button="Right", modifiers=["Control", "Alt"]  )

        ## Visualisation option shortcuts
        self.add_key_shortcut( "Display", shortname="vis. segmentation", fulltext="show/hide segmentation layer", key="b" )
        self.add_key_shortcut( "Display", shortname="vis. movie", fulltext="show/hide movie layer", key="v" )
        self.add_key_shortcut( "Display", shortname="vis. event", fulltext="show.hide events layer", key="x" )
        self.add_key_shortcut( "Display", shortname="only movie", fulltext="show ONLY movie layer on/off", key="c" )
        self.add_key_shortcut( "Display", shortname="light view", fulltext="on/off light segmentation view", key="d" )
        self.add_key_shortcut( "Display", shortname="skeleton", fulltext="show/hide/update segmentation skeleton", key="k" )
        self.add_key_shortcut( "Display", shortname="show side", fulltext="view layers side by side on/off", key="z" )
        self.add_key_shortcut( "Display", shortname="grid", fulltext="show/hide grid", key="g" )
        self.add_key_shortcut( "Display", shortname="increase", fulltext="increase label contour size", key="Control-c" )
        self.add_key_shortcut( "Display", shortname="decrease", fulltext="decrease label contour size", key="Control-d" )
        
        ## Info shortcuts
        self.add_key_shortcut( "Info", shortname="measure length", fulltext="draw and measure a line length", key="Control-i" )
    
    
    def load_default_settings( self ):
        """ Load all default widget settings """
        self.settings = {}

        ## Default visualisation set-up
        self.settings["Display"] = {}
        self.settings["Display"]["Layers"] = { 'Tracks': True, 'events': True, 'ROIs': False, 'Segmentation': True, 'Movie': True, 'EpicGrid': False, 'Groups': False }

        self.settings["Info"] = {}

        ## widgets colors
        self.load_default_colors()

        ## default visualisation of events widget
        self.settings["events"] = {}

    def load_default_colors( self ):
        """ Load the defualt GUI colors """
        self.settings["Display"]["Colors"] = {}
        col_set = self.settings["Display"]["Colors"]
        col_set["button"] = "rgb(40, 60, 75)"
        col_set["Help button"] = "rgb(62, 60, 75)"
        col_set["Reset button"] = "rgb(70, 68, 85)"
        col_set["checkbox"] = "rgb(40, 52, 65)"
        col_set["line edit"] = "rgb(30, 30, 40)"
        col_set["group"] = "rgb(33,42,55)"
        col_set["group4"] = "rgb(37,37,57)"
        col_set["group3"] = "rgb(30,35,40)"
        col_set["group2"] = "rgb(30,40,50)"
        

class ShortCut( QWidget ):
    """ Class to handle edit EpiCure shortcuts """

    def __init__( self, napari_viewer, pref ):
        super().__init__()
        
        layout = QVBoxLayout()

        self.sc = pref.get_shortcuts()
        ## choice list to choose which shortcuts to edit
        self.shortcut_types = self.sc.keys()
        self.sc_types = QComboBox()
        self.sc_groups = {}
        self.sc_guis = {}
        layout.addWidget( self.sc_types )
        for sc_type in self.shortcut_types:
            self.sc_types.addItem( sc_type )
            self.sc_guis[sc_type] = {}
            self.sc_groups[sc_type] = self.create_sc_type( sc_type )
            layout.addWidget( self.sc_groups[sc_type] )
        self.show_sc_type()

        self.setLayout(layout)
        self.sc_types.currentIndexChanged.connect( self.show_sc_type )

    def show_sc_type( self ):
        """ Show only selected shortcut subset """
        for sc_type in self.shortcut_types:
            self.sc_groups[ sc_type ].setVisible( self.sc_types.currentText() == sc_type )

    def create_sc_type( self, sc_type ):
        """ Interface to edit shortcut subset of a given type """
        sc_curgroup = QGroupBox( "" )
        sc_layout = QVBoxLayout()
        
        ## add each shortcut from the current selected group
        cur_shortcuts = self.sc[ sc_type ]
        for shortname, val in cur_shortcuts.items():
            new_line = QHBoxLayout()
            ## current keyboard shortcut
            if val["type"] == "click":
                ## shortcut is a mouse shortcut
                if "modifiers" in val.keys():
                    ind = 0
                    for modif in val["modifiers"]:
                        cur_modif = QComboBox()
                        cur_modif.addItem("")
                        cur_modif.addItem("Control")
                        cur_modif.addItem("Shift")
                        cur_modif.addItem("Alt")
                        new_line.addWidget( cur_modif )
                        cur_modif.setCurrentText( modif )
                        self.sc_guis[sc_type][ shortname+"modifiers"+str(ind) ] = cur_modif
                        ind = ind + 1
                cur_click = QComboBox()
                cur_click.addItem("Left-click")
                cur_click.addItem("Right-click")
                new_line.addWidget( cur_click )
                if val["button"] == "Right":
                    cur_click.setCurrentText( "Right-click" )
                self.sc_guis[sc_type][ shortname ] = cur_click
            if val["type"] == "key":
                new_line_val = QLineEdit()
                new_line_val.setText( val["key"] )
                self.sc_guis[sc_type][ shortname ] = new_line_val
                new_line.addWidget( new_line_val )
            ## full description of the shortcut
            long_description = QLabel()
            long_description.setText( val["text"] )
            new_line.addWidget( long_description )
            sc_layout.addLayout( new_line )
            #empty = QLabel()
            #sc_layout.addWidget( empty )
        
        sc_curgroup.setLayout( sc_layout )
        return sc_curgroup

    def update_pref( self ):
        """ Update the shortcuts in the Preference based on current values """
        for sc_type in self.shortcut_types:
            gui = self.sc_guis[ sc_type ]
            sc_group = self.sc[ sc_type ]
            for shortname, vals in sc_group.items():
                if vals["type"] == "click":
                    ## update the modifiers if there are some
                    ind = 0
                    if "modifiers" in vals.keys():
                        del vals["modifiers"]
                    while shortname+"modifiers"+str(ind) in gui.keys():
                        modif = gui[ shortname+"modifiers"+str(ind) ].currentText()
                        if "modifiers" not in vals.keys():
                            vals["modifiers"] = []
                        if modif != "":
                            vals["modifiers"].append(modif)
                        ind = ind + 1
                        if len( vals["modifiers"] ) == 0:
                            del vals["modifiers"]
                    ## update the button information
                    click = gui[shortname].currentText()
                    if click == "Left-click":
                        vals["button"] = "Left"
                    else:
                        vals["button"] = "Right"
                if vals["type"] == "key":
                    vals["key"] = gui[shortname].text()


class DisplaySettings( QWidget ):
    """ Class to handle edit EpiCure display button colors...)"""
    
    def __init__( self, napari_viewer, pref ):
        super().__init__()
        self.settings = pref.get_settings()
        if "Colors" not in self.settings["Display"]:
            pref.load_default_colors()
        colors = self.settings["Display"]["Colors"]

        ## interface of display choices
        layout = QVBoxLayout()
        self.grid_color = QPushButton("EpicGrid color", self)
        self.grid_color.clicked.connect( self.get_grid_color )
        layout.addWidget( self.grid_color )

        self.add_color( layout, "Buttons color", "button", "Choose default color of buttons" )
        self.add_color( layout, "Help buttons color", "Help button", "Choose color of buttons for Help actions" )
        self.add_color( layout, "Reset buttons color", "Reset button", "Choose color of buttons for Reset actions" )
        self.add_color( layout, "CheckBox color", "checkbox", "Choose color of checkboxes" )
        self.add_color( layout, "Input color", "line edit", "Choose color of editable parameters boxes" )
        self.add_color( layout, "Subpanels color", "group", "Choose color of option subpanels that appears when clicked/selected" )
        self.add_color( layout, "Subpanels color 2", "group2", "Choose second color of option subpanels that appears when clicked/selected" )
        self.add_color( layout, "Subpanels color 3", "group3", "Choose third color of option subpanels that appears when clicked/selected" )
        self.add_color( layout, "Subpanels color 4", "group4", "Choose fourth color of option subpanels that appears when clicked/selected" )
        
        self.setLayout(layout)

    def add_color( self, layout, label, setname, descr="" ):
        """ Add a choice of color (push button that opens a color dialog) """
        btn = QPushButton( label )
        if descr != "":
            btn.setToolTip( descr )
        def get_color():
            """ opens color dialog and set button color to it """
            color = QColorDialog.getColor()
            if color.isValid():
                self.settings["Display"]["Colors"][setname] = color.name()
                btn.setStyleSheet( 'QPushButton {background-color: '+color.name()+'}' )
        btn.clicked.connect( get_color )
        if setname in self.settings["Display"]["Colors"]:
            color = self.settings["Display"]["Colors"][setname]
            btn.setStyleSheet( 'QPushButton {background-color: '+color+'}' )
        layout.addWidget( btn )

    def get_grid_color( self ):
        """ Get the EpiCGrid color """
        color = QColorDialog.getColor()
        if color.isValid():
            if "Display" not in self.settings:
                self.settings["Display"] = {}
            self.settings["Display"]["Grid color"] = color.name()
            self.grid_color.setStyleSheet( 'QPushButton {background-color: '+color.name()+'}' )
        
            


