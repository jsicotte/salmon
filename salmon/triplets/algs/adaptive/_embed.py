import itertools
from copy import copy
from typing import List, Tuple

import numpy as np
import torch
import torch.optim as optim
from numba import jit, prange
from skorch.net import NeuralNet
from torch.nn.modules.loss import _Loss
from sklearn.utils import check_random_state
from scipy.special import binom
from salmon.utils import get_logger

logger = get_logger(__name__)

from .search import gram_utils, score


class _Embedding(NeuralNet):
    def partial_fit(self, *args, **kwargs):
        r = super().partial_fit(*args, **kwargs)

        # Project back onto norm ball
        with torch.no_grad():
            norms = torch.norm(self.module_._embedding, dim=1)
            max_norm = 10 * self.module__d
            idx = norms > max_norm
            if idx.sum():
                self.module_._embedding[idx] *= max_norm / norms[idx]

        return r

    def score(self, answers, y=None):
        win2, lose2 = self.module_._get_dists(answers)
        acc = (win2 < lose2).numpy().astype("float32").mean().item()
        return acc


class Reduce:
    def __call__(self, input: torch.Tensor, target=None) -> torch.Tensor:
        return torch.mean(input)


class Embedding(_Embedding):
    """
    An triplet embedding algorithm.

    Parameters
    ----------


    """

    def __init__(
        self,
        module,
        module__n: int = 85,
        module__d: int = 2,
        optimizer=optim.SGD,
        optimizer__lr=0.05,
        optimizer__momentum=0.9,
        random_state=None,
        initial_batch_size=64,
        warm_start=True,
        max_epochs=1,
        **kwargs,
    ):
        self.initial_batch_size = initial_batch_size
        self.random_state = random_state
        super().__init__(
            module=module,
            module__n=module__n,
            module__d=module__d,
            module__random_state=random_state,
            optimizer=optimizer,
            optimizer__lr=optimizer__lr,
            optimizer__momentum=optimizer__momentum,
            warm_start=warm_start,
            **kwargs,
            criterion=Reduce,
            verbose=False,
            batch_size=-1,
            max_epochs=1,
            optimizer__nesterov=True,
            train_split=None,
        )

    def initialize(self):

        rng = check_random_state(self.random_state)
        super().initialize()

        self.meta_ = {"num_answers": 0, "model_updates": 0}
        self.initialized_ = True
        self.random_state_ = rng
        self.answers_ = np.zeros((1000, 3), dtype="uint16")

    @property
    def batch_size_(self):
        return self.initial_batch_size

    def push(self, answers):
        if not (hasattr(self, "initialized_") and self.initialized_):
            self.initialize()

        if isinstance(answers, list):
            answers = (
                np.array(answers) if len(answers) else np.empty((0, 3), dtype="uint16")
            )
        i = self.meta_["num_answers"]
        if i + len(answers) >= len(self.answers_):
            n = len(answers) + len(self.answers_)
            new_ans = np.zeros((n, 3), dtype="uint16")
            self.answers_ = np.vstack((self.answers_, new_ans))
        self.answers_[i : i + len(answers)] = answers
        self.meta_["answers_bytes"] = self.answers_.nbytes
        return self.answers_.nbytes

    def partial_fit(self, answers):
        """
        Process the provided answers.

        Parameters
        ----------
        anwers : array-like
            The answers, with shape (num_ans, 3). Each row is
            [head, winner, loser].

        Returns
        -------
        self

        Notes
        -----
        This function runs one iteration of SGD.

        This impure function modifies

            * ``self.meta_`` keys ``model_updates`` and ``num_answers``
            * ``self.module_``, the embedding.
        """
        if not isinstance(answers, np.ndarray):
            answers = np.array(answers, dtype="uint16")
        if not len(answers):
            return self
        beg_meta = copy(self.meta_)
        while True:
            incidies = np.arange(len(answers), dtype="int")

            bs = self.batch_size_

            idx_train = self.random_state_.choice(len(answers), size=bs)
            train_ans = answers[idx_train].astype("int64")
            _ = super().partial_fit(train_ans)

            self.meta_["num_answers"] += self.batch_size_
            self.meta_["model_updates"] += 1
            logger.info("%s", self.meta_)
            if self.meta_["num_answers"] - beg_meta["num_answers"] >= len(answers):
                break
        return self

    def score(self, answers, y=None):
        if not (hasattr(self, "initialized_") and self.initialized_):
            self.initialize()
        score = super().score(answers)
        self.meta_["last_score"] = score
        return score

    def fit(self, X, y=None):
        for epoch in range(self.max_epochs):
            self.partial_fit(self.answers_)
        return self

    def embedding(self):
        return self.module_.embedding.detach().numpy()


