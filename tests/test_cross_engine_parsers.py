"""Reject falsely comparable external results, including zero-exit failures."""
import pytest

from examples.cross_engine_matcalc import classify
from examples.cross_engine_opencalphad import parse_output
from examples.cross_engine_thermocalc import parse_output as parse_tc
from examples.cross_engine_thermocalc import macro_for
from examples.cross_engine_thermocalc import audit_import


VALID = """Equilibrium result: 10 its, GS= -100 J/mol
FCC4.................... E  1.000E+00  0.00E+00  1.00E+00
Constitution: Sublattice 1 with 2 constituents and 0.500000 sites
 AL 2.00000E-01 NI 8.00000E-01
              Sublattice 2 with 2 constituents and 0.500000 sites
 NI 6.00000E-01 AL 4.00000E-01
--->OC6: GM= -1.0000000E+02
 X(FCC4,AL)= 3.0000000E-01
 X(FCC4,NI)= 7.0000000E-01
"""


def parse(text):
    return parse_output(text, "FCC4", {"AL": .3, "NI": .7})


def test_oc_single_homogeneous_state():
    result = parse(VALID)
    assert result["comparable"]
    assert result["G"] == -100
    assert result["site_fractions_printed_precision"]["Y_1_AL"] == .4


@pytest.mark.parametrize("text", [
    VALID.replace("Equilibrium result:", "No equilibrium:"),
    VALID+"FCC4_AUTO#2........ E  1.000E-01\n",
    VALID.replace("GM= -1.0000000E+02", "GM= NaN"),
    VALID.replace("X(FCC4,AL)= 3.0000000E-01", "X(FCC4,AL)= 4.0000000E-01"),
    VALID.replace("AL 4.00000E-01", "AL 5.00000E-01"),
])
def test_oc_excludes_invalid_or_split_results(text):
    assert not parse(text)["comparable"]


@pytest.mark.parametrize("log,expected", [
    ("Type definition ignored !!!", "incompatible_order_disorder_syntax"),
    ("cannot attach disordered part", "incompatible_order_disorder_syntax"),
    ("*** error *** unknown keyword", "unsupported_database_keyword"),
    ("*** Error ***: maximum number of iterations reached", "calculation_failed"),
])
def test_matcalc_zero_returncode_does_not_hide_model_or_solver_failure(log, expected):
    assert classify({"status": "commands_completed"}, log, 0) == expected


def test_matcalc_import_success_alone_not_comparison_pass():
    assert classify({"status": "commands_completed"}, "OK", 0) == "requires_model_and_homogeneity_audit"


TC_SEED = {"Y_0_AL": .3, "Y_0_NI": .7, "Y_1_VA": 1.}
TC_VALID = """set_start_constitution FCC4 NONE
Y(FCC4_A1,AL) /1/:
0.3
Y(FCC4_A1,NI) /1/:
0.7
compute_equilibrium -
26 ITS,  CPU TIME USED   0 SECONDS
GM=-60351.514
NP(FCC4_FP)=1.
X(FCC4_FP,AL)=0.3, X(FCC4_FP,NI)=0.7
Y(FCC4_FP,AL)=0.3, Y(FCC4_FP,NI)=0.7, Y(FCC4_FP,VA#2)=1
"""


def test_tc_known_order_alias_and_implicit_pure_vacancy():
    result = parse_tc(TC_VALID, 'FCC4', {'AL': .3, 'NI': .7}, TC_SEED)
    assert result['comparable']
    assert result['input_site_fractions_verified']
    assert result['G'] == -60351.514


@pytest.mark.parametrize('text', [
    TC_VALID.replace('26 ITS,', 'Failed,'),
    TC_VALID.replace('GM=-60351.514', 'GM=NaN'),
    TC_VALID+'\nNP(FCC4_FP#2)=0.2\n',
    TC_VALID+'\nNo such command: 1\n',
    TC_VALID.replace('X(FCC4_FP,AL)=0.3', 'X(FCC4_FP,AL)=0.4'),
    TC_VALID.replace('Y(FCC4_FP,NI)=0.7', 'Y(FCC4_FP,NI)=0.8'),
    TC_VALID.replace(' /1/:\n0.3', ' /1/:\n0.4'),
    TC_VALID.replace('FCC4_FP', 'ANOTHER_PHASE'),
    TC_VALID.replace('26 ITS,  CPU TIME USED   0 SECONDS', '*** ERROR ***'),
])
def test_tc_rejects_stale_split_wrong_or_unconverged_results(text):
    assert not parse_tc(text, 'FCC4', {'AL': .3, 'NI': .7}, TC_SEED)['comparable']


def test_tc_macro_omits_pure_site_input():
    macro = macro_for({'phase': 'FCC4', 'composition': {'AL': .3, 'NI': .7},
                       'T_K': 300, 'P_Pa': 101325}, [{'site_fractions': TC_SEED}])
    assert 'NONE\n0.3\n0.7\ncompute_equilibrium -' in macro


def test_tc_import_audit_does_not_ignore_arbitrary_reader_errors():
    assert audit_import('-OK-')['accepted_for_comparison']
    assert audit_import('*** ERROR  1000 IN TDBGRT: NO REFERENCE FILE\n-OK-')['accepted_for_comparison']
    assert not audit_import('*** ERROR: unknown parameter\n-OK-')['accepted_for_comparison']
    assert not audit_import('Reading file')['accepted_for_comparison']
