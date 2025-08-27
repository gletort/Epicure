# Installation

## From Napari interface
EpiCure is a Napari plugin, in python. 
You can install it either through an already installed Napari instance by going in Napari to `Plugins>Install/Uninstall`, search for `Epicure` and click `Install`.
You could have version issues between the different modules installed in your environment and EpiCure dependencies, in this case it is recommended to create a new virtual environnement specific for EpiCure.

## From virtual environnement
To install EpiCure in a new environnement, you should create a new virtual environnement or activate an exisiting compatible one.

### Create a new virtual environement
 You can create a virtual environement [with venv](https://www.geeksforgeeks.org/create-virtual-environment-using-venv-python/) or anaconda (you may need to install anaconda, see here: [on windows](https://www.geeksforgeeks.org/how-to-install-anaconda-on-windows/), [on macOS](https://www.geeksforgeeks.org/installation-guide/how-to-install-anaconda-on-macos/?ref=ml_lbp) or [on linux](https://www.geeksforgeeks.org/how-to-install-anaconda-on-linux/) ). 

Then use the Anaconda interface to create a new virtual environement with the desired python version, or [through the Terminal](https://www.geeksforgeeks.org/set-up-virtual-environment-for-python-using-anaconda/).

For example, in a terminal, once conda is installed, you can create a new environnement by typing:
```
conda create -n epicurenv python=3.10
```

### Install EpiCure 
Once you have created/identified a virtual environnement, type in the terminal:
``` 
conda activate epicurenv
```
to activate it (and start working in that environnement).

Type in the activated environnement window:

```
pip install epicure 
```
to install EpiCure with its dependencies.

## Compatibility/Dependencies
