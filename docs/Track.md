!!! abstract "Track temporally the cells"
    _Most track options are in the Track tab of the Main interface_

EpiCure handles tracks by using the same label for the corresponding cell accross frames.
One cell has a unique number (its label), displayed with a specific color assigned by Napari, that corresponds to the track number as well.
The file containing the segmentation with the labelled cells is thus enough to reconstruct the tracks.

Cell divisions are organised in a graph and displayed with the `events` structure (see [Inspect](#Inspect.md#events)).
The graph is a NetworkX object and contains as keys the daugther cells and as values the parent cell.
This implementation is compatible with laptrack's output and Napari Track layer.

EpiCure opens a Tracks layer in Napari that displays the trajectories of each cell (label) centroid.
!!! warning "This layer is very slow to update, so it is NOT updated at each action." 
	A local version of the tracks is kept up-to-date with the modifications done, but not the displayed version. To update the display to the latest version, click on Update tracks.

With the EpiCure Track panel, you can choose a tracking algorithm and tune its parameter. 
It's also possible to track the cells in an other software/plugins. 

## Import/Load tracking
To use tracking from an external software, the cells need to be labelled by their track number to be loaded in EpiCure. 
Cell divisions/merges will not be loaded from external tracks.

### Load TrackMate tracks
In particular, you can perform the cell segmentation and tracking in [TrackMate](https://imagej.net/plugins/trackmate/) and use the Action `Export label image`.
Then load this labelled image as the segmentation file in EpiCure and you will directly get the tracks.
However, the division and extrusion will have to be detected within EpiCure afterward.

## Track with Laptrack

Tracking within EpiCure can be performed with the [Laptrack](https://github.com/yfukai/laptrack) module.
Laptrack will optimize the linking of the cell from one frame to another, and can also include the possibility for cell division or cell merging.
As in our movies, we don't have cell merging biologically, we disabled this feature but it can easily be integrated.

### Laptrack centroids

With this option, Laptrack considers the distance between the centroid of the cells from one frame to another to optimize the linking.
Thus this method has good performance in general when the cell's center displacement are smaller than the size of the cell itself (it's less likely to confuse the cell with its neighbor).

### Laptrack overlap

With this option, Laptrack considers the overlap of the segmented cells from one frame to another to optimize the linking.
This method relies on more information than taking only the cell's centroid as it takes into account the full surface distances.
It necessitates the cell motion to be small enough for the cell to stay mainly within the previous cell surface.

### Add feature cost
With both options, it's also possible to take into account the size or the shape of the cell in the linking calculation.
This will improve the tracking when the cell is similar from one frame to another so it will increase the capacity of the algorithm to "recognize" the cell.
This can be done by checking the `add feature cost` in the interface.

### Drift correction
This option allows to take into account local drift in the tracking algorithm.
When there is a fast local movement of all cells in the same direction, the algorithm is more likely to fail as the distance between the cell centroids or their overlaps will be higher than the distance/overlap with another cell. 
This helps to correct it, by calculating the local overall drift and removing this drift from the distance calculation.

Local drift is estimated with optical flow.
This is however quite slow to calculate, so adding this option will significantly increase the computation time.


### Shortcuts
You can select the `Track` layer in the left part of the interface to change the display properties of this layer.
EpiCure proposes also a few shortcuts to change this display directly without having to select this layer, keeping the `Segmentation` layer selected.
General shortcuts are documented [here](index.md/#general-options).

???+ tip "Shortcut/options"

     _**EpiCure shortcuts are only active when `Segmentation` layer is selected**_

	=== "Track display :wrench:"
	
		|   |     |	
		| ------------ | ------------------------------------ |
		| <kbd>r</kbd> | Show/Hide the Track layer |


---

