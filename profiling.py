# Copyright (c) 2017 Philipp Lucas (philipp.lucas@uni-jena.de)
"""
Profiling script for the modelling backend

how to use it:

  (1) configure:
  * select what to profile using the do_what global variable
  * select whether to run data, model or data-model query using the mode variable

  (2) run:
  * use the line_profile:
    * add the @profile before the appropriate functions headers
    * then run it on the command shell:
      * kernprof -l -v profiling.py
  * use the built-in profiler:
    * remove and @profile decorators (if applicable)
    * run the profiler with from the IDE...
"""

import time

import modelbase as mb
import models as md

######### CONFIGURE HERE ###
do_what = 'aggregation'
mode = 'model'  # model, data or both
############################

if mode == 'both':
    where = []
elif mode == 'data':
    where = [{'name': 'model vs data', 'value': 'data', 'operator': 'equals'}]
elif mode == 'model':
    where = [{'name': 'model vs data', 'value': 'model', 'operator': 'equals'}]
else:
    raise ValueError()

mbase = mb.ModelBase(name="modelbase for profiling")
start = time.time()

if do_what == 'dummy':
    # get some model
    mpg_model = mbase.get("mcg_mpg")

    print(md.model_to_str(mpg_model))

    # run a query
    res = mpg_model.aggregate("maximum")
    print(str(res))

elif do_what == 'density':
    # run some longer density query
    query = {'SPLIT BY': [{'args': [20], 'split': 'equiinterval', 'name': 'hwy'}, {'args': [20], 'split': 'equiinterval', 'name': 'displ'}],
             'WHERE': [],
             'PREDICT': ['hwy', 'displ', {'aggregation': 'density', 'name': ['hwy', 'displ']}],
             'FROM': 'mcg_mpg'}
    query['WHERE'].extend(where)
    res = mbase.execute(query=query)
    print(str(res))

elif do_what == 'aggregation':
    # run some longer density query
    split_cnt = 5
    query = {'SPLIT BY': [{'args': [split_cnt], 'split': 'equiinterval', 'name': 'hwy'},
                          {'args': [split_cnt], 'split': 'equiinterval', 'name': 'displ'}],
             'WHERE': [],
             'PREDICT': ['hwy', 'displ', {'name': ['cyl'], 'yields': 'cyl', 'args': [], 'aggregation': 'maximum'}],
             'FROM': 'mcg_mpg'}
    query['WHERE'].extend(where)
    res = mbase.execute(query=query)
    print(str(res))
else:
    print("did nothing!")

end = time.time()
print("everything took: " + str(end-start) + " seconds")
