import numpy as np
import os
import time
import math
from skimage.measure import regionprops, find_contours, regionprops_table
from skimage.segmentation import find_boundaries, expand_labels
from napari.utils.translations import trans # type: ignore
from napari.utils.notifications import show_info # type: ignore
from napari.utils import notifications as nt # type: ignore
from skimage.morphology import skeletonize, binary_dilation, disk, binary_closing 
from scipy.ndimage import center_of_mass, find_objects
from scipy.ndimage import label as ndlabel
from scipy.ndimage import binary_opening as ndbinary_opening
from scipy.ndimage import sum as ndsum
from scipy.ndimage import generate_binary_structure as ndi_structure
import pandas as pd
from epicure.laptrack_centroids import LaptrackCentroids
import tifffile as tif # type: ignore
import napari
from napari.utils import progress # type: ignore
from magicgui.widgets import TextEdit
from joblib import Parallel, delayed
from packaging.version import Version

try:
    from skimage.graph import RAG
except:
    from skimage.future.graph import RAG  ## older version of scikit-image

def show_info(message):
    """ Display info in napari """
    nt.show_info(message)

def show_warning(message):
    """ Display a warning in napari (napari function show_warning doesn't work) """
    mynot = nt.Notification(message, nt.NotificationSeverity.WARNING)
    nt.notification_manager.dispatch(mynot)

def show_error(message):
    """ Display an error in napari (napari function show_error doesn't work) """
    mynot = nt.Notification(message, nt.NotificationSeverity.ERROR)
    nt.notification_manager.dispatch(mynot)

def show_debug(message):
    """ Display an info for debug in napari (napari function show_debug doesn't work) """
    print(message)

def show_documentation():
    import webbrowser
    webbrowser.open_new_tab("https://gletort.github.io/Epicure/")
    return

def show_documentation_page(page):
    import webbrowser
    webbrowser.open_new_tab("https://gletort.github.io/Epicure/"+page)
    return

def show_progress( viewer, show ):
    """ Show.hide the napari activity bar to see processing progress """
    viewer.window._status_bar._toggle_activity_dock( show )

def start_progress( viewer, total, descr=None ):
    """ Start the progress bar """
    show_progress( viewer, True)
    progress_bar = progress( total )
    if descr is not None:
        progress_bar.set_description( descr )
    return progress_bar

def close_progress( viewer, progress_bar ):
    """ Close the progress bar """
    progress_bar.close()
    show_progress( viewer, False)

#### Handle versions of napari
def version_napari_above( compare_version ):
    """ Compare if the current version of napari is above given version """
    return Version(napari.__version__) > Version(compare_version)

def get_directory(imagepath):
    return os.path.dirname(imagepath)

def extract_names(imagepath, subname="epics", mkdir=True):
    imgname = os.path.splitext(os.path.basename(imagepath))[0]
    imgdir = os.path.dirname(imagepath)
    resdir = os.path.join(imgdir, subname)
    if (not os.path.exists(resdir)) and mkdir:
        os.makedirs(resdir)
    return imgname, imgdir, resdir

def extract_names_segmentation(segpath):
    """ Get the output directory and imagename from the segmentation filename """
    imgname = os.path.splitext(os.path.basename(segpath))[0]
    if imgname.endswith("_labels"):
        imgname = imgname[:(len(imgname)-7)]
    imgdir = os.path.dirname(segpath)
    return imgname, imgdir
    
def suggest_segfile(out, imgname):
    """ Check if a segmentation file from EpiCure already exists """
    segfile = os.path.join(out, imgname+"_labels.tif")
    if os.path.exists(segfile):
        return segfile
    else:
        return None

def found_segfile( filepath ):
    """ Check if the segmentation file exists """
    return os.path.exists( filepath )
    
def get_filename(outdir, imgname):
    return os.path.join( outdir, imgname )

def napari_info(text):
    show_info(text)

def create_text_window( name ):
    """ Create and display help text window """
    blabla = TextEdit()
    blabla.name = name 
    blabla.show()
    return blabla

def napari_shortcuts():
    """ Write main napari shortcuts list """
    text = "---- Main napari default shortcuts ----\n"
    text += " -- view options \n"
    text += "  <Ctrl+R> reset view \n"
    text += "  <Ctrl+Y> switch 2D/3D view mode \n"
    text += "  <Ctrl+G> switch Grid/Overlay view mode \n"
    text += "  <left arrow> got to previous frame \n"
    text += "  <right arrow> got to next frame \n"
    text += "\n"
    text += " -- labels options \n"
    text += "  <2> paint brush mode \n"
    text += "  <3> fill mode \n"
    text += "  <4> pick mode (select label) \n"
    text += "  <[> or <]> increase/decrease the paint brush size \n"
    text += "  <p> activate/deactivate preserve labels option \n"
    return text

