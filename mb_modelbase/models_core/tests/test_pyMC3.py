import numpy as np
import unittest
import mb_modelbase.models_core.tests.create_PyMC3_testmodels as cr
import copy

def create_testmodels(fit):
    models = []
    # These functions return the model data and the corresponding model
    models.append(cr.create_pymc3_simplest_model(fit=fit))
    models.append(cr.create_pymc3_getting_started_model(fit=fit))
    models.append(cr.create_pymc3_getting_started_model_independent_vars(fit=fit))
    models.append(cr.create_pymc3_coal_mining_disaster_model(fit=fit))
    models.append(cr.create_getting_started_model_shape(fit=fit))
    models.append(cr.create_flight_delay_model(fit=fit))
    return models

models_unfitted = create_testmodels(fit=False)
models_fitted = create_testmodels(fit=True)



class TestMethodsOnInitializedModel(unittest.TestCase):
    """
    Test the ProbabilisticPymc3Model methods on a model that has just been initialized
    """

    def testinit(self):
        """
        Test if newly initialized model has data, test data or samples and if mode is set to None
        """
        for data, mymod in copy.deepcopy(models_unfitted):
            self.assertEqual(mymod.data.empty, 1, "There should be no data. Model:" + mymod.name)
            self.assertEqual(mymod.test_data.empty, 1, "There should be no test data. Model:" + mymod.name)
            self.assertEqual(mymod.samples.empty, 1, "There should be no samples. Model:" + mymod.name)
            self.assertIsNone(mymod.mode, "Mode of just instantiated model should be set to None. Model:" + mymod.name)

    def testcopy(self):
        """
        Test if data, test data and samples of the copied model are the same as in the original model
        """
        for data, mymod in copy.deepcopy(models_unfitted):
            mymod_copy = mymod.copy()
            self.assertEqual(mymod.data.equals(mymod_copy.data), 1,
                             "Copied model data is different than original model data. Model:" + mymod.name)
            self.assertEqual(mymod.test_data.equals(mymod_copy.test_data), 1,
                             "Copied model test data is different than original model test data. Model: " + mymod.name)
            self.assertEqual(mymod.samples.equals(mymod_copy.samples), 1,
                             "Copied samples are different than original samples. Model: " + mymod.name)

    def test_set_data(self):
        """
        Test if the set_data() method gives any data to the model
        and if the model data has the same columns as the input data and if mode is set to data
        """
        for data, mymod in copy.deepcopy(models_unfitted):
            mymod.set_data(data)
            self.assertEqual(mymod.data.empty, 0, "There is no data in the model. Model: " + mymod.name)
            self.assertEqual(mymod.data.columns.equals(data.columns), 1,
                             "model data has different columns than the original data. Model: " + mymod.name)
            self.assertEqual(mymod.mode, 'data', "model mode should be set to data. Model: " + mymod.name)

    def test_marginalizeout(self):
        """
        Call _marginalizeout on a model without any samples.
        An error should be thrown since the model does not yet know any variables
        """
        for data, mymod in copy.deepcopy(models_unfitted):
            with self.assertRaises(ValueError):
                mymod._marginalizeout(keep='A', remove='B')
            self.assertEqual(mymod.data.empty, 1, "There should be no data. Model: " + mymod.name)
            self.assertEqual(mymod.test_data.empty, 1, "There should be no test data. Model: " + mymod.name)
            self.assertEqual(mymod.samples.empty, 1, "There should be no samples. Model: " + mymod.name)
            self.assertIsNone(mymod.mode, "Mode of just instantiated model should be set to None. Model: " + mymod.name)

    def test_conditionout(self):
        """
        Call _conditionout on a model without any samples.
        An error should be thrown since the model does not yet know any variables
        """
        for data, mymod in copy.deepcopy(models_unfitted):
            with self.assertRaises(ValueError):
                mymod._conditionout(keep='A', remove='B')
            self.assertEqual(mymod.data.empty, 1, "There should be no data. Model: " + mymod.name)
            self.assertEqual(mymod.test_data.empty, 1, "There should be no test data. Model: " + mymod.name)
            self.assertEqual(mymod.samples.empty, 1, "There should be no samples. Model: " + mymod.name)
            self.assertIsNone(mymod.mode, "Mode of just instantiated model should be set to None. Model: " + mymod.name)

    def test_density(self):
        """
        Calculate a probability density on a model.
        An error should be thrown since the model does not yet know any variables
        """
        for data, mymod in copy.deepcopy(models_unfitted):
            with self.assertRaises(ValueError):
                mymod.density([0])

    def test_maximum(self):
        """
        Calculate the maximum probability of a model without samples. It should return an empty array
        """
        for data, mymod in copy.deepcopy(models_unfitted):
            self.assertTrue(len(mymod._maximum()) == 0,
                            "maximum density point for a model without variables should be an empty array. "
                            "Model: " + mymod.name)


