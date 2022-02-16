"""
Filename: full_experiment.py

Authors: Nicolas Raymond

Description: This file is used to execute all the model comparisons
             made on the warmup dataset

Date of last modification : 2022/01/25
"""
import sys
import argparse
import time

from os.path import dirname, realpath
from copy import deepcopy
from typing import Dict, List, Optional


def argument_parser():
    """
    This function defines a parser that enables user to easily run different experiments
    """
    # Create a parser
    parser = argparse.ArgumentParser(usage='\n python full_experiment.py',
                                     description="Runs all the experiments associated to the warmup dataset")

    # Nb inner split and nb outer split selection
    parser.add_argument('-k', '--nb_outer_splits', type=int, default=10,
                        help='Number of outer splits during the models evaluations')
    parser.add_argument('-l', '--nb_inner_splits', type=int, default=10,
                        help='Number of inner splits during the models evaluations')

    # Features selection
    parser.add_argument('-b', '--baselines', default=False, action='store_true',
                        help='True if we want to include variables from the original equation')
    parser.add_argument('-r_w', '--remove_walk_variables', default=False, action='store_true',
                        help='True if we want to remove six minutes walk test variables from baselines'
                             '(only applies if baselines are included')
    parser.add_argument('-gen1', '--genes_subgroup', default=False, action='store_true',
                        help='True if we want to include genes if features')
    parser.add_argument('-gen2', '--all_genes', default=False, action='store_true',
                        help='True if we want to include genes if features')
    parser.add_argument('-f', '--feature_selection', default=False, action='store_true',
                        help='True if we want to apply automatic feature selection')
    parser.add_argument('-s', '--sex', default=False, action='store_true',
                        help='True if we want to include sex in features')

    # Genes encoding
    parser.add_argument('-share', '--embedding_sharing', default=False, action='store_true',
                        help='True if we want to use a single entity embedding layer for all genes'
                             ' (currently only applies with genomic signature creation')

    # Models selection
    parser.add_argument('-han_e', '--han_with_encoding', default=False, action='store_true',
                        help='True if we want to run HAN experiment with single layered pre-encoder')
    parser.add_argument('-han', '--han', default=False, action='store_true',
                        help='True if we want to run heterogeneous graph attention network experiment')
    parser.add_argument('-enet', '--enet', default=False, action='store_true',
                        help='True if we want to enet experiment')
    parser.add_argument('-mlp', '--mlp', default=False, action='store_true',
                        help='True if we want to run mlp experiment')
    parser.add_argument('-rf', '--random_forest', default=False, action='store_true',
                        help='True if we want to run random forest experiment')
    parser.add_argument('-xg', '--xg_boost', default=False, action='store_true',
                        help='True if we want to run xgboost experiment')
    parser.add_argument('-tab', '--tabnet', default=False, action='store_true',
                        help='True if we want to run TabNet experiment')
    parser.add_argument('-gge', '--gge', default=False, action='store_true',
                        help='True if we want to run GeneGraphEncoder with enet experiment')
    parser.add_argument('-ggae', '--ggae', default=False, action='store_true',
                        help='True if we want to run GeneGraphAttentionEncoder with enet experiment')

    # Self supervised learning experiment with GeneGraphAttentionEncoder
    parser.add_argument('-ssl_ggae', '-ssl_ggae', default=False, action='store_true',
                        help='True if we want to run self supervised learning with the GeneGraphAttentionEncoder')

    # Activation of sharpness-aware minimization
    parser.add_argument('-sam', '--enable_sam', default=False, action='store_true',
                        help='True if we want to use Sharpness-Aware Minimization Optimizer')

    # Activation of self supervised learning
    # parser.add_argument('-pre_training', '--pre_training', default=False, action='store_true',
    #                    help='True if we want to apply pre self supervised training to model'
    #                         'where it is enabled. Currently available for ENET with genes encoding')

    # Usage of predictions from another experiment
    parser.add_argument('-p', '--path', type=str, default=None,
                        help='Path leading to predictions of another model, will only be used by HAN if specified')

    # Seed
    parser.add_argument('-seed', '--seed', type=int, default=1010710, help='Seed used during model evaluations')

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
    from hps.warmup_hps import TAB_HPS, RF_HPS, HAN_HPS, MLP_HPS, ENET_HPS, XGBOOST_HPS, GGEHPS
    from settings.paths import Paths
    from src.data.processing.datasets import PetaleDataset, PetaleStaticGNNDataset
    from src.data.processing.feature_selection import FeatureSelector
    from src.data.processing.sampling import extract_masks, GeneChoice, get_warmup_data, push_valid_to_train
    from src.models.blocks.genes_signature_block import GeneEncoder, GeneGraphEncoder, GeneGraphAttentionEncoder
    from src.models.blocks.mlp_blocks import MLPEncodingBlock
    from src.models.gge import PetaleGGE
    from src.models.han import PetaleHANR, HanHP
    from src.models.mlp import PetaleMLPR, MLPHP
    from src.models.tabnet import PetaleTNR
    from src.models.random_forest import PetaleRFR
    from src.models.xgboost_ import PetaleXGBR
    from src.training.evaluation import Evaluator
    from src.data.extraction.constants import *
    from src.data.extraction.data_management import PetaleDataManager
    from src.utils.hyperparameters import Range
    from src.utils.score_metrics import AbsoluteError, Pearson, RootMeanSquaredError, SquaredError

    # Arguments parsing
    args = argument_parser()

    # Initialization of DataManager and sampler
    manager = PetaleDataManager()

    # We extract needed data
    if args.genes_subgroup:
        genes_selection = GeneChoice.SIGNIFICANT
        gene_cols = SIGNIFICANT_CHROM_POS_WARMUP
    elif args.all_genes:
        genes_selection = GeneChoice.ALL
        gene_cols = ALL_CHROM_POS_WARMUP
    else:
        genes_selection = None
        gene_cols = None

    genes = True if genes_selection is not None else False
    df, target, cont_cols, cat_cols = get_warmup_data(manager,
                                                      baselines=args.baselines,
                                                      genes=genes_selection,
                                                      sex=args.sex)
    # We filter variables if needed
    if args.baselines and args.remove_walk_variables:
        df.drop([TDM6_HR_END, TDM6_DIST], axis=1, inplace=True)
        cont_cols = [c for c in cont_cols if c not in [TDM6_HR_END, TDM6_DIST]]

    # Extraction of masks
    masks = extract_masks(Paths.WARMUP_MASK, k=args.nb_outer_splits, l=args.nb_inner_splits)
    gnn_masks = extract_masks(Paths.WARMUP_MASK, k=args.nb_outer_splits, l=args.nb_inner_splits)
    masks_without_val = deepcopy(masks)
    push_valid_to_train(masks_without_val)

    # Initialization of the dictionary containing the evaluation metrics
    evaluation_metrics = [AbsoluteError(), Pearson(), SquaredError(), RootMeanSquaredError()]

    # Initialization of feature selector
    if args.feature_selection:
        feature_selector = FeatureSelector(importance_threshold=0.90, seed=args.seed)
    else:
        feature_selector = None

    # We save the string that will help identify evaluations
    eval_id = ""
    if args.baselines:
        eval_id += "_baselines"
        if args.remove_walk_variables:
            eval_id += "_nw"
    if genes:
        if args.all_genes:
            eval_id += "_gen2"
        else:
            eval_id += "_gen1"
    if args.sex:
        eval_id += "_sex"
    if args.enable_sam:
        eval_id += "_sam"

    # We save the Sharpness-Aware Minimization search space
    sam_search_space = {Range.MIN: 0.05, Range.MAX: 2}

    # We start a timer for the whole experiment
    first_start = time.time()

    """
    TabNet experiment
    """
    if args.tabnet:

        # Start timer
        start = time.time()

        # Creation of dataset
        dataset = PetaleDataset(df, target, cont_cols, cat_cols, classification=False)

        # Creation of function to update fixed params
        def update_fixed_params(dts):
            if len(dts.cat_idx) != 0:
                return {'cat_idx': dts.cat_idx,
                        'cat_sizes': dts.cat_sizes,
                        'cat_emb_sizes': dts.cat_sizes,
                        'max_epochs': 250,
                        'patience': 50}
            else:
                return {'cat_idx': [],
                        'cat_sizes': [],
                        'cat_emb_sizes': [],
                        'max_epochs': 250,
                        'patience': 50}

        # Saving of original fixed params for TabNet
        fixed_params = update_fixed_params(dataset)

        # Creation of the evaluator
        evaluator = Evaluator(model_constructor=PetaleTNR, dataset=dataset,
                              evaluation_name=f"TabNet_warmup{eval_id}",
                              masks=masks, hps=TAB_HPS,
                              n_trials=200,
                              fixed_params=fixed_params,
                              fixed_params_update_function=update_fixed_params,
                              feature_selector=feature_selector,
                              evaluation_metrics=evaluation_metrics,
                              save_hps_importance=True,
                              save_optimization_history=True,
                              seed=args.seed)

        # Evaluation
        evaluator.evaluate()

        print("Time Taken for TabNet (minutes): ", round((time.time() - start) / 60, 2))

    """
    Random Forest experiment
    """
    if args.random_forest:

        # Start timer
        start = time.time()

        # Creation of dataset
        dataset = PetaleDataset(df, target, cont_cols, cat_cols, classification=False)

        # Creation of the evaluator
        evaluator = Evaluator(model_constructor=PetaleRFR,
                              dataset=dataset,
                              masks=masks_without_val,
                              evaluation_name=f"RandomForest_warmup{eval_id}",
                              hps=RF_HPS,
                              n_trials=200,
                              evaluation_metrics=evaluation_metrics,
                              feature_selector=feature_selector,
                              save_hps_importance=True,
                              save_optimization_history=True,
                              seed=args.seed)

        # Evaluation
        evaluator.evaluate()

        print("Time Taken for Random Forest (minutes): ", round((time.time() - start) / 60, 2))

    """
    XGBoost experiment
    """
    if args.xg_boost:

        # Start timer
        start = time.time()

        # Creation of dataset
        dataset = PetaleDataset(df, target, cont_cols, cat_cols, classification=False)

        # Creation of the evaluator
        evaluator = Evaluator(model_constructor=PetaleXGBR,
                              dataset=dataset,
                              masks=masks_without_val,
                              evaluation_name=f"XGBoost_warmup{eval_id}",
                              hps=XGBOOST_HPS,
                              n_trials=200,
                              evaluation_metrics=evaluation_metrics,
                              feature_selector=feature_selector,
                              save_hps_importance=True,
                              save_optimization_history=True,
                              seed=args.seed)

        # Evaluation
        evaluator.evaluate()

        print("Time Taken for XGBoost (minutes): ", round((time.time() - start) / 60, 2))

    """
    MLP experiment
    """
    if args.mlp:

        # Start timer
        start = time.time()

        # Creation of the dataset
        dataset = PetaleDataset(df, target, cont_cols, cat_cols, to_tensor=True, classification=False)

        # Creation of function to update fixed params
        def update_fixed_params(dts):
            nb_cont_col = len(dts.cont_cols) if dts.cont_cols is not None else 0
            return {'max_epochs': 250,
                    'patience': 50,
                    'num_cont_col': nb_cont_col,
                    'cat_idx': dts.cat_idx,
                    'cat_sizes': dts.cat_sizes,
                    'cat_emb_sizes': dts.cat_sizes}

        # Saving of fixed_params for MLP
        fixed_params = update_fixed_params(dataset)

        # Update of hyperparameters
        if args.enable_sam:
            MLP_HPS[MLPHP.RHO.name] = sam_search_space

        # Creation of evaluator
        evaluator = Evaluator(model_constructor=PetaleMLPR,
                              dataset=dataset,
                              masks=masks,
                              evaluation_name=f"MLP_warmup{eval_id}",
                              hps=MLP_HPS,
                              n_trials=200,
                              evaluation_metrics=evaluation_metrics,
                              feature_selector=feature_selector,
                              fixed_params=fixed_params,
                              fixed_params_update_function=update_fixed_params,
                              save_hps_importance=True,
                              save_optimization_history=True,
                              seed=args.seed)

        # Evaluation
        evaluator.evaluate()

        print("Time Taken for MLP (minutes): ", round((time.time() - start) / 60, 2))

    """
    ENET experiment
    """
    if args.enet:

        # Start timer
        start = time.time()

        # Creation of the dataset
        dataset = PetaleDataset(df, target, cont_cols, cat_cols,
                                to_tensor=True, classification=False)

        # Creation of function to update fixed params
        max_e = 200 if genes else 50

        def update_fixed_params(dts):
            nb_cont_col = len(dts.cont_cols) if dts.cont_cols is not None else 0
            return {'max_epochs': max_e,
                    'patience': 25,
                    'num_cont_col': nb_cont_col,
                    'cat_idx': dts.cat_idx,
                    'cat_sizes': dts.cat_sizes,
                    'cat_emb_sizes': dts.cat_sizes}


        # Saving of fixed_params for ENET
        fixed_params = update_fixed_params(dataset)

        # Update of hyperparameters
        if args.enable_sam:
            ENET_HPS[MLPHP.RHO.name] = sam_search_space

        # Creation of evaluator
        m = masks_without_val if not genes else masks
        evaluator = Evaluator(model_constructor=PetaleMLPR,
                              dataset=dataset,
                              masks=m,
                              evaluation_name=f"enet_warmup{eval_id}",
                              hps=ENET_HPS,
                              n_trials=200,
                              evaluation_metrics=evaluation_metrics,
                              feature_selector=feature_selector,
                              fixed_params=fixed_params,
                              fixed_params_update_function=update_fixed_params,
                              save_hps_importance=True,
                              save_optimization_history=True,
                              seed=args.seed)

        # Evaluation
        evaluator.evaluate()

        print("Time Taken for ENET (minutes): ", round((time.time() - start) / 60, 2))

    """
    GeneEncoding experiment
    """
    if args.gge and genes:

        # Start timer
        start = time.time()

        # Creation of the dataset
        dataset = PetaleDataset(df, target, cont_cols, cat_cols,
                                gene_cols=gene_cols, to_tensor=True, classification=False)

        def gene_encoder_constructor(gene_idx_groups: Optional[Dict[str, List[int]]]) -> GeneEncoder:
            """
            Builds a GeneGraphEncoder

            Args:
                gene_idx_groups: dictionary where keys are names of chromosomes and values
                                 are list of idx referring to columns of genes associated to
                                 the chromosome

            Returns: GeneEncoder
            """

            return GeneGraphEncoder(gene_idx_groups=gene_idx_groups,
                                    genes_emb_sharing=args.embedding_sharing,
                                    signature_size=3)

        def update_fixed_params(dts):
            nb_cont_col = len(dts.cont_cols) if dts.cont_cols is not None else 0
            return {'max_epochs': 200,
                    'patience': 25,
                    'num_cont_col': nb_cont_col,
                    'cat_idx': dts.cat_idx,
                    'cat_sizes': dts.cat_sizes,
                    'cat_emb_sizes': dts.cat_sizes,
                    'gene_idx_groups': dts.gene_idx_groups,
                    'gene_encoder_constructor': gene_encoder_constructor}


        # Saving of fixed_params for GGE + ENET
        fixed_params = update_fixed_params(dataset)

        # Update of hyperparameters
        if args.enable_sam:
            ENET_HPS[MLPHP.RHO.name] = sam_search_space

        # Creation of evaluator
        evaluator = Evaluator(model_constructor=PetaleMLPR,
                              dataset=dataset,
                              masks=masks,
                              evaluation_name=f"ggeEnet_warmup{eval_id}",
                              hps=ENET_HPS,
                              n_trials=200,
                              evaluation_metrics=evaluation_metrics,
                              feature_selector=feature_selector,
                              fixed_params=fixed_params,
                              fixed_params_update_function=update_fixed_params,
                              save_hps_importance=True,
                              save_optimization_history=True,
                              seed=args.seed)

        # Evaluation
        evaluator.evaluate()

        print("Time Taken for GGE (minutes): ", round((time.time() - start) / 60, 2))

    """
    GGAE experiment
    """
    if args.ggae and genes:

        # Start timer
        start = time.time()

        # Creation of the dataset
        dataset = PetaleDataset(df, target, cont_cols, cat_cols,
                                gene_cols=gene_cols, to_tensor=True, classification=False)


        def gene_encoder_constructor(gene_idx_groups: Optional[Dict[str, List[int]]]) -> GeneEncoder:
            """
            Builds a GeneGraphAttentionEncoder

            Args:
                gene_idx_groups: dictionary where keys are names of chromosomes and values
                                 are list of idx referring to columns of genes associated to
                                 the chromosome

            Returns: GeneEncoder
            """

            return GeneGraphAttentionEncoder(gene_idx_groups=gene_idx_groups,
                                             genes_emb_sharing=args.embedding_sharing,
                                             signature_size=3)

        def update_fixed_params(dts):
            nb_cont_col = len(dts.cont_cols) if dts.cont_cols is not None else 0
            return {'max_epochs': 200,
                    'patience': 25,
                    'num_cont_col': nb_cont_col,
                    'cat_idx': dts.cat_idx,
                    'cat_sizes': dts.cat_sizes,
                    'cat_emb_sizes': dts.cat_sizes,
                    'gene_idx_groups': dts.gene_idx_groups,
                    'gene_encoder_constructor': gene_encoder_constructor}


        # Saving of fixed_params for GGAE + ENET
        fixed_params = update_fixed_params(dataset)

        # Update of hyperparameters
        if args.enable_sam:
            ENET_HPS[MLPHP.RHO.name] = sam_search_space

        # Creation of evaluator
        evaluator = Evaluator(model_constructor=PetaleMLPR,
                              dataset=dataset,
                              masks=masks,
                              evaluation_name=f"ggaeEnet_warmup{eval_id}",
                              hps=ENET_HPS,
                              n_trials=200,
                              evaluation_metrics=evaluation_metrics,
                              feature_selector=feature_selector,
                              fixed_params=fixed_params,
                              fixed_params_update_function=update_fixed_params,
                              save_hps_importance=True,
                              save_optimization_history=True,
                              seed=args.seed)

        # Evaluation
        evaluator.evaluate()

        print("Time Taken for GGAE (minutes): ", round((time.time() - start) / 60, 2))

    """
    HAN experiment
    """
    if args.han and (genes or args.sex) and args.baselines:

        # Start timer
        start = time.time()

        # Creation of the dataset
        dataset = PetaleStaticGNNDataset(df, target, cont_cols, cat_cols, classification=False)

        # Creation of function to update fixed params
        def update_fixed_params(dts):
            return {'meta_paths': dts.get_metapaths(),
                    'num_cont_col': len(dts.cont_cols),
                    'cat_idx': dts.cat_idx,
                    'cat_sizes': dts.cat_sizes,
                    'cat_emb_sizes': dts.cat_sizes,
                    'max_epochs': 250,
                    'patience': 15}

        # Saving of original fixed params for HAN
        fixed_params = update_fixed_params(dataset)

        # Update of hyperparameters
        if args.enable_sam:
            HAN_HPS[HanHP.RHO.name] = sam_search_space

        # Creation of the evaluator
        evaluator = Evaluator(model_constructor=PetaleHANR,
                              dataset=dataset,
                              masks=gnn_masks,
                              evaluation_name=f"HAN_warmup{eval_id}",
                              hps=HAN_HPS,
                              n_trials=200,
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

        print("Time Taken for HAN (minutes): ", round((time.time() - start) / 60, 2))

    """
    HAN with single layered pre-encoder
    """
    if args.han_with_encoding and (genes or args.sex) and args.baselines:

        # Start timer
        start = time.time()

        # Creation of the dataset
        dataset = PetaleStaticGNNDataset(df, target, cont_cols, cat_cols, classification=False)

        # Creation of function that builds pre-encoder
        def build_encoder(input_size: int) -> MLPEncodingBlock:
            return MLPEncodingBlock(input_size=input_size,
                                    output_size=5,
                                    layers=[],
                                    activation="PReLU",
                                    dropout=0)

        # Creation of function to update fixed params
        def update_fixed_params(dts):
            return {'meta_paths': dts.get_metapaths(),
                    'num_cont_col': len(dts.cont_cols),
                    'cat_idx': dts.cat_idx,
                    'cat_sizes': dts.cat_sizes,
                    'cat_emb_sizes': dts.cat_sizes,
                    'max_epochs': 250,
                    'patience': 15,
                    'pre_encoder_constructor': build_encoder}


        # Saving of original fixed params for HANe
        fixed_params = update_fixed_params(dataset)

        # Update of hyperparameters
        if args.enable_sam:
            HAN_HPS[HanHP.RHO.name] = sam_search_space

        # Creation of the evaluator
        evaluator = Evaluator(model_constructor=PetaleHANR,
                              dataset=dataset,
                              masks=gnn_masks,
                              evaluation_name=f"HANe_warmup{eval_id}",
                              hps=HAN_HPS,
                              n_trials=200,
                              evaluation_metrics=evaluation_metrics,
                              fixed_params=fixed_params,
                              fixed_params_update_function=update_fixed_params,
                              feature_selector=feature_selector,
                              save_hps_importance=True,
                              save_optimization_history=True,
                              seed=args.seed)

        # Evaluation
        evaluator.evaluate()

        print("Time Taken for encoder + HAN (minutes): ", round((time.time() - start) / 60, 2))

    print("Overall time (minutes): ", round((time.time() - first_start) / 60, 2))

    """
    Self supervised learning experiment
    """
    if args.ssl_ggae and genes:

        # Start timer
        start = time.time()

        # Creation of the dataset
        dataset = PetaleDataset(df, target, cont_cols, cat_cols,
                                gene_cols=gene_cols, to_tensor=True, classification=False)

        # Creation of a function to update fixed params
        def update_fixed_params(dts):
            return {'max_epochs': 200,
                    'patience': 25,
                    'gene_idx_groups': dts.gene_idx_groups,
                    'hidden_size': 3,
                    'signature_size': 3,
                    'genes_emb_sharing': args.embedding_sharing,
                    'aggregation_method': 'att'}

        # Saving of original fixed params for GGAE
        fixed_params = update_fixed_params(dataset)

        # Creation of the evaluator
        evaluator = Evaluator(model_constructor=PetaleGGE,
                              dataset=dataset,
                              masks=masks,
                              evaluation_name=f"ggae_warmup{eval_id}",
                              hps=GGEHPS,
                              n_trials=200,
                              evaluation_metrics=[],
                              fixed_params=fixed_params,
                              fixed_params_update_function=update_fixed_params,
                              feature_selector=feature_selector,
                              save_hps_importance=True,
                              save_optimization_history=True,
                              seed=args.seed,
                              pred_path=args.path)

        # Evaluation
        evaluator.evaluate()

        print("Time Taken for Self Supervised GGAE (minutes): ", round((time.time() - start) / 60, 2))