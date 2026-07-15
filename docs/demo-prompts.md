# Demo Prompts

1. `/generate` Generate a new CT abdomen study with 200 slices using the existing CT abdomen study.

2. `/generate` Generate a new MG study from the existing MG study with ISO_IR 13 specific character set applied to patient name and study description.

3. `/generate` Generate a new MR brain study with one instance having a small circular shutter from an existing MR head study.

4. `/generate` Generate a presentation state object having a graphic annotation — a horizontal line at the middle of the image — and a text annotation "CT Head" referencing the first instance of an existing CT head study. It shall appear as a new series in the same study with the same patient details, and it shall refer to the correct instance.

5. `/generate` Generate a new series in an existing CT abdomen study with a gantry tilt of 30 degrees in the x-direction in geometry, based on an existing series, so I can have 2 series in the same study with the same number of instances.
