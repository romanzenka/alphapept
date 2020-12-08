# AUTOGENERATED! DO NOT EDIT! File to edit: nbs/08_quantification.ipynb (unless otherwise specified).

__all__ = ['gaussian', 'return_elution_profile', 'simulate_sample_profiles', 'get_peptide_error',
           'get_total_error_parallel', 'get_total_error', 'normalize_experiment_SLSQP', 'normalize_experiment_BFGS',
           'delayed_normalization', 'get_protein_ratios', 'triangle_error', 'solve_profile_LFBGSB',
           'solve_profile_SLSQP', 'solve_profile_trf', 'get_protein_table', 'protein_profile',
           'protein_profile_parallel']

# Cell
import random
import numpy as np
import logging

def gaussian(mu, sigma, grid):
    """
    Gaussian function
    """
    norm = 0.3989422804014327 / sigma
    return norm * np.exp(-0.5 * ((grid - mu) / sigma) ** 2)


def return_elution_profile(timepoint, sigma, n_runs):
    """
    Returns a gaussian elution profile for a given timepoint
    """
    return gaussian(timepoint, sigma, np.arange(0, n_runs))


def simulate_sample_profiles(n_peptides, n_runs, n_samples, threshold=0.2, use_noise=True):
    """
    Generate random profiles to serve as test_data
    """
    abundances = np.random.rand(n_peptides)*10e7

    true_normalization = np.random.normal(loc=1, scale=0.1, size=(n_runs, n_samples))

    true_normalization[true_normalization<0] = 0

    true_normalization = true_normalization/np.max(true_normalization)

    maxvals = np.max(true_normalization, axis=1)

    elution_timepoints = random.choices(list(range(n_runs)), k=n_peptides)

    profiles = np.empty((n_runs, n_samples, n_peptides))
    profiles[:] = np.nan

    for i in range(n_peptides):

        elution_timepoint = elution_timepoints[i]
        abundance = abundances[i]

        profile = return_elution_profile(elution_timepoint, 1, n_runs)
        profile = profile/np.max(profile)
        profile = profile * abundance
        elution_profiles = np.tile(profile, (n_samples, 1)).T

        # Add Gaussian Noise
        if use_noise:
            noise = np.random.normal(1, 0.2, elution_profiles.shape)
            noisy_profile = noise * elution_profiles
        else:
            noisy_profile = elution_profiles

        normalized_profile = noisy_profile * true_normalization

        normalized_profile[normalized_profile < threshold] = 0
        normalized_profile[normalized_profile == 0] = np.nan


        profiles[:,:,i] = normalized_profile

    return profiles, true_normalization

# Cell
from numba import njit, prange

@njit
def get_peptide_error(profile, normalization):

    pep_ints = np.zeros(profile.shape[1])

    normalized_profile = profile*normalization

    for i in range(len(pep_ints)):
        pep_ints[i] = np.nansum(normalized_profile[:,i])

    pep_ints = pep_ints[pep_ints>0]

    # Loop through all combinations
    n = len(pep_ints)

    error = 0
    for i in range(n):
        for j in range(i+1,n):
            error += np.abs(np.log(pep_ints[i]/pep_ints[j]))**2

    return error


@njit(parallel=True)
def get_total_error_parallel(normalization, profiles):

    normalization = normalization.reshape(profiles.shape[:2])

    total_error = 0

    for index in prange(profiles.shape[2]):
        total_error += get_peptide_error(profiles[:,:, index], normalization)

    return total_error


def get_total_error(normalization, profiles):

    normalization = normalization.reshape(profiles.shape[:2])

    total_error = 0

    for index in range(profiles.shape[2]):
        total_error += get_peptide_error(profiles[:,:, index], normalization)

    return total_error

# Cell
from scipy.optimize import minimize
import pandas as pd
import numpy as np

def normalize_experiment_SLSQP(profiles):
    """
    Calculate normalization with SLSQP approach
    """
    x0 = np.ones(profiles.shape[0] * profiles.shape[1])
    bounds = [(0.1, 1) for _ in x0]
    res = minimize(get_total_error, args = profiles , x0 = x0*0.5, bounds=bounds, method='SLSQP', options={'disp': False} )

    solution = res.x/np.max(res.x)
    solution = solution.reshape(profiles.shape[:2])

    return solution

def normalize_experiment_BFGS(profiles):
    """
    Calculate normalization with BFGS approach
    """
    x0 = np.ones(profiles.shape[0] * profiles.shape[1])
    bounds = [(0.1, 1) for _ in x0]
    res = minimize(get_total_error, args = profiles , x0 = x0*0.5, bounds=bounds, method='L-BFGS-B', options={'disp': False} )

    solution = res.x/np.max(res.x)
    solution = solution.reshape(profiles.shape[:2])

    return solution

