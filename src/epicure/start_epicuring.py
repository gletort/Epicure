from napari import current_viewer
from magicgui import magicgui
from napari.utils.history import get_save_history, update_save_history 
import pathlib
import epicure.Utils as ut
from epicure.epicuring import EpiCure
import multiprocessing

"""
   Start EpiCure plugin
   Open the interface to select the movie and associated segmentation to process
"""

def start_epicure():
    hist = get_save_history()
    cdir = hist[0]
    viewer = current_viewer()
    Epic = EpiCure(viewer)
    caxis = None
    cval = 0
    ncpus = int(multiprocessing.cpu_count()*0.5)

    def set_visibility():
        """ Handle the visibility of the advanced parameters """
        get_files.output_dirname.visible = get_files.advanced_parameters.value
        get_files.show_other_chanels.visible = get_files.advanced_parameters.value
        get_files.process_frames_parallel.visible = get_files.advanced_parameters.value
        get_files.nbparallel_threads.visible = get_files.advanced_parameters.value
        get_files.junction_half_thickness.visible = get_files.advanced_parameters.value
        get_files.verbose_level.visible = get_files.advanced_parameters.value
        get_files.allow_gaps.visible = get_files.advanced_parameters.value
        get_files.show_scale_bar.visible = get_files.advanced_parameters.value
        get_files.epithelial_cells.visible = get_files.advanced_parameters.value

    def load_movie():
        """ Load and display the selected movie """
        start_time = ut.start_time()
        nonlocal caxis, cval
        image_file = get_files.image_file.value
        caxis, cval = Epic.load_movie(image_file)
        imgdir = ut.get_directory(image_file)
        get_files.segmentation_file.visible = True
        get_files.segmentation_file.value = pathlib.Path(imgdir)
        labname = Epic.suggest_segfile( get_files.output_dirname.value )
        Epic.set_names( get_files.output_dirname.value )
        if labname is not None:
            get_files.segmentation_file.value = pathlib.Path(labname)
            Epic.read_epicure_metadata()    
        if caxis is not None:
            get_files.junction_chanel.max = cval-1
            get_files.junction_chanel.visible = True
            set_chanel()
        get_files.scale_xy.value = Epic.epi_metadata["ScaleXY"]
        get_files.timeframe.value = Epic.epi_metadata["ScaleT"]
        get_files.unit_xy.value = Epic.epi_metadata["UnitXY"]
        get_files.unit_t.value = Epic.epi_metadata["UnitT"]
        get_files.scale_xy.visible = True
        get_files.unit_xy.visible = True
        get_files.timeframe.visible = True
        get_files.unit_t.visible = True
        get_files.segment_with_epyseg.visible = True
        get_files.allow_gaps.value = bool(Epic.epi_metadata["Allow gaps"])
        get_files.verbose_level.value = int(Epic.epi_metadata["Verbose"])
        get_files.call_button.enabled = True
        ut.show_duration(start_time, header="Movie loaded in ")

    def show_others():
        """ Display other chanels from the initial movie """
        for ochan in range(cval):
            ut.remove_layer(viewer, "MovieChannel_"+str(ochan))
        if get_files.show_other_chanels.value == True:
            Epic.add_other_chanels(int(get_files.junction_chanel.value), caxis)

    def set_chanel():
        """ Set the correct chanel that contains the junction signal """
        start_time = ut.start_time()
        Epic.set_chanel( int(get_files.junction_chanel.value), caxis )
        show_others()
        ut.show_duration(start_time, header="Movie chanel loaded in ")

    def launch_napari_epyseg():
        """ Open napari-epyseg plugin to segment the intensity channel movie """
        try:
            import napari_epyseg
            from napari_epyseg.start_epyseg import run_epyseg
        except:
            ut.show_error( "This option requires the plugin napari-epyseg that is missing.\nInstall it and restart" )
            return
        print("Running EpySeg with default parameters on the movie. To change the settings, use the napari-epyseg plugin outside of EpiCure or EpySeg module directly")
        parameters = {"tile_width":256, "tile_height":256, "overlap_width":32, "overlap_height":32, "model":"epyseg default(v2)", "norm_min":0, "norm_max":1}
        print(Epic.img.shape)
        ut.show_progress( viewer, True )
        segres = run_epyseg( Epic.img, parameters, prog=True )
        ut.show_progress( viewer, False )
        segname = str(get_files.image_file.value)+"_epyseg.tif"
        ut.writeTif( segres, segname, 1.0, "uint8", what="Epyseg results saved in " )
        get_files.segmentation_file.value = segname
        get_files.segment_with_epyseg.visible = False


    @magicgui(call_button="START CURE",
            junction_chanel={"widget_type": "Slider", "min":0, "max": 0},
            segment_with_epyseg = {"widget_type": "PushButton", "label": "Segment now with EpySeg"},
            scale_xy = {"widget_type": "LiteralEvalLineEdit"},
            timeframe = {"widget_type": "LiteralEvalLineEdit"},
            junction_half_thickness={"widget_type": "LiteralEvalLineEdit"},
            nbparallel_threads = {"widget_type": "LiteralEvalLineEdit"},
            verbose_level={"widget_type": "Slider", "min":0, "max": 3},
            )
    def get_files( 
                   image_file = pathlib.Path(cdir),
                   junction_chanel = 0,
                   segmentation_file = pathlib.Path(cdir),
                   segment_with_epyseg = False,
                   scale_xy = 1,
                   unit_xy = "um",
                   timeframe = 1,
                   unit_t = "min",
                   advanced_parameters = False,
                   show_other_chanels = True,
                   show_scale_bar = True,
                   allow_gaps = True,
                   epithelial_cells = True,
                   process_frames_parallel = False,
                   nbparallel_threads = ncpus,
                   junction_half_thickness = 1,
                   output_dirname = "epics",
                   verbose_level = 1,
                   ):
        
        print("Starting")
        imname, imdir, outdir = ut.extract_names( image_file, output_dirname )
        update_save_history(imdir)
        #ut.remove_widget(viewer, "Start EpiCure (epicure)")
        ut.remove_all_widgets( viewer )
        Epic.process_parallel = process_frames_parallel
        Epic.set_verbose( verbose_level )
        Epic.nparallel = nbparallel_threads
        #Epic.load_segmentation(segmentation_file)
        Epic.set_thickness( junction_half_thickness )
        Epic.set_scales(scale_xy, timeframe, unit_xy, unit_t)
        Epic.set_scalebar( show_scale_bar )
        Epic.set_gaps_option( allow_gaps )
        Epic.set_epithelia( epithelial_cells )
        Epic.go_epicure(outdir, segmentation_file)

    set_visibility()
    get_files.call_button.enabled = False
    get_files.segmentation_file.visible = False
    get_files.segment_with_epyseg.visible = False
    get_files.scale_xy.visible = False
    get_files.unit_xy.visible = False
    get_files.timeframe.visible = False
    get_files.unit_t.visible = False
    get_files.junction_chanel.visible = False
    get_files.advanced_parameters.clicked.connect(set_visibility)
    get_files.show_other_chanels.clicked.connect(show_others)
    get_files.image_file.changed.connect(load_movie)
    get_files.junction_chanel.changed.connect(set_chanel)
    get_files.segment_with_epyseg.clicked.connect( launch_napari_epyseg )
    return get_files

