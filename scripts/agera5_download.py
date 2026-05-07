#!/usr/bin/env python3
"""
AgERA5 Daily Climate Data Downloader
=====================================
Downloads temperature, relative humidity, and vapour pressure deficit
from the Copernicus Climate Data Store (CDS) AgERA5 dataset.

Dataset: sis-agrometeorological-indicators
https://cds.climate.copernicus.eu/datasets/sis-agrometeorological-indicators

Requirements:
    pip install cdsapi xarray netCDF4 numpy pandas tqdm

CDS credentials:
    Create ~/.cdsapirc with:
        url: https://cds.climate.copernicus.eu/api
        key: <your-uid:api-key>

    Or set environment variables:
        export CDSAPI_URL=https://cds.climate.copernicus.eu/api
        export CDSAPI_KEY=<your-uid:api-key>
"""

import argparse
import calendar
import os
import shutil
import sys
import zipfile
from datetime import date, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Country bounding-box presets  (N, W, S, E)
# ---------------------------------------------------------------------------
COUNTRY_PRESETS = {
    "kenya":    {"north":  5.0, "west": 33.9, "south": -4.7, "east": 42.0},
    "ethiopia": {"north": 15.1, "west": 33.0, "south":  3.4, "east": 48.0},
    "somalia":  {"north": 12.0, "west": 40.9, "south": -1.7, "east": 51.5},
    "east_africa": {
        "north": 15.1, "west": 33.0, "south": -4.7, "east": 51.5
    },
}

# ---------------------------------------------------------------------------
# Variable definitions
# AgERA5 separates some variables by statistic (temperature) or time (humidity)
# ---------------------------------------------------------------------------
VARIABLE_DEFS = {
    # key → (cds_variable, extra_params, file_label)
    "temperature_mean": (
        "2m_temperature",
        {"statistic": "24_hour_mean"},
        "Temperature_Air_2m_Mean_24h",
    ),
    "temperature_max": (
        "2m_temperature",
        {"statistic": "Day_time_Maximum"},
        "Temperature_Air_2m_Max_Day_Time",
    ),
    "temperature_min": (
        "2m_temperature",
        {"statistic": "Night_time_Minimum"},
        "Temperature_Air_2m_Min_Night_Time",
    ),
    "relative_humidity_mean": (
        "2m_relative_humidity",
        {"time": "06_00"},
        "Relative_Humidity_2m_06h",
    ),
    "relative_humidity_max": (
        "2m_relative_humidity",
        {"time": "18_00"},
        "Relative_Humidity_2m_18h",
    ),
    "relative_humidity_min": (
        "2m_relative_humidity",
        {"time": "12_00"},
        "Relative_Humidity_2m_12h",
    ),
    "2m_relative_humidity_derived": (
        "2m_relative_humidity_derived",
        {"statistic": ["24_hour_maximum", "24_hour_minimum"]},
        "Relative_Humidity_2m_Derived",
    ),
    "vapour_pressure": (
        "vapour_pressure",
        {"statistic": "24_hour_mean"},
        "Vapour_Pressure_Mean",
    ),
    "vapour_pressure_deficit": (
        "vapour_pressure_deficit_at_maximum_temperature",
        {},
        "Vapour_Pressure_Deficit_Mean",
    ),
}

# Convenient shorthand groups
VARIABLE_GROUPS = {
    "temperature": ["temperature_mean", "temperature_max", "temperature_min"],
    "humidity":    ["relative_humidity_mean", "relative_humidity_max", "relative_humidity_min", "2m_relative_humidity_derived"],
    "vpd":         ["vapour_pressure", "vapour_pressure_deficit"],
    "vapour_pressure_deficit_at_maximum_temperature": ["vapour_pressure_deficit"],
    "all":         list(VARIABLE_DEFS.keys()),
}

