!!! abstract "Merge temporally two EpiCured movies"
	_ Start it with `Napari>Plugins>EpiCure>Concatenate EpiCured movies`_


To treat a huge movie, it can be convenient to split it temporally in two (or more movies). You can then correct each movie with EpiCure, and recombine it with this option. 
This option can be started in `Napari>Plugins>EpiCure>Concatenate EpiCured movies`.

* Choose the first movie and its corresponding segmentation (and EpiCure .pkl file).
* Choose the second movie and its corresponding segmentation (and EpiCure .pkl file).
* Choose the name of the resulting movie that will be the concatenation of the two movie.

EpiCure will create a new movie and segmentation containing the full movie. The EpiCure additional informations as cell's group, track and lineage will also be merged in the new movie.

!!! warning "One frame must be shared between the two movies" 
	Note that two merge the two movie, you need to keep one common frame: the last frame of the first movie **must** be the first frame of the second movie. 
