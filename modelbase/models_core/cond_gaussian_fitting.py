# Copyright (c) 2017 Philipp Lucas (philipp.lucas@uni-jena.de)

"""
@author: Philipp Lucas

This is a collection of methods to
  (i) fit parameters of various specific conditional gaussian model types to data, as well as
  (ii) conversion of a one parameter representation to another.

Data is generally given as a pandas data frame. Appropiate preperation is expected, e.g. normalization, no nans/nones, ...

Parameters are generally provided by means of numpy ndarrays. The order of categorical random variables in the given data frame is equivalent to the implicit order of dimensions (representing categorical random variables) in the derived parameters.

"""
from CGmodelselection.CG_CLZ_util import CG_CLZ_Utils
from CGmodelselection.CG_MAP_estimator import fitCGMeanParams
from CGmodelselection.dataops import getMetaData, prepareCGData

### model selection methods


def fit_pairwise_canonical(df):
    pass


def fit_clz_mean (df):
    """Fits parameters of a CLZ model to given data in pandas.DataFrame df and returns their representation as general mean paramters.

    Args:
        df: DataFrame of training data.
    """

    meta = getMetaData(df)
    D, Y = prepareCGData(df, meta, shuffle=False)  # transform discrete variables to indicator data
    # TODO: split into training and test data? if so: see Franks code
    solver = CG_CLZ_Utils()  # initialize problem
    solver.dropdata(D, Y, meta['L'])  # set training data
    # solve it attribute .x contains the solution parameter vector.
    res = solver.solveSparse(klbda=3, verb=True, innercallback=solver.nocallback)
    solver.getCanonicalParams(res.x, verb=True)

    (p, mus, Sigmas) = solver.getMeanParams(res.x, verb=True)
    return p, mus, Sigmas, meta

def fit_map_mean (df):
    """Fits parameters of a CLZ model to given data in pandas.DataFrame df and returns their representation as general mean paramters.

    Args:
        df: DataFrame of training data.
    """

    meta = getMetaData(df)
    D, Y = prepareCGData(df, meta, shuffle=False)  # transform discrete variables to indicator data
    # TODO: split into training and test data? if so: see Franks code
    

    (p, mus, Sigmas) = fitCGMeanParams(D, Y, meta, verb = False)
    return p, mus, Sigmas, meta

### parameter transformation methods


def clz_to_mean ():
    """Transforms a set of parameters for a CLZ model (as generated by fit_clz_canonical()) to the equivalent general
    mean parameters."""
    pass


def mean_to_canonical ():
    """Transforms a set of general mean parameters to their equivalent general canonical parameter representation."""
    pass


def canonical_to_mean ():
    """Transforms a set of general canonical parameters to their equivalent general mean parameter representation."""
    pass

