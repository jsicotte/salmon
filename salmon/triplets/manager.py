import random
from copy import deepcopy
from datetime import datetime, timedelta
from textwrap import dedent
from typing import Any, Dict, List, Optional, Union
import logging

import numpy as np
from pydantic import BaseModel, BaseSettings, Field, validator

logger = logging.getLogger(__name__)


class Answer(BaseModel):
    """
    An answer to a triplet query. head, left and right are integers
    from '/get_query'. The 'winner' is an integer that is most similar to 'head',
    and must be one of 'left' and 'right'.

    'puid' is the "participant unique ID", and is optional.

    """

    head: int
    left: int
    right: int
    winner: int
    sampler: str
    score: float = 0
    puid: str = ""
    response_time: float = -1
    network_latency: float = -1


class Sampling(BaseSettings):
    """
    Settings to configure how more than two samplers are used.

    These settings are used in the HTML but are not stylistic. The
    exception is ``common``, which is passed to every ``sampler`` during
    initialization and will likely be optional arguments for
    :class:`~salmon.triplets.samplers.Adaptive`.

    The default configuration is specified completely below, which is rendered into a YAML file in `an example`_.

    .. _an example: https://github.com/stsievert/salmon/blob/master/examples/default.yaml


    """

    common: Dict[str, Any] = Field(
        {"d": 2},
        description="""Arguments to pass to every sampler for initialization (likely
        values for :class:`~salmon.triplets.samplers.Adaptive`; note that
        values for ``n`` and ``ident`` are already specified). Any
        values specified in this field will be overwritten by
        sampler-specific arguments.""",
    )
    probs: Optional[Dict[str, int]] = Field(
        None,
        description="""The percentage to sample each ``sampler`` when given the
        opportunity (which depends on ``samplers_per_user``). The percentages
        in this sampler must add up to 100.
        If not specified (default), choose each sampler with equal
        probability.""",
    )
    samplers_per_user: int = Field(
        0,
        description="""The number of samplers to assign to each user. Setting
        ``samplers_per_user=1`` means any user only sees queries generated
        from one sampler, and ``sampler_per_user=0`` means the user sees a
        new sampler every query""",
    )
    details: Dict[int, Any] = Field(
        {},
        description="""Different options for a deterministic choice of samplers.

        This dictionary is of the form ``{query_shown_to_user: options}``. The
        ``options`` is a dictionary with up to two keys:

        - ``sampler`` (required), which reflects which sampler receives the
          responses)

        - ``query`` (optional), which is a list of length 3 indicating the target
          indices appear in the query.

        For example, this YAML will ensure the 1st and 10th query the
        crowdsourcing user sees will be from:

        .. code-block:: yaml

          targets: [zero, one, two, three, four, five, six]
          # ^ list of (textual) targets; target "zero" has index 0 and
          # is targets[0] in Python

          samplers:
            ARR: {}
            Validation: {}
            valid2:
              class: Validation
              n_queries: 3

          sampling:
            probs: {ARR: 100, Validation: 0, valid2: 0}
            details:
              # Each key "n" is the n-th query the user sees
              # So here the 1st and 10th queries the user sees is customized
              1: {sampler: "Validation", query: [0, 2, 3]}
              10: {sampler: "valid2"}

          html:
            # ask 10 queries according to "sampling.probs".
            # The probabilistic sampling will be overriden by sampling.details
            max_queries: 10

        In this case, the crowdsourcing user will see the following:

        * 1st query shown will have head "zero", and feet "two" and "three".
        * Queries 2 and 9 will be generated by the :class:`~salmon.triplets.samplers.ARR` sampler.
        * The 10th query they see (also the last query): one of three
          (random) fixed/static queries.

        The sampler ``valid2`` will receive answers to 3 fixed/static queries,
        and the ``Validation`` sampler will receive answers to the query
        ``[0, 2, 3]``.
        """,
    )


class HTML(BaseSettings):
    """
    Stylistic settings to configure the HTML page.

    The default configuration is specified completely below, which is rendered into a YAML file in `an example`_.

    .. _an example: https://github.com/stsievert/salmon/blob/master/examples/default.yaml

    Arbitrary keys are allowed in this class
    (which might allow for customization on the HTML page).

    """

    class Config:
        extra = "allow"

    title: str = Field(
        "Similarity judgements",
        description="The title of the HTML page (the text shown in the tab bar)",
    )
    instructions: str = Field(
        "Please select the <i>comparison</i> item that is most similar to the <i>target</i> item.",
        description="The instructions the user sees above each query.",
    )
    debrief: str = Field(
        "<b>Thanks!</b> Please use the participant ID below.",
        description=dedent(
            """The message that the user sees after ``max_queries`` responses
            have been completed. The participant ID (``puid``) is shown below
            this message."""
        ),
    )
    skip_button: bool = Field(
        False,
        description="""Wheter to show a button to skip queries. Most
        useful when participants are instructed to skip queries only when the
        know nothing about any object.""",
    )
    css: str = Field(
        "",
        description="""CSS to be included the in the query page.  This CSS is
        inserted just before the ``</style>`` tag in the HTML head.""",
    )
    max_queries: int = Field(
        50,
        description="""The number of queries that the user will answer before
        seeing the ``debrief`` message). Set ``max_queries=0`` or
        ``max_queries=-1`` to ask unlimited queries.""",
    )
    arrow_keys: bool = Field(
        True,
        description="""Wheter to allow using the arrow keys as input.  Specifying
        ``arrow_keys=True`` might allow bad input (though there is a delay of
        200ms between queries).""",
    )


