"""
Author : Nicolas Raymond

This file contains the procedure to create the tables containing details on SNPs significantly associated to
cardiorespiratory fitness.

"""

from SQL.DataManager.Utils import initialize_petale_data_manager
from pandas import read_csv
from constants import SIGNIFICANT_COMMON_SNPS_ID, GENES, SNPS_ID, SNP_POSITION, CHROM, TYPES
import os

COL = {GENES: TYPES[GENES], SNPS_ID: TYPES[SNPS_ID], CHROM: TYPES[CHROM], SNP_POSITION: TYPES[SNP_POSITION]}
DIR = "csv_files"
EXT = "csv"
SEP = ","

if __name__ == '__main__':

    # We create a data manager
    dm = initialize_petale_data_manager()

    # We build the pandas dataframe
    df = read_csv(os.path.join(DIR, f"{SIGNIFICANT_COMMON_SNPS_ID}.{EXT}"), sep=SEP)

    # We remove duplicate rows
    df = df.drop_duplicates()

    # We create and fill the table in the database
    dm.create_and_fill_table(df, SIGNIFICANT_COMMON_SNPS_ID, COL)



