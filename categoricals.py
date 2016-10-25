import copy as cp
import numpy as np
from numpy import nan
import xarray as xr
import logging

import utils
import models as md
import domains as dm

# setup logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.WARNING)

class CategoricalModel(md.Model):
    """A multivariate categorical model"""
    def __init__(self, name):
        super().__init__(name)
        self._p = nan
        self._aggrMethods = {
            'maximum': self._maximum
        }

    @staticmethod
    def _get_header(df):
        fields = []
        for column_name in df:
            column = df[column_name]
            domain = dm.DiscreteDomain()
            extent = dm.DiscreteDomain(sorted(column.unique()))
            fields.append(md.Field(column_name, domain, extent, 'string'))
        return fields

    @staticmethod
    def _maximum_aposteriori(df, fields, k=1):
        extents = [f['extent'].value() for f in fields]
        sizes = tuple(len(e) for e in extents)
        z = np.zeros(shape=sizes)

        # initialize count array
        counts = xr.DataArray(data=z, coords=extents, dims=df.columns)

        # iterate over table and sum up occurrences
        for row in df.itertuples():
            values = row[1:]  # 1st element is index, which we don't need
            counts.loc[values] += 1

        # smooth, normalize and return
        return (counts + k) / (counts.sum() + k * counts.size)

    def fit(self, df):
        """Fits the model to passed DataFrame

        Returns:
            The modified model.
        """
        self.data = df
        self.fields = CategoricalModel._get_header(self.data)
        self._p = CategoricalModel._maximum_aposteriori(df, self.fields)
        return self.update()

    def __str__(self):
        return ("Multivariate Categorical Model '" + self.name + "':\n" +
                "dimension: " + str(self._n) + "\n" +
                "names: " + str([self.names]) + "\n" +
                "fields: " + str([str(field) for field in self.fields]))

    def update(self):
        """updates dependent parameters / precalculated values of the model"""
        self._update()
        if self._n == 0:
            self._p = xr.DataArray([])
        return self

    def _conditionout(self, remove):
        """ Conditioning out categorical variables works by means of the definition of conditional probability:
          p(x|c) = p(x,c) / p(c)
        where p(x,c) is the join probability. Hence it works by normalizing a subrange of the probability look-up
        table"""
        if len(remove) == 0 or self._isempty():
            return self
        if len(remove) == self._n:
            return self._setempty()

        # collect singular values to condition out on
        removeidx = sorted(self.asindex(remove))
        # todo: not  needed anymore: remove = [self.names[idx] for idx in j]  # reorder to match index order
        pairs = []
        for idx in removeidx:
            field = self.fields[idx]
            domain = field['domain']
            dvalue = domain.value()
            assert (not domain.isunbounded())
            # TODO: we don't know yet how to condition on a not singular, but not unrestricted domain.
            if field['dtype'] == 'string':
                pairs.append((field['name'], dvalue[0]))
                # actually it is: domain[0] if singular else domain[0]
            else:
                raise ValueError('invalid dtype of field: ' + str(field['dtype']))

        # 1. trim the probability look-up table to the appropriate subrange
        # build look-up array for it
        p = self._p.loc[dict(pairs)]

        # 2. normalize
        self._p = p / p.sum()

        # 3. keep all fields not in remove
        keepidx = utils.invert_indexes(removeidx, self._n)
        self.fields = [self.fields[idx] for idx in keepidx]

        return self.update()

    def _marginalizeout(self, keep):
        if len(keep) == self._n or self._isempty():
            return self
        if len(keep) == 0:
            return self._setempty()

        keepidx = sorted(self.asindex(keep))
        removeidx = utils.invert_indexes(keepidx, self._n)
        # the marginal probability is the sum along the variable(s) to marginalize out
        self._p = self._p.sum(axis=removeidx)
        self.fields = [self.fields[idx] for idx in keepidx]
        return self.update()

    def _density(self, x):
        """Returns the density of the model at point x.

        Args:
            x: a scalar or a list of scalars.
        """
        if len(x) != self._n:
            raise ValueError("length of argument does not match the model's dimension")
        return self._p.loc[tuple(x)]  # need to convert to tuple for indexing!

    def _maximum(self):
        """Returns the point of the maximum density in this model"""
        # todo: how to get the coordinates of the maximum?
        p = self._p
        pmax = p.where(p == p.max(), drop=True) # get view on maximum (coordinates remain)
        return [idx[0] for idx in pmax.indexes.values()]  # extract coordinates from indexes

    def _sample(self):
        # TODO: let it return a dataframe?
        raise "not implemented"

    def copy(self, name=None):
        # TODO: this should be as lightweight as possible!
        name = self.name if name is None else name
        mycopy = CategoricalModel(name)
        mycopy.data = self.data # todo: reference, not copy
        mycopy.fields = cp.deepcopy(self.fields)
        mycopy._p = self._p
        mycopy.update()
        return mycopy

if __name__ == '__main__':
    import pdb
    import pandas as pd
    df = pd.read_csv('data/categorical_dummy.csv')
    model = CategoricalModel('model1')
    model.fit(df)

    print('model:', model)
    print('model._p:', model._p)

    print('model density 1:', model._density(['a', 'z']))
    print('model density 1:', model._density(['a', 'zz']))

    print('model maximum:', model._maximum())

