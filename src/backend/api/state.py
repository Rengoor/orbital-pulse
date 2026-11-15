"""What the app loads once at startup and every route shares.

Owner: person A
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from fastapi import Request

from backend.downlink.queue import DownlinkQueue, PersistentDownlinkQueue
from backend.orchestrator import load_rules
from backend.pipelines.a_statistical.baseline import compute_baseline
from backend.records.handoff import link_for, load_autonomy_policy
from backend.records.signing import require_signing_key
from backend.records.store import RecordStore

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_BASELINES_PATH = (
    _REPO_ROOT / "data" / "nasa" / "osdr_inspiration4" / "processed" / "baselines.json"
)


def load_all_baselines(draws_path: str | os.PathLike | None = None) -> dict:
    """``{astronaut_id: {channel: BaselineStats}}`` from a pre-flight draws file.

    The file maps astronaut id to ``{channel: [draws]}``. Path comes from the
    argument, then ``BASELINES_PATH``, then the processed Inspiration4 file.
    Returns ``{}`` when no file exists yet: pipeline A then skips CUSUM for
    channels without a baseline instead of guessing one.
    """
    path = Path(draws_path or os.environ.get("BASELINES_PATH") or _DEFAULT_BASELINES_PATH)
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        draws = json.load(f)
    return {
        astronaut_id: {
            channel: compute_baseline(values, channel=channel)
            for channel, values in channels.items()
            if values
        }
        for astronaut_id, channels in draws.items()
    }


@dataclass
class AppState:
    rules: dict
    baselines: dict
    policy_actions: list[str]
    signing_key: str = ""
    store: RecordStore = field(default_factory=RecordStore)
    queue: DownlinkQueue = field(default_factory=DownlinkQueue)
    # Delay-aware autonomy: the autonomy policy and the current link to Earth.
    autonomy_policy: dict = field(default_factory=dict)
    autonomy_hash: str = ""
    link: dict = field(default_factory=lambda: link_for("moon"))

    @classmethod
    def load(cls) -> "AppState":
        signing_key = require_signing_key()
        rules = load_rules()
        # Fails loudly if policy.yaml is missing or unreadable: the app must
        # not serve requests without a valid policy.
        with open(rules["policy_path"], encoding="utf-8") as f:
            policy = yaml.safe_load(f)
        if not isinstance(policy, dict) or not policy.get("actions"):
            raise RuntimeError(f"{rules['policy_path']} has no 'actions' whitelist")
        store = RecordStore(os.environ.get("RECORDS_PATH") or None)
        autonomy_policy, autonomy_hash = load_autonomy_policy()
        # LINK_PRESET (leo, moon, mars_near, mars_far) or LINK_ONE_WAY_S picks the
        # starting link; POST /link changes it while running.
        custom = os.environ.get("LINK_ONE_WAY_S")
        link = (link_for(one_way_delay_s=float(custom)) if custom
                else link_for(os.environ.get("LINK_PRESET") or autonomy_policy.get("default_link", "moon")))
        return cls(
            autonomy_policy=autonomy_policy,
            autonomy_hash=autonomy_hash,
            link=link,
            rules=rules,
            baselines=load_all_baselines(),
            policy_actions=list(policy["actions"]),
            signing_key=signing_key,
            store=store,
            # Writes through to the store, so with RECORDS_PATH set a restart
            # no longer drops queued (possibly urgent) downlink summaries.
            queue=PersistentDownlinkQueue(store),
        )


def get_state(request: Request) -> AppState:
    return request.app.state.ctx