def removeOverlayText(viewer):
    viewer.text_overlay.text = trans._("")
    viewer.text_overlay.visible = False

def getOverlayText(viewer):
    return viewer.text_overlay.text

def setOverlayText(viewer, text, size=12 ):
    viewer.text_overlay.text = trans._(text)
    viewer.text_overlay.position = "top_left"
    viewer.text_overlay.visible = True
    viewer.text_overlay.font_size = size
    viewer.text_overlay.color = "white"
    viewer.text_overlay.opacity = 1

def showOverlayText(viewer, vis=None):
    if vis is None:
        viewer.text_overlay.visible = not viewer.text_overlay.visible
    else:
        viewer.text_overlay.visible = vis 

def reactive_bindings(layer, mouse_drag, key_map):
    """ Reactive the mouse and key event bindings on layer """
    layer.mouse_drag_callbacks = mouse_drag
    layer.keymap.update(key_map)

def clear_bindings(layer):
    """ Clear and returns the current event bindings on layer """
    old_mouse_drag = layer.mouse_drag_callbacks.copy()
    old_key_map = layer.keymap.copy()
    layer.mouse_drag_callbacks = []
    layer.keymap.clear()
    return old_mouse_drag, old_key_map

def is_binary( img ):
    """ Test if more than 2 values (skeleton or labelled image) """
    return all(len(np.unique(frame)) <= 2 for frame in img)

def set_frame(viewer, frame, scale=1):
    """ Set current frame """
    viewer.dims.set_point(0, frame*scale)

def set_active_layer(viewer, layname):
    """ Set the current Napari active layer """
    if layname in viewer.layers:
        viewer.layers.selection.active = viewer.layers[layname]

def set_visibility(viewer, layname, vis):
    """ Set visibility of layer layname if exists """
    if layname in viewer.layers:
        viewer.layers[layname].visible = vis

def remove_layer(viewer, layname):
    if layname in viewer.layers:
        viewer.layers.remove(layname)

def remove_widget(viewer, widname):
    if widname in viewer.window._dock_widgets:
        wid = viewer.window._dock_widgets[widname]
        wid.setDisabled(True)
        try:
            wid.disconnect()
        except Exception:
            pass
        del viewer.window._dock_widgets[widname]
        wid.destroyOnClose()

def remove_all_widgets( viewer ):
    """ Remove all widgets """
    viewer.window.remove_dock_widget("all")

def opentif(imagepath, verbose=True):
    img = tif.TiffFile(imagepath)
    metadata = img.imagej_metadata
    #print(metadata)
    scale = 1
    scalet = 1
    unitxy = "um"
    unitt = "min"
    nchan = -1
    if metadata is not None:
        if verbose:
            print(metadata)
        try:
            info = metadata["Info"]
            if info is not None: 
                metadatas = (info).splitlines()
                scale = float(metadatas[-4].split()[2])*1000000
        except:
            metadatas = None
        try:
            if metadata['physicalsizex'] is not None:
                scale = float(metadata['physicalsizex'])
            if metadata['finterval'] is not None:
                scalet = float(metadata['finterval'])
            if 'unit' in metadata:
                if metadata['unit'] is not None:
                    unitxy = metadata['unit']
        except:
            metadatas = None
            #print(info)
        try:
            nchan = metadata["channels"]
            print("Nb chanels found: "+str(nchan))
        except:
            nchan = -1
    image = img.asarray()
    img.close()
    return image, nchan, scale, unitxy, scalet, unitt

def writeTif(img, imgname, scale, imtype, what=""):
    """ Write image in tif format """
    if len(img.shape) == 2:
        tif.imwrite(imgname, np.array(img, dtype=imtype), imagej=True, resolution=[1./scale, 1./scale], metadata={'unit': 'um', 'axes': 'YX'})
    else:
        try:
            tif.imwrite(imgname, np.array(img, dtype=imtype), imagej=True, resolution=[1./scale, 1./scale], metadata={'unit': 'um', 'axes': 'TYX'}, compression="zstd")
        except:
            tif.imwrite(imgname, np.array(img, dtype=imtype), imagej=True, resolution=[1./scale, 1./scale], metadata={'unit': 'um', 'axes': 'TYX'})
    show_info(what+" saved in "+imgname)

def appendToTif(img, imgname):
    """ Append to RGB tif the current image """
    tif.imwrite(imgname, img, photometric="rgb", append=True)

def getCellValue(label_layer, event):
    """ Get the label under the click """
    vis = label_layer.visible
    if vis == False:
        label_layer.visible = True
    label = label_layer.get_value(position=event.position, view_direction = event.view_direction, dims_displayed=event.dims_displayed, world=True)
    if vis == False:
        ## put it back to not visible state
        label_layer.visible = vis
    return label