class TestMethodsOnModelWithData(unittest.TestCase):
    """
    Test the ProbabilisticPymc3Model methods on a model that has been initialized and given data
    """

    def testcopy(self):
        """
        Test if data, test data and samples of the copied model are the same as in the original model
        """
        for data, mymod in copy.deepcopy(models_unfitted):
            mymod.set_data(data)
            mymod_copy = mymod.copy()
            self.assertEqual(mymod.data.equals(mymod_copy.data), 1,
                             "Copied model data is different than original model data. Model: " + mymod.name)
            self.assertEqual(mymod.test_data.equals(mymod_copy.test_data), 1,
                             "Copied model test data is different than original model test data. Model: " + mymod.name)
            self.assertEqual(mymod.samples.equals(mymod_copy.samples), 1,
                             "Copied samples are different than original samples. Model: " + mymod.name)

    def test_fit(self):
        """
        Test if there are samples, data and test data in the model and if the mode is set to both
        """
        for data, mymod in copy.deepcopy(models_unfitted):
            mymod.fit(data)
            self.assertEqual(mymod.data.empty, 0, "There is no data in the model. Model: " + mymod.name)
            self.assertEqual(mymod.test_data.empty, 0, "There is no test data in the model. Model: " + mymod.name)
            self.assertEqual(mymod.samples.empty, 0, "There are no samples in the model. Model: " + mymod.name)
            self.assertEqual(mymod.mode, 'both', "mode should be set to both. Model: " + mymod.name)
            self.assertEqual(mymod.names, list(mymod.samples.columns.values),
                             "names and samples should hold the same variables in the same order. Model: " + mymod.name)
            self.assertEqual(mymod.names, [field['name'] for field in mymod.fields],
                             "names and fields should hold the same variables in the same order. Model: " + mymod.name)

    def test_marginalizeout(self):
        """
        Call _marginalizeout on a model without any samples for variables not in the model.
        An error should be thrown since the model does not have the variables
        """
        for data, mymod in copy.deepcopy(models_unfitted):
            mymod.set_data(data)
            with self.assertRaises(ValueError):
                mymod._marginalizeout(keep='A', remove='B')
            self.assertEqual(mymod.data.empty, 0, "There should be data. Model: " + mymod.name)
            self.assertEqual(mymod.samples.empty, 1, "There should be no samples. Model: " + mymod.name)
            self.assertEqual(mymod.mode, "data",
                             "Mode of just instantiated model should be set to data. Model: " + mymod.name)

    def test_conditionout(self):
        """
        Call _conditionout on a model without any samples for variables not in the model.
        An error should be thrown since the model does not have the variables
        """
        for data, mymod in copy.deepcopy(models_unfitted):
            mymod.set_data(data)
            with self.assertRaises(ValueError):
                mymod._conditionout(keep='A', remove='B')
            self.assertEqual(mymod.data.empty, 0, "There should be data. Model: " + mymod.name)
            self.assertEqual(mymod.samples.empty, 1, "There should be no samples. Model: " + mymod.name)
            self.assertEqual(mymod.mode, "data",
                             "Mode of just instantiated model should be set to data. Model: " + mymod.name)
    def test_maximum(self):
        """
        Calculate the maximum probability of a model without samples. It should return an empty array
        """
        for data, mymod in copy.deepcopy(models_unfitted):
            mymod.set_data(data)
            self.assertTrue(len(mymod._maximum()) == 0,
                            "maximum density point for a model without samples should be an empty array. "
                            "Model: " + mymod.name)

