"""
Authors : Nicolas Raymond

This files contains all class function related to preprocessing

"""
from Data.Transforms import ContinuousTransform as ConT
from Data.Transforms import CategoricalTransform as CaT

ENCODING = ["ordinal", "one-hot"]


def preprocess_continuous(df, mean=None, std=None):
    """
    Applies all continuous transforms to a dataframe containing only continuous data

    :param df: pandas dataframe
    :param mean: pandas series with mean
    :param std: pandas series with standard deviations
    :return: pandas dataframe
    """
    return ConT.normalize(ConT.fill_missing(df, mean), mean, std)


def preprocess_categoricals(df, encoding="ordinal", mode=None):
    """
    Applies all categorical transforms to a dataframe containing only continuous data

    :param df: pandas dataframe
    :param encoding: one option in ("ordinal", "one-hot")
    :param mode: panda series with modes of columns
    :return: pandas dataframe, list of encoding sizes
    """
    assert encoding in ENCODING, 'Encoding option not available'

    # We ensure that all columns are considered as categories
    df = CaT.fill_missing(CaT.to_category(df), mode)

    if encoding == "ordinal":
        return CaT.ordinal_encode(df)

    else:
        return CaT.one_hot_encode(df)