def setCellValue(layer, label_layer, event, newvalue, layer_frame=None, label_frame=None):
    # get concerned label (under the cursor), layer has to be visible for this
    vis = label_layer.visible
    if vis == False:
        label_layer.visible = True
    label = label_layer.get_value(position=event.position, view_direction = event.view_direction, dims_displayed=event.dims_displayed, world=True)
    label_layer.visible = vis
    if label is not None and label > 0:
        # if the seg image is 2D (single frame), label_frame will be None
        if label_frame is not None and label_frame >= 0:
            ldata = label_layer.data[label_frame,:,:]
        else:
            ldata = label_layer.data
        # if the layer is 2D (single frame), layer_frame will be None
        if layer_frame is not None and layer_frame >= 0:
            #slice_coord = tuple(sc[keep_coords] for sc in slice_coord)
            cdata = layer.data[layer_frame,:,:]
        else:
            cdata = layer.data
            #slice_coord = tuple(sc[keep_coords] for sc in slice_coord)

        cdata[np.where(ldata==label)] = newvalue
        layer.refresh()
        return label

def thin_seg_one_frame( segframe ):
    """ Boundaries of the frame one pixel thick """
    bin_img = binary_closing( find_boundaries(segframe, connectivity=2, mode="outer"), footprint=np.ones((3,3)) )
    skel = skeletonize( bin_img )
    skel = copy_border( skel, bin_img )
    return skeleton_to_label( skel, segframe )
    
def copy_border( skel, bin ):
    """ Copy the pixel border onto skeleton image """
    skel[[0, -1], :] = bin[[0, -1], :]  # top and bottom borders
    skel[:, [0, -1]] = bin[:, [0, -1]]  # left and right borders
    return skel
    
def get_skeleton( seg, viewer=None, verbose=0, parallel=0 ) :
    """ convert labels movie to skeleton (thin boundaries) """
    startt = start_time()
    if viewer is not None:
        show_progress( viewer, show=True )

    def frame_skeleton( frame ):
        """ Calculate skeleton on one frame """
        expz = expand_labels( frame, distance=1 )
        frame_skel = np.zeros( frame.shape, dtype="uint8" )
        frame_skel[ (frame==0) * (expz>0) ] = 1
        return frame_skel
        
    if parallel > 0:
        skel = Parallel( n_jobs=parallel )(
            delayed(frame_skeleton)(frame) for frame in seg
        )
        skel = np.array(skel)
    else:
        skel = np.zeros(seg.shape, dtype="uint8")
        for z in progress(range(seg.shape[0])):
            expz = expand_labels( seg[z], distance=1 )
            skel[z][(seg[z] == 0) *(expz > 0)] = 1
    if verbose > 0:
        show_duration(startt, header="Skeleton calculted in ")
    if viewer is not None:
        show_progress( viewer, show=False )
    return skel


def setLabelValue(layer, label_layer, event, newvalue, layer_frame=None, label_frame=None):
    """ Change the label value under event position and returns its old value """
    ## get concerned label (under the cursor), layer has to be visible for this
    vis = label_layer.visible
    if vis == False:
        label_layer.visible = True
    label = label_layer.get_value(position=event.position, view_direction = event.view_direction, dims_displayed=event.dims_displayed, world=True)
    label_layer.visible = vis
    
    if label > 0:
        inds = getLabelIndexes( label_layer.data, label, label_frame )
        setNewLabel(layer, inds, newvalue, add_frame=layer_frame)
        layer.refresh()
        return label
    return None

def getLabelIndexes(label_data, label, frame):
    """ Get the indixes at which label_layer is label for given frame """
    # if the seg image is 2D (single frame), frame will be None
    if frame is not None and frame >= 0:
        ldata = label_data[frame,:,:]
    else:
        ldata = label_data
    return np.argwhere( ldata==label ).tolist()

def getLabelIndexesInFrame(frame_data, label):
    """ Get the indexes at which frame data is label """
    # if the seg image is 2D (single frame), frame will be None
    return np.argwhere( frame_data==label ).tolist()

def changeLabel( label_layer, old_value, new_value ):
    """ replace the value of label old-value by new_value """
    index = np.argwhere( label_layer.data==old_value ).tolist()
    setNewLabel( label_layer, index, new_value )

def setNewLabel(label_layer, indices, newvalue, add_frame=None, return_old=True):
    """ Change the label of all the pixels indicated by indices """
    indexs = np.array(indices).T
    if add_frame is not None:
        indexs = np.vstack((np.repeat(add_frame, indexs.shape[1]), indexs))
    changed_indices = label_layer.data[tuple(indexs)] != newvalue
    inds = tuple(x[changed_indices] for x in indexs)
    oldvalues = None
    if return_old:
        oldvalues = label_layer.data[inds]
    if isinstance(newvalue, list):
        newvalue = np.array(newvalue)[np.where(changed_indices)[0]]
    label_layer.data_setitem( inds, newvalue )
    return inds, newvalue, oldvalues 