def delayed_normalization(df, field='int_sum', minimum_occurence=None):
    """
    Returns normalization for given peptide intensities
    """
    files = np.sort(df['shortname'].unique()).tolist()
    n_files = len(files)

    if 'fraction' in df.keys():
        fractions = np.sort(df['fraction'].unique()).tolist()
        n_fractions = len(fractions)

        df_max = df.groupby(['precursor','fraction','shortname'])[field].max() #Maximum per fraction

        prec_count = df_max.index.get_level_values('precursor').value_counts()

        if not minimum_occurence:
            minimum_occurence = np.percentile(prec_count[prec_count>1].values, 75) #Take the 25% best datapoints
            logging.info('Setting minimum occurence to {}'.format(minimum_occurence))

        shared_precs = prec_count[prec_count >= minimum_occurence]
        precs = prec_count[prec_count > minimum_occurence].index.tolist()

        n_profiles = len(precs)

        selected_precs = df_max.loc[precs]
        selected_precs = selected_precs.reset_index()

        profiles = np.empty((n_fractions, n_files, n_profiles))
        profiles[:] = np.nan

        #get dictionaries
        fraction_dict = {_:i for i,_ in enumerate(fractions)}
        filename_dict = {_:i for i,_ in enumerate(files)}
        precursor_dict = {_:i for i,_ in enumerate(precs)}

        prec_id = [precursor_dict[_] for _ in selected_precs['precursor']]
        frac_id = [fraction_dict[_] for _ in selected_precs['fraction']]
        file_id = [filename_dict[_] for _ in selected_precs['shortname']]

        profiles[frac_id,file_id, prec_id] = selected_precs[field]

        try:
            normalization = normalize_experiment_SLSQP(profiles)
        except ValueError: # SLSQP error in scipy https://github.com/scipy/scipy/issues/11403
            logging.info('Normalization with SLSQP failed. Trying BFGS')
            normalization = normalize_experiment_BFGS(profiles)


        #intensity normalization: total intensity to remain unchanged

        df[field+'_dn'] = df[field]*normalization[[fraction_dict[_] for _ in df['fraction']], [filename_dict[_] for _ in df['shortname']]]
        df[field+'_dn'] *= df[field].sum()/df[field+'_dn'].sum()

    else:
        logging.info('No fractions present. Skipping delayed normalization.')
        normalization = None

    return df, normalization

# Cell
from numba import njit

@njit
def get_protein_ratios(signal, column_combinations, minimum_ratios = 1):
    n_samples = signal.shape[1]
    ratios = np.empty((n_samples, n_samples))
    ratios[:] = np.nan

    for element in column_combinations:
        i = element[0]
        j = element[1]

        ratio = signal[:,j] / signal[:,i]

        non_nan = np.sum(~np.isnan(ratio))

        if non_nan >= minimum_ratios:
            ratio_median = np.nanmedian(ratio)
        else:
            ratio_median = np.nan

        ratios[j,i] = ratio_median

    return ratios

# Cell
@njit
def triangle_error(normalization, ratios):
    int_matrix = np.repeat(normalization, len(normalization)).reshape((len(normalization), len(normalization))).transpose()
    x = (np.log(ratios) - np.log(int_matrix.T) + np.log(int_matrix))**2

    return np.nansum(x)

# Cell
## L-BFGS-B


from scipy.optimize import minimize, least_squares

# LFBGSB

def solve_profile_LFBGSB(ratios):
    x0 = np.ones(ratios.shape[1])
    bounds = [(x0[0]*0+0.01, x0[0]) for _ in x0]
    res_wrapped = minimize(triangle_error, args = ratios , x0 = x0*0.5, bounds=bounds, method = 'L-BFGS-B')
    solution = res_wrapped.x
    solution = solution/np.max(solution)
    return solution, res_wrapped.success


def solve_profile_SLSQP(ratios):
    x0 = np.ones(ratios.shape[1])
    bounds = [(x0[0]*0+0.01, x0[0]) for _ in x0]
    res_wrapped = minimize(triangle_error, args = ratios , x0 = x0*0.5, bounds=bounds, method = 'SLSQP', options={'maxiter':10000})
    solution = res_wrapped.x
    solution = solution/np.max(solution)
    return solution, res_wrapped.success


# TRF
def solve_profile_trf(ratios):
    x0 = np.ones(ratios.shape[1])
    bounds = (x0*0+0.01, x0)
    res_wrapped = least_squares(triangle_error, args = [ratios] , x0 = x0*0.5, bounds=bounds, verbose=0, method = 'trf')
    solution = res_wrapped.x
    solution = solution/np.max(solution)
    return solution, res_wrapped.success

# Cell
from numba.typed import List
from itertools import combinations

