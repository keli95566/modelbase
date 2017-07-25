# Copyright (c) 2017 Philipp Lucas (philipp.lucas@uni-jena.de)
import functools
import logging
import numpy as np
from numpy import nan, pi, exp, dot, abs
from numpy.linalg import inv, det
import xarray as xr

import models as md
import cond_gaussian_wm as cgwm

import data.crabs.crabs as crabs

# setup logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.WARNING)


def _argmax(p):
    return p.where(p == p.max(), drop=True)


def _masked(vec, mask):
    """Returns a vector of those entries vec[i] where mask[i] is True. Order of elements is invariant."""
    return [vec[i] for i in range(len(vec)) if mask[i]]


def _not_masked(vec, mask):
    """Returns a vector of those entries vec[i] where mask[i] is False. Order of elements is invariant."""
    return [vec[i] for i in range(len(vec)) if not mask[i]]


def _maximum_mixable_cg_heuristic_a(cat_len, marg_len, num_len, marginalized_mask, mu, p, detS):
    """ Returns an approximation to the point of maximum density.

    Heuristic (a) "highest single gaussian": return the density at the mean of the individually most probably gaussian (
     including shadowed ones). "individually" means that only the density of each individual mean of a gaussian
     is of interest, not the the actual, summed density at its mean (summed over shadowed gaussians)

    * this should be the simplest to implement, but also the worst performing?
    * in fact, this is cond_gaussian_wm._maximum_cgwm_heuristic1, but with the shadowed coordinates cut off
    """

    # get coordinates of maximum over all cgs including shadowed ones
    coord = cgwm._maximum_cgwm_heuristic1(cat_len + marg_len, num_len, mu, p, detS)
    # all_cat_len = len(self._categoricals) + len(self._marginalized)
    # num_len = len(self._numericals)

    # cut out shadowed fields
    return _not_masked(coord, marginalized_mask)


