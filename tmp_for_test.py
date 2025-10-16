import epicure.epicuring as epicure


main_path = "/media/lxenard/data/Code/EpiCure/trackMateMoiCa"
raw_path = main_path + "/013_crop.tif"

epic = epicure.EpiCure()
epic.verbose = 3  # 0: minimal to 3: debug informations
epic.load_movie(raw_path)
epic.go_epicure()

epic.outputing.output_mode.setCurrentText("All cells")
epic.outputing.save_tm_xml()
