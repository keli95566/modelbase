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
        # Set values for independent, shared variables
        #for name in self.shared_vars.keys:
        #   if name in df.cols:
        #        self.shared_vars[name].set_value(df[name].values)
        return ()

    def _fit(self):
        with self.model_structure:
            # Draw samples
            nr_of_samples = 500
            for var in self.fields:
                self.samples[var['name']] = np.full(nr_of_samples,np.NaN)
            trace = pm.sample(nr_of_samples,chains=1,cores=1,progressbar=False)
            for varname in trace.varnames:
                self.samples[varname] = trace[varname]
            # Generate samples for independent variables
            for key,val in self.shared_vars.items():
                lower_bound = self.byname(key)['extent'].value()[0]
                upper_bound = self.byname(key)['extent'].value()[1]
                generated_samples = np.linspace(lower_bound, upper_bound, num=nr_of_samples)
                self.shared_vars[key].set_value(generated_samples)
                self.samples[key] = generated_samples
            ppc = pm.sample_ppc(trace)
            for varname in self.model_structure.observed_RVs:
                # each sample has 100 draws in the ppc, so take only the first one for each sample
                self.samples[str(varname)] = ppc[str(varname)][0]


            # Add parameters to fields
            self.fields = self.fields + get_numerical_fields(self.samples, trace.varnames)
            self._update_all_field_derivatives()
            self._init_history()

            # Change order of sample columns so that it matches order of fields
            self.samples = self.samples[self.names]
            self.test_data = self.samples
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
        elif all([math.isnan(i) for i in self.samples.values]):
            return np.NaN
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


