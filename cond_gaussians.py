import logging
import numpy as np
from numpy import matrix, ix_, nan, pi, exp
import pandas as pd
import xarray as xr

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
                data structure used: xarray DataArray with 2 dimensions dim_0 and dim_1. Both dimensions have
                    coordinates that match the names of the continuous random variables.
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

        Furthermore there are a number of precomputed values:
            _SInv:
                meaning: the inverse of _S
            _detS
                meaning: the determinant of _S
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
        self._SInv = nan
        self._detS = nan

    @staticmethod
    def _fitFullLikelihood(data, fields, dc):
        """fit full likelihood for CG model. the data frame data consists of dc many categorical columns and the rest are
        numerical columns. all categorical columns occure before the numercial ones."""
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
        dims = list(catcols) + ['mean']
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
        Sigma = xr.DataArray(Sigma, coords=[gausscols]*2)

        return pML, musML, Sigma

    def fit(self, df):
        """Fits the model to passed DataFrame.

        Parameters:
            df: A pandas data frame that holds the data to fit the model to. All columns of df are used.

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
        self.fields = fields
        self._update()

        dc = len(categoricals)

        (p, mus, Sigma) = ConditionallyGaussianModel._fitFullLikelihood(df, fields, dc)
        self._p = p
        self._mu = mus
        self._S = Sigma
        self._categoricals = categoricals
        self._numericals = numericals

        return self.update()

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
        df = pd.concat([df_cat, df_num], axis=1)
#        df.plot.scatter(x="age", y="income")
        return df

    def update(self):
        """Updates dependent parameters / precalculated values of the model after some internal changes."""
        self._update()

        if self._n == 0:
            self._detS = nan
            self._SInv = nan
        else:
            self._detS = np.abs(np.linalg.det(self._S))
            self._SInv = np.linalg.inv(self._S)

        return self

    def _conditionout(self, remove):
        if len(remove) == 0 or self._isempty():
            return self
        if len(remove) == self._n:
            return self._setempty()

        # condition on categorical fields
        # _S remains unchanged
        categoricals = [self.byname(name) for name in self._categoricals if name in remove]
        if len(categoricals) != 0:
            # note: if we condition on all categoricals the following procedure also works. It simply remains the single
            # 'selected' mu...
            # _p changes like in the categoricals.py case
            pairs = []
            # todo: factor this out. its the same as in categoricals and we can put it as a function there
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

        # condition on continuous fields
        numericals = [self.byname(name) for name in self._numericals if name in remove]  # guaranteed to be sorted!
        if len(numericals) == len(self._numericals):
            # all gaussians are implicitely removed
            self._S = nan
            self._mu = nan
        elif len(numericals) != 0:
            # collect singular values to condition out
            condvalues = []
            # todo: factor this out. its the same as in gaussians and we can put it as a function there
            for field in numericals:
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
            i = [idx - len(self._categoricals) for idx in self.asindex(numericals)]
            j = utils.invert_indexes(i, len(self._numericals))

            S = self._S
            self._S = MultiVariateGaussianModel._schurcompl_upper(S, i)

            # iterate over all mu and update them
            stacked = self._mu.stack(pl_stack=tuple(numericals))  # this is a reference to mu!
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

        num_keep = [name for name in self._numericals if name in keep]  # note: this is guaranteed to be sorted
        #num_remove = [name for name in self._numericals if name not in keep]
        #cat_keep = [name for name in self._categoricals if name in keep]
        cat_remove = [name for name in self._categoricals if name not in keep]

        # use weak marginals to get the best approximation of the marginal distribution that is still a cg-distribution
        # clone old values
        p = self._p.copy()
        mu = self._mu.copy()

        # todo: fix integer indices (offset because of ordering of fields)
        # marginalize p just like in the categorical case (categoricals.py), i.e. sum up over removed dimensions
        self._p = self._p.sum(cat_remove)

        # marginalized mu (take from the script)
        # slice out the gaussian part to keep; sum over the categorical part to remove
        #num_keep_idx = [idx - len(self._categoricals) for idx in self.asindex(num_keep)]
        mu = mu.loc[dict(mean=num_keep)]
        self._mu = (p * mu).sum(cat_remove) / self._p

        # marginalized sigma
        # TODO: this is kind of wrong... the best CG-approximation does not have a single S but a different one for each x in omega_X...
        #self._S = self._S[np.ix_(num_keep_idx, num_keep_idx)]
        self._S = self._S.loc[num_keep, num_keep]

        keep = set(keep)
        self.fields = [field for field in self.fields if field['name'] in keep]
        return self.update()

    def _density(self, x):
        """Returns the density of the model at point x.

        Args:
            x: a list of values as input for the density.
        """

        cat_len = len(self._categoricals)
        num_len = len(self._numericals)
        cat = x[:cat_len]
        num = x[cat_len:]

        p = self._p.loc[:, cat]
        mu = self._mu.loc[:, cat]  # todo: gibt mir das wirklich ein mu?

        num = matrix(num).T  # turn into column vector of type numpy matrix
        xmu = num - mu
        return (p * (2 * pi) ** (-num_len / 2) * (self._detS ** -.5) * exp(-.5 * xmu.T * self._SInv * xmu)).item()

    def _maximum(self):
        """Returns the point of the maximum density in this model"""
        # categorical part
        # TODO: ask Frank about it
        # I think its just scanning over all x of omega_x, since there is only one sigma
        # i.e. this is like in the categorical case
        p = self._p
        pmax = p.where(p == p.max(), drop=True)  # get view on maximum (coordinates remain)
        cat_argmax = [idx[0] for idx in pmax.indexes.values()]  # extract coordinates from indexes

        # gaussian part
        # the mu is the mean and the maximum of the conditional gaussian
        # todo: don't think that way of indexing works...
        num_argmax = self._mu.loc[cat_argmax]

        return cat_argmax + num_argmax

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
    # generate input data
    Sigma = np.diag([1, 1, 1])
    Sigma = np.matrix([[1, 0, 0.5], [0, 1, 0], [0.5, 0, 1]])
    Sigma = np.diag([1, 1, 1, 1])

    # select data set using this indicator variable
    dataset = "dummy_cg"
    #dataset = "a"
    #dataset = "b"

    if dataset == "a":
        n = 1000
        testopts = {'levels': {0: [1, 2, 3, 4], 1: [2, 5, 10], 2: [1, 2]},
                    'Sigma': Sigma,
                    'fun': genCatData,
                    'catvalasmean': 1,  # works if dc = dg
                    'seed': 10}
        data = genCGSample(n, testopts)  # categoricals first, then gaussians, np array
        dc = len(testopts.keys())
    elif dataset == "b":
        n = 1000
        testopts = {'levels': {0: [0, 1], 1: [0, 1], 2: [0, 1]},
                    'Sigma': Sigma,
                    'fun': genCatDataJEx,
                    'catvalasmean': 1,
                    'seed': 10}
        data = genCGSample(n, testopts)  # categoricals first, then gaussians, np array
        dc = len(testopts.keys())
        print("dc ", dc)
    elif dataset == "dummy_cg":
        data = ConditionallyGaussianModel.cg_dummy()

    # fit model
    model = ConditionallyGaussianModel('testmodel')
    model.fit(data)

    # print some information about the model
    print(model)
    print('p_ML: \n', model._p)
    print('mu_ML: \n', model._mu)
    print('Sigma_ML: \n', model._S)

    #ind = (0, 1, 1)
    #print('mu(', [model._extents[i][ind[i]] for i in ind], '):', model._mu[ind])
    #print(np.histogram(data[:, dc]))
    #plothist(data.iloc[:, dc + 1].ravel())

    # PHILIPP
    #model.condition([('city', "==", 'Jena')])
    #model.marginalize(remove=['city'])
    model.model(model=['sex', 'city', 'age'])  # marginalize income out
    model.model(model=['sex', 'age'], where=[('city', "==", 'Jena')])  # condition city out






