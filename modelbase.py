"""
@author: Philipp Lucas
"""
import seaborn.apionly as sns
import models as gm
from functools import reduce

class QuerySyntaxError(Exception):
    '''This error indicates that a PQL query was incomplete and hence could not be executed'''    
    meaning = 'This error indicates that a PQL query was incomplete and hence could not be executed'
    
    def __init__(self, message="", value=None):
        self.value = value
        self.message = message
        
    def __str__(self):
        return repr(self.value)
        

class QueryValueError(Exception):
    meaning = 'This error indicates that a PQL query contains a value that is semantically invalid, such as referring to a model that does not exist.'

    def __init__(self, message="", value=None):
        self.value = value
        self.message = message
    def __str__(self):
        return repr(self.value)

ReturnCode = {
    "SUCCESS" : "success",
    "FAIL": "fail"
}

class ModelBase:
    '''a ModelBase is the analogon of a DataBase(-Management System) but for models: it holds models and allows queries against them'''
    def __init__ (self, name):
        # load some default models
        # more data sets here: https://github.com/mwaskom/seaborn-data
        self.name = name        
        self.models = {}
        self.models['iris'] =  ModelBase._loadIrisModel()
        self.models['car_crashes'] = ModelBase._loadCarCrashModel()
        
    def __repr__ (self):
        return " -- Model Base > " + self.name+ " < -- \n" + \
            "contains " + str(len(self.models)) + " models, as follows:\n\n" + \
            reduce(lambda p, m: p + str(m) + "\n\n", self.models.values(), "")
        #return str(self.models)    
    
    def execute (self, query):
        '''executes the given query on this model base'''
        # what's the command?
        if 'MODEL' in query:
            # do basic syntax and semantics checking of the given query
            if 'FROM' not in query:
                raise QuerySyntaxError("'FROM'-statement missing")
            if 'AS' not in query:
                raise QuerySyntaxError("'AS'-statement missing")            
            if query['FROM'] not in self.models:
                raise QueryValueError("The specified model does not exist.")
            
            self._model(randVars = list( map( lambda v: v['randVar'], query['MODEL'] ) ), 
                        baseModel = self.models[query['FROM']], 
                        name = query['AS'], 
                        filters = query.get('WHERE') )            
                        
            return ReturnCode["SUCCESS"]

        elif 'PREDICT' in query:
            raise NotImplementedError()
        
        elif 'DROP' in query:
            modelToDrop = query['DROP']
            self._drop(modelToDrop)

    def _loadIrisModel ():
        # load data set as pandas DataFrame
        data = sns.load_dataset('iris')
        # train model on continuous part of the data
        model = gm.MultiVariateGaussianModel('iris', data.iloc[:, 0:-1])
        model.fit()        
        return model
        
    def _loadCarCrashModel ():        
        data = sns.load_dataset('car_crashes')
        model = gm.MultiVariateGaussianModel('car_crashes', data.iloc[:, 0:-1])
        model.fit()
        return model
       
    def _add  (self, model, name):
        if name in self.models:
            pass
        self.models[name] = model
    
    def _drop (self, name):
        del self.models[name]
        
    def _model (self, randVars, baseModel, name, filters=None):
        # 1. copy model        
        derivedModel = baseModel.copy()        
        randVarIdxs = derivedModel._asIndex(randVars)
        # 2. apply filter, i.e. condition
        if filters is not None:
            raise NotImplementedError()
        # 3. remove unneeded random variables
        derivedModel.marginalize(keep = randVarIdxs)        
        # 4. store model in model base
        self._add(derivedModel, name)        
        
    def _predict (self, query):
        raise NotImplementedError()
        
        
        
if __name__ == '__main__':
     import numpy as np
     mvg = gm.MultiVariateGaussianModel()
     mvg.fit()
     print(mvg._density(np.matrix('1 1 1 1').T))
     print(mvg._density(mvg._sample()))
     mb = ModelBase("mymodelbase")
     cc = mb.models['car_crashes']