class MixableCondGaussianModel(md.Model):
    """This is Conditional Gaussian (CG) model that supports true marginals and conditional.

     An advantage is, that this model stays more accurate when marginal and or conditional models are derived,
     compared to CG model with weak marginals (WM). See cond_gaussian_wm.py for more.

    A disadvantage is that is is much more computationally expensive to answer queries against this type of model.
    The reason is:
    (1) that marginals of mixable CG models are mixtures of CG models, and the query has to be answered for each
    component of the mixture.
    (2) the number of components grows exponentially with the number of discrete random variables (RV) marginalized.

    It seems like this should be relatively straight forward. See the notes on paper.
    In essence we never throw parameters when marginalizing discrete RV, but just mark them as 'marginalized'.

    The major questions appear to be:

      * how to efficiently store what the marginalized variables are? what about 'outer interfaces' that rely on internal storage order or something? not sure if that really is a problem
      * how to determine the maximum of such a mixture? this is anyway an interesting question...!
      * can I reuse code from cond_gaussian_wm.py? I sure can, but I would love to avoid code duplication...

    """

    def __init__(self, name):
        super().__init__(name)

        self._aggrMethods = {
            'maximum': self._maximum,
            'average': self._maximum
        }
        self._categoricals = []
        self._numericals = []
        self._marginalized = []  # list of marginalized, discrete fields, NOT in same order like occurring in parameters
        # boolean mask for all fields (incl marginalized ones), where True indicates a marginalized field
        self._marginalized_mask = []
        self._p = xr.DataArray([])
        self._mu = xr.DataArray([])
        self._S = xr.DataArray([])
        self._SInv = xr.DataArray([])
        self._detS = xr.DataArray([])
        # creates an self contained update function. we use it as a callback function later
        self._unbound_updater = functools.partial(self.__class__._update, self)

    def _set_data(self, df, drop_silently):
        self._set_data_mixed(df, drop_silently)
        self._marginalized_mask = [False]*len(self.fields)
        return ()

    def _fit(self):
        assert (self.mode != 'none')
        self._p, self._mu, self._S = cgwm.fitConditionalGaussian(self.data, self.fields, self._categoricals,
                                                                 self._numericals)
        return self._unbound_updater,

    def _assert_invariants(self):
        """Check for some invariants and raise AssertionError if violated, since this represents a severe bug."""
        marg_set = set(self._marginalized)
        cat_set =  set(self._categoricals)
        p_set = set(self._p.dims)
        s_set = set(self._S.dims)
        invs_set = set(self._SInv.dims)
        dets_set = set(self._detS.dims)
        mu_set = set(self._mu.dims)

        # (1) non of the shadowed fields may still be in _categorical, i.e. the intersection is empty
        assert(len(marg_set & cat_set) == 0)
        # (2) all of the shadowed fields must exist in _p.dims
        assert(p_set.issuperset(marg_set))
        # (3) the union of shadowed field names and remaining categorical field names must be identical to _p.dims
        assert(marg_set | cat_set == p_set)
        # (4) dimensions of _S, _invS must be identical
        assert(s_set == invs_set)
        # (5) dimensions of _S[:-2] and _mu[:-1] and _p and dets_set must be identical
        if len(self._numericals) > 0:
            mu_set.remove("mean")
            s_set.remove("S1")
            s_set.remove("S2")
            assert(p_set == s_set == mu_set == dets_set)
        # (6) matching "True"s
        assert sum(self._marginalized_mask) == len(marg_set)
        # (7) marginalized mask must have proper length
        assert len(self._marginalized_mask) >= len(p_set)

    def _update(self):   # mostly like CG WM, but different update for _detS
        """Updates dependent parameters / precalculated values of the model after some internal changes."""
        if len(self._numericals) == 0:
            self._S = xr.DataArray([])
            self._SInv = xr.DataArray([])
            self._detS = xr.DataArray([])
            self._mu = xr.DataArray([])
        else:
            S = self._S

            invS = inv(S.values)
            self._SInv = xr.DataArray(data=invS, coords=S.coords, dims=S.dims)  # reuse coords from Sigma

            detS = abs(det(S.values)) ** -0.5
            if len(self._categoricals) == 0 and len(self._marginalized) == 0:
                self._detS = xr.DataArray(data=detS)  # no coordinates left to use... none needed, its a scalar now!
            else:
                self._detS = xr.DataArray(data=detS, coords=self._p.coords, dims=self._p.dims)   # reuse coords from p

        if len(self._categoricals) == 0 and len(self._marginalized) == 0:
            self._p = xr.DataArray([])

        self._assert_invariants()

        return self

    def _marginalizeout(self, keep, remove):
        # we use exact marginals, which lead to a kind of mixtures of cg. Alternatively speaking: we simply keep the
        # full parameters but shadow the existence of the marginalized field to the outside.
        keep = set(keep)
        num_keep = [name for name in self._numericals if name in keep]  # note: this is guaranteed to be sorted
        cat_remove = [name for name in self._categoricals if name not in keep]

        # we never actually marginalize out categorical fields. we simply shadow them, but keep the parameters
        # internally

        # marginalized mu and Sigma (taken from the script)
        if len(num_keep) != 0:
            # marginalize numerical fields: slice out the gaussian part to keep
            self._mu = self._mu.loc[dict(mean=num_keep)]
            self._S = self._S.loc[dict(S1=num_keep, S2=num_keep)]

        # update fields and dependent variables
        self._categoricals = [name for name in self._categoricals if name in keep]
        self._numericals = num_keep

        # mark newly marginalized categorical fields as such
        self._marginalized += cat_remove
        cat_names = self._p.dims
        for name in cat_remove:
            # find index. we must find the index of that field in all the remaining categorical fields, shadowed or not
            idx = cat_names.index(name)
            assert (not self._marginalized_mask[idx])
            self._marginalized_mask[idx] = True

        return self._unbound_updater,

    def _conditionout(self, keep, remove):   # exactly like CG WM!!
        remove = set(remove)

        cat_dims = self._p.dims  # safe current categorical dims for later reuse

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
        self._categoricals = [name for name in self._categoricals if name not in remove]
        self._numericals = [name for name in self._numericals if name not in remove]

        # update marginalized mask
        # TODO: use some acceleration data structure?
        # (i) get indexes of the conditioned-out categorical fields in self._marginalized_mask
        # (we now reuse the saved cat_dims from the beginning of the function)
        cat_remove_idxs = set(cat_dims.index(name) for name in cat_remove)
        # (ii) throw mask entries
        self._marginalized_mask = [v for idx, v in enumerate(self._marginalized_mask) if idx not in cat_remove_idxs]
        assert sum(self._marginalized_mask) == len(self._marginalized)
        assert len(self._marginalized_mask) >= len(self._p.dims)

        return self._unbound_updater,

    def _density(self, x):
        """Returns the density of the model at x.

        Internal:

        * all shadowed fields are categorical
        * categorical fields are needed to retrieve the correct mu and sigma to then query the density for that gaussian
        * instead of one gaussian, we have to compute the density at x for all implicit gaussians (by shadowed categorical
         fields) and multiply it with the respective probability of occurrence (self._p)
        * then, these weighted densities have to be summed

        * question is: how can I do this in parallel, without explicitly iterating through all value combinations of
          the shadowed fields?

        * alternative iterative procedure:
           - create data frame of cross join of marginalized field values
           - init sum to 0
           - iterate over that frame:
              - extract the corresponding gaussian
              - compute density for gaussian
              - add to sum
           - return that sum
           * this is a bad idea, because we cross join is already there - I simply need to iterate over it -> see alternative 2

        * alternative 2:
           - filter mu and sigma by the given categorical values in x,
           - that results in all the gaussians that we need to evaluate on the numerical part of x
           - stack over filtered mu and sigma (like in _conditionout of cg wm), to iterate over it
           - then sum densities up
        """
        cat_len = len(self._categoricals)
        num_len = len(self._numericals)
        num = np.array(x[cat_len:])  # need as np array for dot product
        cat = tuple(x[:cat_len])   # need it as a tuple for indexing

        if num_len == 0:
            if len(self._marginalized) == 0:
                p = self._p
            else:
                p = self._p.sum(self._marginalized)   # sum over marginalized/shadowed fields
            return p.loc[cat].values
        # we get here only if there is any continuous fields left

        if len(self._marginalized) == 0:
            # no shadowed/marginalized fields. hence we cannot stack over them and the density query works as "normal"
            # the following is copy-and-pasted from cond_gaussian_wm.py -> _density
            mu = self._mu.loc[cat].values
            detS = self._detS.loc[cat].values
            invS = self._SInv.loc[cat].values
            xmu = num - mu
            gauss = (2 * pi) ** (-num_len / 2) * detS * exp(-.5 * np.dot(xmu, np.dot(invS, xmu)))

            if cat_len == 0:
                return gauss
            else:
                p = self._p.loc[cat].values
                return p * gauss
        else:
            # dictionary of "categorical-field-name : value" for all given categorical values

            # note: even if cat_len == 0, i.e. the following selections have 'empty cat_dict', it works
            cat_dict = dict(zip(self._categoricals, cat))

            # filter mu and sigma by the given categorical values in x, i.e. a view on these xarrays
            mu_shadowed = self._mu.loc[cat_dict]
            invS_shadowed = self._SInv.loc[cat_dict]
            detS_shadowed = self._detS.loc[cat_dict]
            p_shadowed = self._p.loc[cat_dict]

            ## alternative 2 (see above)
            # stack over shadowed dimensions
            mu_stacked = mu_shadowed.stack(pl_stack=self._marginalized)
            invS_stacked = invS_shadowed.stack(pl_stack=self._marginalized)
            detS_stacked = detS_shadowed.stack(pl_stack=self._marginalized)
            p_stacked = p_shadowed.stack(pl_stack=self._marginalized)
            gauss_sum = 0
            for mu_coord, invS_coord, detS_coord, p_coord in zip(mu_stacked.pl_stack, invS_stacked.pl_stack, detS_stacked.pl_stack, p_stacked.pl_stack):
                mu_indexer = dict(pl_stack=mu_coord)
                invS_indexer = dict(pl_stack=invS_coord)
                detS_indexer = dict(pl_stack=detS_coord)
                p_indexer = dict(pl_stack=p_coord)

                mu = mu_stacked.loc[mu_indexer].values
                invS = invS_stacked.loc[invS_indexer].values
                detS = detS_stacked.loc[detS_indexer].values
                p = p_stacked.loc[p_indexer].values

                try:
                    xmu = num - mu
                except TypeError:
                    print("here")
                    raise

                gauss = (2 * pi) ** (-num_len / 2) * detS * exp(-.5 * np.dot(xmu, np.dot(invS, xmu)))

                gauss_sum += p * gauss

            return gauss_sum

            ## vectorized version (instead of alternative 2 code)
            # I simply don't know the syntax for what i want...
            # maybe it is not possible?
            # np.dot(xmu, np.dot(invS, xmu))
            #.sum()*(2 * pi) ** (-num_len / 2)


