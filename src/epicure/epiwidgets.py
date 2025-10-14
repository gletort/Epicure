import epicure.Utils as ut
from qtpy.QtWidgets import QPushButton, QCheckBox, QHBoxLayout, QVBoxLayout, QLabel, QLineEdit, QComboBox, QSpinBox, QSlider, QGroupBox, QFrame # type: ignore
from qtpy.QtCore import Qt # type: ignore

def help_button( link, description="", display_settings=None ):
    """ Create a new Help button with given parameter """
    def show_doc():
        """ Open documentation page """
        ut.show_documentation_page( link )

    help_btn = QPushButton( "help" )
    if description == "":
        help_btn.setToolTip( "Open EpiCure documentation" )
        help_btn.setStatusTip( "Open EpiCure documentation" )
    else:
        help_btn.setToolTip( description )
        help_btn.setStatusTip( description )
    help_btn.clicked.connect( show_doc )
    if display_settings is not None:
        if "Help button" in display_settings:
            color = display_settings["Help button"]
            help_btn.setStyleSheet( 'QPushButton {background-color: '+color+'}' )
    return help_btn

def group_layout( grname ):
    """ Create a group box with a vertical layout """
    group = QGroupBox( grname )
    layout = QVBoxLayout()
    return group, layout

def separation():
    """ Create horizontal line to create a separation """
    sep = QFrame()
    sep.setFrameShape(QFrame.HLine)
    sep.setLineWidth(2)
    sep.setMidLineWidth(2)
    sep.setMinimumSize( 10, 2 )
    sep.setStyleSheet('background-color: rgb(150,150,150)')  
    return sep

def checkgroup_help( name, checked, descr, help_link, display_settings=None, groupnb=None ):
    """ Create a group that can be show/hide with checkbox and an help button """
    group = QGroupBox( name )
    chbox = QCheckBox( text=name )

    ## set group and checkbox to the same specific color
    if (groupnb is not None) and (display_settings is not None):
        if groupnb in display_settings:
            color = display_settings[groupnb]
            group.setStyleSheet( 'QGroupBox {background-color: '+color+'}' )
            chbox.setStyleSheet( 'QCheckBox::indicator {background-color: '+color+'}' )
    
    def show_hide():
        group.setVisible( chbox.isChecked() )

    line = QHBoxLayout()
    ## create checkbox
    chbox.setToolTip( descr )
    line.addWidget( chbox )
    chbox.stateChanged.connect( show_hide )
    chbox.setChecked( checked )
    ## create button
    if help_link is not None:
        help_btn = help_button( help_link, "", display_settings )
        line.addWidget( help_btn )
    return line, chbox, group

def checkhelp_line( checkbox_name, checked, checkfunc, check_descr, help_link, display_settings=None, help_descr="" ):
    """ Create a layout line with a checkbox associated with help button """
    line = QHBoxLayout()
    ## create checkbox
    chbox = QCheckBox( text=checkbox_name )
    chbox.setToolTip( check_descr )
    line.addWidget( chbox )
    if checkfunc is not None:
        chbox.stateChanged.connect( checkfunc )
    chbox.setChecked( checked )
    ## create button
    help_btn = help_button( help_link, help_descr, display_settings )
    line.addWidget( help_btn )
    return line, chbox

def add_check( check, checked, check_func=None, descr="" ):
    """ Add a checkbox with set parameters """
    cbox = QCheckBox( text=check )
    cbox.setToolTip( descr )
    if check_func is not None:
        cbox.stateChanged.connect( check_func )
    cbox.setChecked( checked )
    return cbox

def label_line( label ):
    """ Returns a label line """
    lab = QLabel( label )
    return lab

def hlayout():
    """ Return a horizontal layout """
    return QHBoxLayout()

def vlayout():
    """ Return a vertical layout """
    return QVBoxLayout()

def add_check_tolayout( layout, check, checked, check_func=None, descr="" ):
    """ Add a checkbox with set parameters """
    cbox = add_check( check, checked, check_func, descr )
    layout.addWidget( cbox )
    return cbox

def double_check( checka, checkeda, funca, descra, checkb, checkedb, funcb, descrb ):
    """ Line with two customized checkboxes """
    line = QHBoxLayout()
    check_a = add_check( checka, checkeda, funca, descra )
    check_b = add_check( checkb, checkedb, funcb, descrb )
    line.addWidget( check_a )
    line.addWidget( check_b )
    return line, check_a, check_b

def add_button( btn, btn_func, descr="", color=None ):
    """ Add a button connected to an action when pushed """
    btn = QPushButton( btn )
    if btn_func is not None:
        btn.clicked.connect( btn_func )
    if descr != "":
        btn.setToolTip( descr )
    else:
        btn.setToolTip( "Click to perform action" )
    if color is not None:
        btn.setStyleSheet( 'QPushButton {background-color: '+color+'}' )
    return btn

def double_button( btna, funca, descra, btnb, funcb, descrb ):
    """ Line with two customized buttons """
    line = QHBoxLayout()
    btn_a = add_button( btna, funca, descra )
    btn_b = add_button( btnb, funcb, descrb )
    line.addWidget( btn_a )
    line.addWidget( btn_b )
    return line

