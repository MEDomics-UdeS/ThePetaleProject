"""
Authors : Nicolas Raymond

This file contains the procedure to execute in order to obtain "L0_WARMUP_RAW".

"""

from os.path import join, realpath, dirname

import pandas as pd
import sys


if __name__ == '__main__':

    # Imports specific to project
    sys.path.append(dirname(dirname(dirname(realpath(__file__)))))
    from settings.paths import Paths
    from src.data.extraction.constants import *
    from src.data.extraction.data_management import initialize_petale_data_manager
    from src.data.extraction.helpers import get_missing_update
    from src.data.processing.cleaning import DataCleaner

    # We build a PetaleDataManager that will help interacting with PETALE database
    data_manager = initialize_petale_data_manager()

    # We build a data cleaner
    data_cleaner = DataCleaner(join(Paths.CLEANING_RECORDS, "WARMUP"), column_thresh=COLUMN_REMOVAL_THRESHOLD,
                               row_thresh=ROW_REMOVAL_THRESHOLD, outlier_alpha=OUTLIER_ALPHA,
                               min_n_per_cat=MIN_N_PER_CAT, max_cat_percentage=MAX_CAT_PERCENTAGE)

    # We save the variables needed from GENERALS
    GEN_vars = [PARTICIPANT, AGE, WEIGHT, DT, MVLPA, VO2R_MAX]

    # We save the variables needed from 6MWT
    SIXMWT_vars = [PARTICIPANT, TDM6_HR_END, TDM6_DIST]

    # We save a set with all the variables
    all_vars = set(GEN_vars+SIXMWT_vars)

    # We retrieve the tables needed
    gen_df = data_manager.get_table(GENERALS, GEN_vars)
    six_df = data_manager.get_table(SIXMWT, SIXMWT_vars)

    # We remove survivors with missing VO2R_MAX values
    gen_df = gen_df[~(gen_df[VO2R_MAX].isnull())]

    # We proceed to table concatenation
    complete_df = pd.merge(gen_df, six_df, on=[PARTICIPANT], how=INNER)

    # We look at the missing data
    get_missing_update(complete_df)

    # We remove rows and columns with too many missing values and stores other cleaning suggestions
    complete_df = data_cleaner(complete_df)

    # We look at the missing data
    get_missing_update(complete_df)

    # We create the dictionary needed to create the table
    types = {c: TYPES[c] for c in all_vars}

    # We make sure that the target is at the end
    types.pop(VO2R_MAX)
    types[VO2R_MAX] = TYPES[VO2R_MAX]

    # We create the RAW learning table
    data_manager.create_and_fill_table(complete_df, f"{LEARNING_0}_{RAW}", types, primary_key=[PARTICIPANT])