def convert_coords( coord ):
    """ Get the time frame, and the 2D coordinates as int """
    int_coord = tuple(np.round(coord).astype(int))
    tframe = int(coord[0])
    int_coord = int_coord[1:3]
    return tframe, int_coord

def outerBBox2D(bbox, imshape, margin=0):
    if (bbox[0]-margin) <= 0:
        return True
    if (bbox[2]+margin) >= imshape[0]:
        return True
    if (bbox[1]-margin) <= 0:
        return True
    if (bbox[3]+margin) >= imshape[1]:
        return True
    return False

def isInsideBBox( bbox, obbox ):
    """ Check if bbox is included in obbox """
    if (bbox[0] >= obbox[0]) and (bbox[1] >= obbox[1]):
        return (bbox[2] <= obbox[2]) and (bbox[3] <= obbox[3])
    return False

def setBBox(position, extend, imshape):
    bbox = [
        max(int(position[0] - extend), 0),
        max(int(position[1] - extend), 0),
        max(int(position[2] - extend), 0),
        min(int(position[0] + extend), imshape[0]),
        min(int(position[1] + extend), imshape[1]),
        min(int(position[2] + extend), imshape[2])
    ]
    return bbox

def setBBoxXY(position, extend, imshape):
    bbox = [
        max(int(position[0]), 0),
        max(int(position[1] - extend), 0),
        max(int(position[2] - extend), 0),
        min(int(position[0] + 1), imshape[0]),
        min(int(position[1] + extend), imshape[1]),
        min(int(position[2] + extend), imshape[2])
    ]
    return bbox

def getBBox2DFromPts(pts, extend, imshape):
    """ Get the bounding box surrounding all the points, plus a margin """
    arr = np.array(pts)
    ptsdim = arr.shape[1]
    if ptsdim == 2:
        bbox = [
            max( int(np.min(arr[:,0])) - extend, 0), 
            max( int(np.min(arr[:,1])) - extend, 0), 
            min( int(np.max(arr[:,0]))+1+extend, imshape[0]), 
            min( int(np.max(arr[:,1]))+1+extend, imshape[1] )
            ]
    if ptsdim == 3:
        bbox = [
            max( int(np.min(arr[:,1])) -extend, 0), 
            max( int(np.min(arr[:,2])) - extend, 0),
            min( int(np.max(arr[:,1]))+1 + extend, imshape[0]), 
            min( int(np.max(arr[:,2]))+1 + extend, imshape[1] )
            ]

    return bbox

def getBBoxFromPts(pts, extend, imshape, outdim=None, frame=None):
    arr = np.array(pts)
    ## get if points are 2D or 3D
    ptsdim = arr.shape[1]
    ## if not imposed, output the same dimension as input points
    if outdim is None:
        outdim = ptsdim
    ## Get bounding box from points according to dimensions
    if ptsdim == 2:
        if outdim == 2:
            bbox = [int(np.min(arr[:,0])), int(np.min(arr[:,1])), int(np.max(arr[:,0]))+1, int(np.max(arr[:,1]))+1]
        else:
            bbox = [frame, int(np.min(arr[:,0])), int(np.min(arr[:,1])), frame+1, int(np.max(arr[:,0]))+1, int(np.max(arr[:,1]))+1]
    if ptsdim == 3:
        if outdim == 2:
            bbox = [int(np.min(arr[:,1])), int(np.min(arr[:,2])), int(np.max(arr[:,1]))+1, int(np.max(arr[:,2]))+1]
        else:
            bbox = [int(np.min(arr[:,0])), int(np.min(arr[:,1])), int(np.min(arr[:,2])), int(np.max(arr[:,0]))+1, int(np.max(arr[:,1]))+1, int(np.max(arr[:,2]))+1]
    if extend > 0:
        for i in range(outdim):
            if i < 2:
                bbox[(outdim==3)+i] = max( bbox[(outdim==3)+i] - extend, 0)
                bbox[(outdim==3)+i+outdim] = min(bbox[(outdim==3)+i+outdim] + extend, imshape[(outdim==3)+i] )
    return bbox

def inside_bounds( pt, imshape ):
    """ Check if given point is inside image limits """
    return all(0 <= pt[i] < imshape[i] for i in range(len(pt)))

def extendBBox2D( bbox, extend_factor, imshape ):
    """ Extend bounding box with given margin """
    extend = max(bbox[2] - bbox[0], bbox[3] - bbox[1]) * extend_factor
    bbox = np.array(bbox)
    bbox[:2] = np.maximum(bbox[:2] - extend, 0)
    bbox[2:] = np.minimum(bbox[2:] + extend, imshape[:2])
    return bbox

