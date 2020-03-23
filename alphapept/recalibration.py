# AUTOGENERATED! DO NOT EDIT! File to edit: 07_recalibration.ipynb (unless otherwise specified).

__all__ = ['estimate_stepsize', 'get_calibration']

# Cell

from scipy.interpolate import griddata
import pandas as pd
import numpy as np


def estimate_stepsize(df, min_mz_step = 80, min_rt_step = 50, **kwargs):
    """
    Function to estimate the stepsize for recalibration

    """
    points_rt = np.sort(df['rt'].values)[::min_rt_step]
    points_mz = np.sort(df['mz'].values)[::min_mz_step]

    mz_step = np.round(np.mean(np.diff(points_mz))) #1 Th precision
    rt_step = np.round(np.mean(np.diff(points_rt)),1) #0.1 minute precision

    # Minimum values are 1 Da and 0.1 minutes
    if mz_step < 1:
        mz_step = 1
    if rt_step < 0.1:
        rt_step = 0.1

    return mz_step, rt_step


def get_calibration(df, features, minimum_score = 20, outlier_std = 3, method='linear', min_mz_step=80, min_rt_step=50, callback = None, **kwargs):
    """
    Calibration

    Brief description

    (1) From the scored psms isolate the o_mass ppm offset. Filter for x std deviations
    (2) Estimate a stepsize for interpolation to ensure minimum sampling
    (3) Use points to interpolate on a grid
    (4) Use grid to interpolate offset for features

    """

    df_sub = df.copy()

    # Remove outliers for calibration
    o_mass_std = df_sub['o_mass_ppm'].std()
    o_mass_mean = df_sub['o_mass_ppm'].mean()

    df_sub = df_sub.query('score > @minimum_score and o_mass_ppm < @o_mass_mean+@outlier_std*@o_mass_std and o_mass_ppm > -@o_mass_mean-@outlier_std*@o_mass_std')

    mz_step, rt_step = estimate_stepsize(df_sub, min_mz_step, min_rt_step, **kwargs)

    #Define a grid for valid interpolation

    min_x = np.floor(df_sub['mz'].min())
    max_x = np.ceil(df_sub['mz'].max())
    step_x = mz_step

    min_y = np.floor(df_sub['rt'].min())
    max_y = np.ceil(df_sub['rt'].max())
    step_y = rt_step

    tx = np.arange(min_x, max_x, step_x) #mz
    ty = np.arange(min_y, max_y, step_y) #rt

    xx, yy = np.meshgrid(tx, ty)

    f1 = griddata(df_sub[['mz','rt']].values,  df_sub['o_mass_ppm'].values, (xx, yy) , fill_value = 0, method = method, rescale=True)

    f2 = griddata(np.vstack([xx.flatten(),yy.flatten()]).T, f1.flatten(), df_sub[['mz','rt']].values, fill_value=0, method = method, rescale=True)

    df_sub['o_mass_ppm_offset'] = f2
    df_sub['o_mass_ppm_calib'] = (df_sub['o_mass_ppm']-df_sub['o_mass_ppm_offset'])

    #Apply to features

    offset = griddata(np.vstack([xx.flatten(), yy.flatten()]).T, f1.flatten(), features[['mz_matched','rt_matched']].values, fill_value=0, method = method, rescale=True)/1e6*features['mass_matched']

    features_calib = features.copy()
    features_calib['mass_matched_raw'] = features_calib['mass_matched'].copy()
    features_calib['mass_matched'] -= offset
    features_calib['mass_offset'] = offset
    features_calib = features_calib.sort_values('mass_matched', ascending=True)

    return features_calib, df_sub
