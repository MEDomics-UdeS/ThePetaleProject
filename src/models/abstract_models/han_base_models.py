"""
Filename: han_base_models.py

Author: Nicolas Raymond

Description: Defines all components related to Heterogeneous Graph Attention Network (HAN).
             The code was mainly taken from this DGL code example :
             https://github.com/dmlc/dgl/tree/master/examples/pytorch/han

Date of last modification: 2021/11/18

"""

from dgl import DGLHeteroGraph
from src.data.processing.datasets import MaskType, PetaleStaticGNNDataset
from src.models.abstract_models.custom_torch_base import TorchCustomModel
from src.models.blocks.gnn_blocks import HANLayer
from src.training.early_stopping import EarlyStopper
from src.utils.score_metrics import BinaryClassificationMetric, BinaryCrossEntropy, Metric, \
    RegressionMetric, RootMeanSquaredError
from torch import cat, no_grad, ones, sigmoid, tensor, unsqueeze
from torch.nn import BCEWithLogitsLoss, Identity, Linear, MSELoss
from torch.utils.data import DataLoader
from typing import Callable, List, Optional, Tuple


class HAN(TorchCustomModel):
    """
    Heterogeneous Graph Attention Network model.
    """
    def __init__(self,
                 meta_paths: List[List[str]],
                 hidden_size: int,
                 out_size: int,
                 num_heads: int,
                 dropout: float,
                 criterion: Callable,
                 criterion_name: str,
                 eval_metric: Metric,
                 cat_idx: List[int],
                 cat_sizes: List[int],
                 cat_emb_sizes: List[int],
                 num_cont_col: Optional[int] = None,
                 alpha: float = 0,
                 beta: float = 0,
                 pre_encoder_constructor: Callable = None,
                 verbose: bool = False
                 ):
        """
        Sets the input encoding function according to the presence or absence of pre-encoder
        and builds the layers of the HAN model.

        Args:
            meta_paths: list of metapaths, each meta path is a list of edge types
            hidden_size: size of embedding learnt within each attention head
            out_size: output size (number of node in last layer)
            num_heads: number of attention heads in the HANLayer
            dropout: dropout probability
            criterion: loss function of our model
            criterion_name: name of the loss function of our model
            eval_metric: evaluation metric
            num_cont_col: number of numerical continuous columns in the dataset
            cat_idx: idx of categorical columns in the dataset
            cat_sizes: list of integer representing the size of each categorical column
            cat_emb_sizes: list of integer representing the size of each categorical embedding
            alpha: L1 penalty coefficient
            beta: L2 penalty coefficient
            pre_encoder_constructor: function that creates an encoder that goes after the entity embedding block
                                     This function must have a parameter "input_size"
            verbose: True if we want trace of the training progress
        """
        # Call of parent's constructor
        super().__init__(criterion=criterion,
                         criterion_name=criterion_name,
                         eval_metric=eval_metric,
                         output_size=out_size,
                         alpha=alpha,
                         beta=beta,
                         num_cont_col=num_cont_col,
                         cat_idx=cat_idx,
                         cat_sizes=cat_sizes,
                         cat_emb_sizes=cat_emb_sizes,
                         verbose=verbose)

        # We check if a pre-encoder is given
        if pre_encoder_constructor is not None:

            # We set the pre-encoder
            self._pre_encoder = pre_encoder_constructor(input_size=self._input_size)

            # We modify the input size passed to the HANLayer
            self._input_size = self._pre_encoder.output_size

        else:
            # We set the pre-encoder attribute to None
            self._pre_encoder = Identity()

        # We create the appropriate encoding function according to the output size
        if self._input_size > 1:
            self._encode = self._custom_encoding
        else:
            self._encode = self._custom_encoding_with_unsqueeze

        # Initialization of the main layer
        self._gnn_layer = HANLayer(meta_paths=meta_paths,
                                   in_size=self._input_size,
                                   out_size=hidden_size,
                                   layer_num_heads=num_heads,
                                   dropout=dropout)

        # Addition of linear layer before calculation of the loss
        self._linear_layer = Linear(hidden_size * num_heads, out_size)

        # Attribute dedicated to training
        self._optimizer = None

    def _custom_encoding(self, x: tensor) -> tensor:
        """
        Executes a forward pass with the given pre-encoder

        Args:
            x: (N,D) tensor with D-dimensional samples

        Returns: (N, D') tensor with encodings
        """
        return self._pre_encoder(x)

    def _custom_encoding_with_unsqueeze(self, x: tensor) -> tensor:
        """
        Executes a forward pass with the given pre-encoder

        Args:
            x: (N,D) tensor with D-dimensional samples

        Returns: (N, D') tensor with encodings
        """
        return unsqueeze(self._pre_encoder(x), dim=1)

    def _execute_train_step(self,
                            train_data: Tuple[DataLoader, PetaleStaticGNNDataset],
                            sample_weights: tensor) -> float:
        """
        Executes one training epoch

        Args:
            train_data: tuple (train loader, dataset)
            sample_weights: weights of the samples in the loss

        Returns: mean epoch loss
        """

        # We set the model for training
        self.train()
        epoch_loss, epoch_score = 0, 0

        # We extract train loader, dataset
        train_loader, dataset = train_data

        # We extract train_subgraph, train_mask and train_idx_map
        train_subgraph, train_idx_map, train_mask = dataset.train_subgraph

        # We extract the features related to all the train mask
        x, _, _ = dataset[train_mask]

        # We execute one training step
        for item in train_loader:

            # We extract the data
            _, y, idx = item

            # We map the original idx to their position in the train mask
            pos_idx = [train_idx_map[i.item()] for i in idx]

            # We clear the gradients
            self._optimizer.zero_grad()

            # We perform the weight update
            pred, loss = self._update_weights(sample_weights[idx], [train_subgraph, x], y, pos_idx)

            # We update the metrics history
            score = self._eval_metric(pred, y)
            epoch_loss += loss
            epoch_score += score

        # We save mean epoch loss and mean epoch score
        nb_batch = len(train_data)
        mean_epoch_loss = epoch_loss / nb_batch
        self._evaluations[MaskType.TRAIN][self._criterion_name].append(mean_epoch_loss)
        self._evaluations[MaskType.TRAIN][self._eval_metric.name].append(epoch_score / nb_batch)

        return mean_epoch_loss

    def _execute_valid_step(self,
                            valid_data: Optional[Tuple[DataLoader, PetaleStaticGNNDataset]],
                            early_stopper: EarlyStopper) -> bool:
        """
        Executes an inference step on the validation data and apply early stopping if needed

        Args:
            valid_data: tuple (valid loader, dataset)
            early_stopper: early stopper keeping track of validation loss

        Returns: True if we need to early stop
        """
        # We extract train loader, dataset
        valid_loader, dataset = valid_data

        # We check if there is validation to do
        if valid_loader is None:
            return False

        # We extract valid_subgraph, mask (train + valid) and valid_idx_map
        valid_subgraph, valid_idx_map, mask = dataset.valid_subgraph

        # We extract the features related to all the train + valid
        x, _, _ = dataset[mask]

        # Set model for evaluation
        self.eval()
        epoch_loss, epoch_score = 0, 0

        # We execute one inference step on validation set
        with no_grad():

            for item in valid_loader:

                # We extract the data
                _, y, idx = item

                # We map original idx to their position in the train mask
                pos_idx = [valid_idx_map[i.item()] for i in idx]

                # We perform the forward pass: compute predicted outputs by passing inputs to the model
                pred = self(valid_subgraph, x)

                # We calculate the loss and the score
                batch_size = len(idx)
                sample_weights = ones(batch_size) / batch_size  # Sample weights are equal for validation (1/N)
                epoch_loss += self.loss(sample_weights, pred[pos_idx], y).item()
                epoch_score += self._eval_metric(pred[pos_idx], y)

        # We save mean epoch loss and mean epoch score
        nb_batch = len(valid_loader)
        mean_epoch_loss = epoch_loss / nb_batch
        mean_epoch_score = epoch_score / nb_batch
        self._evaluations[MaskType.VALID][self._criterion_name].append(mean_epoch_loss)
        self._evaluations[MaskType.VALID][self._eval_metric.name].append(mean_epoch_score)

        # We check early stopping status
        early_stopper(mean_epoch_score, self)

        if early_stopper.early_stop:
            return True

        return False

    def forward(self,
                g: DGLHeteroGraph,
                x: tensor) -> tensor:
        """
        Executes the forward pass

        Args:
            g: DGL Heterogeneous graph
            x: (N,D) tensor with D-dimensional samples

        Returns: (N, D') tensor with values of the node within the last layer
        """

        # We passe the input through the entity embedding block
        if len(self._cont_idx) != 0:
            e = cat([x[:, self._cont_idx], self._embedding_block(x)], 1)
        else:
            e = self._embedding_block(x)

        # We create encodings with the pre-encoder
        e = self._encode(e)

        # We make a forward pass through the han main layer to get the embeddings
        h = self._gnn_layer(g, e)

        # We pass the final embedding through a linear layer
        return self._linear_layer(h).squeeze()