# Variables whose native unit is Kelvin
KELVIN_VARIABLES = {"temperature_mean", "temperature_max", "temperature_min"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def kelvin_to_celsius(ds):
    """Convert all temperature variables in an xarray Dataset from K to °C."""
    import xarray as xr  # noqa: F401  (lazy import so CLI help works without xarray)
    for var in list(ds.data_vars):
        attrs = ds[var].attrs
        unit = attrs.get("units", "").strip()
        if unit == "K" or "kelvin" in unit.lower():
            ds[var] = ds[var] - 273.15
            ds[var].attrs = {**attrs, "units": "°C",
                             "long_name": attrs.get("long_name", var) + " (°C)"}
    return ds


def daterange_months(start: date, end: date):
    """Yield (year, month) tuples covering [start, end] inclusive."""
    current = date(start.year, start.month, 1)
    while current <= date(end.year, end.month, 1):
        yield current.year, current.month
        # advance one month
        if current.month == 12:
            current = date(current.year + 1, 1, 1)
        else:
            current = date(current.year, current.month + 1, 1)


def days_in_month_range(year: int, month: int, start: date, end: date):
    """Return list of day strings ('01'..'31') that fall within [start, end]."""
    _, last_day = calendar.monthrange(year, month)
    days = []
    for d in range(1, last_day + 1):
        current = date(year, month, d)
        if start <= current <= end:
            days.append(f"{d:02d}")
    return days


def resolve_variables(requested: list[str]) -> list[str]:
    """Expand group names into individual variable keys."""
    resolved = []
    for item in requested:
        item = item.lower().strip()
        if item in VARIABLE_GROUPS:
            resolved.extend(VARIABLE_GROUPS[item])
        elif item in VARIABLE_DEFS:
            resolved.append(item)
        else:
            print(f"  [!] Unknown variable or group '{item}' — skipping.")
    # deduplicate while preserving order
    seen = set()
    return [v for v in resolved if not (v in seen or seen.add(v))]


def extract_nc_from_zip(zip_path: Path, dest_dir: Path) -> list[Path]:
    """Unzip a CDS zip archive and return paths to extracted .nc files."""
    nc_files = []
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            for name in zf.namelist():
                if name.endswith(".nc"):
                    zf.extract(name, dest_dir)
                    nc_files.append(dest_dir / name)
    except zipfile.BadZipFile:
        print(f"  [WARN] Skipping invalid zip archive: {zip_path}")
    return nc_files


# ---------------------------------------------------------------------------
# Core download function
# ---------------------------------------------------------------------------

def download_variable(
    client,
    var_key: str,
    year: int,
    month: int,
    days: list[str],
    bbox: dict,
    out_dir: Path,
    version: str = "2_0",
) -> Path | None:
    """Download one variable/month combo. Returns path to downloaded zip."""
    import cdsapi  # noqa

    cds_var, extra, label = VARIABLE_DEFS[var_key]
    month_str = f"{month:02d}"
    fname = f"{label}_{year}_{month_str}.zip"
    dest = out_dir / fname

    if dest.exists():
        if dest.stat().st_size > 0 and zipfile.is_zipfile(dest):
            print(f"  [cache] {fname} already exists — skipping download.")
            return dest
        print(f"  [cache] {fname} exists but is invalid — re-downloading.")
        dest.unlink(missing_ok=True)

    area = [bbox["north"], bbox["west"], bbox["south"], bbox["east"]]

    request = {
        "variable": cds_var,
        "year": str(year),
        "month": month_str,
        "day": days,
        "area": area,
        "version": version,
        **extra,
    }

    print(f"  → Requesting {var_key} | {year}-{month_str} | days: {days[0]}–{days[-1]}")
    try:
        client.retrieve("sis-agrometeorological-indicators", request, str(dest))
        if dest.stat().st_size == 0 or not zipfile.is_zipfile(dest):
            print(f"  [ERROR] Downloaded file is not a valid zip: {dest}")
            dest.unlink(missing_ok=True)
            return None
        return dest
    except Exception as exc:
        print(f"  [ERROR] Failed to download {var_key} {year}-{month_str}: {exc}")
        return None


# ---------------------------------------------------------------------------
# Post-processing
# ---------------------------------------------------------------------------

def process_downloads(
    zip_files: list[Path],
    scratch_dir: Path,
    convert_kelvin: bool,
    merge: bool,
    final_output: Path,
    output_prefix: str,
) -> list[Path]:
    """Extract → convert → optionally merge all downloaded files."""
    try:
        import xarray as xr
    except ImportError:
        print("[ERROR] xarray is required for processing. Install with: pip install xarray netCDF4")
        return []

    datasets = []
    extracted_files = []

    for zf in zip_files:
        nc_paths = extract_nc_from_zip(zf, scratch_dir)
        for nc in nc_paths:
            ds = xr.open_dataset(nc)
            if convert_kelvin:
                ds = kelvin_to_celsius(ds)
            extracted_files.append((nc, ds))

    if not extracted_files:
        print("[WARN] No NetCDF files were extracted.")
        return []

    if merge:
        print("\n[*] Merging all downloaded files into a single NetCDF …")
        merged_ds = None
        for _, ds in extracted_files:
            if merged_ds is None:
                merged_ds = ds
            else:
                try:
                    # Try to concat along time first; fall back to merge
                    merged_ds = xr.merge([merged_ds, ds])
                except Exception:
                    merged_ds = xr.merge([merged_ds, ds], compat="override")

        if merged_ds is not None:
            out_nc = final_output / f"{output_prefix}_merged.nc"
            merged_ds.to_netcdf(out_nc)
            print(f"  [✓] Merged output: {out_nc}")
            return [out_nc]
    else:
        saved = []
        for nc_path, ds in extracted_files:
            out_nc = final_output / nc_path.name
            ds.to_netcdf(out_nc)
            saved.append(out_nc)
        return saved


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="agera5_download",
        description=(
            "Download AgERA5 daily climate data (temperature, humidity, VPD)\n"
            "from the Copernicus Climate Data Store (CDS).\n\n"
            "Dataset: sis-agrometeorological-indicators\n"
            "Requires a free CDS account and ~/.cdsapirc credentials file."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
EXAMPLES
--------
# Kenya, full year 2022, all variables, merge output, convert K→°C
  agera5_download.py --country kenya --start 2022-01-01 --end 2022-12-31 \\
      --variables all --merge --convert-kelvin --output ./data

# Ethiopia + custom months, temperature only
  agera5_download.py --country ethiopia --start 2021-03-01 --end 2021-05-31 \\
      --variables temperature --output ./data/ethiopia

# Custom bounding box (Horn of Africa), specific variables
  agera5_download.py --bbox 15 33 -5 51 --start 2020-06-01 --end 2020-08-31 \\
      --variables temperature_mean vapour_pressure_deficit --output ./horn

# Somalia, humidity + VPD, merge into single file
  agera5_download.py --country somalia --start 2023-01-01 --end 2023-03-31 \\
      --variables humidity vpd --merge --output ./somalia_data

AVAILABLE VARIABLES / GROUPS
-----------------------------
  Groups (expand to multiple variables):
    temperature     → temperature_mean, temperature_max, temperature_min
        humidity        → relative_humidity_mean, relative_humidity_max, relative_humidity_min, relative_humidity_derived_max, relative_humidity_derived_min
    vpd             → vapour_pressure, vapour_pressure_deficit
    all             → everything above

  Individual variables:
    temperature_mean, temperature_max, temperature_min
    relative_humidity_mean, relative_humidity_max, relative_humidity_min, relative_humidity_derived_max, relative_humidity_derived_min
    vapour_pressure, vapour_pressure_deficit

COUNTRY PRESETS  (N / W / S / E)
---------------------------------
  kenya        :   5.0 / 33.9 /  -4.7 / 42.0
  ethiopia     :  15.1 / 33.0 /   3.4 / 48.0
  somalia      :  12.0 / 40.9 /  -1.7 / 51.5
  east_africa  :  15.1 / 33.0 /  -4.7 / 51.5
""",
    )

    # --- Spatial ---
    spatial = p.add_argument_group("Spatial domain (mutually exclusive)")
    spatial_ex = spatial.add_mutually_exclusive_group(required=True)
    spatial_ex.add_argument(
        "--country",
        choices=list(COUNTRY_PRESETS.keys()),
        metavar="COUNTRY",
        help="Use a built-in country bounding box. "
             f"Choices: {', '.join(COUNTRY_PRESETS.keys())}",
    )
    spatial_ex.add_argument(
        "--bbox",
        nargs=4,
        type=float,
        metavar=("NORTH", "WEST", "SOUTH", "EAST"),
        help="Custom bounding box in decimal degrees. Example: --bbox 5.0 33.9 -4.7 42.0",
    )

    # --- Temporal ---
    temporal = p.add_argument_group("Temporal range")
    temporal.add_argument(
        "--start",
        required=True,
        metavar="YYYY-MM-DD",
        help="Start date (inclusive). Example: 2022-01-01",
    )
    temporal.add_argument(
        "--end",
        required=True,
        metavar="YYYY-MM-DD",
        help="End date (inclusive). Example: 2022-12-31",
    )

    # --- Variables ---
    var_grp = p.add_argument_group("Variables")
    var_grp.add_argument(
        "--variables",
        nargs="+",
        default=["all"],
        metavar="VAR",
        help=(
            "Variables or groups to download. "
            "Groups: temperature, humidity, vpd, all. "
            "Individual: temperature_mean, temperature_max, temperature_min, "
            "relative_humidity_mean, relative_humidity_max, relative_humidity_min, relative_humidity_derived_max, relative_humidity_derived_min, "
            "vapour_pressure, vapour_pressure_deficit. "
            "Default: all"
        ),
    )

    # --- Output ---
    out_grp = p.add_argument_group("Output")
    out_grp.add_argument(
        "--output",
        required=True,
        metavar="DIR",
        help="Directory to save downloaded and processed files.",
    )
    out_grp.add_argument(
        "--prefix",
        default="agera5",
        metavar="PREFIX",
        help="Filename prefix for merged output. Default: agera5",
    )
    out_grp.add_argument(
        "--merge",
        action="store_true",
        help="Merge all downloaded files into a single NetCDF file.",
    )
    out_grp.add_argument(
        "--convert-kelvin",
        action="store_true",
        help="Convert temperature variables from Kelvin to Celsius.",
    )
    out_grp.add_argument(
        "--keep-zips",
        action="store_true",
        help="Keep the raw downloaded .zip files (deleted by default after extraction).",
    )

    # --- CDS options ---
    cds_grp = p.add_argument_group("CDS API options")
    cds_grp.add_argument(
        "--version",
        default="2_0",
        choices=["1_1", "2_0"],
        help="AgERA5 dataset version. Default: 2_0",
    )
    cds_grp.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the planned API requests without actually downloading.",
    )

    return p


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main():
    parser = build_parser()
    args = parser.parse_args()

    # ---- Resolve spatial domain ----
    if args.country:
        bbox = COUNTRY_PRESETS[args.country]
        region_label = args.country
    else:
        n, w, s, e = args.bbox
        bbox = {"north": n, "west": w, "south": s, "east": e}
        region_label = f"custom_{n}N_{w}W_{s}S_{e}E"

    # ---- Parse dates ----
    try:
        start_date = date.fromisoformat(args.start)
        end_date   = date.fromisoformat(args.end)
    except ValueError as exc:
        print(f"[ERROR] Invalid date format: {exc}")
        sys.exit(1)

    if start_date > end_date:
        print("[ERROR] --start must be before or equal to --end.")
        sys.exit(1)

    # ---- Resolve variables ----
    var_keys = resolve_variables(args.variables)
    if not var_keys:
        print("[ERROR] No valid variables selected. Exiting.")
        sys.exit(1)

    # ---- Set up output directories ----
    out_dir    = Path(args.output)
    raw_dir    = out_dir / "raw_zips"
    scratch    = out_dir / "_scratch"
    final_dir  = out_dir / "netcdf"

    for d in [raw_dir, scratch, final_dir]:
        d.mkdir(parents=True, exist_ok=True)

    # ---- Summary ----
    print("\n" + "=" * 62)
    print("  AgERA5 Downloader — Copernicus CDS")
    print("=" * 62)
    print(f"  Region    : {region_label}")
    print(f"  Bbox      : N={bbox['north']}  W={bbox['west']}  "
          f"S={bbox['south']}  E={bbox['east']}")
    print(f"  Period    : {start_date} → {end_date}")
    print(f"  Variables : {', '.join(var_keys)}")
    print(f"  K→°C      : {args.convert_kelvin}")
    print(f"  Merge     : {args.merge}")
    print(f"  Output    : {out_dir.resolve()}")
    print(f"  Version   : {args.version}")
    print("=" * 62 + "\n")

    if args.dry_run:
        print("[DRY RUN] Planned API requests:\n")
        for year, month in daterange_months(start_date, end_date):
            days = days_in_month_range(year, month, start_date, end_date)
            for vk in var_keys:
                cds_var, extra, label = VARIABLE_DEFS[vk]
                print(f"  variable={cds_var}  year={year}  month={month:02d}  "
                      f"days={days[0]}–{days[-1]}  extra={extra}")
        print("\n[DRY RUN] No files downloaded.")
        return

    # ---- Initialise CDS client ----
    try:
        import cdsapi
    except ImportError:
        print("[ERROR] cdsapi not installed. Run: pip install cdsapi")
        sys.exit(1)

    try:
        client = cdsapi.Client(quiet=True)
    except Exception as exc:
        print(f"[ERROR] Could not initialise CDS client: {exc}")
        print("  Make sure ~/.cdsapirc is configured with your CDS credentials.")
        sys.exit(1)

    # ---- Download loop ----
    all_zips: list[Path] = []
    months = list(daterange_months(start_date, end_date))
    total  = len(var_keys) * len(months)
    done   = 0

    for vk in var_keys:
        for year, month in months:
            days = days_in_month_range(year, month, start_date, end_date)
            if not days:
                continue
            done += 1
            print(f"[{done}/{total}] {vk} | {year}-{month:02d}")
            zp = download_variable(
                client, vk, year, month, days, bbox, raw_dir, args.version
            )
            if zp:
                all_zips.append(zp)

    print(f"\n[*] Download complete. {len(all_zips)} zip files retrieved.")

    # ---- Post-process ----
    if all_zips:
        output_files = process_downloads(
            all_zips,
            scratch_dir=scratch,
            convert_kelvin=args.convert_kelvin,
            merge=args.merge,
            final_output=final_dir,
            output_prefix=f"{args.prefix}_{region_label}",
        )

        print(f"\n[✓] Processed files ({len(output_files)}):")
        for f in output_files:
            size_mb = f.stat().st_size / 1e6
            print(f"    {f}  ({size_mb:.1f} MB)")

        # Cleanup scratch
        shutil.rmtree(scratch, ignore_errors=True)

        # Optionally remove raw zips
        if not args.keep_zips:
            for zp in all_zips:
                zp.unlink(missing_ok=True)
            raw_dir.rmdir() if not any(raw_dir.iterdir()) else None
            print("\n[*] Raw zip files removed (use --keep-zips to retain them).")

    print("\n[✓] Done.\n")


if __name__ == "__main__":
    main()

