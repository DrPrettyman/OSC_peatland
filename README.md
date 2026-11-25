# Sentinel-1 backscatter trends on Bodmin Moor

Interview task: map the 2023–2024 trend in Sentinel-1 radar backscatter over peatland on Bodmin Moor, Cornwall.

## Layout

| Path | Contents |
| --- | --- |
| `code/` | Python scripts (`download_s1.py` fetches Sentinel-1 GRD scenes from Earth Engine) |
| `code/data/` | Downloaded data (git-ignored) |
| `write_up/` | LaTeX write-up (`main.tex`, figures in `write_up/figures/`) |
| `notes/` | Working notes (git-ignored) |
| `papers/` | Related literature: PDFs, abstracts, `references.bib` (catalogue in `papers/README.md`) |

## Reproducing the results

In order:

1. Set up the Python environment and Earth Engine access (below).
2. Download the Sentinel-1 scenes (`download_s1.py`).
3. Download the ancillary layers and build the peat mask (`download_peat_map.py`, `download_ancillary.py`, `make_mask.py`).
4. Select the restoration and control patches (`make_study_areas.py`).
5. Run the notebook `code/eda.ipynb`, which makes all the figures, including the two in the write-up.
6. Build the write-up (`write_up/main.tex`).

## Setup

### Python environment

Python 3.14 with a standard `venv` and `pip`:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r code/requirements.txt
```

### Earth Engine authentication

Authenticate once per machine:

```bash
earthengine authenticate --auth_mode=localhost
```

This opens a browser for Google sign-in and saves a token locally.

> **Note:** plain `earthengine authenticate` uses `gcloud` by default. The installed Google Cloud SDK (v416) fails on Python ≥ 3.12 with `ModuleNotFoundError: No module named 'imp'`. `--auth_mode=localhost` skips `gcloud`. If browser redirection fails, use `--auth_mode=notebook`, which gives a code to paste into the terminal.

### Earth Engine project

Scripts also need a Google Cloud project registered for Earth Engine ([register here](https://code.earthengine.google.com/register): Unpaid usage → Academic & Research). Put its ID in a `.env` file at the repository root:

```bash
cp .env.example .env
# then edit .env:
EE_PROJECT=your-project-id
```

`download_s1.py` loads `.env` automatically, and `--project` overrides it. `.env` is git-ignored, and `.env.example` is the committed template.

### Download data

```bash
# list matching scenes and per-orbit counts without downloading
python code/download_s1.py --dry-run