#    def _sample(self):
#        pass

    def _maximum_mixable_cg_heuristic_b(self):
        """ Returns an approximation to the point of maximum density.

        Heuristic (c) "highest accumulated gaussian":
         1. calculate cumulated density at each gaussian (including shadowed ones)
         2. take the maximum of these, but cut off shadowed coordinates
        This is probably the best performing one the maximum heuristics for this model type.
        """

        # stack over all means (including the shadowed ones) in self_mu and keep coordinates of maximum cumulated density
        stack_over = self._marginalized + self._categoricals
        len_so = len(stack_over)
        mu_stacked = self._mu.stack(pl_stack=stack_over)
        p_max = 0
        coord_max = None
        for mu_coord in mu_stacked.pl_stack:
            # assemble coordinates for density query
            mu_coord = mu_coord.item()
            mu_indexer = dict(pl_stack=mu_coord)
            num_coord = mu_stacked.loc[mu_indexer].values.tolist()
            mu_coord = (mu_coord,) if len_so == 1 else mu_coord  # make sure it's a tuple (needed for _not_masked())
            cat_coord = _not_masked(mu_coord, self._marginalized_mask)  # remove coordinates of marginalized fields
            coord = cat_coord + num_coord

            # query density and compare to so-far maximum
            # TODO: can I use pseudo-density like in cond_gaussian_wm._maximum_cgwm_heuristic1?
            p = self._density(coord)
            if p > p_max:
                p_max = p
                coord_max = coord

        return coord_max

    def _maximum_mixable_cg_heuristics_c(self):
        """ heuristic (c) "highest non-shadowed gaussian"
           1. calc the probability of the mean of each unshadowed gaussian, and select the most likeliest
           2. then "split" again by the shadowed fields and of these gaussian means, select the most probable
           * this is a simplification of (b), but should be a bit faster
        """

        # stage 1: stack over unshadowed gaussian and find mean of gaussian with maximum density
        # uh...? this aint a single gaussian ...
        mu_stacked = self._mu.stack(pl_stack=self._categoricals)
        p_max = 0
        coord_max = None
        for mu_coord in mu_stacked.pl_stack:
            # assemble coordinates for density query
            mu_indexer = dict(pl_stack=mu_coord)
            num_coord = mu_stacked.loc[mu_indexer].values
            cat_coord = _not_masked(mu_coord, self._marginalized_mask)  # remove coordinates of marginalized fields
            coord = cat_coord + num_coord

            # query density
            p = self._density(coord)
            if p > p_max:
                p_max = p
                coord_max = coord

        # stage 2: split on the shadowed fields for the found maximum only
        # TODO: not done/buggy
        raise NotImplemented

    def _maximum(self):

        cat_len = len(self._categoricals)
        num_len = len(self._numericals)
        mrg_len = len(self._marginalized)

        if cat_len == 0 and mrg_len == 0:
            # then there is only a single gaussian left and the maximum is its mean value, i.e. the value of _mu
            return list(self._mu.values)

        if num_len == 0:
            # find maximum in p and return its coordinates
            p = self._p.sum(self._marginalized)  # sum over marginalized fields
            pmax = p.where(p == p.max(), drop=True)  # get view on maximum (coordinates remain)
            return [idx[0] for idx in pmax.indexes.values()]  # extract coordinates from indexes

        else:
            # this is difficult case, and we don't have a perfect solution yet, just a couple of heuristics...
            # return _maximum_mixable_cg_heuristic_a(
            #     cat_len, mrg_len, num_len, self._marginalized_mask, self._mu, self._p, self._detS)
            return self._maximum_mixable_cg_heuristic_b()

    # mostly like cg wm
    def copy(self, name=None):
        mycopy = self._defaultcopy(name)
        mycopy._mu = self._mu.copy()
        mycopy._S = self._S.copy()
        mycopy._p = self._p.copy()
        mycopy._categoricals = self._categoricals.copy()
        mycopy._numericals = self._numericals.copy()
        mycopy._marginalized = self._marginalized.copy()
        mycopy._marginalized_mask = self._marginalized_mask.copy()
        mycopy._update()
        return mycopy


if __name__ == '__main__':

    # load data
    data = crabs.mixed('data/crabs/australian-crabs.csv')

    # fit model
    m = MixableCondGaussianModel(name="foo_model")
    m.fit(df=data)

    orig = m.copy()

    m = m.model(model=["RW"])
    aggr = m.aggregate("maximum")

    print(aggr)