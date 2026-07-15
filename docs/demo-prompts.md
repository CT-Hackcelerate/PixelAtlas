#Demo promots
/generate Generate a new CT abdomen study with 200 slices using the existing CT abdomen study.
/generate Generate a new MG study from the existing MG study with ISO_IR 13 specific character set applied to patient name and study description
/generate Generate a new MR brain study with one instance having small circular shutter from existing MR head study
/generate Generate a presentation state object having a graphic annotation - horizonal line at middle of the image and text annotation "CT Head" referencing to the first instance of existing CT head study. It shall appear as a new series in the same study with same patient details and it shall refer to the correct instance.
/generate Generate a new series in existing CT abdomen study with gantry tilt of 30 degree in x - direction in geometry from existing series. So I can have 2 series in same study with same number of instances. 