import logging
import numpy as np
from numpy import matrix, ix_, nan
import pandas as pd
import xarray as xr
from numpy.distutils.system_info import numerix_info

import utils
import models as md
from gaussians import MultiVariateGaussianModel
import domains as dm

#imports frank
from cond_gaussians.datasampling import genCGSample, genCatData, genCatDataJEx
from cond_gaussians.output import plothist

# setup logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.WARNING)


def getCumlevelsAndDict(levels, excludeindex=None):
    """
    cumlevels[i] ... total # of levels of categorical variables with index <=i
    dval2ind[i][v] ... index of value v in the list of levels of variable i
    """
    dc = len(levels.keys())

    dval2ind = {}
    for i in range(dc):
        dval2ind[i] = {}
        for j, v in enumerate(levels[i]):
            dval2ind[i][v] = j  # assign numerical value to each level of variable i

    cumlevels = [0]
    for v in levels.keys():
        cumlevels.append(cumlevels[-1] + len(levels[v]))

    return (cumlevels, dval2ind)


class ConditionallyGaussianModel(md.Model):
    """A conditional gaussian model and methods to derive submodels from it
    or query density and other aggregations of it.

    Note that all conditional Gaussians use the same covariance matrix. Their mean, however, is not identical.

    Internal:
        Assume a CG-model on m categorical random variables and n continuous random variables.
        The model is parametrized using the mean parameters as follows:
            _p:
                meaning: probability look-up table for the categorical part of the model.
                data structure used: xarray DataArray. The labels of the dimensions and the coordinates of each
                    dimension are the same as the name of the categorical fields and their domain, respectively.
                    Each entry of the DataArray is a scalar, i.e. the probability of that event.
            _S:
                meaning: covariance matrix of the conditionals. All conditionals share the same covariance!
                data structure used: numpy array
            _mu:
                meaning: the mean of each conditional gaussian.
                data structure used: xarray DataArray with m+1 dimensions. The first m dimensions represent the
                categorical random variables of the model and are labeled accordingly. The last dimension represents
                the mean vector of the continuous part of the model and is therefore of length n.

            _categoricals:
                list of names of all categorical fields (in same order as they appear in fields)

            _numericals:
                list of names of all continuous fields (in same order as they appear in fields)

            fields:
                list of fields of this model. continuous fields are stored __before__ categorical ones.
    """

    def __init__(self, name):
        super().__init__(name)

        self._aggrMethods = {
            'maximum': self._maximum,
            'average': self._maximum
        }

        self._categoricals = []
        self._numericals = []
        self._p = nan
        self._mu = nan
        self._S = nan
        self._extents = []

    def _fitFullLikelihood(self, data, fields, dc):
        """fit full likelihood for CG model"""
        n, d = data.shape
        dg = d - dc

        cols = data.columns
        catcols = cols[:dc]
        gausscols = cols[dc:]

        extents = [f['extent'].value() for f in fields[:dc]]  # levels
        sizes = [len(v) for v in extents]
        #        print('extents:', extents)

        z = np.zeros(tuple(sizes))
        pML = xr.DataArray(data=z, coords=extents, dims=catcols)

        # mus
        mus = np.zeros(tuple(sizes + [dg]))
        coords = extents + [[contname for contname in gausscols]]
        dims = catcols | [['mean']]
        musML = xr.DataArray(data=mus, coords=coords, dims=dims)

        # calculate p(x)
        for row in data.itertuples():
            cats = row[1:1 + dc]
            gauss = row[1 + dc:]

            pML.loc[cats] += 1
            musML.loc[cats] += gauss

            #        print(pMLx)

        it = np.nditer(pML, flags=['multi_index'])  # iterator over complete array
        while not it.finished:
            ind = it.multi_index
            #            print "%d <%s>" % (it[0], it.multi_index)
            #            print(ind, pMLx[ind])
            musML[ind] /= pML[ind]
            it.iternext()
        pML /= 1.0 * n

        Sigma = np.zeros((dg, dg))
        for row in data.itertuples():
            cats = row[1:1 + dc]
            gauss = row[1 + dc:]
            ymu = np.matrix(gauss - musML.loc[cats])
            Sigma += np.dot(ymu.T, ymu)

        Sigma /= n

        return pML, musML, Sigma

    def fit(self, df):
        """Fits the model to passed DataFrame

        Parameters:
            df: A pandas data frame that holds the data to fit the model to. All columns in the data frame will be used.
                The data frame must have its columns ordered such that categorical columns occur before continuous
                columns.

        Internal:
            This method estimates the set of mean parameters that fit best to the data given in the dataframe df.

        Returns:
            The modified model with selected parameters set.
        """
        # split in categorical and numeric columns
        categoricals = []
        numericals = []
        for colname in df:
            column = df[colname]
            # if column.dtype == "category" or column.dtype == "object":
            if column.dtype == "object":
                categoricals.append(colname)
            else:
                numericals.append(colname)

        # reorder data frame such that categorical columns are first
        df = pd.DataFrame(df, columns=categoricals + numericals)

        #  derive fields
        fields = []
        for colname in categoricals:
            column = df[colname]
            domain = dm.DiscreteDomain()
            extent = dm.DiscreteDomain(sorted(column.unique()))
            field = md.Field(colname, domain, extent, 'string')
            fields.append(field)
        for colname in numericals:
            column = df[colname]
            field = md.Field(colname, dm.NumericDomain(), dm.NumericDomain(column.min(), column.max()), 'numerical')
            fields.append(field)

        # update field access by name
        self._update()