# download all scenes to code/data/s1_VV
python code/download_s1.py
```

### Ancillary data (masking)

Land-cover, peat and elevation layers used to build the moorland-peat mask, saved to `code/data/ancillary/`. Earth Engine layers are exported directly onto the Sentinel-1 grid (EPSG:27700, 10 m); peat-map polygons are rasterised onto the same grid by `make_mask.py`.

```bash
python code/download_peat_map.py    # England Peat Map layers (no Earth Engine needed)
python code/download_ancillary.py   # WorldCover, Dynamic World, DEM (needs Earth Engine)
python code/make_mask.py            # build code/data/ancillary/peat_mask.tif
```

| Layer | Source | How obtained | Used for |
| --- | --- | --- | --- |
| **England Peat Map: Peat Status, GHG and C storage** | Natural England; layer marked "© BGS & NSRI" | Natural England open-data ArcGIS feature service, queried by bounding box (`download_peat_map.py`) | Peat extent (shallow vs deep peaty soils) and land-use flags: improved grassland (IMP), afforested (AFF), woodland (WOD), linear features (REM) |
| **England Peat Map: Peatland Restoration Register** | Natural England (compiled from EA, Nature for Climate grant scheme, Countryside Stewardship records) | Same service | Restoration polygons and start dates (Priddicombe, Crowdy, Stanning Hill, Stannon South); point records plotted with 1 km rings as areas to avoid for a comparison patch |
| **ESA WorldCover v200** (2021, 10 m) | ESA (Zanaga et al., 2022) | Earth Engine `ESA/WorldCover/v200` (`download_ancillary.py`) | Trees, open water and built-up areas in the mask |
| **Dynamic World V1** (modal class and mean tree probability, 2023–24) | Google / World Resources Institute (Brown et al., 2022, *Scientific Data*) | Earth Engine `GOOGLE/DYNAMICWORLD/V1` | Downloaded but not used: labels ~25% of the box as trees, which is implausible |
| **Copernicus GLO-30 DEM** | ESA / Copernicus | Earth Engine `COPERNICUS/DEM/GLO30_2024_1` | Elevation matching of the control patch (`make_study_areas.py`) |

**To check:** the licence and required attribution for the England Peat Map layers (assumed Open Government Licence, not yet confirmed on Natural England's dataset pages), and the Zanaga and Brown citations before adding them to `references.bib`.

### Study areas

```bash
python code/make_study_areas.py     # Crowdy restoration patch and matched control -> code/outputs/study_areas.{tif,geojson}
```

The outputs are committed, so this step is only needed if the mask or the selection rules change.

### Run the notebook

The notebook reads its inputs with paths relative to `code/`, so start Jupyter from there:

```bash
cd code
jupyter lab eda.ipynb
```

or run every cell without opening it (about 15 seconds):

```bash
cd code
jupyter nbconvert --to notebook --execute --inplace eda.ipynb
```

It writes the exploratory figures to `code/eda_figures/` and the two write-up figures to `write_up/figures/` (`timeseries.pdf`, `trend_map.pdf`).

### Build the write-up

```bash
cd write_up
latexmk -pdf main.tex
```

## Notes on Sentinel-1 Data

Sentinel-1 beams a pulse of microwave radiation towards the earth (C-band, 5.405 GHz, so a wavelength of ~55 mm) and measures the amount of energy coming back (backscatter). At each pixel (a 10m by 10m patch), $\sigma^0$ is the backscatter coefficient in decibels on a log scale: $-10\text{dB}$ means $10\%$ of radiation power is returned; $-20\text{dB}$ means $1\%$ is returned. Sources: frequency and wavelength from ESA's [SentiWiki: S1 Mission](https://sentiwiki.copernicus.eu/web/s1-mission); the 10 m pixel size (IW mode), the conversion to dB as $10\log_{10}(\sigma^0)$, and the preprocessing (thermal noise removal, radiometric calibration, terrain correction) from the [Earth Engine catalogue: COPERNICUS/S1_GRD](https://developers.google.com/earth-engine/datasets/catalog/COPERNICUS_S1_GRD). See also the [Earth Engine Sentinel-1 algorithms guide](https://developers.google.com/earth-engine/guides/sentinel1).

The radar looks down on earth at an angle ($\thicksim 30^o$ to $45^o$ from vertical), so a flat, reflective surface (like still water) will return almost no radiation (it is reflected away from the sensor at the incident angle) and appears black. A "rough" surface (e.g. vegetation) will appear "brighter" (more returned radiation). N.B. roughness is relative to wavelength, so a few centimeters in this case. Source: [NASA Earthdata: SAR Image Interpretation](https://www.earthdata.nasa.gov/learn/earth-observation-data-basics/sar/image-interpretation) ("Regions of calm water and other smooth surfaces appear black"; "Rough surfaces appear brighter, as they reflect the radar in all directions"; wind-roughened water is bright when the waves are "close in size to the incident radar's wavelength"). Background on wavelength and scattering: [NASA Earthdata: What is SAR?](https://www.earthdata.nasa.gov/learn/earth-observation-data-basics/sar).

**Challenge:** Damp ground will appear brighter until the point that water pools on the surface, which will look very dark. The challenge will be separating changes in vegetation cover from changes in wetness. Possibly use rainfall or water table data together with Sentinel-1. Studies that have tried this (BibTeX keys in [papers/references.bib](papers/references.bib)):

- **Toca et al. (2023)** (`toca2023potential`): Sentinel-1 backscatter compared against dipwell water-table depth in blanket bog at Forsinard Flows, Flow Country, Scotland. In near-natural bog the water table stayed within 0–15 cm and backscatter varied by about 3–4 dB over the year. In restored sites (previously drained or afforested) the water table reached 35 cm and backscatter varied by up to about 6 dB. A random-forest model predicted water-table depth with $R^2 = 0.66$, RMSE 2.1 cm.
- **Toca et al. (2022)** (`toca2022high`): laboratory C-band radar on a reconstructed peat block during a 4-month forced drought. Both backscatter amplitude and phase responded coherently to falling water table and soil moisture. The phase change corresponded to 8.3 mm of surface subsidence for 17 cm of water-table drawdown.
- **Asmuß et al. (2019)** (`asmuss2019potential`): Sentinel-1 at 60 wells in a drained peatland used as grassland. Mean temporal correlation between backscatter and water-table depth was 0.45. The correlation weakened in summer (taller vegetation, deeper water table), with mowing and grazing, and where the mean water table was deeper than about 60 cm.
- **Millard & Richardson (2018)** (`millard2018quantifying`): quantifies the relative contributions of vegetation and soil moisture to C-band (polarimetric) backscatter in a temperate peatland; paywalled, not yet read.
- **Hrysiewicz et al. (2023)** (`hrysiewicz2023sar`): Sentinel-1 SAR and InSAR over an Irish raised bog, with a wildfire in 2019. The fire removed a 10–20 cm moss layer and VV backscatter increased, but soil moisture, InSAR coherence and surface motion did not change noticeably. This is a direct example of vegetation change altering VV independently of wetness.

### Polarisation: VV and VH

A radar wave vibrates in a fixed orientation, either vertical (V) or horizontal (H). The two letters give the transmitted orientation, then the received one:

- VV: sent vertical, received vertical ("co-polarised").
- VH: sent vertical, received horizontal ("cross-polarised").

From [NASA Earthdata](https://www.earthdata.nasa.gov/learn/earth-observation-data-basics/sar):

- VV: strongest for surface scattering from bare soil, peat or water. A rougher or wetter surface sends more straight back.
- VH: only produced when the wave's orientation gets scrambled, which mostly happens through volume scattering as the wave bounces around inside vegetation. So VH is the more vegetation-sensitive channel.
- HH responds to double bounce (buildings, tree trunks, flooded vegetation), but Sentinel-1 doesn't record it over the UK.

VH is noisier than VV ([SentiWiki: S1 Mission](https://sentiwiki.copernicus.eu/web/s1-mission)). 

For this project we propose using the VV data (the spec asks us to choose one). It is the less noisy signal and correlates with wetness/water table which comes up a lot in the literature. 

### Orbits

The satellite circles Earth from pole to pole 175 times every 12 days, in a near-polar, sun-synchronous orbit ([SentiWiki: S1 Mission](https://sentiwiki.copernicus.eu/web/s1-mission): "12 day repeat cycle and 175 orbits per cycle for a single satellite"). Only Sentinel-1A was operating in 2023–2024 (Sentinel-1B failed in December 2021), so each orbit revisits every 12 days. We are looking for data from orbits which pass over Bodmin Moor. Each orbit covers any given point on Earth at roughly the same time of day every 12 days, giving around 30 data points per year, or 60 in our two-year period of study (Jan 2023 to Dec 2024).

***Ascending and Descending***: For any given geo point some orbits may pass that point while *ascending* (as they travel from South to North) and some will pass that point whilst *descending* (as they travel from North to South). 

***Incidence angle***: Several orbits may cover the same location but at different incidence angles, with $0^o$ being "directly overhead". A smaller angle means a shorter distance traveled for the radiation. A larger angle means the radiation must travel through more vegetation (if any) before reaching the surface. A smaller angle is better suited to detecting surface wetness, whilst a larger angle is more suitable for detecting change in vegetation. Both could be suitable avenues for this project. N.B. The angle given by Earth Engine assumed the Earth a smooth ellipsoid and does not account for local slope (hills/valleys). 

From running `python code/download_s1.py --dry-run` with the default bounding box (-4.66 to -4.55 East; 50.55 to 50.63 North) which roughly covers Bodmin Moor we find that three orbits contain data for this area: 1, 52 and 103. See table:

| Orbit # | Orbit passage | Time of day (UTC) | # dates | Incidence angle (mean, range over area) |
|---|---|---|---|---|
| 1 | Ascending | $\sim$18:14 | 58 | 44.8° (44.5–45.0°) |
| 52 | Descending | $\sim$06:32 | 61 | 37.7° (37.4–38.0°) |
| 103 | Ascending | $\sim$18:06 | 60 | 36.5° (36.2–36.8°) |

All dates are Sentinel-1A (Jan 2023 to Dec 2024). Bodmin Moor falls on the boundary between two consecutive slices of orbit 1, so each orbit 1 date is a mosaic of two slices from the same pass; `download_s1.py` joins them, leaving a 1–2 pixel strip of no data along the join. Times are from `code/data/s1_VV/index.csv`. Incidence angles are from Earth Engine's `angle` band (ellipsoid, so no local slope), averaged over the study area at 100 m for one date per orbit.

The Orbit 1 data are 103 is likely the better choice because measurements are in the afternoon/evening whereas the \#52 measurements are early morning, before sunrise for much of the year, and dew or frost may distort the signal. Orbit 1 has a larger incidence angle and the data may be less reliable since it is stitched together from two scenes at each pass. 

## Notes on Bodmin Moor

Bodmin Moor is a granite upland in north-east Cornwall, part of the same granite mass (the Cornubian Batholith) as Dartmoor ([Natural England, NCA 153: Bodmin Moor](https://nationalcharacterareas.co.uk/bodmin-moor/description/)). The highest point is Brown Willy (420 m) in the north-west of the moor, with Rough Tor just beside it ([Cornwall National Landscape: Bodmin Moor](https://cornwall-landscape.org/section/12-bodmin-moor/)). Both are inside our study box. High rainfall on hard rock gives "thin and peaty-topped soils" (NCA 153). I haven't yet found rainfall figures for the moor, or a map of peat extent or depth.

***Peat and vegetation***: The high ground is "damp grass moorland, blanket bog and purple moor grass" (NCA 153). There are "large areas of peat and blanket bog" in the valleys at the edge of the moor, and fens and quaking bogs at the heads of streams (Cornwall National Landscape). Purple moor grass (*Molinia*) dies back each winter, so it will probably add a seasonal vegetation signal to the backscatter on top of any wetness signal.

***History of damage***: The peat has been worked for a long time.

- Tin streaming: "The majority of valley bottoms display evidence of tin streaming" (NCA 153), and this "often took place up on the peatlands and blanket bogs of Bodmin Moor and Dartmoor" ([South West Peatland Partnership: History of peatlands](https://southwestpeatlandpartnership.co.uk/history-of-peatlands)).
- Peat cutting: medieval peat-drying platforms survive on the moor (same SWPP page).
- China clay: large-scale extraction at Stannon Pit and Parson's Pit has ended, and parts have been restored (Cornwall National Landscape). Stannon Lake, a flooded pit at about 50.60°N, 4.65°W, is inside our study box and is the second dark patch in our radar images (the other is Crowdy Reservoir).
- Forestry: large conifer blocks were planted on the north and south moors after the Second World War (NCA 153). The Cornwall National Landscape plan lists plantations including Priddacombe and Roughtor as targets for "restoration to open habitats" (I've only seen a summary of this; check the original).

***Land use and designations***: Much of the moor is registered common land, managed under the Commons Act 2006 by the Bodmin Moor Commons Council (set up in 2015) (Cornwall National Landscape). It is grazed by sheep, cattle and ponies, with an average of about 74,000 sheep in the area (NCA 153). About 20% of the moor is SSSI and SAC (NCA 153), including much of the northern moor. The moor is within the Cornwall National Landscape (formerly the Cornwall AONB). Crowdy Reservoir, in the north-west corner of our box, is one of three 20th-century reservoirs on the moor, with Colliford and Siblyback (NCA 153).

***Restoration***: Bodmin Moor is one of four areas in the South West Peatland Partnership (SWPP), with Dartmoor, Exmoor and West Penwith. Partners on Bodmin include South West Water, the University of Exeter and Cornwall Wildlife Trust ([SWPP: Where we work](https://southwestpeatlandpartnership.co.uk/where-we-work)). Restoration uses "various ditch blocking techniques using sustainable materials (wood, peat, grass and heather)... on historic peat cuttings, drainage networks and eroding gullies" ([Cornwall National Landscape: Bodmin Moor Peatland project](https://cornwall-landscape.org/project/bodmin-moor-peatland-project/)).

**Important:** An SWPP photo of works on Bodmin is labelled "Priddacombe Down restoration 2022". Priddacombe Downs is at about 50.568°N, 4.594°W ([OpenStreetMap](https://www.openstreetmap.org/search?query=Priddacombe%20Downs)), inside our study box. Rewetting just before our study period could show up as a trend: wetter peat gets brighter, but pooled water gets darker. The boundary and start date of the works are in Natural England's Peatland Restoration Register, as "Priddicombe" (see below). SWPP also says it monitors "the levels of water retained on the landscape" across Bodmin Moor, which could be a source of field data for interpreting our results.

***Peatland Restoration Register records in our study box***: Natural England's England Peat Map includes a Peatland Restoration Register (see **Ancillary data** above; downloaded to `code/data/ancillary/restoration_register.geojson` by `download_peat_map.py`, which also writes the attributes as a table, `restoration_sites.csv`). Nine records fall in our box: four mapped polygons and five point records. Facts below come from the register's attribute fields (field names in brackets); statements marked *(our reading)* are interpretation, not register data.

*The four polygons.* All four are from the Nature for Climate Peatland Grant Scheme 2021–25 (`Src_Data`; data provider Natural England), led by South West Water (`Lead_Org`), with an end date of March 2026 (`EndDate`). All are recorded before restoration as "Degraded Peatlands – not currently supporting semi-natural wetland vegetation" (`Hab_Base`) and as "D - Degraded" (`Resto_stg`).

| Site (`RestoID`) | Area (`Hab_Amt`) | Works started (`Act_Date`) | Land use before (`GHG_LU`) | Target stage (`Resto_end`) | Notes |
| --- | --- | --- | --- | --- | --- |
| Priddicombe | 89 ha | Jan 2022 | Grass-dominated modified bog, drained | Stage 3: Recovery | Actions include adjusting grazing/mowing. Matches the SWPP "Priddacombe Down restoration 2022" photo above: same name and date, and the register's grid reference is about 250 m from OpenStreetMap's Priddacombe Downs *(our reading)* |
| Crowdy | 58 ha | Mar 2023 | Grass-dominated modified bog, drained | Stage 2: Stabilisation | East of Crowdy Reservoir *(from the map)* |
| Stanning Hill | 9 ha | Mar 2023 | Forest, drained | Stage 2: Stabilisation | Actions include "Remove_plants", probably clearing trees or scrub given the forest land use *(our reading)* |
| Stannon (South) | 6 ha | Sep 2022 | Grass-dominated modified bog, drained | Stage 2: Stabilisation | Next to the flooded Stannon pit *(from the map)* |

The start dates are labelled "Date action started" (`Date_Type`) and look rounded to the month or year, so they mark when each project began, not when particular ditches were blocked. The listed actions (`Act_Desc`) are much the same at every site: manage the water table, prevent erosion, stabilise slumping, help peat form and store water, plus administrative steps (agreements, permissions, funding, contractors). In practice this means ditch and gully blocking to rewet the peat *(our reading, consistent with the Cornwall National Landscape description above)*. The target-stage scale ("D - Degraded", "Stage 2 - Stabilisation", "Stage 3 - Recovery") is the register's own; I haven't found its definitions yet.

*The five points.* Point records give only a grid reference (stored as a 5 m circle), not the extent of the restored area, so we can't test them the way we test the polygons. They sit at three locations:

| Location | Records | Source (`Src_Data`) | Area (`Hab_Amt`) | Dates | Description (`Act_Desc`) |
| --- | --- | --- | --- | --- | --- |
| E213679, N76713 (50.560°N, 4.632°W), south-west of the box | 2 | Environment Agency Conservation Projects Database | 1.2 + 5.24 ha | No start date; end date 31 Mar 2021 (`EndDate`) | "Creating and restoring upland habitats across the SW upland peatlands ... across 12 waterbodies"; habitat "Blanket bog priority habitat" (`Hab_Type`) |
| E218857, N77541 (50.570°N, 4.559°W), south-east of the box | 2 | Environment Agency Conservation Projects Database | 45 + 53 ha | As above | As above |
| E216280, N77380 (50.567°N, 4.596°W), inside the Priddicombe polygon | 1 | Countryside Stewardship (data provider Rural Payments Agency) | 39.5 ha | Legal agreement Jan 2024 to Dec 2033 | "UP5 - Moorland re-wetting supplement" |

The Countryside Stewardship agreement means rewetting payments at Priddicombe run through 2024. The Environment Agency records are part of a programme spanning 12 waterbodies, so their grid references may be nominal project locations rather than the centre of the work *(our reading)*.

How we use them: the points are plotted on the mask map in `code/eda.ipynb` (via `plot_helpers.plot_restoration_areas`) with a dashed **1 km ring** around each location. The ring is an area to avoid when choosing a comparison (control) patch, since restoration may have happened anywhere near the point. 1 km is a judgement: the largest location totals about 98 ha, a circle of about 0.56 km radius, so 1 km leaves a margin for the unknown shape and position of the work. It's set by `POINT_BUFFER_KM` in the notebook.

Implication for choosing a comparison patch: all three point locations, Priddicombe and Stanning Hill lie in the southern strip of the box (N75.5–78.5 km), so a comparison patch should come from further north. The open moor at roughly E216–219, N80–83 km is well clear of every point; Crowdy, about 1.5–2 km away, is the nearest restoration site. The control patch actually used is chosen from this area by `code/make_study_areas.py`, using only peat depth, elevation and distance from restoration sites, never backscatter, so the comparison isn't tuned to the result.

N.B. The Cornwall National Landscape project page's figure of "35 hectares of moor at Park Pitt and Blackadon" covers the wider Bodmin–Dartmoor–Exmoor project. Blackadon Tor is on Dartmoor, so don't quote it as Bodmin restoration.

***Weather 2023–2024***: From the [Met Office climate summaries](https://www.metoffice.gov.uk/research/climate/maps-and-data/summaries/index):

- June 2023: the UK's warmest June on record (series from 1884), with UK rainfall 68% of average.
- July 2023: wet, with over 200% of average rainfall in parts of Devon.
- Autumn 2023: the warmest autumn on record for the south-west England and South Wales district, and a run of named storms (Babet, Ciarán).
- Winter 2023/24: the UK's eighth-wettest winter (129% of average), with southern England at 153%. February 2024 was the wettest February on record for southern England (239%). Check whether the Met Office's "southern England" region includes Cornwall.
- Spring 2024: warm and very wet; the UK's warmest spring on record.
- Summer 2024: cooler than average.
- November 2024: Storm Bert brought 150 mm or more of rain to the wettest upland areas of south-west England.

So the two years differ: a record-warm, dry June in 2023 against a very wet winter and spring and a cool summer in 2024. With only two years, a trend could simply reflect 2024 being wetter than 2023, rather than any change in the peat.

I didn't find any reports of moorland fires on Bodmin in 2023–2024. The arson fires I found were in 2025 and 2026, after our study period.

***Things to check***:

- ~~The extent and dates of the Priddacombe restoration.~~ Found in the Peatland Restoration Register (above). Still to do: look for it in the trend map.
- Whether any conifer plantations in our box were felled in 2023–2024. Felling would show up as a large change in VV; compare with Google Earth or Sentinel-2 imagery.
- ~~Mask out Crowdy Reservoir, Stannon Lake and the forestry blocks before mapping trends.~~ Done in `code/make_mask.py` (see **Ancillary data** above).
- ~~Find a peat extent map to define a proper study boundary, instead of the bounding box.~~ England Peat Map peat extent, used in the mask.
- Choose a comparison patch clear of the restoration polygons and the 1 km rings around the point records (see the five points above).

## Notes on the literature and InSAR

Organised by the questions we need to answer. BibTeX keys refer to [papers/references.bib](papers/references.bib); PDFs and a catalogue are in [papers/](papers/README.md).

### What controls C-band backscatter over peat?

VV backscatter mixes surface wetness, vegetation and roughness (see **Challenge** above). The studies that compare VV and VH:

- **Asmuß et al. (2019)** (`asmuss2019potential`): VV correlated better with water-table depth than VH did: 0.45 vs about 0.32.
- **Hrysiewicz et al. (2023)** (`hrysiewicz2023sar`): after the bog fire removed the moss layer, VV rose but VH showed no fire-related change. VH was noisier, though it still tracked soil moisture. Their reading: the moss layer weakens the C-band signal, and removing it exposed the peat surface to VV. So VV isn't a pure wetness signal either: it responds to the vegetation layer the wave passes through.
- **Toca et al. (2022)** (`toca2022high`): in the lab, VV and VH responded similarly to drying, VV was much stronger, and VH increased where dwarf shrubs were present, consistent with VH tracking vegetation.
- **Toca et al. (2023)** (`toca2023potential`): used both VV and VH as predictors of water-table depth.
- **Millard & Richardson (2018)** (`millard2018quantifying`): quantifies how much of the C-band signal comes from vegetation versus soil moisture in a peatland. Paywalled; not yet read, but it's the most direct study on this question.

**Takeaway:** VV is the better wetness signal, but a change in VV can't be put down to wetness alone. VH, or VV − VH, can help show whether vegetation is involved.

### Can Sentinel-1 backscatter track the water table?

Yes, roughly. **Toca et al. (2023)** in the Flow Country found yearly backscatter swings of about 3–4 dB in near-natural bog and up to about 6 dB in restored sites, and predicted water-table depth to within about 2 cm (random forest, $R^2 = 0.66$). **Asmuß et al. (2019)** found a weaker link (r = 0.45) in drained grassland peat, getting worse in summer, with mowing and grazing, and where the water table was deeper than about 60 cm. Details are under **Challenge** above.

What this means for us:

- Seasonal swings of 3–6 dB are much bigger than any plausible two-year trend, so we must fit the trend with the seasonal cycle accounted for (e.g. the sine/cosine model in `main.tex`), not a straight line through the raw data.
- Bodmin is grazed and partly drained, so we should expect a weaker wetness signal than in the near-natural Flow Country.

### Peatland surface motion (InSAR, "bog breathing")

The Scottish group behind this project mainly work with surface motion, not backscatter. InSAR measures it from the phase of the radar signal. Peat swells when wet and shrinks when dry.

- **Bradley et al. (2022)** (`bradley2022identification`): "Peatland surface motion is a response to changes in the water and gas content of a peat body". The timing of the seasonal peak in swelling maps condition across the Flow Country. An autumn peak indicates "stiffer", often degraded, shrub-dominated peat; a winter peak indicates "softer" peat with pools and *Sphagnum*.
- **Marshall et al. (2022)** (`marshall2022multiscale`): ground levelling vs InSAR in the Flow Country. Motion is larger closer to the water table (hollows > lawns > hummocks). InSAR matches the ground data well, except during extreme droughts.
- **NatureScot Reports 1269 and 1308** (`marshall2021naturescot`, `bradley2025naturescot`): using surface motion to monitor restoration sites, and testing the InSAR condition classes against field surveys at Cairnsmore of Fleet. That site turned out "more degraded than those in the Flow Country", so they made a revised classification covering degraded peat.
- **Toca et al. (2022)** (`toca2022high`): in the lab, the phase change matched 8.3 mm of surface subsidence for 17 cm of water-table drop.
- **Hrysiewicz et al. (2023)** (`hrysiewicz2023sar`): Sentinel-1 InSAR over an Irish raised bog shows long-term subsidence, with yearly oscillations in step with soil moisture.

**Why we don't use it here:** our data (GRD) is amplitude only; the phase is thrown away. InSAR needs the SLC product, hundreds of GB for our period, and specialist processing (e.g. the ISBAS method used by Bradley et al.) because vegetation on peat breaks up the phase signal. That's beyond a three-hour task, but worth raising in the discussion as the obvious next step.

### Tipping points and early warning in peatlands

- **Thresholds:** **Lamentowicz et al. (2019)** (`lamentowicz2019unveiling`) found that plant communities in 2,000-year Polish peat records converged at a water-table depth of about 11.7 cm, with 45 taxa changing between 8 and 17 cm. **Jassey et al. (2018)** (`jassey2018tipping`) found abrupt changes in ecosystem respiration and plant and fungal communities when the water table fell below about 24 cm. Both are summarised in the EGU 2020 talk (`lamentowicz2020unveiling`; slides in `papers/`).
- **The project's approach:** **Sudakow et al. (2026)** (`sudakow2026scottish`) apply early-warning indicators to InSAR surface motion over about 400 km² of Scotland. In a blind test they picked out a 60 km² fire scar that matched ground observations and MODIS fire products.
- **Methods:** Dakos et al. (2012) (`dakos2012methods`) and Kéfi et al. (2014) (`kefi2014early`) review early-warning methods in time and space. Lenton et al. (2012) (`lenton2012early`) compare ways of detecting critical slowing down. Livina & Lenton (2007) (`livina2007modified`) introduce degenerate fingerprinting, and Livina et al. (2010, 2013) (`livina2010potential`, `livina2013forecasting`) introduce potential analysis. Prettyman et al. (2018) (`prettyman2018novel`) add the scaling indicator.
- **Caveat:** Radhakrishnan et al. (2025) (`radhakrishnan2025early`) show that early warnings come too late when conditions change quickly. These methods also need long, dense records; two years (about 60 dates per orbit) is too short. So early-warning analysis is out of scope for this task, but it's where the project is heading.

### Implications for this task

- **Polarisation:** VV. Stronger signal, and it correlates better with the water table.
- **Orbit:** 103. Evening pass, smallest incidence angle, single scene per date.
- **Trend method:** fit with seasonal terms; the seasonal cycle and the 2023/2024 weather contrast will otherwise dominate.
- **Interpretation:** be explicit that a VV trend could be wetness, vegetation or roughness (the Hrysiewicz fire example is a good one to quote). Check whether VH or VV − VH tells the same story.
- **Field observation:** dipwell water-table depth (as in Toca et al. 2023 and Asmuß et al. 2019), or repeat surface levelling (as in Marshall et al. 2022). SWPP's water-level monitoring on Bodmin may already have some.
- **Next step to mention:** InSAR surface motion from the same satellite's phase data.


## Further notes

"VV backscatter mixes surface wetness, vegetation and roughness, so a trend in dB/yr can't be attributed to peat condition alone. InSAR surface motion from the same satellite's phase data responds directly to peat water and gas content (Bradley et al., 2022) and would help separate these effects."