class Damper(Embedding):
    def __init__(
        self,
        module,
        module__n=85,
        module__d=85,
        optimizer=None,
        optimizer__lr=None,
        optimizer__momentum=0.9,
        random_state=None,
        initial_batch_size=64,
        max_batch_size=None,
        **kwargs,
    ):
        self.max_batch_size = max_batch_size
        super().__init__(
            module=module,
            module__n=module__n,
            module__d=module__d,
            optimizer=optimizer,
            optimizer__lr=optimizer__lr,
            optimizer__momentum=optimizer__momentum,
            random_state=random_state,
            initial_batch_size=initial_batch_size,
            **kwargs,
        )

    def initialize(self):
        r = super().initialize()
        if hasattr(self, "max_batch_size"):
            self.max_batch_size_ = self.max_batch_size or 10 * self.module__n
        return r

    def _set_lr(self, lr):
        opt = self.module_.optimizer_
        for group in opt.param_groups:
            group["lr"] = lr

    @property
    def batch_size_(self):
        bs = self.damping()
        self.meta_["batch_size"] = bs
        if self.max_batch_size and bs > self.max_batch_size:
            lr_decay = self.max_batch_size / bs
            new_lr = self.optimizer__lr * lr_decay
            self._set_lr(new_lr)
            self.meta_["lr_"] = new_lr
            self.meta_["batch_size"] = self.max_batch_size
        return self.meta_["batch_size"]

    def damping(self):
        raise NotImplementedError


class PadaDampG(Damper):
    def __init__(
        self,
        module,
        module__n=85,
        module__d=85,
        optimizer=None,
        optimizer__lr=None,
        optimizer__momentum=0.9,
        random_state=None,
        initial_batch_size=64,
        max_batch_size=None,
        dwell=10,
        growth_factor=1.01,
        **kwargs,
    ):
        super().__init__(
            module=module,
            module__n=module__n,
            module__d=module__d,
            optimizer=optimizer,
            optimizer__lr=optimizer__lr,
            optimizer__momentum=optimizer__momentum,
            random_state=random_state,
            initial_batch_size=initial_batch_size,
            max_batch_size=max_batch_size,
            **kwargs,
        )
        self.growth_factor = growth_factor
        self.dwell = dwell

    def damping(self):
        mu = self.meta_["model_updates"]
        if mu % self.dwell == 0:
            pwr = mu / self.dwell
            assert np.allclose(pwr, int(pwr))
            bs = self.initial_batch_size * (self.growth_factor ** (pwr + 1))
            self.meta_["damping"] = int(np.round(bs))
        return self.meta_["damping"]


class GeoDamp(Damper):
    def __init__(
        self,
        module,
        module__n=85,
        module__d=85,
        optimizer=None,
        optimizer__lr=None,
        optimizer__momentum=0.9,
        random_state=None,
        initial_batch_size=64,
        max_batch_size=None,
        dwell=10,
        growth_factor=1.01,
        **kwargs,
    ):
        super().__init__(
            module=module,
            module__n=module__n,
            module__d=module__d,
            optimizer=optimizer,
            optimizer__lr=optimizer__lr,
            optimizer__momentum=optimizer__momentum,
            random_state=random_state,
            initial_batch_size=initial_batch_size,
            max_batch_size=max_batch_size,
            **kwargs,
        )
        self.growth_factor = growth_factor
        self.dwell = dwell

    def damping(self):
        n_eg = self.meta_["num_answers"]
        if n_eg % self.dwell == 0:
            pwr = n_eg / self.dwell
            assert np.allclose(pwr, int(pwr))
            pwr = int(pwr)
            bs = self.initial_batch_size * (self.growth_factor ** (pwr + 1))
            self.meta_["damping"] = int(np.round(bs))
        return self.meta_["damping"]