#        data = genCGSample(n, testopts) # categoricals first, then gaussians
        dg = len(numericals);
        dc = len(categoricals);
        d = dc + dg

        # get levels
        extents = [f['extent'].value() for f in fields[:dc]]

#        print(df[0:10])

        (p, mus, Sigma) = self._fitFullLikelihood(df, fields, dc)
        self._p = p
        self._mu = mus
        self._S = Sigma
        self._extents = extents
        self._categoricals = categoricals
        self._numericals = numericals

    @staticmethod
    def cg_dummy():
        """Returns a dataframe that contains sample of a 4d cg distribution. See the code for the used parameters."""
        # chose fixed parameters
        mu_M_Jena = [0, 0]
        mu_F_Jena = [1, 3]
        mu_M_Erfurt = [-10, 1]
        mu_F_Erfurt = [-5, -6]
        S = [[3, 0.5], [0.5, 1]]
        dims = ['sex', 'city', 'age', 'income']
        # and a sample size
        samplecnt = 200

        # generate samples for each and arrange in dataframe
        df_cat = pd.concat([
            pd.DataFrame([["M", "Jena"]] * samplecnt, columns=['sex', 'city']),
            pd.DataFrame([["F", "Jena"]] * samplecnt, columns=['sex', 'city']),
            pd.DataFrame([["M", "Erfurt"]] * samplecnt, columns=['sex', 'city']),
            pd.DataFrame([["F", "Erfurt"]] * samplecnt, columns=['sex', 'city'])
        ])

        df_num = pd.concat([
            pd.DataFrame(np.random.multivariate_normal(mu_M_Jena, S, samplecnt), columns=['age', 'income']),
            pd.DataFrame(np.random.multivariate_normal(mu_F_Jena, S, samplecnt), columns=['age', 'income']),
            pd.DataFrame(np.random.multivariate_normal(mu_M_Erfurt, S, samplecnt), columns=['age', 'income']),
            pd.DataFrame(np.random.multivariate_normal(mu_F_Erfurt, S, samplecnt), columns=['age', 'income'])
        ])
        df = pd.concat([df_num, df_cat], axis=1)