def button_parameter_line( btn, btn_func, value, descr_btn="", descr_value="" ):
    """ Create a layout with a button and an editable value associated """
    line = QHBoxLayout()
    ## Action button
    btn = QPushButton( btn )
    btn.clicked.connect( btn_func )
    if descr_btn != "":
        btn.setToolTip( descr_btn )
    line.addWidget( btn )
    ## Value editable
    val = QLineEdit()
    val.setText( value )
    line.addWidget( val )
    if descr_value != "":
        val.setToolTip( descr_value )
    return line, val

def min_button_max( btn, btn_func, min_val, max_val, descr="" ):
    """ Button inside two values (min and max) interfaces """
    line = QHBoxLayout()
    ## left value
    minv = QLineEdit()
    minv.setText( min_val )
    line.addWidget( minv )
    ## button
    btn = QPushButton( btn )
    btn.clicked.connect( btn_func )
    if descr != "":
        btn.setToolTip( descr )
    line.addWidget( btn )
    ## right value
    maxv = QLineEdit()
    maxv.setText( max_val )
    line.addWidget( maxv )
    return line, minv, maxv


def button_check_line( btn, btn_func, check, checked=False, checkfunc=None, descr_btn="", descr_check="", leftbtn=True ):
    """ Create a layout with a button and an assiociated checkbox """
    line = QHBoxLayout()
    ## Action button
    btn = QPushButton( btn )
    btn.clicked.connect( btn_func )
    if descr_btn != "":
        btn.setToolTip( descr_btn )
    ## Value editable
    cbox = QCheckBox( check )
    if descr_check != "":
        cbox.setToolTip( descr_check )
    if checkfunc is not None:
        cbox.stateChanged.connect( checkfunc )
    cbox.setChecked( checked )
    ## button first (left), then checkbox
    if leftbtn:
        line.addWidget( btn )
        line.addWidget( cbox )
    else:
        ## or checkbox first (left), then button
        line.addWidget( cbox )
        line.addWidget( btn )
    return line, cbox

def value_line( label, default_value, descr="" ):
    """ Create a layout line with a value to edit (non editable name + value part ) """
    line = QHBoxLayout()
    ## Value name
    lab = QLabel()
    lab.setText( label )
    line.addWidget( lab )
    if descr != "":
        lab.setToolTip( descr )
    ## Value editable part
    value = QLineEdit()
    value.setText( default_value )
    line.addWidget( value )
    return line, value

def check_value( check, checkfunc=None, checked=False, value="0", descr="", label=None ):
    """ Line with a checkbox and an associated editable parameter """
    line = QHBoxLayout()
    ## add checkbox
    cbox = add_check( check, checked=checked, check_func=checkfunc, descr=descr )
    line.addWidget( cbox )
    ## add eventually a text
    if label is not None:
        lab = QLabel()
        lab.setText( label )
        line.addWidget( lab )
    ## add the editable value
    val = QLineEdit()
    val.setText( value )
    line.addWidget( val )
    return line, cbox, val

def ranged_value_line( label, minval, maxval, step, val, descr="" ):
    """ Create a line with a label and a ranged value (limited between min and max) """
    line = QHBoxLayout()
    ## Add the name of the value
    lab = QLabel()
    lab.setText( label )
    if descr != "":
        lab.setToolTip( descr )
    line.addWidget( lab )
    ## Ranged-value widget
    ranged_val = QSpinBox()
    ranged_val.setMinimum( minval )
    ranged_val.setMaximum( maxval )
    ranged_val.setSingleStep( step ) 
    ranged_val.setValue( val )
    line.addWidget( ranged_val )
    return line, ranged_val

def button_list( btn, func, descr ):
    """ Button associated with a list """
    line = QHBoxLayout()
    ## Button part
    button = add_button( btn, func, descr )
    line.addWidget( button )
    ## list part
    li = QComboBox()
    line.addWidget( li )
    return line, li

def list_line( label, descr="", func=None ):
    """ Create a layout line with a choice list to edit (non editable name + list part ) """
    line = QHBoxLayout()
    ## Value name
    lab = QLabel()
    lab.setText( label )
    line.addWidget( lab )
    if descr != "":
        lab.setToolTip( descr )
        lab.setStatusTip( descr )
    ## Value editable part
    value = QComboBox()
    line.addWidget( value )
    if func is not None:
        value.currentIndexChanged.connect( func )
    return line, value

def listbox( func=None ):
    """ Create a choice list to edit """
    ## Value editable part
    value = QComboBox()
    if func is not None:
        value.currentIndexChanged.connect( func )
    return value

def slider_line( name, minval, maxval, step, value, show_value=False, slidefunc=None, descr="" ):
    """ Line with a text and a slider """
    line = QHBoxLayout()
    ## add name if any
    if name is not None:
        lab = QLabel()
        lab.setText( name )
        line.addWidget( lab )
    ## add slider
    slider =  QSlider( Qt.Horizontal )
    slider.setMinimum( minval )
    slider.setMaximum( maxval )
    slider.setSingleStep( step )
    slider.setValue( value )
    if slidefunc is not None:
        slider.valueChanged.connect( slidefunc )
    if descr != "":
        slider.setToolTip( descr )
    if show_value:
        lab = QLabel(""+str(value))
        line.addWidget( lab )
        slider.valueChanged.connect( lambda: lab.setText( ""+str(slider.value()) ) )
    line.addWidget( slider )
    return line, slider
