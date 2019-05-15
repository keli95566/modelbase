# Copyright (c) 2018 Philipp Lucas (philipp.lucas@uni-jena.de), Jonas Gütter (jonas.aaron.guetter@uni-jena.de)
import os
from mb_modelbase.models_core.models import Model
from mb_modelbase.utils.data_import_utils import get_numerical_fields
from mb_modelbase.models_core import data_operations as data_op
from mb_modelbase.models_core import data_aggregation as data_aggr
import pymc3 as pm
import numpy as np
import pandas as pd
import math
from mb_modelbase.models_core.empirical_model import EmpiricalModel
from mb_modelbase.models_core import data_operations as data_op
from sklearn.neighbors.kde import KernelDensity
import scipy.optimize as sciopt
import copy as cp


class ProbabilisticPymc3Model(Model):
    """
    A Bayesian model built by the PyMC3 library is treated here.

        Parameters:

        model_structure : a PyMC3 Model() instance

        shared_vars : dictionary of theano shared variables

            If the model has independent variables, they have to be encoded as theano shared variables and provided
            in this dictionary, additional to the general dataframe containing all observed data
    """

    def __init__(self, name, model_structure, shared_vars=None):
        super().__init__(name)
        self.model_structure = model_structure
        self.samples = pd.DataFrame()
        self._aggrMethods = {
            'maximum': self._maximum
        }
        self.parallel_processing = False
        self.shared_vars = shared_vars

    def _set_data(self, df, drop_silently, **kwargs):
        self._set_data_mixed(df, drop_silently, split_data=False)
        self._update_all_field_derivatives()
        # Enforce usage of theano shared variables for independent variables
        # Independent variables are those variables which appear in the data but not in the RVs of the model structure
        model_vars = [str(name) for name in self.model_structure.observed_RVs]
        ind_vars = [varname for varname in self.data.columns.values if varname not in model_vars]
        # When there are no shared variables, there should be no independent variables. Otherwise, raise an error
        if not self.shared_vars:
            assert len(ind_vars) == 0, \
                'The model appears to include the following independent variables: ' + str(ind_vars) + ' It is '\
                'required to pass the data for these variables as theano shared variables to the ' \
                'ProbabilisticPymc3Model constructor'
        # When there are shared variables, there should be independent variables. Otherwise, raise an error
        else:
            assert len(ind_vars) > 0, ' theano shared variables were passed to the ProbabilisticPymc3Model constructor'\
                                      ' but the model does not appear to include independent variables. Only pass '\
                                      'shared variables to the constructor if the according variables are independent'
            # Each independent variable should appear in self.shared_vars. If not, raise an error
            missing_vars = [varname for varname in ind_vars if varname not in self.shared_vars.keys()]
            assert len(missing_vars) == 0, \
                'The following independent variables do not appear in shared_vars:' + str(missing_vars) + ' Make sure '\
                'that you pass the data for each independent variable as theano shared variable to the constructor'
        return ()

    def _fit(self):
        with self.model_structure:
            # Draw samples
            nr_of_samples = 500
            for var in self.fields:
                self.samples[var['name']] = np.full(nr_of_samples,np.NaN)
            trace = pm.sample(nr_of_samples, chains=1, cores=1, progressbar=False)
            # Store varnames for later generation of fields
            varnames = trace.varnames.copy()
            for varname in trace.varnames:
                # check if trace consists of more than one variable
                if len(trace[varname].shape) == 2:
                    varnames.remove(varname)
                    for i in range(trace[varname].shape[1]):
                        self.samples[varname+'_'+str(i)] = [var[i] for var in trace[varname]]
                        varnames.append(varname+'_'+str(i))
                else:
                    self.samples[varname] = trace[varname]
            # Generate samples for independent variables
            if hasattr(self, 'shared_vars'):
                if self.shared_vars is not None:
                    for key, val in self.shared_vars.items():
                        lower_bound = self.byname(key)['extent'].value()[0]
                        upper_bound = self.byname(key)['extent'].value()[1]
                        generated_samples = np.linspace(lower_bound, upper_bound, num=nr_of_samples)
                        # If the samples have another data type than the original data, problems can arise. Therefore,
                        # data types of the new samples are changed to the dtypes of the original data here
                        if str(generated_samples.dtype) != self.shared_vars[key].dtype:
                            generated_samples = generated_samples.astype(self.shared_vars['years'].dtype)
                        self.shared_vars[key].set_value(generated_samples)
                        self.samples[key] = generated_samples
                    ppc = pm.sample_ppc(trace)
                    for varname in self.model_structure.observed_RVs:
                        # sample_ppc works the following way: For each parameter set generated by sample(), a sequence of
                        # points is generated with the same length as the observed data. So, in the i-th row of the
                        # samples df, we want to write the new data point that was generated by the i-th parameter set and
                        # the i-th row of the given data: ppc[...][i][i].
                        self.samples[str(varname)] = [ppc[str(varname)][i][i] for i in range(nr_of_samples)]
                else:
                    # when no shared vars are given, data and samples do not have the same length. In this case, the first
                    # point of each sequence is taken as new sample point
                    ppc = pm.sample_ppc(trace)
                    for varname in self.model_structure.observed_RVs:
                        self.samples[str(varname)] = [samples[0] for samples in ppc[str(varname)]]
            else:
                # when no shared vars are given, data and samples do not have the same length. In this case, the first
                # point of each sequence is taken as new sample point
                ppc = pm.sample_ppc(trace)
                for varname in self.model_structure.observed_RVs:
                    self.samples[str(varname)] = [samples[0] for samples in ppc[str(varname)]]

        # Add parameters to fields
        self.fields = self.fields + get_numerical_fields(self.samples, varnames)
        self._update_all_field_derivatives()
        self._init_history()

        # Change order of sample columns so that it matches order of fields
        self.samples = self.samples[self.names]
        self.test_data = self.samples

        # Mark variables as independent. Independent variables are variables that appear in the data but
        # not in the observed random variables of the model
        for field in self.fields:
            if field['name'] in self.data.columns and \
                    field['name'] not in [str(var) for var in self.model_structure.observed_RVs]:
                field['independent'] = True
        return ()

    def _marginalizeout(self, keep, remove):
        keep_not_in_names = [name for name in keep if name not in self.names]
        if len(keep_not_in_names) > 0:
            raise ValueError('The following variables in keep do not appear in the model: ' + str(keep_not_in_names) )
        remove_not_in_names = [name for name in remove if name not in self.names]
        if len(remove_not_in_names) > 0:
            raise ValueError('The following variables in remove do not appear in the model: ' + str(remove_not_in_names))
        # Remove all variables in remove
        for varname in remove:
            if varname in list(self.samples.columns):
                self.samples = self.samples.drop(varname,axis=1)
            if hasattr(self, 'shared_vars'):
                if self.shared_vars is not None:
                    if varname in self.shared_vars:
                        del self.shared_vars[varname]
        return ()

    def _conditionout(self, keep, remove):
        keep_not_in_names = [name for name in keep if name not in self.names]
        if len(keep_not_in_names) > 0:
            raise ValueError('The following variables in keep do not appear in the model: ' + str(keep_not_in_names) )
        remove_not_in_names = [name for name in remove if name not in self.names]
        if len(remove_not_in_names) > 0:
            raise ValueError('The following variables in remove do not appear in the model: ' + str(remove_not_in_names))
        names = remove
        fields = self.fields if names is None else self.byname(names)
        # Here: Konditioniere auf die Domäne der Variablen in remove
        for field in fields:
            # filter out values smaller than domain minimum
            filter = self.samples.loc[:,str(field['name'])] > field['domain'].value()[0]
            self.samples.where(filter, inplace = True)
            # filter out values bigger than domain maximum
            filter = self.samples.loc[:,str(field['name'])] < field['domain'].value()[1]
            self.samples.where(filter, inplace = True)
        self.samples.dropna(inplace=True)
        self._marginalizeout(keep, remove)
        return ()

    def _density(self, x):
        if self.samples.empty:
            raise ValueError("There are no samples in the model")
        #elif all([math.isnan(i) for i in self.samples.values]):
        #    return np.NaN
        else:
            X = self.samples.values
            kde = KernelDensity(kernel='gaussian', bandwidth=0.1).fit(X)
            x = np.reshape(x,(1,len(x)))
            logdensity = kde.score_samples(x)[0]
            return np.exp(logdensity).item()



    def _negdensity(self,x):
        return -self._density(x)

    def _sample(self):
        sample = []
        with self.model_structure:
            trace = pm.sample(1,chains=1,cores=1)
            ppc = pm.sample_ppc(trace)
            for varname in self.names:
                if varname in [str(name) for name in self.model_structure.free_RVs]:
                    sample.append(trace[varname][0])
                elif varname in [str(name) for name in self.model_structure.observed_RVs]:
                    sample.append(ppc[str(varname)][0][0])
                else:
                    raise ValueError("Unexpected error: variable name " + varname +  " is not found in the PyMC3 model")

        return (sample)

    def copy(self, name=None):
        name = self.name if name is None else name
        mycopy = self.__class__(name, self.model_structure)
        mycopy.data = self.data.copy()
        mycopy.test_data = self.test_data.copy()
        mycopy.fields = cp.deepcopy(self.fields)
        mycopy.mode = self.mode
        mycopy._update_all_field_derivatives()
        mycopy.history = cp.deepcopy(self.history)
        mycopy.samples = self.samples.copy()
        return mycopy

    def _maximum(self):
        """Returns the point of the maximum density in this model"""
        row_cnt, col_cnt = self.samples.shape
        if row_cnt == 0:
            # can not compute any aggregation. return nan
            return [None] * col_cnt
        x0 = np.zeros(len(self.fields))
        maximum = sciopt.minimize(self._negdensity,x0,method='nelder-mead',options={'xtol': 1e-8, 'disp': False}).x
        return maximum


