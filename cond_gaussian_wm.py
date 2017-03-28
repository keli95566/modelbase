# Copyright (c) 2017 Philipp Lucas and Frank Nussbaum, FSU Jena
import logging
import numpy as np
from numpy import nan, pi, exp, dot, abs
from numpy.linalg import inv, det
import xarray as xr

import models as md
import cond_gaussians as cg

logger = logging.getLogger(__name__)
logger.setLevel(logging.WARNING)


class CgWmModel(md.Model):
    """A conditional gaussian model and methods to derive submodels from it
    or query density and other aggregations of it.

    In this model each conditional Gaussian uses its own covariance matrix and mean vector. This is
    effective difference to the ConditionallyGaussianModel-class.

    Internal:
        Assume a CG-model on m categorical random variables and n continuous random variables.
        The model is parametrized using the mean parameters as follows:
            _p:
                meaning: probability look-up table for the categorical part of the model.
                data structure used: xarray DataArray. The labels of the dimensions and the coordinates of each
                    dimension are the same as the name of the categorical fields and their domain, respectively.
                    Each entry of the DataArray is a scalar, i.e. the probability of that event.

            _S:
                meaning: covariance matrix of each of the conditionals.
                data structure used: xarray DataArray with m+2 dimensions. The first m dimensions represent the
                    categorical random variables of the model and are labeled accordingly. The last two dimensions
                    represents the mean vector of the continuous part of the model and are therefore of length n.
                    The labels of the last two dimensions are 'S1' and 'S2'.

            _mu:
                meaning: the mean of each conditional gaussian.
                data structure used: xarray DataArray with m+1 dimensions. The first m dimensions represent the
                    categorical random variables of the model and are labeled accordingly. The last dimension represents
                    the mean vector of the continuous part of the model and is therefore of length n. The label of the
                    last dimension is 'mean'

            _categoricals:
                list of names of all categorical fields (in same order as they appear in fields)

            _numericals:
                list of names of all continuous fields (in same order as they appear in fields)

            fields:
                list of fields of this model. continuous fields are stored __before__ categorical ones.

        Furthermore there are a number of internally held precomputed values:
            _SInv:
                meaning: the inverse of _S
            _detS
                meaning: abs(det(S))**-0.5

    Limitations:
        inference queries:
            Marginalizing out on any categorical variable leads to an inexact model. Conditional Gaussian models are
             not closed under marginalization, but lead to a mixture of conditional gaussians. In this model we stay
             inside the class of CG Models by using the best CG Model (in terms of the Kulbeck-Leibler divergence)
             as an approximation to the true marginal model. This is called weak marginals (WM) and gave the name
             to this class.
    """

    def __init__(self, name):
        super().__init__(name)

        self._aggrMethods = {
            'maximum': self._maximum,
            'average': self._maximum
        }
        self._categoricals = []
        self._numericals = []
        self._p = xr.DataArray([])
        self._mu = xr.DataArray([])
        self._S = xr.DataArray([])
        self._SInv = xr.DataArray([])
        self._detS = xr.DataArray([])

    # base
    def _set_data(self, df):
        return self._set_data_mixed(df)

    def _fit(self):
        """ Internal: estimates the set of mean parameters that fit best to the data given in the
        dataframe df.
        """
        assert(self.mode != 'none')
        df = self.data
        dc = len(self._categoricals)
        self._p, mu, S_single = cg.ConditionallyGaussianModel._fitFullLikelihood(df, self.fields, dc)

        # replicate S_single to a individual S for each cg
        # setup coords as dict of dim names to extents
        #dims = mu.dims[:-1]
        #coords = {key: mu.coords[key] for key in dims}
        dims = self._p.dims
        coords = dict(self._p.coords)
        coords['S1'] = self._numericals  # extent is the list of numerical variables
        coords['S2'] = self._numericals
        sizes = [len(coords[dim]) for dim in dims]  # generate blow-up sizes

        S = np.outer(np.ones(tuple(sizes)), S_single.values)  # replicate S as many times as needed
        dims += ('S1', 'S2')  # add missing dimensions for Sigma
        shape = tuple(sizes + [len(self._numericals)]*2)  # update shape
        S = S.reshape(shape)  # reshape to match dimension requirements

        self._S = xr.DataArray(data=S, coords=coords, dims=dims)
        self._mu = mu

        return self.update()  # needed to compute precalculated values

    def update(self):
        """Updates dependent parameters / precalculated values of the model after some internal changes."""
        self._update()

        if len(self._numericals) == 0:
            self._detS = xr.DataArray([])
            self._SInv = xr.DataArray([])
            self._S = xr.DataArray([])
            self._mu = xr.DataArray([])
        else:
            S = self._S

            invS = inv(S.values)
            self._SInv = xr.DataArray(data=invS, coords=S.coords, dims=S.dims)  # reuse coords from Sigma

            detS = abs(det(S.values)) ** -0.5
            if len(self._categoricals) == 0:
                self._detS = xr.DataArray(data=detS)  # no coordinates left to use...
            else:
                self._detS = xr.DataArray(data=detS, coords=self._p.coords, dims=self._p.dims)   # reuse coords from p

        if len(self._categoricals) == 0:
            self._p = xr.DataArray([])

        return self

    def _conditionout(self, remove):
        remove = set(remove)

        # condition on categorical fields
        cat_remove = [name for name in self._categoricals if name in remove]
        if len(cat_remove) != 0:
            pairs = dict(self._condition_values(cat_remove, True))

            # _p changes like in the categoricals.py case
            # trim the probability look-up table to the appropriate subrange and normalize it
            p = self._p.loc[pairs]
            self._p = p / p.sum()

            # _mu is trimmed: keep the slice that we condition on, i.e. reuse the 'pairs' access-structure
            # note: if we condition on all categoricals this also works: it simply remains the single 'selected' mu...
            if len(self._numericals) != 0:
                self._mu = self._mu.loc[pairs]
                self._S = self._S.loc[pairs]

        # condition on continuous fields
        num_remove = [name for name in self._numericals if name in remove]
        if len(num_remove) == len(self._numericals):
            # all gaussians are removed
            self._S = xr.DataArray([])
            self._mu = xr.DataArray([])
        elif len(num_remove) != 0:
            # collect singular values to condition out
            condvalues = self._condition_values(num_remove)

            # calculate updated mu and sigma for conditional distribution, according to GM script
            j = num_remove  # remove
            i = [name for name in self._numericals if name not in num_remove]  # keep

            cat_keep = self._mu.dims[:-1]
            if len(cat_keep) != 0:
                # iterate the mu and sigma of each cg and update them
                #  for that create stacked _views_ on mu and sigma! it stacks up all categorical dimensions and thus
                #  allows us to iterate on them
                # TODO: can I use the same access structure or do i need seperate ones for mu and S?
                mu_stacked = self._mu.stack(pl_stack=cat_keep)
                S_stacked = self._S.stack(pl_stack=cat_keep)
                for mu_coord, S_coord in zip(mu_stacked.pl_stack, S_stacked.pl_stack):
                    mu_indexer = dict(pl_stack=mu_coord)
                    S_indexer = dict(pl_stack=S_coord)

                    mu = mu_stacked.loc[mu_indexer]
                    S = S_stacked.loc[S_indexer]

                    # extent indexer to subselect only the part of mu and S that is updated. the rest is removed later.
                    #  problem is: we cannot assign a shorter vector to stacked.loc[indexer]
                    mu_indexer['mean'] = i
                    S_indexer['S1'] = i
                    S_indexer['S2'] = i

                    # update Sigma and mu
                    sigma_expr = np.dot(S.loc[i, j], inv(S.loc[j, j]))   # reused below multiple times
                    S_stacked.loc[S_indexer] = S.loc[i, i] - dot(sigma_expr, S.loc[j, i])  # upper Schur complement
                    mu_stacked.loc[mu_indexer] = mu.loc[i] + dot(sigma_expr, condvalues - mu.loc[j])

                # above we partially updated only the relevant part of mu and Sigma. the remaining part is now removed:
                self._mu = self._mu.loc[dict(mean=i)]
                self._S = self._S.loc[dict(S1=i,S2=i)]
            else:
                # special case: no categorical fields left. hence we cannot stack over them, it is only a single mu left
                # and we only need to update that
                sigma_expr = np.dot(self._S.loc[i, j], inv(self._S.loc[j, j]))  # reused below
                self._S = self._S.loc[i, i] - dot(sigma_expr, self._S.loc[j, i])  # upper Schur complement
                self._mu = self._mu.loc[i] + dot(sigma_expr, condvalues - self._mu.loc[j])

        # remove fields as needed
        self.fields = [field for field in self.fields if field['name'] not in remove]
        self._categoricals = [name for name in self._categoricals if name not in remove]
        self._numericals = [name for name in self._numericals if name not in remove]

        return self.update()

    def _marginalizeout(self, keep):
        # use weak marginals to get the best approximation of the marginal distribution that is still a cg-distribution
        keep = set(keep)
        num_keep = [name for name in self._numericals if name in keep]  # note: this is guaranteed to be sorted
        cat_remove = [name for name in self._categoricals if name not in keep]

        if len(self._categoricals) != 0:  # only enter if there is work to do
            # clone old p for later reuse
            if len(cat_remove) > 0:
                # marginalized p: just like in the categorical case (categoricals.py), i.e. sum over removed dimensions
                p = self._p.copy()
                self._p = self._p.sum(cat_remove)
            else:
                # no need to copy it
                p = self._p

        # marginalized mu and Sigma (taken from the script)
        if len(num_keep) != 0:
            # slice out the gaussian part to keep
            mu = self._mu.loc[dict(mean=num_keep)]
            S = self._S.loc[dict(S1=num_keep, S2=num_keep)]
            if len(cat_remove) == 0:
                # just set the sliced out gaussian parts
                self._mu = mu
                self._S = S
            else:
                # marginalized mu
                # sum over the categorical part to remove
                self._mu = (p * mu).sum(cat_remove) / self._p

                # marginalized Sigma - see script
                # only in that case the following operations yield something different from S
                mu_diff = mu - self._mu

                # outer product of each mu_diff.
                #  do it in numpy with einsum: 1st reshape to [x, len(mu)], 2nd use einsum
                #  credits to: http://stackoverflow.com/questions/20683725/numpy-multiple-outer-products
                shape = mu_diff.shape
                shape = (np.prod(shape[:-1]), shape[-1:][0])
                mu_diff_np = mu_diff.values.reshape(shape)
                mu_dyad = np.einsum('ij,ik->ijk' ,mu_diff_np, mu_diff_np)
                mu_dyad = mu_dyad.reshape(S.shape)  # match to shape of S

                inner_sum = mu_dyad + S

                times_p = inner_sum * p
                marginalized_sum = times_p.sum(cat_remove)
                normalized = marginalized_sum / self._p
                self._S = normalized

        # update fields and dependent variables
        self.fields = [field for field in self.fields if field['name'] in keep]
        self._categoricals = [name for name in self._categoricals if name in keep]
        self._numericals = num_keep

        return self.update()

    def _density(self, x):
        cat_len = len(self._categoricals)
        num_len = len(self._numericals)
        cat = tuple(x[:cat_len])  # need it as a tuple for indexing below
        num = np.array(x[cat_len:])  # need as np array for dot product

        p = self._p.loc[cat].values

        if num_len == 0:
            return p

        # works because gaussian variables are - by design of this class - after categoricals.
        # Therefore the only not specified dimension is the last one, i.e. the one that holds the mean!
        mu = self._mu.loc[cat].values
        S = self._S.loc[cat].values
        detS = self._detS.loc[cat].values
        invS = self._SInv.loc[cat].values
        xmu = num - mu
        #gauss = (2 * pi) ** (-num_len / 2) * (abs(det(S)) ** -.5) * exp(-.5 * np.dot(xmu, np.dot(inv(S), xmu)))
        gauss = (2 * pi) ** (-num_len / 2) * detS * exp(-.5 * np.dot(xmu, np.dot(invS, xmu)))

        if cat_len == 0:
            return gauss
        else:
            return p * gauss

    def _maximum(self):
        """Returns the point of the maximum density in this model"""
        cat_len = len(self._categoricals)
        num_len = len(self._numericals)

        if cat_len == 0:
            # then there is only a single gaussian left and the maximum is its mean value, i.e. the value of _mu
            return list(self._mu.values)

        # observation 1: for a given x in Omega_X the maximum is taken at the corresponding cg's mu, lets call it
        #  argmu(x). hence, in order to determine the maximum, we scan over all x of Omega_x and
        #  calculate the density over p(x, argmu(x))
        # observation 2: the density of a gaussian at its mean is quite simple since the (x-mu) terms evaluate to 0.
        # observation 3: we are only interested in where the maximum is taken, no its actual value. Hence we can remove
        #  any values that are equal for all. Hence, the following simplies:
        #     (2*pi)^(-n/2) * det(Sigma)^-0.5 * exp( -0.5 * (x-mu)^T * Sigma^-1 * (x-mu) )
        # to: det(Sigma)^-0.5
        # observation 4: luckily, we already have that precalculated!

        if num_len == 0:
            # find maximum in p and return its coordinates
            p = self._p
            pmax = p.where(p == p.max(), drop=True)  # get view on maximum (coordinates remain)
            return [idx[0] for idx in pmax.indexes.values()]  # extract coordinates from indexes

        else:
            # find compound maximum

            # compute pseudo-density at all gaussian means to find maximum
            p = self._p * self._detS
            pmax = p.where(p == p.max(), drop=True)  # get view on maximum (coordinates remain)

            # now figure out the coordinates
            cat_argmax = [idx[0] for idx in pmax.indexes.values()]  # extract categorical coordinates from indexes
            num_argmax = self._mu.loc[tuple(cat_argmax)]  # extract numerical coordinates as mean

            # return compound coordinates
            return cat_argmax + list(num_argmax.values)

    def copy(self, name=None):
        mycopy = self._defaultcopy(name)
        mycopy._mu = self._mu.copy()
        mycopy._S = self._S.copy()
        mycopy._p = self._p.copy()
        mycopy._categoricals = self._categoricals.copy()
        mycopy._numericals = self._numericals.copy()
        mycopy.update()
        return mycopy

