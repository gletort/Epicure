!!! abstract "Settings to customize EpiCure to user specific preferences"
	_Set your preferences by going to `Plugins>Epicure>Edit preferences`_

You can customize EpiCure to your specific usage by redefining the key or mouse shortcuts and by saving your default plugin state and parameters.

For this, EpiCure generates a file containing all the user settings in your home directory, in the `.napari` folder (which will be created if not there already). The file will be called `epicure_preferences.pkl`. It can be deleted, but then all the user settings will be lost.

At each start of EpiCure, this preference file, if present in the defined path (`$home_directory/.napari/epicure_preferences.pkl`) will be loaded and applied.

## Update EpiCure display settings

To save your prefered plugin set-up (visible options, checked options, some parameter values, default display...), go to the [Display](./Display.md) option in EpiCure and click on the button `Set current settings as default`.

For example, if you displayed the labels as a contour of width 2 (instead of full filled labels), next time you start EpiCure, it will directly display the label as contour of width 2. If you activated the grid visualisation, it will also be directly active.


## Redefine EpiCure shortcuts/colors

You can set-up several EpiCure default ergonomic parameters as the choice of shortcuts or display colors of the interfaces. 
For this, open the `Preferences` option in `Napari>Plugins>EpiCure>Edit preferences`.

### Edit shortcuts

You can redefine EpiCure shortcuts to put your favorite keys instead of EpiCure default ones (reminder, you can see the full list of EpiCure shortcuts by pressing <kbd>a</kbd> when EpiCure is open).
A panel will open on the right side, with a list of shortcuts for each type of EpiCure action (General, Edit, Track, Suspect, Output, Display), under the onglet `Shortcuts Config.`

![preferences interface](./imgs/preferences)

Select the one you wish to edit, change the corresponding shortcut by putting your favorite <kbd>key</kbd> instead of the default one.

🖱️ If the shortcut involves a mouse click, a list of optionnal key (Control, Shift) and of mouse click are proposed instead of a possible key letter.

Click on the button `Save preferences` when all shortcuts have been modified to set them.

??? warning "The new shortcut configuration will be active only at the next EpiCure session." 
	If you already have an EpiCure opened, restart it to apply the new shortcuts.

??? warning "The compability of shortcuts is not checked"
	Avoid to use twice the same shortcut as there is no (in the current version) screening of the shortcut to check their unicity 

### Edit interface colors

To change the colors in the interface (e.g. the buttons color), select the onglet `Display Config.`
Click on the type of interface to change the color. 
Each button is colored by its current color. 
When you click on it, an interface pops-up to allow you to choose a new color and the button color will be modified when you click on `Ok` 