def get_protein_table(df, field = 'int_sum', minimum_ratios = 1, callback = None):
    unique_proteins = df['protein'].unique()
    files = df['shortname'].unique().tolist()
    files.sort()

    if len(files) == 1:
        raise ValueError('Only one file present.')

    column_combinations = List()
    [column_combinations.append(_) for _ in combinations(range(len(files)), 2)]

    columnes_ext = [_+'_LFQ' for _ in files]
    protein_table = pd.DataFrame(index=unique_proteins, columns=columnes_ext + files)

    if field+'_dn' in df.columns:
        field_ = field+'_dn'
    else:
        field_ = field

    if df[field_].min() < 0:
        raise ValueError('Negative intensity values present.')

    for idx, protein in enumerate(unique_proteins):
        subset = df[df['protein'] == protein].copy()
        per_protein = subset.groupby(['shortname','precursor'])[field_].sum().unstack().T

        for _ in files:
            if _ not in per_protein.columns:
                per_protein[_] = np.nan

        per_protein = per_protein[files]

        ratios = get_protein_ratios(per_protein.values, column_combinations, minimum_ratios)
        try:
            solution, success = solve_profile_SLSQP(ratios)
        except ValueError:
            logging.info('Normalization with SLSQP failed. Trying BFGS')
            solution, success = solve_profile_LFBGSB(ratios)

        file_ids = per_protein.columns.tolist()

        pre_lfq = per_protein.sum().values

        if not success or np.sum(~np.isnan(ratios)) == 0: # or np.sum(solution) == len(pre_lfq):
            profile = pre_lfq
        else:
            invalid = ((np.nansum(ratios, axis=1) == 0) & (np.nansum(ratios, axis=0) == 0))
            total_int = subset[field_].sum() * solution
            total_int[invalid] = 0
            profile = total_int * subset[field_].sum().sum() / np.sum(total_int) #Normalize inensity again


        protein_table.loc[protein, [_+'_LFQ' for _ in file_ids]] = profile
        protein_table.loc[protein, file_ids] = pre_lfq

        if callback:
            callback((idx+1)/len(unique_proteins))

    protein_table[protein_table == 0] = np.nan
    protein_table = protein_table.astype('float64')

    return protein_table

def protein_profile(df, files, field_, protein, minimum_ratios=1):
    """
    Calculate the protein profile for a a df based on a dateframe

    """
    column_combinations = List()
    [column_combinations.append(_) for _ in combinations(range(len(files)), 2)]

    subset = df[df['protein'] == protein].copy()
    per_protein = subset.groupby(['shortname','precursor'])[field_].sum().unstack().T

    for _ in files:
        if _ not in per_protein.columns:
            per_protein[_] = np.nan

    per_protein = per_protein[files]

    ratios = get_protein_ratios(per_protein.values, column_combinations, minimum_ratios)
    try:
        solution, success = solve_profile_SLSQP(ratios)
    except ValueError:
        logging.info('Normalization with SLSQP failed. Trying BFGS')
        solution, success = solve_profile_LFBGSB(ratios)

    file_ids = per_protein.columns.tolist()
    pre_lfq = per_protein.sum().values

    if not success or np.sum(~np.isnan(ratios)) == 0: # or np.sum(solution) == len(pre_lfq):
        profile = pre_lfq
    else:
        invalid = ((np.nansum(ratios, axis=1) == 0) & (np.nansum(ratios, axis=0) == 0))
        total_int = subset[field_].sum() * solution
        total_int[invalid] = 0
        profile = total_int * subset[field_].sum().sum() / np.sum(total_int) #Normalize inensity again

    return profile, pre_lfq, file_ids, protein


import os
from multiprocessing import Pool
from functools import partial


def protein_profile_parallel(settings, df, callback=None):

    n_processes = settings['general']['n_processes']
    field = settings['quantification']['mode']

    unique_proteins = df['protein'].unique().tolist()

    files = df['shortname'].unique().tolist()

    files.sort()

    columnes_ext = [_+'_LFQ' for _ in files]
    protein_table = pd.DataFrame(index=unique_proteins, columns=columnes_ext + files)

    if field+'_dn' in df.columns:
        field_ = field+'_dn'
    else:
        field_ = field

    if df[field_].min() < 0:
        raise ValueError('Negative intensity values present.')

    results = []

    if len(files) > 1:
        with Pool(n_processes) as p:
            max_ = len(unique_proteins)
            for i, _ in enumerate(p.imap_unordered(partial(protein_profile, df, files, field_), unique_proteins)):
                results.append(_)
                if callback:
                    callback((i+1)/max_)

        for result in results:

            profile, pre_lfq, file_ids, protein = result
            protein_table.loc[protein, [_+'_LFQ' for _ in file_ids]] = profile
            protein_table.loc[protein, file_ids] = pre_lfq

        protein_table[protein_table == 0] = np.nan
        protein_table = protein_table.astype('float')
    else:
        protein_table = df.groupby(['protein'])[field_].sum().to_frame().reset_index()
        protein_table = protein_table.set_index('protein')
        protein_table.index.name = None
        protein_table.columns=[files[0]]

        if callback:
            callback(1)

    return protein_table