class Config(BaseSettings):
    """
    Customization of Salmon sampling and HTML.

    This class is often specified through uploading an ``init.yaml`` file as
    described in :ref:`yamlinitialization`.

    The default configuration is specified completely below, which is rendered into a YAML file in `an example`_.

    .. _an example: https://github.com/stsievert/salmon/blob/master/examples/default.yaml

    Some details on specific fields:

    * The only required field is targets.

        * ``targets`` is often specified with the upload of a ZIP file. See
          :ref:`yaml_plus_zip` for more detail. If not, specify a list of strings (which
          will be rendered as HTML).

    * ``sampling`` is not relevant until ``samplers`` is customized.

    Here's how to customize the config a bit with
    a YAML file:

    .. code-block:: yaml

       samplers:
         testing: {class: Random}
         ARR: {}
         Validation:
           n_queries: 20
       sampling:
         probs: {"ARR": 40, "Validation": 20, "testing": 20}
         common:
           d: 3  # dimensions to embed to; passed to every sampler
           random_state: 42  # argument to Adaptive
           initial_batch_size: 128  # argument to Embedding
       html:
         instructions: Click buttons, <b><i>or else.</i></b>

    Full documentation is below.

    .. note::

       ``sampler_per_user`` and ``detail`` only affect the HTML page
       shown to the user. They do not affect the backend code executed.
       They are not grouped with :class:`~salmon.triplets.manager.HTML`
       because they do affect the responses (at least when using
       Salmon's default config and not writing a custom query page).

    """

    targets: Optional[Union[int, List[str]]] = Field(
        None,
        description="""A list of targets that will be rendered as HTML. If a ZIP file is
            uploaded, this field is populated automatically.
            See :ref:`yaml_plus_zip` for more detail.""",
    )
    html: HTML = Field(
        HTML(),
        description="""Stylistic settings to configure the HTML page.
            See :class:`~salmon.triplets.manager.HTML` for more detail.""",
    )
    samplers: dict = Field(
        {"random": {"class": "Random"}},
        description="""Samplers to use, and their initialization parameters. See
            above or ":ref:`adaptive-config`" for more detail on
            customization, and :ref:`experiments` for experiments/benchmarks.""",
    )
    sampling: Sampling = Field(
        Sampling(),
        description="""Settings to configure how more than two samplers are
        used. See :class:`~salmon.triplets.manager.Sampling` for more detail.""",
    )

    def parse(self, user_config):
        self._update(user_config)
        self = self.parse_obj(user_config)
        self._validate()
        return self

    def _update(self, user_config):
        # Update user_config so when updated below, changes reflected.
        # (it's a plain dict, so it needs some help)
        if "sampling" in user_config and "common" in user_config["sampling"]:
            default_common = self.dict()["sampling"]["common"]
            default_common.update(user_config["sampling"]["common"])
            user_config["sampling"]["common"] = default_common

        self._warn(user_config)

    def _validate(self):
        if self.sampling.probs is None:
            # Sample each sampler equally
            n = len(self.samplers)
            freqs = [100 // n,] * n
            freqs[0] += 100 % n  # because integer division might be off by one
            sampling_percent = {k: f for k, f in zip(self.samplers, freqs)}
            self.sampling.probs = sampling_percent

        if set(self.sampling.probs.keys()) != set(self.samplers.keys()):
            sf = set(self.sampling.probs)
            s = set(self.samplers)
            msg = (
                "sampling.probs keys={} are not the same as samplers keys={}.\n\n"
                "Keys in sampling.probs but not in samplers: {}\n"
                "Keys in samplers but but in sampling.probs: {}\n\n"
            )
            raise ValueError(msg.format(sf, s, sf - s, s - sf))

        if (v := self.sampling.samplers_per_user) not in {0, 1}:
            raise NotImplementedError(
                "Only samplers_per_user in {0, 1} is implemented, not "
                f"samplers_per_user={v}"
            )

        if sum(self.sampling.probs.values()) != 100:
            msg = (
                "The values in sampling.probs should add up to 100; however, "
                "the passed sampling.probs={} adds up to {}"
            )
            s2 = self.sampling.probs
            raise ValueError(msg.format(s2, sum(s2.values())))

        if len(self.sampling.details):
            details = self.sampling.details
            if not all("sampler" in v for v in details.values()):
                bad_items = [v for v in details.items() if "sampler" not in v]
                msg = (
                    "Specify the key `sampler` for each element of "
                    "`sampling.details`. Received items {} without a key "
                    "'sampler'"
                )
                raise ValueError(msg.format(bad_items))
            details_samplers = set([v["sampler"] for v in details.values()])
            samplers = set(self.samplers.keys())
            if not details_samplers.issubset(samplers):
                msg = (
                    "Each sampler specified in sampling.details must be "
                    "created in samplers. In sampling.details, received  "
                    "key(s) {} which is not a subset of the samplers={}"
                )
                raise ValueError(msg.format(details_samplers, samplers))
            if any(not isinstance(d.get("query", []), list) for d in details.values()):
                bad_queries = {k: q.get("query", []) for k, q in details.items()}
                bad_queries = {
                    k: v for k, v in bad_queries.items() if not isinstance(v, list)
                }
                msg = (
                    "Not all `query` keys in sampling.details are lists. "
                    "Bad elements are {} "
                    "(show with {{num_queries_shown: supplied_query}}"
                )
                raise ValueError(msg.format(bad_queries))
            lengths = {len(d.get("query", [1, 2, 3])) for d in details.values()}
            if lengths != {3}:
                bad_queries = {k: q.get("query", [1, 2, 3]) for k, q in details.items()}
                bad_queries = {k: v for k, v in bad_queries.items() if len(v) != 3}
                msg = (
                    "Not all `query` keys in sampling.details have length 3. "
                    "Bad elements are {} "
                    "(show with {{num_queries_shown: supplied_query}}"
                )
                raise ValueError(msg.format(bad_queries))
            queries = {k: d.get("query", []) for k, d in details.items()}
            logger.warning("targets = %s", self.targets)
            n_targets = -1 + (
                len(self.targets) if isinstance(self.targets, list) else self.targets
            )
            bad_queries = {
                k: q
                for k, q in queries.items()
                if not (0 <= min(q) <= max(q) <= n_targets)
            }
            if len(bad_queries):
                msg = (
                    "Some target indices in the for sampling.details."
                    "query are too large. Shown in the form of"
                    "{{num_queries_shown: supplied_query}}, they are {}. "
                    "\n\n(reminder: here, Salmon/Python uses 0-based indexing, not 1-based indexing)"
                )
                raise ValueError(msg.format(bad_queries))

    def _warn(self, config):
        # TODO: deprecate
        html = self.html.dict()
        if any(h in config for h in html.keys()):
            misplaced_keys = [h for h in config if h in html]
            misplaced = [f"{h}: {config[h]}" for h in misplaced_keys]
            fmt_misplace = "\n  ".join(list(sorted(misplaced)))
            msg = (
                f"Move keys {misplaced_keys} into the `html` key. That is, include "
                f"this block of YAML:\n\nhtml:\n  {fmt_misplace}\n"
            )
            raise ValueError(msg)

        if "RandomSampling" in config.get("samplers", ""):
            raise ValueError(
                "The sampler `RandomSampling` has been renamed to `Random`."
            )


def deserialize_query(serialized_query: str) -> Dict[str, int]:
    h, l, r = serialized_query.split("-")
    flip = random.choice([True, False])
    if flip:
        l, r = r, l
    return {
        "head": int(h),
        "left": int(l),
        "right": int(r),
    }


def get_responses(answers: List[Dict[str, Any]], targets, start_time=0):
    start = start_time
    out = []
    for datum in answers:
        out.append(datum)
        datetime_received = timedelta(seconds=datum["time_received"]) + datetime(
            1970, 1, 1
        )
        idxs = {
            key + "_html": targets[datum[key]]
            for key in ["left", "right", "head", "winner", "loser"]
        }
        names = {
            key + "_filename": _get_filename(idxs[f"{key}_html"])
            for key in ["left", "right", "head", "winner", "loser"]
        }
        meta = {
            "time_received_since_start": datum["time_received"] - start,
            "datetime_received": datetime_received.isoformat(),
            "start_time": start_time,
        }
        out[-1].update({**idxs, **names, **meta})
    return out


def random_query(n: int) -> Dict[str, int]:
    rng = np.random.RandomState()
    a, b, c = rng.choice(n, size=3, replace=False)
    return {"head": int(a), "left": int(b), "right": int(c)}


def _get_filename(html):
    html = str(html)
    if "<img" in html or "<video" in html:
        i = html.find("src=")
        j = html[i:].find(" ")
        return html[i + 5 : i + j - 1].replace("/static/targets/", "")
    return html
