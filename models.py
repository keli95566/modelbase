"""
@author: Philipp Lucas

This module defines:

   * Model: an abstract base class for models.
   * Field: a class that represent random variables in a model.

It also defines models that implement that base model:

   * MultiVariateGaussianModel
"""
import pandas as pd
import numpy as np
from numpy import pi, exp, matrix, ix_, nan
import copy as cp
from collections import namedtuple
from functools import reduce
from sklearn import mixture
import logging
import splitter as sp
import utils as utils

# TODO: I don't know how to calculate aggregations beyond maximum, average and density of unrestricted multivariate gaussians
# e.g. what if we restrict the domain to >1? what is the average of such a distribution? how do we marginalize out such restricted fields?

# for fuzzy comparision.
# TODO: make it nicer?
eps = 0.000001

# setup logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.WARNING)

""" Development Notes (Philipp)

## how to get from data to model ##

1. provide some data file
2. open that data file
3. read that file into a tabular structure and guess its header, i.e. its
    columns and its data types
    * pandas dataframes can aparently guess headers/data types
4. use it to train a model
5. return the model

https://github.com/rasbt/pattern_classification/blob/master/resources/python_data_libraries.md !!!

### what about using a different syntax for the model, like the following:

    model['A'] : to select a submodel only on random variable with name 'A' // marginalize
    model['B'] = ...some domain...   // condition
    model.
"""

### GENERIC / ABSTRACT MODELS and other base classes
AggregationTuple = namedtuple('AggregationTuple', ['name', 'method', 'yields', 'args'])
SplitTuple = namedtuple('SplitTuple', ['name', 'method', 'args'])
ConditionTuple = namedtuple('ConditionTuple', ['name', 'operator', 'value'])
""" A condition tuple describes the details of how a field of model is
    conditioned.

    Attributes:
        name: the name of field to condition
        operator: may take be one of ['in', 'equals', '==', 'greater', 'less']
        value: its allowed values depend on the value of operator
            operator == 'in': A sequence of elements if the field is discrete. A two-element list [min, max] if the
                field is continuous.
            operator == 'equals' or operator == 'is': a single element of the domain of the field
            operator == 'greater': a single element that is set to be the new upper bound of the domain.
            operator == 'less': a single element that is set to be the new lower bound of the domain.
"""

def Field(name, domain, dtype='numerical'):
    return {'name': name, 'domain': domain, 'dtype': dtype}
""" A constructor that returns 'Field'-dicts, i.e. a dict with three components
    as passed in:

    'name': the name of the field
TODO: fix/confirm notation
    'domain': the domain of the field, represented as a list as follows:
        if dtype == 'numerical': A 2 element list of [min, max], or a singular value (i.e. not a list but a scalar)
        if dtype == 'string': A list of the possible values.
    'dtype': the data type that the field represents. Possible values are: 'numerical' and 'string'
"""


def _tuple2str(tuple_):
    """Returns a string that summarizes the given splittuple or aggregation tuple"""
    prefix = (str(tuple_.yields) + '@') if hasattr(tuple_, 'yields') else ""
    return  prefix + str(tuple_[1]) + '(' + str(tuple_[0]) + ')'

def _isSingularDomain(domain):
    """Returns True iff the given domain is singular, i.e. if it _is_ a single value."""
    return isinstance(domain, str) or not isinstance(domain, (list, tuple))#\
           #or len(domain) == 1\
           #or domain[0] == domain[1]