class HANBinaryClassifier(HAN):
    """
    Single layered heterogeneous graph attention network binary classifier
    """
    def __init__(self,
                 meta_paths: List[List[str]],
                 hidden_size: int,
                 num_heads: int,
                 dropout: float,
                 cat_idx: List[int],
                 cat_sizes: List[int],
                 cat_emb_sizes: List[int],
                 eval_metric: Optional[BinaryClassificationMetric] = None,
                 num_cont_col: Optional[int] = None,
                 alpha: float = 0,
                 beta: float = 0,
                 pre_encoder_constructor: Callable = None,
                 verbose: bool = False
                 ):
        """
        Sets protected attributes of the HAN model

        Args:
            meta_paths: list of metapaths, each meta path is a list of edge types
            hidden_size: size of embedding learnt within each attention head
            num_heads: int representing the number of attention heads
            dropout: dropout probability
            num_cont_col: number of numerical continuous columns in the dataset
            cat_idx: idx of categorical columns in the dataset
            cat_sizes: list of integer representing the size of each categorical column
            cat_emb_sizes: list of integer representing the size of each categorical embedding
            eval_metric: evaluation metric
            alpha: L1 penalty coefficient
            beta: L2 penalty coefficient
            pre_encoder_constructor: function that creates an encoder that goes after the entity embedding block
                                     This function must have a parameter "input_size"
            verbose: true to print training progress when fit is called
        """
        # Call parent's constructor
        eval_metric = eval_metric if eval_metric is not None else BinaryCrossEntropy()
        super().__init__(meta_paths=meta_paths,
                         hidden_size=hidden_size,
                         out_size=1,
                         num_heads=num_heads,
                         dropout=dropout,
                         criterion=BCEWithLogitsLoss(reduction='none'),
                         criterion_name='WBCE',
                         eval_metric=eval_metric,
                         num_cont_col=num_cont_col,
                         cat_idx=cat_idx,
                         cat_sizes=cat_sizes,
                         cat_emb_sizes=cat_emb_sizes,
                         alpha=alpha,
                         beta=beta,
                         pre_encoder_constructor=pre_encoder_constructor,
                         verbose=verbose)

    def predict_proba(self,
                      dataset: PetaleStaticGNNDataset,
                      mask: Optional[List[int]] = None) -> tensor:
        """
        Returns the probabilities of being in class 1 for all samples
        in a particular set (default = test)

        Args:
            dataset: PetaleDatasets which its items are tuples (x, y, idx) where
                     - x : (N,D) tensor with D-dimensional samples
                     - y : (N,) tensor with classification labels
                     - idx : (N,) tensor with idx of samples according to the whole dataset
            mask: list of dataset idx for which we want to predict proba

        Returns: (N,) tensor
        """
        # We extract subgraph data (we add training data for graph convolution)
        if mask is not None:
            mask_with_train = list(set(mask + dataset.train_mask))
            g, idx_map = dataset.get_arbitrary_subgraph(mask_with_train)
        else:
            mask = dataset.test_mask
            g, idx_map, mask_with_train = dataset.test_subgraph

        # Set model for evaluation
        self.eval()

        # Execute a forward pass and apply a softmax
        with no_grad():
            pos_idx = [idx_map[i] for i in mask]
            x, _, _ = dataset[mask_with_train]
            return sigmoid(self(g, x))[pos_idx]


