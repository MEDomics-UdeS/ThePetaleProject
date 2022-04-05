"""
Filename: experiments.py

Author: Nicolas Raymond

Description: This file stores experiment functions that can be used with different datasets

Date of last modification: 2022/02/03
"""
import json

from apyori import apriori
from copy import deepcopy
from hps.fixed_hps import ENET_HPS, ENET_GGE_HPS, GATHPS, GCNHPS, MLP_HPS, RF_HPS, XGBOOST_HPS
from os import mkdir
from os.path import exists, join
from pandas import DataFrame
from settings.paths import Paths
from src.data.extraction.constants import *
from src.data.extraction.data_management import PetaleDataManager
from src.data.processing.datasets import MaskType, PetaleDataset
from src.data.processing.feature_selection import FeatureSelector
from src.data.processing.gnn_datasets import PetaleKGNNDataset
from src.data.processing.preprocessing import preprocess_for_apriori
from src.data.processing.sampling import extract_masks, GeneChoice, push_valid_to_train
from src.models.blocks.genes_signature_block import GeneEncoder, GeneGraphEncoder, GeneGraphAttentionEncoder
from src.models.gat import PetaleGATR, GATHP
from src.models.gcn import PetaleGCNR, GCNHP
from src.models.mlp import PetaleMLPR, MLPHP
from src.models.random_forest import PetaleRFR
from src.models.xgboost_ import PetaleXGBR
from src.recording.constants import PREDICTION, RECORDS_FILE, TRAIN_RESULTS, TEST_RESULTS, VALID_RESULTS
from src.recording.recording import Recorder, compare_prediction_recordings, get_evaluation_recap
from src.training.evaluation import Evaluator
from src.utils.argparsers import fixed_hps_lae_experiment_parser
from src.utils.graph import PetaleGraph, correct_and_smooth
from src.utils.results_analysis import get_apriori_statistics, print_and_save_apriori_rules
from src.utils.score_metrics import RegressionMetric, BinaryClassificationMetric, AbsoluteError, Pearson,\
    RootMeanSquaredError, SquaredError
from time import time
from torch import zeros
from tqdm import tqdm
from typing import Callable, Dict, List, Optional, Union


def run_apriori_experiment(experiment_name: str,
                           df: DataFrame,
                           target: str,
                           cat_cols: List[str],
                           masks: Dict,
                           arguments,
                           continuous_target: bool = True) -> None:
    """
    Finds association rules among a dataset, using different splits.
    First, all rules are found and saved in a json.
    Then, rules associated to a specified target variable are filtered and saved in a different directory.
    Finally, a summary of rules associated to the target is also saved in the last directory created.

    Args:
        experiment_name: str that will be used to identify directories created during the experiment
        df: pandas dataframe with the records
        target: name of the column associated to the target
        cat_cols: list of categorical columns
        masks: dictionary with idx of train, valid and test set
        arguments: arguments from the apriori argparser
        continuous_target: if True, continuous targets will be converted to classes

    Returns: None
    """
    # We save start time
    start = time()

    # We only keep categorical columns and targets
    df = df[cat_cols + [target]]

    # We save folder names for different results
    result_folder = f"{experiment_name}_apriori"
    filtered_result_folder = f"{result_folder}_{target}"
    f1, f2 = join(Paths.EXPERIMENTS_RECORDS, result_folder), join(Paths.EXPERIMENTS_RECORDS, filtered_result_folder)
    for f in [f1, f2]:
        if not exists(f):
            mkdir(f)

    for i in range(len(masks.keys())):

        # We filter the dataset to only consider training set
        df_subset = df.iloc[masks[i][MaskType.TRAIN]]

        # We preprocess data
        if continuous_target:
            records = preprocess_for_apriori(df_subset, cont_cols={target: arguments.nb_groups}, cat_cols=cat_cols)
        else:
            records = preprocess_for_apriori(df_subset, cat_cols=cat_cols + [target])

        # We print the number of records
        print(f"Number of records : {len(records)}")

        # We run apriori algorithm
        association_rules = apriori(records,
                                    min_support=arguments.min_support,
                                    min_confidence=arguments.min_confidence,
                                    min_lift=arguments.min_lift,
                                    max_length=(arguments.max_length + 1))

        association_results = list(association_rules)

        # We print the number of rules
        print(f"Number of rules : {len(association_results)}")

        # We clean results to only keep association rules of with a single item on the right side
        association_results = [rule for rule in association_results if len(list(rule.ordered_statistics[0].items_add)) < 2]

        # We sort the rules by lift
        association_results = sorted(association_results, key=lambda x: x[2][0][3], reverse=True)

        # We save a dictionary with apriori settings
        settings = {"min_support": arguments.min_support,
                    "min_confidence": arguments.min_confidence,
                    "min_lift": arguments.min_lift,
                    "max_length": arguments.max_length,
                    f"nb_{target}_groups": arguments.nb_groups}

        # We print and save all the rules
        print_and_save_apriori_rules(association_results, settings, f1, f"{result_folder}_{i}", start)

        # We print and save the rules only related to target
        temp_list = []
        for rule in association_results:
            right_part = list(rule.ordered_statistics[0].items_add)
            right_part = right_part[0]
            if right_part.split(" <")[0] == target.upper() or right_part.split(" >")[0] == target.upper():
                temp_list.append(rule)

        association_results = temp_list
        print_and_save_apriori_rules(association_results, settings, f2, f"{filtered_result_folder}_{i}", start, True)

    # We compute summary of apriori results for rules associated to target
    get_apriori_statistics(f2)


