## Segment with EpySeg

When starting EpiCure, once you have selected the movie to process and the junction channel, you have to load the file containing the segmentation of the epithelia movie. If you haven't done it yet, you can use the `Segment now with EpySeg` button that appears in the `Start EpiCure` interface. 
This option uses the [napari-epyseg](https://github.com/gletort/napari-epyseg) plugin to directly run [EpySeg](https://github.com/baigouy/EPySeg) on the movie. It will run with the default parameters. If you want to change some parameters, either use directly the napari-epyseg plugin within Napari (limited number of options) or use the original distribution of EpySeg (you can launch it with `python -m epyseg` in your python environement).

Note that the option requires to install the napari-epyseg plugin which is not installed by default in the EpiCure release. You can install it by typing `pip install napari-epyseg` in the environement or by going to `Plugins>Install\Uninstall Plugins` in Napari interface.