class Model:
    """An abstract base model that provides an interface to derive submodels
    from it or query density and other aggregations of it.
    """

    @staticmethod
    def _get_header(df):
        """ Returns suitable fields for a model from a given pandas dataframe.
        """
        #TODO: at the moment this only works for continuous data.
        fields = []
        for column in df:
            field = {'name': column, 'domain': [df[column].min(), df[column].max()], 'dtype': 'numerical'}
            fields.append(field)
        return fields

    def asindex(self, names):
        """Given a single name or a list of names of random variables, returns
        the indexes of these in the .field attribute of the model.
        """
        if isinstance(names, str):
            return self._name2idx[names]
        else:
            return [self._name2idx[name] for name in names]

    def byname(self, names):
        """Given a list of names of random variables, returns the corresponding
        fields of this model.
        """
        if isinstance(names, str):
            return self.fields[self._name2idx[names]]
        else:
            return [self.fields[self._name2idx[name]] for name in names]

    def isfieldname(self, names):
        """Returns true iff the name or names of variables given are names of
        random variables of this model.
        """
        if isinstance(names, str):
            names = [names]
        return all([name in self._name2idx for name in names])

    def __init__(self, name):
        self.name = name
        self.fields = []
        self.names = []
        self.data = []
        self._aggrMethods = None
        self._n = 0
        self._name2idx = {}

    def fit(self, data):
        """Fits the model to the dataframe assigned to this model in at
        construction time.

        Returns:
            The modified model.
        """
        self.data = data
        self.fields = Model._get_header(self.data)
        self._fit()
        return self

    def _fit(self):
        raise NotImplementedError()

    def marginalize(self, keep=None, remove=None):
        """Marginalizes random variables out of the model. Either specify which
        random variables to keep or specify which to remove.

        Note that marginalization is depending on the domain of a random
        variable. That is: if nothing but a single value is left in the
        domain it is conditioned on this value (and marginalized out).
        Otherwise it is 'normally' marginalized out (assuming that the full
        domain is available)

        Returns:
            The modified model.
        """
        logger.debug('marginalizing: '
                     + ('keep = ' + str(keep) if remove is None else ', remove = ' + str(remove)))

        if keep is not None:            
            if keep == '*':
                keep = self.names
            if not self.isfieldname(keep):
                raise ValueError("invalid random variable names: " + str(keep))
        elif remove is not None:
            if not self.isfieldname(remove):
                raise ValueError("invalid random variable names")
            keep = set(self.names) - set(remove)
        else:
            raise ValueError("not both arguments keep and remove can be None")

        return self._marginalize(keep)

    def _marginalize(self, keep):
        raise NotImplementedError()

    def condition(self, conditions):
        """Conditions this model according to the list of three-tuples
        (<name-of-random-variable>, <operator>, <value(s)>). In particular
        ConditionTuples are accepted and see there for allowed values.

        Note: This only restricts the domains of the random variables. To
        remove the conditioned random variable you need to call marginalize
        with the appropriate paramters.

        Returns:
            The modified model.
        """
        simplified_conditions = []

        for (name, operator, values) in conditions:
            operator = operator.lower()
            # TODO: check validity of conditions
            if operator == 'equals' or operator == '==':
                #newdomain = [values]
                newdomain = values
            elif operator == 'in':
                # this is either the range [min, max] or the sequence of distinct values [val1, val2, ...]
                newdomain = values
            elif operator == 'greater' or operator == '>':
                lower, upper = self.byname(name)['domain']
                newdomain = [lower if lower > values else values, upper]
            elif operator == 'less' or operator == '<':
                lower, upper = self.byname(name)['domain']
                newdomain = [lower, upper if upper < values else values]
            else:
                raise ValueError('invalid operator for condition: ' + str(operator))
            simplified_conditions.append((name, newdomain))

        self._condition(simplified_conditions)
        return self

    def _condition(self, pairs):
        """ Conditions a model according to the passed list of pairs of
        (<field-name>, <new-domain>).
        For valid domains see the docstring of Field above.
        """
        raise NotImplementedError()

    def aggregate(self, method):
        """Aggregates this model using the given method and returns the
        aggregation as a list. The order of elements in the list, matches the
        order of random variables in the models field.

        Returns:
            The aggregation of the model. Note this always retrusn a list, even if aggregation is 1 dimensional.
        """
        if method in self._aggrMethods:
            return self._aggrMethods[method]()
        else:
            raise ValueError("Your Model does not provide the requested aggregation: '" + method + "'")

    def density(self, names, values=None):
        """Returns the density at given point. You may either pass both, names
        and values, or only one list with values. In the latter case values is
        assumed to be in the same order as the fields of the model.

        Args:
            values may be anything that numpy.matrix accepts to construct a vector from.
        """
        if len(names) != self._n:
            raise ValueError(
                'Not enough names/values provided. Require ' + str(self._n) + ' got ' + str(len(names)) + '.')

        if values is None:
            # in that case the only argument holds the (correctly sorted) values
            values = names
        else:
            sorted_ = sorted(zip(self.asindex(names), values), key=lambda pair: pair[0])
            values = [pair[1] for pair in sorted_]
        return self._density(matrix(values).T)

    def sample(self, n=1):
        """Returns n samples drawn from the model."""
        samples = (self._sample() for i in range(n))
        return pd.DataFrame.from_records(samples, self.names)

    def _sample(self):
        raise NotImplementedError()

    def copy(self):
        raise NotImplementedError()

    def _update(self):
        """Updates the name2idx dictionary based on the fields in .fields"""
        # TODO: call it from aggregate, ... make it transparent to subclasses!? is that possible?
        self._n = len(self.fields)
        self._name2idx = dict(zip([f['name'] for f in self.fields], range(self._n)))
        self.names = [f['name'] for f in self.fields]

    def model(self, model, where=[], as_=None):
        """Returns a model with name 'as_' that models the fields in 'model'
        respecting conditions in 'where'.

        Note that it does NOT create a copy, but modifies this model.

        Args:
            model:  A list of strings, representing the names of fields to 
                model. Its value may also be "*" or ["*"], meaning all fields
                of this model.
            where: A list of 'conditiontuple's, representing the conditions to
                model.
            as_: An optional string. The name for the model to derive. If set
                to None the name of the base model is used.

        Returns:
            The modified model.
        """
        self.name = self.name if as_ is None else as_
        return self.condition(where).marginalize(keep=model)

    def predict(self, predict, where=[], splitby=[], returnbasemodel=False):
        """ Calculates the prediction against the model and returns its result
        by means of a data frame.

        The data frame contains exactly those columns/random variables which
        are specified in 'predict'. Its order is preserved.

        Note that this does NOT modify the model it is called on.

        Args:
            predict: A list of names of fields (strings) and 'AggregationTuple's.
                This is hence the list of fields to be included in the returned
                dataframe.
            where: A list of 'conditiontuple's, representing the conditions to
                adhere.
            splitby: A list of 'SplitTuple's, i.e. a list of fields on which to
                split the model and the method how to do the split.
            returnbasemodel: A boolean flag. If set this method will return the
                pair (result-dataframe, basemodel-for-the-prediction).
                Defaults to False.
        Returns:
            A dataframe with the fields as given in 'predict', or a tuple (see
            returnbasemodel).
        """
        idgen = utils.linear_id_generator()

        # (1) derive base model, i.e. a model on all requested dimensions and measures, respecting filters
        predict_ids = []  # unique ids of columns in data frame. In correct order. For reordering of columns.
        predict_names = []  # names of columns as to be returned. In correct order. For renaming of columns.

        split_names = [f.name for f in splitby]  # name of fields to split by. Same order as in split-by clause.
        split_ids = [f.name + next(idgen) for f in splitby]  # ids for columns for fields to split by. Same order as in splitby-clause.
        split_name2id = dict(zip(split_names, split_ids))  # maps split names to ids (for columns in data frames)

        aggrs = []  # list of aggregation tuples, in same order as in the predict-clause
        aggr_ids = []  # ids for columns fo fields to aggregate. Same order as in predict-clause

        basenames = set(split_names)  # set of names of fields needed for basemodel of this query
        for t in predict:
            if isinstance(t, str):
                # t is a string, i.e. name of a field that is split by
                name = t
                predict_names.append(name)
                try:
                    predict_ids.append(split_name2id[name])
                except KeyError:
                    raise ValueError("Missing split-tuple for a split-field in predict: " + name)
                basenames.add(name)
            else:
                # t is an aggregation tuple
                id_ = _tuple2str(t) + next(idgen)
                aggrs.append(t)
                aggr_ids.append(id_)
                predict_names.append(_tuple2str(t))  # generate column name to return
                predict_ids.append(id_)
                basenames.update(t.name)

        basemodel = self.copy().model(basenames, where, '__' + self.name + '_base')

        # (2) derive a sub-model for each requested aggregation
        splitnames_unique = set(split_names)        
        # for density: keep only those fields as requested in the tuple
        # for 'normal' aggregations: remove all random variables of other measures which are not also
        # a used for splitting, or equivalently: keep all random variables of dimensions, plus the one
        # for the current aggregation

        def _derive_aggregation_model(aggr):
            aggr_model = basemodel.copy()
            if aggr.method == 'density':
                return aggr_model.model(model=aggr.name)
            else:
                return aggr_model.model(model=list(splitnames_unique | set(aggr.name)))

        aggr_models = [_derive_aggregation_model(aggr) for aggr in aggrs]

        # (3) generate input for model aggregations,
        # i.e. a cross join of splits of all dimensions
        if len(splitby) == 0:
            input_frame = pd.DataFrame()
        else:
            def _get_group_frame(split, column_id):
                try:
                    domain = basemodel.byname(split.name)['domain']
                    splitfct = sp.splitter[split.method.lower()]
                except KeyError:
                    raise ValueError("split method '" + split.method + "' is not supported")
                frame = pd.DataFrame(splitfct(domain, split.args), columns=[column_id])
                frame['__crossIdx__'] = 0  # need that index to cross join later
                return frame
    
            def _crossjoin(df1, df2):
                return pd.merge(df1, df2, on='__crossIdx__', copy=False)

            group_frames = map(_get_group_frame, splitby, split_ids)        
            input_frame = reduce(_crossjoin, group_frames, next(group_frames)).drop('__crossIdx__', axis=1)

        # (4) query models and fill result data frame
        """ question is: how to efficiently query the model? how can I vectorize it?
            I believe that depends on the query. A typical query is consists of
            dimensions for splits and then aggregations and densities.
            For the case of aggregations a conditioned model has to be
            calculated for every split. I don't see how to vectorize / speed
            this up easily.
            For densities it might be very well possible, as the splits are
            now simply input to some density function.

            it might actually be faster to first condition the model on the
            dimensions (values) and then derive the measure models...
            note: for density however, no conditioning on the input is required
        """
        result_list = [input_frame]
        for idx, aggr in enumerate(aggrs):
            aggr_results = []
            aggr_model = aggr_models[idx]
            if aggr.method == 'density':
                # TODO: this is inefficient because it recalculates the same value many times, when we split on more
                # than the density is calculated on
                try:
                    # select relevant columns and iterate over it
                    ids = [split_name2id[name] for name in aggr.name]
                except KeyError:
                    raise ValueError("missing split-clause for field '" + str(name) + "'.")
                subframe = input_frame[ids]
                for _, row in subframe.iterrows():
                    res = aggr_model.density(aggr.name, row)
                    aggr_results.append(res)
            else:
                if len(splitby) == 0:
                    # there is no fields to split by, hence only a single value will be aggregated
                    # i.e. marginalize all other fields out
                    singlemodel = aggr_model.copy().marginalize(keep=aggr.name)
                    res = singlemodel.aggregate(aggr.method)
                    # reduce to requested dimension
                    res = res[singlemodel.asindex(aggr.yields)]
                    aggr_results.append(res)
                else:
                    for _, row in input_frame.iterrows():
                        pairs = zip(split_names, row)
                        # derive model for these specific conditions
                        rowmodel = aggr_model.copy()._condition(pairs).marginalize(keep=aggr.name)
                        res = rowmodel.aggregate(aggr.method)
                        # reduce to requested dimension
                        res = res[rowmodel.asindex(aggr.yields)]
                        aggr_results.append(res)

            df = pd.DataFrame(aggr_results, columns=[aggr_ids[idx]])
            result_list.append(df)

        # (5) filter on aggregations?
        # TODO? actually there should be some easy way to do it, since now it really is SQL filtering

        # (6) collect all results into one data frame
        return_frame = pd.concat(result_list, axis=1)

        # (7) get correctly ordered frame that only contain requested fields
        return_frame = return_frame[predict_ids]  # flattens

        # (8) rename columns to be readable (but not unique anymore)
        return_frame.columns = predict_names

        # (9) return data frame or tuple including the basemodel
        return (return_frame, basemodel) if returnbasemodel else return_frame