#        df.plot.scatter(x="age", y="income")
        return df


    def update(self):
        """Updates dependent parameters / precalculated values of the model after some internal changes."""
        self._update()
        raise NotImplementedError()
        return self

    def _conditionout(self, remove):
        if len(remove) == 0 or self._isempty():
            return self
        if len(remove) == self._n:
            return self._setempty()

        # condition on categorical fields
        # _S remains unchanged
        categoricals = [name for name in self._categoricals if name in remove]

        # _p changes like in the categoricals.py case
        pairs = []
        for field in categoricals:
            domain = field['domain']
            dvalue = domain.value()
            assert (domain.isbounded())
            if field['dtype'] == 'string':
                # TODO: we don't know yet how to condition on a not singular, but not unrestricted domain.
                pairs.append((field['name'], dvalue if domain.issingular() else dvalue[0]))
            else:
                raise ValueError('invalid dtype of field: ' + str(field['dtype']))

        # trim the probability look-up table to the appropriate subrange and normalize it
        p = self._p.loc[dict(pairs)]
        self._p = p / p.sum()

        # _mu is trimmed: keep the slice that we condition on, i.e. reuse the 'pairs' access-structure
        self._mu = self._mu.loc[dict(pairs)]

        # todo: spezialfall "alle categoricals fallen raus"

        # condition on continuous fields
        continuous = [name for name in self._continuous if name in remove]  # note: this is guaranteed to be sorted

        # collect singular values to condition out
        condvalues = []
        for field in continuous:
            domain = field['domain']
            dvalue = domain.value()
            assert (domain.isbounded())
            if field['dtype'] == 'numerical':
                condvalues.append(dvalue if domain.issingular() else (dvalue[1] - dvalue[0]) / 2)
                # TODO: we don't know yet how to condition on a not singular, but not unrestricted domain.
            else:
                raise ValueError('invalid dtype of field: ' + str(field['dtype']))
        condvalues = matrix(condvalues).T

        # calculate updated mu and sigma for conditional distribution, according to GM script
        i = self.asindex(continuous)
        j = utils.invert_indexes(i, len(self._continuous))

        S = self._S
        self._S = MultiVariateGaussianModel._schurcompl_upper(S, i)

        # iterate over all mu and update them
        stacked = self._mu.stack(pl_stack=tuple(continuous))  # this is a reference to mu!
        Sigma_expr = S[ix_(i, j)] * S[ix_(j, j)].I
        for coord in stacked.pl_stack:
            indexer = dict(pl_stack=coord)
            mu = stacked.loc[indexer]
            stacked.loc[indexer] = mu[i] + Sigma_expr * (condvalues - mu[j])

        # remove fields as needed
        remove = set(remove)
        self.fields = list(filter(lambda f: f.name not in remove, self.fields))

        return self.update()

    def _marginalizeout(self, keep):
        if len(keep) == self._n or self._isempty():
            return self
        if len(keep) == 0:
            return self._setempty()

        # i.e.: just select the part of mu and sigma that remains
        #keepidx = sorted(self.asindex(keep))
        # TODO
        raise NotImplementedError()
        #self.fields = [self.fields[idx] for idx in keepidx]
        return self.update()

    def _density(self, x):
        """Returns the density of the model at point x.

        Args:
            x: a list of values as input for the density.
        """
        raise NotImplementedError()

    def _maximum(self):
        """Returns the point of the maximum density in this model"""
        raise NotImplementedError()

    def _sample(self):
        raise NotImplementedError()

    def copy(self, name=None):
        name = self.name if name is None else name
        mycopy = ConditionallyGaussianModel(name)
        # todo: implement rest
        #raise NotImplementedError()
        #mycopy.update()
        #return mycopy


if __name__ == '__main__':
    #    import pdb

    Sigma = np.diag([1, 1, 1])
    Sigma = np.matrix([[1, 0, 0.5], [0, 1, 0], [0.5, 0, 1]])
    Sigma = np.diag([1, 1, 1, 1])

    independent = 0
    if independent:
        n = 1000
        testopts = {'levels': {0: [1, 2, 3, 4], 1: [2, 5, 10], 2: [1, 2]},
                    'Sigma': Sigma,
                    'fun': genCatData,
                    'catvalasmean': 1,  # works if dc = dg
                    'seed': 10}
    else:
        n = 1000
        testopts = {'levels': {0: [0, 1], 1: [0, 1], 2: [0, 1]},
                    'Sigma': Sigma,
                    'fun': genCatDataJEx,
                    'catvalasmean': 1,
                    'seed': 10}
    dc = len(testopts.keys())

    data = genCGSample(n, testopts)  # categoricals first, then gaussians, np array



    model = ConditionallyGaussianModel('model1')

    model.fit(data)

    print ('pML:', model._p)

    ind = (0,1,1)
    print('mu(',[model._extents[i][ind[i]] for i in ind], '):', model._mu[ind])

    print('Sigma:', model._S)

#    print(np.histogram(data[:, dc]))
    plothist(data.iloc[:, dc+1].ravel())