def run_correct_and_smooth_experiment(dataset: PetaleDataset,
                                      evaluation_name: str,
                                      masks: dict,
                                      metrics: Union[List[BinaryClassificationMetric], List[RegressionMetric]],
                                      path: str,
                                      r_smooth: float,
                                      r_correct: float,
                                      max_degree: Optional[int] = None,
                                      include_distances: bool = False,
                                      nb_iter: int = 1):

    # For all splits
    for k, m in tqdm(masks.items()):

        # We extract the records from folder "Split k"
        with open(join(path, f"Split_{k}", RECORDS_FILE)) as json_file:
            records_k = json.load(json_file)

        # We save the predictions made for each id
        pred = zeros((len(dataset), 1))
        for result_section in [TRAIN_RESULTS, TEST_RESULTS, VALID_RESULTS]:
            for id_, result_dict in records_k[result_section].items():
                pred[dataset.ids_to_row_idx[id_]] = float(result_dict[PREDICTION])

        # We update dataset mask
        dataset.update_masks(train_mask=m[MaskType.TRAIN],
                             test_mask=m[MaskType.TEST],
                             valid_mask=m[MaskType.VALID])

        # Recorder initialization
        recorder = Recorder(evaluation_name=evaluation_name,
                            index=k, recordings_path=Paths.EXPERIMENTS_RECORDS)

        # We build the graph
        g = PetaleGraph(dataset, include_distances=include_distances,
                        cat_cols=dataset.cat_cols, max_degree=max_degree)

        # We proceed to correction and smoothing of the predictions
        y_copy = deepcopy(dataset.y)
        cs_pred = correct_and_smooth(g, pred=pred, labels=y_copy, masks=m, r_correct=r_correct,
                                     r_smooth=r_smooth, nb_iter=nb_iter)

        for mask, masktype in [(m[MaskType.TRAIN], MaskType.TRAIN),
                               (m[MaskType.TEST], MaskType.TEST),
                               (m[MaskType.VALID], MaskType.VALID)]:
            if mask is not None:

                # We record predictions
                pred, ground_truth = cs_pred[mask], dataset.y[mask]
                recorder.record_predictions([dataset.ids[i] for i in mask], pred, ground_truth, mask_type=masktype)

                # We record scores
                for metric in metrics:
                    recorder.record_scores(score=metric(pred, ground_truth), metric=metric.name, mask_type=masktype)

        # Generation of the file with the results
        recorder.generate_file()
        compare_prediction_recordings(evaluations=[evaluation_name], split_index=k,
                                      recording_path=Paths.EXPERIMENTS_RECORDS)

    get_evaluation_recap(evaluation_name=evaluation_name, recordings_path=Paths.EXPERIMENTS_RECORDS)


