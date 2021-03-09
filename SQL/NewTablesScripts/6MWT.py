"""
Author : Nicolas Raymond

This file stores the procedure to execute in order to obtain "6MWT" table in the database.
"""

from SQL.DataManager.Utils import initialize_petale_data_manager
from constants import *
import pandas as pd

if __name__ == '__main__':

    # We build a PetaleDataManager that will help interacting with PETALE database
    data_manager = initialize_petale_data_manager()

    # We save the variables needed from Cardio_4
    C4_vars = PKEY + [TDM6_DIST, TDM6_HR_END, TDM6_HR_REST, TDM6_TAS_END, TDM6_TAD_END]

    # We retrieve the table with the variables and the table with the filtered ID
    df_cardio_4 = data_manager.get_table(CARDIO_4, C4_vars)
    IDs = data_manager.get_table(ID_TABLE)

    # We only keep survivors from phase 1
    df_cardio_4 = df_cardio_4[df_cardio_4[TAG] == PHASE]
    df_cardio_4 = df_cardio_4.drop([TAG], axis=1)

    # We proceed to dataframes concatenation
    complete_df = pd.merge(IDs, df_cardio_4, on=[PARTICIPANT], how=INNER)

    # We create the dictionary needed to create the table
    types = {}
    for var in C4_vars:
        types[var] = TYPES[var]
    types.pop(TAG)

    # We create the table
    data_manager.create_and_fill_table(complete_df, SIXMWT, types, primary_key=[PARTICIPANT])