class TestMethodsOnFittedModel(unittest.TestCase):
    """
    Test the ProbabilisticPymc3Model methods on a model that has been initialized, given data and fitted
    """

    def testcopy(self):
        """
        Test if data, test data and samples of the copied model are the same as in the original model
        """
        for data, mymod in copy.deepcopy(models_fitted):
            mymod_copy = mymod.copy()
            self.assertEqual(mymod.data.equals(mymod_copy.data), 1,
                             "Copied model data is different than original model data. Model: " + mymod.name)
            self.assertEqual(mymod.test_data.equals(mymod_copy.test_data), 1,
                             "Copied model test data is different than original model test data. Model: " + mymod.name)
            self.assertEqual(mymod.samples.equals(mymod_copy.samples), 1,
                             "Copied samples are different than original samples. Model: " + mymod.name)

    def test_marginalizeout(self):
        """
        Call _marginalizeout on a fitted model. Check if the correct variables are removed from the model
        """
        for data, mymod in copy.deepcopy(models_fitted):
            keep = mymod.names[1:]
            remove = [mymod.names[0]]
            mymod._marginalizeout(keep=keep, remove=remove)
            self.assertEqual(mymod.data.empty, 0,"There should be data. Model: " + mymod.name)
            self.assertEqual(mymod.test_data.empty, 0, "There should be test data. Model: " + mymod.name)
            self.assertEqual(mymod.samples.empty, 0, "There should be samples. Model: " + mymod.name)
            self.assertEqual(mymod.mode, "both",
                             "Mode of just instantiated model should be set to both. Model: " + mymod.name)
            self.assertFalse(remove[0] in mymod.samples.columns,
                             str(remove) + " should be marginalized out and not be present in the samples. "
                                           "Model: " + mymod.name)
            self.assertTrue(all([name in mymod.samples.columns for name in keep]),
                            str(keep) + "should be still present in the samples. Model: " + mymod.name)

    def test_conditionout(self):
        """
        Call _conditionout on a fitted model. Check if the correct variables are removed from the model
        and if all the samples are within the variable domain
        """
        for data, mymod in copy.deepcopy(models_fitted):
            keep = mymod.names[1:]
            remove = [mymod.names[0]]

            sample_size_all_values = len(mymod.samples)
            mymod.fields[0]['domain'].setupperbound(np.mean(mymod.samples[remove[0]]))
            isBiggerThanUpperBound = mymod.samples[remove[0]] > np.mean(mymod.samples[remove[0]])
            big_samples = mymod.samples[remove[0]][isBiggerThanUpperBound]
            sample_size_big_values = len(big_samples)

            mymod._conditionout(keep=keep, remove=remove)
            self.assertEqual(mymod.data.empty, 0, "There should be data. Model: " + mymod.name)
            self.assertEqual(mymod.test_data.empty, 0, "There should be test data. Model: " + mymod.name)
            self.assertEqual(mymod.samples.empty, 0, "There should be samples. Model: " + mymod.name)
            self.assertEqual(mymod.mode,"both",
                             "Mode of just instantiated model should be set to both. Model: " + mymod.name)
            self.assertFalse(remove in mymod.samples.columns.values,
                             str(remove) + " should be marginalized out and not be present in the samples. "
                                           "Model: " + mymod.name)
            self.assertTrue(all([name in mymod.samples.columns for name in keep]),
                            str(keep) + "should be still present in the samples. Model: " + mymod.name)
            sample_size_small_values = len(mymod.samples)
            self.assertEqual(sample_size_all_values-sample_size_big_values, sample_size_small_values,
                             "numbers of removed samples and kept samples do not add up to previous number of samples. "
                             "Model: " + mymod.name)

    def test_density(self):
        """
        Calculate a probability density on a model. A single scalar should be the return value
        """
        for data, mymod in copy.deepcopy(models_fitted):
            location = np.zeros(len(mymod.names))
            self.assertTrue(isinstance(mymod.density(location), float),
                            "A single scalar should be returned. Model: " + mymod.name)

    def test_maximum(self):
        """
        Calculate the maximum probability of a model. Dimensions should match
        """
        for data, mymod in copy.deepcopy(models_fitted):
            self.assertEqual(len(mymod._maximum()), len(mymod.names),
                             "Dimension of the maximum does not match dimension of the model. Model: " + mymod.name)

    def test_sample(self):
        for data, mymod in copy.deepcopy(models_fitted):
            n = 10
            self.assertEqual(mymod.sample(n).shape[0],  n, 'Number of samples is not correct')


class TestMoreCombinationsOnModel(unittest.TestCase):
    """
    Test more complex cases, with more combinations of methods being applied to a already fitted model
    """

    # More combinations of marginalization and conditionalization cannot be applied
    # to the simple model since it only has two variables
    # TODO: What happens when each variable is marginalized out?

    def test_maximum_marginalized(self):
        """
        Check if the density maximum of a marginalized model has the same dimensions as the model variables
        """
        for data, mymod in copy.deepcopy(models_fitted):
            remove = mymod.names[0]
            mymod.marginalize(remove=remove)
            self.assertEqual(len(mymod._maximum()), len(mymod.names),
                             "Dimensions of the maximum and the model variables do not match. Model: " + mymod.name)


if __name__ == "__main__":
    unittest.main()
