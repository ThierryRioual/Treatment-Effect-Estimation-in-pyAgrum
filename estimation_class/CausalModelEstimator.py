import pyAgrum as gum
import pyAgrum.causal as csl

import numpy as np
import pandas as pd

import pyAgrum.lib.notebook as gnb
import pyAgrum.causal.notebook as cslnb

class CausalModelEstimator:
    """
    A Causal Baysian Network estimator.
    Uses LazyPropagation from pyAgrum.causal to determine the causal effect.
    """

    def _useCausalStructure(self, cm_clone, causal_model):
        """
        """
        for id in causal_model.latentVariablesIds():
            childrens = causal_model.causalBN().children(id)
            childrens = {
                causal_model.causalBN().variable(c).name() for c in childrens
            }
            cm_clone.addLatentVariable(
                causal_model.causalBN().variable(id).name(), tuple(childrens)
            )
        for x, y in causal_model.arcs():
            if not cm_clone.existsArc(x, y):
                cm_clone.addCausalArc(x, y)

    def __init__(
            self,
            causal_model : csl.CausalModel,
            treatment : str,
            outcome : str,
        ) -> None:
        """
        Initialize an Causal Model estimator.

        Parameters
        ----------
        propensity_score_learner (optional): str | object | None
            Estimator for propensity score.
            If not provided, defaults to LogisticRegression.
        """
        if isinstance(causal_model, csl.CausalModel):
            self.causal_model = causal_model.clone()
            self._useCausalStructure(
                self.causal_model,
                causal_model
            )
        else:
            raise ValueError("Causal Model cannot be None. ")

        self.treatment = treatment
        self.outcome = outcome

    def fit(
            self,
            df : pd.DataFrame,
            smoothing_prior : float = 1e-9
        ) -> None:
        """
        Fit the inference model.

        Parameters
        ----------
        df : pd.DataFrame
            The observations.
        smoothing_prior (Optional): float
            The uniform prior distribution. Default is 1e-9.
        """

        parameter_learner = gum.BNLearner(df, self.causal_model.observationalBN())
        parameter_learner.useNMLCorrection()
        parameter_learner.useSmoothingPrior(smoothing_prior)

        bn = gum.BayesNet(self.causal_model.observationalBN())

        parameter_learner.fitParameters(bn)

        causal_model = csl.CausalModel(bn)
        self._useCausalStructure(causal_model, self.causal_model)
        self.causal_model = causal_model

        return self.causal_model

    def _getIntervalIndex(self, x : float, var : str) -> int:
        """
        Gets the domain index of the variable.

        Parameters
        ---------
        x : float
            The conditional.
        var : str
            The variable label string.

        Returns
        -------
        int
            The index of the conditional in the variable domain.
        """

        splits = list()
        accumulator = ""
        for letter in \
            self.causal_model.causalBN().variable(var).domain():
            if letter in ["-", ".", "0", "1", "2", "3", \
                          "4", "5", "6", "7", "8", "9"]:
                accumulator += letter
            elif len(accumulator) > 0:
                split = float(accumulator)
                if len(splits) > 0 and splits[-1] == split:
                    splits.pop()
                splits.append(split)
                accumulator = ""

        for i in range(len(splits)):
            if x < splits[i]:
                return i

        return len(splits)-1

    def _predictRow(
            self,
            X : pd.Series
        )-> float:
        """
        Predict the Individual Causal Effect (ICE) of a single row.

        Parameters
        ----------
        X: pd.Series
            The of covariates.

        Returns
        -------
        float
            The predicted ICE.
        """

        keys = X.index.to_list() + [self.treatment]
        values = list()
        for covar in X.index:
            values.append(self._getIntervalIndex(X[covar], covar))

        values0 = values + [0]
        values1 = values + [1]

        _, cpt0, _ = csl.causalImpact(
            cm=self.causal_model,
            on=self.outcome,
            doing=self.treatment,
            knowing=set(X.index),
            values=dict(zip(keys, values0))
        )

        _, cpt1, _ = csl.causalImpact(
            cm=self.causal_model,
            on=self.outcome,
            doing=self.treatment,
            knowing=set(X.index),
            values=dict(zip(keys, values1))
        )

        diff = cpt1 - cpt0
        ite = diff.expectedValue(
            lambda d : diff.variable(0).numerical(
                d[diff.variable(0).name()]
            )
        )

        return ite

    def predict(
            self,
            w : np.matrix | np.ndarray | pd.DataFrame = None,
            X : np.matrix | np.ndarray | pd.DataFrame = None,
            M : np.matrix | np.ndarray | pd.DataFrame = None,
            treatment : np.ndarray | pd.Series | None = None,
            y : np.ndarray | pd.Series | None = None,
        )-> np.ndarray:
        """
        Predict the Idividual Causal Effect (ICE),
        also referd to as the Individual Treatment Effect (ITE).

        Parameters
        ----------
        w : np.matrix | np.ndarray | pd.DataFrame
            The instrument variable.
        X: np.matrix | np.ndarray | pd.DataFrame
            The matrix of covariates.
        treatment (optional): np.ndarray | pd.Series | None
            The vector of treatment assignments.
        y (optional): np.ndarray | pd.Series | None
            The vector of outcomes.

        Returns
        -------
        np.ndarray
            An array containing the predicted ICE.
        """

        if X is not None:
            return X.apply(self._predictRow, axis=1).to_numpy()
        else:
            return M.apply(self._predictRow, axis=1).to_numpy()


    def estimate_ate(
            self,
            w : np.matrix | np.ndarray | pd.DataFrame = None,
            X : np.matrix | np.ndarray | pd.DataFrame = None,
            M : np.matrix | np.ndarray | pd.DataFrame = None,
            treatment : np.ndarray | pd.Series | None = None,
            y : np.ndarray | pd.Series | None = None,
            pretrain : bool = True
        ) -> float:
        """
        Predicts the Average Causal Effect (ACE),
        also refered to as the Average Treatment Effect (ATE).
        (The term ATE is used in the method name for compatibility purposes.)

        Parameters
        ----------
        w : np.matrix | np.ndarray | pd.DataFrame
            The instrument variable.
        X: np.matrix | np.ndarray | pd.DataFrame
            The matrix of covariates.
        treatment (optional): np.ndarray | pd.Series | None
            The vector of treatment assignments.
        y (optional): np.ndarray | pd.Series
            The vector of outcomes.

        Returns
        -------
        float
            The value of the ACE.
        """

        _, cpt0, _ = csl.causalImpact(
            self.causal_model,
            on=self.outcome,
            doing=self.treatment,
            values={self.treatment:0}
        )

        _, cpt1, exp = csl.causalImpact(
            self.causal_model,
            on=self.outcome,
            doing=self.treatment,
            values={self.treatment:1}
        )

        #print(exp)

        difference = cpt1 - cpt0
        return difference.expectedValue(
            lambda d : difference.variable(0).numerical(
                d[difference.variable(0).name()]
            )
        )