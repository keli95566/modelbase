import numpy as np
import pandas as pd

from mb_modelbase.utils import utils


def filter_(df, point_conditions):
    """ Applies all '==' filters in the sequence of conditions to given dataframe and returns it."""
    # TODO: do I need some general solution for the interval vs scalar problem?
    for (col_name, value) in point_conditions:
        try:
            if not isinstance(value, str):  # try to access its elements
                # TODO: this really is more difficult. in the future we want to support values like ['A', 'B']
                # TODO: I guess I should pass a (list of) Domain to the density-method in the first place
                # assuming interval for now
                df = df.loc[df[col_name].between(*value, inclusive=True)]
            else:
                df = df.loc[df[col_name] == value]
        except TypeError:  # catch when expansion (*value) fails. its a scalar then...
            df = df.loc[df[col_name] == value]
    return df

# def filter2 (df, conditions):
#     # [
#     for (col_name, values) in conditions:
#         try:
#
#             if not isinstance(value, str):  # try to access its elements
#                 # TODO: this really is more difficult. in the future we want to support values like ['A', 'B']
#                 # TODO: I guess I should pass a (list of) Domain to the density-method in the first place
#                 # assuming interval for now
#                 df = df.loc[df[col_name].between(*value, inclusive=True)]
#             else:
#                 df = df.loc[df[col_name] == value]
#         except TypeError:  # catch when expansion (*value) fails. its a scalar then...
#             df = df.loc[df[col_name] == value]
#     return df


def _condition_data(df, name, operator, values):
    """Conditions the data of the model according to given parameters. Returns nothing.
    """
    column = df.loc[:, name]  # references the column, doesn't copy
    if operator == 'in':
        if column.dtype == 'object':   # categorical column
            df = df.loc[column.isin(values)]
        else:   # quantitative column
            df = df.loc[column.between(*values, inclusive=True)]
    else:
        # values is necessarily a single scalar value, not a list
        if operator == 'equals' or operator == '==':
            df = df.loc[column == values]
        elif operator == 'greater' or operator == '>':
            df = df.loc[column > values]
        elif operator == 'less' or operator == '<':
            df = df.loc[column < values]
        else:
            raise ValueError('invalid operator for condition: ' + str(operator))
    return df


def reduce_to_scalars(values):
    """Reduce all elements of values to scalars, as follows:
       * a scalar s are kept: s -> s
       * an interval [a,b] is reduced to its mean: [a,b] -> (a+b)/2
       Note that it only accepts numbers or intervals of numbers.
    """
    v = []
    for value in values:
        # all of the todos in filter apply here as well...
        try:
            if not isinstance(value, str):
                v.append((value[0] + value[1]) / 2)
            else:
                v.append(value)
        except (TypeError, IndexError):
            v.append(value)
    return v