if __name__ == '__main__':
    import numpy as np
    import pandas as pd
    from cond_gaussian_wm import CgWmModel
    from cond_gaussian.datasampling import genCGSample, genCatData, genCatDataJEx, cg_dummy

    # generate input data
    data = cg_dummy()

    # fit model
    model = CgWmModel('testmodel')
    model.fit(data)
    original = model.copy()

    # marginalize a single continuous variable out: income
    model = original.copy().model(model=['sex', 'city', 'age'])
    print("model of sex, city, age:\n", model)

    # marginalize two continuous variables out: income, age
    model = original.copy().model(model=['sex', 'city'])
    print("model of sex, city:\n", model)

    # marginalize a single categorical variable out: sex
    model = original.copy().model(model=['city', 'age', 'income'])
    print("model of city, age, income:\n", model)

    # marginalize two categorical variables out: sex, city
    model = original.copy().model(model=['age', 'income'])
    print("model of age, income:\n", model)

    # marginalize a continuous and a categorical variable out: sex, income
    model = original.copy().model(model=['city', 'age'])
    print("model of city, age:\n", model)

    # marginalize two continuous and a single categorical variable out: sex, income, age
    model = original.copy().model(model=['city'])
    print("model of city:\n", model)

    # marginalize a single continuous and a two categorical variables out: sex, city, age
    model = original.copy().model(model=['income'])
    print("model of income:\n", model)

    ## older stuff
    model = original.copy()
    print('p(M) = ', model._density(['M', 'Jena', 0, -6]))

    print('argmax of p(sex, city, age, income) = ', model._maximum())

    print('p(M) = ', model._density(['M', 'Jena', 0]))

    print('argmax of p(sex, city, age) = ', model._maximum())

    model.model(model=['sex', 'age'], where=[('city', "==", 'Jena')])  # condition city out
    print("model [sex, city == Jena, age]:\n", model)

    print('p(M) = ', model._density(['M', 0]))

    print('argmax of p(sex, agge) = ', model._maximum())

    model.model(model=['sex'], where=[('age', "==", 0)])  # condition age out
    print("model [sex, city == Jena, age == 0]:\n", model)

    print('p(M) = ', model._density(['M']))

    print('p(F) = ', model._density(['F']))

    print('argmax of p(sex) = ', model._maximum())

    model = original.copy().model(['sex', 'age', 'income'])  # marginalize city out
    print("model [sex, age, income]:\n", model)

    pass
