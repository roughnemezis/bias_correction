# sxcen
from os.path import join as pj
import gc

from cftime import datetime
from datetime import datetime, timedelta
import xarray as xr
import numpy as np
import pyproj
from tqdm import tqdm

from bias_correction.postprocessing.arome_interpolation import (
    DelaunayFixGridsInterpolator,
    convert_4324_to_2154,
    force_dir_from_u_v,
    reshape_as_grid,
    get_downscaled_wind,
)

# --------------------- functions   ---------------------------------------------
def reshape_to_timeserie(bdap_array):
    shape = bdap_array.data.shape
    time = bdap_array.valid_time.data.reshape(shape[0] * shape[1])
    reshaped_array = xr.DataArray(
        bdap_array.data.reshape(shape[0] * shape[1], shape[2], shape[3]),
        dims=["time", "latitude", "longitude"],
        coords=dict(
            latitude=bdap_array.latitude, longitude=bdap_array.longitude, time=time
        ),
    )
    return reshaped_array


def assign_2154_coords(bdap_array):
    lon_r, lat_r = reshape_as_grid(bdap_array.longitude, bdap_array.latitude)
    x, y = convert_4324_to_2154(lon_r, lat_r)
    return bdap_array.assign_coords(x=x, y=y)


def get_interpolated_wind(u, v, x, y, target_dem):
    target_x, target_y = reshape_as_grid(target_dem.x, target_dem.y)
    interpolator = DelaunayFixGridsInterpolator(x, y, target_x, target_y)
    interpolator.compute_interpolation_coeffs()
    size_t = u.time.shape[0]
    size_y = target_dem.y.shape[0]
    size_x = target_dem.x.shape[0]
    wind_interpolated = xr.Dataset(
        data_vars=dict(
            u=(
                ["time", "y", "x"],
                np.zeros((size_t, size_y, size_x), dtype=np.float32),
            ),
            v=(
                ["time", "y", "x"],
                np.zeros((size_t, size_y, size_x), dtype=np.float32),
            ),
        ),
        coords=dict(
            x=(["x"], target_dem.x.data),
            y=(["y"], target_dem.y.data),
            time=(["time"], u.time.data),
        ),
    )
    for time in tqdm(u.time):
        u_interp = interpolator.compute_interpolated_values_on_target(u.sel(time=time))
        v_interp = interpolator.compute_interpolated_values_on_target(v.sel(time=time))
        wind_interpolated.u.loc[dict(time=time)] = u_interp
        wind_interpolated.v.loc[dict(time=time)] = v_interp
    return wind_interpolated


def compute_downscaled(u_interp, v_interp, unet_output):
    force, direction = force_dir_from_u_v(u_interp, v_interp)
    force_down, direction_down = get_downscaled_wind(force, direction, unet_output)
    downscaled_wind = xr.Dataset({"force": force_down, "direction": direction_down})
    return downscaled_wind


# --------------------- generic data ---------------------------------------------
data_dir = "/home/merzisenh/NO_SAVE/bias_correction_data"
unet_output = xr.open_dataset(pj(data_dir, "dem_grandmaison_corrections.nc"))
target_dem = xr.open_dataset(pj(data_dir, "dem_grandmaison.nc"))


# --------------------- querying wind data ---------------------------------------

arome = xr.open_dataset(pj(data_dir, "arome_wind", "uv_2019_2020.nc"))
arome
#
# --------------------- begin processing   ---------------------------------------

u_arome = arome.u
v_arome = arome.v

u_arome = assign_2154_coords(u_arome)
v_arome = assign_2154_coords(v_arome)

for year, month in [
    (2019, 8),
    (2019, 9),
    (2019, 10),
    (2019, 11),
    (2019, 12),
    (2020, 1),
    (2020, 1),
    (2020, 2),
    (2020, 3),
    (2020, 4),
    (2020, 5),
    (2020, 6),
    (2020, 7),
]:
    time_range = slice(
        datetime(year, month, 1),
        datetime(year, (month + 1) % 12, 1) - timedelta(hours=1),
    )
    u_monthly = u_arome.sel(time=time_range)
    v_monthly = v_arome.sel(time=time_range)
    interpolated = get_interpolated_wind(
        u_monthly, v_monthly, u_arome.x, u_arome.y, target_dem
    )
    interpolated.to_netcdf(
        pj(
            data_dir,
            "grandmaison",
            "interpolated",
            f"wind_interpolation_{year}_{month}.nc",
        )
    )
    downscaled = compute_downscaled(interpolated.u, interpolated.v, unet_output)
    downscaled.to_netcdf(
        pj(
            data_dir,
            "grandmaison",
            "downscaled",
            f"wind_downscaling_{year}_{month}.nc",
        )
    )
    del interpolated, downscaled, u_monthly, v_monthly
    gc.collect()
