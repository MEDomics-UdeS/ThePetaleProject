"""
Author: Nicolas Raymond

This file is used to store the base skeleton of custom pytorch models
"""

from abc import ABC, abstractmethod
from dgl import DGLHeteroGraph
from src.data.processing.datasets import PetaleDataset, PetaleStaticGNNDataset
from src.training.early_stopping import EarlyStopper
from src.utils.score_metrics import Metric
from torch import tensor, mean, zeros_like, ones
from torch.nn import Module
from torch.nn.functional import l1_loss, mse_loss
from torch.optim import Adam
from torch.utils.data import DataLoader, SubsetRandomSampler
from typing import Callable, Optional, Tuple, Union


class TorchCustomModel(Module, ABC):
    """
    Use to store common protected attribute of torch custom models
    and loss function with elastic net penalty
    """
    def __init__(self, criterion: Callable, criterion_name: str, eval_metric: Metric,
                 alpha: float = 0, beta: float = 0, verbose: bool = False):
        """
        Sets protected attributes

        Args:
            criterion: loss function of our model
            criterion_name: name of the loss function of our model
            eval_metric: name of the loss function of our model
            alpha: L1 penalty coefficient
            beta: L2 penalty coefficient
            verbose: True if we want trace of the training progress
        """
        Module.__init__(self)
        self._alpha = alpha
        self._beta = beta
        self._criterion = criterion
        self._criterion_name = criterion_name
        self._eval_metric = eval_metric
        self._evaluations = {i: {self._criterion_name: [], self._eval_metric.name: []} for i in ["train", "valid"]}
        self._optimizer = None
        self._verbose = verbose

    def _generate_progress_func(self, max_epochs: int) -> Callable:
        """
        Defines a function that updates the training progress

        Args:
            max_epochs: maximum number of training epochs

        Returns: function
        """
        if self._verbose:
            def update_progress(epoch: int, mean_epoch_loss: float):
                if (epoch + 1) % 5 == 0 or (epoch + 1) == max_epochs:
                    print(f"Epoch {epoch + 1} - Loss : {round(mean_epoch_loss, 4)}")
        else:
            def update_progress(*args):
                pass

        return update_progress

    def fit(self, dataset: PetaleDataset, lr: float, batch_size: int = 55,
            valid_batch_size: Optional[int] = None, max_epochs: int = 200, patience: int = 15,
            sample_weights: Optional[tensor] = None) -> None:
        """
        Fits the model to the training data

        Args:
            dataset: PetaleDataset used to feed data loaders
            lr: learning rate
            batch_size: size of the batches in the training loader
            valid_batch_size: size of the batches in the valid loader (None = one single batch)
            max_epochs: Maximum number of epochs for training
            patience: Number of consecutive epochs without improvement
            sample_weights: (N,) tensor with weights of the samples in the training set

        Returns: None
        """
        # We check the validity of the samples' weights
        sample_weights = self._validate_sample_weights(dataset, sample_weights)

        # We create the training objects
        train_data = self._create_train_objects(dataset, batch_size)

        # We create validation objects
        early_stopper, valid_data = self._create_validation_objects(dataset, valid_batch_size, patience)

        # We init the update function
        update_progress = self._generate_progress_func(max_epochs)

        # We set the optimizer
        self._optimizer = Adam(self.parameters(), lr=lr)

        # We execute the epochs
        for epoch in range(max_epochs):

            # We calculate training mean epoch loss on all batches
            mean_epoch_loss = self._execute_train_step(train_data, sample_weights)
            update_progress(epoch, mean_epoch_loss)

            # We proceed to calculate valid mean epoch loss and apply early stopping if needed
            if self._execute_valid_step(valid_data, early_stopper):
                print(f"\nEarly stopping occurred at epoch {epoch} with best_epoch = {epoch - patience}"
                      f" and best_val_{self._criterion_name} = {round(early_stopper.val_loss_min, 4)}")
                break

        if early_stopper is not None:

            # We extract best params and remove checkpoint file
            self.load_state_dict(early_stopper.get_best_params())
            early_stopper.remove_checkpoint()

    def loss(self, sample_weights: tensor, pred: tensor, y: tensor) -> tensor:
        """
        Calls the criterion and add elastic penalty

        Args:
            sample_weights: (N,) tensor with weights of samples on which we calculate loss
            pred: (N, C) tensor if classification with C classes, (N,) tensor for regression
            y: (N,) tensor with targets

        Returns: tensor with loss value
        """
        # Computations of penalties
        flatten_params = [w.view(-1, 1) for w in self.parameters()]
        l1_penalty = mean(tensor([l1_loss(w, zeros_like(w)) for w in flatten_params]))
        l2_penalty = mean(tensor([mse_loss(w, zeros_like(w)) for w in flatten_params]))

        # Computation of loss without reduction
        loss = self._criterion(pred, y.float())  # (N,) tensor

        # Computation of loss reduction + elastic penalty
        return (loss * sample_weights / sample_weights.sum()).sum() + self._alpha * l1_penalty + self._beta * l2_penalty

    @staticmethod
    def _create_train_objects(dataset: PetaleDataset, batch_size: int
                              ) -> Union[DataLoader, Tuple[DataLoader, DGLHeteroGraph]]:
        """
        Creates objects proper to training (train dataloader and train graph)
        Args:
            dataset: PetaleDataset used to feed data loaders
            batch_size: size of the batches in the train loader

        Returns: train loader, DGLHeterograph

        """
        # Creation of training loader
        train_data = DataLoader(dataset, batch_size=min(len(dataset.train_mask), batch_size),
                                sampler=SubsetRandomSampler(dataset.train_mask))

        # If the dataset is a GNN dataset, we include the train subgraph into train data
        if isinstance(dataset, PetaleStaticGNNDataset):
            train_data = (train_data, dataset.get_train_subgraph())

        return train_data

    @staticmethod
    def _create_validation_objects(dataset: PetaleDataset, valid_batch_size: Optional[int], patience: int
                                   ) -> Tuple[Optional[EarlyStopper],
                                              Optional[Union[DataLoader, Tuple[DataLoader, DGLHeteroGraph]]]]:
        """
        Creates the object used for validation during the training

        Args:
            dataset: PetaleDataset used to feed data loaders
            valid_batch_size: size of the batches in the valid loader (None = one single batch)
            patience: Number of consecutive epochs without improvement

        Returns: early stopper, (Dataloader, DGLHeteroGraph)

        """
        # We create the valid data loader
        valid_size, valid_data, early_stopper = len(dataset.valid_mask), None, None

        # If we need a validation set, we set the variables with real values
        if valid_size != 0:

            # We check if a valid batch size was provided
            valid_bs = valid_batch_size if valid_batch_size is not None else valid_size

            # We create the valid loader
            valid_bs = min(valid_size, valid_bs)
            valid_data = DataLoader(dataset, batch_size=valid_bs, sampler=SubsetRandomSampler(dataset.valid_mask))
            early_stopper = EarlyStopper(patience)

            # If the dataset is a GNN dataset, we include the valid subgraph into valid data
            if isinstance(dataset, PetaleStaticGNNDataset):
                valid_data = (valid_data, dataset.get_valid_subgraph())

        return early_stopper, valid_data

    @staticmethod
    def _validate_sample_weights(dataset: PetaleDataset, sample_weights: Optional[tensor]) -> tensor:
        """
        Validates the provided sample weights and return them.
        If None are provided, each sample as the same weights of 1/n in the training loss
        Args:
            dataset: PetaleDataset used to feed data loaders
            sample_weights: (N,) tensor with weights of the samples in the training set

        Returns:

        """
        # We check the validity of the samples' weights
        dataset_size = len(dataset)
        if sample_weights is not None:
            assert (sample_weights.shape[0] == dataset_size),\
                f"Sample weights as length {sample_weights.shape[0]} while dataset as length {dataset_size}"
        else:
            sample_weights = ones(dataset_size) / dataset_size

        return sample_weights

    @abstractmethod
    def _execute_train_step(self, train_data: Union[DataLoader, Tuple[DataLoader, DGLHeteroGraph]],
                            sample_weights: tensor) -> float:
        """
        Executes one training epoch

        Args:
            train_data: training data loader or tuple (train loader, train subgraph)
            sample_weights: weights of the samples in the loss

        Returns: mean epoch loss
        """
        raise NotImplementedError

    @abstractmethod
    def _execute_valid_step(self, valid_data: Optional[Union[DataLoader, Tuple[DataLoader, DGLHeteroGraph]]],
                            early_stopper: Optional[EarlyStopper]) -> bool:
        """
        Executes an inference step on the validation data

        Args:
            valid_data: valid data loader or tuple (valid loader, valid subgraph)
            early_stopper: early stopper keeping track of validation loss

        Returns: True if we need to early stop
        """
        raise NotImplementedError