class HANRegressor(HAN):
    """
    Single layered heterogeneous graph attention network regression model
    """
    def __init__(self,
                 meta_paths: List[List[str]],
                 hidden_size: int,
                 num_heads: int,
                 dropout: float,
                 cat_idx: List[int],
                 cat_sizes: List[int],
                 cat_emb_sizes: List[int],
                 eval_metric: Optional[RegressionMetric] = None,
                 num_cont_col: Optional[int] = None,
                 alpha: float = 0,
                 beta: float = 0,
                 pre_encoder_constructor: Callable = None,
                 verbose: bool = False
                 ):
        """
        Sets protected attributes of the HAN model

        Args:
            meta_paths: list of metapaths, each meta path is a list of edge types
            hidden_size: size of embedding learnt within each attention head
            num_heads: int representing the number of attention heads
            dropout: dropout probability
            num_cont_col: number of numerical continuous columns in the dataset
            cat_idx: idx of categorical columns in the dataset
            cat_sizes: list of integer representing the size of each categorical column
            cat_emb_sizes: list of integer representing the size of each categorical embedding
            eval_metric: evaluation metric
            alpha: L1 penalty coefficient
            beta: L2 penalty coefficient
            pre_encoder_constructor: function that creates an encoder that goes after the entity embedding block
                                     This function must have a parameter "input_size"
            verbose: true to print training progress when fit is called
        """
        # Call parent's constructor
        eval_metric = eval_metric if eval_metric is not None else RootMeanSquaredError()
        super().__init__(meta_paths=meta_paths,
                         hidden_size=hidden_size,
                         out_size=1,
                         num_heads=num_heads,
                         dropout=dropout,
                         criterion=MSELoss(reduction='none'),
                         criterion_name='MSE',
                         eval_metric=eval_metric,
                         num_cont_col=num_cont_col,
                         cat_idx=cat_idx,
                         cat_sizes=cat_sizes,
                         cat_emb_sizes=cat_emb_sizes,
                         alpha=alpha,
                         beta=beta,
                         pre_encoder_constructor=pre_encoder_constructor,
                         verbose=verbose)

    def predict(self,
                dataset: PetaleStaticGNNDataset,
                mask: Optional[List[int]] = None) -> tensor:
        """
        Returns the real-valued predictions for all samples
        in a particular set (default = test)

        Args:
            dataset: PetaleDatasets which its items are tuples (x, y, idx) where
                     - x : (N,D) tensor with D-dimensional samples
                     - y : (N,) tensor with classification labels
                     - idx : (N,) tensor with idx of samples according to the whole dataset
            mask: list of dataset idx for which we want to predict target

        Returns: (N,) tensor
        """
        # We extract subgraph data (we add training data for graph convolution)
        if mask is not None:
            mask_with_train = list(set(mask + dataset.train_mask))
            g, idx_map = dataset.get_arbitrary_subgraph(mask_with_train)
        else:
            mask = dataset.test_mask
            g, idx_map, mask_with_train = dataset.test_subgraph

        # Set model for evaluation
        self.eval()

        # Execute a forward pass and apply a softmax
        with no_grad():
            pos_idx = [idx_map[i] for i in mask]
            x, _, _ = dataset[mask_with_train]
            return self(g, x)[pos_idx]