### ACTUAL MODEL IMPLEMENTATIONS

class MultiVariateGaussianModel(Model):
    """A multivariate gaussian model and methods to derive submodels from it
    or query density and other aggregations of it
    """

    def __init__(self, name):
        super().__init__(name)
        self._mu = nan
        self._S = nan
        self._detS = nan
        self._SInv = nan
        self._aggrMethods = {
            'maximum': self._maximum,
            'average': self._maximum
        }

    def _fit(self):
        model = mixture.GMM(n_components=1, covariance_type='full')
        model.fit(self.data)
        self._model = model
        self._mu = matrix(model.means_).T
        self._S = matrix(model.covars_)
        self.update()

    def __str__(self):
        return ("Multivariate Gaussian Model '" + self.name + "':\n" +
                "dimension: " + str(self._n) + "\n" +
                "names: " + str([self.names]) + "\n" +
                "fields: " + str([str(field) for field in self.fields]))

    def update(self):
        """updates dependent parameters / precalculated values of the model"""
        self._update()
        if self._n == 0:
            self._detS = None
            self._SInv = None
        else:
            self._detS = np.abs(np.linalg.det(self._S))
            self._SInv = self._S.I

        assert (self._mu.shape == (self._n, 1) and
                self._S.shape == (self._n, self._n))

        return self

    def _condition(self, pairs):
        for pair in pairs:
            # reminder: pair[1] must hold the new domain!
            self.byname(pair[0])['domain'] = pair[1]
        return self

    def _conditionout(self, names):
        """Conditions the random variables with name in names on their
        available domain and marginalizes them out
        """
        if len(names) == 0:
            return
        j = sorted(self.asindex(names))
        i = utils.invert_indexes(j, self._n)
        assert (utils.issorted(j))
        condvalues = matrix([self.fields[idx]['domain'] for idx in j]).T
        # store old sigma and mu
        #TODO: does this copy or reference!???
        S = self._S
        mu = self._mu
        # update sigma and mu according to GM script
        self._S = MultiVariateGaussianModel._schurcompl_upper(S, i)
        self._mu = mu[i] + S[ix_(i, j)] * S[ix_(j, j)].I * (condvalues - mu[j])
        self.fields = [self.fields[idx] for idx in i]
        return self.update()

    def _marginalize(self, keep):
        if len(keep) == self._n:
            return self

        # there is two types of a random variable v that is removed:
        # (i) v's domain is a single value, i.e. it is 'conditioned out'
        # (ii) v's domain is a range (continuous random variable) or a set
        #   (discrete random variable), i.e. it is 'normally' marginalized out
        condoutnames = [randVar['name'] for idx, randVar in enumerate(self.fields)
                     if (randVar['name'] not in keep) and _isSingularDomain(randVar['domain'])]
        self._conditionout(condoutnames)

        # marginalize all other not wanted random variables
        # i.e.: just select the part of mu and sigma that remains
        keepidx = sorted(self.asindex(keep))
        self._mu = self._mu[keepidx]
        self._S = self._S[np.ix_(keepidx, keepidx)]
        self.fields = [self.fields[idx] for idx in keepidx]
        return self.update()

    def _density(self, x):
        """Returns the density of the model at point x.

        Args:
            x: a Scalar or a _column_ vector as a numpy matrix.
        """
        xmu = x - self._mu
        return ((2 * pi) ** (-self._n / 2) * (self._detS ** -.5) * exp(-.5 * xmu.T * self._SInv * xmu)).item()

    def _maximum(self):
        """Returns the point of the maximum density in this model"""
        # _mu is a np matrix, but we want to return a list
        return self._mu.T.tolist()[0]

    def _sample(self):
        # TODO: let it return a dataframe?
        return self._S * np.matrix(np.random.randn(self._n)).T + self._mu

    def copy(self, name=None):
        name = self.name if name is None else name
        mycopy = MultiVariateGaussianModel(name)
        mycopy.data = self.data
        mycopy.fields = cp.deepcopy(self.fields)
        mycopy._mu = self._mu.copy()
        mycopy._S = self._S.copy()
        mycopy.update()
        return mycopy

    @staticmethod
    def custom_mvg(sigma, mu, name):
        """Returns a MultiVariateGaussian model that uses the provided sigma, mu and name.

        Note: The domain of each field is set to (-10,10).

        Args:
            sigma: a suitable numpy matrix
            mu: a suitable numpy row vector
        """

        if not isinstance(mu, matrix) or not isinstance(sigma, matrix) or mu.shape[1] != 1:
            raise ValueError("invalid arguments")
        model = MultiVariateGaussianModel(name)
        model._S = sigma
        model._mu = mu
        model.fields = [Field(name="dim" + str(idx), domain=(mu[idx].item()-2, mu[idx].item()+2)) for idx in range(sigma.shape[0])]
        model.update()
        return model

    @staticmethod
    def normal_mvg(dim, name):
        sigma = matrix(np.eye(dim))
        mu = matrix(np.zeros(dim)).T
        return MultiVariateGaussianModel.custom_mvg(sigma, mu, name)

    @staticmethod
    def _schurcompl_upper(M, idx):
        """Returns the upper Schur complement of matrix M with the 'upper block'
        indexed by idx.
        """
        # derive index lists
        i = idx
        j = utils.invert_indexes(i, M.shape[0])
        # that's the definition of the upper Schur complement
        return M[ix_(i, i)] - M[ix_(i, j)] * M[ix_(j, j)].I * M[ix_(j, i)]


