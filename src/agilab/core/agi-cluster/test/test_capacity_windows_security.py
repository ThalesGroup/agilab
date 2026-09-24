"""Cross-platform tests of the pywin32 capacity-model trust boundary."""
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from agi_cluster.agi_distributor.runtime import runtime_misc_support as runtime


@pytest.fixture
def windows_security(monkeypatch):
    token = SimpleNamespace(Close=Mock())
    descriptor = SimpleNamespace(GetSecurityDescriptorOwner=Mock(return_value="owner"))
    security = SimpleNamespace(
        OWNER_SECURITY_INFORMATION=1, DACL_SECURITY_INFORMATION=4, TokenUser=1, TokenOwner=4,
        GetFileSecurity=Mock(return_value=descriptor), OpenProcessToken=Mock(return_value=token),
        GetTokenInformation=Mock(side_effect=[("owner", 0), "default"]),
        ConvertSidToStringSid=Mock(side_effect=lambda sid: "S-" + sid),
        LookupAccountSid=Mock(return_value=("name", "domain", 1)),
    )
    monkeypatch.setitem(sys.modules, "win32security", security)
    monkeypatch.setitem(sys.modules, "win32api", SimpleNamespace(GetCurrentProcess=lambda: 123))
    monkeypatch.setitem(sys.modules, "win32con", SimpleNamespace(TOKEN_QUERY=8))
    return security, descriptor, token


@pytest.mark.parametrize("default_owner", ["default", ("default", 0), "owner"])
@pytest.mark.parametrize("domain", ["domain", ""])
def test_windows_owner_sid_and_token_owner_normalization(windows_security, default_owner, domain):
    security, _, token = windows_security
    security.GetTokenInformation.side_effect = [("owner", 0), default_owner]
    security.LookupAccountSid.return_value = ("name", domain, 1)
    expected = ("S-owner",) if default_owner == "owner" else ("S-owner", "S-default")
    assert runtime._windows_capacity_model_identities(Path("model.pkl")) == (
        "S-owner", expected, "domain\\name" if domain else "name")
    token.Close.assert_called_once_with()


def test_windows_label_failure_does_not_change_sid_authority(windows_security):
    security, _, token = windows_security
    security.LookupAccountSid.side_effect = OSError("account unavailable")
    assert runtime._windows_capacity_model_identities(Path("model.pkl")) == ("S-owner", ("S-owner", "S-default"), None)
    token.Close.assert_called_once_with()


def test_windows_missing_owner_rejects_before_opening_token(windows_security):
    security, descriptor, token = windows_security
    descriptor.GetSecurityDescriptorOwner.return_value = None
    with pytest.raises(OSError, match="no owner SID"):
        runtime._windows_capacity_model_identities(Path("model.pkl"))
    security.OpenProcessToken.assert_not_called()
    token.Close.assert_not_called()


def test_windows_conversion_failure_always_closes_token(windows_security):
    security, _, token = windows_security
    security.ConvertSidToStringSid.side_effect = OSError("invalid SID")
    with pytest.raises(OSError, match="invalid SID"):
        runtime._windows_capacity_model_identities(Path("model.pkl"))
    token.Close.assert_called_once_with()


@pytest.mark.parametrize("helper", ["_windows_capacity_model_identities", "_windows_capacity_model_dacl_grants"])
def test_missing_pywin32_is_explicit(monkeypatch, helper):
    monkeypatch.setitem(sys.modules, "win32security", None)
    with pytest.raises(RuntimeError, match="pywin32 is required"):
        getattr(runtime, helper)(Path("model.pkl"))


def install_dacl(descriptor, entries, *, valid=True):
    dacl = SimpleNamespace(IsValid=lambda: valid, GetAceCount=lambda: len(entries),
                           GetAce=lambda index: entries[index])
    descriptor.GetSecurityDescriptorDacl = lambda: dacl


def test_windows_dacl_normalizes_standard_and_object_grants(windows_security):
    _, descriptor, _ = windows_security
    install_dacl(descriptor, [((0, 0), 2, "owner"), ((5, 0), 4, None, None, "other"), ((1, 0), 2, "denied")])
    assert runtime._windows_capacity_model_dacl_grants(Path("model.pkl")) == (("S-owner", 2), ("S-other", 4))


@pytest.mark.parametrize("entry,match", [
    (None, "unsupported shape"), ((), "unsupported shape"), (([], 2, "x"), "unsupported header"),
    (((), 2, "x"), "unsupported header"), (((5, 0), 2, "x"), "object ACE"),
    (((4, 0), 2, "x"), "type 4"), (((9, 0), 2, "x"), "type 9"), (((11, 0), 2, "x"), "type 11"),
])
def test_windows_dacl_rejects_unsupported_allow_semantics(windows_security, entry, match):
    _, descriptor, _ = windows_security
    install_dacl(descriptor, [entry])
    with pytest.raises(OSError, match=match):
        runtime._windows_capacity_model_dacl_grants(Path("model.pkl"))


@pytest.mark.parametrize("null", [True, False])
def test_windows_dacl_requires_valid_non_null_acl(windows_security, null):
    _, descriptor, _ = windows_security
    install_dacl(descriptor, [], valid=False)
    if null:
        descriptor.GetSecurityDescriptorDacl = lambda: None
    with pytest.raises(OSError, match="null DACL" if null else "invalid DACL"):
        runtime._windows_capacity_model_dacl_grants(Path("model.pkl"))


@pytest.mark.parametrize("grant", [(None, 2), ("S-owner", "2")])
def test_malformed_acl_provider_grants_fail_closed(grant):
    error = runtime._windows_capacity_model_dacl_error(Path("model.pkl"), trusted_sids=("S-owner",),
                                                     grants_fn=lambda _: (grant,))
    assert "cannot verify model file ACL" in error
    assert "invalid SID or access mask" in error


@pytest.mark.parametrize("mask", [2, 4, 16, 64, 256, 65536, 262144, 524288, 33554432, 268435456, 1073741824])
def test_each_write_equivalent_permission_rejects_untrusted_principal(mask):
    error = runtime._windows_capacity_model_dacl_error(Path("model.pkl"), trusted_sids=("S-owner",),
                                                     grants_fn=lambda _: (("S-untrusted", mask),))
    assert "unsafe write/delete access" in error


@pytest.mark.parametrize("trustee", ["S-owner", "s-OWNER", "S-1-5-18", "S-1-5-32-544"])
def test_privileged_and_token_principals_are_trusted(trustee):
    assert runtime._windows_capacity_model_dacl_error(
        Path("model.pkl"), trusted_sids=("S-owner",),
        grants_fn=lambda _: ((trustee, 0x10000000), ("S-other", 1))) is None


@pytest.mark.parametrize("owner,trusted,label,match", [
    ("", ("S-owner",), None, "owner SID is missing"),
    ("S-owner", (), None, "owner SID is missing"),
    ("S-other", ("S-owner",), "Other User", "owned by Other User"),
    ("S-other", ("S-owner",), None, "owned by S-other"),
])
def test_owner_failure_never_evaluates_dacl(owner, trusted, label, match):
    grants = Mock()
    error = runtime._windows_capacity_model_owner_error(Path("model.pkl"),
        identities_fn=lambda _: (owner, trusted, label), acl_grants_fn=grants)
    assert match in error
    grants.assert_not_called()


def test_owner_rights_sid_is_accepted_only_after_owner_verified():
    assert runtime._windows_capacity_model_owner_error(
        Path("model.pkl"), identities_fn=lambda _: ("S-owner", ("s-OWNER",), None),
        acl_grants_fn=lambda _: (("S-1-3-4", 2),)) is None