def getBBox2D(img, label):
    """ Get bounding box of label """
    mask = (img==label)*1
    props = regionprops(mask)
    for prop in props:
        bbox = prop.bbox
        return bbox

def getPropLabel(img, label):
    """ Get the properties of label """
    mask = np.uint8(img == label)
    props = regionprops(mask)
    return props[0]

def getBBoxLabel(img, label):
    """ Get bounding box of label """
    mask_ind = np.where(img==label)
    if len(mask_ind) <= 0:
        return None
    dim = len(img.shape)
    bbox = np.zeros(dim*2, int)
    for i in range(dim):
        bbox[i] = int(np.min(mask_ind[i]))
        bbox[i+dim] = int(np.max(mask_ind[i]))+1
    return bbox

def getBBox2DMerge(img, label, second_label): #, checkTouching=False):
    """ Get bounding box of two labels and check if they are in contact """
    mask = np.isin( img, [label, second_label] )
    props = regionprops(mask*1)
    return props[0].bbox, mask 


def frame_to_skeleton(frame, connectivity=1):
    """ convert labels frame to skeleton (thin boundaries) """
    return skeletonize( find_boundaries(frame, connectivity=connectivity, mode="outer") )

def remove_boundaries(img):
    """ Put the boundaries pixels between labels as 0 """
    bound = frame_to_skeleton( img, connectivity=1 )
    img[bound>0] = 0
    return img

def ind_boundaries(img):
    """ Get indices of the boundaries pixels between two labels """
    bound = frame_to_skeleton( img, connectivity=1 )
    return np.argwhere(bound>0)

def checkTouchingLabels(img, label, second_label):
    """ Returns if labels are in contact (1-2 pixel away) """
    disk_one = disk(radius=1)
    maska = binary_dilation(img==label, footprint=disk_one)
    maskb = binary_dilation(img==second_label, footprint=disk_one)
    return np.any(maska & maskb)

def positionsIn2DBBox( positions, bbox ):
    """ Shift all the positions to their position inside the 2D bounding box """
    return [positionIn2DBBox( pos, bbox ) for pos in positions ]

def positions2DIn2DBBox( positions, bbox ):
    """ Shift all the positions to their position inside the 2D bounding box """
    return [position2DIn2DBBox( pos, bbox ) for pos in positions ]

def positionIn2DBBox(position, bbox):
    """ Returns the position shifted to its position inside the 2D bounding box """
    return (int(position[1]-bbox[0]), int(position[2]-bbox[1]))

def position2DIn2DBBox(position, bbox):
    """ Returns the position shifted to its position inside the 2D bounding box """
    return (int(position[0]-bbox[0]), int(position[1]-bbox[1]))

def toFullImagePos(indices, bbox):
    indices = np.array(indices)
    return np.column_stack((indices[:, 0] + bbox[0], indices[:, 1] + bbox[1])).tolist()

def addFrameIndices( indices, frame ):
    return [ [frame, ind[0], ind[1]] for ind in indices ]

def shiftFrameIndices( indices, add_frame ):
    if isinstance( indices, list ):
        indices = np.array(indices)
    indices[:, 0] += add_frame
    return indices.tolist()

def shiftFrames( indices, frames ):
    if isinstance( indices, list ):
        indices = np.array(indices)
    indices[:, 0] = frames[indices[:, 0]]
    return indices.tolist()

def toFullMoviePos( indices, bbox, frame=None ):
    """ Replace indexes inside bounding box to full movie indexes """
    indices = np.array(indices)
    if frame is not None:
        frame_arr = np.full(len(indices), frame)
        return np.column_stack((frame_arr, indices[:, 0] + bbox[0], indices[:, 1] + bbox[1]))
    if len(bbox) == 6:
        return np.column_stack((indices[:, 0] + bbox[0], indices[:, 1] + bbox[1], indices[:, 2] + bbox[2]))
    return np.column_stack((indices[:, 0], indices[:, 1] + bbox[0], indices[:, 2] + bbox[1]))

