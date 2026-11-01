from __future__ import annotations

import pytest
from pydantic import ValidationError

from trace_to_golden.config import Settings, check_env_vars


def test_misspelled_variable_names_the_closest_field(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TTG_MIN_CLUSTER_SIZ", "5")
    with pytest.raises(
        ValidationError, match=r"TTG_MIN_CLUSTER_SIZ \(did you mean TTG_MIN_CLUSTER_SIZE\?\)"
    ):
        Settings()


def test_known_variables_and_other_prefixes_pass():
    check_env_vars({"TTG_DB_PATH": "x.db", "ttg_redactor": "regex", "OTHER_DB_PTH": "y"})


def test_unknown_variable_without_close_match():
    with pytest.raises(ValueError, match=r"variables: TTG_ZZZ\. Valid names"):
        check_env_vars({"TTG_ZZZ": "1"})
