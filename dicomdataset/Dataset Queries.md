**Basic Queries:**

 A. Routine single studies
1  Generate a CT head study: 1 patient, 1 series, 200 slices.
2  Generate a chest X-ray (CR): 1 patient, 1 study, 2 images (PA + lateral).
3  Generate an MR knee study: 1 patient, 5 series (different sequences),    30 slices each.
4  Generate a screening mammogram: 1 patient, 4 views (L/R CC + MLO).
5  Generate an ultrasound abdomen study: 1 patient, 12 single-frame images + 2 cine loops.

 B. Complex multi-series studies (viewer layout / series-picker testing)
6  Generate a CT abdomen with contrast phases: 1 patient, 4 series (non-contrast, arterial, venous, delayed), 150 slices each.
7  Generate a CT study with a scout/localizer series plus the main axial series: 1 patient, 2 series (3 localizer images + 200 axial slices).
8  Generate an MR brain study with axial, coronal, and sagittal reconstructions: 1 patient, 3 series, 25 slices each.
9  Generate a CT chest with a derived MIP/MPR series: 1 patient, 1 source series (200 slices) + 1 derived series (50 slices).

 C. Multi-frame / enhanced objects (single instance, many frames)
10 Generate an ultrasound cine: 1 patient, 1 study, 1 multi-frame instance of 60 frames.
11 Generate an enhanced CT study as a single multi-frame object: 1 patient, 1 instance containing 300 frames.
12 Generate an XA (angiography) run: 1 patient, 2 multi-frame acquisitions, 40 frames each.

 D. Longitudinal / priors (comparison workflows)
13 Generate a patient with 3 CT chest studies over 18 months (baseline, 6-month, 18-month follow-up), 150 slices each.
14 Generate an oncology patient with 5 studies across 2 years: mix of CT chest and PET/CT.
15 Generate a mammography patient with current + 2 prior screening studies, 4 views each.

 E. Multi-modality patients (VNA / MPI testing)
16 Generate 1 patient with CT chest (150 slices), MR brain (3 series), chest X-ray (2 images), and abdominal ultrasound (10 images).
17 Generate a PET/CT study: 1 patient, 1 CT series (200 slices) + 1 PET series (200 slices), spatially registered.
18 Generate a stroke patient: CT head (non-contrast), CT angiography, and CT perfusion — 1 patient, 3 studies same day.

 F. Specialty modalities
19 Generate a breast tomosynthesis study: 1 patient, 4 views, each as a multi-frame tomo object.
20 Generate a nuclear medicine (NM) bone scan: 1 patient, whole-body anterior + posterior images.
21 Generate a digital radiography (DX) series for orthopedics: 1 patient, 3 studies (different body parts), 2 images each.

 G. High-volume / scale (load \& performance)
22 Generate 100 patients, each with 1 CT chest study of 150 slices.
23 Generate a whole-body CT: 1 patient, 1 series, 1,500 slices.
24 Generate a stress dataset: 500 studies mixed across CT, MR, CR, and US.
25 Generate a tiny smoke-test set: 3 patients, 1 study each, 5 slices.


**Internationalization**

1  Generate a Japanese CT chest study: 1 patient with a full 3-component name (Yamada^Tarou=山田^太郎=やまだ^たろう), Kanji StudyDescription and InstitutionName, Specific Character Set ISO 2022 IR 87, 150 slices.
2  Generate a Chinese (GB18030) MR brain study: Hanzi PatientName and descriptions, 1 patient, 3 series.
3  Generate a Korean (ISO 2022 IR 149) study: Hangul name with alphabetic + ideographic components, CR chest, 2 images.
4  Generate a UTF-8 (ISO\_IR 192) study with mixed Latin + CJK text across all fields — the modern encoding most new systems standardize on. 
5  Generate a Japanese study with CJK text in ALL eligible fields (PatientName, ReferringPhysicianName, StudyDescription, SeriesDescription, InstitutionName, InstitutionAddress) — proves it's not name-only.
6  Generate a patient with alphabetic + ideographic only (no phonetic) — the most common partial-name pattern in real Japanese/Korean data.
7  Generate a mixed-population dataset: 10 patients spanning Japanese, Chinese, Korean, and Latin names in one batch — mirrors a real multi-site PACS.
8  Generate a Cyrillic (ISO\_IR 144) Russian study with name and descriptions in Cyrillic — common non-CJK i18n case.
9  Generate a study where the declared Specific Character Set does NOT match the actual byte encoding — the mojibake/garbled-text defect testers need.
10 Generate long CJK text approaching the field length limit (LO = 64 chars) to test truncation and buffer handling.

**PR and KO**
1  Generate a CT chest study, then a GSPS presentation state that stores a custom window/level for the lung view.
2  Generate an MR brain study with a GSPS that includes annotations — an arrow and a text label — on slice 12.
3  Generate a CT study with a measurement annotation (a distance line) stored in a presentation state.
4  Generate a study with a GSPS applying zoom, pan, and rotation to a specific image.
5  Generate a CT chest study, then a Key Object Selection flagging 3 key images with reason code "Of Interest".
6  Generate a study with a KO document referencing images across 2 different series, with reason "For Referring Provider".
7  Generate a study that has BOTH a GSPS and a KO referencing the same images (full annotate + flag workflow).
8  Generate an edge case: a KO / PR that references an image UID that does NOT exist in the study (broken-reference test).
9  Generate a study with multiple presentation states on the same image (e.g., a "lung" PR and a "bone" PR) to test PR selection in the viewer.

**Negative scenarios:**

1  Generate a CT study where PixelData is present but Rows/Columns tags are missing.
2  Generate a study where the number of slices declared doesn't match the actual instances (e.g. says 200, ships 150).
3  Generate a series with duplicate SOPInstanceUIDs across two instances.
4  Generate a study with two instances sharing the same InstanceNumber.
5  Generate a CT with inconsistent SliceThickness / ImagePositionPatient (non-monotonic, gaps, or overlaps) to break 3D reconstruction.
6  Generate an image with a wrong PhotometricInterpretation (e.g. declares MONOCHROME2 but pixels are RGB).
7  Generate a study where StudyInstanceUID differs between instances that claim to be the same study.
8  Generate an image with BitsAllocated/BitsStored/HighBit mismatch.
9  Generate a multi-frame object claiming 300 frames but containing 100.
10 Generate a truncated file — valid header, PixelData cut off mid-stream.
11 Generate a study with an empty/absent PatientID and PatientName.
12 Generate a file with an invalid VR for a tag (e.g. a date string in a numeric field).
13 Generate an out-of-range date (2026-02-30) and an impossible time.
14 Generate extreme pixel dimensions (e.g. 1×1, and 10000×10000).
15 Generate a file missing required Type 1 tags (e.g. no SOPClassUID).
16 Generate a study with special/illegal characters in UIDs (UIDs must be nueric-dotted only).
17 Generate a negative or zero value where positive is required (e.g. PixelSpacing = 0).
18 Generate a file with an incorrect Transfer Syntax declared vs. actual encoding (implicit vs explicit VR).
19 Generate a GSPS that references a SOPInstanceUID not present in the study (boken reference).
20 Generate a KO document with an empty reference list (flags nothing).
21 Generate a PR with annotation coordinates outside the image bounds.
22 Generate a KO with an invalid/undefined reason code.
23 Generate a GSPS referencing an image in a DIFFERENT study than its own.
24 Generate a PR with a VOI LUT / window value that is invalid (e.g. window width = 0).
25 Generate two presentation states that reference each other or form a circular reference.