def run_fixed_hps_regression_experiments(data_extraction_function: Callable,
                                         mask_path: str,
                                         experiment_id: str) -> None:
    """
    Run all the model comparisons over a dataset using fixed hps

    Returns: None
    """
    # Arguments parsing
    args = fixed_hps_lae_experiment_parser()

    # Initialization of DataManager and sampler
    manager = PetaleDataManager()

    # We extract needed data
    if args.genes_subgroup:
        genes_selection = GeneChoice.SIGNIFICANT
        gene_cols = SIGNIFICANT_CHROM_POS_OBESITY
    elif args.all_genes:
        genes_selection = GeneChoice.ALL
        gene_cols = ALL_CHROM_POS_OBESITY
    else:
        genes_selection = None
        gene_cols = None

    genes = True if genes_selection is not None else False
    df, target, cont_cols, cat_cols = data_extraction_function(data_manager=manager, genes=genes_selection)

    # Extraction of masks
    masks = extract_masks(mask_path, k=args.nb_outer_splits, l=args.nb_inner_splits)
    masks_without_val = deepcopy(masks)
    push_valid_to_train(masks_without_val)

    # Initialization of the dictionary containing the evaluation metrics
    evaluation_metrics = [AbsoluteError(), Pearson(), SquaredError(), RootMeanSquaredError()]

    # Initialization of feature selector
    if args.feature_selection:
        if genes:
            feature_selector = FeatureSelector(threshold=[0.01, 0.01],
                                               cumulative_imp=[False, False],
                                               seed=args.seed)
        else:
            feature_selector = FeatureSelector(threshold=[0.01],
                                               cumulative_imp=[False],
                                               seed=args.seed)
    else:
        feature_selector = None

    # We save the string that will help identify evaluations
    experiment_id = f"{experiment_id}_fixedhps"
    if genes:
        if args.all_genes:
            experiment_id += "_gen2"
        else:
            experiment_id += "_gen1"
    if args.enable_sam:
        experiment_id += "_sam"

    # We save the Sharpness-Aware Minimization search space
    sam_value = 0.05

    # We start a timer for the whole experiment
    first_start = time()

    """
    Random Forest experiment
    """
    if args.random_forest:

        # Start timer
        start = time()

        # Creation of dataset
        dataset = PetaleDataset(df, target, cont_cols, cat_cols, classification=False,
                                feature_selection_groups=[gene_cols])

        # Creation of the evaluator
        evaluator = Evaluator(model_constructor=PetaleRFR,
                              dataset=dataset,
                              masks=masks_without_val,
                              evaluation_name=f"RandomForest_{experiment_id}",
                              hps={},
                              n_trials=0,
                              evaluation_metrics=evaluation_metrics,
                              feature_selector=feature_selector,
                              fixed_params=RF_HPS,
                              save_hps_importance=True,
                              save_optimization_history=True,
                              seed=args.seed,
                              pred_path=args.path)

        # Evaluation
        evaluator.evaluate()

        print("Time Taken for Random Forest (minutes): ", round((time() - start) / 60, 2))

    """
    XGBoost experiment
    """
    if args.xg_boost:

        # Start timer
        start = time()

        # Creation of dataset
        dataset = PetaleDataset(df, target, cont_cols, cat_cols, classification=False,
                                feature_selection_groups=[gene_cols])

        # Creation of the evaluator
        evaluator = Evaluator(model_constructor=PetaleXGBR,
                              dataset=dataset,
                              masks=masks_without_val,
                              evaluation_name=f"XGBoost_{experiment_id}",
                              hps={},
                              n_trials=0,
                              evaluation_metrics=evaluation_metrics,
                              feature_selector=feature_selector,
                              fixed_params=XGBOOST_HPS,
                              save_hps_importance=True,
                              save_optimization_history=True,
                              seed=args.seed,
                              pred_path=args.path)

        # Evaluation
        evaluator.evaluate()

        print("Time Taken for XGBoost (minutes): ", round((time() - start) / 60, 2))

    """
    MLP experiment
    """
    if args.mlp:

        # Start timer
        start = time()

        # Creation of the dataset
        dataset = PetaleDataset(df, target, cont_cols, cat_cols, to_tensor=True,
                                classification=False, feature_selection_groups=[gene_cols])

        # Creation of function to update fixed params
        def update_fixed_params(dts):
            return {'max_epochs': 500,
                    'patience': 50,
                    'num_cont_col': len(dts.cont_idx),
                    'cat_idx': dts.cat_idx,
                    'cat_sizes': dts.cat_sizes,
                    'cat_emb_sizes': dts.cat_sizes,
                    **MLP_HPS}

        # Saving of fixed_params for MLP
        fixed_params = update_fixed_params(dataset)

        # Update of hyperparameters
        if args.enable_sam:
            MLP_HPS[MLPHP.RHO.name] = sam_value

        cat_sizes_sum = sum(dataset.cat_sizes) if dataset.cat_sizes is not None else 0
        MLP_HPS[MLPHP.N_UNIT.name] = int((len(cont_cols) + cat_sizes_sum)/2)

        # Creation of evaluator
        evaluator = Evaluator(model_constructor=PetaleMLPR,
                              dataset=dataset,
                              masks=masks,
                              evaluation_name=f"MLP_{experiment_id}",
                              hps={},
                              n_trials=0,
                              evaluation_metrics=evaluation_metrics,
                              feature_selector=feature_selector,
                              fixed_params=fixed_params,
                              fixed_params_update_function=update_fixed_params,
                              save_hps_importance=True,
                              save_optimization_history=True,
                              seed=args.seed,
                              pred_path=args.path)

        # Evaluation
        evaluator.evaluate()

        print("Time Taken for MLP (minutes): ", round((time() - start) / 60, 2))

    """
    ENET experiment
    """
    if args.enet:

        # Start timer
        start = time()

        # Creation of the dataset
        dataset = PetaleDataset(df, target, cont_cols, cat_cols,
                                to_tensor=True, classification=False,
                                feature_selection_groups=[gene_cols])

        def update_fixed_params(dts):
            return {'max_epochs': 500,
                    'patience': 50,
                    'num_cont_col': len(dts.cont_idx),
                    'cat_idx': dts.cat_idx,
                    'cat_sizes': dts.cat_sizes,
                    'cat_emb_sizes': dts.cat_sizes,
                    **ENET_HPS}

        # Saving of fixed_params for ENET
        fixed_params = update_fixed_params(dataset)

        # Update of hyperparameters
        if args.enable_sam:
            ENET_HPS[MLPHP.RHO.name] = sam_value

        # Creation of evaluator
        evaluator = Evaluator(model_constructor=PetaleMLPR,
                              dataset=dataset,
                              masks=masks,
                              evaluation_name=f"enet_{experiment_id}",
                              hps={},
                              n_trials=0,
                              evaluation_metrics=evaluation_metrics,
                              feature_selector=feature_selector,
                              fixed_params=fixed_params,
                              fixed_params_update_function=update_fixed_params,
                              save_hps_importance=True,
                              save_optimization_history=True,
                              seed=args.seed,
                              pred_path=args.path)

        # Evaluation
        evaluator.evaluate()

        print("Time Taken for ENET (minutes): ", round((time() - start) / 60, 2))

    """
    GGE experiment
    """
    if args.gge and genes:

        # Start timer
        start = time()

        # Creation of the dataset
        dataset = PetaleDataset(df, target, cont_cols, cat_cols,
                                gene_cols=gene_cols, to_tensor=True,
                                classification=False, feature_selection_groups=[gene_cols])

        def gene_encoder_constructor(gene_idx_groups: Optional[Dict[str, List[int]]],
                                     dropout: float) -> GeneEncoder:
            """
            Builds a GeneGraphEncoder

            Args:
                gene_idx_groups: dictionary where keys are names of chromosomes and values
                                 are list of idx referring to columns of genes associated to
                                 the chromosome
                dropout: dropout probability

            Returns: GeneEncoder
            """

            return GeneGraphEncoder(gene_idx_groups=gene_idx_groups,
                                    genes_emb_sharing=args.embedding_sharing,
                                    dropout=dropout,
                                    signature_size=args.signature_size)

        def update_fixed_params(dts):
            return {'max_epochs': 500,
                    'patience': 50,
                    'num_cont_col': len(dts.cont_idx),
                    'cat_idx': dts.cat_idx,
                    'cat_sizes': dts.cat_sizes,
                    'cat_emb_sizes': dts.cat_sizes,
                    'gene_idx_groups': dts.gene_idx_groups,
                    'gene_encoder_constructor': gene_encoder_constructor,
                    **ENET_GGE_HPS}

        # Saving of fixed_params for GGE + ENET
        fixed_params = update_fixed_params(dataset)

        # Update of hyperparameters
        if args.enable_sam:
            ENET_GGE_HPS[MLPHP.RHO.name] = sam_value

        # Creation of evaluator
        evaluator = Evaluator(model_constructor=PetaleMLPR,
                              dataset=dataset,
                              masks=masks,
                              evaluation_name=f"ggeEnet_{experiment_id}",
                              hps={},
                              n_trials=0,
                              evaluation_metrics=evaluation_metrics,
                              feature_selector=feature_selector,
                              fixed_params=fixed_params,
                              fixed_params_update_function=update_fixed_params,
                              save_hps_importance=True,
                              save_optimization_history=True,
                              seed=args.seed)

        # Evaluation
        evaluator.evaluate()

        print("Time Taken for GGE (minutes): ", round((time() - start) / 60, 2))

    """
    GGAE experiment
    """
    if args.ggae and genes:

        # Start timer
        start = time()

        # Creation of the dataset
        dataset = PetaleDataset(df, target, cont_cols, cat_cols,
                                gene_cols=gene_cols, to_tensor=True,
                                classification=False, feature_selection_groups=[gene_cols])

        def gene_encoder_constructor(gene_idx_groups: Optional[Dict[str, List[int]]],
                                     dropout: float) -> GeneEncoder:
            """
            Builds a GeneGraphAttentionEncoder

            Args:
                gene_idx_groups: dictionary where keys are names of chromosomes and values
                                 are list of idx referring to columns of genes associated to
                                 the chromosome
                dropout: dropout probability

            Returns: GeneEncoder
            """

            return GeneGraphAttentionEncoder(gene_idx_groups=gene_idx_groups,
                                             genes_emb_sharing=args.embedding_sharing,
                                             dropout=dropout,
                                             signature_size=args.signature_size)

        def update_fixed_params(dts):
            return {'max_epochs': 500,
                    'patience': 50,
                    'num_cont_col': len(dts.cont_idx),
                    'cat_idx': dts.cat_idx,
                    'cat_sizes': dts.cat_sizes,
                    'cat_emb_sizes': dts.cat_sizes,
                    'gene_idx_groups': dts.gene_idx_groups,
                    'gene_encoder_constructor': gene_encoder_constructor,
                    **ENET_GGE_HPS}

        # Saving of fixed_params for GGAE + ENET
        fixed_params = update_fixed_params(dataset)

        # Update of hyperparameters
        if args.enable_sam:
            ENET_GGE_HPS[MLPHP.RHO.name] = sam_value

        # Creation of evaluator
        evaluator = Evaluator(model_constructor=PetaleMLPR,
                              dataset=dataset,
                              masks=masks,
                              evaluation_name=f"ggaeEnet_{experiment_id}",
                              hps={},
                              n_trials=0,
                              evaluation_metrics=evaluation_metrics,
                              feature_selector=feature_selector,
                              fixed_params=fixed_params,
                              fixed_params_update_function=update_fixed_params,
                              save_hps_importance=True,
                              save_optimization_history=True,
                              seed=args.seed)

        # Evaluation
        evaluator.evaluate()

        print("Time Taken for GGAE (minutes): ", round((time() - start) / 60, 2))

    """
    GAT experiment
    """
    if args.gat:

        # Start timer
        start = time()

        for nb_neighbor in args.degree:

            # We change the type from str to int
            nb_neighbor = int(nb_neighbor)

            # We set the conditional column
            cond_cat_col = SEX if args.conditional_column else None

            # We set the distance computations options
            GAT_options = [("", False)] if not args.weighted_similarity else [("", False), ("w", True)]

            for prefix, w_sim in GAT_options:

                dataset = PetaleKGNNDataset(df, target, k=nb_neighbor,
                                            weighted_similarity=w_sim,
                                            cont_cols=cont_cols, cat_cols=cat_cols,
                                            conditional_cat_col=cond_cat_col,
                                            classification=False, feature_selection_groups=[gene_cols])

                # Creation of function to update fixed params
                def update_fixed_params(dts):
                    return {'num_cont_col': len(dts.cont_idx),
                            'cat_idx': dts.cat_idx,
                            'cat_sizes': dts.cat_sizes,
                            'cat_emb_sizes': dts.cat_sizes,
                            'max_epochs': 500,
                            'patience': 50,
                            **GATHPS}

                # Saving of original fixed params for GAT
                fixed_params = update_fixed_params(dataset)

                # Update of hyperparameters
                if args.enable_sam:
                    GATHPS[GATHP.RHO.name] = sam_value

                # Creation of the evaluator
                evaluator = Evaluator(model_constructor=PetaleGATR,
                                      dataset=dataset,
                                      masks=masks,
                                      evaluation_name=f"{prefix}GAT{nb_neighbor}_{experiment_id}",
                                      hps=GATHPS,
                                      n_trials=0,
                                      evaluation_metrics=evaluation_metrics,
                                      fixed_params=fixed_params,
                                      fixed_params_update_function=update_fixed_params,
                                      feature_selector=feature_selector,
                                      save_hps_importance=True,
                                      save_optimization_history=True,
                                      seed=args.seed,
                                      pred_path=args.path)

                # Evaluation
                evaluator.evaluate()

        print("Time Taken for GAT (minutes): ", round((time() - start) / 60, 2))

    """
    GCN experiment
    """
    if args.gcn:

        # Start timer
        start = time()

        for nb_neighbor in args.degree:

            # We change the type from str to int
            nb_neighbor = int(nb_neighbor)

            # We set the conditional column
            cond_cat_col = SEX if args.conditional_column else None

            # We set the distance computations options
            GCN_options = [("", False)] if not args.weighted_similarity else [("", False), ("w", True)]

            for prefix, w_sim in GCN_options:

                # Creation of the dataset
                dataset = PetaleKGNNDataset(df, target, k=nb_neighbor,
                                            weighted_similarity=w_sim,
                                            cont_cols=cont_cols, cat_cols=cat_cols,
                                            conditional_cat_col=cond_cat_col,
                                            classification=False, feature_selection_groups=[gene_cols])

                # Creation of function to update fixed params
                def update_fixed_params(dts):
                    return {'num_cont_col': len(dts.cont_idx),
                            'cat_idx': dts.cat_idx,
                            'cat_sizes': dts.cat_sizes,
                            'cat_emb_sizes': dts.cat_sizes,
                            'max_epochs': 500,
                            'patience': 50,
                            **GCNHPS}

                # Saving of original fixed params for GCN
                fixed_params = update_fixed_params(dataset)

                # Update of hyperparameters
                if args.enable_sam:
                    GCNHPS[GCNHP.RHO.name] = sam_value

                # Creation of the evaluator
                evaluator = Evaluator(model_constructor=PetaleGCNR,
                                      dataset=dataset,
                                      masks=masks,
                                      evaluation_name=f"{prefix}GCN{nb_neighbor}_{experiment_id}",
                                      hps=GCNHPS,
                                      n_trials=0,
                                      evaluation_metrics=evaluation_metrics,
                                      fixed_params=fixed_params,
                                      fixed_params_update_function=update_fixed_params,
                                      feature_selector=feature_selector,
                                      save_hps_importance=True,
                                      save_optimization_history=True,
                                      seed=args.seed,
                                      pred_path=args.path)

                # Evaluation
                evaluator.evaluate()

        print("Time Taken for GCN (minutes): ", round((time() - start) / 60, 2))

    print("Overall time (minutes): ", round((time() - first_start) / 60, 2))