if __name__ == '__main__':
    import pdb

    # foo = MultiVariateGaussianModel.normalMVG(5,"foo")
    sigma = matrix(np.array([
        [1.0, 0.6, 0.0, 2.0],
        [0.6, 1.0, 0.4, 0.0],
        [0.0, 0.4, 1.0, 0.0],
        [2.0, 0.0, 0.0, 1.]]))
    mu = np.matrix(np.array([1.0, 2.0, 0.0, 0.5])).T
    foo = MultiVariateGaussianModel.custom_mvg(sigma, mu, "foo")
    # foo.marginalize(remove=['dim3'])
    # print("\n\nmarginalized\n" + str(foo.names))
    # foo.condition([('dim1', 'equals', 3)])
    # print("\n\nconditioned\n" + str(foo))
    foocp = foo.copy("foocp")
    print("\n\nmodel 1\n" + str(foocp))
    foocp2 = foocp.model(['dim1', 'dim0'], as_="foocp2")
    print("\n\nmodel 2\n" + str(foocp2))

    res = foo.predict(predict=['dim0'], splitby=[SplitTuple('dim0', 'equiDist', [5])])
    print("\n\npredict 1\n" + str(res))
    res = foo.predict(predict=[AggregationTuple(['dim1'], 'maximum', []), 'dim0'],
                      splitby=[SplitTuple('dim0', 'equiDist', [10])])
    print("\n\npredict 2\n" + str(res))
    res = foo.predict(predict=[AggregationTuple(['dim0'], 'maximum', []), 'dim0'],
                      where=[ConditionTuple('dim0', 'equals', 1)], splitby=[SplitTuple('dim0', 'equiDist', [10])])
    print("\n\npredict 3\n" + str(res))
    res = foo.predict(predict=[AggregationTuple(['dim0'], 'density', []), 'dim0'],
                      splitby=[SplitTuple('dim0', 'equiDist', [10])])
    print("\n\npredict 4\n" + str(res))
    res = foo.predict(
        predict=[AggregationTuple(['dim0'], 'density', []), 'dim0'],
        splitby=[SplitTuple('dim0', 'equiDist', [10])],
        where=[ConditionTuple('dim0', 'greater', -1)])
    print("\n\npredict 5\n" + str(res))
    res = foo.predict(
        predict=[AggregationTuple(['dim0'], 'density', []), 'dim0'],
        splitby=[SplitTuple('dim0', 'equiDist', [10])],
        where=[ConditionTuple('dim0', 'less', -1)])
    print("\n\npredict 6\n" + str(res))
    res = foo.predict(
        predict=[AggregationTuple(['dim0'], 'density', []), 'dim0'],
        splitby=[SplitTuple('dim0', 'equiDist', [10])],
        where=[ConditionTuple('dim0', 'less', -1), ConditionTuple('dim2', 'equals', -5.0)])
    print("\n\npredict 7\n" + str(res))
    res, base = foo.predict(
        predict=[AggregationTuple(['dim0'], 'density', []), 'dim0'],
        splitby=[SplitTuple('dim0', 'equiDist', [10]), SplitTuple('dim1', 'equiDist', [7])],
        where=[ConditionTuple('dim0', 'less', -1), ConditionTuple('dim2', 'equals', -5.0)],
        returnbasemodel=True)
    print("\n\npredict 8\n" + str(res))
    res, base = foo.predict(
        predict=[AggregationTuple(['dim0'], 'average', []), AggregationTuple(['dim0'], 'density', []), 'dim0'],
        splitby=[SplitTuple('dim0', 'equiDist', [10])],
        # where=[ConditionTuple('dim0', 'less', -1), ConditionTuple('dim2', 'equals', -5.0)],
        returnbasemodel=True)
    print("\n\npredict 9\n" + str(res))
    #print("\n\n" + str(base) + "\n")
