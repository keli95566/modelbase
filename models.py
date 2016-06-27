"""
Created on Mon Jun 13 13:43:29 2016

@author: Philipp Lucas
"""
import numpy as np
from numpy import pi, exp, matrix, ix_, nan
from sklearn import mixture

# probably remove this import later. Just for convenience to have default data for models available
import seaborn.apionly as sns
   
''' 
 ## how to get from data to model ##
   
1. provide some data file
2. open that data file
3. read that file into a tabular structure and guess its header, i.e. its columns and its data types
4. use it to train a model
5. return the model

https://github.com/rasbt/pattern_classification/blob/master/resources/python_data_libraries.md !!!

## query a model

1. receive JSON object that describes the query
2. execute query:

### what about using a different syntax for the model, like the following:

    model['A'] : to select a submodel only on random variable with name 'A' // marginalize
    model['B'] = ...some domain...   // condition
    model.
    
### other    
Somehow, I get the feeling I'm using numpy not correctly. it's too complicated to always have to write matrix() explicitely 
'''

### UTILITY FUNCTIONS ###

def invertedIdxList (idx, len) :
    '''utility function that returns an inverted index list, e.g. given [0,1,4] and len=6 it returns [2,3,5].'''
    return list( set(range(0, len)) - set(idx) )   
    
def UpperSchurCompl (M, idx):
    '''Returns the upper Schur complement of matrix M with the 'upper block' indexed by i'''
    # derive index lists
    i = idx
    j = invertedIdxList(i, M.shape[0])

    # that's the definition of the upper Schur complement
    return M[ix_(i,i)] - M[ix_(i,j)] * M[ix_(j,j)].I * M[ix_(j,i)]        

### GENERIC / ABSTRACT MODELS and other base classes ###
      
class Field(dict):    
    '''a random variable of a probability model
       name ... name of the field, i.e a string descriptor
       domain ... range of possible values, either a list (dtype == 'categorial') or a numerical range as a tuple (min, max)
       dtype ... data type: either 'float' or 'categorical'
    '''
    def __init__ (self, name=None, domain=None, dtype=None, base=None):        
        # just a fancy way of providing a clean interface to actually nothing more than a python dict
        if name is not None and domain is not None:
            super().__init__(name=name, domain=domain, dtype=dtype)
        elif base is not None:
            raise NotImplementedError()
        else:
            raise ValueError()
    
    def __str__ (self):
        return self['name'] + "(" + self['dtype'] + ")" 
       
        
class Model:
    '''an abstract base model that provides an interface to derive submodels from it or query density and other aggregations of it'''
    
    def _getHeader (df):
        ''' derive fields from a given pandas dataframe'''
        fields = []
        for column in df:
            ''' todo: this only works for continuous data '''
            field = Field( name = column, domain = (df[column].min(), df[column].max()), dtype = 'continuous' )
            fields.append(field)
        return fields

    def _asIndex (self, names):
        '''given a list of names of random variables, returns the indexes of these in the .field attribute of the model'''
        #return sorted( map( lambda name: self.fields))        
        #return sorted( map( lambda i: self.fields[i], names ) )
        #return [ for name in names if self.fields.index()]        
        noArrayFlag = False        
        if type(names) is not list:
            names = [names]
            noArrayFlag = True            
        indices = []
        for idx, field in enumerate(self.fields):
            if field['name'] in names:
                indices.append(idx)        
        return  indices[0] if noArrayFlag else indices
       
    def __init__ (self, name, dataframe):
        self.name = name
        self.data = dataframe
        self.fields = Model._getHeader(self.data)
        #self.fields.__str__ = lambda f: 
        self._aggrMethods = None
            
    def fit (self):
        raise NotImplementedError()        
            
    def marginalize (self, keep = [], remove = []):
        if keep:
            self._marginalize(keep)
        else:
            raise NotImplementedError()    
    
    def _marginalize (self, keep):
        raise NotImplementedError()
    
    def condition (self, pairs):
        raise NotImplementedError()
    
    def aggregate (self, method):
        if (method in self._aggrMethods):
            return self._aggrMethods[method]()
        else:
            raise NotImplementedError()
            
    def sample (self, n=1):
        '''returns n many samples drawn from the model'''
        return [self._sample() for i in range(n)]

    def _sample(self):
        raise NotImplementedError()
    
    def copy(self):
        raise NotImplementedError()

### ACTUAL MODEL IMPLEMENTATIONS ###

class MultiVariateGaussianModel (Model):
    '''a multivariate gaussian model and methods to derive submodels from it or query density and other aggregations of it'''
    def __init__ (self, name = "iris", data = sns.load_dataset('iris').iloc[:, 0:4]):
        # make sure these are matrix types (numpy.matrix)
        super().__init__(name, data)              
        self._mu = nan
        self._S = nan
        self._aggrMethods = {
            'maximum': self._maximum,
            'average': self._maximum
        }
    
    def fit (self):
        model = mixture.GMM(n_components=1, covariance_type='full')
        model.fit(self.data)
        self._model = model        
        self._mu = matrix(model.means_).T
        self._S = matrix(model.covars_)
        self._update()
        
    def __str__ (self):
        return( "Multivariate Gaussian Model '" + self.name + "':\n" + \
                "dimension: " + str(self._n) + "\n" + \
                "random variables: " + str( [str(field) for field in self.fields] ))
#                "mu:\n" + str(self._mu) + "\n" + \
#               "sigma:\n" + str(self._S) + "\n")
        
    def _update (self):
        '''updates dependent parameters / precalculated values of the model'''
        self._n = self._mu.shape[0]        
        self._detS = np.abs(np.linalg.det(self._S))
        self._SInv = self._S.I
        
    def condition (self, pairs):
        '''conditions this model according to the list of 2-tuples (<name-of-random-variable>, <condition-value>)'''
        if len(pairs) == 0:
            return
        i, xj = zip(*pairs)
        i = list(i)
        xj = list(xj)
        i = self._asIndex(i)
        j = invertedIdxList(i, self._n)        
        # store old sigma and mu
        S = self._S
        mu = self._mu                
        # update sigma and mu according to GM script
        self._S = UpperSchurCompl(S, i)        
        self._mu = mu[i] + S[ix_(i,j)] * S[ix_(j,j)].I * (xj - mu[j])        
        self._update()
    
    def _marginalize (self, keep):        
        '''marginalizes all but the variables given by their name in keep out
        of this model.
        
        Note for Future: Note that marginalization is done depending on the available domain of 
        a random variable. That is, if only a single value is left in the 
        domain it is conditioned on this value and marginalized out. Otherwise
        it is marginalized out (assuming that the full domain is available)'''                 
        #remove = invertedIdxList(keep)        
        # just select the part of mu and sigma that remains
        keepIdx = self._asIndex(keep)
        self._mu = self._mu[keepIdx]  
        self._S = self._S[np.ix_(keepIdx, keepIdx)]
        self.fields = [self.fields[idx] for idx in keepIdx]
        self._update()
    
    def _density (self, x):   
        xmu = x - self._mu
        return (2*pi)**(-self._n/2) * (self._detS**-.5) * exp( -.5 * xmu.T * self._SInv * xmu )
        
    def _maximum (self):
        return self._mu
    
    def _sample  (self):
        return self._S * np.matrix(np.random.randn(self._n)).T + self._mu
        
    def copy (self):
        mycopy = MultiVariateGaussianModel(name = self.name, data = self.data)
        mycopy._mu = self._mu
        mycopy._S = self._S
        mycopy._update()
        return mycopy
