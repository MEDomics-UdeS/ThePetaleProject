"""
Authors : Nicolas Raymond

This file contains the procedure to execute in order to obtain "L0_WARMUP and L0_WARMUP_HOLDOUT".
This table is used to reproduce 6MWT experiment with a more complex model.
"""

import argparse
import os
import sys
dir_path = os.path.dirname(os.path.realpath(__file__))
parent_dir_path = os.path.abspath(os.path.join(dir_path, os.pardir))
parent_parent = os.path.abspath(os.path.join(parent_dir_path, os.pardir))
sys.path.insert(0, parent_parent)
from Data.Sampling import split_train_test
from SQL.DataManagement.Utils import initialize_petale_data_manager
from SQL.DataManagement.Helpers import fill_id
from SQL.constants import *
from pandas import read_csv
from decimal import Decimal


def argument_parser():
    """
    This function defines a parser to enable user to easily experiment different models
    """
    # Create a parser
    parser = argparse.ArgumentParser(usage='\n python GenerateLearningTable.py [raw_table] [outliers_csv]',
                                     description="This program enables to remove participants from raw"
                                                 "learning table.")

    parser.add_argument('-rt', '--raw_table', type=str,
                        help=f"Name of the raw learning table (ex. 'L0_WARMUP')")

    parser.add_argument('-ocsv', '--outliers_csv', type=str,
                        help=f"Path of the csv file containing participant ids to remove")

    parser.add_argument('-sep', '--csv_separator', type=str, default=",",
                        help=f"Separation character used in the csv file")

    parser.add_argument('-tc', '--target_column', type=str,
                        help=f"Name of the column to use as target")

    parser.add_argument('-s', '--seed', type=int, default=SEED,
                        help=f"Seed value used to create holdout set")

    parser.add_argument('-hs', '--holdout_size', type=float, default=0.10,
                        help=f"Percentage of data to use as holdout set")

    args = parser.parse_args()

    # Print arguments
    print("\n The inputs are:")
    for arg in vars(args):
        print("{}: {}".format(arg, getattr(args, arg)))
    print("\n")

    return args


if __name__ == '__main__':

    # We build a PetaleDataManager that will help interacting with PETALE database
    data_manager = initialize_petale_data_manager()

    # We retrieve parser's arguments
    args = argument_parser()

    # We retrieve the raw table needed
    df = data_manager.get_table(args.raw_table)

    # We retrieve participant ids to remove
    outliers_ids = read_csv(args.outliers_csv, sep=args.csv_separator)
    outliers_ids[PARTICIPANT] = outliers_ids[PARTICIPANT].astype(str).apply(fill_id)

    # We remove the ids
    df = df.loc[~df[PARTICIPANT].isin(list(outliers_ids[PARTICIPANT].values)), :]

    # We extract an holdout set from the whole dataframe
    learning_df, hold_out_df = split_train_test(df, args.target_column,
                                                test_size=args.holdout_size, random_state=args.seed)

    # We create the dictionary needed to create the table
    types = {c: TYPES[c] for c in list(learning_df.columns)}

    # We create the tables
    data_manager.create_and_fill_table(learning_df, LEARNING_0, types, primary_key=[PARTICIPANT])
    data_manager.create_and_fill_table(hold_out_df, LEARNING_0_HOLDOUT, types, primary_key=[PARTICIPANT])
