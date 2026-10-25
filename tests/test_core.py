from gh_issue_lens.core import command_signature


def test_command_signature_is_stable():
    inputs = {"labels": ["bug"], "depth": 100, "exclude_open_prs": False}

    assert command_signature(inputs) == command_signature(inputs)


def test_command_signature_changes_when_options_change():
    base = {"labels": ["bug"], "depth": 100, "exclude_open_prs": False}
    changed = {"labels": ["bug"], "depth": 100, "exclude_open_prs": True}

    assert command_signature(base) != command_signature(changed)


def test_command_signature_ignores_key_order():
    a = {"depth": 100, "labels": ["bug"]}
    b = {"labels": ["bug"], "depth": 100}

    assert command_signature(a) == command_signature(b)