def cropBBox(img, bbox):
    slices = tuple(slice(bbox[i], bbox[i + len(bbox) // 2]) for i in range(len(bbox) // 2))
    return img[slices]

def crop_twoframes( img, bbox, frame ):
    """ Crop bounding box with two frames """
    return np.copy(img[(frame-1):(frame+1), bbox[0]:bbox[2], bbox[1]:bbox[3]])

def cropBBox2D(img, bbox):
    return img[bbox[0]:bbox[2], bbox[1]:bbox[3]]

def setValueInBBox2D(img, setimg, bbox):
    bbimg = img[bbox[0]:bbox[2], bbox[1]:bbox[3]] 
    bbimg[setimg>0]= setimg[setimg>0]

def addValueInBBox(img, addimg, bbox):
    img[bbox[0]:bbox[3], bbox[1]:bbox[4], bbox[2]:bbox[5]] = img[bbox[0]:bbox[3], bbox[1]:bbox[4], bbox[2]:bbox[5]] + addimg

def set_maxlabel(layer):
    layer.mode = "PAINT"
    layer.selected_label = np.max(layer.data)+1
    layer.refresh()

def set_label(layer, lab):
    layer.mode = "PAINT"
    layer.selected_label = lab
    layer.refresh()

def get_free_labels( used, nlab ):
    """ Get n-th unused label (not in used list) """
    maxlab = max(used)+1
    unused = list(set(range(1, maxlab)) - set(used))
    if nlab < len(unused):
        return unused[0:nlab]
    else:
        return unused+list(range(maxlab+1, maxlab+1+(nlab-len(unused))))

def get_next_label(layer, label):
    """ Get the next unused label starting from label """
    used = np.unique(layer.data)
    i = label+1
    while i < np.max(used):
        if i>0 and (i not in used):
            return i
        i = i + 1
    return i+1

def relabel_layer(layer):
    maxlab = np.max(layer.data)
    used = np.unique(layer.data)
    nlabs = len(used)
    if nlabs == maxlab:
        #print("already relabelled")
        return
    for j in range(1, nlabs+1):
        if j not in used:
            layer.data[layer.data==maxlab] = j
            maxlab = np.max(layer.data)
    show_info("Labels reordered")
    layer.refresh()

def inv_visibility(viewer, layername):
    """ Switch the visibility of a layer """
    if layername in viewer.layers:
        layer = viewer.layers[layername]
        layer.visible = not layer.visible

######## Measure labels
def average_area( seg ):
    """ Average area of labels (cells) """
    # Label the input image
    labeled_array, num_features = ndlabel(seg)
    
    if num_features == 0:
        return 0.0
    
    # Calculate the area of each label
    areas = ndsum(seg > 0, labeled_array, index=np.arange(1, num_features + 1))
    # Calculate the average area
    avg_area = np.mean(areas)   
    return avg_area


def summary_labels( seg ):
    """ Summary of labels (cells) measurements """
    props = regionprops(seg)
    avg_duration = 0
    avg_area = 0.0
    for prop in props:
        bbox = prop.bbox
        nz = 1
        if len(bbox)>4:
            nz = bbox[3]-bbox[0]
        avg_duration += nz
        avg_area += prop.area/nz
    return len(props), avg_duration/len(props), avg_area/len(props) 

def labels_in_cell( sega, segb, label ):
    """ Look at the labels of segb inside label from sega """
    cell = np.isin( sega, [label] )
    labelb = segb[ cell ]
    cell_area = np.sum( cell*1, axis=None )
    filled_area = np.sum( labelb>0 )
    nobj = len(np.unique( labelb ))
    if 0 in labelb:
        nobj = nobj - 1
    return nobj, (filled_area/cell_area), np.unique(labelb)


def match_labels( sega, segb ):
    """ Match the labels of the two segmentation images """
    region_properties = ["label", "centroid"]

    df0 = pd.DataFrame( regionprops_table( sega, properties=region_properties ) )
    df0["frame"] = 0
    df1 = pd.DataFrame( regionprops_table( segb, properties=region_properties ) )
    df1["frame"] = 1
    df = pd.concat([df0, df1])

    ## Link the two frames with LapTrack tracking
    laptrack = LaptrackCentroids(None, None)
    laptrack.max_distance = 10 
    laptrack.set_region_properties(with_extra=False)
    laptrack.splitting_cost = False ## disable splitting option
    laptrack.merging_cost = False ## disable merging option
    labels = list(np.unique(segb))
    if 0 in labels:
        labels.remove(0)
    parent_labels = laptrack.twoframes_track(df, labels)
    return parent_labels, labels

def labels_table( labimg, intensity_image=None, properties=None, extra_properties=None ):
    """ Returns the regionprops_table of the labels """
    if properties is None:
        properties = ['label', 'centroid']
    if intensity_image is not None:
        return regionprops_table( labimg, intensity_image=intensity_image, properties=properties, extra_properties=extra_properties )
    return regionprops_table( labimg, properties=properties, extra_properties=extra_properties )

def labels_to_table( labimg, frame ):
    """ Get label and centroid """
    labels = np.unique(labimg.ravel())
    labels = labels[labels != 0]
    centroids = center_of_mass(labimg, labels=labimg, index=labels)
    table = np.column_stack((labels, np.full(len(labels), frame), centroids))
    return table.astype(int)

def labels_to_table_v1( labimg, frame ):
    """ Get label and centroid """
    props = regionprops( labimg )
    n = len(props)
    if n == 0:
        return np.empty( (0, 2+labimg.ndim) )
    res = np.zeros( (n, 2+labimg.ndim), dtype=int )
    for i, prop in enumerate(props):
        res[i, 0] = prop.label
        res[i, 1] = frame
        res[i,:2] = np.array(prop.centroid).astype(int)
    return res

def non_unique_labels( labimg ):
    """ Check if contains only unique labels """
    relab, nlabels = ndlabel( labimg )
    return nlabels > (len( np.unique(labimg) )-1)

def reset_labels( labimg, closing=True ):
    """ Relabel in 3D all labels (unique labels) """
    s = ndi_structure(3,1)
    ## ignore 3D connectivity (unique labels in all frames)
    s[0,:,:] = 0
    s[2,:,:] = 0
    if closing:
        labimg = ndbinary_opening( labimg, iterations=1, structure=s )
    lab = ndlabel( labimg, structure=s )[0]
    return lab

    
def skeleton_to_label( skel, labelled ):
    """ Transform a skeleton to label image with numbers from labelled image """
    labels = ndlabel( np.invert(skel) )[0]
    new_labels = find_objects( labels )
    newlab = np.zeros( skel.shape, np.uint32 )   
    for i, obj_slice in enumerate(new_labels):
        if (obj_slice is not None):
            if ((obj_slice[1].stop-obj_slice[1].start) <= 2) and ((obj_slice[0].stop-obj_slice[0].start) <= 2):
                continue
            label_mask = labels[obj_slice] == (i+1)
            label_values = labelled[obj_slice][label_mask]
            labvals, counts = np.unique(label_values, return_counts=True )
            labval = labvals[ np.argmax(counts) ]
            newlab[obj_slice][label_mask] = labval
    return newlab

def get_most_frequent( labimg, img, label ):
    """ Returns which label is the most frequent in mask """
    mask = labimg == label
    vals, counts = np.unique( img[mask], return_counts=True )
    return vals[ np.argmax(counts) ]

def labels_properties( labimg ):
    """ Returns basic label properties """
    return regionprops( labimg )

def labels_bbox( labimg ):
    """ Returns for each label its bounding box """
    return regionprops_table( labimg, properties=('label', 'bbox') )

def tuple_int(pos):
    if len(pos) == 3:
        return ( (int(pos[0]), int(pos[1]), int(pos[2])) )
    if len(pos) == 2:
        return ( (int(pos[0]), int(pos[1])) )

def get_consecutives( ordered ):
    """ Returns the list of consecutives integers (already sorted) """
    gaps = [ [start, end] for start, end in zip( ordered, ordered[1:] ) if start+1 < end ]
    edges = iter( ordered[:1] + sum(gaps, []) + ordered[-1:] )
    return list( zip(edges, edges) )


def prop_to_pos(prop, frame):
    return np.array( (frame, int(prop.centroid[0]), int(prop.centroid[1])) )

def current_frame(viewer):
    return int(viewer.cursor.position[0])

def distance( x, y ):
    """ 2d distance """
    return math.sqrt( (x[0]-y[0])*(x[0]-y[0]) + (x[1]-y[1])*(x[1]-y[1]) )

def interm_position( prop, a, b ):
    res = [0,0]
    res[0] = a[0] + prop*(b[0]-a[0])
    res[1] = a[1] + prop*(b[1]-a[1])
    return res

def nb_frames( seg, lab ):
    """ Return nb frames with label lab """
    labseg = seg==lab
    return np.sum( np.any(labseg, axis=(1,2)) )

def keep_orphans( img, comp_img, klabels ):
    """ Keep only labels that doesn't have a follower """
    valid_labels = np.setdiff1d(img[0], klabels)
    if (len(valid_labels)==1) and (valid_labels[0]==0):
        return
    labels = [val for val in valid_labels if (val!=0) and np.any(comp_img==val)]
    mask = np.isin(img, labels)
    img[mask] = 0

def keep_orphans_3d( img, klabels ):
    """ Keep only orphans labels or lab and olab """
    for label in np.unique(img[1]):
        if label not in klabels:
            if nb_frames( img, label ) == 2:
                img[img==label] = 0
    return img

def mean_nonzero( array ):
    nonzero = np.count_nonzero(array)
    if nonzero > 0:
        return np.sum(array)/nonzero
    return 0

def get_contours( binimg ):
    """ Return the contour of a binary shape """
    return find_contours( binimg )

###### Connectivity labels
def touching_labels( img, expand=3 ):
    """ Extends the labels to make them touch """
    return expand_labels( img, distance=expand )

def connectivity_graph( img, distance ):
    """ Returns the region adjancy graph of labels """
    touchlab = touching_labels( img, expand=distance )
    return RAG( touchlab, connectivity=2 )

def get_neighbor_graph( img, distance ):
    """ Returns the adjancy graph without bg, so only neigbor cells """
    graph = connectivity_graph( img, distance=distance ) # be sure that labels touch and get the graph
    graph.remove_node(0) if 0 in graph.nodes else None
    return graph

def get_neighbors( label, graph ):
    """ Get the list of neighbors of cell 'label' from the graph """
    if label in graph.nodes:
        return list(graph.adj[label])
    return []
    
def get_boundary_cells( img ):
    """ Return cells on tissu boundary in current image """ 
    dilated = binary_dilation( img > 0, disk(3) )
    zero = np.invert( dilated )
    zero = binary_dilation( zero, disk(5) )
    touching = np.unique( img[ zero ] ).tolist()
    if 0 in touching:
        touching.remove(0)
    return touching
    
def get_border_cells( img ):
    """ Return cells on border in current image """ 
    height = img.shape[1]
    width = img.shape[0]
    labels = list( np.unique( img[ :, 0:2 ] ) )   ## top border
    labels += list( np.unique( img[ :, (height-2): ] ) )   ## bottom border
    labels += list( np.unique( img[ 0:2,] ) )   ## left border
    labels += list( np.unique( img[ (width-2):,] ) )   ## right border
    return labels

def count_neighbors( label_img, label ):
    """ Get the number of neighboring labels of given label """
    ## much slower than using the RAG graph
    # Dilate the labeled image
    dilated_mask = binary_dilation( label_img==label, disk(1) )
    nonzero = np.nonzero( dilated_mask)
        
    # Find the unique labels in the dilated region, excluding the current label and background
    neighboring_labels = np.unique( label_img[nonzero] ).tolist()
        
    # Add the number of unique neighboring labels
    return len(neighboring_labels) - 1 - 1*(0 in neighboring_labels) ## don't count itself or 0

def get_cell_radius( label, labimg ):
    """ Get the radius of the cell label in labimg (2D) """
    area = np.sum( labimg == label )
    return math.sqrt( area / math.pi )


####### Distance measures

def consecutive_distances( pts_pos ):
    """ Distance travelled by the cell between each frame """
    diff = np.diff( pts_pos, axis=0 )
    disp = np.linalg.norm(diff, axis=1)
    return disp

def velocities( pts_pos ):
    """ Velocity of the cell between each frame (average between previous and next) """
    diff = np.diff( pts_pos, axis=0 ).astype(float)
    diff = np.vstack( (diff[0], diff) )
    diff = np.vstack( (diff, diff[-1]) )
    kernel=np.array([0.5,0.5])
    adiff = np.zeros( (len(diff)+1, 3) )
    for i in range(3):
        adiff[:,i] = np.convolve( diff[:,i], kernel )
    adiff = adiff[1:-1]
    disp = np.linalg.norm(adiff[:,1:3], axis=1)
    dt = adiff[:,0] 
    return disp/dt

def total_distance( pts_pos ):
    """ Total distance travelled by point with coordinates xpos and ypos """
    diff = np.diff( pts_pos, axis=0 )
    disp = np.linalg.norm(diff, axis=1)
    return np.sum(disp)

def net_distance( pts_pos ):
    """ Net distance travelled by point with coordinates xpos and ypos """
    disp = pts_pos[len(pts_pos)-1] - pts_pos[0]
    return np.sum( np.sqrt( np.square(disp[0]) + np.square(disp[1]) ) )


###### Time measures
def start_time():
    return time.time()

def show_duration(start_time, header=None):
    if header is None:
        header = "Processed in "
    #show_info(header+"{:.3f}".format((time.time()-start_time)/60)+" min")
    print(header+"{:.3f}".format((time.time()-start_time)/60)+" min")

###### Preferences/shortcuts 

def shortcut_click_match( shortcut, event ):
    """ Test if the click event corresponds to the shortcut """
    button = 1
    if shortcut["button"] == "Right":
        button = 2
    if event.button != button:
        return False
    if "modifiers" in shortcut.keys():
        return set(list(event.modifiers)) == set(shortcut["modifiers"])
    else:
        if len(event.modifiers) > 0:
            return False
        return True
        
def print_shortcuts( shortcut_group ):
    """ Put to text the subset of shortcuts """
    text = ""
    for short_name, vals in shortcut_group.items():
        if vals["type"] == "key":
            text += "  <"+vals["key"]+"> "+vals["text"]+"\n"
        if vals["type"] == "click":
            modif = ""
            if "modifiers" in vals.keys():
                modifiers = vals["modifiers"]
                for mod in modifiers:
                    modif += mod+"-"
            text += "  <"+modif+vals["button"]+"-click> "+vals["text"]+"\n"
    return text


