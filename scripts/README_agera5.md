# AgERA5 Daily Climate Downloader

Downloads **temperature**, **relative humidity**, and **vapour pressure deficit**
from the Copernicus Climate Data Store (CDS) AgERA5 dataset
(`sis-agrometeorological-indicators`).

---

## 1 · Prerequisites

### Install dependencies

```bash
pip install cdsapi xarray netCDF4 numpy pandas
```

### Register on CDS and get your API key

1. Create a free account at <https://cds.climate.copernicus.eu>
2. Accept the dataset licence (search *sis-agrometeorological-indicators* → Download tab → tick the licence box)
3. Go to **your profile page** and copy your **UID** and **API key**

### Create `~/.cdsapirc`

```ini
url: https://cds.climate.copernicus.eu/api
key: <YOUR-UID>:<YOUR-API-KEY>
```

> On Windows the file lives at `C:\Users\<you>\.cdsapirc`

---

## 2 · Quick start

```bash
# Kenya, full year 2022, all variables, merge to single file, convert K → °C
python agera5_download.py \
    --country kenya \
    --start 2022-01-01 --end 2022-12-31 \
    --variables all \
    --merge --convert-kelvin \
    --output ./data/kenya_2022
```

---

## 3 · Command reference

```
usage: agera5_download.py [-h]
    (--country COUNTRY | --bbox NORTH WEST SOUTH EAST)
    --start YYYY-MM-DD
    --end   YYYY-MM-DD
    --output DIR
    [--variables VAR [VAR ...]]
    [--prefix PREFIX]
    [--merge]
    [--convert-kelvin]
    [--keep-zips]
    [--version {1_1,2_0}]
    [--dry-run]
```

### Spatial domain  *(one of these is required)*

| Flag | Description |
|------|-------------|
| `--country COUNTRY` | Built-in preset: `kenya`, `ethiopia`, `somalia`, `east_africa` |
| `--bbox N W S E` | Custom bounding box in decimal degrees |

**Country bounding boxes (N / W / S / E)**

| Country | North | West | South | East |
|---------|-------|------|-------|------|
| kenya | 5.0 | 33.9 | −4.7 | 42.0 |
| ethiopia | 15.1 | 33.0 | 3.4 | 48.0 |
| somalia | 12.0 | 40.9 | −1.7 | 51.5 |
| east_africa | 15.1 | 33.0 | −4.7 | 51.5 |

### Temporal range

| Flag | Description |
|------|-------------|
| `--start YYYY-MM-DD` | Start date (inclusive) |
| `--end YYYY-MM-DD` | End date (inclusive) |

The script downloads **one CDS request per variable per month**, which is the most
efficient approach given CDS rate limits.

### Variables

| Group / key | Variables included |
|-------------|--------------------|
| `all` *(default)* | everything below |
| `temperature` | `temperature_mean`, `temperature_max`, `temperature_min` |
| `humidity` | `relative_humidity_mean`, `relative_humidity_max`, `relative_humidity_min` |
| `vpd` | `vapour_pressure`, `vapour_pressure_deficit` |
| `temperature_mean` | 2 m mean air temperature (24-hour mean) |
| `temperature_max` | 2 m daytime maximum temperature |
| `temperature_min` | 2 m night-time minimum temperature |
| `relative_humidity_mean` | 2 m mean relative humidity |
| `relative_humidity_max` | 2 m daytime max relative humidity |
| `relative_humidity_min` | 2 m night-time min relative humidity |
| `vapour_pressure` | Vapour pressure (24-hour mean, hPa) |
| `vapour_pressure_deficit` | VPD at daily maximum temperature (hPa) |

Native units: temperature in **K**, humidity in **%**, pressure in **hPa**.

### Output options

| Flag | Description |
|------|-------------|
| `--output DIR` | Root directory for all output |
| `--prefix PREFIX` | Prefix for merged filename (default: `agera5`) |
| `--merge` | Merge all NetCDF files into one `*_merged.nc` |
| `--convert-kelvin` | Convert temperature from K to °C |
| `--keep-zips` | Retain raw `.zip` archives |

### Other

| Flag | Description |
|------|-------------|
| `--version {1_1,2_0}` | AgERA5 dataset version (default: `2_0`) |
| `--dry-run` | Print planned requests without downloading |

---

## 4 · Output folder layout

```
<output>/
├── netcdf/              ← processed .nc files (or merged file)
│   ├── Temperature_Air_2m_Mean_24h_2022_01.nc
│   ├── ...
│   └── agera5_kenya_merged.nc   (if --merge)
└── raw_zips/            ← raw CDS archives (removed unless --keep-zips)
```

---

## 5 · More examples

```bash
# Ethiopia + Somalia (custom bbox), MAM season 2021, temperature only
python agera5_download.py \
    --bbox 15.1 33.0 -1.7 51.5 \
    --start 2021-03-01 --end 2021-05-31 \
    --variables temperature \
    --convert-kelvin \
    --output ./horn_mam_2021

# Dry run — preview requests without downloading
python agera5_download.py \
    --country kenya \
    --start 2020-01-01 --end 2020-12-31 \
    --variables all \
    --dry-run

# Just VPD, single month, keep raw zips
python agera5_download.py \
    --country somalia \
    --start 2023-07-01 --end 2023-07-31 \
    --variables vpd \
    --keep-zips \
    --output ./vpd_test
```

---

## 6 · Tips

- **CDS queue times** can be long (minutes to hours) during peak hours.
  Each request covers one variable × one month, so a full year = 12 requests per variable.
- Re-running the script is **safe**: files already downloaded are skipped (cache check).
- Use `--dry-run` first to verify your bounding box and date range before submitting.
- For multi-year downloads, consider running one year at a time to avoid very large merged files.
- The merged NetCDF can be opened directly in Python (`xarray.open_dataset`),
  QGIS, or any CF-compliant tool.
