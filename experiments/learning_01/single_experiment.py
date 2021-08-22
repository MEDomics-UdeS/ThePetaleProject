"""
This file consists of all the experiments made on the l1 dataset
"""
from os.path import dirname, realpath, join
from copy import deepcopy
import sys
import argparse
import time


def argument_parser():
    """
    This function defines a parser that enables user to easily run different experiments
    """
    # Create a parser
    parser = argparse.ArgumentParser(usage='\n python3 full_experiment.py',
                                     description="Runs all the experiments associated to the l1 dataset")

    # Nb inner split and nb outer split selection
    parser.add_argument('-k', '--nb_outer_splits', type=int, default=5,
                        help='Number of outer splits during the models evaluations')
    parser.add_argument('-l', '--nb_inner_splits', type=int, default=5,
                        help='Number of inner splits during the models evaluations')

    # Features selection
    parser.add_argument('-base', '--baselines', default=False, action='store_true',
                        help='True if we want to add baselines features into dataset')
    parser.add_argument('-comp', '--complication', type=str, default='bone',
                        choices=['bone', 'cardio', 'neuro', 'all'],
                        help='Choices of health complication to predict')
    parser.add_argument('-gen', '--genes', nargs='*', type=str, default=[None, 'significant', 'all'],
                        help="Selection of genes to incorporate into the dataset")
    parser.add_argument('-f', '--feature_selection', default=False, action='store_true',
                        help='True if we want to proceed to feature selection')

    # Models selection
    parser.add_argument('-han', '--han', default=False, action='store_true',
                        help='True if we want to run heterogeneous graph attention network experiments')
    parser.add_argument('-logit', '--logistic_regression', default=False, action='store_true',
                        help='True if we want to run logistic regression experiments')
    parser.add_argument('-mlp', '--mlp', default=False, action='store_true',
                        help='True if we want to run mlp experiments')
    parser.add_argument('-rf', '--random_forest', default=False, action='store_true',
                        help='True if we want to run random forest experiments')
    parser.add_argument('-xg', '--xg_boost', default=False, action='store_true',
                        help='True if we want to run xgboost experiments')
    parser.add_argument('-tab', '--tabnet', default=False, action='store_true',
                        help='True if we want to run TabNet experiments')

    # Seed
    parser.add_argument('-seed', '--seed', type=int, default=SEED, help='Seed to use during model evaluations')

    arguments = parser.parse_args()

    # Print arguments
    print("\nThe inputs are:")
    for arg in vars(arguments):
        print("{}: {}".format(arg, getattr(arguments, arg)))
    print("\n")

    return arguments


