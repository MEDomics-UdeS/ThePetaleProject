"""
Author : Nicolas Raymond

This file contains the Sampler class used to separate test sets from train sets
"""

from Datasets.Datasets import PetaleDataset
from .Transforms import ContinuousTransform as ConT
from SQL.NewTablesScripts.constants import *
import numpy as np
import pandas as pd


class Sampler:

    def __init__(self, dm, table_name, cont_cols, target_col, cat_cols=None):
        """
        Object that creates all datasets
        :param dm: PetaleDataManager
        :param table_name: name of the table on which we want to sample datasets
        :param cont_cols: list with the names of continuous columns of the table
        :param cat_cols: list with the names of the categorical columns of the table
        :param target_col: name of the target column in the table
        """

        # We save the learning set as seen in the Workflow presentation
        self.learning_set = dm.get_table(table_name)

        # We make sure that continuous variables are considered as continuous
        self.learning_set[cont_cols] = ConT.to_float(self.learning_set[cont_cols])

        # We save the continuous and categorical column names
        self.cont_cols = cont_cols
        self.cat_cols = cat_cols

        # We save the target column name
        self.target_col = target_col

    def __call__(self, k=5, l=2, split_cat=True, test_size=0.20, add_biases=False):
        return self.create_train_and_test_datasets(k, l, split_cat, test_size, add_biases)

    def create_train_and_test_datasets(self, k=5, l=2, split_cat=True, test_size=0.20, add_biases=False):
        """
        Creates the train and test PetaleDatasets from the df and the specified continuous and categorical columns

        :param k: number of outer validation loops
        :param l: number if inner validation loops
        :param split_cat: boolean indicating if we want to split categorical variables from the continuous ones
        :param test_size: number of elements in the test set (if 0 < test_size < 1 we consider the parameter as a %)
        :param add_biases: boolean indicating if a column of ones should be added at the beginning of X_cont
        :return: dictionary with all datasets
        """

        # We initialize an empty dictionary to store the outer loops datasets
        all_datasets = {}

        # We create the datasets for the outer validation loops:
        for i in range(k):

            # We split the training and test data
            train, test = split_train_test(self.learning_set, self.target_col, test_size)
            outer_dict = self.dataframes_to_datasets(train, test, split_cat, add_biases)

            # We add storage in the outer dict to save the inner loops datasets
            outer_dict['inner'] = {}

            # We create the datasets for the inner validation loops
            for j in range(l):

                inner_train, inner_test = split_train_test(train, self.target_col, test_size)
                outer_dict['inner'][j] = self.dataframes_to_datasets(inner_train, inner_test, split_cat, add_biases)
                all_datasets[i] = outer_dict

        return all_datasets

    def dataframes_to_datasets(self, train, test, split_cat=True, add_biases=False):
        """
        Turns two pandas dataframe into training and test PetaleDatasets

        :return: dict
        """
        # We save the mean and the standard deviations of the continuous columns in train
        mean, std = train[self.cont_cols].mean(), train[self.cont_cols].std()

        # We create the test and train datasets
        train_ds = PetaleDataset(train, self.cont_cols, self.target_col, cat_cols=self.cat_cols,
                                 split=split_cat, add_biases=add_biases)

        test_ds = PetaleDataset(test, self.cont_cols, self.target_col, cat_cols=self.cat_cols,
                                split=split_cat, mean=mean, std=std, add_biases=add_biases)

        return {"train": train_ds, "test": test_ds}


class WarmUpSampler(Sampler):

    def __init__(self, dm):
        """
        Creates a Sampler for the WarmUp data table
        :param dm: PetaleDataManager
        """
        cont_cols = [WEIGHT, TDM6_HR_END, TDM6_DIST, DT, AGE, MVLPA]
        super().__init__(dm, LEARNING_0, cont_cols, VO2R_MAX)


class LearningOneSampler(Sampler):

    def __init__(self, dm):
        """
        Creates a Sampler for the Learning One data table
        :param dm: PetaleDataManager
        """
        # We save continuous columns
        cont_cols = [AGE, HEIGHT, WEIGHT, AGE_AT_DIAGNOSIS, DT, TSEOT, RADIOTHERAPY_DOSE, TDM6_DIST, TDM6_HR_END,
                     TDM6_HR_REST, TDM6_TAS_END, TDM6_TAD_END, MVLPA, TAS_REST, TAD_REST, DOX]

        # We save the categorical columns
        cat_cols = [SEX, SMOKING, DEX_PRESENCE]

        super().__init__(dm, LEARNING_1, cont_cols, FITNESS_LVL, cat_cols)


def split_train_test(df, target_col, test_size=0.20, random_state=None):
    """
    Split de training and testing data contained within a pandas dataframe
    :param df: pandas dataframe
    :param target_col: name of the target column
    :param test_size: number of elements in the test set (if 0 < test_size < 1 we consider the parameter as a %)
    :param random_state: seed for random number generator (does not overwrite global seed value)
    :return: 2 pandas dataframe
    """

    # Test and train split
    test_data = stratified_sample(df, target_col, test_size, random_state=random_state)
    train_data = df.drop(test_data.index)

    return train_data, test_data


def stratified_sample(df, target_col, n, quantiles=4, random_state=None):
    """
    Proceeds to a stratified sampling of the original dataset based on the target variable

    :param df: pandas dataframe
    :param target_col: name of the column to use for stratified sampling
    :param n: sample size, if 0 < n < 1 we consider n as a percentage of data to select
    :param quantiles: number of quantiles to used if the target_col is continuous
    :param random_state: seed for random number generator (does not overwrite global seed value)
    :return: pandas dataframe
    """
    if target_col not in df.columns:
        raise Exception('Target column not part of the dataframe')
    if n < 0:
        raise Exception('n must be greater than 0')

    # If n is a percentage we change it to a integer
    elif 0 < n < 1:
        n = int(n*df.shape[0])

    # We make a deep copy of the current dataframe
    sample = df.copy()

    # If the column on which we want to do a stratified sampling is continuous,
    # we create another discrete column based on quantiles
    if len(df[target_col].unique()) > 10:
        sample["quantiles"] = pd.qcut(sample[target_col], quantiles, labels=False)
        target_col = "quantiles"

    # We execute the sampling
    sample = sample.groupby(target_col, group_keys=False).\
        apply(lambda x: x.sample(int(np.rint(n*len(x)/len(sample))), random_state=random_state)).\
        sample(frac=1, random_state=random_state)

    sample = sample.drop(['quantiles'], axis=1, errors='ignore')

    return sample