if __name__ == '__main__':

    # Imports specific to project
    sys.path.append(dirname(dirname(dirname(realpath(__file__)))))
    from hps.l1_hps import TAB_HPS, RF_HPS, HAN_HPS, MLP_HPS, LOGIT_HPS, XGBOOST_HPS
    from settings.paths import Paths
    from src.data.processing.datasets import PetaleDataset, PetaleStaticGNNDataset
    from src.data.processing.feature_selection import FeatureSelector
    from src.data.processing.sampling import get_learning_one_data, extract_masks, push_valid_to_train
    from src.models.han import PetaleBinaryHANC
    from src.models.mlp import PetaleBinaryMLPC
    from src.models.tabnet import PetaleBinaryTNC
    from src.models.random_forest import PetaleBinaryRFC
    from src.models.xgboost_ import PetaleBinaryXGBC
    from src.training.evaluation import Evaluator
    from src.data.extraction.constants import *
    from src.data.extraction.data_management import PetaleDataManager
    from src.utils.score_metrics import AUC, BinaryAccuracy, BinaryBalancedAccuracy, \
        BalancedAccuracyEntropyRatio, Sensitivity, Specificity, Reduction

    # Arguments parsing
    args = argument_parser()

    # Extraction of complication choice
    complication = args.complication
    if complication == 'bone':
        complication = BONE_COMPLICATIONS
        mask_file = 'l1_bone_mask.json'

    elif complication == 'cardio':
        complication = CARDIOMETABOLIC_COMPLICATIONS
        mask_file = 'l1_cardio_mask.json'

    elif complication == 'neuro':
        complication = NEUROCOGNITIVE_COMPLICATIONS
        mask_file = 'l1_neuro_mask.json'
    else:
        complication = COMPLICATIONS
        mask_file = 'l1_general_mask.json'

    # Extraction of genes choices
    genes_choices = args.genes

    # Initialization of DataManager and sampler
    manager = PetaleDataManager("rayn2402")

    # We extract data for each selection of gene
    data_dict = {}
    for gene in genes_choices:
        df, cont_cols, cat_cols = get_learning_one_data(manager, baselines=args.baselines,
                                                        genes=gene, complications=[complication])
        data_dict[gene] = (df, cont_cols, cat_cols)

    # Extraction of masks
    masks = extract_masks(join(Paths.MASKS, mask_file), k=args.nb_outer_splits, l=args.nb_inner_splits)
    masks_without_val = deepcopy(masks)
    push_valid_to_train(masks_without_val)

    # Initialization of the dictionary containing the evaluation metrics
    evaluation_metrics = [AUC(), BinaryAccuracy(), BinaryBalancedAccuracy(),
                          BinaryBalancedAccuracy(Reduction.GEO_MEAN),
                          Sensitivity(), Specificity(),
                          BalancedAccuracyEntropyRatio(Reduction.GEO_MEAN)]

    # Initialization of feature selector
    if args.feature_selection:
        feature_selector = FeatureSelector(0.95)
    else:
        feature_selector = None

    # We start a timer for the whole experiment
    first_start = time.time()

    for gene in genes_choices:

        gene_start = time.time()

        """
        TabNet experiment
        """
        if args.tabnet:

            # Start timer
            start = time.time()

            # Creation of dataset
            df, cont_cols, cat_cols = data_dict[gene]
            dts = PetaleDataset(df, complication, cont_cols, cat_cols)

            # Saving of original fixed params for TabNet
            def update_fixed_params(subset):
                return {'cat_idx': subset.cat_idx, 'cat_sizes': subset.cat_sizes,
                        'cat_emb_sizes': subset.cat_sizes, 'max_epochs': 300, 'beta': 0.8,
                        'patience': 100, 'lr': 0.01, 'batch_size': 36, 'n_steps': 5,
                        'n_d': 4, 'n_a': 4, 'gamma': 1.5, 'weight': 0.50}

            fixed_params = update_fixed_params(dts)

            # Creation of the evaluator
            evaluator = Evaluator(model_constructor=PetaleBinaryTNC, dataset=dts,
                                  evaluation_name=f"L1_TabNet_{args.complication}_{gene}_no_tuning_"
                                                  f"{args.feature_selection}",
                                  masks=masks, hps=TAB_HPS, n_trials=0, fixed_params=fixed_params,
                                  fixed_params_update_function=update_fixed_params,
                                  feature_selector=feature_selector,
                                  evaluation_metrics=evaluation_metrics,
                                  save_hps_importance=True, save_optimization_history=True)

            # Evaluation
            evaluator.nested_cross_valid()

            print("Time Taken for TabNet (minutes): ", round((time.time() - start) / 60, 2))

        """
        Random Forest experiment
        """
        if args.random_forest:

            # Start timer
            start = time.time()

            # Creation of dataset
            df, cont_cols, cat_cols = data_dict[gene]
            dataset = PetaleDataset(df, complication, cont_cols, cat_cols)

            # Saving of original fixed params
            fixed_params = {'n_estimators': 3000, 'max_samples': 0.8, 'max_depth': 5, 'weight': 0.50}

            # Creation of the evaluator
            evaluator = Evaluator(model_constructor=PetaleBinaryRFC, dataset=dataset, masks=masks_without_val,
                                  evaluation_name=f"L1_RandomForest_{args.complication}_{gene}_no_tuning_"
                                                  f"{args.feature_selection}",
                                  hps=RF_HPS, n_trials=0, fixed_params=fixed_params,
                                  evaluation_metrics=evaluation_metrics, feature_selector=feature_selector,
                                  save_hps_importance=True, save_optimization_history=True)

            # Evaluation
            evaluator.nested_cross_valid()

            print("Time Taken for Random Forest (minutes): ", round((time.time() - start) / 60, 2))

        """
        XGBoost experiment
        """
        if args.xg_boost:

            # Start timer
            start = time.time()

            # Creation of dataset
            df, cont_cols, cat_cols = data_dict[gene]
            dataset = PetaleDataset(df, complication, cont_cols, cat_cols)

            # Saving of fixed params
            fixed_params = {'max_depth': 6, 'lr': 0.01, 'weight': 0.50}

            # Creation of the evaluator
            evaluator = Evaluator(model_constructor=PetaleBinaryXGBC, dataset=dataset, masks=masks_without_val,
                                  evaluation_name=f"L1_XGBoost_{args.complication}_{gene}_no_tuning_"
                                                  f"{args.feature_selection}",
                                  hps=XGBOOST_HPS, n_trials=0, fixed_params=fixed_params,
                                  evaluation_metrics=evaluation_metrics, feature_selector=feature_selector,
                                  save_hps_importance=True, save_optimization_history=True)

            # Evaluation
            evaluator.nested_cross_valid()

            print("Time Taken for XGBoost (minutes): ", round((time.time() - start) / 60, 2))

        """
        MLP experiment
        """
        if args.mlp:

            # Start timer
            start = time.time()

            # Creation of the dataset
            df, cont_cols, cat_cols = data_dict[gene]
            dts = PetaleDataset(df, complication, cont_cols, cat_cols, to_tensor=True)

            # Creation of function to update fixed params
            def update_fixed_params(subset):
                return {'max_epochs': 500, 'patience': 50, 'num_cont_col': len(subset.cont_cols),
                        'cat_idx': subset.cat_idx, 'cat_sizes': subset.cat_sizes,
                        'cat_emb_sizes': subset.cat_sizes, 'n_layer': 3, 'n_unit': 5,
                        'activation': "PReLU", 'alpha': 0.5, 'beta': 0.5, 'lr': 0.01,
                        'batch_size': 36, 'weight': 0.50}

            fixed_params = update_fixed_params(dts)

            # Creation of evaluator
            evaluator = Evaluator(model_constructor=PetaleBinaryMLPC, dataset=dts, masks=masks,
                                  evaluation_name=f"L1_MLP_{args.complication}_{gene}_no_tuning_"
                                                  f"{args.feature_selection}",
                                  hps=MLP_HPS, n_trials=0, evaluation_metrics=evaluation_metrics,
                                  feature_selector=feature_selector, fixed_params=fixed_params,
                                  fixed_params_update_function=update_fixed_params,
                                  save_hps_importance=True, save_optimization_history=True)

            # Evaluation
            evaluator.nested_cross_valid()

            print("Time Taken for MLP (minutes): ", round((time.time() - start) / 60, 2))

        """
        Logistic regression experiment
        """
        if args.logistic_regression:

            # Start timer
            start = time.time()

            # Creation of the dataset
            df, cont_cols, cat_cols = data_dict[gene]
            dts = PetaleDataset(df, complication, cont_cols, cat_cols, to_tensor=True)

            # Creation of function to update fixed params
            def update_fixed_params(subset):
                return {'max_epochs': 50, 'patience': 200, 'num_cont_col': len(subset.cont_cols),
                        'cat_idx': subset.cat_idx, 'cat_sizes': subset.cat_sizes,
                        'cat_emb_sizes': subset.cat_sizes, 'n_layer': 0, 'n_unit': 5,
                        'activation': "PReLU", 'alpha': 0, 'beta': 0, 'lr': 0.05,
                        'batch_size': 36, 'weight': 0.50}

            fixed_params = update_fixed_params(dts)

            # Creation of evaluator
            evaluator = Evaluator(model_constructor=PetaleBinaryMLPC, dataset=dts, masks=masks_without_val,
                                  evaluation_name=f"L1_Logit_{args.complication}_{gene}_no_tuning_"
                                                  f"{args.feature_selection}",
                                  hps=LOGIT_HPS, n_trials=0, evaluation_metrics=evaluation_metrics,
                                  feature_selector=feature_selector, fixed_params=fixed_params,
                                  fixed_params_update_function=update_fixed_params,
                                  save_hps_importance=True, save_optimization_history=True)

            # Evaluation
            evaluator.nested_cross_valid()

            print("Time Taken for Logistic Regression (minutes): ", round((time.time() - start) / 60, 2))

        """
        HAN experiment
        """
        if args.han:

            # Start timer
            start = time.time()

            # Creation of the dataset
            df, cont_cols, cat_cols = data_dict[gene]
            dts = PetaleStaticGNNDataset(df, complication, cont_cols, cat_cols)

            # Saving of fixed params
            def update_fixed_params(subset):
                return {'meta_paths': subset.get_metapaths(), 'in_size': len(subset.cont_cols),
                        'max_epochs': 250, 'patience': 25, 'hidden_size': 15, 'alpha': 0.5, 'beta': 0.5,
                        'num_heads': 10, 'lr': 0.01, 'batch_size': 36, 'weight': 0.50}

            fixed_params = update_fixed_params(dts)

            # Creation of the evaluator
            evaluator = Evaluator(model_constructor=PetaleBinaryHANC, dataset=dts, masks=masks,
                                  evaluation_name=f"L1_HAN_{args.complication}_{gene}_no_tuning_"
                                                  f"{args.feature_selection}",
                                  hps=HAN_HPS, n_trials=0, evaluation_metrics=evaluation_metrics,
                                  fixed_params=fixed_params, feature_selector=feature_selector,
                                  fixed_params_update_function=update_fixed_params,
                                  save_hps_importance=True, save_optimization_history=True)

            # Evaluation
            evaluator.nested_cross_valid()

            print("Time Taken for HAN (minutes): ", round((time.time() - start) / 60, 2))

        print(f"\nTime Taken for Genes = {gene}  (minutes): ", round((time.time() - gene_start) / 60, 2), "\n")

    print("Overall time (minutes): ", round((time.time() - first_start) / 60, 2))
